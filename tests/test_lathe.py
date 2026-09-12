"""Unit tests for the lathe-form finder. Run with a plain Python interpreter:

    python -m unittest discover -s tests
"""

import unittest

import synth
from _loader import core

topology = core.topology


def find(mesh):
    return topology.find_components(mesh.verts, mesh.faces, mesh.edges)


class ReductionLatheTest(unittest.TestCase):
    def test_rings_of_mixed_counts_with_quad_and_triangle_reductions(self):
        mesh, rings = synth.reduction_lathe()
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_lengths, [36, 36, 18, 18, 9])
        self.assertEqual(c.band_kind, ["BRIDGE"] * 4)
        self.assertEqual(c.caps[0][0], "NGON")
        self.assertEqual(c.caps[1][0], "NGON")
        self.assertEqual(len(c.faces), len(mesh.faces))
        self.assertEqual(c.vertex_indices(), set(range(len(mesh.verts))))
        for ring, expected in zip(c.grid, rings):
            self.assertEqual(set(ring), set(expected))
        self.assertEqual(len(set(c.band_winding)), 1)

    def test_fan_caps_and_full_triangulation(self):
        mesh, _rings = synth.reduction_lathe(caps="FAN", triangulate=True)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_lengths, [36, 36, 18, 18, 9])
        self.assertEqual(c.caps[0][0], "FAN")
        self.assertEqual(c.caps[1][0], "FAN")
        self.assertEqual(len(c.faces), len(mesh.faces))

    def test_rings_are_oriented_consistently(self):
        mesh, _rings = synth.reduction_lathe()
        c = find(mesh)[0][0]
        normals = [core.geometry.polygon_normal([mesh.verts[i] for i in ring]) for ring in c.grid]
        self.assertTrue(all(n[2] > 0 for n in normals) or all(n[2] < 0 for n in normals))

    def test_cube_is_still_not_a_form(self):
        components, notes = find(synth.cube())
        self.assertEqual(components, [])

    def test_foreign_face_on_a_ring_is_rejected_with_a_note(self):
        mesh, rings = synth.reduction_lathe()
        extra = mesh.add_verts([(5.0, 5.0, 2.0), (5.0, 6.0, 2.0)])
        mesh.faces.append((rings[2][0], extra[0], extra[1]))
        components, notes = find(mesh)
        self.assertEqual(components, [])
        self.assertTrue(notes, "a reason is reported")

    def test_grid_forms_are_not_duplicated_by_the_lathe_finder(self):
        mesh, _rings = synth.cylinder(n=12, rings=3)
        components, notes = find(mesh)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].band_kind, ["QUAD", "QUAD"])


if __name__ == "__main__":
    unittest.main()
