"""KiWay Test Coverage Planner plugin entry point."""

from .test_coverage_plugin import TestCoveragePlugin

import wx

if wx.GetApp() is not None:
    TestCoveragePlugin().register()

