"""KiCad ActionPlugin entry point for WayriCAD Portable Assets."""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_ROOT = str(Path(__file__).resolve().parent)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

try:
    import wx
except ImportError:  # pragma: no cover - standalone inspection
    wx = None

if wx is not None and wx.GetApp() is not None:
    from .legacy_action_plugin import register

    register()
