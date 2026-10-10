"""Capture the native component input table and optional public-demo board views.

Run with KiCad Python. The output is an opaque native client-area capture;
no desktop content, image retouching or board edits are involved.
"""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--board-views', action='store_true',
                        help='Also capture a solved thin-sheet 3D view and top/bottom workspace')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import wx
    from quick_therm_plugin.ui import QuickThermFrame
    from quick_therm_plugin.service import execute

    board = root / 'quick_therm_plugin/examples/thermal-demo.kicad_pcb'
    output = args.output or board.with_name('quicktherm-input-workspace.png')
    source_hash = hashlib.sha256(board.read_bytes()).hexdigest()
    app = wx.App(False)
    wx.Log.EnableLogging(False)
    screen = wx.Display().GetClientArea()
    capture_size = (min(1500, screen.width - 40), min(867, screen.height - 80))

    def settle(window):
        for _ in range(10):
            app.Yield()
            window.Layout()
            window.Update()
            time.sleep(.04)

    def capture(window, target):
        settle(window)
        assert screen.Contains(window.GetScreenRect()), 'Capture window must fit the screen'
        width, height = window.GetClientSize()
        # Windows DC alpha is undefined. A 24-bit target records RGB only.
        bitmap = wx.Bitmap(width, height, 24)
        dc = wx.MemoryDC(bitmap)
        assert dc.Blit(0, 0, width, height, wx.ClientDC(window), 0, 0)
        dc.SelectObject(wx.NullBitmap)
        image = bitmap.ConvertToImage()
        assert not image.HasAlpha()
        assert image.SaveFile(str(target), wx.BITMAP_TYPE_PNG)
        print(f'Captured opaque native view: {target.name}, {width} x {height}', flush=True)

    inspect = QuickThermFrame._inspect
    with patch.object(QuickThermFrame, '_inspect'):
        frame = QuickThermFrame(None, board)
    try:
        # Windows applies the frame's initial maximization on first Show.
        frame.Show()
        app.Yield()
        frame.Maximize(False)
        app.Yield()
        frame.SetClientSize(capture_size)
        frame.SetPosition((screen.x + 20, screen.y + 20))
        frame.Raise()
        with patch.object(frame, '_job', lambda request, finished, message: finished(execute(request))):
            inspect(frame)
        frame.therm_inputs.model.select_all(included=False)
        for reference in ('C1', 'C2', 'C3', 'J1'):
            frame.therm_inputs.model.set_included(reference, True)
        frame.therm_inputs._notify()
        frame.therm_inputs._refresh_rows()
        frame.book.SetSelection(1)
        frame.status.SetLabel('Saved demo scanned; four parts selected. Review or edit values before running.')
        frame._buttons()
        assert set(frame.therm_inputs.model.components) >= {'C1', 'C2', 'C3', 'J1'}
        capture(frame, output)
        if args.board_views:
            frame.therm_model_enabled.SetValue(True)
            frame.therm_model_kind.SetSelection(0)
            frame.therm_k.ChangeValue('35')
            frame.therm_emissivity.ChangeValue('.8')
            frame.therm_air_board.ChangeValue('10')
            frame.therm_grid.SetValue(48)
            frame.therm_ambient.ChangeValue('20')
            frame.therm_step_models.SetValue(False)
            frame._therm_controls()
            with patch.object(frame, '_job', lambda request, finished, message: finished(execute(request))):
                frame.on_quick_therm()
            assert frame.thermal_bundle.get('thermal_network'), frame.status.GetLabel()
            assert len(frame.thermal_bundle['thermal_network']['components']) == 4
            frame._set_thermal_view('3D overview')
            frame._fit_thermal_view()
            frame.therm_canvas.draw()
            capture(frame, output.with_name('quicktherm-3d-workspace.png'))

            def paired(dialog):
                from quick_therm_plugin.plot_canvas import FigureCanvasWxAgg
                dialog.SetClientSize(capture_size)
                dialog.SetPosition((screen.x + 20, screen.y + 20))
                frame.Hide()
                dialog.Show()
                dialog.Raise()
                settle(dialog)
                def descendants(window):
                    for child in window.GetChildren():
                        yield child
                        yield from descendants(child)
                canvases = [child for child in descendants(dialog) if isinstance(child, FigureCanvasWxAgg)]
                assert len(canvases) == 2
                for canvas in canvases:
                    canvas.draw()
                capture(dialog, output.with_name('quicktherm-paired-workspace.png'))
                dialog.Hide()
                frame.Show()
                return wx.ID_CLOSE

            with patch.object(wx.Dialog, 'ShowModal', paired):
                frame.on_expand_thermal()
        assert hashlib.sha256(board.read_bytes()).hexdigest() == source_hash
        print('Saved source hash unchanged.', flush=True)
    finally:
        frame.Hide()
        frame.Destroy()
        app.Yield()


if __name__ == '__main__':
    status = 0
    try:
        main()
    except BaseException:
        traceback.print_exc()
        status = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
