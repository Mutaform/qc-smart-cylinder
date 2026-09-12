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
"""Add-on preferences: the editable table of anchor points.

The rule lives in ``core.segments``; here the studio's anchor points become
a table the user can edit in Preferences > Add-ons. Anything that needs the
rule asks ``get_rule()`` and so follows every edit at once.
"""

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, IntProperty
from bpy.types import AddonPreferences, Operator, PropertyGroup, UIList

from ..core import segments as rule_module

# "bl_ext.<repo>.qc_smart_cylinder.ui" -> "bl_ext.<repo>.qc_smart_cylinder"
PACKAGE = __package__.rpartition(".")[0]

PREVIEW_DIAMETERS = (5.0, 10.0, 15.0, 30.0, 50.0, 75.0, 100.0, 150.0)


class QC_SmartCylinderAnchor(PropertyGroup):
    diameter_cm: FloatProperty(
        name="Diameter",
        description="Section diameter in centimetres",
        min=0.01,
        soft_max=500.0,
        default=10.0,
        precision=1,
        step=100,
    )
    segments: IntProperty(
        name="Segments",
        description="Segment count a cylinder of this diameter gets",
        min=3,
        soft_max=512,
        default=20,
    )


class QC_UL_smart_cylinder_anchors(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index=0, _flt_flag=0):
        row = layout.row(align=True)
        row.prop(item, "diameter_cm", text="cm")
        row.label(text="", icon='FORWARD')
        row.prop(item, "segments", text="segments")


def get_preferences(context=None):
    addon = (context or bpy.context).preferences.addons.get(PACKAGE)
    return addon.preferences if addon is not None else None


def get_rule(context=None):
    """The rule as configured in the preferences (the studio table until edited)."""
    prefs = get_preferences(context)
    if prefs is None:
        return rule_module.DEFAULT_RULE
    anchors = [(item.diameter_cm, item.segments) for item in prefs.anchors]
    return rule_module.Rule(anchors, prefs.min_segments, prefs.even_only, prefs.max_segments)


def fill_defaults(prefs):
    prefs.anchors.clear()
    for diameter, count in rule_module.ANCHORS:
        item = prefs.anchors.add()
        item.diameter_cm = diameter
        item.segments = count
    prefs.active_anchor = 0
    bpy.context.preferences.is_dirty = True


def ensure_defaults():
    """Fill the studio table into a never-touched preferences panel (once: a table the
    user emptied on purpose stays empty, the rule then uses the studio table). Timer-safe."""
    prefs = get_preferences()
    if prefs is not None and not prefs.table_initialised:
        if len(prefs.anchors) == 0:
            fill_defaults(prefs)
        prefs.table_initialised = True
    return None


class QC_OT_smart_cylinder_anchor_add(Operator):
    bl_idname = "qc_smart_cylinder.anchor_add"
    bl_label = "Add Anchor"
    bl_description = "Add an anchor point 10 cm above the largest one, with the count the rule gives there"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        prefs = get_preferences(context)
        rule = get_rule(context)
        diameter = max((item.diameter_cm for item in prefs.anchors), default=0.0) + 10.0
        item = prefs.anchors.add()
        item.diameter_cm = diameter
        item.segments = rule.segments(diameter)
        prefs.active_anchor = len(prefs.anchors) - 1
        context.preferences.is_dirty = True
        return {'FINISHED'}


class QC_OT_smart_cylinder_anchor_remove(Operator):
    bl_idname = "qc_smart_cylinder.anchor_remove"
    bl_label = "Remove Anchor"
    bl_description = "Remove the selected anchor point"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        prefs = get_preferences(context)
        return prefs is not None and 0 <= prefs.active_anchor < len(prefs.anchors)

    def execute(self, context):
        prefs = get_preferences(context)
        prefs.anchors.remove(prefs.active_anchor)
        prefs.active_anchor = min(prefs.active_anchor, len(prefs.anchors) - 1)
        context.preferences.is_dirty = True
        return {'FINISHED'}


class QC_OT_smart_cylinder_anchors_reset(Operator):
    bl_idname = "qc_smart_cylinder.anchors_reset"
    bl_label = "Reset to Studio Table"
    bl_description = "Replace the anchor points with the studio table"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        fill_defaults(get_preferences(context))
        return {'FINISHED'}


class QC_SmartCylinderPreferences(AddonPreferences):
    bl_idname = PACKAGE

    anchors: CollectionProperty(type=QC_SmartCylinderAnchor)
    active_anchor: IntProperty(default=0)
    table_initialised: BoolProperty(default=False, options={'HIDDEN'})
    min_segments: IntProperty(
        name="Minimum Segments",
        description="A cylinder never gets fewer segments than this",
        min=3,
        soft_max=64,
        default=rule_module.MIN_SEGMENTS,
    )
    max_segments: IntProperty(
        name="Maximum Segments",
        description="A cylinder never gets more segments than this; a form that hits it is almost always an object at the wrong scale",
        min=8,
        soft_max=1024,
        default=rule_module.MAX_SEGMENTS,
    )
    even_only: BoolProperty(
        name="Even Counts Only",
        description="Round the count to an even number so the cylinder stays mirror-symmetric on both axes",
        default=True,
    )

    def draw(self, context):
        draw_preferences(self.layout, self, context)


def draw_preferences(layout, prefs, context):
    """Draw the preferences panel; ``prefs`` is the AddonPreferences instance.

    A module function so a GUI check can render it in a temporary panel.
    """
    column = layout.column()
    column.label(text="Anchor points: the segment count at these diameters.")
    column.label(text="Between anchors the count is interpolated; outside, the edge length of the nearest anchor is kept.")

    row = layout.row()
    row.template_list("QC_UL_smart_cylinder_anchors", "", prefs, "anchors", prefs, "active_anchor", rows=6)
    buttons = row.column(align=True)
    buttons.operator(QC_OT_smart_cylinder_anchor_add.bl_idname, text="", icon='ADD')
    buttons.operator(QC_OT_smart_cylinder_anchor_remove.bl_idname, text="", icon='REMOVE')
    buttons.separator()
    buttons.operator(QC_OT_smart_cylinder_anchors_reset.bl_idname, text="", icon='FILE_REFRESH')
    if len(prefs.anchors) == 0:
        layout.label(text="No anchors: the studio table is used. Press the reset button to edit it.", icon='INFO')

    split = layout.split(factor=0.5)
    split.prop(prefs, "min_segments")
    split.prop(prefs, "even_only")
    layout.prop(prefs, "max_segments")

    rule = get_rule(context)
    box = layout.box()
    box.label(text="Preview", icon='MESH_CYLINDER')
    grid = box.grid_flow(row_major=True, columns=4, even_columns=True, align=True)
    for diameter in PREVIEW_DIAMETERS:
        grid.label(text="Ø %g cm: %d" % (diameter, rule.segments(diameter)))


_classes = (
    QC_SmartCylinderAnchor,
    QC_UL_smart_cylinder_anchors,
    QC_OT_smart_cylinder_anchor_add,
    QC_OT_smart_cylinder_anchor_remove,
    QC_OT_smart_cylinder_anchors_reset,
    QC_SmartCylinderPreferences,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    # register() may not write to preferences; a one-shot timer fills the
    # table with the studio defaults once Blender is up.
    bpy.app.timers.register(ensure_defaults, first_interval=0.2)


def unregister():
    if bpy.app.timers.is_registered(ensure_defaults):
        bpy.app.timers.unregister(ensure_defaults)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
