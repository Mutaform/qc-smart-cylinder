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
#
# QC Smart Cylinder
# =================
# A cylinder primitive and a cylinder fixer by Mutaform Studio for low-poly work.
#
# Add > Mesh > qc Smart Cylinder sits right under the regular Cylinder. Without a
# selection it adds a cylinder whose segment count is not guessed but derived
# from the diameter by the studio's low-poly rule. With a cylindrical mesh
# selected (a cylinder, a pipe along a path, a lathe profile, a sphere, a
# torus) it rebuilds that mesh with the count its diameter calls for.
#
# Layout of the package:
#   core/   pure Python, no bpy -- the rule, ring geometry, topology search;
#           unit-tested with a plain interpreter (tests/)
#   build/  the BMesh side -- building a new cylinder, rebuilding found forms
#   ui/     the operator, its redo-panel layout, the menu entry, the preferences
#
# This file only orchestrates registration.

from .ui import menu, operator, preferences

# Preferences first (the operator reads the rule from them), then the
# operator, then the menu that references its bl_idname.
_modules = (preferences, operator, menu)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
