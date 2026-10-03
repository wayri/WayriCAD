"""Wayri Project Fusion: saved-file project merger for KiCad 10."""
__version__ = '0.9.4'
# A CLI/test import does not require KiCad or wxPython.
try:
    import pcbnew
except ImportError:
    pcbnew = None
if pcbnew is not None:
    try:
        import wx
    except ImportError:
        wx = None
    # KiCad owns a wx app when scanning plugins. Native CLI imports do not;
    # register_action() asserts without KiCad's application singleton.
    if wx is not None and wx.GetApp() is not None:
        from .action import ProjectFusionAction
        ProjectFusionAction().register()
