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
"""Finding cylindrical forms in a mesh.

Pure Python on purpose so the search can be unit-tested with synthetic
meshes and a plain interpreter (see ``tests/test_topology.py``).

A cylindrical form is a chain of rings. Inside a *section* every ring has the
same vertex count and consecutive rings are joined by a band of quads: a
grid of rings crossed by rails. Sections with different counts are joined by
a *bridge* band of triangles (the way the fixer itself builds a tube with a
collar). Straight cylinders, pipes along a path, lathe profiles, spheres
between their poles and tori all have this structure. The ends may be open,
closed with one n-gon, or closed with a triangle fan around a centre vertex.

The search walks edge loops the way Blender does for loop select (at every
vertex continue along the one edge that shares no quad with the current
edge), sorts the loops into the two families of each quad grid, recognises
the family of closed loops as the rings, lays the vertices out as
``grid[ring][position]`` using the rails, then links grids whose end rings
are joined by bridges. A form is only accepted when it is self-contained:
every ring vertex belongs to the form's own bands and caps and nothing else,
so rebuilding it cannot tear other geometry.
"""

from . import geometry


class Component:
    """One cylindrical form: its rings, its bands and what is attached to it.

    Rows of ``grid`` may differ in length where sections meet. A band between
    ring ``j`` and ``j + 1`` is a row of quads (``band_kind`` "QUAD") or a set
    of triangles (``"BRIDGE"``).
    """

    __slots__ = ("grid", "closed", "caps", "band_faces", "band_winding", "band_kind", "band_pairs", "faces")

    def __init__(self):
        self.grid = []            # grid[j][k]: vertex index, ring j, position k around
        self.closed = False       # torus: the last ring connects back to the first
        self.caps = [None, None]  # per end: None, ("NGON", face, winding) or ("FAN", centre, faces, winding)
        self.band_faces = []      # per band: quad face per position, or the bridge / wedge faces
        self.band_winding = []    # per band: +1 if the faces run ring j -> j+1 as (A[k], A[k+1], B.., B..)
        self.band_kind = []       # per band: "QUAD", "BRIDGE" or "WEDGE"
        self.band_pairs = {}      # WEDGE bands: per position k of ring j the position in ring j+1
        self.faces = set()        # every face the form owns (bands and caps)

    @property
    def ring_count(self):
        return len(self.grid)

    @property
    def segments(self):
        """Vertex count of the first ring (of every ring, for a single section)."""
        return len(self.grid[0]) if self.grid else 0

    @property
    def ring_lengths(self):
        return [len(ring) for ring in self.grid]

    @property
    def band_count(self):
        return self.ring_count if self.closed else self.ring_count - 1

    def cap_centres(self):
        return [cap[1] for cap in self.caps if cap is not None and cap[0] == "FAN"]

    def vertex_indices(self):
        seen = set()
        for ring in self.grid:
            seen.update(ring)
        seen.update(self.cap_centres())
        return seen

    def reversed(self):
        """The same form walked from the other end."""
        other = Component()
        other.grid = [list(ring) for ring in reversed(self.grid)]
        other.closed = self.closed
        other.caps = [self.caps[1], self.caps[0]]
        other.band_faces = list(reversed(self.band_faces))
        other.band_winding = [-w for w in reversed(self.band_winding)]
        other.band_kind = list(reversed(self.band_kind))
        last = len(self.band_kind) - 1
        for j, pairs in self.band_pairs.items():
            inverse = [0] * len(pairs)
            for k, k1 in enumerate(pairs):
                inverse[k1] = k
            other.band_pairs[last - j] = inverse
        other.faces = set(self.faces)
        return other


class _Loop:
    __slots__ = ("verts", "closed", "edges")

    def __init__(self, verts, closed, edges):
        self.verts = verts
        self.closed = closed
        self.edges = edges


class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


class _Rejected(Exception):
    """A quad grid that is not a self-contained cylindrical form."""


