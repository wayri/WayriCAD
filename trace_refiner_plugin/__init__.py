"""Independent native KiCad Trace Refiner plugin."""
__version__='0.3.7'
try:
    import pcbnew
    import wx
except ImportError:
    pass
else:
    if wx.GetApp() is not None:
        from .action import TraceRefinerAction
        TraceRefinerAction().register()
