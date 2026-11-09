"""KiCad action entry point for Portable Web Export."""
from __future__ import annotations

import os

import pcbnew
import wx


class PortableWebExportPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "WayriCAD Portable Web Export"
        self.category = "Documentation"
        self.description = "Export selected KiCad views as one offline interactive HTML page."
        self.show_toolbar_button = True
        base = os.path.dirname(__file__)
        self.icon_file_name = os.path.join(base, "resources", "icon-24.png")
        self.dark_icon_file_name = os.path.join(base, "resources", "icon-dark-24.png")
        self.version = "0.1.0"

    def Run(self):
        from .ui import PortableWebExportFrame

        board = pcbnew.GetBoard()
        path = board.GetFileName() if board is not None and hasattr(board, "GetFileName") else ""
        if not path:
            wx.MessageBox(
                "Open and save a PCB before launching Portable Web Export.",
                self.name,
                wx.OK | wx.ICON_INFORMATION,
            )
            return
        existing = getattr(self, "_frame", None)
        if existing is not None and existing:
            existing.Show()
            existing.Raise()
            existing.load_project(path)
            return
        self._frame = PortableWebExportFrame(None, path)
        self._frame.Show()
        self._frame.Raise()