class _Mesh:
    """Lookup tables of one mesh, shared by the search steps."""

    __slots__ = ("verts", "faces", "face_edges", "edge_faces", "vert_faces", "vert_edges", "quads", "edge_quads")

    def __init__(self, verts, faces, edges):
        self.verts = verts
        self.faces = faces
        vert_count = len(verts)
        self.face_edges = []
        self.edge_faces = {}
        self.vert_faces = [[] for _ in range(vert_count)]
        for fi, face in enumerate(faces):
            n = len(face)
            keys = []
            for i in range(n):
                key = edge_key(face[i], face[(i + 1) % n])
                keys.append(key)
                self.edge_faces.setdefault(key, []).append(fi)
            self.face_edges.append(keys)
            for v in face:
                self.vert_faces[v].append(fi)
        if edges:
            for a, b in edges:
                self.edge_faces.setdefault(edge_key(a, b), [])
        self.vert_edges = [set() for _ in range(vert_count)]
        for key in self.edge_faces:
            self.vert_edges[key[0]].add(key)
            self.vert_edges[key[1]].add(key)
        self.quads = {fi for fi, face in enumerate(faces) if len(face) == 4}
        self.edge_quads = {
            key: frozenset(fi for fi in fl if fi in self.quads) for key, fl in self.edge_faces.items()
        }


def edge_key(a, b):
    return (a, b) if a < b else (b, a)


def _other(edge, vertex):
    return edge[1] if edge[0] == vertex else edge[0]


def find_components(verts, faces, edges=None, excluded=frozenset()):
    """Find every self-contained cylindrical form in a mesh.

    :param verts: sequence of (x, y, z)
    :param faces: sequence of vertex index tuples
    :param edges: optional sequence of (a, b) for loose edges the faces do not cover
    :param excluded: vertices already owned by forms found in an earlier run;
        faces touching them are neither walked nor complained about
    :return: (components, notes) -- notes describe grids that were rejected
    """
    mesh = _Mesh(verts, faces, edges)
    excluded = set(excluded)
    quads = [fi for fi in mesh.quads if not excluded or not any(v in excluded for v in faces[fi])]
    quad_ids = set(quads)
    candidates = {key for key, q in mesh.edge_quads.items() if q & quad_ids}
    loops, loop_of_edge = _walk_loops(candidates, mesh.edge_quads, mesh.vert_edges)

    # Two loop families per quad grid: the loops of opposite quad edges belong
    # together, the loops of adjacent quad edges must differ.
    family = UnionFind(len(loops))
    grid_of = UnionFind(len(loops))
    opposite = []
    for fi in quads:
        la, lb, lc, ld = (loop_of_edge[key] for key in mesh.face_edges[fi])
        family.union(la, lc)
        family.union(lb, ld)
        grid_of.union(la, lb)
        grid_of.union(la, lc)
        grid_of.union(la, ld)
        opposite.append((la, lb))

    grids = {}
    for loop_id in range(len(loops)):
        grids.setdefault(grid_of.find(loop_id), []).append(loop_id)
    conflicts = set()
    for la, lb in opposite:
        if family.find(la) == family.find(lb):
            conflicts.add(grid_of.find(la))

    components = []
    notes = []
    for root, members in grids.items():
        if root in conflicts:
            notes.append("irregular quad grid")
            continue
        families = {}
        for loop_id in members:
            families.setdefault(family.find(loop_id), []).append(loop_id)
        if len(families) != 2:
            continue  # a lone strip of quads, not a grid
        fam_a, fam_b = list(families.values())
        try:
            component = _build_component(mesh, loops, fam_a, fam_b)
        except _Rejected as why:
            notes.append(str(why))
            continue
        except (KeyError, ValueError, IndexError):
            notes.append("irregular topology")
            continue
        if component is not None:
            components.append(component)

    linked, link_notes = _link_bridges(mesh, components)
    notes.extend(link_notes)

    # Whatever the grid walk could not read gets more chances: first as a rod
    # bent with a hand-made elbow (rings derived band by band from the ends),
    # then as a lathe-like form (reduction bands mixing quads and triangles).
    from . import elbow, lathe
    owned = set(excluded)
    for component in linked:
        owned.update(component.vertex_indices())
    closed_loops = [loop.verts for loop in loops if loop.closed]
    elbow_forms, elbow_notes = elbow.find_elbow_forms(mesh, owned, closed_loops)
    linked.extend(elbow_forms)
    notes.extend(elbow_notes)
    for component in elbow_forms:
        owned.update(component.vertex_indices())
    lathe_forms, lathe_notes = lathe.find_lathe_forms(mesh, owned, closed_loops)
    linked.extend(lathe_forms)
    notes.extend(lathe_notes)
    return linked, notes


