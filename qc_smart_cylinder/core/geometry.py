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
"""Ring geometry: fitting an ellipse to a cross-section and resampling it.

Pure Python on purpose (tuples instead of mathutils) so the fixer's geometry
can be unit-tested with a plain interpreter.

A cross-section of a cylindrical form is a closed ring of vertices. For a
straight cylinder it is a circle; where a pipe bends with a mitre joint it is
an ellipse (a circle stretched across the joint); a lathe profile gives
circles of different radii. All of those are ellipses, and an ellipse whose
vertices sit at equal parameter angles can be recovered exactly from the
vertex cloud: the principal axes come from a 2D covariance analysis in the
ring plane, and the semi-axes are sqrt(2 * variance) along each axis.
"""

import math

_EPSILON = 1e-12


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a):
    return math.sqrt(dot(a, a))


def normalize(a):
    size = length(a)
    return mul(a, 1.0 / size) if size > _EPSILON else (0.0, 0.0, 0.0)


def centroid(points):
    n = float(len(points))
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def polygon_normal(points):
    """Newell's method: area-weighted normal of a closed polygon (unnormalized)."""
    nx = ny = nz = 0.0
    count = len(points)
    for i in range(count):
        p = points[i]
        q = points[(i + 1) % count]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    return (nx, ny, nz)


class RingFit:
    """An ellipse fitted to a ring of vertices.

    ``points(n)`` regenerates the ring with ``n`` vertices at equal parameter
    angles, starting at the same angle as the original first vertex and
    running in the same direction, so consecutive rings stay untwisted.
    """

    __slots__ = ("center", "normal", "axis_a", "axis_b", "a", "b", "phase", "residual", "count")

    def __init__(self, center, normal, axis_a, axis_b, a, b, phase, residual, count):
        self.center = center
        self.normal = normal
        self.axis_a = axis_a
        self.axis_b = axis_b
        self.a = a
        self.b = b
        self.phase = phase
        self.residual = residual
        self.count = count

    @property
    def minor_diameter(self):
        """Twice the smaller semi-axis: the pipe diameter even at a mitre joint."""
        return 2.0 * min(self.a, self.b)

    @property
    def major_diameter(self):
        return 2.0 * max(self.a, self.b)

    @property
    def is_round(self):
        """True when the vertices lie on the fitted ellipse (within 3 %)."""
        return self.residual <= 0.03

    def point_at(self, angle):
        return add(
            self.center,
            add(mul(self.axis_a, self.a * math.cos(angle)), mul(self.axis_b, self.b * math.sin(angle))),
        )

    def angle_of(self, point):
        """Parameter angle of a point in this fit's frame, in radians.

        ``angle_of(points(n)[k])`` is ``phase + 2 pi k / n`` (modulo 2 pi); any
        point of space is projected onto the ring plane first.
        """
        d = sub(point, self.center)
        x = dot(d, self.axis_a) / self.a if self.a > _EPSILON else 0.0
        y = dot(d, self.axis_b) / self.b if self.b > _EPSILON else 0.0
        return math.atan2(y, x)

    def points(self, n, start=None):
        """``n`` vertices at equal parameter angles, from ``start`` (default: the original first vertex)."""
        phase = self.phase if start is None else start
        step = 2.0 * math.pi / n
        return [self.point_at(phase + k * step) for k in range(n)]


def fit_ring(points):
    """Fit an ellipse to a closed ring of 3D points (ordered around the ring)."""
    count = len(points)
    center = centroid(points)
    normal = normalize(polygon_normal(points))
    if normal == (0.0, 0.0, 0.0):
        # Collapsed ring (all vertices at one point, or on a line).
        axis = (1.0, 0.0, 0.0)
        return RingFit(center, (0.0, 0.0, 1.0), axis, (0.0, 1.0, 0.0), 0.0, 0.0, 0.0, 0.0, count)

    # In-plane basis.
    helper = min(((abs(normal[0]), (1.0, 0.0, 0.0)),
                  (abs(normal[1]), (0.0, 1.0, 0.0)),
                  (abs(normal[2]), (0.0, 0.0, 1.0))), key=lambda item: item[0])[1]
    u = normalize(cross(normal, helper))
    v = cross(normal, u)

    local = []
    sxx = syy = sxy = 0.0
    for p in points:
        d = sub(p, center)
        x = dot(d, u)
        y = dot(d, v)
        local.append((x, y))
        sxx += x * x
        syy += y * y
        sxy += x * y
    sxx /= count
    syy /= count
    sxy /= count

    # Principal axes of the 2D covariance (closed form for a 2x2 matrix).
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    ct = math.cos(theta)
    st = math.sin(theta)
    lambda_a = sxx * ct * ct + 2.0 * sxy * ct * st + syy * st * st
    lambda_b = sxx + syy - lambda_a
    a = math.sqrt(max(2.0 * lambda_a, 0.0))
    b = math.sqrt(max(2.0 * lambda_b, 0.0))
    axis_a = add(mul(u, ct), mul(v, st))
    axis_b = add(mul(u, -st), mul(v, ct))

    def parameter(xy):
        x = (xy[0] * ct + xy[1] * st) / a if a > _EPSILON else 0.0
        y = (-xy[0] * st + xy[1] * ct) / b if b > _EPSILON else 0.0
        return math.atan2(y, x), math.hypot(x, y)

    # The frame is right-handed about the Newell normal, which itself follows
    # the vertex order, so the parameter angle always grows along the ring.
    phase, _radius = parameter(local[0])

    residual = 0.0
    if a > _EPSILON and b > _EPSILON:
        for xy in local:
            _angle, radius = parameter(xy)
            residual = max(residual, abs(radius - 1.0))

    return RingFit(center, normal, axis_a, axis_b, a, b, phase, residual, count)


def resample_closed_polyline(points, n):
    """``n`` points spaced evenly along the closed polyline through ``points``.

    Used for rings that are not ellipses: the shape is kept, only the vertex
    count changes. Starts at the first original vertex.
    """
    count = len(points)
    lengths = [length(sub(points[(i + 1) % count], points[i])) for i in range(count)]
    total = sum(lengths)
    if total <= _EPSILON:
        return [points[0]] * n
    result = []
    step = total / n
    seg = 0
    seg_start = 0.0
    for k in range(n):
        target = k * step
        while seg < count - 1 and seg_start + lengths[seg] < target:
            seg_start += lengths[seg]
            seg += 1
        t = (target - seg_start) / lengths[seg] if lengths[seg] > _EPSILON else 0.0
        p = points[seg]
        q = points[(seg + 1) % count]
        result.append(add(p, mul(sub(q, p), t)))
    return result
