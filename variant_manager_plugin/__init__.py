"""Independent native KiCad variant management."""
__version__ = '0.6.0'

try:
    import pcbnew
    import wx
except ImportError:
    pcbnew = wx = None
if pcbnew is not None and wx is not None and wx.GetApp() is not None:
    from .action import VariantManagerAction
    VariantManagerAction().register()