def _walk_loops(candidates, edge_quads, vert_edges):
    loops = []
    loop_of_edge = {}

    def step(edge, at):
        blocked = edge_quads[edge]
        options = [
            other for other in vert_edges[at]
            if other != edge and other in candidates and not (edge_quads[other] & blocked)
        ]
        return options[0] if len(options) == 1 else None

    for start in sorted(candidates):
        if start in loop_of_edge:
            continue
        chain = [start[0], start[1]]
        chain_edges = [start]
        used = {start}
        closed = False
        current, at = start, start[1]
        while True:
            nxt = step(current, at)
            if nxt is None:
                break
            if nxt == start:
                closed = True
                break
            if nxt in used:
                break
            at = _other(nxt, at)
            chain.append(at)
            chain_edges.append(nxt)
            used.add(nxt)
            current = nxt
        if closed:
            chain.pop()  # the walk arrived back at start[0]
        else:
            current, at = start, start[0]
            while True:
                nxt = step(current, at)
                if nxt is None or nxt in used:
                    break
                at = _other(nxt, at)
                chain.insert(0, at)
                chain_edges.insert(0, nxt)
                used.add(nxt)
                current = nxt
        loop_id = len(loops)
        loops.append(_Loop(chain, closed, used))
        for key in chain_edges:
            loop_of_edge[key] = loop_id
    return loops, loop_of_edge


def _family_stats(verts, loops, ids):
    """(mean radius, all loops round) of a loop family."""
    total = 0.0
    all_round = True
    for loop_id in ids:
        fit = geometry.fit_ring([verts[v] for v in loops[loop_id].verts])
        total += max(fit.a, fit.b)
        all_round = all_round and fit.is_round
    return total / len(ids), all_round


def _build_component(mesh, loops, fam_a, fam_b):
    verts, faces = mesh.verts, mesh.faces
    closed_a = all(loops[i].closed for i in fam_a)
    closed_b = all(loops[i].closed for i in fam_b)
    if closed_a and not closed_b:
        ring_ids, rail_ids = fam_a, fam_b
    elif closed_b and not closed_a:
        ring_ids, rail_ids = fam_b, fam_a
    elif closed_a and closed_b:
        # Torus topology. A doughnut has two round families and the rings are
        # the smaller circles. A ring band (a rectangular profile swept around
        # a circle) has one round family only: those circles are the rings and
        # the profile is the rail, whatever its size.
        radius_a, round_a = _family_stats(verts, loops, fam_a)
        radius_b, round_b = _family_stats(verts, loops, fam_b)
        if round_a and not round_b:
            ring_ids, rail_ids = fam_a, fam_b
        elif round_b and not round_a:
            ring_ids, rail_ids = fam_b, fam_a
        elif radius_a <= radius_b:
            ring_ids, rail_ids = fam_a, fam_b
        else:
            ring_ids, rail_ids = fam_b, fam_a
    else:
        return None  # an open grid (a plane, a bent sheet): not a cylinder
    torus = all(loops[i].closed for i in rail_ids)
    if not torus and any(loops[i].closed for i in rail_ids):
        raise _Rejected("rails partly closed")

    segments = len(loops[ring_ids[0]].verts)
    if segments < 3 or any(len(loops[i].verts) != segments for i in ring_ids):
        raise _Rejected("rings of different lengths")
    ring_count = len(ring_ids)
    if ring_count < 2:
        return None
    if len(rail_ids) != segments:
        raise _Rejected("rail count does not match the rings")
    if any(len(loops[i].verts) != ring_count for i in rail_ids):
        raise _Rejected("rail length does not match the ring count")

    ring_index = {}
    for j, loop_id in enumerate(ring_ids):
        for v in loops[loop_id].verts:
            if v in ring_index:
                raise _Rejected("a vertex on two rings")
            ring_index[v] = j
    rail_of_vertex = {}
    for loop_id in rail_ids:
        for v in loops[loop_id].verts:
            rail_of_vertex[v] = loop_id

    # The order of the rings along the form comes straight from one rail.
    reference = loops[rail_ids[0]].verts
    order = [ring_index[v] for v in reference]
    if len(set(order)) != ring_count:
        raise _Rejected("a rail visits a ring twice")

    first_ring = loops[ring_ids[order[0]]].verts
    start = first_ring.index(reference[0])
    ring0 = first_ring[start:] + first_ring[:start]

    grid = [[None] * segments for _ in range(ring_count)]
    for k, v in enumerate(ring0):
        rail = loops[rail_of_vertex[v]]
        seq = _orient_rail(rail, v, ring_index, order, torus)
        if seq is None:
            raise _Rejected("rail does not start at the first ring")
        for j in range(ring_count):
            grid[j][k] = seq[j]

    # Every grid row must be the ring it claims to be, in consecutive order.
    for j in range(ring_count):
        ring_edges = loops[ring_ids[order[j]]].edges
        for k in range(segments):
            v = grid[j][k]
            if ring_index.get(v) != order[j]:
                raise _Rejected("grid row leaves its ring")
            if edge_key(v, grid[j][(k + 1) % segments]) not in ring_edges:
                raise _Rejected("grid row is not consecutive around the ring")

    component = Component()
    component.grid = grid
    component.closed = torus

    # Bands: the quad between (j,k)-(j,k+1) and (j+1,k)-(j+1,k+1).
    band_count = ring_count if torus else ring_count - 1
    for j in range(band_count):
        ring_a = grid[j]
        ring_b = grid[(j + 1) % ring_count]
        row = []
        for k in range(segments):
            k1 = (k + 1) % segments
            shared = mesh.edge_quads.get(edge_key(ring_a[k], ring_a[k1]), frozenset()) & \
                mesh.edge_quads.get(edge_key(ring_b[k], ring_b[k1]), frozenset())
            if len(shared) != 1:
                raise _Rejected("band without a single quad")
            row.append(next(iter(shared)))
        component.band_faces.append(row)
        component.band_kind.append("QUAD")
        component.faces.update(row)
        face = faces[row[0]]
        i0 = face.index(ring_a[0])
        component.band_winding.append(1 if face[(i0 + 1) % 4] == ring_a[1] else -1)

    # Caps or bridges on the two open ends.
    grid_verts = set(ring_index)
    if not torus:
        for end, j in ((0, 0), (1, ring_count - 1)):
            ring = grid[j]
            extra = set()
            for v in ring:
                extra.update(fi for fi in mesh.vert_faces[v] if fi not in component.faces)
            cap = _classify_end(faces, ring, extra, grid_verts)
            component.caps[end] = cap
            if cap is not None:
                component.faces.update(cap[2] if cap[0] in ("FAN", "BRIDGE") else (cap[1],))

    _check_self_contained(mesh, component)
    return component


