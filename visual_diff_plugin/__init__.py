"""WayriCAD Visual Diff. Core and CLI imports do not require KiCad or wxPython."""
__version__ = "3.0.0"

import sys
if "pcbnew" in sys.modules:
    from .plugin import VisualDiffPlugin
    VisualDiffPlugin().register()
