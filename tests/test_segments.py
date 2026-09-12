"""Unit tests for the segment rule. Run with a plain Python interpreter:

    python -m unittest discover -s tests
"""

import math
import struct
import unittest

from _loader import core

segments = core.segments

seg = segments.segments_for_diameter
Rule = segments.Rule
uncapped = segments.Rule(max_segments=10 ** 6)  # the extrapolation itself, without the safety cap


def as_float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


class SegmentsForDiameterTest(unittest.TestCase):
    def test_table_anchors_are_reproduced_exactly(self):
        for diameter_cm, expected in ((10, 20), (20, 28), (40, 36), (60, 40), (80, 48), (100, 68)):
            with self.subTest(diameter_cm=diameter_cm):
                self.assertEqual(seg(diameter_cm), expected)

    def test_interpolation_inside_the_table(self):
        cases = (
            (12, 22), (15, 24), (18, 26),
            (25, 30), (30, 32), (35, 34),
            (45, 38), (50, 38), (55, 40),
            (65, 42), (70, 44), (75, 46),
            (85, 54), (90, 58), (95, 64),
        )
        for diameter_cm, expected in cases:
            with self.subTest(diameter_cm=diameter_cm):
                self.assertEqual(seg(diameter_cm), expected)

    def test_below_table_keeps_edge_length_of_first_anchor(self):
        # 10 cm / 20 segments: the count shrinks in proportion to the diameter.
        for diameter_cm, expected in ((9, 18), (8, 16), (6, 12), (5, 10), (4, 8), (3, 6)):
            with self.subTest(diameter_cm=diameter_cm):
                self.assertEqual(seg(diameter_cm), expected)

    def test_minimum_six_segments(self):
        for diameter_cm in (0, 0.001, 0.5, 1, 2, 2.9):
            with self.subTest(diameter_cm=diameter_cm):
                self.assertEqual(seg(diameter_cm), 6)
        self.assertEqual(seg(-5), 6)

    def test_above_table_keeps_edge_length_of_last_anchor(self):
        # 100 cm / 68 segments: the count grows in proportion to the diameter.
        for diameter_cm, expected in ((120, 82), (150, 102), (200, 136), (300, 204), (1000, 680)):
            with self.subTest(diameter_cm=diameter_cm):
                self.assertEqual(uncapped.segments(diameter_cm), expected)
        # the default rule stops at the safety cap: a ten-metre "cylinder" is a scale mistake
        self.assertEqual(seg(1000), segments.MAX_SEGMENTS)

    def test_always_even_and_monotonic(self):
        previous = 0
        for tenth in range(0, 5000):
            diameter_cm = tenth / 10.0
            count = seg(diameter_cm)
            self.assertEqual(count % 2, 0, diameter_cm)
            self.assertGreaterEqual(count, segments.MIN_SEGMENTS, diameter_cm)
            self.assertGreaterEqual(count, previous, diameter_cm)
            previous = count

    def test_float32_property_values_on_anchors(self):
        # Blender operator properties are float32: 0.6 m is stored as
        # 0.60000002 m. The anchors must survive that round trip.
        for upper, expected in segments.ANCHORS:
            metres = as_float32(upper / 100.0)
            with self.subTest(anchor_cm=upper, stored_m=metres):
                self.assertEqual(seg(metres * 100.0), expected)
        scale = as_float32(0.01)
        for upper, expected in segments.ANCHORS:
            with self.subTest(anchor_cm=upper, scale=scale):
                self.assertEqual(seg(as_float32(upper) * scale * 100.0), expected)

    def test_edge_length_is_the_chord(self):
        # A hexagon inscribed in a unit circle has unit edges.
        self.assertAlmostEqual(segments.edge_length(2.0, 6), 1.0, places=9)
        # Edge length stays flat outside the table.
        below = [segments.edge_length(d, seg(d)) for d in (4, 5, 6, 8, 10)]
        above = [segments.edge_length(d, uncapped.segments(d)) for d in (100, 150, 200, 500)]
        self.assertLess(max(below) - min(below), 0.05)
        self.assertLess(max(above) - min(above), 0.05)
        self.assertAlmostEqual(segments.edge_length(10, 20), 10 * math.sin(math.pi / 20), places=9)

    def test_anchors_are_sorted_and_growing(self):
        bounds = [row[0] for row in segments.ANCHORS]
        counts = [row[1] for row in segments.ANCHORS]
        self.assertEqual(bounds, sorted(bounds))
        self.assertEqual(counts, sorted(counts))

    def test_description_mentions_every_anchor(self):
        text = segments.table_description()
        for upper, count in segments.ANCHORS:
            self.assertIn("%d at %g cm" % (count, upper), text)
        self.assertIn("never below 6", text)