def _check_self_contained(mesh, component):
    """Nothing but the form's own faces, and edges to bridged rings, touch its vertices."""
    owned = component.vertex_indices()
    allowed = set(owned)
    for cap in component.caps:
        if cap is not None and cap[0] == "BRIDGE":
            allowed |= cap[1]
    for v in owned:
        if any(fi not in component.faces for fi in mesh.vert_faces[v]):
            raise _Rejected("connected to other geometry")
        for key in mesh.vert_edges[v]:
            if _other(key, v) not in allowed:
                raise _Rejected("connected to other geometry")


def _orient_rail(rail, start_vertex, ring_index, order, torus):
    verts = rail.verts
    idx = verts.index(start_vertex)
    if torus:
        seq = verts[idx:] + verts[:idx]
        if len(seq) > 1 and ring_index[seq[1]] != order[1]:
            seq = [seq[0]] + seq[1:][::-1]
        return seq
    if idx == 0:
        seq = list(verts)
    elif idx == len(verts) - 1:
        seq = verts[::-1]
    else:
        return None
    if len(seq) > 1 and ring_index[seq[1]] != order[1]:
        return None
    return seq


def _winding_of(faces, face_ids, ring):
    """+1 when a face holds ring[0] followed by ring[1], -1 for the reverse, None if none does."""
    for fi in face_ids:
        face = faces[fi]
        if ring[0] in face and ring[1] in face:
            i0 = face.index(ring[0])
            return 1 if face[(i0 + 1) % len(face)] == ring[1] else -1
    return None


