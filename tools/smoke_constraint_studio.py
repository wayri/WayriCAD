"""Run with KiCad Python to exercise the integrated wx window on a fixture.

Creates no source-project changes. Optional screenshot captures this test window.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--native-drc', action='store_true', help='Also invoke KiCad CLI on the exported fixture')
    args = parser.parse_args()
    import wx
    from protocol_constraint_composer_plugin.studio_ui import ConstraintStudioFrame
    from protocol_constraint_composer_plugin.analysis import Assignment, generate_rules
    result = {'status': 'running', 'errors': []}
    sys.excepthook = lambda kind, value, tb: result['errors'].append(''.join(traceback.format_exception(kind, value, tb)))
    original_box = wx.MessageBox
    wx.MessageBox = lambda message, *a, **kw: (result['errors'].append(str(message)), wx.ID_OK)[1]
    app = wx.App(False)
    fixture = ROOT / 'protocol_constraint_composer_plugin/examples/workflow_demo/workflow_demo.kicad_pcb'
    try:
        frame = ConstraintStudioFrame(board_path=str(fixture))
        frame.Show()
    except Exception:
        result.update(status='failed', traceback=traceback.format_exc())
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return 1

    def inspect():
        try:
            frame.stage_protocols(generate_rules([Assignment('USB2', 'USB_D+', 'user')]))
            assert frame.overview_panel.rules.GetItemCount() > 0
            frame.overview_panel.edit_rule(None)
            assert frame.book.GetCurrentPage() is frame.rule_page
            frame.select_page(frame.overview_panel)
            frame.open_protocols(None)
            composer = next(window for window in wx.GetTopLevelWindows() if type(window).__name__ == 'ConstraintFrame')
            row = composer.table.InsertItem(composer.table.GetItemCount(), 'USB2')
            composer.table.SetItem(row, 1, 'BGA_D0'); composer.table.SetItem(row, 2, 'user')
            composer.generate(None); composer.apply(None); composer.Destroy()
            with tempfile.TemporaryDirectory() as raw:
                bundle = frame.w.export_bundle(Path(raw) / 'review')
                if args.native_drc:
                    from protocol_constraint_composer_plugin.constraint_studio.validation import native_drc
                    report = native_drc(bundle / fixture.name)
                    result['native_drc'] = {key: report[key] for key in ('status', 'returncode', 'input_unchanged', 'stderr')}
                    assert report['status'] in ('report-produced', 'violations'), report
            result.update(rules=len(frame.w.document.rules), map_items=len(frame.overview_panel.canvas.rows),
                          wx_version=wx.version(), status='passed' if not result['errors'] else 'failed')
            frame.overview_panel.refresh()
            frame.Layout(); frame.Refresh(); frame.Update()
            if args.screenshot:
                size = frame.GetClientSize(); bitmap = wx.Bitmap(size.width, size.height)
                dc = wx.MemoryDC(bitmap)
                dc.Blit(0, 0, size.width, size.height, wx.ClientDC(frame), 0, 0)
                dc.SelectObject(wx.NullBitmap)
                bitmap.SaveFile(str(args.screenshot), wx.BITMAP_TYPE_PNG)
        except Exception:
            result.update(status='failed', traceback=traceback.format_exc())
        finally:
            frame.Destroy(); wx.CallLater(200, app.ExitMainLoop)
    wx.CallLater(800, inspect)
    wx.CallLater(20000, app.ExitMainLoop)
    app.MainLoop()
    if result['errors']: result['status'] = 'failed'
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    wx.MessageBox = original_box
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
