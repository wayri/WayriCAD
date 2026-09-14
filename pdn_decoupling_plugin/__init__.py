"""WayriCAD PDN and Decoupling Planner plugin entry point."""

try:
    from .pdn_decoupling_plugin import PdnDecouplingPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    PdnDecouplingPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        PdnDecouplingPlugin().register()

__all__ = ["PdnDecouplingPlugin"]
