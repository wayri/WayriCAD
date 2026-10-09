"""Bounded native input-to-worker integration and board interaction checks."""
import hashlib
import os
import importlib.util
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

try:
    import wx
    import pcbnew
except ImportError:
    wx = None


def _native_flow():
    self=unittest.TestCase()
    from matplotlib.backend_bases import MouseEvent
    from quick_therm_plugin.ui import QuickThermFrame
    from quick_therm_plugin.service import execute
    from quick_therm_plugin.thermal_plot import component_at_event
    app=wx.GetApp() or wx.App(False)
    root=Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'thermal-review.kicad_pcb'
        board=pcbnew.LoadBoard(str(root/'mechanical_check_plugin/tests/fixtures/validation-fixture.kicad_pcb'))
        for fp in list(board.GetFootprints()):
            if fp.GetReference()!='C1':board.Remove(fp)
            else:
                fp.SetField('Power_W','.5 W');fp.SetField('RthetaJA','40 K/W')
                fp.SetField('RthetaJB','5 K/W');fp.SetField('Tmax','85 C')
        pcbnew.SaveBoard(str(path),board)
        original=hashlib.sha256(path.read_bytes()).hexdigest()
        inventory=execute({'action':'inspect','board_path':str(path)})
        self.assertEqual(inventory['components'][0]['properties']['RthetaJB'],'5 K/W')
        requests=[]
        with patch.object(QuickThermFrame,'_inspect'):
            frame=QuickThermFrame(None,path)
            try:
                frame.inventory=inventory;frame.therm_refs.Set(['C1'])
                for ctrl,name in ((frame.therm_power,'Power_W'),(frame.therm_ja,'RthetaJA'),
                                  (frame.therm_jb,'RthetaJB'),(frame.therm_model_jb,'RthetaJB'),
                                  (frame.therm_limit_max,'Tmax')):
                    ctrl.Set(['',*inventory['field_names']]);ctrl.SetValue(name)
                frame.therm_inputs.load(inventory,frame._thermal_field_map(),{},[],frame._temperature_field_map())
                frame.Show();app.Yield()
                frame._check_thermal_refs(True)
                self.assertEqual(frame.therm_inputs.selected_references(),['C1'])
                self.assertEqual(frame.therm_inputs.grid.GetCellValue(0,6),'5 K/W')
                for environment in range(5):
                    frame.therm_env.SetSelection(environment);frame._therm_controls()
                    self.assertTrue(frame.therm_jb.IsEnabled())
                    self.assertFalse(frame.therm_inputs.grid.IsReadOnly(0,6))
                frame.therm_env.SetSelection(0)
                grid=frame.therm_inputs.grid
                grid.SetGridCursor(0,6);grid.EnableCellEditControl()
                editor=grid.GetCellEditor(0,6);editor.GetControl().SetValue('7 K/W')
                frame.therm_inputs.commit_pending_edits();editor.DecRef()
                frame.therm_inputs.model.set_value('C1','maximum_c',90)
                frame.therm_inputs.model.set_value('C1','theta_ja_air_k_per_w',None)
                frame.therm_inputs._notify()
                frame.therm_model_enabled.SetValue(True);frame.therm_model_kind.SetSelection(0)
                frame.therm_k.ChangeValue('35');frame.therm_grid.SetValue(12)
                def run(request,finished,message):
                    requests.append(request);finished(execute(request))
                with patch.object(frame,'_job',run):frame.on_quick_therm()
                self.assertEqual(len(requests),1,frame.status.GetLabel())
                request=requests[0]
                self.assertEqual(request['manual_values']['C1']['theta_jb_k_per_w'],7)
                self.assertNotIn('theta_ja_air_k_per_w',request['manual_values']['C1'])
                self.assertTrue(request['board_power_only'])
                self.assertNotIn('thermal_network_component_field',request)
                self.assertEqual(request['manual_temperature_limits']['C1']['maximum_c'],90)
                network=frame.thermal_bundle['thermal_network']
                self.assertEqual(network['junction_mapping']['board_references_with_field'],['C1'])
                component=network['components'][0]
                self.assertAlmostEqual(component['junction_c']-component['board_site_c'],.5*7)
                self.assertEqual(frame.thermal_bundle['temperature_limits']['rows'][0]['maximum_c'],90)
                frame._buttons();self.assertTrue(frame.therm_export.IsEnabled())
                frame._set_thermal_view('3D overview');app.Yield();frame.therm_canvas.draw()
                ax=frame.therm_figure.axes[0]
                self.assertFalse(ax.axison)
                self.assertTrue(ax._thermal_field_planes)
                legend=frame.therm_figure.axes[-1]
                lx,ly=legend.bbox.x0+legend.bbox.width/2,legend.bbox.y0+legend.bbox.height/2
                readout=frame.therm_cursor.GetLabel()
                frame.therm_canvas.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',frame.therm_canvas,lx,ly))
                self.assertEqual(frame.therm_cursor.GetLabel(),readout,'color scale is not a board probe')
                self.assertGreater(frame.therm_canvas.GetSize().height,500)
                self.assertLessEqual(frame._therm_input_page.GetVirtualSize().width,
                                     frame._therm_input_page.GetClientSize().width)
                self.assertLessEqual(frame.therm_view_note.GetSize().width,280)
                x,y=ax.bbox.x0+ax.bbox.width*.5,ax.bbox.y0+ax.bbox.height*.5
                before=ax.get_xlim3d()
                event=MouseEvent('scroll_event',frame.therm_canvas,x,y,button='up',step=1)
                frame.therm_canvas.callbacks.process('scroll_event',event)
                self.assertLess(abs(ax.get_xlim3d()[1]-ax.get_xlim3d()[0]),abs(before[1]-before[0]))
                frame._fit_thermal_view();frame.therm_canvas.draw()
                # The actual registered 3D drag callbacks rotate the view.
                camera=(ax.elev,ax.azim)
                frame.therm_canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',frame.therm_canvas,x,y,button=1))
                frame.therm_canvas.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',frame.therm_canvas,x+25,y+15,button=1))
                frame.therm_canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',frame.therm_canvas,x+25,y+15,button=1))
                self.assertNotEqual((ax.elev,ax.azim),camera)
                limits=ax.get_xlim3d()
                frame.therm_canvas.callbacks.process('button_press_event',MouseEvent('button_press_event',frame.therm_canvas,x,y,button=1,key='shift'))
                frame.therm_canvas.callbacks.process('motion_notify_event',MouseEvent('motion_notify_event',frame.therm_canvas,x+25,y+15,button=1,key='shift'))
                frame.therm_canvas.callbacks.process('button_release_event',MouseEvent('button_release_event',frame.therm_canvas,x+25,y+15,button=1,key='shift'))
                self.assertNotEqual(ax.get_xlim3d(),limits)
                frame.therm_inputs.model.set_value('C1','power_w',.75);frame.therm_inputs._notify()
                self.assertFalse(frame.thermal_bundle);self.assertFalse(frame.therm_export.IsEnabled())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
            finally:frame.Destroy();app.Yield()

class ComponentWorkspaceTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),
                         'Native KiCad wx/pcbnew required')
    def test_scanned_edits_scope_limits_and_interactive_3d_reach_worker(self):
        run=subprocess.run([sys.executable,'-B','-I',str(Path(__file__).resolve()),'--native-workflow'],
                           stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=45)
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
        self.assertIn('Native component workspace passed',run.stdout)


if __name__=='__main__':
    if '--native-workflow' in sys.argv:
        try:
            _native_flow()
            print('Native component workspace passed',flush=True)
            sys.stderr.flush();os._exit(0)
        except BaseException:
            import traceback
            traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
    unittest.main()
