"""KiWay PCB / Foil Heater Designer plugin entry point."""

try:
    from .heater_designer_plugin import HeaterDesignerPlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    HeaterDesignerPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        HeaterDesignerPlugin().register()

__all__ = ["HeaterDesignerPlugin"]
