"""Capture actual modeless WayriCAD frames using a synthetic board fixture."""

from __future__ import annotations

import time
import os
import sys
import ctypes
import subprocess
import tempfile
import traceback
from pathlib import Path

import pcbnew
import wx
_BOOTSTRAP_APP = wx.GetApp() or wx.App(False)
# Standalone fixture has wx but no KiCad application singleton to register into.
pcbnew.ActionPlugin.register = lambda self: None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kilo_plugin"))

# Some package UI helpers construct wx.Colour during import and need a live wx.App.
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
from return_path_auditor_plugin.return_path_auditor_plugin import ReturnPathFrame
from harness_workbench_plugin.harness_workbench_plugin import HarnessFrame
from manufacturing_readiness_plugin.manufacturing_readiness_plugin import ManufacturingFrame
from pdn_decoupling_plugin.pdn_decoupling_plugin import PdnFrame
from protocol_constraint_composer_plugin.protocol_constraint_composer_plugin import ConstraintFrame
from heater_designer_plugin.heater_designer_plugin import HeaterFrame
from planar_magnetics_plugin.planar_magnetics_plugin import MagneticsFrame
from kilo.ui.main_frame import MainFrame as KiloFrame
import wx
from PIL import Image


def save_window(hwnd: int, destination: Path, title: str) -> None:
    rect_type = type("RECT", (ctypes.Structure,), {"_fields_": [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]})
    rect = rect_type()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError(f"Could not measure {title}")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    temporary = destination.with_suffix(".capture.png")
    bitmap = wx.Bitmap(width, height)
    memory = wx.MemoryDC(bitmap)
    rendered = ctypes.windll.user32.PrintWindow(hwnd, int(memory.GetHDC()), 2)
    memory.SelectObject(wx.NullBitmap)
    if not rendered:
        raise RuntimeError(f"Windows could not capture {title}")
    bitmap.SaveFile(str(temporary), wx.BITMAP_TYPE_PNG)
    with Image.open(temporary) as source:
        image = source.convert("RGB")
    replacement=destination.with_suffix(".new.png")
    image.save(replacement, optimize=True)
    os.replace(replacement,destination)
    temporary.unlink(missing_ok=True)


def capture(frame: wx.Frame, destination: Path) -> None:
    try:
        frame.SetSize((1200, 780)); frame.SetPosition((30, 30)); frame.Show(); frame.Raise()
        frame.Refresh()
        for child in frame.GetChildren():
            child.Refresh()
        for _ in range(15):
            wx.Yield(); frame.Update(); time.sleep(0.08)
        save_window(int(frame.GetHandle()), destination, frame.GetTitle())
        print("Captured " + str(destination.relative_to(ROOT)), flush=True)
    finally:
        # Destroy native children while wx is fully alive. WebView teardown during
        # Python interpreter finalization can otherwise hang or crash python.exe.
        frame.Hide()
        frame.Destroy()
        for _ in range(3):
            wx.Yield()


def capture_variant(destination: Path) -> None:
    script = ROOT / "variant_workbench_plugin" / "kicad_variant_manager.py"
    interpreter=_tk_python()
    # The Windows Python manager may spawn a different PID; capture the actual interpreter process.
    with tempfile.TemporaryDirectory(prefix='wayricad-capture-python-') as folder:
        marker=Path(folder)/'interpreter.txt'
        subprocess.run([interpreter,'-c','import sys;from pathlib import Path;Path(sys.argv[1]).write_text(sys.executable)',str(marker)],check=True,timeout=10)
        if marker.exists():interpreter=marker.read_text().strip()
    process = subprocess.Popen([interpreter, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    hwnd = 0
    try:
        for _ in range(100):
            if process.poll() is not None:
                output,error=process.communicate()
                raise RuntimeError("Variant Workbench exited before capture: "+(error or output))
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
                    if title.value.startswith("WayriCAD Design Variant Workbench"):
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
        save_window(hwnd, destination, "WayriCAD Design Variant Workbench")
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def demo_board():
    board=pcbnew.BOARD()
    net=pcbnew.NETINFO_ITEM(board,'GND');board.Add(net)
    def point(x,y):return pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))
    for a,b in (((20,20),(80,20)),((80,20),(80,60)),((80,60),(20,60)),((20,60),(20,20))):
        line=pcbnew.PCB_SHAPE(board);line.SetShape(pcbnew.SHAPE_T_SEGMENT)
        line.SetStart(point(*a));line.SetEnd(point(*b));line.SetLayer(pcbnew.Edge_Cuts);board.Add(line)
    fp=pcbnew.FOOTPRINT(board);fp.SetReference('U1');fp.SetValue('SOIC-8');fp.SetPosition(point(50,40));board.Add(fp)
    coordinates=[(47,38.095+i*1.27) for i in range(4)]+[(53,41.905-i*1.27) for i in range(4)]
    for index,(x,y) in enumerate(coordinates,1):
        pad=pcbnew.PAD(fp);pad.SetNumber(str(index));pad.SetPosition(point(x,y));pad.SetSize(point(1.5,.6))
        pad.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT);pad.SetRoundRectRadiusRatio(.2)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD);layers=pcbnew.LSET();layers.AddLayer(pcbnew.F_Cu)
        pad.SetLayerSet(layers);pad.SetNet(net);fp.Add(pad)
    for a,b in (((48.5,37.3),(51.5,37.3)),((51.5,37.3),(51.5,42.7)),((51.5,42.7),(48.5,42.7)),((48.5,42.7),(48.5,37.3))):
        body=pcbnew.PCB_SHAPE(fp);body.SetShape(pcbnew.SHAPE_T_SEGMENT);body.SetStart(point(*a));body.SetEnd(point(*b));body.SetLayer(pcbnew.F_SilkS);body.SetWidth(pcbnew.FromMM(.15));fp.Add(body)
    for a,b in (((47,38.095),(44,38.095)),((44,38.095),(44,35.5))):
        track=pcbnew.PCB_TRACK(board);track.SetStart(point(*a));track.SetEnd(point(*b));track.SetWidth(pcbnew.FromMM(.25));track.SetLayer(pcbnew.F_Cu);track.SetNet(net);board.Add(track)
    via=pcbnew.PCB_VIA(board);via.SetPosition(point(44,35.5));via.SetWidth(pcbnew.FromMM(.7));via.SetDrill(pcbnew.FromMM(.35));via.SetNet(net);via.SetViaType(pcbnew.VIATYPE_THROUGH);via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);board.Add(via)
    return board


