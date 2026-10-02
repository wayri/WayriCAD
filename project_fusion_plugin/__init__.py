"""Wayri Project Fusion: saved-file project merger for KiCad 10."""
__version__ = '0.9.2'
# A CLI/test import does not require KiCad or wxPython.
try:
    import pcbnew
except ImportError:
    pcbnew = None
if pcbnew is not None:
    from .action import ProjectFusionAction
    ProjectFusionAction().register()
