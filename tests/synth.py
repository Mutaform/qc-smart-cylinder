"""Synthetic meshes for the topology and geometry tests. No bpy."""

import math


def _ring(center, radius, n, axis_u, axis_v, phase=0.0, stretch=1.0):
    pts = []
    for k in range(n):
        t = phase + 2.0 * math.pi * k / n
        x = radius * math.cos(t) * stretch
        y = radius * math.sin(t)
        pts.append((
            center[0] + axis_u[0] * x + axis_v[0] * y,
            center[1] + axis_u[1] * x + axis_v[1] * y,
            center[2] + axis_u[2] * x + axis_v[2] * y,
        ))
    return pts


class Mesh:
    def __init__(self):
        self.verts = []
        self.faces = []
        self.edges = []

    def add_verts(self, pts):
        base = len(self.verts)
        self.verts.extend(pts)
        return list(range(base, base + len(pts)))

    def band(self, ring_a, ring_b, flip=False):
        n = len(ring_a)
        for k in range(n):
            k1 = (k + 1) % n
            quad = (ring_a[k], ring_a[k1], ring_b[k1], ring_b[k])
            self.faces.append(quad[::-1] if flip else quad)

    def ngon(self, ring, flip=False):
        self.faces.append(tuple(ring[::-1] if flip else ring))

    def fan(self, ring, centre_co):
        c = self.add_verts([centre_co])[0]
        n = len(ring)
        for k in range(n):
            self.faces.append((ring[k], ring[(k + 1) % n], c))
        return c


def cylinder(n=8, rings=2, radius=1.0, height=2.0, caps="NGON", phase=0.0, rotate_rings=0, twist=0.0):
    """Straight cylinder along Z. ``rotate_rings`` shifts the vertex index of
    each successive ring so the grid has to be aligned by topology, ``twist``
    rotates each ring in space (a twisted cylinder)."""
    m = Mesh()
    rings_idx = []
    for j in range(rings):
        z = -height / 2.0 + height * j / (rings - 1)
        pts = _ring((0.0, 0.0, z), radius, n, (1, 0, 0), (0, 1, 0), phase + twist * j)
        idx = m.add_verts(pts)
        shift = (rotate_rings * j) % n
        idx = idx[shift:] + idx[:shift]
        rings_idx.append(idx)
    for j in range(rings - 1):
        m.band(rings_idx[j], rings_idx[j + 1])
    if caps == "NGON":
        m.ngon(rings_idx[0], flip=True)
        m.ngon(rings_idx[-1])
    elif caps == "FAN":
        m.fan(rings_idx[0][::-1], (0.0, 0.0, -height / 2.0))
        m.fan(rings_idx[-1], (0.0, 0.0, height / 2.0))
    return m, rings_idx


def lathe(radii, n=12, caps="NGON"):
    """Rings of the given radii stacked along Z one unit apart."""
    m = Mesh()
    rings_idx = []
    for j, r in enumerate(radii):
        idx = m.add_verts(_ring((0.0, 0.0, float(j)), r, n, (1, 0, 0), (0, 1, 0)))
        rings_idx.append(idx)
    for j in range(len(radii) - 1):
        m.band(rings_idx[j], rings_idx[j + 1])
    if caps == "NGON":
        m.ngon(rings_idx[0], flip=True)
        m.ngon(rings_idx[-1])
    return m, rings_idx


def pipe(path, radius=0.5, n=16, caps=None):
    """Tube along a polyline with mitre joints (stretched circles at the corners)."""
    m = Mesh()
    rings_idx = []
    count = len(path)
    for i, p in enumerate(path):
        if i == 0:
            tangent = _norm(_sub(path[1], path[0]))
            normal = tangent
            stretch = 1.0
        elif i == count - 1:
            tangent = _norm(_sub(path[-1], path[-2]))
            normal = tangent
            stretch = 1.0
        else:
            t_in = _norm(_sub(path[i], path[i - 1]))
            t_out = _norm(_sub(path[i + 1], path[i]))
            tangent = t_in
            normal = _norm(_add(t_in, t_out))
            half = math.acos(max(-1.0, min(1.0, _dot(t_in, t_out)))) / 2.0
            stretch = 1.0 / math.cos(half)
        # profile: u along the bend plane (stretched), v perpendicular
        helper = (0.0, 0.0, 1.0) if abs(normal[2]) < 0.9 else (1.0, 0.0, 0.0)
        v_axis = _norm(_cross(normal, helper))
        u_axis = _norm(_cross(v_axis, normal))
        idx = m.add_verts(_ring(p, radius, n, u_axis, v_axis, stretch=stretch))
        rings_idx.append(idx)
    for i in range(count - 1):
        m.band(rings_idx[i], rings_idx[i + 1])
    if caps == "NGON":
        m.ngon(rings_idx[0], flip=True)
        m.ngon(rings_idx[-1])
    return m, rings_idx


