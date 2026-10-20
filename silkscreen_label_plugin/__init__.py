"""Independent native KiCad silkscreen placement action."""
__version__ = '0.2.3'
try:
    import pcbnew
    import wx
except ImportError:
    pass
else:
    if wx.GetApp() is not None:
        from .action import SilkscreenAction
        SilkscreenAction().register()
