from .manufacturing_readiness_plugin import ManufacturingReadinessPlugin
try:
    import wx
    if wx.GetApp() is not None:ManufacturingReadinessPlugin().register()
except Exception:pass