def torus(n_minor=8, n_major=12, major=2.0, minor=0.5):
    m = Mesh()
    rings_idx = []
    for i in range(n_major):
        t = 2.0 * math.pi * i / n_major
        centre = (major * math.cos(t), major * math.sin(t), 0.0)
        radial = (math.cos(t), math.sin(t), 0.0)
        idx = m.add_verts(_ring(centre, minor, n_minor, radial, (0.0, 0.0, 1.0)))
        rings_idx.append(idx)
    for i in range(n_major):
        m.band(rings_idx[i], rings_idx[(i + 1) % n_major])
    return m, rings_idx


def sphere(n=12, rings=5, radius=1.0):
    """UV sphere: rings between two pole fans."""
    m = Mesh()
    rings_idx = []
    for j in range(1, rings + 1):
        phi = math.pi * j / (rings + 1)
        idx = m.add_verts(_ring((0.0, 0.0, radius * math.cos(phi)), radius * math.sin(phi), n, (1, 0, 0), (0, 1, 0)))
        rings_idx.append(idx)
    for j in range(rings - 1):
        m.band(rings_idx[j], rings_idx[j + 1])
    m.fan(rings_idx[0], (0.0, 0.0, radius))
    m.fan(rings_idx[-1][::-1], (0.0, 0.0, -radius))
    return m, rings_idx


def cube():
    m = Mesh()
    m.add_verts([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])
    m.faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return m


def merge(*meshes):
    out = Mesh()
    for mesh in meshes:
        base = len(out.verts)
        out.verts.extend(mesh.verts)
        out.faces.extend(tuple(v + base for v in f) for f in mesh.faces)
        out.edges.extend((a + base, b + base) for a, b in mesh.edges)
    return out


def cylinder_on_cube(n=8):
    """A cylinder whose bottom ring is welded to a cube's top face vertices: not self-contained."""
    m, rings_idx = cylinder(n=n, rings=2, caps="NGON")
    bottom = rings_idx[0]
    # hang extra geometry off one bottom vertex
    extra = m.add_verts([(3.0, 0.0, -1.0), (3.0, 1.0, -1.0), (2.0, 1.0, -1.0)])
    m.faces.append((bottom[0], extra[0], extra[1], extra[2]))
    return m


def cylinder_with_triangle(n=8):
    """A cylinder with a stray triangle hanging off one ring vertex."""
    m, rings_idx = cylinder(n=n, rings=2, caps="NGON")
    extra = m.add_verts([(3.0, 0.0, -1.0), (3.0, 1.0, -1.0)])
    m.faces.append((rings_idx[0][0], extra[0], extra[1]))
    return m


def bridge(mesh, ring_a, ring_b):
    """Triangle band between two rings of different length (angle zipper)."""
    import math as _m
    ca = _centroid([mesh.verts[i] for i in ring_a])

    def angle(i):
        x, y, _z = _sub(mesh.verts[i], ca)
        return _m.atan2(y, x) % (2 * _m.pi)

    a_angles = [angle(i) for i in ring_a]
    b_sorted = sorted(ring_b, key=angle)
    b_angles = [angle(i) for i in b_sorted]
    na, nb = len(ring_a), len(b_sorted)
    j = min(range(nb), key=lambda t: (b_angles[t] - a_angles[0]) % (2 * _m.pi))
    i = 0
    steps_a = steps_b = 0
    base_b = j
    while steps_a < na or steps_b < nb:
        next_a = a_angles[(i + 1) % na] + (2 * _m.pi if (i + 1) >= na else 0)
        wrapped_b = (j + 1 - base_b) >= nb
        next_b = b_angles[(j + 1) % nb] + (2 * _m.pi if wrapped_b or (j + 1) % nb < base_b else 0)
        if steps_b >= nb or (steps_a < na and next_a <= next_b):
            mesh.faces.append((ring_a[i % na], ring_a[(i + 1) % na], b_sorted[j % nb]))
            i += 1
            steps_a += 1
        else:
            mesh.faces.append((ring_a[i % na], b_sorted[(j + 1) % nb], b_sorted[j % nb]))
            j += 1
            steps_b += 1


