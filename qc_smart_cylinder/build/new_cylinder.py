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
"""Building a fresh cylinder mesh."""

import bmesh
import bpy
from mathutils import Matrix


def cylinder_mesh(name, segments, radius, depth, end_fill_type='NGON', calc_uvs=True):
    """Return a new mesh datablock: the same geometry the built-in Cylinder makes."""
    bm = bmesh.new()
    if calc_uvs:
        # create_cone writes UVs into an existing layer only; the built-in
        # cylinder operator ensures the layer the same way.
        bm.loops.layers.uv.verify()
    bmesh.ops.create_cone(
        bm,
        cap_ends=end_fill_type != 'NOTHING',
        cap_tris=end_fill_type == 'TRIFAN',
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=depth,
        matrix=Matrix.Identity(4),
        calc_uvs=calc_uvs,
    )
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh
