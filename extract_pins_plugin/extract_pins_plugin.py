# extract_pins_plugin.py

"""
KIWAY EXTRACT PINS PLUGIN

@author - Wayri (Yawar)
@version - 2.11.0
@date - 2025

ALLOWS USER TO EXTRACT ALL THE NET NAMES IN MARKDOWN OR CSV FORMAT FROM CONNECTORS LIKE J1, J2 ETC, OR USER SELECTIONS OR ANY COMPONENT
THE CONTROLS ALLOW FOR DEFINING CUSTOM TYPES OF CONNECTORS USING "CONNECTOR-TYPE" AND THEN USING SELECTION FILTER

NEW IN v2.0:
- Signal flow analysis (source→destination tables)
- IC signal chart generation
- SVG block diagram export
- Power net classification and grouping
- Full CLI interface

THE EXPORTED DATA CAN BE VIEWED USING A MARKDOWN VIEWER

THIS PLUGIN IS PROVIDED AS IS WITHOUT ANY GUARANTEE OR WARRANTY.
"""

import pcbnew
import wx
import os

# The focused extractor is the default entry. The system dashboard is exposed
# separately so harness work does not crowd the normal pin extraction flow.
try:
    from .plugin_ui import PluginUI
    UI_VERSION = "dashboard"
except ImportError:
    PluginUI = None

try:
    from .plugin_dialog_v2 import PluginDialogV2 as PluginDialog
    DIALOG_VERSION = "v2.10"
except ImportError:
    from .plugin_dialog import PluginDialog
    DIALOG_VERSION = "v1.x"


class ExtractPinsPlugin(pcbnew.ActionPlugin):
    """
    Main KiCad ActionPlugin for extracting pin data and highlighting nets.
    This plugin acts as the entry point, launching the GUI dialog.
    """
    def defaults(self):
        """
        Sets the metadata for the plugin, which KiCad displays in its menus.
        """
        self.name = "KiWay Pin Extractor"
        self.category = "Utilities" # Category under which the plugin will be listed
        self.description = "Select PCB components, preview pins, cross-select nets, and export tables or diagrams."
        self.show_toolbar_button = True # Set to True to display a button on the toolbar
        # Define the path to the optional icon file. It should be in the same directory.
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon.png')
        self.version = "2.11.0"

    def Run(self):
        """
        This method is called by KiCad when the user activates the plugin.
        It retrieves the current PCB board and selected footprints, then launches the GUI.
        """
        try:
            board = pcbnew.GetBoard() # Get a reference to the currently active PCB board
        except Exception as exc:
            wx.MessageBox(f"KiWay could not access the active board: {exc}", "KiWay Extract Pins", wx.OK | wx.ICON_ERROR)
            return
        if board is None or not hasattr(board, "GetFootprints"):
            wx.MessageBox("Open a PCB in PCB Editor before launching KiWay Extract Pins.", "KiWay Extract Pins", wx.OK | wx.ICON_INFORMATION)
            return

        # Retrieve all footprints on the board and filter for those that are currently selected.
        # This is the robust way to get user-selected footprints in KiCad 9's pcbnew API.
        try:
            selected_footprints = [f for f in board.GetFootprints() if getattr(f, "IsSelected", lambda: False)()]
        except Exception as exc:
            wx.MessageBox(f"Could not read PCB footprints: {exc}", "KiWay Extract Pins", wx.OK | wx.ICON_ERROR)
            return

        try:
            existing = getattr(self, "_frame", None)
            if existing is not None and existing:
                existing.Raise()
                existing.Show()
                existing.OnRefreshSelection(None)
                return
            self._frame = PluginDialog(None, selected_footprints)
            self._frame.Show()
            self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(f"The pin extractor could not start: {exc}", "KiWay Extract Pins", wx.OK | wx.ICON_ERROR)


class InterboardHarnessPlugin(pcbnew.ActionPlugin):
    """Separate entry point for project-level ICD and harness work."""

    def defaults(self):
        self.name = "KiWay Interboard & Harness"
        self.category = "Documentation"
        self.description = "Analyze multi-board interfaces, harnesses, TM/TC, test points, and ICD reports."
        self.show_toolbar_button = False
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "2.11.0"

    def Run(self):
        if PluginUI is None:
            wx.MessageBox("The Interboard & Harness UI is unavailable.", "KiWay", wx.OK | wx.ICON_ERROR)
            return
        board = pcbnew.GetBoard()
        try:
            existing = getattr(self, "_frame", None)
            if existing is not None and existing:
                existing.Raise()
                existing.Show()
                return
            self._frame = PluginUI(None, board=board)
            self._frame.SetTitle("KiWay Interboard & Harness")
            self._frame.Show()
            self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(f"The Interboard & Harness window could not start: {exc}", "KiWay", wx.OK | wx.ICON_ERROR)
