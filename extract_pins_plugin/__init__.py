# __init__.py - WayriCAD Extract Pins Plugin
"""
WayriCAD Extract Pins Plugin for KiCAD

A comprehensive plugin for extracting component data, analyzing signal flow,
and generating documentation from KiCAD PCB designs.

@author - Wayri (Yawar)
@version - 3.1.1
@license - GPL-3.0
"""

__version__ = "3.2.0"
__author__ = "Wayri (Yawar)"

try:
    from .extract_pins_plugin import ExtractPinsPlugin, InterboardHarnessPlugin
except ImportError:
    ExtractPinsPlugin = None
    InterboardHarnessPlugin = None
else:
    import wx

    if wx.GetApp() is not None:
        _registered_plugins = (ExtractPinsPlugin(), InterboardHarnessPlugin())
        for _plugin in _registered_plugins:
            _plugin.register()

# Export core modules for programmatic use
from .core import DataExtractor, SignalFlowAnalyzer
from .core import MarkdownFormatter, CSVFormatter, JSONFormatter

__all__ = [
    'ExtractPinsPlugin',
    'InterboardHarnessPlugin',
    'DataExtractor',
    'SignalFlowAnalyzer',
    'MarkdownFormatter',
    'CSVFormatter', 
    'JSONFormatter',
    '__version__'
]
