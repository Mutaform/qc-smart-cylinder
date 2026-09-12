# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# ##### END GPL LICENSE BLOCK #####
"""Rebuilding the cylindrical forms of existing meshes with the right segment counts.

The pure ``core.topology`` module finds the forms, ``core.geometry`` fits
their rings and ``core.sections`` decides the count of every ring; this
module does the Blender side: reading the mesh (undoing a triangulation
first), measuring diameters in world space, and swapping the old geometry for
the new one in a BMesh while carrying materials, smoothing, sharp edges,
seams and the UV layout over. Rings of different counts are joined by
triangle bridges.
"""

import math

import bmesh
from mathutils import Vector

from ..core import geometry, sections, topology
from ..core.units import to_centimetres
from . import uv_transfer

# Sections with this many vertices or fewer are ambiguous (a square tube or a
# very coarse cylinder?) and are left alone unless a manual count is given.
AMBIGUOUS_SEGMENTS = 4

_JOIN_FACE_ANGLE = math.radians(40.0)
_JOIN_SHAPE_ANGLE = math.radians(60.0)
_COPLANAR_COS = math.cos(math.radians(1.0))
_CAP_MAX_TURN = 72.0  # degrees: a cap outline never bends more than this at one vertex
_WELD_DIGITS = 5
TWO_PI = 2.0 * math.pi


class FormResult:
    """What happened to one cylindrical form."""

    __slots__ = ("object_name", "index", "old_counts", "new_counts", "diameters_cm", "status", "note")

    def __init__(self, object_name, index, old_counts, new_counts, diameters_cm, status, note=""):
        self.object_name = object_name
        self.index = index
        self.old_counts = list(old_counts)
        self.new_counts = list(new_counts)
        self.diameters_cm = list(diameters_cm)
        self.status = status  # 'FIXED', 'UNCHANGED' or 'SKIPPED'
        self.note = note

    @property
    def old_segments(self):
        return max(self.old_counts) if self.old_counts else 0

    @property
    def new_segments(self):
        return max(self.new_counts) if self.new_counts else 0

    def line(self):
        name = self.object_name if self.index == 0 else "%s #%d" % (self.object_name, self.index + 1)
        if self.status == 'FIXED':
            text = "%s: Ø %s, %s → %s" % (
                name, _fmt_diameters(self.diameters_cm), _fmt_counts(self.old_counts), _fmt_counts(self.new_counts))
        elif self.status == 'UNCHANGED':
            text = "%s: Ø %s, %s already right" % (name, _fmt_diameters(self.diameters_cm), _fmt_counts(self.old_counts))
        else:
            text = "%s: skipped" % name
        if self.note:
            text += " (%s)" % self.note
        return text


def _fmt_cm(value):
    return ("%.1f" % value) if value < 10 else ("%.0f" % value)


def _fmt_diameters(diameters):
    if not diameters:
        return "?"
    lo, hi = min(diameters), max(diameters)
    if hi - lo < 0.5:
        return _fmt_cm(hi) + " cm"
    return "%s–%s cm" % (_fmt_cm(lo), _fmt_cm(hi))


def _fmt_counts(counts):
    """Counts along the form with consecutive repeats collapsed: 36/66/36."""
    collapsed = []
    for count in counts:
        if not collapsed or collapsed[-1] != count:
            collapsed.append(count)
    return "/".join(str(c) for c in collapsed)


FIX_MODES = ('OBJECT', 'EDIT_MESH')


def target_objects(context):
    """Mesh objects to fix, one per mesh datablock: the selected ones, or the ones being edited."""
    pool = list(context.objects_in_mode if context.mode == 'EDIT_MESH' else context.selected_objects)
    active = context.view_layer.objects.active
    if active in pool:
        pool.remove(active)
        pool.insert(0, active)  # linked duplicates share one mesh: the active one sets the scale
    seen = set()
    targets = []
    for obj in pool:
        if obj.type != 'MESH' or obj.data in seen:
            continue
        seen.add(obj.data)
        targets.append(obj)
    return targets


def fix_intended(context):
    """True when a call from the menu means "fix this": mesh objects selected, or a mesh being edited."""
    return context.mode in FIX_MODES and bool(target_objects(context))


def has_targets(context):
    """True when the selection (or the edited mesh) holds at least one rebuildable cylindrical form."""
    if context.mode not in FIX_MODES:
        return False
    for obj in target_objects(context):
        if context.mode == 'EDIT_MESH':
            obj.update_from_editmode()
        analysis = _analyse(obj.data)
        found = bool(analysis.components)
        analysis.free()
        if found:
            return True
    return False


def selected_vertices(obj):
    """The vertex selection of a mesh as a set of indices, or None when it is empty or complete.

    Read in Object Mode (Edit Mode flushes its selection on leaving); a partial
    selection limits the fix to the forms it touches.
    """
    selected = {v.index for v in obj.data.vertices if v.select}
    if not selected or len(selected) == len(obj.data.vertices):
        return None
    return selected


