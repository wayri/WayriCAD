"""KiWay Planar Magnetics & Actuator Workbench plugin entry point."""

try:
    from .planar_magnetics_plugin import PlanarMagneticsPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    PlanarMagneticsPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        PlanarMagneticsPlugin().register()

__all__ = ["PlanarMagneticsPlugin"]
