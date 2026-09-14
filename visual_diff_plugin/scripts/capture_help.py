from pathlib import Path
import sys, time, ctypes
import wx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from visual_diff_plugin.kicad_vizdiff.desktop import show
app=wx.App(False)
frame=show(str(ROOT.parent/'.validation/visual-diff-demo/repository/sensor.kicad_pcb'))
for _ in range(15):
    wx.Yield(); frame.Update(); time.sleep(.08)
class RECT(ctypes.Structure):
    _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
rect=RECT();ctypes.windll.user32.GetWindowRect(int(frame.GetHandle()),ctypes.byref(rect))
bitmap=wx.Bitmap(rect.right-rect.left,rect.bottom-rect.top);memory=wx.MemoryDC(bitmap)
assert ctypes.windll.user32.PrintWindow(int(frame.GetHandle()),int(memory.GetHDC()),2)
memory.SelectObject(wx.NullBitmap)
bitmap.SaveFile(str(ROOT/'help-workflow.png'),wx.BITMAP_TYPE_PNG)
frame.Destroy();wx.Yield()
print('Captured local Visual Diff launcher')