def collar_tube(n_tube=12, n_collar=20, lone=False):
    """Tube with a wider collar: tube rings, bridge, collar ring(s), bridge, tube rings.

    ``lone`` makes the collar a single ring (a thin flange) instead of two.
    """
    m = Mesh()
    tube_a = [m.add_verts(_ring((0, 0, dz), 0.5, n_tube, (1, 0, 0), (0, 1, 0))) for dz in (0.0, 1.0)]
    collar = [m.add_verts(_ring((0, 0, 1.0), 1.2, n_collar, (1, 0, 0), (0, 1, 0)))]
    if not lone:
        collar.append(m.add_verts(_ring((0, 0, 1.5), 1.2, n_collar, (1, 0, 0), (0, 1, 0))))
    top_z = 1.0 if lone else 1.5
    tube_b = [m.add_verts(_ring((0, 0, top_z + dz), 0.5, n_tube, (1, 0, 0), (0, 1, 0))) for dz in (0.0, 1.0)]
    m.band(tube_a[0], tube_a[1])
    bridge(m, tube_a[1], collar[0])
    for a, b in zip(collar, collar[1:]):
        m.band(a, b)
    bridge(m, collar[-1], tube_b[0])
    m.band(tube_b[0], tube_b[1])
    m.ngon(tube_a[0], flip=True)
    m.ngon(tube_b[1])
    return m, tube_a + collar + tube_b


def reduction_band(mesh, ring_a, ring_b):
    """Band between rings where len(ring_a) == 2 * len(ring_b): quads and triangles alternate."""
    na, nb = len(ring_a), len(ring_b)
    assert na == 2 * nb
    for i in range(nb):
        a0, a1, a2 = ring_a[2 * i], ring_a[2 * i + 1], ring_a[(2 * i + 2) % na]
        b0, b1 = ring_b[i], ring_b[(i + 1) % nb]
        mesh.faces.append((a0, a1, b1, b0))
        mesh.faces.append((a1, a2, b1))


def reduction_lathe(caps="NGON", triangulate=False):
    """A turned part with rings of 36, 36, 18, 18, 9 vertices joined by 2:1 reductions.

    Radii grow with the count, like a lamp foot: 1.8, 1.8, 1.0, 1.0, 0.5.
    """
    m = Mesh()
    rings = []
    for j, (n, r) in enumerate(((36, 1.8), (36, 1.8), (18, 1.0), (18, 1.0), (9, 0.5))):
        rings.append(m.add_verts(_ring((0, 0, float(j)), r, n, (1, 0, 0), (0, 1, 0))))
    m.band(rings[0], rings[1])
    reduction_band(m, rings[1], rings[2])
    m.band(rings[2], rings[3])
    reduction_band(m, rings[3], rings[4])
    if caps == "NGON":
        m.ngon(rings[0], flip=True)
        m.ngon(rings[-1])
    elif caps == "FAN":
        m.fan(rings[0][::-1], (0.0, 0.0, 0.0))
        m.fan(rings[-1], (0.0, 0.0, 4.0))
    if triangulate:
        faces = []
        for f in m.faces:
            if len(f) == 4:
                faces.append((f[0], f[1], f[2]))
                faces.append((f[0], f[2], f[3]))
            elif len(f) > 4:
                for i in range(1, len(f) - 1):
                    faces.append((f[0], f[i], f[i + 1]))
            else:
                faces.append(f)
        m.faces = faces
    return m, rings


