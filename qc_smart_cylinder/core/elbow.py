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
"""Bent rods with a hand-made elbow.

A common way to bend a low-poly rod: the two straight parts end in rings
that *share* the vertices on the inside of the bend, while the outside is
filled with a wedge of quads and a pair of triangles. Those shared vertices
break the loop walk of ``topology`` (they have five edges), so here rings
are derived differently: starting from a closed ring at an end of the rod,
the band of quads across every edge gives the next ring, whatever the vertex
valences are. Two such chains whose last rings share vertices and are joined
by a wedge become one form with a "WEDGE" band, which the rebuild reproduces
for any segment count: the shared arc stays shared, quads outside it,
triangles where the arc ends.

Pure Python, unit-tested in ``tests/test_elbow.py``.
"""

from . import topology
from .topology import Component, _Rejected, edge_key


def next_ring(mesh, ring, behind):
    """Across every edge of ``ring`` the one quad not in ``behind``; (next ring in order, quads) or None."""
    count = len(ring)
    far = {}
    quads = []
    for k in range(count):
        a, b = ring[k], ring[(k + 1) % count]
        options = [fi for fi in mesh.edge_quads.get(edge_key(a, b), ()) if fi not in behind]
        if len(options) != 1:
            return None
        fi = options[0]
        face = mesh.faces[fi]
        ia, ib = face.index(a), face.index(b)
        if face[(ia + 1) % 4] == b:
            far_a, far_b = face[(ia - 1) % 4], face[(ib + 1) % 4]
        else:
            far_a, far_b = face[(ia + 1) % 4], face[(ib - 1) % 4]
        if far.setdefault(a, far_a) != far_a or far.setdefault(b, far_b) != far_b:
            return None
        quads.append(fi)
    nxt = [far[v] for v in ring]
    if len(set(nxt)) != count or set(nxt) & set(ring):
        return None
    return nxt, quads


def _walk_chain(mesh, ring):
    """Rings from an end ring inwards, band by band, until the quads run out."""
    # An end ring has quads on one side only.
    for k in range(len(ring)):
        quads = mesh.edge_quads.get(edge_key(ring[k], ring[(k + 1) % len(ring)]), ())
        if len(quads) != 1:
            return None
    rings = [list(ring)]
    bands = []
    behind = set()
    seen = {frozenset(ring)}
    while True:
        step = next_ring(mesh, rings[-1], behind)
        if step is None:
            break
        nxt, quads = step
        key = frozenset(nxt)
        if key in seen:
            break
        seen.add(key)
        rings.append(nxt)
        bands.append(quads)
        behind = set(quads)
    return {"rings": rings, "bands": bands}


def find_elbow_forms(mesh, excluded, closed_loops):
    """Forms made of two rod chains joined by a wedge elbow.

    :param mesh: a ``topology._Mesh``
    :param excluded: vertices already owned by forms found otherwise
    :param closed_loops: vertex cycles found by the loop walk (candidates for end rings)
    :return: (components, notes)
    """
    chains = []
    seen = set()
    for loop in closed_loops:
        key = frozenset(loop)
        if key in seen or any(v in excluded for v in loop):
            continue
        chain = _walk_chain(mesh, list(loop))
        if chain is not None and len(chain["rings"]) >= 2:
            seen.add(key)
            chains.append(chain)

    components = []
    notes = []
    used = set()
    for ia in range(len(chains)):
        if ia in used:
            continue
        tail_a = set(chains[ia]["rings"][-1])
        for ib in range(ia + 1, len(chains)):
            if ib in used:
                continue
            tail_b = set(chains[ib]["rings"][-1])
            if not (tail_a & tail_b):
                continue
            try:
                component = _join_with_wedge(mesh, chains[ia], chains[ib])
            except _Rejected as why:
                notes.append(str(why))
                used.update((ia, ib))
                break
            components.append(component)
            used.update((ia, ib))
            break
    return components, notes


def _join_with_wedge(mesh, chain_a, chain_b):
    faces = mesh.faces
    ring_m = chain_a["rings"][-1]
    ring_p = chain_b["rings"][-1]
    if len(ring_m) != len(ring_p):
        raise _Rejected("elbow rings of different lengths")
    band_faces = set()
    for band in chain_a["bands"] + chain_b["bands"]:
        band_faces.update(band)
    shared = set(ring_m) & set(ring_p)
    both = set(ring_m) | set(ring_p)
    wedge = set()
    for v in both:
        wedge.update(fi for fi in mesh.vert_faces[v] if fi not in band_faces)
    # the outer ends may carry caps; those touch only the end rings, never the elbow rings
    end_faces = set()
    for chain in (chain_a, chain_b):
        for v in chain["rings"][0]:
            end_faces.update(fi for fi in mesh.vert_faces[v] if fi not in band_faces)
    wedge -= end_faces
    for fi in wedge:
        if not set(faces[fi]) <= both:
            raise _Rejected("elbow wedge touches other geometry")

    # Pairs across the wedge: an edge of a wedge face from an M-only vertex to a P-only vertex.
    only_m = set(ring_m) - shared
    only_p = set(ring_p) - shared
    partner = {}
    for fi in wedge:
        face = faces[fi]
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            if a in only_m and b in only_p:
                pair = (a, b)
            elif b in only_m and a in only_p:
                pair = (b, a)
            else:
                continue
            if partner.setdefault(pair[0], pair[1]) != pair[1]:
                raise _Rejected("elbow wedge is irregular")
    if set(partner) != only_m or set(partner.values()) != only_p:
        raise _Rejected("elbow wedge is irregular")

    def pairing_for(ring_p_ordered):
        index_p = {v: k for k, v in enumerate(ring_p_ordered)}
        return [index_p[v] if v in shared else index_p[partner[v]] for v in ring_m]

    pairs = pairing_for(ring_p)
    count = len(ring_m)
    if len(set(pairs)) != count:
        raise _Rejected("elbow wedge is irregular")
    # Orient and rotate the second chain so that position k of ring P pairs with
    # position k of ring M: the rebuild then works index by index across the wedge.
    forward = sum(1 for k in range(count) if pairs[(k + 1) % count] == (pairs[k] + 1) % count)
    backward = sum(1 for k in range(count) if pairs[(k + 1) % count] == (pairs[k] - 1) % count)
    if backward > forward:
        chain_b["rings"] = [r[::-1] for r in chain_b["rings"]]
        ring_p = chain_b["rings"][-1]
        pairs = pairing_for(ring_p)
    offset = pairs[0]
    if offset:
        chain_b["rings"] = [r[offset:] + r[:offset] for r in chain_b["rings"]]
        ring_p = chain_b["rings"][-1]
        pairs = pairing_for(ring_p)
    if pairs != list(range(count)):
        raise _Rejected("elbow wedge is irregular")

    # Winding of the wedge relative to ring M: a wedge quad holding two consecutive M-only vertices.
    winding = None
    for k in range(count):
        a, b = ring_m[k], ring_m[(k + 1) % count]
        if a in shared or b in shared:
            continue
        for fi in wedge:
            face = faces[fi]
            if a in face and b in face and len(face) == 4:
                i0 = face.index(a)
                winding = 1 if face[(i0 + 1) % 4] == b else -1
                break
        if winding is not None:
            break
    if winding is None:
        raise _Rejected("elbow wedge is irregular")

    component = Component()
    rings_a = chain_a["rings"]
    rings_b = chain_b["rings"][::-1]
    component.grid = [list(r) for r in rings_a] + [list(r) for r in rings_b]
    component.closed = False
    for band in chain_a["bands"]:
        component.band_faces.append(list(band))
        component.band_kind.append("QUAD")
        component.band_winding.append(None)  # set from the ordered row below
    wedge_index = len(component.band_faces)
    component.band_faces.append(sorted(wedge))
    component.band_kind.append("WEDGE")
    component.band_winding.append(winding)
    component.band_pairs[wedge_index] = pairs
    for band in chain_b["bands"][::-1]:
        component.band_faces.append(list(band))
        component.band_kind.append("QUAD")
        component.band_winding.append(None)
    # windings of the quad bands from the grid rows themselves
    for j, kind in enumerate(component.band_kind):
        if kind == "QUAD":
            ring_a = component.grid[j]
            row = component.band_faces[j]
            component.band_winding[j] = topology._winding_of(faces, row, ring_a)
            if component.band_winding[j] is None:
                raise _Rejected("elbow band is irregular")
            # quads must sit in ring order for the rebuild (band_faces[j][k] across edge k)
            ordered = []
            for k in range(len(ring_a)):
                key = edge_key(ring_a[k], ring_a[(k + 1) % len(ring_a)])
                shared_quads = [fi for fi in row if key in mesh.face_edges[fi]]
                if len(shared_quads) != 1:
                    raise _Rejected("elbow band is irregular")
                ordered.append(shared_quads[0])
            component.band_faces[j] = ordered
    component.faces.update(band_faces)
    component.faces.update(wedge)

    grid_verts = set()
    for ring in component.grid:
        grid_verts.update(ring)
    for end, ring in ((0, component.grid[0]), (1, component.grid[-1])):
        extra = set()
        for v in ring:
            extra.update(fi for fi in mesh.vert_faces[v] if fi not in component.faces)
        cap = topology._classify_end(faces, ring, extra, grid_verts)
        if cap is not None and cap[0] == "BRIDGE":
            raise _Rejected("connected to other geometry")
        component.caps[end] = cap
        if cap is not None:
            component.faces.update(cap[2] if cap[0] == "FAN" else (cap[1],))
    topology._check_self_contained(mesh, component)
    return component
