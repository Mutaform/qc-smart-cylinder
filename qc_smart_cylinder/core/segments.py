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
"""Segment count of QC Smart Cylinder as a function of the diameter.

Deliberately free of ``bpy`` imports so the rule can be unit-tested with a
plain Python interpreter (see ``tests/test_segments.py``).

The studio's low-poly table lists one segment count per diameter range. The
idea behind it is a roughly constant edge length: a bigger cylinder gets more
segments. A ``Rule`` turns such a table into a continuous function:

* the table rows are anchor points, each row's count holding at the top of
  its range (10 cm -> 20, 20 cm -> 28, ... 100 cm -> 68);
* between anchors the count is interpolated linearly, so every diameter gets
  its own step instead of one count for a whole range;
* outside the table the edge length of the nearest anchor is kept: below the
  first anchor the count shrinks in proportion to the diameter, above the
  last it grows in proportion;
* the result is rounded to an even number (the cylinder stays mirror
  symmetric on both axes) and never drops below a minimum.

The anchors, the minimum and the even rounding are editable in the add-on
preferences; ``ANCHORS`` and ``MIN_SEGMENTS`` are the studio defaults.
"""

import math

# (diameter in centimetres, segments) -- the studio table, one point per row.
ANCHORS = (
    (10.0, 20),
    (20.0, 28),
    (40.0, 36),
    (60.0, 40),
    (80.0, 48),
    (100.0, 68),
)

MIN_SEGMENTS = 6


class Rule:
    """The diameter -> segments rule for one set of anchor points."""

    __slots__ = ("anchors", "min_segments", "even")

    def __init__(self, anchors=None, min_segments=MIN_SEGMENTS, even=True):
        cleaned = {}
        for diameter, count in (anchors or ()):
            if diameter > 0 and count > 0:
                cleaned[float(diameter)] = int(count)  # a later duplicate diameter wins
        if not cleaned:
            cleaned = dict(ANCHORS)
        self.anchors = tuple(sorted(cleaned.items()))
        self.min_segments = max(1, int(min_segments))
        self.even = bool(even)

    def raw(self, diameter_cm):
        """Unrounded segment count: interpolated inside the anchors, proportional outside."""
        first_d, first_n = self.anchors[0]
        last_d, last_n = self.anchors[-1]
        if diameter_cm <= first_d:
            return first_n * diameter_cm / first_d
        if diameter_cm >= last_d:
            return last_n * diameter_cm / last_d
        for (d0, n0), (d1, n1) in zip(self.anchors, self.anchors[1:]):
            if diameter_cm <= d1:
                return n0 + (n1 - n0) * (diameter_cm - d0) / (d1 - d0)
        return float(last_n)

    def segments(self, diameter_cm):
        """Segment count for a diameter in centimetres."""
        raw = self.raw(max(float(diameter_cm), 0.0))
        if self.even:
            count = int(math.floor(raw / 2.0 + 0.5)) * 2
        else:
            count = int(math.floor(raw + 0.5))
        return max(self.min_segments, count)

    def description(self):
        """One-line, human-readable form of the rule for tooltips."""
        anchors = ", ".join("%d at %g cm" % (n, d) for d, n in self.anchors)
        return (
            "%s; interpolated in between, edge length kept outside that range, "
            "%s, never below %d" % (anchors, "even counts" if self.even else "any count", self.min_segments)
        )


DEFAULT_RULE = Rule()


def segments_for_diameter(diameter_cm, rule=None):
    """Segment count for a diameter in centimetres under ``rule`` (default: the studio table)."""
    return (rule or DEFAULT_RULE).segments(diameter_cm)


def edge_length(diameter, segments):
    """Length of one edge of a regular ``segments``-gon inscribed in ``diameter``.

    Same unit as ``diameter``; this is the chord, i.e. the real edge length.
    """
    return diameter * math.sin(math.pi / segments)


def table_description(rule=None):
    return (rule or DEFAULT_RULE).description()
