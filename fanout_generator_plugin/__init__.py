"""KiWay Fanout Generator plugin entry point."""

try:
    from .fanout_generator_plugin import FanoutGeneratorPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    FanoutGeneratorPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        FanoutGeneratorPlugin().register()

__all__ = ["FanoutGeneratorPlugin"]
