"""WayriCAD Return-Path Auditor plugin entry point."""

try:
    from .return_path_auditor_plugin import ReturnPathAuditorPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    ReturnPathAuditorPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        ReturnPathAuditorPlugin().register()

__all__ = ["ReturnPathAuditorPlugin"]