def rebuild_object(obj, scene, rule, diameter_source='MAX', manual_segments=0,
                   count_mode='SECTIONS', section_step=0.25, only_vertices=None, select_new=False):
    """Rebuild every cylindrical form of ``obj`` under ``rule``; a FormResult per form.

    ``only_vertices`` (a set of vertex indices) limits the work to the forms that
    touch it -- the Edit Mode selection; the other forms are left out of the
    results as if they were not there. ``select_new`` selects the rebuilt
    geometry so it shows up selected back in Edit Mode.
    """
    mesh = obj.data
    if mesh.shape_keys is not None:
        return [FormResult(obj.name, 0, [], [], [], 'SKIPPED', "mesh has shape keys")]

    analysis = _analyse(mesh)
    components, notes, detached = analysis.components, analysis.notes, analysis.detached
    results = []
    if not components:
        analysis.free()
        return _note_results(obj.name, notes or ["no rings found"])

    source_uvs = uv_transfer.SourceUVs(mesh)
    original_quads = {frozenset(p.vertices) for p in mesh.polygons if len(p.vertices) == 4}
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    # Grab the old vertices of every form up front: adding vertices later
    # invalidates the lookup table, deleting keeps other references valid.
    old_vertices = {}
    for index, component in enumerate(components):
        indices = set(component.vertex_indices())
        for end in (0, 1):
            cap = detached.get((index, end))
            if cap is not None:
                indices.update(cap.vertices)
        old_vertices[index] = [bm.verts[i] for i in indices]
    edge_flags = _edge_flags(mesh)
    unit_settings = scene.unit_settings
    matrix = obj.matrix_world
    uv_layer = bm.loops.layers.uv.active
    changed = False
    existing = set(bm.verts) if select_new else None

    for index, component in enumerate(components):
        if only_vertices is not None and not (set(component.vertex_indices()) & only_vertices):
            continue
        coords, bm_analysis, analysis_faces = analysis.pass_of(index)
        old_counts = component.ring_lengths
        fits = [geometry.fit_ring([coords[i] for i in ring]) for ring in component.grid]
        world_fits = [
            geometry.fit_ring([tuple(matrix @ Vector(coords[i])) for i in ring]) for ring in component.grid
        ]
        diameters_cm = [
            to_centimetres(fit.minor_diameter, unit_settings.scale_length, unit_settings.system)
            for fit in world_fits
        ]

        if manual_segments:
            counts = [manual_segments] * len(old_counts)
        elif max(old_counts) <= AMBIGUOUS_SEGMENTS:
            results.append(FormResult(obj.name, index, old_counts, old_counts, diameters_cm, 'SKIPPED',
                                      "%d-gon section: square tube or cylinder? use a manual count" % max(old_counts)))
            continue
        elif count_mode == 'SECTIONS':
            # Bands of quads keep their quads when the counts on both sides are
            # close (whatever the finder called the band); a wedge elbow needs
            # one count on both of its rings.
            quad_bands = set()
            joined_bands = set()
            for j, kind in enumerate(component.band_kind):
                j1 = (j + 1) % component.ring_count
                if kind == "WEDGE":
                    joined_bands.add(j)
                if kind in ("QUAD", "WEDGE") or (
                        len(component.grid[j]) == len(component.grid[j1])
                        and all(len(analysis_faces[fi]) == 4 for fi in component.band_faces[j])):
                    quad_bands.add(j)
            counts = sections.section_counts(diameters_cm, rule, diameter_source, section_step,
                                             _flat_steps(fits), quad_bands, joined_bands=joined_bands,
                                             closed=component.closed)
        else:
            count = rule.segments(sections.pick_diameter(diameters_cm, diameter_source))
            counts = [count] * len(old_counts)
        if not manual_segments:
            # A square section inside a round form (a square peg on a round flange)
            # is a shape, not a segment count: it keeps its vertices.
            counts = [old if old <= AMBIGUOUS_SEGMENTS else new for old, new in zip(old_counts, counts)]
        if counts == old_counts:
            results.append(FormResult(obj.name, index, old_counts, counts, diameters_cm, 'UNCHANGED'))
            continue

        caps = {end: detached[(index, end)] for end in (0, 1) if (index, end) in detached}
        note = _rebuild_component(
            bm, bm_analysis, component, fits, coords, counts, edge_flags, uv_layer,
            source_uvs, caps, analysis_faces, original_quads)
        if not manual_segments and any(rule.is_capped(d) for d in diameters_cm):
            # A twenty-metre "cylinder" is nearly always a centimetre asset read as metres.
            capped = "capped at %d: check the object scale" % rule.max_segments
            note = (note + ", " + capped) if note else capped
        bmesh.ops.delete(bm, geom=old_vertices[index], context='VERTS')
        results.append(FormResult(obj.name, index, old_counts, counts, diameters_cm, 'FIXED', note))
        changed = True

    if changed:
        if select_new:
            for vert in bm.verts:
                if vert not in existing:
                    vert.select = True
            bm.select_flush(True)
        bm.to_mesh(mesh)
        mesh.update()
    bm.free()
    analysis.free()
    if only_vertices is None or not results:
        results.extend(_note_results(obj.name, notes))
    return results


def _flat_steps(fits):
    """Rings that start a new section because the band before them is a flat ledge.

    Two rings of different radius sitting at (nearly) the same height along the
    axis are two parts, a wider and a narrower one, however small the change:
    a step between stacked cylinders, a flange. A sloping band (rings apart
    along the axis) is left to the drift rule.
    """
    breaks = set()
    for j in range(1, len(fits)):
        before, ring = fits[j - 1], fits[j]
        radial = abs(max(before.a, before.b) - max(ring.a, ring.b))
        if radial <= 0.02 * max(before.a, before.b, ring.a, ring.b, 1e-9):
            continue
        axial = abs(geometry.dot(geometry.sub(ring.center, before.center), before.normal))
        if axial < 0.5 * radial:
            breaks.add(j)
    return breaks


def _note_results(object_name, notes):
    """One SKIPPED line per reason (an imported asset can have dozens of rejected grids)."""
    reasons = {}
    for note in notes:
        reasons[note] = reasons.get(note, 0) + 1
    return [
        FormResult(object_name, 0, [], [], [], 'SKIPPED', note if count == 1 else "%s ×%d" % (note, count))
        for note, count in reasons.items()
    ]


# --- analysis -------------------------------------------------------------

class DetachedCap:
    """A face island whose outline coincides with an open end ring (a curve fill cap)."""

    __slots__ = ("vertices", "material_index", "smooth", "normal", "polygons")

    def __init__(self, vertices, material_index, smooth, normal):
        self.vertices = vertices
        self.material_index = material_index
        self.smooth = smooth
        self.normal = normal
        self.polygons = []


class Analysis:
    """Everything the topology search found in one mesh.

    The search runs on the raw mesh first, so bridges of triangles between
    sections are read as they are; a second run on a copy with the
    triangulation undone picks up forms the first one could not see (a
    triangulated cylinder). Each component remembers which run it came from,
    because face indices refer to that run's BMesh.
    """

    __slots__ = ("components", "notes", "detached", "passes", "source")

    def __init__(self):
        self.components = []
        self.notes = []
        self.detached = {}
        self.passes = []   # (coords, bmesh, faces) per run
        self.source = []   # per component: index into passes

    def pass_of(self, index):
        return self.passes[self.source[index]]

    def free(self):
        for _coords, bm, _faces in self.passes:
            bm.free()
        self.passes = []