def profiled_ring(n_around=48, profile=None):
    """A ring band: a closed polygon profile (radius, z) swept around Z. Torus topology, square-ish profile."""
    if profile is None:
        profile = [(2.0, 0.0), (2.1, 0.0), (2.1, 0.5), (2.0, 0.5), (2.0, 0.3), (1.9, 0.3), (1.9, 0.2), (2.0, 0.2)]
    m = Mesh()
    rings = []
    for r, z in profile:
        rings.append(m.add_verts(_ring((0.0, 0.0, z), r, n_around, (1, 0, 0), (0, 1, 0))))
    count = len(rings)
    for i in range(count):
        m.band(rings[i], rings[(i + 1) % count])
    return m, rings


def elbow(n=8, shared=3, bend=0.6, stub=0.3, length=3.0, radius=0.5):
    """A rod bent with a hand-made elbow.

    Ring R0 (an open end), a short band to ring M, then ring P which shares
    ``shared`` consecutive vertices with M and has the rest rotated by ``bend``
    about the chord through the shared arc, a wedge of quads (and two
    triangles) between M and P on the outside, and a long band to ring R1.
    """
    import math as _m
    m = Mesh()
    r0 = m.add_verts(_ring((0.0, 0.0, stub), radius, n, (1, 0, 0), (0, 1, 0)))
    ring_m_pts = _ring((0.0, 0.0, 0.0), radius, n, (1, 0, 0), (0, 1, 0))
    ring_m = m.add_verts(ring_m_pts)
    # shared arc: vertices 0 .. shared-1 (around +X); the rest rotate about the chord
    # through the ends of the arc, the way a rod is bent by hand (the far side opens
    # away from the first rod, towards -Z)
    pivot = ring_m_pts[0]
    chord = _sub(ring_m_pts[shared - 1], pivot)
    far = ring_m_pts[shared + (n - shared) // 2]
    rotate = _rotation_about(pivot, chord, bend)
    if rotate(far)[2] > 0.0:
        rotate = _rotation_about(pivot, chord, -bend)

    ring_p = []
    p_pts = []
    for k in range(n):
        if k < shared:
            ring_p.append(ring_m[k])
            p_pts.append(ring_m_pts[k])
        else:
            q = rotate(ring_m_pts[k])
            p_pts.append(q)
            ring_p.append(m.add_verts([q])[0])
    # far ring: ring P translated along the rotated axis
    direction = rotate((0.0, 0.0, -1.0))
    r1 = m.add_verts([(p[0] + direction[0] * length, p[1] + direction[1] * length, p[2] + direction[2] * length) for p in p_pts])
    m.band(r0, ring_m)
    for k in range(n):
        k1 = (k + 1) % n
        a_shared, b_shared = k < shared, k1 < shared
        if a_shared and b_shared:
            continue
        if not a_shared and not b_shared:
            m.faces.append((ring_m[k], ring_m[k1], ring_p[k1], ring_p[k]))
        elif a_shared:
            m.faces.append((ring_m[k], ring_m[k1], ring_p[k1]))
        else:
            m.faces.append((ring_m[k], ring_m[k1], ring_p[k]))
    m.band(ring_p, r1)
    return m, (r0, ring_m, ring_p, r1)


def _rotation_about(pivot, axis, angle):
    """Rotation by ``angle`` about the line through ``pivot`` along ``axis`` (Rodrigues)."""
    import math as _m
    length = _m.sqrt(axis[0] ** 2 + axis[1] ** 2 + axis[2] ** 2)
    ux, uy, uz = axis[0] / length, axis[1] / length, axis[2] / length
    c, s_ = _m.cos(angle), _m.sin(angle)

    def rotate(p):
        x, y, z = _sub(p, pivot)
        dot = ux * x + uy * y + uz * z
        cx, cy, cz = uy * z - uz * y, uz * x - ux * z, ux * y - uy * x
        return _add((x * c + cx * s_ + ux * dot * (1.0 - c),
                     y * c + cy * s_ + uy * dot * (1.0 - c),
                     z * c + cz * s_ + uz * dot * (1.0 - c)), pivot)
    return rotate


def _centroid(points):
    n = float(len(points))
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n, sum(p[2] for p in points) / n)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    size = math.sqrt(_dot(a, a))
    return (a[0] / size, a[1] / size, a[2] / size)
