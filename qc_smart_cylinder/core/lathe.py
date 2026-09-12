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
"""Finding lathe-like forms whose bands are not clean quad grids.

Game assets often build a turned part from rings of different vertex counts
(36, 24, 18, 16 ...) joined by reduction bands that mix quads and triangles.
The loop-walking search of ``topology`` breaks on those. Here rings are found
geometrically instead: an axis is taken from a closed loop of the part (or
from its principal axes), vertices are grouped by height along that axis and
by radius, and a group is a ring when it is one closed cycle of edges with
one radius. Consecutive rings are joined by whatever faces use only their
vertices; the result is a ``Component`` whose bands are all "BRIDGE" kind, so
the rebuild makes quads where counts agree and triangle zippers where they do
not.

Pure Python, unit-tested in ``tests/test_lathe.py``.
"""

import math

from . import geometry
from . import topology

_HEIGHT_TOLERANCE = 2e-3     # fraction of the island size: rings closer than this merge into one level
_RADIUS_TOLERANCE = 0.03     # fraction of the ring radius: all vertices of a ring within this
_RADIUS_GAP = 0.05           # fraction: a gap between sorted radii larger than this splits a level
_MIN_RING = 5                # a smaller "ring" is a square tube or a cube, not a lathe part


def find_lathe_forms(mesh, excluded_vertices, closed_loops):
    """Lathe-like forms among the faces not touching ``excluded_vertices``.

    :param mesh: a ``topology._Mesh``
    :param excluded_vertices: vertices already owned by forms found otherwise
    :param closed_loops: vertex cycles found by the loop walk; their planes hint the axes
    :return: (components, notes)
    """
    components = []
    notes = []
    islands = [(faces, verts) for faces, verts in _islands(mesh, excluded_vertices) if len(verts) >= 2 * _MIN_RING]
    # Islands are vertex-disjoint: bucket the closed loops by island in one pass.
    island_of = {}
    for index, (_faces, verts) in enumerate(islands):
        for v in verts:
            island_of[v] = index
    loops_of = {}
    for loop in closed_loops:
        index = island_of.get(loop[0])
        if index is not None and all(island_of.get(v) == index for v in loop):
            loops_of.setdefault(index, []).append(loop)
    for index, (island_faces, island_verts) in enumerate(islands):
        hints = []
        for loop in loops_of.get(index, ()):
            fit = geometry.fit_ring([mesh.verts[v] for v in loop])
            if fit.normal != (0.0, 0.0, 0.0):
                hints.append((fit.normal, fit.center))
        centroid = geometry.centroid([mesh.verts[v] for v in island_verts])
        axes = _unique_axes([(n, c) for n, c in hints] + [(a, centroid) for a in _principal_axes(mesh, island_verts)])
        found = None
        reasons = []
        for axis, origin in axes:
            try:
                found = _along_axis(mesh, island_faces, island_verts, axis, origin)
                break
            except topology._Rejected as why:
                reasons.append(str(why))
        if found is not None:
            components.append(found)
        elif reasons:
            notes.append(reasons[0])
    return components, notes


def _islands(mesh, excluded):
    visited = set()
    for seed in range(len(mesh.faces)):
        if seed in visited or any(v in excluded for v in mesh.faces[seed]):
            continue
        faces = []
        verts = set()
        stack = [seed]
        visited.add(seed)
        while stack:
            fi = stack.pop()
            faces.append(fi)
            for v in mesh.faces[fi]:
                verts.add(v)
                for gi in mesh.vert_faces[v]:
                    if gi not in visited and not any(w in excluded for w in mesh.faces[gi]):
                        visited.add(gi)
                        stack.append(gi)
        yield faces, verts


def _unique_axes(candidates):
    unique = []
    for axis, origin in candidates:
        axis = geometry.normalize(axis)
        if axis == (0.0, 0.0, 0.0):
            continue
        if any(abs(geometry.dot(axis, other)) > 0.999 for other, _o in unique):
            continue
        unique.append((axis, origin))
    return unique


def _principal_axes(mesh, verts):
    """Eigenvectors of the covariance of the island's vertices (Jacobi rotations)."""
    points = [mesh.verts[v] for v in verts]
    c = geometry.centroid(points)
    m = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = geometry.sub(p, c)
        for i in range(3):
            for j in range(3):
                m[i][j] += d[i] * d[j]
    vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _sweep in range(30):
        off = sum(m[i][j] ** 2 for i in range(3) for j in range(3) if i != j)
        if off < 1e-18:
            break
        for p in range(3):
            for q in range(p + 1, 3):
                if abs(m[p][q]) < 1e-18:
                    continue
                theta = 0.5 * math.atan2(2.0 * m[p][q], m[q][q] - m[p][p])
                cs, sn = math.cos(theta), math.sin(theta)
                for k in range(3):
                    mkp, mkq = m[k][p], m[k][q]
                    m[k][p] = cs * mkp - sn * mkq
                    m[k][q] = sn * mkp + cs * mkq
                for k in range(3):
                    mpk, mqk = m[p][k], m[q][k]
                    m[p][k] = cs * mpk - sn * mqk
                    m[q][k] = sn * mpk + cs * mqk
                for k in range(3):
                    vkp, vkq = vectors[k][p], vectors[k][q]
                    vectors[k][p] = cs * vkp - sn * vkq
                    vectors[k][q] = sn * vkp + cs * vkq
    return [(vectors[0][i], vectors[1][i], vectors[2][i]) for i in range(3)]