def _mesh_arrays(bm):
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.faces.index_update()
    coords = [tuple(v.co) for v in bm.verts]
    faces = [tuple(v.index for v in face.verts) for face in bm.faces]
    loose = [(e.verts[0].index, e.verts[1].index) for e in bm.edges if not e.link_faces]
    return coords, faces, loose


def _analyse(mesh):
    """Run the topology search on copies of the mesh; the caller frees the result."""
    analysis = Analysis()
    raw = bmesh.new()
    raw.from_mesh(mesh)
    coords, faces, loose = _mesh_arrays(raw)
    components, notes = topology.find_components(coords, faces, loose)
    analysis.passes.append((coords, raw, faces))
    analysis.components.extend(components)
    analysis.source.extend([0] * len(components))
    analysis.notes = list(notes)

    # A second run on a copy with caps dissolved and triangles joined: needed
    # for triangulated meshes, and for quad meshes whose caps are filled with
    # a ladder of quads (a planar disc the loop walk reads as a broken grid).
    if any(len(face) == 3 for face in faces) or not _everything_covered(analysis, faces):
        owned = set()
        for component in components:
            owned.update(component.vertex_indices())
        joined = bmesh.new()
        joined.from_mesh(mesh)
        _undo_triangulation(joined)
        coords2, faces2, loose2 = _mesh_arrays(joined)
        components2, notes2 = topology.find_components(coords2, faces2, loose2, excluded=owned)
        analysis.passes.append((coords2, joined, faces2))
        for component in components2:
            if component.vertex_indices() & owned:
                continue
            analysis.components.append(component)
            analysis.source.append(1)
        analysis.notes = list(notes2)

    if analysis.components:
        analysis.detached = _detached_caps(raw, analysis.components, coords, analysis.notes)
    if _everything_covered(analysis, faces):
        # The second run reads the joined triangles of the forms the first run
        # found as broken grids; those complaints are about nothing.
        analysis.notes = []
    return analysis


def _everything_covered(analysis, faces):
    """True when every face of the mesh belongs to a form (rings, fan centres, welded caps)."""
    owned = set()
    for component in analysis.components:
        owned.update(component.vertex_indices())
        for cap in component.caps:
            if cap is not None and cap[0] == "FAN":
                owned.add(cap[1])
    for cap in analysis.detached.values():
        owned.update(cap.vertices)
    return all(all(v in owned for v in face) for face in faces)


def _undo_triangulation(bm):
    """Dissolve triangulated caps, join the triangle pairs of bands.

    A cap is a planar disc with no interior vertex whose outline bends gently
    at every vertex (at most 72 degrees, i.e. a polygon of five sides or
    more). A coplanar column of band quads, or the two triangles of one flat
    quad, has right-angled corners and is left to join_triangles; a fan
    around a centre vertex has an interior vertex and is kept away from
    join_triangles altogether so fan caps survive. Bridge triangles between
    rings of different counts are usually not coplanar pairs and stay as
    they are; a flat step between two rings (a planar annulus) is coplanar
    throughout, so it is kept as triangles on purpose -- unless its two
    outlines are concentric rings of one count, which is a flange, a band
    of the grid, and gets its quads back.
    """
    bm.normal_update()
    protected = set()
    discs = []
    for faces, interior, loops, max_turn, chains in _planar_patches(bm):
        if len(faces) < 2:
            continue
        if interior:
            protected.update(faces)
        elif loops == 1 and max_turn <= _CAP_MAX_TURN:
            discs.append(faces)
        elif loops >= 2 and not _concentric_band(chains):
            protected.update(faces)
    for faces in discs:
        bmesh.ops.dissolve_faces(bm, faces=faces, use_verts=False)
    triangles = [face for face in bm.faces if len(face.verts) == 3 and face not in protected]
    if triangles:
        bmesh.ops.join_triangles(
            bm, faces=triangles,
            angle_face_threshold=_JOIN_FACE_ANGLE, angle_shape_threshold=_JOIN_SHAPE_ANGLE)


def _planar_patches(bm):
    """Connected sets of coplanar faces.

    Yields (faces, has interior vertex, boundary loop count, sharpest turn of
    the outline in degrees).
    """
    visited = set()
    patches = []
    for seed in bm.faces:
        if seed in visited or seed.normal.length_squared < 0.5:
            continue
        patch = [seed]
        visited.add(seed)
        stack = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                if len(edge.link_faces) != 2:
                    continue
                other = edge.link_faces[0] if edge.link_faces[1] is face else edge.link_faces[1]
                if other in visited or other.normal.length_squared < 0.5:
                    continue
                if face.normal.dot(other.normal) >= _COPLANAR_COS:
                    visited.add(other)
                    patch.append(other)
                    stack.append(other)
        if len(patch) < 2:
            continue
        patch_set = set(patch)
        interior = False
        boundary = set()
        for face in patch:
            for vert in face.verts:
                if all(f in patch_set for f in vert.link_faces):
                    interior = True
            for edge in face.edges:
                if sum(1 for f in edge.link_faces if f in patch_set) == 1:
                    boundary.add(edge)
        loops, max_turn, chains = _boundary_shape(boundary)
        patches.append((patch, interior, loops, max_turn, chains))
    return patches


def _concentric_band(chains):
    """True for exactly two outlines of one vertex count around one centre: a flange between two rings."""
    if len(chains) != 2 or len(chains[0]) != len(chains[1]):
        return False
    centres = []
    radii = []
    for chain in chains:
        centre = sum((v.co for v in chain), Vector((0.0, 0.0, 0.0))) / len(chain)
        centres.append(centre)
        radii.append(sum((v.co - centre).length for v in chain) / len(chain))
    return (centres[0] - centres[1]).length <= 0.05 * max(radii)


def _boundary_shape(boundary):
    """(loop count, sharpest turn in degrees, loops as vertex chains) of a set of boundary edges;
    (0, 180, []) when they are not clean loops."""
    if not boundary:
        return 0, 180.0, []
    adjacency = {}
    for edge in boundary:
        a, b = edge.verts
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    if any(len(neighbours) != 2 for neighbours in adjacency.values()):
        return 0, 180.0, []
    visited = set()
    loops = 0
    max_turn = 0.0
    chains = []
    for start in adjacency:
        if start in visited:
            continue
        loops += 1
        chain = []
        chains.append(chain)
        previous, current = None, start
        while current not in visited:
            visited.add(current)
            chain.append(current)
            first, second = adjacency[current]
            previous, current = current, (second if first is previous else first)
        count = len(chain)
        for i in range(count):
            incoming = chain[i].co - chain[i - 1].co
            outgoing = chain[(i + 1) % count].co - chain[i].co
            if incoming.length_squared < 1e-18 or outgoing.length_squared < 1e-18:
                continue
            max_turn = max(max_turn, incoming.angle(outgoing))
    return loops, math.degrees(max_turn), chains


