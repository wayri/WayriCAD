"""Capture the actual read-only antenna archive UI; no mockups or retouching."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def capture(path):
    import wx
    from quick_emerge_plugin.saved_antenna_viewer import create_viewer, load_solver_json
    app=wx.App(False)
    loaded=load_solver_json(path); frame=create_viewer(None,loaded)
    area=wx.GetClientDisplayRect();frame.SetSize((min(1600,area.width-40),min(1050,area.height-60)))
    frame.Centre();frame.Show();frame.Raise();wx.Yield()
    records=[]
    try:
        import ctypes
        deadline=time.monotonic()+2
        while ctypes.windll.user32.GetForegroundWindow()!=frame.GetHandle() and time.monotonic()<deadline:
            wx.Yield();time.sleep(.05)
        if ctypes.windll.user32.GetForegroundWindow()!=frame.GetHandle():
            raise ValueError('Native screenshot unavailable: unlock the desktop; do not capture another foreground surface.')
        for mode,filename in [('3D radiation','help-saved-antenna-3d.png'),
                              ('3D phase vectors','help-saved-antenna-phase.png')]:
            page=frame.antenna_3d;page.choice.SetStringSelection(mode);page.phase.SetValue(90);page.draw()
            frame.Layout();frame.Update();wx.Yield();page.view.refresh_canvas();wx.Yield()
            time.sleep(.2);wx.Yield()
            rect=frame.GetScreenRect();bitmap=wx.Bitmap(rect.width,rect.height)
            dc=wx.MemoryDC(bitmap);screen=wx.ScreenDC()
            dc.Blit(0,0,rect.width,rect.height,screen,rect.x,rect.y);dc.SelectObject(wx.NullBitmap)
            target=ROOT/'quick_emerge_plugin'/filename
            bitmap.SaveFile(str(target),wx.BITMAP_TYPE_PNG)
            records.append({'file':filename,'mode':mode,'width':rect.width,'height':rect.height,
                            'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        receipt={'captured_at_utc':datetime.now(timezone.utc).isoformat(),
                 'capture_method':'Actual native window screen capture; no retouching',
                 'source_result_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                 'source_context':'Public synthetic context PCB; path not displayed',
                 'python':sys.version.split()[0],'wx':wx.version(),'captures':records}
        (ROOT/'quick_emerge_plugin/help-saved-antenna-provenance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    finally:frame.Destroy();wx.Yield()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('result',type=Path)
    capture(parser.parse_args().result)
