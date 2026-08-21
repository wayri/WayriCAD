"""KiWay Manufacturing Readiness Manager plugin entry point."""

try:
    from .manufacturing_readiness_plugin import ManufacturingReadinessPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    ManufacturingReadinessPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        ManufacturingReadinessPlugin().register()

__all__ = ["ManufacturingReadinessPlugin"]
