# __init__.py - KiWay Extract Pins Plugin
"""
KiWay Extract Pins Plugin for KiCAD

A comprehensive plugin for extracting component data, analyzing signal flow,
and generating documentation from KiCAD PCB designs.

@author - Wayri (Yawar)
@version - 2.6.0
@license - GPL-3.0
"""

__version__ = "2.6.0"
__author__ = "Wayri (Yawar)"

# Register the GUI plugin with KiCAD
from .extract_pins_plugin import ExtractPinsPlugin

ExtractPinsPlugin().register()

# Export core modules for programmatic use
from .core import DataExtractor, SignalFlowAnalyzer
from .core import MarkdownFormatter, CSVFormatter, JSONFormatter

__all__ = [
    'ExtractPinsPlugin',
    'DataExtractor',
    'SignalFlowAnalyzer',
    'MarkdownFormatter',
    'CSVFormatter', 
    'JSONFormatter',
    '__version__'
]