def _weld_key(co):
    return tuple(round(c, _WELD_DIGITS) for c in co)


def _detached_caps(bm, components, coords, notes=None):
    """Match face islands to open end rings whose vertices they duplicate.

    Curve-to-mesh conversion with filled caps makes exactly such islands: a
    disc of its own vertices sitting on the tube's end ring. The island must
    be that disc -- flat, in the ring's plane, inside the ring -- or it is
    some other part of the mesh with a hole where the tube meets it (a body
    with a spout) and must be left alone.
    """
    ends = {}
    fits = {}
    for index, component in enumerate(components):
        if component.closed:
            continue
        for end, j in ((0, 0), (1, component.ring_count - 1)):
            if component.caps[end] is None:
                key = frozenset(_weld_key(coords[i]) for i in component.grid[j])
                ends.setdefault(key, []).append((index, end))
                fits[key] = geometry.fit_ring([coords[i] for i in component.grid[j]])
    if not ends:
        return {}

    def is_flat_disc(island, key):
        fit = fits[key]
        centre, normal = Vector(fit.center), Vector(fit.normal)
        height = max(0.02 * fit.minor_diameter, 1e-5)
        reach = 1.05 * max(fit.a, fit.b) + 1e-5
        for face in island:
            for v in face.verts:
                offset = v.co - centre
                along = offset.dot(normal)
                if abs(along) > height or (offset - normal * along).length > reach:
                    return False
        return True
    owned = set()
    for component in components:
        owned.update(component.vertex_indices())

    result = {}
    visited = set()
    for seed in bm.faces:
        if seed in visited or any(v.index in owned for v in seed.verts):
            continue
        island = [seed]
        visited.add(seed)
        stack = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for other in edge.link_faces:
                    if other in visited or any(v.index in owned for v in other.verts):
                        continue
                    visited.add(other)
                    island.append(other)
                    stack.append(other)
        island_set = set(island)
        outline = set()
        for face in island:
            for edge in face.edges:
                if sum(1 for f in edge.link_faces if f in island_set) == 1:
                    outline.update(edge.verts)
        key = frozenset(_weld_key(v.co) for v in outline)
        targets = ends.get(key)
        if targets is None:
            continue
        if len(targets) > 1:
            # Two open ends at the very same place (a duplicate joined in place):
            # no way to tell whose cap this is, so nobody gets it.
            if notes is not None and "open ends coincide, caps left alone" not in notes:
                notes.append("open ends coincide, caps left alone")
            continue
        target = targets[0]
        if target in result:
            continue
        if not is_flat_disc(island, key):
            if notes is not None and "open end on other geometry, left open" not in notes:
                notes.append("open end on other geometry, left open")
            continue
        vertices = {v.index for face in island for v in face.verts}
        normal = Vector((0.0, 0.0, 0.0))
        for face in island:
            normal += face.normal
        cap = DetachedCap(vertices, island[0].material_index, island[0].smooth, normal)
        cap.polygons = [face.index for face in island]  # raw came straight from the mesh: same indices
        result[target] = cap
    return result


def _edge_flags(mesh):
    flags = {}
    for edge in mesh.edges:
        if edge.use_edge_sharp or edge.use_seam:
            a, b = edge.vertices
            flags[topology.edge_key(a, b)] = (edge.use_edge_sharp, edge.use_seam)
    return flags


def _was_triangulated(component, analysis_faces, original_quads):
    """True when the bands of the form were triangles in the original mesh.

    Quad bands count as triangulated when their quads were joined from
    triangle pairs; forms without quad bands (lathe parts with reduction
    bands) count as triangulated when nearly every band face is a triangle.
    """
    total = joined = 0
    for kind, row in zip(component.band_kind, component.band_faces):
        if kind != "QUAD":
            continue
        for fi in row:
            total += 1
            if frozenset(analysis_faces[fi]) not in original_quads:
                joined += 1
    if total > 0:
        return joined * 2 >= total
    faces = [fi for row in component.band_faces for fi in row]
    triangles = sum(1 for fi in faces if len(analysis_faces[fi]) == 3)
    return bool(faces) and triangles * 10 >= len(faces) * 9


# --- rebuild ----------------------------------------------------------------

def _start_angles(component, fits, coords, edge_flags, uv_seams, deltas):
    """Start angle of every new ring.

    Rings joined by quad bands (and wedges) form a run: the run's first ring
    starts at its seam rail (marked on the edges, or found in the UV layout)
    if it has one, else at vertex 0; the rest of the run follows through the
    rail deltas, so the rings stay rail-aligned. Later runs (across bridges)
    are aligned to the direction the first run started with.
    """
    grid = component.grid
    ring_count = component.ring_count
    angles = [fit.phase for fit in fits]
    runs = []
    current = [0]
    for j in range(ring_count - 1):
        if component.band_kind[j] in ("QUAD", "WEDGE"):
            current.append(j + 1)
        else:
            runs.append(current)
            current = [j + 1]
    runs.append(current)
    reference = None
    for run in runs:
        first = run[0]
        start = None
        for j in run[:-1]:
            if component.band_kind[j] != "QUAD":
                continue
            ring_a, ring_b = grid[j], grid[j + 1]
            for k in range(len(ring_a)):
                if edge_flags.get(topology.edge_key(ring_a[k], ring_b[k]), (False, False))[1]:
                    start = fits[j].angle_of(coords[ring_a[k]])
                    # carry the seam back to the first ring of the run
                    for back in range(j - 1, first - 1, -1):
                        start += deltas[back]
                    break
            if start is not None:
                break
        if start is None:
            for j in run:
                if uv_seams[j] is not None:
                    start = fits[j].angle_of(coords[grid[j][uv_seams[j]]])
                    for back in range(j - 1, first - 1, -1):
                        start += deltas[back]
                    break
        if start is None:
            if reference is None:
                start = fits[first].angle_of(coords[grid[first][0]])
            else:
                start = fits[first].angle_of(geometry.add(fits[first].center, reference))
        angles[first] = start
        for j in run[1:]:
            angles[j] = angles[j - 1] - deltas[j - 1]
        if reference is None:
            reference = geometry.sub(fits[first].point_at(angles[first]), fits[first].center)
    return angles


