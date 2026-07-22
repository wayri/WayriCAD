"""KiWay Via Stitching plugin entry point."""

from .via_stitching_plugin import ViaStitchingPlugin

import wx

if wx.GetApp() is not None:
    ViaStitchingPlugin().register()

