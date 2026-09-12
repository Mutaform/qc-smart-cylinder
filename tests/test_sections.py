"""Unit tests for the per-section counts. Run with a plain Python interpreter:

    python -m unittest discover -s tests
"""

import unittest

from _loader import core

sections = core.sections
Rule = core.segments.Rule


class SplitSectionsTest(unittest.TestCase):
    def test_constant_diameter_is_one_section(self):
        self.assertEqual(sections.split_sections([40.0] * 6), [[0, 1, 2, 3, 4, 5]])

    def test_collar_splits_at_both_steps(self):
        # tube - flange out - collar - flange in - tube
        self.assertEqual(sections.split_sections([40, 40, 97, 97, 40, 40]), [[0, 1], [2, 3], [4, 5]])

    def test_gentle_taper_stays_together_until_the_drift_exceeds_the_step(self):
        # 5 % per ring: a new section every time the drift from the section start passes 25 %
        # of the smaller diameter (100 -> 81.5 is 22.8 % of 81.5 and stays, 77.4 is 29 % and leaves)
        diameters = [100 * (0.95 ** j) for j in range(12)]
        result = sections.split_sections(diameters, step=0.25)
        self.assertEqual(result[0], [0, 1, 2, 3, 4])
        self.assertEqual(sum(len(s) for s in result), 12)

    def test_split_does_not_depend_on_the_walking_direction(self):
        # 80 -> 60 is 25 % of 80 but 33 % of 60: the same split whichever end the form is walked from
        self.assertEqual(sections.split_sections([80, 80, 60, 60]), [[0, 1], [2, 3]])
        self.assertEqual(sections.split_sections([60, 60, 80, 80]), [[0, 1], [2, 3]])

    def test_joined_band_never_splits(self):
        # a wedge elbow between rings 1 and 2: both arms must share one count whatever the drift
        self.assertEqual(sections.split_sections([10, 10, 14, 14], joined_bands={1}), [[0, 1, 2, 3]])
        self.assertEqual(sections.split_sections([10, 10, 14, 14]), [[0, 1], [2, 3]])

    def test_step_threshold_is_respected(self):
        self.assertEqual(sections.split_sections([40, 48], step=0.25), [[0, 1]])
        self.assertEqual(sections.split_sections([40, 52], step=0.25), [[0], [1]])
        self.assertEqual(sections.split_sections([40, 48], step=0.10), [[0], [1]])

    def test_mitre_pipe_minor_diameters_do_not_split(self):
        self.assertEqual(sections.split_sections([10.0, 10.0000024, 9.99999, 10.0]), [[0, 1, 2, 3]])

    def test_empty(self):
        self.assertEqual(sections.split_sections([]), [])

    def test_a_marked_break_starts_a_section_whatever_the_drift(self):
        # 40 -> 36 is a 11 % drift, well within the step; a flat ledge there still splits
        self.assertEqual(sections.split_sections([40, 40, 36, 36]), [[0, 1, 2, 3]])
        self.assertEqual(sections.split_sections([40, 40, 36, 36], breaks={2}), [[0, 1], [2, 3]])


class SectionCountsTest(unittest.TestCase):
    def test_collar_gets_its_own_count(self):
        counts = sections.section_counts([40, 40, 97, 97, 40, 40], Rule())
        self.assertEqual(counts, [36, 36, 66, 66, 36, 36])

    def test_whole_form_when_uniform(self):
        counts = sections.section_counts([60] * 4, Rule())
        self.assertEqual(counts, [40, 40, 40, 40])

    def test_source_applies_inside_a_section(self):
        diameters = [60, 60, 50, 48, 20]  # 60/60/50/48 drift < 25 % of 48, 20 is a new section
        by_max = sections.section_counts(diameters, Rule(), 'MAX')
        by_min = sections.section_counts(diameters, Rule(), 'MIN')
        self.assertEqual(by_max, [40, 40, 40, 40, 28])
        self.assertEqual(by_min, [38, 38, 38, 38, 28])

    def test_ledge_between_anchor_diameters_gets_both_anchor_counts(self):
        counts = sections.section_counts([80, 80, 60, 60], Rule(), breaks={2})
        self.assertEqual(counts, [48, 48, 40, 40])

    def test_close_counts_across_a_quad_band_merge(self):
        # a small knob: 1.8 / 3.4 / 3.8 cm -> 6 / 6 / 8, one even step apart across quads -> all 8
        diameters = [1.8, 2.8, 3.2, 3.4, 3.7, 3.8]
        split = sections.section_counts(diameters, Rule())
        self.assertEqual(split, [6, 6, 6, 6, 8, 8])
        merged = sections.section_counts(diameters, Rule(), quad_bands={0, 1, 2, 3, 4})
        self.assertEqual(merged, [8] * 6)

    def test_close_counts_across_a_bridge_stay_apart(self):
        # the same rings joined by reduction bands (triangles already): each keeps its own count
        diameters = [1.8, 2.8, 3.2, 3.4, 3.7, 3.8]
        self.assertEqual(sections.section_counts(diameters, Rule(), quad_bands=set()), [6, 6, 6, 6, 8, 8])

    def test_merge_never_chains_beyond_one_even_step(self):
        # a funnel 10 / 12.5 / 15.6 / 19.5 cm asks for 20 / 22 / 24 / 28: 20 and 22 may share a count,
        # 24 may not join them (it would put the 10 cm ring two steps off), 28 stays alone
        diameters = [10, 12.5, 15.6, 19.5]
        self.assertEqual(sections.section_counts(diameters, Rule(), quad_bands={0, 1, 2}), [22, 22, 24, 28])

    def test_closed_form_merges_across_the_closing_band(self):
        # a ring band whose tube thickens and thins: rings 5 and 0 are one even step apart across band 5
        diameters = [10, 13, 16, 19, 16, 13]
        counts = sections.section_counts(diameters, Rule(), quad_bands=set(range(6)), closed=True)
        self.assertEqual(counts[0], counts[5])

    def test_wedge_elbow_arms_share_one_count(self):
        counts = sections.section_counts([10, 10, 14, 14], Rule(), quad_bands={0, 1, 2}, joined_bands={1})
        self.assertEqual(counts, [24, 24, 24, 24])

    def test_large_count_differences_do_not_merge(self):
        # a flange 60 -> 40 cm across quads: 40 and 36 are two steps apart, the zipper stays
        self.assertEqual(sections.section_counts([60, 60, 40, 40], Rule(), quad_bands={0, 1, 2}), [40, 40, 36, 36])

    def test_pick_diameter(self):
        self.assertEqual(sections.pick_diameter([10, 20, 60]), 60)
        self.assertEqual(sections.pick_diameter([10, 20, 60], 'MIN'), 10)
        self.assertEqual(sections.pick_diameter([10, 20, 60], 'MEAN'), 30)


if __name__ == "__main__":
    unittest.main()
