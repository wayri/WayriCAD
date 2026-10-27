"""Initial copper display is independent of simulation preparation."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'KiCad native wx runtime required')
class InventoryStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'public-example.kicad_pcb'
        portrait_board(self.path)
        with patch.object(QuickPIFrame, '_inspect'):
            self.frame = QuickPIFrame(None, str(self.path))
            wx.Yield()

    def tearDown(self):
        self.frame._end(); wx.Yield()
        self.directory.cleanup()

    def inventory(self):
        return {'nets': ['GND', *[f'VCC_{index:04d}' for index in range(1373)]],
                'terminals': [{'id': f'pad-{i}', 'label': f'U1.{i}', 'net': 'VCC_0000'} for i in range(1, 5)],
                'source_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
                'layers': [{'id':0,'name':'F.Cu'},{'id':31,'name':'B.Cu'}],
                'board_scene': {'primitives':[{'kind':'polygon','role':'track','layer':0,'net':'VCC_0000',
                                              'points':[[10,10],[20,10],[20,11],[10,11]],'holes':[]}],
                                'net_scope':['VCC_0000']}}

    def callback(self):
        with patch.object(self.frame, '_job') as job:
            self.frame._inspect()
        request, callback, _message = job.call_args.args
        self.assertEqual(request, {'action': 'inspect', 'board_path': str(self.path.resolve()),
                                   'include_display_scene':True,'display_nets':None})
        return callback

    def test_inventory_loads_copper_without_queuing_solver_geometry(self):
        callback = self.callback()
        inventory = self.inventory()
        with patch.object(self.frame,'_job') as jobs, patch.object(self.frame,'preview_geometry') as preview:
            callback(inventory)
            wx.Yield()
            jobs.assert_not_called();preview.assert_not_called()
        self.assertFalse(self.frame.main_panel.IsFrozen())
        self.assertEqual(self.frame.net.GetCount(), 1374)
        self.assertEqual(self.frame.return_signal.GetCount(), 1374)
        self.assertEqual(self.frame.return_nets.GetCount(), 1374)
        self.assertEqual(self.frame.source.GetItems(), ['U1.1', 'U1.2', 'U1.3', 'U1.4'])
        self.assertEqual(self.frame.source.GetSelection(), 0)
        self.assertEqual(self.frame.sink.GetSelection(), 1)
        self.assertEqual(self.frame.net.GetValue(), 'VCC_0000')
        self.assertEqual(len(self.frame._board_scene['primitives']),1)
        self.assertNotIn('geometry',self.frame.bundle)
        self.assertNotIn('result',self.frame.bundle)
        self.assertEqual(self.frame.layer.GetStringSelection(),'All copper layers (projected)')
        self.assertEqual(self.frame._layers[-1]['id'],'all')
        self.assertTrue(self.frame.views[0][0].axes[0].patches)
        self.assertGreaterEqual(self.frame.views[0][0].axes[0].patches[0].get_alpha(),.8)
        self.assertNotIn('Choose a net and preview its copper.',[row.get_text() for row in self.frame.views[0][0].axes[0].texts])
        self.assertEqual(self.frame._board_scene_hash, inventory['source_sha256'])
        request = self.frame._request('geometry')
        self.assertEqual(request['net'], 'VCC_0000')
        self.assertEqual(request['source_terminal'], 'pad-1')
        self.assertEqual(request['sinks'], [{'terminal': 'pad-2'}])
        self.assertEqual(self.frame._request('solve')['sinks'], [{'terminal': 'pad-2', 'current_A': 1.0}])

    def test_all_layer_projection_includes_bottom_only_net_on_open(self):
        inventory=self.inventory();inventory['board_scene']['primitives'][0]['layer']=31
        self.callback()(inventory)
        self.assertEqual(self.frame.layer.GetStringSelection(),'All copper layers (projected)')
        self.assertTrue(self.frame.views[0][0].axes[0].patches)

    def test_cached_copper_switches_nets_and_layers_without_another_job(self):
        inventory=self.inventory();inventory['board_scene']['net_scope']=None
        inventory['board_scene']['primitives'].append({'kind':'polygon','role':'track','layer':31,
            'net':'VCC_0001','points':[[30,10],[40,10],[40,11],[30,11]],'holes':[]})
        self.callback()(inventory)
        with patch.object(self.frame,'_job') as job:
            self.frame.net.SetValue('VCC_0001');self.frame._net_changed()
            self.assertEqual(self.frame.layer.GetStringSelection(),'All copper layers (projected)')
            axes=self.frame.views[0][0].axes[0]
            self.assertTrue(any(p.get_path().vertices[:,0].max()==40 for p in axes.patches))
            self.frame.isolate_nets.SetValue(False);self.frame._scope_changed()
            job.assert_not_called()
        self.assertNotIn('result',self.frame.bundle)

    def test_native_saved_copper_does_not_require_solver_extraction(self):
        from quick_pi_plugin.service import execute
        before=self.path.read_bytes()
        callback=self.callback()
        with patch('quick_pi_plugin.board_geometry.extract',side_effect=AssertionError('Solver extraction must not run on open')):
            inventory=execute({'action':'inspect','board_path':str(self.path),
                               'include_display_scene':True,'display_nets':None})
            callback(inventory);wx.Yield()
        self.assertTrue(any(row.get('role')=='track' for row in self.frame._board_scene['primitives']))
        self.assertTrue(self.frame.views[0][0].axes[0].patches)
        self.frame.show_context.SetValue(False);self.frame._draw()
        self.assertTrue(self.frame.views[0][0].axes[0].patches)
        self.assertEqual(self.path.read_bytes(),before)

    def test_copper_projection_default_excludes_silk_but_retains_edges(self):
        inventory=self.inventory();scene=inventory['board_scene']
        scene['layers']={0:'F.Cu',31:'B.Cu',37:'F.SilkS'}
        scene['primitives'].extend([
            {'kind':'polygon','role':'track','layer':31,'net':'VCC_0000','points':[[30,10],[40,10],[40,11],[30,11]],'holes':[]},
            {'kind':'polygon','role':'outline','layer':44,'uuid':'edge','points':[[0,0],[50,0],[50,20],[0,20]],'holes':[]},
            {'kind':'polygon','role':'reference','layer':37,'uuid':'silk','points':[[12,12],[14,12],[14,13],[12,13]],'holes':[]}])
        self.callback()(inventory);wx.Yield()
        self.assertFalse(self.frame.show_silkscreen.GetValue())
        axes=self.frame.views[0][0].axes[0]
        self.assertTrue(any(p.get_path().vertices[:,0].max()==40 for p in axes.patches))
        self.assertTrue(any(':outline:' in str(p.get_gid()) for p in axes.patches))
        self.assertFalse(any(':reference:' in str(p.get_gid()) for p in axes.patches))
        self.frame.show_silkscreen.SetValue(True);self.frame._draw();wx.Yield()
        self.assertTrue(any(':reference:' in str(p.get_gid()) for p in self.frame.views[0][0].axes[0].patches))

    def test_explicit_layer_selection_survives_inventory_and_result_choices(self):
        self.callback()(self.inventory())
        self.frame.layer.SetSelection(next(i for i,row in enumerate(self.frame._layers) if row['id']==31))
        self.frame._set_layer_choices([{'id':0,'name':'F.Cu'},{'id':31,'name':'B.Cu'}])
        self.assertEqual(self.frame.layer.GetStringSelection(),'B.Cu')
        self.frame.layer.SetSelection(next(i for i,row in enumerate(self.frame._layers) if row['id']=='all'))
        self.frame._set_layer_choices([{'id':0,'name':'F.Cu'},{'id':31,'name':'B.Cu'}])
        self.assertEqual(self.frame.layer.GetStringSelection(),'All copper layers (projected)')

    def test_failed_inventory_update_always_thaws_window(self):
        callback = self.callback()
        with patch.object(self.frame.net, 'Set', side_effect=RuntimeError('Native control rejected items.')):
            with self.assertRaisesRegex(RuntimeError, 'rejected items'):
                callback(self.inventory())
        self.assertFalse(self.frame.main_panel.IsFrozen())


if __name__ == '__main__':
    unittest.main()
