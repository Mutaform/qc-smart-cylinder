"""Unit tests for the cylindrical-form search. Run with a plain Python interpreter:

    python -m unittest discover -s tests
"""

import unittest

import synth
from _loader import core

topology = core.topology
geometry = core.geometry


def find(mesh):
    return topology.find_components(mesh.verts, mesh.faces, mesh.edges)


def check_grid(test, mesh, component):
    """Every grid row is a closed ring of consecutive edges, every column a rail."""
    edges = set()
    for face in mesh.faces:
        n = len(face)
        for i in range(n):
            edges.add(topology.edge_key(face[i], face[(i + 1) % n]))
    grid = component.grid
    n = component.segments
    for j, ring in enumerate(grid):
        for k in range(n):
            test.assertIn(topology.edge_key(ring[k], ring[(k + 1) % n]), edges, "ring %d not consecutive" % j)
    for j in range(component.band_count):
        ring_a, ring_b = grid[j], grid[(j + 1) % component.ring_count]
        for k in range(n):
            test.assertIn(topology.edge_key(ring_a[k], ring_b[k]), edges, "rail broken between rings %d and %d" % (j, j + 1))


class CylinderTest(unittest.TestCase):
    def test_plain_cylinder_with_ngon_caps(self):
        mesh, _rings = synth.cylinder(n=8, rings=2)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.segments, 8)
        self.assertEqual(c.ring_count, 2)
        self.assertFalse(c.closed)
        self.assertEqual(c.caps[0][0], "NGON")
        self.assertEqual(c.caps[1][0], "NGON")
        self.assertEqual(len(c.faces), 8 + 2)
        self.assertEqual(c.vertex_indices(), set(range(16)))
        check_grid(self, mesh, c)

    def test_cylinder_with_loop_cuts_and_fan_caps(self):
        mesh, _rings = synth.cylinder(n=12, rings=5, caps="FAN")
        components, _notes = find(mesh)
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.segments, 12)
        self.assertEqual(c.ring_count, 5)
        self.assertEqual(c.caps[0][0], "FAN")
        self.assertEqual(c.caps[1][0], "FAN")
        self.assertEqual(len(c.cap_centres()), 2)
        self.assertEqual(len(c.faces), 12 * 4 + 24)
        check_grid(self, mesh, c)

    def test_open_ended_cylinder(self):
        mesh, _rings = synth.cylinder(n=6, rings=3, caps=None)
        components, _notes = find(mesh)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].caps, [None, None])
        check_grid(self, mesh, components[0])

    def test_grid_is_aligned_by_topology_not_by_index(self):
        mesh, _rings = synth.cylinder(n=10, rings=4, rotate_rings=3, twist=0.2)
        components, _notes = find(mesh)
        self.assertEqual(len(components), 1)
        check_grid(self, mesh, components[0])

    def test_band_winding_follows_face_orientation(self):
        mesh, _rings = synth.cylinder(n=8, rings=2)
        normal_winding = find(mesh)[0][0].band_winding[0]
        flipped = synth.Mesh()
        flipped.verts = mesh.verts
        flipped.faces = [f[::-1] for f in mesh.faces]
        flipped_winding = find(flipped)[0][0].band_winding[0]
        self.assertEqual(normal_winding, -flipped_winding)

    def test_already_correct_count_is_still_found(self):
        mesh, _rings = synth.cylinder(n=20, rings=2)
        components, _notes = find(mesh)
        self.assertEqual(components[0].segments, 20)