def _zipper(ring_a, ring_b, angles_a, angles_b, winding):
    """Triangles between two rings of different counts, walked by angle.

    ``angles_b`` are the angles of ring B expressed in ring A's frame.
    """
    base = angles_a[0]
    unwrapped_a = [base + ((a - base) % TWO_PI) for a in angles_a]
    order_b = sorted(range(len(ring_b)), key=lambda i: (angles_b[i] - base) % TWO_PI)
    unwrapped_b = [base + ((angles_b[i] - base) % TWO_PI) for i in order_b]
    na, nb = len(ring_a), len(ring_b)
    i = j = 0
    triangles = []
    while i < na or j < nb:
        next_a = unwrapped_a[i + 1] if i + 1 < na else unwrapped_a[0] + TWO_PI
        next_b = unwrapped_b[j + 1] if j + 1 < nb else unwrapped_b[0] + TWO_PI
        if j >= nb or (i < na and next_a <= next_b):
            tri = (ring_a[i % na], ring_a[(i + 1) % na], ring_b[order_b[j % nb]])
            i += 1
        else:
            tri = (ring_a[i % na], ring_b[order_b[(j + 1) % nb]], ring_b[order_b[j % nb]])
            j += 1
        triangles.append(tri if winding > 0 else tri[::-1])
    return triangles


def _rail_deltas(component, fits, coords):
    """Per band: angle offset from ring j+1's frame to ring j's frame, or None across a bridge.

    Inside a quad band vertex k of both rings sits on one rail, so the two
    frames differ by a constant angle -- measured directly, with no
    projection, which matters for hoops whose neighbouring sections are far
    from concentric.
    """
    deltas = []
    ring_count = component.ring_count
    for j in range(component.band_count):
        if component.band_kind[j] not in ("QUAD", "WEDGE"):
            deltas.append(None)
            continue
        j1 = (j + 1) % ring_count
        ring_a, ring_b = component.grid[j], component.grid[j1]
        pairs = component.band_pairs.get(j) or list(range(len(ring_a)))
        sin_sum = cos_sum = 0.0
        for k in range(len(ring_a)):
            d = fits[j].angle_of(coords[ring_a[k]]) - fits[j1].angle_of(coords[ring_b[pairs[k]]])
            sin_sum += math.sin(d)
            cos_sum += math.cos(d)
        deltas.append(math.atan2(sin_sum, cos_sum))
    return deltas


