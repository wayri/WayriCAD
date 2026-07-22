"""KiWay Net Hygiene plugin entry point."""

from .net_hygiene_plugin import NetHygienePlugin

import wx

if wx.GetApp() is not None:
    NetHygienePlugin().register()

