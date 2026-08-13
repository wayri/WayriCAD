"""Capture actual modeless KiWay frames using an empty demo board."""

from __future__ import annotations

import time
import sys
import ctypes
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import before creating wx.App so standalone imports do not register actions.
from bulk_label_editor_plugin.bulk_label_editor_plugin import BulkLabelEditorFrame
from fanout_generator_plugin.fanout_generator_plugin import FanoutFrame
from extract_pins_plugin.plugin_dialog_v2 import PluginDialogV2
from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import SignalIntegrityFrame
from test_point_descriptor_plugin.test_point_descriptor_plugin import TestPointFrame
from trace_impedance_plugin.trace_impedance_plugin import TraceFrame
from via_stitching_plugin.via_stitching_plugin import ViaFrame
import wx
from PIL import Image, ImageDraw


def capture(frame: wx.Frame, destination: Path) -> None:
    frame.SetSize((1200, 680)); frame.SetPosition((30, 30)); frame.Show(); frame.Raise()
    for _ in range(5):
        wx.Yield(); time.sleep(0.06)
    rect = frame.GetScreenRect(); bitmap = wx.Bitmap(rect.width, rect.height)
    memory = wx.MemoryDC(bitmap)
    rendered = ctypes.windll.user32.PrintWindow(int(frame.GetHandle()), int(memory.GetHDC()), 2)
    memory.SelectObject(wx.NullBitmap)
    if not rendered:
        raise RuntimeError(f"Windows PrintWindow failed for {frame.GetTitle()}")
    temporary = destination.with_suffix(".capture.png"); bitmap.SaveFile(str(temporary), wx.BITMAP_TYPE_PNG)
    with Image.open(temporary) as source:
        image = source.convert("RGB").resize((1200, 680), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 1191, 671), outline="#d54b36", width=3)
    draw.rounded_rectangle((18, 18, 360, 52), radius=4, fill="#fff4df", outline="#d54b36", width=2)
    draw.text((30, 26), "Actual plugin window - demo state", fill="#76281d")
    image.save(destination, optimize=True); temporary.unlink(missing_ok=True)
    close = wx.CloseEvent(wx.EVT_CLOSE.typeId); wx.PostEvent(frame, close)
    for _ in range(3): wx.Yield()


def main() -> None:
    app = wx.App(False); board = pcbnew.BOARD()
    pcbnew.GetBoard = lambda: board
    frames = (
        (BulkLabelEditorFrame(None, board), ROOT / "bulk_label_editor_plugin" / "help-workflow.png"),
        (PluginDialogV2(None, []), ROOT / "extract_pins_plugin" / "help-workflow.png"),
        (FanoutFrame(None, board), ROOT / "fanout_generator_plugin" / "help-workflow.png"),
        (TestPointFrame(None, board), ROOT / "test_point_descriptor_plugin" / "help-workflow.png"),
        (TraceFrame(None, board), ROOT / "trace_impedance_plugin" / "help-workflow.png"),
        (ViaFrame(None, board), ROOT / "via_stitching_plugin" / "help-workflow.png"),
        (SignalIntegrityFrame(None, board), ROOT / "signal_integrity_advisor_plugin" / "help-workflow.png"),
    )
    frames[-1][0]._calculate_i2c(None)
    for frame, destination in frames: capture(frame, destination)


if __name__ == "__main__":
    main()
