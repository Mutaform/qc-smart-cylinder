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
"""The Smart Cylinder operator: add a new cylinder, or fix the selected ones.

Invoked from the Add menu it looks at the selection: with a cylindrical mesh
selected it switches to Fix mode and rebuilds that mesh with the segment
count its diameter calls for; otherwise it adds a new cylinder. The mode can
be changed afterwards in the redo panel.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add

from ..build import new_cylinder, rebuild
from ..core.segments import MIN_SEGMENTS, edge_length, table_description
from ..core.units import to_centimetres
from . import layout as ui_layout
from . import preferences


def scene_to_cm(scene, length):
    unit_settings = scene.unit_settings
    return to_centimetres(length, unit_settings.scale_length, unit_settings.system)


class QC_OT_smart_cylinder_add(bpy.types.Operator, AddObjectHelper):
    """Add a cylinder whose segment count follows its diameter, or fix the selected cylindrical meshes"""

    bl_idname = "mesh.qc_smart_cylinder_add"
    bl_label = "Add Smart Cylinder"
    bl_description = (
        "Construct a cylinder mesh whose segment count follows its diameter; "
        "with a cylindrical mesh selected, rebuild it with the right count instead "
        "(QC low-poly rule, editable in the add-on preferences: " + table_description() + ")"
    )
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(
            ('NEW', "New Cylinder", "Add a new cylinder at the 3D cursor"),
            ('FIX', "Fix Selected", "Rebuild the cylindrical forms of the selected meshes with the segment count their diameter calls for"),
        ),
        default='NEW',
    )

    # --- New Cylinder -----------------------------------------------------
    diameter: FloatProperty(
        name="Diameter",
        description="Cylinder diameter; the segment count follows it",
        subtype='DISTANCE',
        unit='LENGTH',
        min=0.0,
        soft_max=2.0,
        default=0.4,
        precision=3,
    )
    depth: FloatProperty(
        name="Depth",
        subtype='DISTANCE',
        unit='LENGTH',
        min=0.0,
        soft_max=2.0,
        default=1.0,
        precision=3,
    )
    end_fill_type: EnumProperty(
        name="Cap Fill Type",
        items=(
            ('NOTHING', "Nothing", "Don't fill at all"),
            ('NGON', "N-Gon", "Use n-gons"),
            ('TRIFAN', "Triangle Fan", "Use triangle fans"),
        ),
        default='NGON',
    )
    calc_uvs: BoolProperty(
        name="Generate UVs",
        description="Generate a default UV map",
        default=True,
    )
    # Read-outs filled in by execute() for the redo panel; never remembered.
    segments: IntProperty(
        name="Segments",
        description="Segment count derived from the diameter",
        min=3,  # the preferences allow a minimum down to 3; the rule, not this property, sets the floor
        default=MIN_SEGMENTS,
        options={'HIDDEN', 'SKIP_SAVE'},
    )
    edge_length: FloatProperty(
        name="Edge Length",
        description="Length of one edge around the cylinder at this diameter and segment count",
        subtype='DISTANCE',
        unit='LENGTH',
        min=0.0,
        default=0.0,
        precision=3,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    # --- Fix Selected -------------------------------------------------------
    count_mode: EnumProperty(
        name="Segments",
        description="Whether every section of a form gets its own count",
        items=(
            ('SECTIONS', "Per Section",
             "Split the form where the diameter changes and give every section the count its own "
             "diameter calls for; sections of different counts are joined by triangle bridges"),
            ('FORM', "Whole Form", "One count for the whole form, from the ring chosen below"),
        ),
        default='SECTIONS',
    )
    section_step: FloatProperty(
        name="Section Step",
        description="Diameter change between rings that starts a new section (a flat ledge between two radii always starts one)",
        subtype='PERCENTAGE',
        min=1.0,
        max=200.0,
        default=25.0,
        precision=0,
    )
    diameter_source: EnumProperty(
        name="Diameter From",
        description="Which ring of a section (or of the whole form) sets its segment count when the rings differ in diameter",
        items=(
            ('MAX', "Largest Ring", "The widest section decides"),
            ('MEAN', "Average Ring", "The average section diameter decides"),
            ('MIN', "Smallest Ring", "The narrowest section decides"),
        ),
        default='MAX',
    )
    use_manual_segments: BoolProperty(
        name="Manual Segments",
        description="Use the count below instead of the rule",
        default=False,
    )
    manual_segments: IntProperty(
        name="Segments",
        description="Segment count to rebuild the selected forms with",
        min=3,
        soft_max=256,
        default=32,
    )
    fix_report: StringProperty(
        name="Report",
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def invoke(self, context, _event):
        # With mesh objects selected the call means "fix these"; if nothing can
        # be fixed the user gets told why instead of a surprise new cylinder.
        if not self.properties.is_property_set("mode"):
            self.mode = 'FIX' if rebuild.fix_intended(context) else 'NEW'
        return self.execute(context)

    def execute(self, context):
        if self.mode == 'FIX':
            return self._execute_fix(context)
        return self._execute_new(context)

    def _execute_new(self, context):
        rule = preferences.get_rule(context)
        self.segments = rule.segments(scene_to_cm(context.scene, self.diameter))
        self.edge_length = edge_length(self.diameter, self.segments)
        mesh = new_cylinder.cylinder_mesh(
            "Cylinder", self.segments, self.diameter * 0.5, self.depth, self.end_fill_type, self.calc_uvs)
        object_data_add(context, mesh, operator=self)
        return {'FINISHED'}

    def _execute_fix(self, context):
        if context.mode not in rebuild.FIX_MODES:
            self.report({'WARNING'}, "Smart Cylinder: Fix Selected works in Object Mode or Edit Mode")
            return {'CANCELLED'}
        # In Edit Mode the edited meshes are the targets and the vertex selection
        # (when partial) says which forms; the mesh is rebuilt in Object Mode
        # and Edit Mode resumed with the rebuilt geometry selected.
        editing = context.mode == 'EDIT_MESH'
        targets = rebuild.target_objects(context)
        manual = self.manual_segments if self.use_manual_segments else 0
        rule = preferences.get_rule(context)
        results = []
        partial = False
        if editing:
            # Leave Edit Mode for the rebuild and come back whatever happens, with
            # exactly the meshes that were being edited (mode_set enters Edit Mode
            # for the selected objects, so the selection is shaped for it briefly).
            edited = list(context.objects_in_mode)
            selected = [o for o in context.view_layer.objects if o.select_get()]
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            for obj in targets:
                only = rebuild.selected_vertices(obj) if editing else None
                partial = partial or only is not None
                results.extend(rebuild.rebuild_object(
                    obj, context.scene, rule, self.diameter_source, manual,
                    self.count_mode, self.section_step / 100.0, only, editing))
        finally:
            if editing:
                for o in selected:
                    o.select_set(o in edited)
                for o in edited:
                    o.select_set(True)
                bpy.ops.object.mode_set(mode='EDIT')
                for o in selected:
                    o.select_set(True)
        fixed = [r for r in results if r.status == 'FIXED']
        unchanged = [r for r in results if r.status == 'UNCHANGED']
        skipped = [r for r in results if r.status == 'SKIPPED']
        if results:
            self.fix_report = "\n".join(r.line() for r in results)
        elif targets and partial:
            self.fix_report = "No cylindrical form in the selection of " + ", ".join(o.name for o in targets)
        elif targets:
            self.fix_report = "No cylindrical form in " + ", ".join(o.name for o in targets)
        else:
            self.fix_report = "Nothing selected: select a cylindrical mesh, or switch Mode to New Cylinder"
        if fixed:
            if len(fixed) == 1:
                self.report({'INFO'}, "Smart Cylinder: " + fixed[0].line())
            else:
                self.report({'INFO'}, "Smart Cylinder: rebuilt %d forms" % len(fixed))
        elif unchanged and not skipped:
            self.report({'INFO'}, "Smart Cylinder: already right, nothing to change")
        elif skipped:
            reasons = "; ".join(sorted({r.note for r in skipped if r.note}))
            self.report({'WARNING'}, "Smart Cylinder: nothing rebuilt in %s (%s)" % (
                ", ".join(o.name for o in targets), reasons or "no cylindrical form"))
        else:
            self.report({'WARNING'}, "Smart Cylinder: " + self.fix_report)
        return {'FINISHED'}

    def draw(self, _context):
        ui_layout.draw_operator(self.layout, self)


def register():
    bpy.utils.register_class(QC_OT_smart_cylinder_add)


def unregister():
    bpy.utils.unregister_class(QC_OT_smart_cylinder_add)
