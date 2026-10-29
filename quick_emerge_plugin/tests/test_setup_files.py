"""Setup file contracts and actual native Save/Load handlers."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from quick_emerge_plugin.model import DEFAULT_CONFIG, source_identity, validate_config
from quick_emerge_plugin.setup_files import read_setup, write_setup, validate_region_choices


class SetupFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.board = self.root / 'example.kicad_pcb'
        self.board.write_text('(kicad_pcb)')
    def tearDown(self):self.temporary.cleanup()

    def test_complete_config_named_file_and_legacy_roundtrip(self):
        config = validate_config(dict(DEFAULT_CONFIG, advanced={'boundary':'pmc', 'solver_threads':2}))
        path = write_setup(self.root/'my study', self.board, config)
        self.assertEqual(path.name, 'my study.json')
        actual, source = read_setup(path)
        self.assertEqual(actual, config)
        self.assertEqual(source, source_identity(self.board))
        path.write_text(json.dumps({'schema':1,'config':config}))
        self.assertEqual(read_setup(path), (config, None))

    def test_other_plugin_result_malformed_and_protected_import(self):
        path = self.root/'chosen.json'
        for payload in ({'schema':1,'plugin':'quick-pi','config':DEFAULT_CONFIG},
                        {'schema':1,'kind':'wayricad-result','config':DEFAULT_CONFIG},
                        {'schema':1,'backend':{'backend':'EMerge'},'config':DEFAULT_CONFIG},
                        {'schema':True,'config':DEFAULT_CONFIG},
                        {'schema':1,'config':DEFAULT_CONFIG,'source':{'path':'x','sha256':'wrong'}}):
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):read_setup(path)
        path.write_text('{ broken')
        with self.assertRaises(ValueError):read_setup(path)
        config = validate_config(dict(DEFAULT_CONFIG, advanced={'study':'scattering', 'import_kind':'gerber',
            'import_path':str(self.root/'gerber'), 'import_recipe_path':str(path), 'import_sha256':'a'*64}))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'overwrite'):write_setup(path, self.board, config)
        self.assertEqual(path.read_bytes(), before)

    def test_region_requires_exact_current_area_and_nets(self):
        config = dict(rule_area_id='one',signal_net='SIGNAL',reference_net='GND')
        listing = dict(areas=[{'id':'one'}],copper_net_names=['SIGNAL','GND'])
        validate_region_choices(config, listing)
        with self.assertRaisesRegex(ValueError,'rule area'):validate_region_choices(dict(config,rule_area_id='other'),listing)
        with self.assertRaisesRegex(ValueError,'net'):validate_region_choices(dict(config,signal_net='MISSING'),listing)

    def test_changed_step_source_is_not_silently_rebound(self):
        import hashlib
        step=self.root/'shape.step';step.write_bytes(b'original step fixture')
        config=dict(DEFAULT_CONFIG,advanced={'study':'scattering','step_path':str(step),
            'step_sha256':hashlib.sha256(step.read_bytes()).hexdigest()})
        path=write_setup(self.root/'step-study',self.board,config)
        self.assertEqual(read_setup(path)[0]['advanced']['step_sha256'],config['advanced']['step_sha256'])
        step.write_bytes(b'changed fixture')
        with self.assertRaisesRegex(ValueError,'changed'):read_setup(path)


try:
    if sys.platform != 'win32':raise ImportError('Native Windows display test')
    import wx
    from quick_emerge_plugin.ui import QuickEMergeFrame
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Windows wx display unavailable')
class NativeSetupHandlersTests(SetupFilesTests):
    @classmethod
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        super().setUp()
        self.frame = QuickEMergeFrame(Path(__file__).parent/'fixtures/region_coupon.kicad_pcb')
        self.frame.message = MagicMock()
    def tearDown(self):
        self.frame.close(None)
        wx.Yield()
        super().tearDown()
    def dialog(self, path, code=None):
        dialog = MagicMock()
        dialog.__enter__.return_value = dialog
        dialog.ShowModal.return_value = wx.ID_OK if code is None else code
        dialog.GetPath.return_value = str(path)
        return dialog

    def test_native_save_load_complete_config_default_project_and_cancel(self):
        f = self.frame
        f.inputs['points'].ChangeValue('17')
        f.advanced_inputs['solver_threads'].ChangeValue('2')
        expected = copy.deepcopy(f.config())
        path = self.root/'user choice'
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path)) as chooser:
            f.save_setup(None)
        self.assertEqual(Path(chooser.call_args.kwargs['defaultDir']), f.session.board.parent)
        path=path.with_suffix('.json')
        self.assertTrue(path.is_file())
        f.inputs['points'].ChangeValue('9')
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path)):
            f.load_setup(None)
        self.assertEqual(f.config(), expected)
        self.assertEqual(f.setup_path, path.resolve())
        f.result={'unchanged':'cancel'}
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path,wx.ID_CANCEL)):
            f.load_setup(None)
        self.assertEqual(f.result, {'unchanged':'cancel'})
        f.message.assert_not_called()

    def test_failed_load_and_failed_control_apply_preserve_inputs(self):
        f=self.frame;before=copy.deepcopy(f.config());f.result={'still':'current'}
        path=self.root/'other.json';path.write_text(json.dumps({'schema':1,'plugin':'quick-pi','config':DEFAULT_CONFIG}))
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path)):
            f.load_setup(None)
        self.assertEqual(f.config(),before);self.assertEqual(f.result,{'still':'current'})
        config=validate_config(dict(DEFAULT_CONFIG,solver='PARDISO'))
        with patch.object(f.solver,'SetStringSelection',side_effect=ValueError('failed choice')):
            with self.assertRaises(ValueError):f._apply_setup_config(config,path)
        self.assertEqual(f.config(),before)
        self.assertFalse(f._solver_explicit)

    def test_changed_source_declined_and_region_choice_unknown_preserve_inputs(self):
        f=self.frame;before=copy.deepcopy(f.config())
        path=write_setup(self.root/'different',self.board,DEFAULT_CONFIG)
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path)), \
             patch('quick_emerge_plugin.ui.wx.MessageDialog',return_value=self.dialog(path,wx.ID_NO)):
            f.load_setup(None)
        self.assertEqual(f.config(),before)
        region=validate_config(dict(DEFAULT_CONFIG,mode='pcb_region',rule_area_id='missing',signal_net='S',reference_net='G',region_er_reviewed=True))
        path=write_setup(self.root/'region',f.session.board,region)
        f.region_listing=dict(source=source_identity(f.session.board),areas=[{'id':'current'}],copper_net_names=['S','G'])
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path)):
            f.load_setup(None)
        self.assertEqual(f.config(),before)
        f.message.assert_called_once()

    def test_region_file_waits_for_current_inventory_before_applying(self):
        f=self.frame;before=copy.deepcopy(f.config());f.result={'preserved':'until validated'}
        region=validate_config(dict(DEFAULT_CONFIG,mode='pcb_region',rule_area_id='missing',signal_net='S',reference_net='G',region_er_reviewed=True))
        path=write_setup(self.root/'region',f.session.board,region)
        with patch('quick_emerge_plugin.ui.wx.FileDialog',return_value=self.dialog(path)), \
             patch.object(f,'load_rule_areas') as load_areas:
            f.load_setup(None)
        load_areas.assert_called_once_with()
        self.assertEqual(f.config(),before)
        f._region_done(dict(source=source_identity(f.session.board),areas=[{'id':'other'}],copper_net_names=['S','G']),None,None)
        self.assertEqual(f.config(),before)
        self.assertEqual(f.result,{'preserved':'until validated'})
        self.assertIsNone(f._pending_region_file)
        self.assertIn('rule area',f.GetStatusBar().GetStatusText())

    def test_result_load_does_not_disable_an_active_solver_or_extractor(self):
        f=self.frame;actions=MagicMock()
        with patch.object(f,'_result_file_actions',return_value=actions):
            for key in ('running','region_busy','network_busy'):
                setattr(f,key,True)
                f.load_result_file(None)
                actions.on_load.assert_not_called()
                setattr(f,key,False)
            f.load_result_file(None)
        actions.on_load.assert_called_once_with(None)


if __name__ == '__main__':unittest.main()
