# QC Smart Cylinder

QC Smart Cylinder is a Blender Extension by Mutaform Studio. It gives
cylinders the segment count their diameter calls for, following the studio's
low-poly rule, so nobody has to guess.

`Add > Mesh > qc Smart Cylinder` sits directly under the regular `Cylinder`
and works in two modes:

- **New Cylinder** (nothing cylindrical selected): adds a cylinder at the 3D
  cursor. Set the diameter in the redo panel and the segment count follows.
- **Fix Selected** (a mesh selected, or a mesh being edited): rebuilds the
  cylindrical forms of the selected meshes with the right count, keeping their
  shape, transforms, names, materials, smoothing, sharp edges, seams and UV
  layout. In Edit Mode the edited meshes are the targets, and a partial vertex
  selection limits the fix to the forms it touches; the rebuilt geometry comes
  back selected. When nothing in the selection can be fixed it says why instead
  of adding a cylinder. The mode can be switched in the redo panel.

## The rule

The studio table rows are anchor points:

| Diameter | Segments | Edge length |
|----------|----------|-------------|
| 10 cm    | 20       | 1.56 cm     |
| 20 cm    | 28       | 2.24 cm     |
| 40 cm    | 36       | 3.49 cm     |
| 60 cm    | 40       | 4.71 cm     |
| 80 cm    | 48       | 5.23 cm     |
| 100 cm   | 68       | 4.62 cm     |

Between anchors the count is interpolated linearly, so every diameter gets its
own step (15 cm gives 24, 30 cm gives 32, 90 cm gives 58). Outside the table
the edge length of the nearest anchor is kept: below 10 cm the count shrinks
in proportion (5 cm gives 10, 3 cm gives 6), above 100 cm it grows in
proportion (150 cm gives 102, 200 cm gives 136). Counts are always even,
never below 6 and never above 256; a form that hits the maximum is reported
as capped, which almost always means the object is at the wrong scale.

Lengths are scene-unit lengths; the scene's unit scale and the object's scale
are honoured when the rule is evaluated.

The table lives in the add-on preferences (`Edit > Preferences > Add-ons >
QC Smart Cylinder`): every row is an anchor point (diameter in centimetres,
segments) and can be edited, added or removed; a reset button restores the
studio table. The minimum and maximum counts and the even-only rounding are there too, and
a preview row shows what the current rule gives for a few diameters. New
cylinders and fixes follow the table as soon as it changes.

## What Fix Selected understands

A cylindrical form is a grid of quads: rings around the section crossed by
rails along the form. That covers straight cylinders with any number of loop
cuts, pipes along a path (mitre joints keep their elliptical sections), lathe
profiles with several radii, UV spheres between their poles, tori, and several
forms inside one mesh (each gets its own count). Ends may be open, closed with
an n-gon or closed with a triangle fan. Triangulated meshes are read through
their quad structure and come out triangulated again; caps that a curve
conversion leaves as separate islands are welded back as n-gon caps. Turned
parts whose rings differ in vertex count and are joined by reduction bands
mixing quads and triangles (the usual game-asset topology) are read as well:
rings are found as closed cycles at one height along the axis with one radius.
Rods bent with a hand-made elbow, where the two straight parts share the
vertices on the inside of the bend and a wedge fills the outside, are read as
well; the rebuild keeps the shared arc shared for any count. Cylinders stacked
with offset axes and joined by flat steps (a body with a narrower cylinder on
top, a socket with a hole) are read as sections of one form, each with its own
count. Caps filled with quads and triangles rather than one n-gon keep their
UVs; a part of the mesh that is not a cylindrical form (a body with a spout
sitting on it) is left untouched.

A form whose rings differ in diameter (a tube with a collar, a lathe profile,
a sphere) is split into sections wherever the diameter drifts by more than the
Section Step (25 % by default); a flat ledge between two radii always starts a
new section. Every section gets the count its own diameter calls for, wider
sections more, narrower fewer, and sections of different counts are joined by
triangle bridges, except that neighbouring sections whose counts differ by no
more than one even step keep their quads and share one count. Inside a section the Diameter From
setting decides which ring counts: the largest (default), the average or the
smallest. `Segments: Whole Form` gives the whole form one count instead, and a
manual count can be forced. Sectioned forms are recognised again, so a later
fix (after editing the table) rebuilds them.

The UV layout survives the rebuild: new vertices take their UVs from the
original faces around them by angle, and every ring starts at the original
seam, so islands keep their outlines and seams stay where they were.

A form welded to other geometry, a section with four vertices or fewer (a
square tube?) and a mesh with shape keys are left alone and reported.

## Compatibility

- Blender 4.2 or newer (developed and verified on 5.2 LTS; the Python API it
  uses did not change between 5.1 and 5.2)
- Packaged as a Blender Extension

## Manual Install

1. Download the release ZIP (`qc_smart_cylinder-<version>.zip`).
2. In Blender, open `Edit > Preferences > Extensions`.
3. Use `Install from Disk` and pick the ZIP.
4. Enable `QC Smart Cylinder`.

## Build Release ZIP

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_release.ps1
```

The archive is written to `..\Dev\dist\qc_smart_cylinder-<version>.zip`. The
version is read from `qc_smart_cylinder/blender_manifest.toml`. Add `-Release`
to also copy the archive into `..\Zip Addon\` (the previous one moves to
`Zip Addon\old\`).

Tests of the pure modules run without Blender:

```powershell
python -m unittest discover -s tests
```

## Repository Layout

```text
qc_smart_cylinder/
  blender_manifest.toml
  __init__.py          registration
  core/                pure Python, no bpy, unit-tested
    segments.py        the diameter -> segments rule
    geometry.py        ellipse fit and resampling of a ring
    topology.py        finding cylindrical forms (grids of rings, bridged sections)
    sections.py        per-section segment counts
    lathe.py           turned parts with reduction bands (rings by height and radius)
    elbow.py           rods bent with a hand-made elbow (rings band by band, wedge joints)
    units.py           scene units -> centimetres
  build/               the BMesh side
    new_cylinder.py    a fresh cylinder mesh
    rebuild.py         rebuilding found forms in place
    uv_transfer.py     carrying the UV layout over
  ui/
    operator.py        mesh.qc_smart_cylinder_add (New / Fix)
    layout.py          the redo panel
    menu.py            the entry under Cylinder in Add > Mesh
    preferences.py     the editable anchor table
tests/
  _loader.py           imports core without Blender (every test starts with it)
  synth.py             synthetic meshes for the topology tests
  test_segments.py, test_geometry.py, test_topology.py, test_sections.py, test_lathe.py, test_elbow.py
tools/
  build_release.ps1
```

## Publishing Notes

The Pages workflow builds the ZIP and publishes a Blender extension repository
from the `gh-pages` branch. Once the repository is on GitHub, Blender can use
the direct `index.json` URL of that site as an extension repository.
