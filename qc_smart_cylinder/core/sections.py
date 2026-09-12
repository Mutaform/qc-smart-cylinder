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
"""Splitting a form into sections that each get their own segment count.

A tube with a collar, a lathe profile with a knob, a sphere between its
poles: their rings differ in diameter, and the studio rule says wider gets
more segments, narrower fewer. This module groups consecutive rings into
sections wherever the diameter has drifted from the section start by more
than a step -- or wherever the caller marks a break, such as a flat ledge
between two radii, which is a new part whatever the drift -- and gives every
section the count its own diameter calls for. Bands between sections of
different counts are later bridged -- which is why two neighbouring sections
whose counts differ by no more than one even step are merged again when the
band between them is a band of quads: a zipper of triangles there would be
worse than an edge a few per cent off.

Pure Python, unit-tested in ``tests/test_sections.py``.
"""


def pick_diameter(diameters, source='MAX'):
    """One diameter for a group of rings: the largest, the average or the smallest."""
    if source == 'MIN':
        return min(diameters)
    if source == 'MEAN':
        return sum(diameters) / len(diameters)
    return max(diameters)


def split_sections(diameters, step=0.25, breaks=(), joined_bands=()):
    """Group ring indices into runs whose diameter stays within ``step`` of the run start.

    ``diameters`` is one value per ring along the form; ``step`` is a fraction
    (0.25 = 25 %) of the smaller of the two diameters compared, so the split
    does not depend on which end the form is walked from; ``breaks`` are ring
    indices that start a new section regardless of the drift; ``joined_bands``
    are band indices (band j joins rings j and j + 1) across which the two
    rings must stay in one section whatever the drift -- a wedge elbow needs
    one count on both of its rings. Returns a list of index lists, in order.
    """
    if not diameters:
        return []
    sections = [[0]]
    reference = diameters[0]
    for j in range(1, len(diameters)):
        diameter = diameters[j]
        drift = abs(diameter - reference) > step * max(min(diameter, reference), 1e-9)
        if (j - 1) in joined_bands:
            sections[-1].append(j)
            reference = diameter  # the section goes on from the joined ring
        elif j in breaks or drift:
            sections.append([j])
            reference = diameter
        else:
            sections[-1].append(j)
    return sections


def section_counts(diameters_cm, rule, source='MAX', step=0.25, breaks=(), quad_bands=None, merge_below=2,
                   joined_bands=(), closed=False):
    """Segment count per ring: each section gets the count for its own diameter.

    ``quad_bands`` are the band indices (band j joins rings j and j + 1) made of
    quads; two neighbouring sections split at such a band are merged back
    while the counts the rule gives their members stay within ``merge_below``
    of each other, so the quads stay and no ring drifts more than one even
    step from its own count. ``joined_bands`` never split (see
    ``split_sections``). On a ``closed`` form the last band joins the last
    ring back to the first.
    """
    sections = split_sections(diameters_cm, step, breaks, joined_bands)

    def count_of(section):
        return rule.segments(pick_diameter([diameters_cm[j] for j in section], source))

    ring_counts = [rule.segments(d) for d in diameters_cm]   # what every ring asks for on its own
    spread = [(min(ring_counts[j] for j in section), max(ring_counts[j] for j in section)) for section in sections]
    counts_by_section = [count_of(section) for section in sections]
    if quad_bands is not None:
        merged = True
        while merged and len(sections) > 1:
            merged = False
            pairs = [(k, k + 1) for k in range(len(sections) - 1)]
            if closed:
                pairs.append((len(sections) - 1, 0))
            for k, k1 in pairs:
                band = sections[k][-1]
                if band not in quad_bands:
                    continue
                low = min(spread[k][0], spread[k1][0])
                high = max(spread[k][1], spread[k1][1])
                if high - low > merge_below:
                    continue
                joined = sections[k] + sections[k1]
                for index in sorted((k, k1), reverse=True):
                    del sections[index], spread[index], counts_by_section[index]
                at = min(k, k1) if k1 != 0 else 0
                sections.insert(at, joined)
                spread.insert(at, (low, high))
                counts_by_section.insert(at, count_of(joined))
                merged = True
                break
    counts = [0] * len(diameters_cm)
    for section, count in zip(sections, counts_by_section):
        for j in section:
            counts[j] = count
    return counts