class OtherFormsTest(unittest.TestCase):
    def test_lathe_profile(self):
        mesh, _rings = synth.lathe([1.0, 1.0, 1.4, 1.4, 0.6, 0.6, 0.3], n=24)
        components, _notes = find(mesh)
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_count, 7)
        self.assertEqual(c.segments, 24)
        check_grid(self, mesh, c)
        radii = [geometry.fit_ring([mesh.verts[i] for i in ring]).a for ring in c.grid]
        self.assertAlmostEqual(max(radii), 1.4, places=9)
        self.assertAlmostEqual(min(radii), 0.3, places=9)

    def test_pipe_with_mitre_joints(self):
        path = [(0, 0, 0), (0, 0, 3), (2, 0, 4), (4, 0, 4), (4, 0, 0)]
        mesh, _rings = synth.pipe(path, radius=0.5, n=16)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_count, 5)
        self.assertEqual(c.segments, 16)
        check_grid(self, mesh, c)
        for ring in c.grid:
            fit = geometry.fit_ring([mesh.verts[i] for i in ring])
            self.assertTrue(fit.is_round)
            self.assertAlmostEqual(fit.minor_diameter, 1.0, places=6)

    def test_torus(self):
        mesh, _rings = synth.torus(n_minor=8, n_major=12)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertTrue(c.closed)
        self.assertEqual(c.segments, 8)
        self.assertEqual(c.ring_count, 12)
        self.assertEqual(c.band_count, 12)
        check_grid(self, mesh, c)

    def test_torus_split_into_two_counts_is_one_closed_chain(self):
        # what a sectioned fix leaves behind: half the rings 12, half 16, zippers both ways round
        import math as _m
        mesh = synth.Mesh()
        rings = []
        for i in range(12):
            t = 2.0 * _m.pi * i / 12
            centre = (2.0 * _m.cos(t), 2.0 * _m.sin(t), 0.0)
            radial = (_m.cos(t), _m.sin(t), 0.0)
            rings.append(mesh.add_verts(synth._ring(centre, 0.5, 12 if i < 6 else 16, radial, (0.0, 0.0, 1.0))))
        for i in range(12):
            a, b = rings[i], rings[(i + 1) % 12]
            if len(a) == len(b):
                mesh.band(a, b)
            else:
                synth.bridge(mesh, a, b)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertTrue(c.closed)
        self.assertEqual(c.ring_count, 12)
        self.assertEqual(c.band_count, 12)
        self.assertEqual(sorted(c.ring_lengths), [12] * 6 + [16] * 6)
        self.assertEqual(c.band_kind.count("BRIDGE"), 2)
        self.assertEqual(len(c.faces), len(mesh.faces))

    def test_excluded_vertices_are_neither_walked_nor_complained_about(self):
        mesh = synth.cylinder_with_triangle(n=8)
        components, notes = find(mesh)
        self.assertEqual(components, [])
        self.assertTrue(notes)
        components, notes = topology.find_components(mesh.verts, mesh.faces, mesh.edges, excluded=set(range(len(mesh.verts))))
        self.assertEqual((components, notes), ([], []))

    def test_profiled_ring_band_is_subdivided_around_the_big_circle(self):
        mesh, rings = synth.profiled_ring(n_around=48)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertTrue(c.closed)
        self.assertEqual(c.ring_lengths, [48] * 8)
        self.assertEqual(c.band_count, 8)
        for ring, expected in zip(c.grid, rings):
            self.assertIn(set(ring), [set(r) for r in rings])
        check_grid(self, mesh, c)

    def test_doughnut_still_uses_the_small_circles(self):
        mesh, _rings = synth.torus(n_minor=10, n_major=24, major=3.0, minor=0.4)
        c = find(mesh)[0][0]
        self.assertEqual(c.segments, 10)
        self.assertEqual(c.ring_count, 24)

    def test_sphere_between_poles(self):
        mesh, _rings = synth.sphere(n=12, rings=5)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.segments, 12)
        self.assertEqual(c.ring_count, 5)
        self.assertEqual(c.caps[0][0], "FAN")
        self.assertEqual(c.caps[1][0], "FAN")
        check_grid(self, mesh, c)


