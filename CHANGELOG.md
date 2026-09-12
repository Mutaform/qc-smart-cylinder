# Changelog

## 1.6.2 - 2026-09-12

- A maximum segment count (256 by default, editable in the preferences next
  to the minimum). Unchecking Manual Segments on an asset whose scale is
  wrong (centimetres read as metres, so a button measures twenty metres)
  used to flood the mesh with over a thousand segments per ring; such forms
  now stop at the maximum and the report says "capped: check the object
  scale". A manual count is never capped.

## 1.6.1 - 2026-09-12

- Cylinders whose caps are filled with a ladder of quads (no triangle
  anywhere) are recognised. The loop walk read such a cap as a broken grid,
  and the second analysis run that dissolves flat caps into n-gons only ran
  for triangulated meshes; it now also runs whenever the first run leaves
  faces unexplained. The caps come back as one n-gon each.

## 1.6.0 - 2026-09-12

Release after a full code review. Fixes:

- A wedge elbow whose two rings asked for different counts (arms of
  different diameter, or a small Section Step) raised an IndexError or left
  a torn elbow: the two rings of a wedge now always share one count.
- The UV transfer across a wedge sampled the arm's band quads instead of
  the wedge faces where the rings share vertices; a wedge that is its own UV
  island keeps it.
- A torus split into two counts by a previous fix was not recognised again
  (a closed chain of bridged sections); it is, and a second fix reports
  "already right".
- Fix Selected in Edit Mode comes back to Edit Mode whatever happens, with
  exactly the meshes that were being edited.
- Sharp and seam flags on rails are carried over rail by rail: one sharp
  rail stays one, two seam rails stay two (all-sharp bands stay all sharp).
- Sections: the drift is measured against the smaller of the two diameters,
  so a form gets the same sections whichever end it is read from (some forms
  now split one step finer than before); neighbouring sections merge across
  quads only while no ring ends up more than one even step from its own
  count; on a closed form the closing band merges too; a square section
  inside a round form keeps its four vertices.
- The New Cylinder segments read-out no longer clamps the rule to 6 when
  the preferences allow a lower minimum.
- The second analysis run ignores the forms the first one found, so its
  complaints about their joined triangles no longer appear in the report;
  two open ends at the same place are reported instead of caps being
  guessed; an emptied anchor table stays empty across restarts.
- Faster on big meshes: interval search by bisection in the UV transfer,
  closed loops bucketed by island in the lathe search, cap islands kept from
  the analysis instead of rescanning the mesh.
- README updated (menu name, Edit Mode, stacked cylinders), full GPL-2.0
  text in LICENSE.

## 1.5.7 - 2026-09-12

- Fix Selected works in Edit Mode: the meshes being edited are the targets,
  and a partial vertex selection limits the fix to the forms it touches
  (nothing or everything selected means the whole mesh). The mesh is
  rebuilt in Object Mode and Edit Mode resumes with the rebuilt geometry
  selected.

## 1.5.6 - 2026-09-12

- The menu item reads "qc Smart Cylinder", so the studio tools stand out in
  Add > Mesh.

## 1.5.5 - 2026-09-12

- Neighbouring sections whose counts differ by no more than one even step
  are merged again when the band between them is made of quads: a small
  knob (1.8 to 3.8 cm) used to come out as 6 segments with a rim of 8 and a
  crumpled zipper of triangles between them; it is 8 throughout now. Where
  the original already reduces through triangles, every section keeps its
  own count as before.
- An object rebuilt in full no longer reports skipped parts: the second
  analysis run used to complain about the joined triangles of forms the
  first run had already found.

## 1.5.4 - 2026-09-12

- Cylinders stacked with offset axes and joined by flat steps (a body with
  a narrower cylinder on top, a socket with a hole) are recognised in
  triangulated meshes. A flat step between two rings is a planar annulus,
  so undoing the triangulation used to join its triangles into quads and the
  walls merged into one unreadable grid; such steps now stay triangles and
  become bridges between sections. A concentric step of one count (a
  flange) still gets its quads back.
- A flat ledge between two radii always starts a new section, whatever the
  section step: 80 cm on 60 cm is exactly the default 25 % and used to be
  one section of 48; it is 48 and 40 now, as the table says.

## 1.5.3 - 2026-09-12

- A form whose open end sits on a hole in another part of the mesh (a body
  with a spout) no longer swallows that part. Such a part was taken for a
  detached fill cap because its outline duplicates the end ring, and was
  replaced by one n-gon. A detached cap must now be a flat disc in the
  plane of the ring and inside it; anything else is left alone and the end
  stays open, with a note in the report.

## 1.5.2 - 2026-09-12

- UVs are carried over when a cap is a planar fill of quads and triangles
  (a common game-asset fill) rather than one n-gon. The analysis already
  joined such a fill into an n-gon cap; the UV transfer then skipped the
  triangles of the fill and gave up, regenerating the UVs of the whole
  object.

## 1.5.1 - 2026-09-12

- UVs stay stitched across a hand-made elbow. Only the new vertices strictly
  inside the original shared arc are shared now (a vertex beyond its end
  would take two different UVs, one per side), and a shared vertex samples
  the same point of the original layout from both rings. A new ring P vertex
  that would fall behind its ring M partner is welded, so the wedge never
  folds.

## 1.5.0 - 2026-09-12

