"""Capture actual modeless KiWay frames using an empty demo board."""

from __future__ import annotations

import time
import sys
import ctypes
import subprocess
import tempfile
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
from portable_assets_plugin.portable_assets.app import PortableAssetsFrame
from portable_assets_plugin.portable_assets.core.engine import ProjectContext
from variant_workbench_plugin.variant_manager_plugin import _tk_python
import wx
from PIL import Image, ImageDraw


def save_window(hwnd: int, destination: Path, title: str) -> None:
    rect_type = type("RECT", (ctypes.Structure,), {"_fields_": [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]})
    rect = rect_type()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError(f"Could not measure {title}")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    bitmap = wx.Bitmap(width, height)
    memory = wx.MemoryDC(bitmap)
    rendered = ctypes.windll.user32.PrintWindow(hwnd, int(memory.GetHDC()), 2)
    memory.SelectObject(wx.NullBitmap)
    if not rendered:
        raise RuntimeError(f"Windows PrintWindow failed for {title}")
    temporary = destination.with_suffix(".capture.png")
    bitmap.SaveFile(str(temporary), wx.BITMAP_TYPE_PNG)
    with Image.open(temporary) as source:
        image = source.convert("RGB").resize((1200, 680), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 1191, 671), outline="#d54b36", width=3)
    draw.rounded_rectangle((18, 18, 360, 52), radius=4, fill="#fff4df", outline="#d54b36", width=2)
    draw.text((30, 26), "Actual plugin window - demo state", fill="#76281d")
    image.save(destination, optimize=True)
    temporary.unlink(missing_ok=True)


def capture(frame: wx.Frame, destination: Path) -> None:
    frame.SetSize((1200, 680)); frame.SetPosition((30, 30)); frame.Show(); frame.Raise()
    for _ in range(5):
        wx.Yield(); time.sleep(0.06)
    save_window(int(frame.GetHandle()), destination, frame.GetTitle())
    close = wx.CloseEvent(wx.EVT_CLOSE.typeId); wx.PostEvent(frame, close)
    for _ in range(3): wx.Yield()


def capture_variant(destination: Path) -> None:
    script = ROOT / "variant_workbench_plugin" / "kicad_variant_manager.py"
    process = subprocess.Popen([_tk_python(), str(script)])
    hwnd = 0
    try:
        for _ in range(100):
            time.sleep(0.1)
            matches: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            def visit(candidate: int, _unused: int) -> bool:
                owner = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(candidate, ctypes.byref(owner))
                if owner.value != process.pid or not ctypes.windll.user32.IsWindowVisible(candidate):
                    return True
                length = ctypes.windll.user32.GetWindowTextLengthW(candidate)
                if length:
                    title = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(candidate, title, length + 1)
                    if title.value.startswith("KiWay Design Variant Workbench"):
                        matches.append(candidate)
                return True

            ctypes.windll.user32.EnumWindows(visit, 0)
            if matches:
                hwnd = matches[0]
                break
        if not hwnd:
            raise RuntimeError("Variant Workbench window did not appear")
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 30, 30, 1200, 680, 0x0040)
        time.sleep(0.4)
        save_window(hwnd, destination, "KiWay Design Variant Workbench")
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def main() -> None:
    app = wx.App(False); board = pcbnew.BOARD()
    pcbnew.GetBoard = lambda: board
    with tempfile.TemporaryDirectory(prefix="kiway-help-") as temporary:
        demo = Path(temporary)
        (demo / "demo.kicad_pro").write_text("{}\n", encoding="utf-8")
        pcbnew.SaveBoard(str(demo / "demo.kicad_pcb"), board)
        frames = (
            (BulkLabelEditorFrame(None, board), ROOT / "bulk_label_editor_plugin" / "help-workflow.png"),
            (PluginDialogV2(None, []), ROOT / "extract_pins_plugin" / "help-workflow.png"),
            (FanoutFrame(None, board), ROOT / "fanout_generator_plugin" / "help-workflow.png"),
            (TestPointFrame(None, board), ROOT / "test_point_descriptor_plugin" / "help-workflow.png"),
            (TraceFrame(None, board), ROOT / "trace_impedance_plugin" / "help-workflow.png"),
            (ViaFrame(None, board), ROOT / "via_stitching_plugin" / "help-workflow.png"),
            (SignalIntegrityFrame(None, board), ROOT / "signal_integrity_advisor_plugin" / "help-workflow.png"),
            (PortableAssetsFrame(ProjectContext.discover(demo)), ROOT / "portable_assets_plugin" / "help-workflow.png"),
        )
        frames[-2][0]._calculate_i2c(None)
        for frame, destination in frames:
            capture(frame, destination)
    capture_variant(ROOT / "variant_workbench_plugin" / "help-workflow.png")


if __name__ == "__main__":
    main()