def _rebuild_component(bm, bm_analysis, component, fits, coords, counts, edge_flags, uv_layer,
                       source_uvs, detached, analysis_faces, original_quads):
    grid = component.grid
    ring_count = component.ring_count
    notes = []

    # New rings, each starting at the original seam (or vertex 0).
    deltas = _rail_deltas(component, fits, coords)
    uv_seams = _uv_seams(component, fits, coords, source_uvs) if source_uvs.available else [None] * ring_count
    start_angles = _start_angles(component, fits, coords, edge_flags, uv_seams, deltas)
    new_rings = []
    ring_angles = []
    vertex_angle = {}
    for j, (fit, ring, count) in enumerate(zip(fits, grid, counts)):
        start = start_angles[j]
        if fit.is_round:
            points = fit.points(count, start=start)
            angles = [start + TWO_PI * k / count for k in range(count)]
        else:
            original = [coords[i] for i in ring]
            first = min(range(len(ring)), key=lambda k: abs(((fit.angle_of(original[k]) - start + math.pi) % TWO_PI) - math.pi))
            rotated = original[first:] + original[:first]
            points = geometry.resample_closed_polyline(rotated, count)
            angles = [fit.angle_of(p) for p in points]
            if "section not round, shape kept" not in notes:
                notes.append("section not round, shape kept")
        verts = [bm.verts.new(Vector(p)) for p in points]
        new_rings.append(verts)
        ring_angles.append(list(angles))
        for vert, angle in zip(verts, angles):
            vertex_angle[vert] = (j, angle)

    # Wedge elbows: the arc the two rings shared stays shared.
    wedge_shared = {}
    for j in range(component.band_count):
        if component.band_kind[j] != "WEDGE":
            continue
        j1 = j + 1
        pairs = component.band_pairs[j]
        old_a, old_b = grid[j], grid[j1]
        shared_angles = [fits[j].angle_of(coords[old_a[k]]) for k in range(len(old_a)) if old_a[k] == old_b[pairs[k]]]
        if not shared_angles:
            continue
        lo, hi = _arc_bounds(shared_angles)
        # Only vertices strictly inside the original shared arc stay shared: beyond
        # its ends the two rings part ways, and a vertex shared there would take
        # two different UVs. If the count is so low that none falls inside, the
        # one nearest the middle of the arc is shared.
        arc = (hi - lo) % TWO_PI
        shared_new = []
        for k, angle in enumerate(ring_angles[j]):
            rel = (angle - lo) % TWO_PI
            if rel <= arc + 1e-6 or rel >= TWO_PI - 1e-6:
                shared_new.append(k)
        if not shared_new:
            middle = lo + 0.5 * arc
            shared_new = [min(range(len(ring_angles[j])),
                              key=lambda k: abs(((ring_angles[j][k] - middle + math.pi) % TWO_PI) - math.pi))]
        ring_b = new_rings[j1]
        # Safety net for odd geometry: the wedge opens to one side of ring M
        # (the mean of the original rails), so a new ring P vertex that falls
        # behind its ring M partner would fold the band; it is welded instead.
        opening = Vector((0.0, 0.0, 0.0))
        for k in range(len(old_a)):
            if old_a[k] != old_b[pairs[k]]:
                opening += Vector(coords[old_b[pairs[k]]]) - Vector(coords[old_a[k]])
        if opening.length_squared > 0.0:
            for k in range(len(ring_angles[j])):
                if k not in shared_new and (ring_b[k].co - new_rings[j][k].co).dot(opening) <= 0.0:
                    shared_new.append(k)
        # Angles of the original, index-aligned vertices in both frames: a shared
        # new vertex sits at some fraction of an original edge in ring M's frame,
        # and takes the same fraction of the same edge in ring P's frame, so both
        # sides sample the very same point of the original UV layout.
        alpha = [fits[j].angle_of(coords[v]) for v in old_a]
        beta = [fits[j1].angle_of(coords[old_b[pairs[k]]]) for k in range(len(old_a))]
        old_count = len(old_a)
        for k in shared_new:
            old_vert = ring_b[k]
            ring_b[k] = new_rings[j][k]
            vertex_angle.pop(old_vert, None)
            bm.verts.remove(old_vert)
            theta = ring_angles[j][k]
            best = None
            for i in range(old_count):
                a0 = alpha[i]
                span = (alpha[(i + 1) % old_count] - a0) % TWO_PI
                rel = (theta - a0) % TWO_PI
                if rel <= span + 1e-9:
                    best = (i, rel / span if span > 1e-12 else 0.0)
                    break
            if best is not None:
                i, frac = best
                b0 = beta[i]
                b_span = ((beta[(i + 1) % old_count] - b0 + math.pi) % TWO_PI) - math.pi
                ring_angles[j1][k] = b0 + frac * b_span
        wedge_shared[j] = set(shared_new)

    def face_attrs(fi):
        face = bm_analysis.faces[fi]
        return face.material_index, face.smooth

    def flags(a, b):
        return edge_flags.get(topology.edge_key(a, b), (False, False))

    # Bands: quads between rings of equal count, a triangle zipper otherwise.
    # Inside a quad band the rings are rail-aligned (same start rail, same
    # rotational sense), so vertex k pairs with vertex k. Across a bridge the
    # rings come from different sections: their angles are compared in ring
    # A's frame, offset and direction taken from the actual positions.
    def angles_in_frame_a(j):
        """Angles of ring j+1's new vertices expressed in ring j's frame."""
        j1 = (j + 1) % ring_count
        if deltas[j] is not None:
            return [angle + deltas[j] for angle in ring_angles[j1]]
        return [fits[j].angle_of(tuple(v.co)) for v in new_rings[j1]]

    def pairing(j):
        count = len(new_rings[(j + 1) % ring_count])
        if deltas[j] is not None:
            return lambda k: k
        ring_a = new_rings[j]
        base = fits[j].angle_of(tuple(ring_a[0].co))
        angles_b = [(a - base + math.pi) % TWO_PI - math.pi for a in angles_in_frame_a(j)]
        offset = min(range(count), key=lambda i: abs(angles_b[i]))
        forward = True
        if count > 2:
            forward = ((angles_b[(offset + 1) % count] - angles_b[offset]) % TWO_PI) < math.pi
        return (lambda k: (offset + k) % count) if forward else (lambda k: (offset - k) % count)

    new_faces = []
    band_new_faces = []
    for j in range(component.band_count):
        ring_a, ring_b = new_rings[j], new_rings[(j + 1) % ring_count]
        material, smooth = face_attrs(component.band_faces[j][0])
        winding = component.band_winding[j]
        row = []
        if component.band_kind[j] == "WEDGE":
            shared_new = wedge_shared.get(j, set())
            count = len(ring_a)
            for k in range(count):
                k1 = (k + 1) % count
                a_shared, b_shared = k in shared_new, k1 in shared_new
                if a_shared and b_shared:
                    continue
                if not a_shared and not b_shared:
                    face_verts = (ring_a[k], ring_a[k1], ring_b[k1], ring_b[k])
                elif a_shared:
                    face_verts = (ring_a[k], ring_a[k1], ring_b[k1])
                else:
                    face_verts = (ring_a[k], ring_a[k1], ring_b[k])
                if winding < 0:
                    face_verts = face_verts[::-1]
                row.append(bm.faces.new(face_verts))
        elif len(ring_a) == len(ring_b):
            count = len(ring_a)
            pair = pairing(j)
            for k in range(count):
                k1 = (k + 1) % count
                if winding > 0:
                    quad = (ring_a[k], ring_a[k1], ring_b[pair(k1)], ring_b[pair(k)])
                else:
                    quad = (ring_a[k], ring_b[pair(k)], ring_b[pair(k1)], ring_a[k1])
                row.append(bm.faces.new(quad))
        else:
            for tri in _zipper(ring_a, ring_b, ring_angles[j], angles_in_frame_a(j), winding):
                row.append(bm.faces.new(tri))
        for face in row:
            face.material_index = material
            face.smooth = smooth
        band_new_faces.append(row)
        new_faces.extend(row)

    # Caps.
    cap_faces = [[], []]
    centres = [None, None]
    for end in (0, 1):
        cap = component.caps[end]
        ring = new_rings[0] if end == 0 else new_rings[-1]
        count = len(ring)
        if cap is None and end in detached:
            island = detached[end]
            polygon = [tuple(v.co) for v in ring]
            forward = Vector(geometry.polygon_normal(polygon)).dot(island.normal) >= 0.0
            face = bm.faces.new(ring if forward else ring[::-1])
            face.material_index = island.material_index
            face.smooth = island.smooth
            cap_faces[end].append(face)
            if "detached cap welded" not in notes:
                notes.append("detached cap welded")
        elif cap is None:
            continue
        elif cap[0] == "NGON":
            material, smooth = face_attrs(cap[1])
            face = bm.faces.new(ring if cap[2] > 0 else ring[::-1])
            face.material_index = material
            face.smooth = smooth
            cap_faces[end].append(face)
        else:
            material, smooth = face_attrs(cap[2][0])
            centre = bm.verts.new(Vector(coords[cap[1]]))
            centres[end] = centre
            for k in range(count):
                k1 = (k + 1) % count
                tri = (ring[k], ring[k1], centre) if cap[3] > 0 else (ring[k1], ring[k], centre)
                face = bm.faces.new(tri)
                face.material_index = material
                face.smooth = smooth
                cap_faces[end].append(face)
        new_faces.extend(cap_faces[end])

    # Sharp edges and seams: a ring keeps its flags if any of its old edges had them,
    # a quad band keeps sharp rails likewise, and a seam along the form becomes the
    # rail at position 0 -- which now sits where the old seam was.
    for j in range(ring_count):
        old_ring = grid[j]
        old_n = len(old_ring)
        sharp = seam = False
        for k in range(old_n):
            s, m = flags(old_ring[k], old_ring[(k + 1) % old_n])
            sharp = sharp or s
            seam = seam or m
        if sharp or seam:
            ring = new_rings[j]
            count = len(ring)
            for k in range(count):
                edge = bm.edges.get((ring[k], ring[(k + 1) % count]))
                if edge is not None:
                    if sharp:
                        edge.smooth = False
                    if seam:
                        edge.seam = True
    # Rails: every flagged old rail marks the new rail nearest to it by angle
    # (the seam rail lands on position 0, where the ring now starts); a band
    # whose rails were all sharp stays all sharp whatever the new count.
    for j in range(component.band_count):
        if component.band_kind[j] != "QUAD":
            continue
        ring_a, ring_b = new_rings[j], new_rings[(j + 1) % ring_count]
        if len(ring_a) != len(ring_b):
            continue
        old_a, old_b = grid[j], grid[(j + 1) % ring_count]
        flagged = [(k, flags(old_a[k], old_b[k])) for k in range(len(old_a))]
        flagged = [(k, s, m) for k, (s, m) in flagged if s or m]
        if not flagged:
            continue
        all_sharp = all(flags(old_a[k], old_b[k])[0] for k in range(len(old_a)))
        count = len(ring_a)
        rails = [bm.edges.get((ring_a[k], ring_b[k])) for k in range(count)]
        if all_sharp:
            for edge in rails:
                if edge is not None:
                    edge.smooth = False
        for k, s, m in flagged:
            angle = fits[j].angle_of(coords[old_a[k]])
            nearest = min(range(count), key=lambda kk: abs(((ring_angles[j][kk] - angle + math.pi) % TWO_PI) - math.pi))
            edge = rails[nearest]
            if edge is None:
                continue
            if s:
                edge.smooth = False
            if m:
                edge.seam = True

    if uv_layer is not None:
        transferred = False
        if source_uvs.available:
            transferred = _transfer_uvs(
                uv_layer, component, fits, coords, new_rings, vertex_angle, ring_angles,
                band_new_faces, cap_faces, centres, source_uvs, detached, deltas)
        if not transferred:
            _assign_uvs_synthetic(uv_layer, component, fits, new_rings, vertex_angle, band_new_faces, cap_faces, centres)
            notes.append("UVs regenerated")

    if _was_triangulated(component, analysis_faces, original_quads):
        bmesh.ops.triangulate(bm, faces=new_faces, quad_method='BEAUTY', ngon_method='BEAUTY')
    return ", ".join(notes)


