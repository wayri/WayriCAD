# extract_pins_plugin.py

"""
KIWAY EXTRACT PINS PLUGIN

@author - Wayri (Yawar)
@version - 2.2.0
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

# Try to import the advanced dashboard, then fall back to the v2 dialog.
try:
    from .plugin_ui import PluginUI
    UI_VERSION = "dashboard"
except ImportError:
    PluginUI = None

try:
    from .plugin_dialog_v2 import PluginDialogV2 as PluginDialog
    DIALOG_VERSION = "v2.0"
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
        self.name = "Extract Component Pins with GUI" # The name visible in KiCad's 'Tools -> External Plugins' menu
        self.category = "Utilities" # Category under which the plugin will be listed
        self.description = "Extract pins, trace interfaces, build TM/TC tables, resolve test points, and generate docs."
        self.show_toolbar_button = True # Set to True to display a button on the toolbar
        # Define the path to the optional icon file. It should be in the same directory.
        self.icon_file_name = os.path.join(os.path.dirname(__file__), 'icon.png')
        self.version = "2.2.0"

    def Run(self):
        """
        This method is called by KiCad when the user activates the plugin.
        It retrieves the current PCB board and selected footprints, then launches the GUI.
        """
        board = pcbnew.GetBoard() # Get a reference to the currently active PCB board

        # Retrieve all footprints on the board and filter for those that are currently selected.
        # This is the robust way to get user-selected footprints in KiCad 9's pcbnew API.
        selected_footprints = [f for f in board.GetFootprints() if f.IsSelected()]

        if not selected_footprints:
            # If no footprints are selected, show dialog anyway - user can use pattern matching
            result = wx.MessageBox(
                "No footprints selected. Open the plugin anyway?\n\n"
                "You can use patterns (J*, U*, etc.) to select components.",
                "No Selection",
                wx.YES_NO | wx.ICON_QUESTION
            )
            if result != wx.YES:
                return

        # Prefer the advanced wx.Frame dashboard.  ActionPlugin registration is
        # handled by extract_pins_plugin/__init__.py calling
        # ExtractPinsPlugin().register(); KiCad then invokes this Run() method.
        if PluginUI is not None:
            print("DEBUG: Launching KiWay dashboard")
            frame = PluginUI(None, board=board)
            frame.Show()
            return

        # Fallback for minimal KiCad Python environments.
        print(f"DEBUG: Launching dialog {DIALOG_VERSION}")
        dialog = PluginDialog(None, selected_footprints)
        
        # The dialog is non-modal and handles its own lifecycle.
        # Once the dialog is closed, this Run() method simply finishes.
