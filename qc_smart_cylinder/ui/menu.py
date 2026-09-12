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
"""Puts the Smart Cylinder item into Add > Mesh, directly under Cylinder.

``Menu.append`` / ``Menu.prepend`` can only add to the ends of a menu. To land
right under the built-in Cylinder, the built-in draw function of
``VIEW3D_MT_mesh_add`` is swapped for a wrapper that runs the original draw
unchanged, but through a layout proxy: the proxy forwards every call to the
real layout and, the moment the Cylinder item has been drawn, draws the Smart
Cylinder item after it. The original draw keeps working as is, so primitives
Blender adds later still show up, and draw functions other add-ons append to
the menu are untouched.

If the built-in draw cannot be found (some other add-on replaced it), the item
is appended to the end of the menu instead.
"""

import bpy

from .operator import QC_OT_smart_cylinder_add

MENU_TEXT = "qc Smart Cylinder"
MENU_ICON = 'MESH_CYLINDER'

_BUILTIN_MENU = "VIEW3D_MT_mesh_add"
_BUILTIN_DRAW_QUALNAME = "VIEW3D_MT_mesh_add.draw"
_INSERT_AFTER = "mesh.primitive_cylinder_add"

# Attribute set on the wrapper so a stale copy left by an earlier registration
# (script reload without a clean unregister) is recognised and replaced.
_WRAPPER_TAG = "_qc_smart_cylinder_builtin_draw"

_state = {"mode": None, "builtin_draw": None}


def draw_item(layout):
    layout.operator(QC_OT_smart_cylinder_add.bl_idname, text=MENU_TEXT, icon=MENU_ICON)


class _LayoutAfterCylinder:
    """Proxy over a UILayout that draws the Smart Cylinder item under Cylinder."""

    __slots__ = ("_layout",)

    def __init__(self, layout):
        object.__setattr__(self, "_layout", layout)

    def __getattr__(self, name):
        return getattr(self._layout, name)

    def __setattr__(self, name, value):
        setattr(self._layout, name, value)

    def operator(self, operator, *args, **kwargs):
        props = self._layout.operator(operator, *args, **kwargs)
        if operator == _INSERT_AFTER:
            draw_item(self._layout)
        return props


class _MenuProxy:
    """Stand-in for the menu instance whose ``layout`` is the proxy above."""

    __slots__ = ("_menu", "layout")

    def __init__(self, menu):
        self._menu = menu
        self.layout = _LayoutAfterCylinder(menu.layout)

    def __getattr__(self, name):
        return getattr(self._menu, name)


def _draw_mesh_add(self, context):
    _state["builtin_draw"](_MenuProxy(self), context)


def _draw_appended(self, context):
    self.layout.separator()
    draw_item(self.layout)


def _find_builtin_draw(draw_funcs):
    """Return ``(index, builtin_draw)`` inside the menu's draw list, or ``(None, None)``."""
    for index, func in enumerate(draw_funcs):
        stale_builtin = getattr(func, _WRAPPER_TAG, None)
        if stale_builtin is not None:
            return index, stale_builtin
        if getattr(func, "__qualname__", "") == _BUILTIN_DRAW_QUALNAME:
            return index, func
    return None, None


def register():
    menu = getattr(bpy.types, _BUILTIN_MENU)
    initialize = getattr(menu, "_dyn_ui_initialize", None)
    draw_funcs = initialize() if initialize is not None else None
    index, builtin_draw = _find_builtin_draw(draw_funcs or ())

    if builtin_draw is None:
        menu.append(_draw_appended)
        _state["mode"] = "appended"
        return

    _state["builtin_draw"] = builtin_draw
    setattr(_draw_mesh_add, _WRAPPER_TAG, builtin_draw)
    draw_funcs[index] = _draw_mesh_add
    _state["mode"] = "inline"


def unregister():
    menu = getattr(bpy.types, _BUILTIN_MENU, None)
    if menu is not None:
        if _state["mode"] == "inline":
            draw_funcs = getattr(menu.draw, "_draw_funcs", None) or []
            for index, func in enumerate(draw_funcs):
                if func is _draw_mesh_add:
                    draw_funcs[index] = _state["builtin_draw"]
        elif _state["mode"] == "appended":
            menu.remove(_draw_appended)
    _state["mode"] = None
    _state["builtin_draw"] = None
