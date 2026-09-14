"""WayriCAD Manufacturing Readiness Manager plugin entry point."""

try:
    import pcbnew
    import wx
except ImportError:  # pcbnew/wx unavailable outside KiCad
    ManufacturingReadinessPlugin = None
else:
    if wx.GetApp() is not None:
        from .manufacturing_readiness_plugin import ManufacturingReadinessPlugin
        ManufacturingReadinessPlugin().register()
    else:
        ManufacturingReadinessPlugin = None

__all__ = ["ManufacturingReadinessPlugin"]