def _along_axis(mesh, island_faces, island_verts, axis, origin):
    verts = mesh.verts
    heights = {v: geometry.dot(geometry.sub(verts[v], origin), axis) for v in island_verts}
    radial = {}
    for v in island_verts:
        d = geometry.sub(verts[v], origin)
        radial[v] = geometry.length(geometry.sub(d, geometry.mul(axis, heights[v])))
    size = max(max(heights.values()) - min(heights.values()), max(radial.values()), 1e-9)
    tolerance = size * _HEIGHT_TOLERANCE

    # Levels along the axis.
    ordered = sorted(island_verts, key=lambda v: heights[v])
    levels = [[ordered[0]]]
    for v in ordered[1:]:
        if heights[v] - heights[levels[-1][-1]] <= tolerance:
            levels[-1].append(v)
        else:
            levels.append([v])

    # Rings: one radius, one closed cycle of edges. Lone vertices near the axis may be fan centres.
    rings = []
    centres = set()
    for level in levels:
        for group in _split_by_radius(level, radial):
            if len(group) == 1:
                if radial[group[0]] <= size * _HEIGHT_TOLERANCE * 5:
                    centres.add(group[0])
                    continue
                raise topology._Rejected("rings interrupted by reductions")
            ring = _cycle(mesh, set(group))
            if ring is None:
                raise topology._Rejected("rings interrupted by reductions")
            if len(ring) < _MIN_RING:
                raise topology._Rejected("rings too small for a lathe part")
            normal = geometry.polygon_normal([verts[v] for v in ring])
            if geometry.dot(normal, axis) < 0:
                ring.reverse()
            rings.append(ring)
    if len(rings) < 2:
        raise topology._Rejected("rings interrupted by reductions")

    ring_of = {}
    for index, ring in enumerate(rings):
        for v in ring:
            ring_of[v] = index

    # Faces: a band between two rings, a cap on one ring, or a fan towards a centre.
    bands = {}
    caps = {}
    fans = {}
    for fi in island_faces:
        face = mesh.faces[fi]
        touched = set()
        centre = None
        for v in face:
            if v in ring_of:
                touched.add(ring_of[v])
            elif v in centres:
                centre = v
            else:
                raise topology._Rejected("rings interrupted by reductions")
        if centre is not None:
            if len(touched) != 1:
                raise topology._Rejected("faces span more than two rings")
            fans.setdefault(next(iter(touched)), []).append(fi)
        elif len(touched) == 1:
            caps.setdefault(next(iter(touched)), []).append(fi)
        elif len(touched) == 2:
            bands.setdefault(frozenset(touched), []).append(fi)
        else:
            raise topology._Rejected("faces span more than two rings")

    neighbours = {index: set() for index in range(len(rings))}
    for pair in bands:
        a, b = tuple(pair)
        neighbours[a].add(b)
        neighbours[b].add(a)
    if any(len(n) > 2 for n in neighbours.values()):
        raise topology._Rejected("rings branch")
    ends = [index for index, n in neighbours.items() if len(n) == 1]
    if len(ends) not in (0, 2):
        raise topology._Rejected("rings do not form one chain")
    closed = not ends
    start = ends[0] if ends else 0
    order = [start]
    previous = None
    while True:
        options = [n for n in neighbours[order[-1]] if n != previous]
        if not options:
            break
        nxt = options[0]
        if nxt == start:
            break
        if nxt in order:
            raise topology._Rejected("rings do not form one chain")
        previous = order[-1]
        order.append(nxt)
    if len(order) != len(rings):
        raise topology._Rejected("rings do not form one chain")

    component = topology.Component()
    component.grid = [list(rings[index]) for index in order]
    component.closed = closed
    band_count = len(order) if closed else len(order) - 1
    for j in range(band_count):
        a, b = order[j], order[(j + 1) % len(order)]
        faces = sorted(bands[frozenset((a, b))])
        winding = topology._winding_of(mesh.faces, faces, rings[a])
        if winding is None:
            raise topology._Rejected("rings interrupted by reductions")
        component.band_faces.append(faces)
        component.band_kind.append("BRIDGE")
        component.band_winding.append(winding)
        component.faces.update(faces)
    for index in order[1:-1] if not closed else order:
        if index in caps or index in fans:
            raise topology._Rejected("faces span more than two rings")
    if not closed:
        for end, index in ((0, order[0]), (1, order[-1])):
            extra = set(caps.get(index, ())) | set(fans.get(index, ()))
            cap = topology._classify_end(mesh.faces, rings[index], extra, set(ring_of))
            component.caps[end] = cap
            if cap is not None:
                component.faces.update(cap[2] if cap[0] in ("FAN", "BRIDGE") else (cap[1],))
            if cap is not None and cap[0] == "BRIDGE":
                raise topology._Rejected("rings interrupted by reductions")
    if len(component.faces) != len(island_faces):
        raise topology._Rejected("faces span more than two rings")
    topology._check_self_contained(mesh, component)
    return component


def _split_by_radius(level, radial):
    ordered = sorted(level, key=lambda v: radial[v])
    groups = [[ordered[0]]]
    for v in ordered[1:]:
        reference = radial[groups[-1][-1]]
        if radial[v] - reference <= max(reference * _RADIUS_GAP, 1e-9):
            groups[-1].append(v)
        else:
            groups.append([v])
    result = []
    for group in groups:
        mean = sum(radial[v] for v in group) / len(group)
        if len(group) > 1 and any(abs(radial[v] - mean) > max(mean * _RADIUS_TOLERANCE, 1e-9) for v in group):
            raise topology._Rejected("rings interrupted by reductions")
        result.append(group)
    return result


def _cycle(mesh, vertex_set):
    """The vertices as one closed cycle of edges, or None."""
    return topology.vertex_cycle(mesh, vertex_set)