class RuleTest(unittest.TestCase):
    def test_default_rule_matches_the_module_functions(self):
        rule = segments.Rule()
        self.assertEqual(rule.anchors, segments.ANCHORS)
        for diameter_cm in (3, 5, 10, 15, 60, 100, 250):
            self.assertEqual(rule.segments(diameter_cm), seg(diameter_cm))

    def test_custom_anchors_change_everything(self):
        rule = segments.Rule([(10, 12), (50, 40)])
        self.assertEqual(rule.segments(10), 12)
        self.assertEqual(rule.segments(50), 40)
        self.assertEqual(rule.segments(30), 26)   # halfway: 12 + 28/2
        self.assertEqual(rule.segments(5), 6)     # proportional below, then the minimum
        self.assertEqual(rule.segments(100), 80)  # proportional above

    def test_anchors_are_sorted_and_duplicates_collapse(self):
        rule = segments.Rule([(50, 40), (10, 12), (10, 14)])
        self.assertEqual(rule.anchors, ((10.0, 14), (50.0, 40)))

    def test_invalid_or_empty_anchors_fall_back_to_the_studio_table(self):
        self.assertEqual(segments.Rule([]).anchors, segments.ANCHORS)
        self.assertEqual(segments.Rule([(0, 10), (-5, 8)]).anchors, segments.ANCHORS)
        self.assertEqual(segments.Rule(None).segments(40), 36)

    def test_single_anchor_keeps_one_edge_length(self):
        rule = segments.Rule([(20, 30)])
        self.assertEqual(rule.segments(20), 30)
        self.assertEqual(rule.segments(40), 60)
        self.assertEqual(rule.segments(10), 16)  # 15 rounded to even

    def test_minimum_and_odd_counts(self):
        rule = segments.Rule(min_segments=12)
        self.assertEqual(rule.segments(1), 12)
        self.assertEqual(rule.segments(5), 12)
        self.assertEqual(rule.segments(40), 36)
        odd = segments.Rule(even=False)
        self.assertEqual(odd.segments(45), 37)
        self.assertEqual(segments.Rule(even=True).segments(45), 38)

    def test_description_follows_the_anchors(self):
        text = segments.Rule([(12, 16)], min_segments=8).description()
        self.assertIn("16 at 12 cm", text)
        self.assertIn("never below 8", text)


class MaximumTest(unittest.TestCase):
    def test_huge_diameters_are_capped(self):
        # a centimetre asset read as metres asks for 1284 segments at "18.88 m"
        rule = Rule()
        self.assertEqual(rule.segments(1888), 256)
        self.assertTrue(rule.is_capped(1888))
        self.assertFalse(rule.is_capped(100))
        self.assertEqual(Rule(max_segments=1000).segments(1888), 1000)

    def test_odd_maximum_keeps_even_counts(self):
        self.assertEqual(Rule(max_segments=255).segments(1888), 254)
        self.assertEqual(Rule(max_segments=255, even=False).segments(1888), 255)

    def test_maximum_never_undercuts_the_minimum(self):
        self.assertEqual(Rule(min_segments=12, max_segments=4).segments(1.0), 12)


if __name__ == "__main__":
    unittest.main()