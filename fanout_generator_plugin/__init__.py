"""KiWay Fanout Generator plugin entry point."""

from .fanout_generator_plugin import FanoutGeneratorPlugin

import wx

if wx.GetApp() is not None:
    FanoutGeneratorPlugin().register()

