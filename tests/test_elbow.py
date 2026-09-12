"""Unit tests for the elbow finder. Run with a plain Python interpreter:

    python -m unittest discover -s tests
"""

import unittest

import synth
from _loader import core

topology = core.topology
elbow = core.elbow


def find(mesh):
    return topology.find_components(mesh.verts, mesh.faces, mesh.edges)


class ElbowTest(unittest.TestCase):
    def test_bent_rod_with_a_wedge_elbow(self):
        mesh, (r0, ring_m, ring_p, r1) = synth.elbow(n=8, shared=3)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_lengths, [8, 8, 8, 8])
        self.assertEqual(c.band_kind, ["QUAD", "WEDGE", "QUAD"])
        self.assertEqual([set(r) for r in c.grid], [set(r0), set(ring_m), set(ring_p), set(r1)])
        pairs = c.band_pairs[1]
        for k, v in enumerate(c.grid[1]):
            self.assertEqual(c.grid[2][pairs[k]], v if v in ring_p else c.grid[2][pairs[k]])
        shared = [k for k, v in enumerate(c.grid[1]) if v == c.grid[2][pairs[k]]]
        self.assertEqual(len(shared), 3)
        self.assertEqual(len(c.faces), len(mesh.faces))
        self.assertEqual(c.caps, [None, None])
        self.assertIsNotNone(c.band_winding[1])

    def test_next_ring_walks_a_band(self):
        mesh, rings = synth.cylinder(n=6, rings=3, caps=None)
        m = topology._Mesh(mesh.verts, mesh.faces, None)
        nxt, quads = elbow.next_ring(m, rings[0], set())
        self.assertEqual(set(nxt), set(rings[1]))
        self.assertEqual(len(quads), 6)

    def test_plain_forms_are_not_duplicated(self):
        mesh, _rings = synth.cylinder(n=8, rings=3)
        components, _notes = find(mesh)
        self.assertEqual(len(components), 1)


if __name__ == "__main__":
    unittest.main()
