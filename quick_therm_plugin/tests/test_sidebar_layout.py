"""Native sidebar bounds after expansion, long values and window resizing."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


NATIVE_FLOW=r'''
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,sys.argv[1])
import wx
from quick_therm_plugin.ui import QuickThermFrame
app=wx.App(False);app.SetExitOnFrameDelete(False)
with patch.object(QuickThermFrame,'_inspect'):
    frame=QuickThermFrame(None,Path(sys.argv[1])/'quick_therm_plugin/examples/thermal-demo.kicad_pcb')
frame.Maximize(False);frame.Show();frame.book.SetSelection(0)
page=frame._therm_input_page
def descendants(window):
    for child in window.GetChildren():
        yield child
        yield from descendants(child)
frame.therm_time_enabled.SetValue(True);frame._transient_setup_changed()
for child in descendants(page):
    if isinstance(child,wx.CollapsiblePane):child.Collapse(False)
long_name='Reviewed_component_thermal_properties_from_saved_footprint_fields'
for combo in (frame.therm_power,frame.therm_ja,frame.therm_jb,frame.therm_jc):
    combo.Set([long_name]);combo.SetSelection(0)
frame.therm_ccx_executable.ChangeValue('C:/Projects/Example/solver/bin/ccx.exe')
checked=0
for size in ((940,680),(1000,740),(1440,900)):
    frame.SetSize(size);frame.Layout();page.Layout();page.FitInside()
    wx.CallLater(60,app.ExitMainLoop);app.MainLoop()
    client=page.GetClientSize();origin=page.ClientToScreen((0,0))
    assert page.GetVirtualSize().width<=client.width+1,(size,client,page.GetVirtualSize())
    for child in descendants(page):
        if child.IsShownOnScreen() and isinstance(child,(wx.TextCtrl,wx.Choice,wx.ComboBox,wx.SpinCtrl,wx.Button,wx.CheckListBox)):
            rectangle=child.GetScreenRect()
            assert origin.x-1<=rectangle.x and rectangle.GetRight()<=origin.x+client.width+1,(
                size,type(child).__name__,child.GetName(),rectangle,origin,client)
            assert rectangle.width>=30,(type(child).__name__,rectangle)
            checked+=1
assert checked>=90,checked
frame.Destroy();app.Yield()
print('Sidebar bounds verified across three window sizes and expanded input sections: '+str(checked),flush=True)
'''


@unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),
                     'Requires native wx and KiCad for geometry/layout checks')
class SidebarLayoutTests(unittest.TestCase):
    def test_expanded_controls_stay_inside_sidebar(self):
        root=Path(__file__).resolve().parents[2]
        result=subprocess.run([sys.executable,'-c',NATIVE_FLOW,str(root)],cwd=root,
                              capture_output=True,text=True,timeout=40,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        self.assertIn('Sidebar bounds verified',result.stdout)


if __name__=='__main__':unittest.main()