def _classify_end(faces, ring, extra, grid_verts):
    """What sits on a ring at the end of a grid.

    Returns None (open end), ("NGON", face, winding), ("FAN", centre, faces,
    winding) or ("BRIDGE", other vertices, faces, winding) -- a band of
    triangles leading to a ring of a different vertex count.
    """
    if not extra:
        return None
    ring_set = set(ring)
    segments = len(ring)
    if len(extra) == 1:
        fi = next(iter(extra))
        face = faces[fi]
        if len(face) == segments and set(face) == ring_set:
            i0 = face.index(ring[0])
            winding = 1 if face[(i0 + 1) % segments] == ring[1] else -1
            return ("NGON", fi, winding)
        raise _Rejected("connected to other geometry")

    if any(len(faces[fi]) != 3 for fi in extra):
        raise _Rejected("connected to other geometry")

    if len(extra) == segments:
        centre = None
        fan = [None] * segments
        for fi in extra:
            face = faces[fi]
            outside = [v for v in face if v not in ring_set]
            if len(outside) != 1:
                break
            if centre is None:
                centre = outside[0]
            elif centre != outside[0]:
                break
            inside = [v for v in face if v in ring_set]
            k0 = ring.index(inside[0])
            k1 = ring.index(inside[1])
            if (k1 - k0) % segments == 1:
                fan[k0] = fi
            elif (k0 - k1) % segments == 1:
                fan[k1] = fi
            else:
                break
        else:
            if centre is not None and centre not in grid_verts and None not in fan:
                face = faces[fan[0]]
                i0 = face.index(ring[0])
                winding = 1 if face[(i0 + 1) % 3] == ring[1] else -1
                return ("FAN", centre, fan, winding)

    # A bridge: triangles between this ring and one other ring.
    others = set()
    for fi in extra:
        face = faces[fi]
        outside = [v for v in face if v not in ring_set]
        if not outside or len(outside) == 3:
            raise _Rejected("connected to other geometry")
        others.update(outside)
    if len(others) < 3 or (others & grid_verts):
        raise _Rejected("connected to other geometry")
    winding = _winding_of(faces, extra, ring)
    if winding is None:
        raise _Rejected("connected to other geometry")
    return ("BRIDGE", frozenset(others), sorted(extra), winding)


# --- linking sections through bridges -----------------------------------------

def _end_ring(component, end):
    return frozenset(component.grid[0 if end == 0 else -1])


def _link_bridges(mesh, components):
    """Chain grids whose end rings are bridged; resolve lone rings between bridges."""
    notes = []
    components = list(components)
    owners = {}  # frozenset(end ring) -> [(component index, end), ...]

    def index_component(ci):
        c = components[ci]
        if not c.closed:
            for end in (0, 1):
                owners.setdefault(_end_ring(c, end), []).append((ci, end))

    for ci in range(len(components)):
        index_component(ci)

    def resolve(ci, end):
        """The (component, end) a bridge leads to, or None when no end bridges back."""
        cap = components[ci].caps[end]
        mine = _end_ring(components[ci], end)
        for tc, tend in owners.get(cap[1], ()):
            if tc == ci:
                continue
            back = components[tc].caps[tend]
            if back is not None and back[0] == "BRIDGE" and back[1] == mine:
                return tc, tend
        return None

    # Bridges that lead to no grid may lead to a lone ring; build those.
    rejected = set()
    queue = list(range(len(components)))
    while queue:
        ci = queue.pop(0)
        if ci in rejected:
            continue
        c = components[ci]
        for end in (0, 1):
            cap = c.caps[end]
            if cap is None or cap[0] != "BRIDGE" or cap[1] in owners:
                continue
            try:
                lone = _lone_ring(mesh, cap[1], set(cap[2]), _end_ring(c, end))
            except _Rejected as why:
                notes.append(str(why))
                rejected.add(ci)
                break
            components.append(lone)
            index_component(len(components) - 1)
            queue.append(len(components) - 1)

    # Every bridge must be mutual.
    for ci, c in enumerate(components):
        if ci in rejected:
            continue
        for end in (0, 1):
            cap = c.caps[end]
            if cap is not None and cap[0] == "BRIDGE" and resolve(ci, end) is None:
                rejected.add(ci)
                notes.append("connected to other geometry")
                break

    # Assemble chains from a free end.
    visited = set(rejected)
    result = []
    for ci, c in enumerate(components):
        if ci in visited:
            continue
        if c.closed:
            visited.add(ci)
            result.append(c)
            continue
        if all(cap is not None and cap[0] == "BRIDGE" for cap in c.caps):
            continue  # a middle section: reached from an end of its chain, or part of a closed chain below
        visited.add(ci)
        if c.caps[0] is not None and c.caps[0][0] == "BRIDGE":
            chain = c.reversed()
            head_end = 0  # the chain's tail end is this component's end 0
        else:
            chain = c
            head_end = 1
        current, current_end = ci, head_end
        broken = False
        while chain.caps[1] is not None and chain.caps[1][0] == "BRIDGE":
            target = resolve(current, current_end)
            if target is None:
                broken = True
                break
            tc, tend = target
            if tc in visited:
                broken = True  # a loop of sections: not supported
                break
            visited.add(tc)
            nxt = components[tc] if tend == 0 else components[tc].reversed()
            chain = _join(chain, chain.caps[1], nxt)
            current, current_end = tc, 1 - tend
        if broken:
            notes.append("connected to other geometry")
            continue
        result.append(chain)

    # What is left are middle sections only: chains that close on themselves
    # (a torus whose tube changes thickness, split into sections by a fix).
    for ci, c in enumerate(components):
        if ci in visited:
            continue
        visited.add(ci)
        chain = c
        current, current_end = ci, 1
        closing = None
        broken = False
        while True:
            target = resolve(current, current_end)
            if target is None:
                broken = True
                break
            tc, tend = target
            if tc == ci:
                closing = chain.caps[1] if tend == 0 else None
                break
            if tc in visited:
                broken = True
                break
            visited.add(tc)
            nxt = components[tc] if tend == 0 else components[tc].reversed()
            chain = _join(chain, chain.caps[1], nxt)
            current, current_end = tc, 1 - tend
        if broken or closing is None:
            notes.append("connected to other geometry")
            continue
        chain.closed = True
        chain.caps = [None, None]
        chain.band_faces.append(list(closing[2]))
        chain.band_winding.append(closing[3])
        chain.band_kind.append("BRIDGE")
        chain.faces.update(closing[2])
        result.append(chain)
    return result, notes


