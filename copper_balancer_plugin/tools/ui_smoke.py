"""Exercise the real wx dialog on an in-memory board; capture only this window."""
import os
os.environ['WAYRICAD_COPPER_NO_REGISTER'] = '1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wx
import pcbnew as p
from copper_balancer.dialog import CopperBalancerDialog
from copper_balancer.engine import Settings
from copper_balancer.kicad_backend import build_preview, review_stamp
from tools.make_demo import make_board

app = wx.App(False)
board = make_board()
dialog = CopperBalancerDialog(None,board)
settings,layers = dialog.read_settings()
assert layers == [p.F_Cu]
previews,warnings = build_preview(board,layers,settings)
dialog.previews = previews
dialog.preview_settings = settings
dialog.preview_stamp = review_stamp(board)
dialog.preview_layer.SetItems([pr.name for pr in previews])
dialog.preview_layer.SetSelection(0)
dialog.on_preview_layer(None)
dialog.apply_button.Enable(True)
dialog.status.SetValue(f"Preview ready · {len(previews[0].plan.shapes):,} shapes / unique nets on F.Cu. Copper clearance ≥ 0.5 mm. Edge clearance ≥ 1 mm.\nEach object gets a WayriCADCopper/L0_F.Cu/… net. Remove or replace by layer, even after ungrouping.")
dialog.Show()
errors = []

def finish():
    try:
        dialog.canvas.fit()
        dialog.Refresh()
        dialog.Update()
        wx.YieldIfNeeded()
        import ctypes
        rect = dialog.GetRect()
        bmp = wx.Bitmap(rect.width,rect.height)
        dc = wx.MemoryDC(bmp)
        print_window = ctypes.windll.user32.PrintWindow
        print_window.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
        print_window.restype = ctypes.c_bool
        ok = print_window(int(dialog.GetHandle()),dc.GetHandle(),2)
        dc.SelectObject(wx.NullBitmap)
        out = Path(__file__).resolve().parents[1]/'help-workflow.png'
        out.parent.mkdir(exist_ok=True)
        assert ok, 'Window capture failed'
        assert bmp.SaveFile(str(out),wx.BITMAP_TYPE_PNG)
        # Invalidation and region controls use the actual bound handler.
        dialog.controls['size'].SetValue(1.5)
        event = wx.CommandEvent(wx.EVT_SPINCTRLDOUBLE.typeId)
        dialog.on_change(event)
        assert not dialog.apply_button.IsEnabled()
        assert dialog.canvas.stale
        dialog.region_choice.SetSelection(2)
        dialog.update_enabled()
        assert all(c.IsEnabled() for c in dialog.region_fields)
        # Cancelling the output picker must not execute a deferred board edit.
        changed = []
        dialog.save_result = lambda operation: False
        dialog.finish_edits(lambda: changed.append(True))
        assert not changed
        print(f'UI smoke passed. Preview: {len(previews[0].plan.shapes)} shapes. Screenshot: {out}',flush=True)
    except Exception as exc:
        errors.append(exc)
    finally:
        dialog.Destroy()
        app.ExitMainLoop()

wx.CallLater(1200,finish)
app.MainLoop()
if errors:
    raise errors[0]