class SectionedFormsTest(unittest.TestCase):
    def test_tube_with_collar_is_one_form_with_bridges(self):
        mesh, rings = synth.collar_tube(n_tube=12, n_collar=20)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_lengths, [12, 12, 20, 20, 12, 12])
        self.assertEqual(c.band_kind, ["QUAD", "BRIDGE", "QUAD", "BRIDGE", "QUAD"])
        self.assertEqual(c.caps[0][0], "NGON")
        self.assertEqual(c.caps[1][0], "NGON")
        self.assertEqual(len(c.band_faces[1]), 12 + 20)
        self.assertEqual(len(c.faces), len(mesh.faces))
        self.assertEqual(c.vertex_indices(), set(range(len(mesh.verts))))
        for ring, expected in zip(c.grid, rings):
            self.assertEqual(set(ring), set(expected))

    def test_thin_flange_is_a_lone_ring_section(self):
        mesh, rings = synth.collar_tube(n_tube=12, n_collar=20, lone=True)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(len(components), 1)
        c = components[0]
        self.assertEqual(c.ring_lengths, [12, 12, 20, 12, 12])
        self.assertEqual(c.band_kind, ["QUAD", "BRIDGE", "BRIDGE", "QUAD"])
        self.assertEqual(set(c.grid[2]), set(rings[2]))
        self.assertEqual(len(c.faces), len(mesh.faces))

    def test_bridge_winding_matches_the_quads(self):
        mesh, _rings = synth.collar_tube()
        c = find(mesh)[0][0]
        self.assertEqual(set(c.band_winding), {c.band_winding[0]})
        flipped = synth.Mesh()
        flipped.verts = mesh.verts
        flipped.faces = [f[::-1] for f in mesh.faces]
        d = find(flipped)[0][0]
        self.assertEqual(d.band_winding, [-w for w in c.band_winding])

    def test_bridge_to_foreign_geometry_is_rejected(self):
        mesh, rings = synth.collar_tube()
        extra = mesh.add_verts([(5.0, 5.0, 1.2), (5.0, 6.0, 1.2)])
        mesh.faces.append((rings[2][0], extra[0], extra[1]))
        components, notes = find(mesh)
        self.assertEqual(components, [])
        self.assertIn("connected to other geometry", notes)


class RejectionTest(unittest.TestCase):
    def test_cube_has_no_form(self):
        components, notes = find(synth.cube())
        self.assertEqual(components, [])
        self.assertEqual(notes, [])

    def test_cylinder_with_a_quad_welded_to_a_ring_is_rejected(self):
        # The extra quad breaks the ring loop itself: no form, no note.
        components, _notes = find(synth.cylinder_on_cube())
        self.assertEqual(components, [])

    def test_cylinder_with_a_triangle_welded_to_a_ring_is_rejected_with_a_note(self):
        # The ring loop survives (triangles do not take part in loop walking),
        # so the form is found and then refused as not self-contained.
        components, notes = find(synth.cylinder_with_triangle())
        self.assertEqual(components, [])
        self.assertIn("connected to other geometry", notes)

    def test_two_forms_in_one_mesh(self):
        a, _r = synth.cylinder(n=8, rings=2)
        b, _r = synth.lathe([0.5, 0.5, 0.2], n=12)
        mesh = synth.merge(a, b)
        components, notes = find(mesh)
        self.assertEqual(notes, [])
        self.assertEqual(sorted(c.segments for c in components), [8, 12])
        self.assertEqual(len(components[0].vertex_indices() & components[1].vertex_indices()), 0)

    def test_loose_edge_on_a_ring_vertex_is_rejected(self):
        mesh, rings = synth.cylinder(n=8, rings=2)
        extra = mesh.add_verts([(5.0, 5.0, 5.0)])[0]
        mesh.edges.append((rings[0][0], extra))
        components, notes = find(mesh)
        self.assertEqual(components, [])
        self.assertIn("connected to other geometry", notes)


if __name__ == "__main__":
    unittest.main()
