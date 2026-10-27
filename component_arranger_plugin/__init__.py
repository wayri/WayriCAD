"""Independent native KiCad Component Arranger plugin."""
__version__ = '0.1.13'
try:
    import pcbnew
    import wx
except ImportError:
    pass
else:
    if wx.GetApp() is not None:
        from .action import ComponentArrangerAction
        ComponentArrangerAction().register()
