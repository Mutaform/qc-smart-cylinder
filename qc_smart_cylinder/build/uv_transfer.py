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
"""Carrying the original UV layout over to rebuilt rings.

Every original ring vertex carries UVs in the faces around it. Along a ring
those UVs are sampled by the parameter angle of the vertex, one set of
samples per side of the ring (the band towards the previous ring, the band
towards the next ring, or a cap). A new vertex at some angle gets the UV
interpolated between the two original vertices around it, in a face on the
same side, so islands keep their outlines and seams stay where they were.
Inside a band of quads all corners of a new face come from one original quad
(the one under the face centre), so no face straddles a seam.
"""

import bisect
import math

from ..core import topology

TWO_PI = 2.0 * math.pi
_EPSILON = 1e-9


class SourceUVs:
    """The active UV layer of a mesh, indexed by edge and by vertex."""

    def __init__(self, mesh):
        layer = mesh.uv_layers.active
        self.available = layer is not None
        if not self.available:
            return
        self.loop_uv = [(d.uv[0], d.uv[1]) for d in layer.data]
        loops = mesh.loops
        self.poly_verts = []
        self.poly_start = []
        self.edge_polys = {}  # edge_key -> [(poly index, loop of the first vertex, loop of the second)]
        self.vert_loops = {}  # vertex -> [(poly index, loop index)]
        for poly in mesh.polygons:
            start, total = poly.loop_start, poly.loop_total
            verts = [loops[start + i].vertex_index for i in range(total)]
            self.poly_verts.append(verts)
            self.poly_start.append(start)
            for i in range(total):
                a, b = verts[i], verts[(i + 1) % total]
                self.edge_polys.setdefault(topology.edge_key(a, b), []).append(
                    (poly.index, start + i, start + (i + 1) % total))
                self.vert_loops.setdefault(a, []).append((poly.index, start + i))
        self.island = self._islands(len(mesh.polygons))

    def _islands(self, poly_count):
        """UV island id per polygon: polygons joined across edges whose loop UVs agree on both ends."""
        groups = topology.UnionFind(poly_count)
        for entries in self.edge_polys.values():
            if len(entries) < 2:
                continue
            pi0, la0, lb0 = entries[0]
            a0 = self.poly_verts[pi0][la0 - self.poly_start[pi0]]
            uv0 = {a0: self.loop_uv[la0], self.poly_verts[pi0][lb0 - self.poly_start[pi0]]: self.loop_uv[lb0]}
            for pi, la, lb in entries[1:]:
                va = self.poly_verts[pi][la - self.poly_start[pi]]
                vb = self.poly_verts[pi][lb - self.poly_start[pi]]
                same = all(
                    abs(uv0[v][0] - uv[0]) < 1e-5 and abs(uv0[v][1] - uv[1]) < 1e-5
                    for v, uv in ((va, self.loop_uv[la]), (vb, self.loop_uv[lb]))
                )
                if same:
                    groups.union(pi0, pi)
        return [groups.find(i) for i in range(poly_count)]

    def island_of(self, poly):
        return None if poly is None else self.island[poly]

    def edge_uvs(self, a, b, side):
        """(uv at a, uv at b, polygon) for the first polygon along edge a-b whose vertex list satisfies ``side``."""
        for pi, la, lb in self.edge_polys.get(topology.edge_key(a, b), ()):
            verts = self.poly_verts[pi]
            if not side(verts):
                continue
            first_vertex = verts[la - self.poly_start[pi]]
            uv_first, uv_second = self.loop_uv[la], self.loop_uv[lb]
            return (uv_first, uv_second, pi) if first_vertex == a else (uv_second, uv_first, pi)
        return None

    def loop_uv_of(self, poly, vertex):
        """UV of ``vertex`` in polygon ``poly``, or None."""
        for pi, loop in self.vert_loops.get(vertex, ()):
            if pi == poly:
                return self.loop_uv[loop]
        return None

    def vertex_uv(self, v, side):
        """Mean UV of vertex ``v`` over the polygons that satisfy ``side``."""
        total_u = total_v = 0.0
        count = 0
        for pi, loop in self.vert_loops.get(v, ()):
            if side(self.poly_verts[pi]):
                uv = self.loop_uv[loop]
                total_u += uv[0]
                total_v += uv[1]
                count += 1
        if count == 0:
            return None
        return (total_u / count, total_v / count)

    def outline_samples(self, polygon_indices, angle_of):
        """Samples along the outline of an island of polygons (a detached cap)."""
        island = set(polygon_indices)
        counts = {}
        for pi in island:
            verts = self.poly_verts[pi]
            n = len(verts)
            for i in range(n):
                key = topology.edge_key(verts[i], verts[(i + 1) % n])
                counts[key] = counts.get(key, 0) + 1
        samples = RingSamples()
        for key, count in counts.items():
            if count != 1:
                continue
            for pi, la, lb in self.edge_polys.get(key, ()):
                if pi not in island:
                    continue
                verts = self.poly_verts[pi]
                start = self.poly_start[pi]
                va, vb = verts[la - start], verts[lb - start]
                samples.add(angle_of(va), angle_of(vb), self.loop_uv[la], self.loop_uv[lb], pi)
                break
        return samples


