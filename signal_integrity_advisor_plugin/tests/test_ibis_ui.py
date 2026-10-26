"""Native IBIS control checks with synthetic metadata (no user models)."""
import importlib.util
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


def catalog():
    return {
        'path': 'C:/Projects/Example/device.ibs', 'sha256': 'a'*64,
        'components': {'Device': {'pins': {
            '1': {'signal_name': 'TX', 'model_name': 'TX_SEL'},
            '2': {'signal_name': 'RX', 'model_name': 'RX'},
            '4': {'signal_name': 'TX4', 'model_name': 'TX'},
            'A.1': {'signal_name': 'TX2', 'model_name': 'TX'},
        }}},
        'models': {
            'TX': {'model_type': 'Output', 'roles': ['source']},
            'TX_ALT': {'model_type': 'Output', 'roles': ['source']},
            'RX': {'model_type': 'Input', 'roles': ['sink']},
        },
        'selectors': {'TX_SEL': {'models': ['TX', 'TX_ALT']}},
    }


@unittest.skipUnless(importlib.util.find_spec('wx'), 'KiCad wxPython is required')
class IbisNativeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        from signal_integrity_advisor_plugin.ibis_ui import IbisPane
        self.frame = self.wx.Frame(None)
        self.changes = []
        self.pane = IbisPane(self.frame, lambda: self.changes.append(1))
        self.frame.Show()
        self.app.Yield()

    def tearDown(self):
        self.frame.Destroy()
        self.app.Yield()

    def test_exact_pad_and_single_supported_model_only(self):
        from signal_integrity_advisor_plugin.ibis_ui import model_choices
        model = catalog()
        self.assertEqual(model_choices(model, 'Device', '1', 'source'), ['TX', 'TX_ALT'])
        self.assertEqual(model_choices(model, 'Device', '1', 'sink'), [])
        self.pane._catalogs[model['path']] = model
        self.pane._current['source'] = model
        self.pane._current['sink'] = model
        self.pane.set_context('DATA', 'U1.1', 'U2.2')
        self.assertIsNone(self.pane.assignment('DATA', 'source', 'U1.1'))
        self.assertEqual(self.pane.assignment('DATA', 'sink', 'U2.2')['model'], 'RX')
        self.pane._controls['source']['model'].SetStringSelection('TX')
        self.pane._selection_changed('source', 'model')
        self.assertEqual(self.pane.assignment('DATA', 'source', 'U1.1')['pin'], '1')
        self.assertEqual(self.pane.assignment('DATA', 'source', 'U1.1')['corners']['vcc'], 'typ')
        self.pane.set_context('OTHER', 'U1.9', 'U2.9')
        self.assertIsNone(self.pane.assignment('OTHER', 'source', 'U1.9'))
        self.assertIsNone(self.pane.assignment('OTHER', 'sink', 'U2.9'))
        self.pane._controls['source']['pin'].SetStringSelection('4')
        self.pane._selection_changed('source', 'pin')
        self.assertEqual(self.pane.assignment('OTHER', 'source', 'U1.9')['pin'], '4')
        self.assertIn('U1.9 → Device.4', self.pane._controls['source']['endpoint'].GetLabel())
        self.pane.set_context('BUS', 'U1.A.1', 'U2.2')
        self.assertEqual(self.pane.assignment('BUS', 'source', 'U1.A.1')['pin'], 'A.1')
        self.pane.set_context('OTHER', 'U1.9', 'U2.9')
        self.assertEqual(self.pane._controls['source']['pin'].GetStringSelection(), '4')
        self.pane.set_context('DATA', 'U1.1', 'U2.2')
        self.assertEqual(self.pane.assignment('DATA', 'source', 'U1.1')['model'], 'TX')

    def test_changed_file_requires_new_selection_and_stale_load_is_ignored(self):
        first = catalog()
        self.pane._catalogs[first['path']] = first
        self.pane._current['source'] = first
        self.pane.set_context('DATA', 'U1.1', 'U2.2')
        self.pane._controls['source']['model'].SetStringSelection('TX')
        self.pane._selection_changed('source', 'model')
        self.assertIsNotNone(self.pane.assignment('DATA', 'source', 'U1.1'))
        changed = deepcopy(first)
        changed['sha256'] = 'b'*64
        serial = self.pane._serial['source']
        context = self.pane._context
        self.pane._loaded('source', serial, context, changed, None)
        self.assertIsNone(self.pane.assignment('DATA', 'source', 'U1.1'))
        self.pane._controls['source']['model'].SetStringSelection('TX')
        self.pane._selection_changed('source', 'model')
        self.assertEqual(self.pane.assignment('DATA', 'source', 'U1.1')['sha256'], 'b'*64)
        self.pane._loaded('source', serial-1, context, first, None)
        self.assertEqual(self.pane._current['source']['sha256'], 'b'*64)

    def test_quick_si_model_change_keeps_route_and_stale_copy_is_blocked(self):
        from types import SimpleNamespace
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        fake = SimpleNamespace(_closed=False, _circuit_busy=True, _circuit_generation=4,
                               status=SimpleNamespace(SetLabel=lambda value: labels.append(value)),
                               _update_circuit_buttons=lambda: None)
        labels = []
        QuickSIPanel._circuit_finished(fake, 3, {}, {}, 'unused', True,
                                       {'clipboard_text': 'must not copy'}, None)
        self.assertIn('clipboard was not changed', labels[-1])
        fake.report = {'path': {'net_name': 'DATA', 'start_pad': 'U1.1', 'end_pad': 'U2.2'}}
        fake.study_report = None
        fake._circuit_generation = 4
        QuickSIPanel._circuit_inputs_changed(fake)
        self.assertEqual(fake._circuit_generation, 5)
        self.assertIsNotNone(fake.report)
        case = QuickSIPanel._circuit_cases(fake)[0]
        self.assertEqual((case['start'], case['end']), ('U1.1', 'U2.2'))

    def test_copper_thickness_is_blank_by_default_and_explicit_when_entered(self):
        from signal_integrity_advisor_plugin.ibis_ui import circuit_options_dialog
        counts=[]
        def accept(value):
            dialog=next((window for window in self.wx.GetTopLevelWindows()
                         if window.GetTitle()=='KiCad circuit export settings' and window.IsModal()),None)
            if dialog is None:
                self.wx.CallLater(50,accept,value)
                return
            fields=[child for child in dialog.GetChildren() if isinstance(child,self.wx.TextCtrl)]
            counts.append(len(fields))
            if value and len(fields)>4:fields[4].SetValue(value)
            dialog.EndModal(self.wx.ID_OK)
        for value,expected in (('',None),('18',18.)):
            self.wx.CallLater(50,accept,value)
            options=circuit_options_dialog(self.frame)
            self.assertEqual(counts[-1],7)
            self.assertEqual(options['copper_thickness_um'],expected)

    @unittest.skipUnless(importlib.util.find_spec('pcbnew'), 'KiCad native board bindings are required')
    def test_saved_export_uses_exact_assignments_and_rejects_changed_board(self):
        import pcbnew
        from signal_integrity_advisor_plugin.tests.test_study_native import make_board
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel, _model_source_stamps
        from signal_integrity_advisor_plugin.ibis_models import load_ibis
        from signal_integrity_advisor_plugin.service import source_fingerprints
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            board_path = root/'sample.kicad_pcb'
            make_board(board_path)
            ibis_path = root/'device.ibs'
            ibis_path.write_text('[IBIS Ver] 4.1\n[Component] Device\n[Pin] signal_name model_name\n1 SIG IO\n[Model] IO\nModel_type I/O\n[End]\n', encoding='ascii')
            model = load_ibis(ibis_path)
            board = pcbnew.LoadBoard(str(board_path))
            frame = self.wx.Frame(None, size=(1100, 760))
            panel = QuickSIPanel(frame, board, RoutePreview, saved_board=True)
            frame.Show();self.app.Yield()
            try:
                panel.report = {'status': 'SCREENED', 'path': {'net_name': 'DATA',
                                'start_pad': 'U1.1', 'end_pad': 'J1.1'}}
                panel._result_fingerprints = source_fingerprints(board_path)
                panel.ibis._catalogs[model['path']] = model
                panel.ibis._current.update(source=model, sink=model)
                panel.ibis.set_context('DATA', 'U1.1', 'J1.1')
                self.assertEqual(panel.ibis.assignment('DATA', 'source', 'U1.1')['model'], 'IO')
                self.assertEqual(panel.ibis.assignment('DATA', 'sink', 'J1.1')['model'], 'IO')

                class FolderDialog:
                    def __init__(self, *args, **kwargs):pass
                    def __enter__(self):return self
                    def __exit__(self, *args):pass
                    def ShowModal(self):return self_wx.ID_OK
                    def GetPath(self):return str(root)

                self_wx = self.wx
                exported = []
                def stub_export(cases, destination, options, *, guard=None):
                    guard()
                    exported.append((cases, options))
                    destination.mkdir()
                    return {'schematic': str(destination/'circuit.kicad_sch'),
                            'clipboard_text': 'not copied'}

                with patch('signal_integrity_advisor_plugin.ibis_ui.circuit_options_dialog',
                           return_value={'duration_ns': 100., 'timestep_ns': .1,
                                         'frequency_mhz': 100., 'duty_percent': 50.,
                                         'allow_approximations': False,
                                         'copper_thickness_um': None,
                                         'via_capacitance_pf': None, 'via_inductance_nh': None}), \
                     patch('wx.DirDialog', FolderDialog), \
                     patch('signal_integrity_advisor_plugin.si_circuit.export_circuit', side_effect=stub_export):
                    panel._start_circuit_export(False)
                    deadline = time.monotonic()+10
                    while panel._circuit_busy and time.monotonic()<deadline:
                        self.app.Yield();time.sleep(.02)
                self.assertFalse(panel._circuit_busy, panel.status.GetLabel())
                self.assertEqual(len(exported), 1)
                self.assertEqual(exported[0][0][0]['source']['pin'], '1')
                self.assertEqual(exported[0][0][0]['sink']['role'], 'sink')
                self.assertIsNone(exported[0][1]['copper_thickness_um'])
                self.assertIn('bundle exported', panel.status.GetLabel())
                model_stamps=_model_source_stamps([ibis_path])
                ibis_path.write_bytes(ibis_path.read_bytes()+b'\n')
                clipboard_guard=type('ClipboardGuard',(),{'Open':lambda self: (_ for _ in ()).throw(
                    AssertionError('stale export touched clipboard'))})()
                with patch('signal_integrity_advisor_plugin.quick_ui.wx.TheClipboard',clipboard_guard):
                    panel._circuit_finished(panel._circuit_generation,panel._result_fingerprints,
                                            model_stamps,root/'previous',True,
                                            {'clipboard_text':'must not copy'},None)
                self.assertIn('IBIS model file changed',panel.status.GetLabel())
                board_path.write_bytes(board_path.read_bytes()+b'\n')
                panel._start_circuit_export(False)
                self.assertIn('Saved PCB or rules changed', panel.status.GetLabel())
                self.assertEqual(len(exported), 1)
            finally:
                frame.Destroy();self.app.Yield()


if __name__ == '__main__':
    unittest.main()
