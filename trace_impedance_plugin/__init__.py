"""KiWay Trace RLC and Impedance Analyzer plugin entry point."""

try:
    from .trace_impedance_plugin import TraceImpedancePlugin
except ImportError:  # pcbnew/wx unavailable outside KiCad
    TraceImpedancePlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        TraceImpedancePlugin().register()

__all__ = ["TraceImpedancePlugin"]
