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
"""Drawing the operator settings (the redo panel).

Kept apart from the operator so the very same layout code can be rendered in
a temporary panel for GUI checks: ``props`` is the operator in the redo panel
and an ``OperatorProperties`` (``window_manager.operator_properties_last``)
in a check.
"""

MAX_REPORT_LINES = 12


def draw_operator(layout, props):
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.prop(props, "mode")
    layout.separator()
    if props.mode == 'FIX':
        draw_fix(layout, props)
    else:
        draw_new(layout, props)


def draw_new(layout, props):
    layout.prop(props, "diameter")
    layout.prop(props, "depth")

    readout = layout.column()
    readout.enabled = False
    readout.prop(props, "segments")
    readout.prop(props, "edge_length")

    layout.prop(props, "end_fill_type")
    layout.prop(props, "calc_uvs")

    layout.separator()
    layout.prop(props, "align")
    layout.prop(props, "location")
    layout.prop(props, "rotation")


def draw_fix(layout, props):
    layout.prop(props, "count_mode")
    if props.count_mode == 'SECTIONS':
        layout.prop(props, "section_step")
    layout.prop(props, "diameter_source")
    layout.prop(props, "use_manual_segments")
    row = layout.row()
    row.enabled = props.use_manual_segments
    row.prop(props, "manual_segments")

    lines = [line for line in props.fix_report.split("\n") if line]
    if not lines:
        return
    layout.separator()
    box = layout.box()
    box.use_property_split = False
    column = box.column(align=True)
    for line in lines[:MAX_REPORT_LINES]:
        column.label(text=line)
    if len(lines) > MAX_REPORT_LINES:
        column.label(text="… and %d more" % (len(lines) - MAX_REPORT_LINES))
