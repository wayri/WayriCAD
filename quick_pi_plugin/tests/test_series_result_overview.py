"""A completed/reopened series path starts with every solved copper plane."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime.project_results_ui import plot_specs, probe_sample, _saved_field_image


def series_bundle():
    from quick_pi_plugin.tests.test_solver import strip
    from quick_pi_plugin.solver import solve
    mesh={'points_mm':[], 'triangles':[], 'triangle_layer':[], 'triangle_thickness_mm':[],
          'vias':[], 'terminal_nodes':{}, 'lumped_branches':[]}
    layers=[];ends=[]
    for stage,layer in enumerate((0,31,0)):
        local,left,right=strip(nx=2,ny=1)
        offset=len(mesh['points_mm'])
        mesh['points_mm'].extend([[x+stage*15,y,0.02 if layer==0 else 1.5] for x,y,z in local['points_mm']])
        mesh['triangles'].extend([[i+offset for i in cell] for cell in local['triangles']])
        mesh['triangle_layer'].extend([layer]*len(local['triangles']))
        mesh['triangle_thickness_mm'].extend(local['triangle_thickness_mm'])
        ends.append(([i+offset for i in left],[i+offset for i in right]))
        polygon={'outer':[[stage*15,0],[stage*15+10,0],[stage*15+10,1],[stage*15,1]],'holes':[]}
        row=next((row for row in layers if row['id']==layer),None)
        if row is None:
            row={'id':layer,'name':'F.Cu' if layer==0 else 'B.Cu','polygons':[]};layers.append(row)
        row['polygons'].append(polygon)
    for stage in range(2):
        mesh['lumped_branches'].append(dict(id='R'+str(stage+1),top_nodes=ends[stage][1],
            bottom_nodes=ends[stage+1][0],resistance_ohm=.1,inductance_h=0.))
    geometry=dict(net='VIN → MID → OUT',nets=['VIN','MID','OUT'],layers=layers,terminals=[],vias=[])
    mesh['geometry']=geometry
    request=dict(series=[dict(id='R1'),dict(id='R2')],source_voltage=3.3,sink_current=2.)
    return dict(geometry=geometry,mesh=mesh,request=request,
        result=solve(mesh,ends[0][0],ends[-1][1],source_voltage=3.3,sink_current=2.))


class ArchivedSeriesOverviewTests(unittest.TestCase):
    def test_reopened_three_net_path_contains_every_triangle_and_exact_samples(self):
        from wayricad_runtime.project_results import save_result,load_result
        from matplotlib.figure import Figure
        bundle=series_bundle();original=deepcopy(bundle)
        with tempfile.TemporaryDirectory() as directory:
            receipt=save_result(directory,'quick-pi',bundle,version='4.1.0')
            reopened=load_result(directory,receipt['path'],plugin='quick-pi')['bundle']
        specs=plot_specs(reopened);overview=specs[0]
        self.assertIn('Complete series path',overview['label'])
        self.assertEqual(len(overview['triangles']),len(bundle['mesh']['triangles']))
        self.assertEqual(sorted(overview['values']),sorted(bundle['result']['potential_V']))
        self.assertEqual(set(overview['sample_z']),{.02,1.5})
        image,_=_saved_field_image(Figure().add_subplot(),overview)
        self.assertEqual(len(image._triangulation.triangles),len(bundle['mesh']['triangles']))
        for x in (0,15,30):
            self.assertIsNotNone(probe_sample(overview,x,0)['value'])
        self.assertEqual(reopened,original)
        self.assertEqual(bundle,original)
        self.assertTrue(any('layer 31' in spec['label'] for spec in specs[1:]))


try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None

_APP=None
_LOG=None
_PREVIOUS_LOG=None


@unittest.skipIf(wx is None,'KiCad native wx runtime required')
class NativeSeriesOverviewTests(unittest.TestCase):
    def test_post_run_opens_complete_path_after_source_layer_preview(self):
        import hashlib
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board
        global _APP,_LOG,_PREVIOUS_LOG
        _APP=wx.GetApp() or wx.App(False);app=_APP
        if _LOG is None:
            _LOG=wx.LogStderr();_PREVIOUS_LOG=wx.Log.SetActiveTarget(_LOG)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'series-display.kicad_pcb';portrait_board(path)
            bundle=series_bundle();bundle['geometry']['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,str(path))
            try:
                frame._board_scene_hash=bundle['geometry']['source_sha256']
                frame._board_scene={'net_scope':None,'primitives':[]}
                frame._set_layer_choices(bundle['geometry']['layers']);frame.layer.SetSelection(0)
                frame._accept_result(bundle,bundle['request'],'solve')
                self.assertEqual(frame._layers[frame.layer.GetSelection()]['id'],'all')
                axis=frame.views[2][0].axes[0]
                self.assertLess(axis.get_xlim()[0],0)
                self.assertGreater(axis.get_xlim()[1],40)
                self.assertEqual(frame._visible_nets(),['VIN','MID','OUT'])
                self.assertEqual(len(frame.bundle['result']['components']),2)
                from wayricad_runtime.project_results_ui import create_viewer
                viewer=create_viewer(frame,dict(bundle=deepcopy(bundle),receipt=dict(
                    plugin='quick-pi',source_state='unverified',can_restore=False)))
                try:
                    self.assertIn('Complete series path',viewer.current_spec()['label'])
                    self.assertGreater(viewer.figure.axes[0].get_xlim()[1],40)
                finally:viewer.Destroy()
            finally:frame._end();app.Yield()


if __name__=='__main__':unittest.main()
