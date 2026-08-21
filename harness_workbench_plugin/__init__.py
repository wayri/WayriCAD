"""Harness Workbench package with headless-safe analysis imports."""

HarnessWorkbenchPlugin = None
try:
    import pcbnew  # noqa: F401
    import wx
except ImportError:
    pass
else:
    from .harness_workbench_plugin import HarnessWorkbenchPlugin
    if wx.GetApp() is not None:
        HarnessWorkbenchPlugin().register()

__all__ = ["HarnessWorkbenchPlugin"]
