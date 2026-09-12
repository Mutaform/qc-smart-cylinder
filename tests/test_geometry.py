"""Unit tests for the ring geometry. Run with a plain Python interpreter:

    python -m unittest discover -s tests
"""

import math
import unittest

from _loader import core

geometry = core.geometry


def circle(n, radius=1.0, phase=0.0, center=(0.0, 0.0, 0.0), reverse=False, stretch=1.0):
    pts = []
    for k in range(n):
        t = phase + 2.0 * math.pi * k / n
        pts.append((center[0] + radius * stretch * math.cos(t), center[1] + radius * math.sin(t), center[2]))
    return pts[::-1] if reverse else pts


def tilt(points, angle):
    """Rotate points about the X axis."""
    c, s = math.cos(angle), math.sin(angle)
    return [(x, y * c - z * s, y * s + z * c) for x, y, z in points]


def dist(a, b):
    return geometry.length(geometry.sub(a, b))


class FitRingTest(unittest.TestCase):
    def test_circle_is_recovered(self):
        for n in (6, 8, 20, 68):
            fit = geometry.fit_ring(circle(n, radius=0.35, center=(1.0, 2.0, 3.0)))
            self.assertAlmostEqual(fit.a, 0.35, places=9)
            self.assertAlmostEqual(fit.b, 0.35, places=9)
            self.assertAlmostEqual(fit.minor_diameter, 0.7, places=9)
            self.assertAlmostEqual(fit.residual, 0.0, places=9)
            self.assertTrue(fit.is_round)
            for c, expected in zip(fit.center, (1.0, 2.0, 3.0)):
                self.assertAlmostEqual(c, expected, places=9)

    def test_regenerated_ring_starts_at_the_first_vertex_and_runs_the_same_way(self):
        original = circle(8, radius=2.0, phase=0.3)
        fit = geometry.fit_ring(original)
        same = fit.points(8)
        for p, q in zip(original, same):
            self.assertLess(dist(p, q), 1e-9)
        more = fit.points(24)
        self.assertLess(dist(more[0], original[0]), 1e-9)
        self.assertLess(dist(more[3], original[1]), 1e-9)

    def test_reversed_ring_keeps_its_direction(self):
        original = circle(10, radius=1.5, phase=1.0, reverse=True)
        fit = geometry.fit_ring(original)
        same = fit.points(10)
        for p, q in zip(original, same):
            self.assertLess(dist(p, q), 1e-9)

    def test_tilted_ellipse_is_recovered(self):
        original = tilt(circle(16, radius=0.5, stretch=1.7), 0.6)
        fit = geometry.fit_ring(original)
        self.assertAlmostEqual(max(fit.a, fit.b), 0.85, places=9)
        self.assertAlmostEqual(min(fit.a, fit.b), 0.5, places=9)
        self.assertAlmostEqual(fit.minor_diameter, 1.0, places=9)
        self.assertTrue(fit.is_round)
        same = fit.points(16)
        for p, q in zip(original, same):
            self.assertLess(dist(p, q), 1e-9)

    def test_square_section_is_not_round(self):
        square = [(1, 1, 0), (-1, 1, 0), (-1, -1, 0), (1, -1, 0), (1, 0, 0), (0, 1, 0)]
        # six points, four corners plus two edge midpoints: not on one ellipse
        fit = geometry.fit_ring(square)
        self.assertFalse(fit.is_round)

    def test_angle_of_matches_the_generated_angles(self):
        fit = geometry.fit_ring(tilt(circle(12, radius=0.7, phase=0.4, stretch=1.3), 0.5))
        for k, p in enumerate(fit.points(12)):
            expected = (fit.phase + 2.0 * math.pi * k / 12) % (2.0 * math.pi)
            self.assertAlmostEqual(fit.angle_of(p) % (2.0 * math.pi), expected, places=9)

    def test_points_can_start_at_any_angle(self):
        fit = geometry.fit_ring(circle(8, radius=1.0))
        seam = fit.angle_of(circle(8, radius=1.0)[3])
        pts = fit.points(20, start=seam)
        self.assertLess(dist(pts[0], circle(8, radius=1.0)[3]), 1e-9)
        self.assertEqual(len(pts), 20)

    def test_collapsed_ring(self):
        fit = geometry.fit_ring([(1.0, 1.0, 1.0)] * 6)
        self.assertEqual(fit.a, 0.0)
        for p in fit.points(8):
            self.assertLess(dist(p, (1.0, 1.0, 1.0)), 1e-12)


class ResampleTest(unittest.TestCase):
    def test_even_spacing_along_a_square(self):
        square = [(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)]
        pts = geometry.resample_closed_polyline(square, 8)
        self.assertEqual(len(pts), 8)
        self.assertEqual(pts[0], (0.0, 0.0, 0.0))
        self.assertLess(dist(pts[1], (2.0, 0.0, 0.0)), 1e-9)
        self.assertLess(dist(pts[2], (4.0, 0.0, 0.0)), 1e-9)
        self.assertLess(dist(pts[5], (2.0, 4.0, 0.0)), 1e-9)
        for i in range(8):
            self.assertAlmostEqual(dist(pts[i], pts[(i + 1) % 8]), 2.0, places=9)


if __name__ == "__main__":
    unittest.main()
