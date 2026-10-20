"""Independent native KiCad copper layer counter action."""
__version__ = '0.1.0'
try:
    import pcbnew
    import wx
except ImportError:
    pass
else:
    if wx.GetApp() is not None:
        from .action import LayerCounterAction
        LayerCounterAction().register()