def main() -> None:
    app = wx.GetApp() or wx.App(False); board = demo_board()
    requested = set(sys.argv[1:])
    pcbnew.GetBoard = lambda: board
    with tempfile.TemporaryDirectory(prefix="wayricad-help-") as temporary:
        demo = Path(temporary)
        (demo / "demo.kicad_pro").write_text("{}\n", encoding="utf-8")
        pcbnew.SaveBoard(str(demo / "demo.kicad_pcb"), board)
        frames = (
            ("bulk_label_editor_plugin", lambda: BulkLabelEditorFrame(None, board)),
            ("extract_pins_plugin", lambda: PluginDialogV2(None, [])),
            ("fanout_generator_plugin", lambda: FanoutFrame(None, board)),
            ("test_point_descriptor_plugin", lambda: TestPointFrame(None, board)),
            ("trace_impedance_plugin", lambda: TraceFrame(None, board)),
            ("via_stitching_plugin", lambda: ViaFrame(None, board)),
            ("signal_integrity_advisor_plugin", lambda: SignalIntegrityFrame(None, board)),
            ("portable_assets_plugin", lambda: PortableAssetsFrame(ProjectContext.discover(demo))),
            ("return_path_auditor_plugin", lambda: ReturnPathFrame(None, board)),
            ("harness_workbench_plugin", lambda: HarnessFrame(None)),
            ("manufacturing_readiness_plugin", lambda: ManufacturingFrame(None, board)),
            ("pdn_decoupling_plugin", lambda: PdnFrame(None, board)),
            ("protocol_constraint_composer_plugin", lambda: ConstraintFrame(None, board)),
            ("heater_designer_plugin", lambda: HeaterFrame(None, board)),
            ("planar_magnetics_plugin", lambda: MagneticsFrame(None, board)),
            ("kilo_plugin", lambda: KiloFrame()),
        )
        for package, factory in frames:
            if requested and package not in requested:
                continue
            frame = factory()
            if isinstance(frame, FanoutFrame):
                frame.scope.SetValue('All SMD pads');frame.preview(None,silent=True)
            if isinstance(frame, ViaFrame):
                frame.net_choice.SetValue('GND');frame.require_target_zone.SetValue(False);frame.preview(None,silent=True)
            if isinstance(frame, SignalIntegrityFrame):
                frame._calculate_i2c(None)
            if isinstance(frame, HeaterFrame):
                frame.generate(None)
            if isinstance(frame, MagneticsFrame):
                frame.analyze(None)
            if isinstance(frame, KiloFrame):
                frame.notebook.SetSelection(frame.help_page)
            destination = ROOT / package / "help-workflow.png"
            capture(frame, destination)
    if not requested or "variant_workbench_plugin" in requested:
        try:
            capture_variant(ROOT / "variant_workbench_plugin" / "help-workflow.png")
        except RuntimeError as exc:
            print(f"Variant Workbench capture skipped: {exc}", file=sys.stderr)


if __name__ == "__main__":
    status = 0
    try:
        main()
    except BaseException:
        traceback.print_exc()
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        # wx/WebView owns native threads that are unsafe to tear down after the
        # Python runtime has started finalizing. This is a one-shot build tool.
        os._exit(status)
