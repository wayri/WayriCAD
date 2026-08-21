"""KiWay Via Stitching plugin entry point."""

try:
    from .via_stitching_plugin import ViaStitchingPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    ViaStitchingPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        ViaStitchingPlugin().register()

__all__ = ["ViaStitchingPlugin"]
