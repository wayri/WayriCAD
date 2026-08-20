from .harness_workbench_plugin import HarnessWorkbenchPlugin
try:
    import wx
    if wx.GetApp() is not None: HarnessWorkbenchPlugin().register()
except Exception: pass
