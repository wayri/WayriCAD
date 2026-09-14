"""Visible ActionPlugin launcher for the detached Variant Workbench."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pcbnew
import wx

from .variant_manager_plugin import _tk_python


PLUGIN_ROOT = Path(__file__).resolve().parent


def _active_schematic() -> str:
    board = pcbnew.GetBoard()
    board_name = str(board.GetFileName() or "") if board is not None else ""
    if not board_name:
        return ""
    schematic = Path(board_name).resolve().with_suffix(".kicad_sch")
    return str(schematic) if schematic.is_file() else ""


def _launch() -> None:
    initial = _active_schematic()
    note = (
        f"Active project detected from PCB Editor: {Path(initial).name}"
        if initial
        else "No matching top-level schematic was found; choose a .kicad_sch in the Workbench."
    )
    command = [_tk_python(), str(PLUGIN_ROOT / "kicad_variant_manager.py")]
    if initial:
        command.append(initial)
    command.extend(("--plugin-mode", "--launch-note", note))

    kwargs = {
        "cwd": str(PLUGIN_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


class VariantWorkbenchActionPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Design Variant Workbench"
        self.category = "Project Configuration"
        self.description = "Review, edit, validate, and release KiCad design variants"
        self.icon_file_name = str(PLUGIN_ROOT / "icon.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.show_toolbar_button = True

    def Run(self) -> None:
        try:
            _launch()
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Design Variant Workbench", wx.OK | wx.ICON_ERROR)


def register() -> None:
    VariantWorkbenchActionPlugin().register()
