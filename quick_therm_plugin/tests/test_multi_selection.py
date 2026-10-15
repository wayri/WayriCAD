"""Multi-component navigation does not rebuild thermal geometry on each click."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from quick_therm_plugin.thermal_plot import draw_thermal_view, update_component_selection
from quick_therm_plugin.tests.test_component_labels import dense_view


class OverlayTests(unittest.TestCase):
    def test_repeated_multi_select_retains_mesh_and_camera(self):
        figure=Figure();FigureCanvasAgg(figure)
        axes=draw_thermal_view(figure,dense_view(12),'Top-side map',viewport=True)
        limits=(axes.get_xlim(),axes.get_ylim());original=list(axes.collections)
        for i in range(10):
            self.assertEqual(update_component_selection(axes,[str(i),str(i+1)]),2)
            self.assertEqual(len(axes._thermal_selection_artists),2)
            self.assertEqual((axes.get_xlim(),axes.get_ylim()),limits)
            self.assertEqual(list(axes.collections)[:-1],original)
        update_component_selection(axes,[])
        self.assertEqual(list(axes.collections),original)


NATIVE_FLOW=r'''
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import wx
from quick_therm_plugin.ui import QuickThermFrame
from quick_therm_plugin.thermal_plot import _install_component_hover
app=wx.App(False)
with patch.object(QuickThermFrame,'_inspect'):
 frame=QuickThermFrame(None,Path(sys.argv[1])/'quick_therm_plugin/examples/thermal-demo.kicad_pcb')
frame.Show();app.Yield()
frame._thermal_rows=[({'id':'a','reference':'U1'},{}),({'id':'b','reference':'U2'},{})]
for i in range(2):frame.therm_table.InsertItem(i,'U'+str(i+1))
axes=frame.therm_figure.add_subplot()
_install_component_hover(axes,[dict(id='a',position=[1,1],label='U1 30C'),dict(id='b',position=[2,2],label='U2 40C')],None)
frame._busy=True
with patch.object(frame,'_thermal_selection_text'),patch.object(frame,'_draw_thermal',side_effect=AssertionError('selection rebuilt field')):
 frame._thermal_apply_selection(['a','b'],from_editor=True,update_table=True)
 assert frame.therm_table.GetSelectedItemCount()==2
 assert axes._thermal_selected_ids=={'a','b'}
 frame.therm_table.Select(0,False);frame._thermal_commit_table_selection()
 assert frame._pending_thermal_selection==('b',)
 assert axes._thermal_selected_ids=={'b'}
 frame._thermal_apply_selection([],from_editor=True,update_table=True)
 assert not frame._pending_thermal_selection
 assert frame.therm_table.GetSelectedItemCount()==0
frame._closed=True;frame.Destroy();app.Yield()
print('Native multi-row reverse sync, queued latest selection and incremental plot highlight passed.')
'''


@unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),
                     'Requires native KiCad wxPython')
class NativeSelectionTests(unittest.TestCase):
    def test_table_multi_selection_and_reverse_sync(self):
        root=Path(__file__).resolve().parents[2]
        result=subprocess.run([sys.executable,'-c',NATIVE_FLOW,str(root)],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