def _ring_side_sets(component):
    return [set(ring) for ring in component.grid]


def _uv_seams(component, fits, coords, source):
    """Per ring: the index of a vertex where the UV layout jumps (a seam), or None."""
    grid = component.grid
    ring_count = component.ring_count
    ring_sets = _ring_side_sets(component)
    seams = [None] * ring_count
    for j, ring in enumerate(grid):
        angles = [fits[j].angle_of(coords[i]) for i in ring]
        # The band towards the previous ring first: the seam of a band then
        # lands on a vertex of its second ring, the first ring's seam being
        # decided by the band before it.
        sides = []
        if j > 0 or component.closed:
            sides.append(ring_sets[(j - 1) % ring_count])
        if j + 1 < ring_count or component.closed:
            sides.append(ring_sets[(j + 1) % ring_count])
        for target in sides:
            samples = uv_transfer.ring_side_samples(
                source, ring, angles, lambda verts, t=target: any(v in t for v in verts))
            if samples is None:
                continue
            found = samples.seam_indices()
            if found:
                seams[j] = found[0]
                break
    return seams


def _transfer_uvs(uv_layer, component, fits, coords, new_rings, vertex_angle, ring_angles,
                  band_new_faces, cap_faces, centres, source, detached, deltas):
    """Sample the original UVs onto the new faces. False when the source lacks a face somewhere.

    Every face takes all its corners on one ring from a single original
    interval -- the one under the face's centre as seen from that ring -- so
    no face straddles a UV seam even where the seam is only in the layout.
    """
    grid = component.grid
    ring_count = component.ring_count
    ring_sets = _ring_side_sets(component)
    original_angles = [[fits[j].angle_of(coords[i]) for i in ring] for j, ring in enumerate(grid)]

    def towards(j):
        target = ring_sets[j % ring_count]
        return lambda verts: any(v in target for v in verts)

    angle_of = {}
    for jj, ring in enumerate(new_rings):
        for k, vert in enumerate(ring):
            angle_of[(jj, vert)] = ring_angles[jj][k]

    def corner_ring(loop, ring_samples):
        for r in ring_samples:
            if (r, loop.vert) in angle_of:
                return r
        return None

    def seen_from(jj, loop, delta, j, j1, ring_samples):
        """Angle of a corner in ring jj's frame: its own angle, shifted through the rail
        delta for the neighbour ring of a quad band, projected across a bridge."""
        if (jj, loop.vert) in angle_of:
            return angle_of[(jj, loop.vert)]
        ring_of_loop = corner_ring(loop, ring_samples)
        if delta is not None and ring_of_loop is not None:
            angle = angle_of[(ring_of_loop, loop.vert)]
            return angle + delta if (ring_of_loop == j1 and jj == j) else angle - delta
        return fits[jj].angle_of(tuple(loop.vert.co))

    def assign(face, ring_samples, ring_indices, delta=None, j=None, j1=None):
        """ring_samples: {ring index: RingSamples} for the rings this face touches.

        The ring holding most corners picks the original face under the new
        face's centre; the other ring then samples from the same UV island,
        so a face never mixes two islands even where a seam zigzags through
        a reduction band.
        """
        corners = {}
        for loop in face.loops:
            ring_of_loop = corner_ring(loop, ring_samples)
            if ring_of_loop is not None:
                corners.setdefault(ring_of_loop, []).append(loop)
        island = None
        for jj in sorted(ring_samples, key=lambda r: -len(corners.get(r, ()))):
            samples = ring_samples[jj]
            seen_from_ring = [seen_from(jj, loop, delta, j, j1, ring_samples) for loop in face.loops
                              if loop.vert not in ring_indices]
            centre = uv_transfer.face_centre_angle(seen_from_ring)
            if island is None:
                index = samples.index_containing(centre)
                island = source.island_of(samples.polys[index])
            else:
                index = samples.index_near(centre, island, source.island_of)
            count = len(samples)
            for loop in corners.get(jj, ()):
                angle = angle_of[(jj, loop.vert)]
                # A vertex takes the UV of the interval it sits in, the same for
                # every face around it, so islands stay in one piece. On a UV
                # cut the face's side decides, and a face that reaches across a
                # cut extrapolates from its own side instead.
                own = samples.index_owning(angle)
                if samples.starts_at(own, angle) and own in samples.cut_set():
                    before = ((centre - angle + math.pi) % TWO_PI) - math.pi < 0.0
                    chosen = (own - 1) % count if before else own
                elif samples.crosses_cut(index, own):
                    chosen = index
                else:
                    chosen = own
                loop[uv_layer].uv = samples.sample_in(chosen, angle)
            yield jj, index

    def towards_wedge(j_self, j_other):
        """Side test for the two rings of a wedge elbow, which share vertices: a face
        of the wedge holds a vertex the other ring has of its own; on the shared arc
        (no wedge face) either neighbour will do, the samples there are never used."""
        self_only = ring_sets[j_self] - ring_sets[j_other]
        other_only = ring_sets[j_other] - ring_sets[j_self]
        return lambda verts: any(v in other_only for v in verts) or not any(v in self_only for v in verts)

    for j in range(component.band_count):
        j1 = (j + 1) % ring_count
        if component.band_kind[j] == "WEDGE":
            side_a, side_b = towards_wedge(j, j1), towards_wedge(j1, j)
        else:
            side_a, side_b = towards(j1), towards(j)
        samples_a = uv_transfer.ring_side_samples(source, grid[j], original_angles[j], side_a)
        samples_b = uv_transfer.ring_side_samples(source, grid[j1], original_angles[j1], side_b)
        if samples_a is None or samples_b is None:
            return False
        for face in band_new_faces[j]:
            for _jj, _index in assign(face, {j: samples_a, j1: samples_b}, (), deltas[j], j, j1):
                pass

    for end in (0, 1):
        faces = cap_faces[end]
        if not faces:
            continue
        j = 0 if end == 0 else ring_count - 1
        cap = component.caps[end]
        centre_vertex = None
        if cap is None:
            island = detached[end]
            fit = fits[j]
            samples = source.outline_samples(island.polygons, lambda v: fit.angle_of(coords[v]))
            if len(samples) == 0:
                return False
        elif cap[0] == "NGON":
            # The original cap may be one n-gon or a planar fill of quads and
            # triangles (joined into the n-gon by the analysis): any face
            # lying entirely on the ring is part of it.
            ring_set = ring_sets[j]
            samples = uv_transfer.ring_side_samples(
                source, grid[j], original_angles[j], lambda verts: set(verts) <= ring_set)
        else:
            centre_vertex = cap[1]
            samples = uv_transfer.ring_side_samples(
                source, grid[j], original_angles[j], lambda verts: centre_vertex in verts)
        if samples is None:
            return False
        centre_mean = source.vertex_uv(centre_vertex, lambda verts: True) if centre_vertex is not None else None
        for face in faces:
            chosen = None
            if centre_vertex is None:
                # One n-gon over the whole ring: every corner in its own interval.
                for loop in face.loops:
                    loop[uv_layer].uv = samples.sample(angle_of[(j, loop.vert)])
                continue
            for _jj, index in assign(face, {j: samples}, (centres[end],)):
                chosen = index
            centre_loop = next((loop for loop in face.loops if loop.vert is centres[end]), None)
            if centre_loop is not None:
                uv = None
                if chosen is not None and samples.polys[chosen] is not None and centre_vertex is not None:
                    uv = source.loop_uv_of(samples.polys[chosen], centre_vertex)
                if uv is None:
                    uv = centre_mean if centre_mean is not None else (0.5, 0.5)
                centre_loop[uv_layer].uv = uv
    return True


def _arc_bounds(angles):
    """(lo, hi) of the shortest arc holding all angles; hi may exceed lo by up to 2 pi."""
    ordered = sorted(a % TWO_PI for a in angles)
    count = len(ordered)
    if count == 1:
        return ordered[0], ordered[0]
    best_gap, best_index = -1.0, 0
    for i in range(count):
        gap = (ordered[(i + 1) % count] - ordered[i]) % TWO_PI
        if gap > best_gap:
            best_gap, best_index = gap, i
    lo = ordered[(best_index + 1) % count]
    hi = ordered[best_index]
    if hi < lo:
        hi += TWO_PI
    return lo, hi


def _assign_uvs_synthetic(uv_layer, component, fits, new_rings, vertex_angle, band_new_faces, cap_faces, centres):
    """A plain cylindrical layout for forms whose original had no usable UVs."""
    ring_count = component.ring_count
    distances = [0.0]
    for j in range(1, ring_count):
        distances.append(distances[-1] + geometry.length(geometry.sub(fits[j].center, fits[j - 1].center)))
    total = distances[-1]
    if component.closed:
        total += geometry.length(geometry.sub(fits[0].center, fits[-1].center))
    if total <= 0.0:
        total = 1.0
    v_of_ring = [d / total for d in distances]
    start = [fits[j].phase for j in range(ring_count)]

    for j, row in enumerate(band_new_faces):
        closing = j + 1 >= ring_count
        for face in row:
            uvs = []
            for loop in face.loops:
                ring_j, angle = vertex_angle[loop.vert]
                u = ((angle - start[ring_j]) % TWO_PI) / TWO_PI
                v = 1.0 if (closing and ring_j == 0) else v_of_ring[ring_j]
                uvs.append([u, v])
            if max(uv[0] for uv in uvs) - min(uv[0] for uv in uvs) > 0.5:
                for uv in uvs:
                    if uv[0] < 0.5:
                        uv[0] += 1.0
            for loop, uv in zip(face.loops, uvs):
                loop[uv_layer].uv = (uv[0], uv[1])

    for end, faces in enumerate(cap_faces):
        for face in faces:
            for loop in face.loops:
                if loop.vert is centres[end]:
                    loop[uv_layer].uv = (0.5, 0.5)
                else:
                    _j, angle = vertex_angle[loop.vert]
                    loop[uv_layer].uv = (0.5 + 0.5 * math.cos(angle), 0.5 + 0.5 * math.sin(angle))
