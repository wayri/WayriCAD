from .heater_designer_plugin import HeaterDesignerPlugin

try:
    import wx
    if wx.GetApp() is not None:
        HeaterDesignerPlugin().register()
except Exception:
    pass
