"""Capture the native QuickTherm window using the saved KiCad example result."""

import json
from pathlib import Path
import sys

import wx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quick_therm_plugin.ui import QuickThermFrame


def save_capture(bitmap, path):
    """Discard undefined Windows DC alpha while preserving captured RGB pixels."""
    capture = bitmap.ConvertToImage()
    if capture.HasAlpha():
        capture.ClearAlpha()
    capture.SaveFile(str(path), wx.BITMAP_TYPE_PNG)


def main():
    folder = Path(__file__).resolve().parent
    bundle = json.loads((folder / "thermal-demo-report.json").read_text(encoding="utf-8"))
    board = folder / "thermal-demo.kicad_pcb"
    # The data was produced by the real CLI run; suppress a second analysis.
    QuickThermFrame._inspect = lambda self: None
    app = wx.App(False)
    frame = QuickThermFrame(None, board)
    for control, name in ((frame.therm_power, "Power_W"),
                          (frame.therm_ja, "RthetaJA"),
                          (frame.therm_limit_min, "Tmin_C"),
                          (frame.therm_limit_max, "Tmax_C")):
        control.Set(["", name])
        control.SetStringSelection(name)
    frame.therm_refs.Set(["C1", "C2", "C3", "J1"])
    for index in range(4):
        frame.therm_refs.Check(index, True)
    frame.therm_probe_definitions = bundle["request"].get("probes", [])
    frame._accept_therm(bundle)
    frame.status.SetLabel("Ready. Example result loaded from the saved board.")
    frame.Show()
    frame.Maximize()

    def capture(name):
        frame.Raise()
        frame.Refresh()
        frame.Update()
        size = frame.main_panel.GetClientSize()
        bitmap = wx.Bitmap(size.width, size.height)
        memory = wx.MemoryDC(bitmap)
        memory.Blit(0, 0, size.width, size.height, wx.ClientDC(frame.main_panel), 0, 0)
        memory.SelectObject(wx.NullBitmap)
        save_capture(bitmap, folder / name)

    def capture_results():
        page = frame.book.GetPage(0)
        page.Scroll(0, page.GetScrollRange(wx.VERTICAL))
        wx.CallLater(350, finish)

    def finish():
        capture("quicktherm-native-results.png")
        wx.CallLater(900, capture_large_view)
        frame.on_expand_thermal()
        frame.therm_mode.SetStringSelection("Top board model")
        frame._draw_thermal()
        wx.CallLater(900, capture_large_view)
        frame.on_expand_thermal()
        frame.Close()

    def capture_large_view():
        windows = [window for window in wx.GetTopLevelWindows()
                   if window.GetTitle() == "QuickTherm · Board thermal views"]
        if not windows:
            return
        dialog = windows[0]
        dialog.Refresh()
        dialog.Update()
        size = dialog.GetClientSize()
        bitmap = wx.Bitmap(size.width, size.height)
        memory = wx.MemoryDC(bitmap)
        memory.Blit(0, 0, size.width, size.height, wx.ClientDC(dialog), 0, 0)
        memory.SelectObject(wx.NullBitmap)
        name = ("quicktherm-board-model-view.png" if frame.therm_mode.GetStringSelection() == "Top board model"
                else "quicktherm-large-board-view.png")
        save_capture(bitmap, folder / name)
        dialog.EndModal(wx.ID_CLOSE)

    wx.CallLater(1800, lambda: (capture("quicktherm-native-window.png"), capture_results()))
    app.MainLoop()


if __name__ == "__main__":
    main()
