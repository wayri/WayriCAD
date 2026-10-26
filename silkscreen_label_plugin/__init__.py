"""Independent native KiCad silkscreen placement action."""
__version__ = '0.3.9'
try:
    import pcbnew
    import wx
except ImportError:
    pass
else:
    if wx.GetApp() is not None:
        from .action import SilkscreenAction
        SilkscreenAction().register()
