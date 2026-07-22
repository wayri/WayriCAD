"""KiWay Trace RLC and Impedance Analyzer plugin entry point."""

from .trace_impedance_plugin import TraceImpedancePlugin

import wx

if wx.GetApp() is not None:
    TraceImpedancePlugin().register()

