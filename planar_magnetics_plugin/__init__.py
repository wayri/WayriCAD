from .planar_magnetics_plugin import PlanarMagneticsPlugin

try:
    import wx
    if wx.GetApp() is not None:
        PlanarMagneticsPlugin().register()
except Exception:
    pass
