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
"""Scene units: the rule speaks centimetres, Blender speaks scene units."""


def to_centimetres(length, scale_length=1.0, unit_system='METRIC'):
    """Convert a length in Blender units to centimetres.

    Honours the scene unit scale. With the unit system switched off Blender
    still treats one unit as one metre, so the same conversion applies.
    """
    scale = scale_length if unit_system != 'NONE' else 1.0
    return length * scale * 100.0