class RingSamples:
    """UV as a function of the parameter angle along one side of one ring."""

    __slots__ = ("intervals", "polys", "_cuts", "_cut_list", "_order", "_starts", "_ends")

    def __init__(self):
        self.intervals = []  # (angle_a, angle_b, uv_a, uv_b): angle_a < angle_b, span below pi
        self.polys = []      # the source polygon of every interval (or None)
        self._cuts = None
        self._cut_list = None
        self._order = None   # interval indices sorted by start angle, when the intervals do not overlap
        self._starts = None
        self._ends = None

    def add(self, angle_a, angle_b, uv_a, uv_b, poly=None):
        self._order = self._starts = self._ends = None
        angle_a %= TWO_PI
        angle_b %= TWO_PI
        if angle_b < angle_a:
            angle_b += TWO_PI
        if angle_b - angle_a > math.pi:
            # the edge runs the other way round the ring: flip it
            angle_a, angle_b, uv_a, uv_b = angle_b - TWO_PI, angle_a, uv_b, uv_a
        self.intervals.append((angle_a, angle_b, uv_a, uv_b))
        self.polys.append(poly)

    def seam_indices(self):
        """Interval indices whose start vertex carries a different UV than the previous interval's end.

        Intervals are in ring order, so index k names ring vertex k as a UV seam.
        """
        seams = []
        count = len(self.intervals)
        for k in range(count):
            _a0, _b0, _ua0, ub_prev = self.intervals[k - 1]
            _a1, _b1, ua_this, _ub1 = self.intervals[k]
            if math.hypot(ub_prev[0] - ua_this[0], ub_prev[1] - ua_this[1]) > 1e-5:
                seams.append(k)
        return seams

    def __len__(self):
        return len(self.intervals)

    def _sorted(self):
        """Intervals sorted by start, for a binary search; None when they overlap (a ring
        whose parameter angle does not grow steadily along it: the linear scan then)."""
        if self._order is None:
            order = sorted(range(len(self.intervals)), key=lambda i: self.intervals[i][0])
            starts = [self.intervals[i][0] for i in order]
            ends = [self.intervals[i][1] for i in order]
            if all(starts[i + 1] >= ends[i] - _EPSILON for i in range(len(order) - 1)):
                self._order, self._starts, self._ends = order, starts, ends
            else:
                self._order, self._starts, self._ends = [], [], []
        return self._order

    def _containing_sorted(self, candidate, strict):
        """Sorted position of the interval holding ``candidate`` (strict: a <= c < b), or None."""
        starts, ends = self._starts, self._ends
        pos = bisect.bisect_right(starts, candidate + _EPSILON) - 1
        found = None
        for p in (pos - 1, pos):  # the earlier of two intervals meeting at ``candidate`` wins, as the scan did
            if p < 0 or p >= len(starts):
                continue
            if starts[p] - _EPSILON <= candidate and (candidate < ends[p] - _EPSILON if strict else candidate <= ends[p] + _EPSILON):
                if found is None or self._order[p] < self._order[found]:
                    found = p
        return found

    def index_containing(self, angle):
        """Index of the interval holding ``angle`` (any representative modulo 2 pi), else the nearest."""
        order = self._sorted()
        if order:
            best, best_distance = 0, None
            for candidate in (angle, angle + TWO_PI, angle - TWO_PI):
                p = self._containing_sorted(candidate, False)
                if p is not None:
                    return order[p]
                pos = bisect.bisect_right(self._starts, candidate)
                for q in (pos - 1, pos):
                    if 0 <= q < len(order):
                        distance = min(abs(candidate - self._starts[q]), abs(candidate - self._ends[q]))
                        if best_distance is None or distance < best_distance:
                            best, best_distance = order[q], distance
            return best
        best, best_distance = 0, None
        for index, (a, b, _ua, _ub) in enumerate(self.intervals):
            for candidate in (angle, angle + TWO_PI, angle - TWO_PI):
                if a - _EPSILON <= candidate <= b + _EPSILON:
                    return index
                distance = min(abs(candidate - a), abs(candidate - b))
                if best_distance is None or distance < best_distance:
                    best, best_distance = index, distance
        return best

    def cut_set(self):
        """Indices of intervals whose start boundary is a UV cut (cached)."""
        if self._cuts is None:
            self._cuts = set(self.seam_indices())
            self._cut_list = sorted(self._cuts)
        return self._cuts

    def starts_at(self, index, angle):
        """True when ``angle`` is (modulo 2 pi) exactly the start of interval ``index``."""
        a = self.intervals[index][0]
        return any(abs(candidate - a) < 1e-7 for candidate in (angle, angle + TWO_PI, angle - TWO_PI))

    def _cuts_between(self, first, last):
        """Number of cut indices in the cyclic index range first .. last (inclusive)."""
        cuts = self._cut_list
        if not cuts:
            return 0
        count = len(self.intervals)
        first %= count
        last %= count
        if first <= last:
            return bisect.bisect_right(cuts, last) - bisect.bisect_left(cuts, first)
        return (len(cuts) - bisect.bisect_left(cuts, first)) + bisect.bisect_right(cuts, last)

    def crosses_cut(self, index_from, index_to):
        """True when the shorter way round from one interval to the other passes a UV cut."""
        if index_from == index_to:
            return False
        count = len(self.intervals)
        self.cut_set()
        forward = (index_to - index_from) % count
        backward = (index_from - index_to) % count
        if forward <= backward:
            return self._cuts_between(index_from + 1, index_from + forward) > 0
        return self._cuts_between(index_from - backward + 1, index_from) > 0

    def index_owning(self, angle):
        """The interval that owns ``angle``: a <= angle < b, so a vertex sitting exactly on
        an interval boundary belongs to the interval that starts there."""
        order = self._sorted()
        if order:
            for candidate in (angle, angle + TWO_PI, angle - TWO_PI):
                p = self._containing_sorted(candidate, True)
                if p is not None:
                    return order[p]
            return self.index_containing(angle)
        for index, (a, b, _ua, _ub) in enumerate(self.intervals):
            for candidate in (angle, angle + TWO_PI, angle - TWO_PI):
                if a - _EPSILON <= candidate < b - _EPSILON:
                    return index
        return self.index_containing(angle)

    def index_near(self, angle, island, island_of):
        """The interval under ``angle``, or the nearest one around it that belongs to ``island``."""
        base = self.index_containing(angle)
        if island is None or island_of(self.polys[base]) == island:
            return base
        count = len(self.intervals)
        for step in range(1, min(count, 6)):
            for candidate in ((base + step) % count, (base - step) % count):
                if island_of(self.polys[candidate]) == island:
                    return candidate
        return base

    def sample_in(self, index, angle):
        """UV at ``angle`` on interval ``index``, extrapolating beyond its ends."""
        a, b, uv_a, uv_b = self.intervals[index]
        middle = 0.5 * (a + b)
        candidate = min((angle, angle + TWO_PI, angle - TWO_PI), key=lambda c: abs(c - middle))
        span = b - a
        t = (candidate - a) / span if span > _EPSILON else 0.0
        return (uv_a[0] + (uv_b[0] - uv_a[0]) * t, uv_a[1] + (uv_b[1] - uv_a[1]) * t)

    def sample(self, angle):
        return self.sample_in(self.index_containing(angle), angle)


def ring_side_samples(source, ring, angles, side):
    """Samples along ``ring`` (vertex indices with their angles) in the faces that satisfy ``side``.

    Returns None when some edge of the ring has no face on that side.
    """
    samples = RingSamples()
    n = len(ring)
    for k in range(n):
        a, b = ring[k], ring[(k + 1) % n]
        uvs = source.edge_uvs(a, b, side)
        if uvs is None:
            return None
        samples.add(angles[k], angles[(k + 1) % n], uvs[0], uvs[1], uvs[2])
    return samples


def face_centre_angle(corner_angles):
    """Mean angle of a face's corners, unwrapped around the first corner."""
    first = corner_angles[0]
    total = 0.0
    for angle in corner_angles:
        delta = (angle - first + math.pi) % TWO_PI - math.pi
        total += first + delta
    return total / len(corner_angles)
