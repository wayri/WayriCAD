"""Visible ActionPlugin launcher with IPC-independent project discovery."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pcbnew
import wx


PLUGIN_ROOT = Path(__file__).resolve().parent
PLUGIN_ID = "wayricad-portable-assets"


def _gui_python() -> Path:
    candidates = []
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates.append(
            local / "kicad" / "10.0" / "python-environments" / PLUGIN_ID / "Scripts" / "pythonw.exe"
        )
        candidates.extend((Path(sys.prefix) / name for name in ("pythonw.exe", "python.exe")))
        candidates.extend((Path(sys.executable).with_name(name) for name in ("pythonw.exe", "python.exe")))
    for name in ("pythonw", "python3", "python"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("A Python GUI interpreter could not be located for Portable Assets.")


def _active_board_path() -> str:
    board = pcbnew.GetBoard()
    if board is None:
        return ""
    return str(board.GetFileName() or "")


def _launch() -> None:
    command = [str(_gui_python()), str(PLUGIN_ROOT / "portable_project_action.py")]
    board_path = _active_board_path()
    if board_path:
        command.extend(("--project", board_path))

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


class PortableAssetsActionPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Portable Assets"
        self.category = "Project Dependencies"
        self.description = "Snapshot project footprints, symbols, and 3D assets safely"
        self.icon_file_name = str(PLUGIN_ROOT / "resources" / "icon-24.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.show_toolbar_button = True

    def Run(self) -> None:
        try:
            _launch()
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Portable Assets", wx.OK | wx.ICON_ERROR)


def register() -> None:
    PortableAssetsActionPlugin().register()
