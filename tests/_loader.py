"""Makes the add-on's pure ``core`` package importable without Blender.

Importing ``qc_smart_cylinder`` itself would pull in bpy, so the tests put
the add-on directory on the path and import ``core`` as a top-level package.
"""

import importlib
import pathlib
import sys

ADDON_DIR = pathlib.Path(__file__).resolve().parent.parent / "qc_smart_cylinder"
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

core = importlib.import_module("core")
for _name in ("segments", "geometry", "topology", "units", "sections", "lathe", "elbow"):
    importlib.import_module("core." + _name)