def _join(head, bridge, tail):
    """Concatenate ``tail`` after ``head`` across ``bridge`` (the BRIDGE cap of head's last ring)."""
    joined = Component()
    joined.grid = [list(r) for r in head.grid] + [list(r) for r in tail.grid]
    joined.closed = False
    joined.caps = [head.caps[0], tail.caps[1]]
    joined.band_faces = list(head.band_faces) + [list(bridge[2])] + list(tail.band_faces)
    joined.band_winding = list(head.band_winding) + [bridge[3]] + list(tail.band_winding)
    joined.band_kind = list(head.band_kind) + ["BRIDGE"] + list(tail.band_kind)
    offset = len(head.band_kind) + 1
    joined.band_pairs = dict(head.band_pairs)
    for j, pairs in tail.band_pairs.items():
        joined.band_pairs[offset + j] = pairs
    joined.faces = set(head.faces) | set(tail.faces) | set(bridge[2])
    return joined


def vertex_cycle(mesh, vertex_set):
    """The vertices as one closed cycle of edges (from the lowest index), or None."""
    neighbours = {}
    for v in vertex_set:
        inside = [_other(key, v) for key in mesh.vert_edges[v] if _other(key, v) in vertex_set]
        if len(inside) != 2:
            return None
        neighbours[v] = inside
    start = min(vertex_set)
    ring = [start]
    previous, current = None, start
    while True:
        a, b = neighbours[current]
        nxt = b if a == previous else a
        if nxt == start:
            break
        if nxt in ring:
            return None
        ring.append(nxt)
        previous, current = current, nxt
    return ring if len(ring) == len(vertex_set) else None


def _lone_ring(mesh, vertices, bridge_faces, previous_ring):
    """A ring that has no quads of its own: a bridge on one side, anything on the other."""
    faces = mesh.faces
    vertex_set = set(vertices)
    ring = vertex_cycle(mesh, vertex_set)
    if ring is None:
        raise _Rejected("connected to other geometry")

    component = Component()
    component.grid = [ring]
    winding = _winding_of(faces, bridge_faces, ring)
    if winding is None:
        raise _Rejected("connected to other geometry")
    component.caps[0] = ("BRIDGE", previous_ring, sorted(bridge_faces), winding)
    component.faces.update(bridge_faces)

    extra = set()
    for v in ring:
        extra.update(fi for fi in mesh.vert_faces[v] if fi not in bridge_faces)
    cap = _classify_end(faces, ring, extra, vertex_set)
    component.caps[1] = cap
    if cap is not None:
        component.faces.update(cap[2] if cap[0] in ("FAN", "BRIDGE") else (cap[1],))
    _check_self_contained(mesh, component)
    return component