- Rods bent with a hand-made elbow are recognised and rebuilt: the two
  straight parts end in rings that share the vertices on the inside of the
  bend, with a wedge of quads and two triangles on the outside. Rings are
  derived band by band from the end rings (no matter the vertex valences),
  the wedge becomes a band of its own, and the rebuild keeps the shared arc
  shared for any segment count.

## 1.4.4 - 2026-09-12

- Thin hoops (a tube around a circle with few segments along the circle)
  rebuild correctly. Neighbouring sections of such a hoop are far from
  concentric, so comparing their vertices by projection into one frame gave
  twisted quads. Inside quad bands vertices now pair rail by rail again, and
  angles between neighbouring rings are related through the original rails;
  projection is used only across bridges between sections.

## 1.4.3 - 2026-09-12

- A ring band (a rectangular profile swept around a circle, torus topology)
  is subdivided around its big circle. Before, the profile polygon was taken
  for the section and resampled, which wrecked the shape and the UVs. On a
  closed grid the round family of loops is the rings; a doughnut with two
  round families still uses the smaller circles.

## 1.4.2 - 2026-09-12

- UV islands stay in one piece: a vertex takes one UV for every face of the
  same island (the interval it sits in), only a face across a seam keeps a
  UV of its own. Before, each face interpolated its corners separately and
  every edge became a tiny UV cut; fan caps fell apart into triangles.

## 1.4.1 - 2026-09-12

- UV seams that exist only in the layout (not marked on edges, as in imported
  assets) are found from the UV data; rings start on them, and every face
  takes its corners on a ring from one original face, so nothing straddles a
  seam any more. Fan-cap centres take the UV of the face they sit in.

## 1.4.0 - 2026-09-12

- Turned parts whose rings differ in vertex count and are joined by reduction
  bands mixing quads and triangles (typical game assets) are recognised: rings
  are found as closed cycles of vertices at one height along the axis with one
  radius, bands may hold any faces. They are rebuilt like any sectioned form.
- With a mesh selected the menu item always fixes; when nothing can be fixed
  it says why (in the status bar and the redo panel) instead of silently
  adding a new cylinder. With nothing selected it adds a cylinder as before.
- Reasons are reported for forms the search gives up on ("rings interrupted
  by reductions", "connected to other geometry", ...).

## 1.3.0 - 2026-09-12

- Fix mode counts per section. A form whose rings differ in diameter (a tube
  with a collar, a lathe profile, a sphere) is split where the diameter drifts
  by more than the Section Step (25 % by default); every section gets the
  count its own diameter calls for, and sections of different counts are
  joined by triangle bridges. `Segments: Whole Form` restores one count for
  the whole form.
- Sectioned forms are recognised again, so a later fix (after editing the
  table) rebuilds them; a thin one-ring flange is a section of its own.
- The UV layout is carried over: new vertices take their UVs from the original
  faces around them by angle, rings start at the original seam, so islands keep
  their outlines and seams stay where they were.
- Report lines show the counts along the form, e.g. `Ø 40–97 cm, 14 → 36/66/36`.

## 1.2.0 - 2026-09-11

- Fix mode. With a cylindrical mesh selected, `Add > Mesh > Smart Cylinder`
  rebuilds it with the segment count its diameter calls for instead of adding
  a new cylinder. Handles straight cylinders, pipes along a path (mitre
  joints keep their elliptical sections), lathe profiles with several radii,
  UV spheres between their poles, tori, several forms in one mesh and
  triangulated meshes (they stay triangulated). Caps (n-gon, triangle fan or
  open), materials, smooth shading, sharp edges, seams and a cylindrical UV
  layout are carried over. Forms welded to other geometry are left alone.
- Redo panel of Fix mode: which ring sets the count (largest, average,
  smallest), a manual count, and a report line per form.
- Add-on preferences: the anchor table of the rule (diameter in centimetres,
  segments) is editable, with add, remove and reset-to-studio-table buttons,
  a minimum count and an even-only switch, plus a live preview. New cylinders
  and fixes follow the edited table at once.
- Triangulated meshes are read through their quad structure: triangulated
  caps are recognised by their outline, fans around a centre vertex are kept,
  and the result comes out triangulated again. Caps that curve-to-mesh
  conversion leaves as separate islands are welded back as n-gon caps.
- Package split into `core/` (pure Python, unit-tested), `build/` (BMesh) and
  `ui/` (operator, layout, menu, preferences).

## 1.1.0 - 2026-09-11

- The segment count is now a continuous rule instead of one count per
  diameter range. The studio table rows are anchor points (20 at 10 cm,
  28 at 20 cm, 36 at 40 cm, 40 at 60 cm, 48 at 80 cm, 68 at 100 cm); between
  them the count is interpolated, so every diameter gets its own step.
- Below 10 cm and above 100 cm the edge length of the nearest anchor is kept:
  5 cm gives 10 segments, 200 cm gives 136.
- Counts are always even and never below 6.
- The redo panel shows the resulting edge length next to the segment count.

## 1.0.0 - 2026-09-11

- First release.
- `Add > Mesh > Smart Cylinder`, placed directly under the regular Cylinder.
- Segment count picked from the QC low-poly table by diameter range.
- Redo panel shows the segment count that was used.
- Diameter is read in scene units; the scene's unit scale is honoured.
