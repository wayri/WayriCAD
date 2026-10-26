"""AC intake, provenance, read-only export and native interaction contracts."""
import copy
from argparse import Namespace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from quick_pi_plugin.ac_cli import main as cli_main, parse_study
from quick_pi_plugin.ac_report import draw, write_report


def example():
    return {'schema':'wayricad.pi-ac/v1','length_mm':20.,'reference_voltage_v':12.,
            'dc_current_a':5.,'temperature_c':20.,
            'conductors':[{'name':'Supply','x_mm':0.,'y_mm':0.,'width_mm':2.,'thickness_mm':.07,'current_scale':1.},
                          {'name':'Return','x_mm':0.,'y_mm':-.8,'width_mm':2.,'thickness_mm':.07,'current_scale':-1.}],
            'harmonics':[{'frequency_hz':100000.,'current_rms_a':1.}],
            'mesh_step_mm':.035,'air_padding_mm':4.,'max_cells':50000,'convergence_tolerance':.05}


def result_bundle():
    study = example()
    return {'study':study,'study_sha256':hashlib.sha256(json.dumps(study,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
            'ac':{'schema':'wayricad.pi-ac-result/v1','status':'CONVERGED',
                  'dc_loss_w':.123,'ac_loss_w':.005,'total_loss_w':.128,
                  'harmonics':[{'frequency_hz':100000.,'current_rms_a':1.,'resistance_ohm':.005,'reactance_ohm':.02,'loss_w':.005,'skin_depth_mm':.2}],
                  'conductors':[{'name':'Supply','dc_loss_w':.0615,'ac_loss_w':.0025,'total_loss_w':.064},
                                {'name':'Return','dc_loss_w':.0615,'ac_loss_w':.0025,'total_loss_w':.064}],
                  'checks':{'power_relative_error':0.},'limitations':['Explicit straight cross-section only.']}}


class ACWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_repeated_fields_nonfinite_nesting_and_schema_are_rejected(self):
        invalid = ['{"schema":"wayricad.pi-ac/v1","schema":"wayricad.pi-ac/v1"}',
                   '{"schema":"wayricad.pi-ac/v1","current":NaN}',
                   '{"schema":"wayricad.pi-ac/v1","current":1e999}',
                   '{"schema":"wrong"}',
                   '{"schema":"wayricad.pi-ac/v1","x":'+('['*34)+'0'+(']'*34)+'}']
        for text in invalid:
            with self.subTest(text=text),self.assertRaises(ValueError): parse_study(text.encode())
        self.assertEqual(parse_study(json.dumps(example()).encode()),example())

    def test_cli_passes_custody_and_rejects_source_aliases_and_unrelated_flags(self):
        source = self.root/'study.json'; source.write_text(json.dumps(example()),encoding='utf-8')
        args = Namespace(ac=source,board=None,output=source,html=None,timeout=4.)
        with self.assertRaisesRegex(ValueError,'overwrite'): cli_main(args,lambda *a,**k:None)
        args.output = None; args.html = source.with_suffix('.html')
        with self.assertRaisesRegex(ValueError,'overwrite'): cli_main(args,lambda *a,**k:None)
        args.html = None
        with self.assertRaisesRegex(ValueError,'unrelated'): cli_main(args,lambda *a,**k:None,forbidden=True)
        calls = []
        def runner(request,timeout): calls.append((request,timeout)); return result_bundle()
        args.output = self.root/'result.json'
        with patch('builtins.print'): self.assertEqual(cli_main(args,runner),0)
        self.assertEqual(calls[0][0]['action'],'ac')
        self.assertEqual(calls[0][0]['study_file_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(json.loads(args.output.read_text())['ac']['status'],'CONVERGED')
        with patch('builtins.print'):
            self.assertEqual(cli_main(args,lambda *a,**k:{'ac':{'status':'UNCONVERGED'}}),3)

    def test_report_three_visuals_selection_and_script_safe_names(self):
        from matplotlib.figure import Figure
        bundle = result_bundle(); figure = Figure(figsize=(11,5)); draw(figure,bundle)
        self.assertEqual(len(figure.axes),3)
        target = self.root/'ac.html'; write_report(target,bundle)
        html = target.read_text(encoding='utf-8')
        self.assertEqual(html.count('<svg'),3)
        self.assertIn('data-conductor="Supply"',html); self.assertIn('data-harmonic="0"',html)
        self.assertIn('pickHarmonic',html); self.assertIn('pickConductor',html)
        self.assertIn('No complete SMPS',html)
        self.assertNotIn('src="https://',html)
        self.assertEqual(json.loads(target.with_suffix('.json').read_text())['study'],example())
        changed = copy.deepcopy(bundle); changed['study']['length_mm'] = 40.
        with self.assertRaisesRegex(ValueError,'settings changed'): write_report(target,changed)

    def test_real_worker_report_and_saved_board_are_read_only(self):
        try: import scipy
        except ImportError: self.skipTest('Scientific runtime required for the actual AC worker')
        source = self.root/'request.json'; response = self.root/'response.json'
        board = self.root/'example.kicad_pcb'; board.write_bytes(b'(kicad_pcb (version 20250101))')
        digest = hashlib.sha256(board.read_bytes()).hexdigest()
        source.write_text(json.dumps({'action':'ac','study':example(),'board_path':str(board),
                                      'source_sha256':digest,'html_output':str(self.root/'worker.html')}),encoding='utf-8')
        script = Path(__file__).resolve().parents[1]/'quickmain.py'
        environment = os.environ.copy(); environment.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
        done = subprocess.run([sys.executable,'-I','-B',str(script),'--worker',str(source),str(response)],
                              env=environment,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=90)
        self.assertEqual(done.returncode,0,done.stderr)
        bundle = json.loads(response.read_text(encoding='utf-8'))
        self.assertEqual(bundle['ac']['status'],'CONVERGED',bundle.get('error'))
        self.assertEqual(bundle['board_binding'],'provenance_only')
        self.assertEqual(hashlib.sha256(board.read_bytes()).hexdigest(),digest)
        self.assertGreater(len(bundle['ac']['cells']),0)
        html = (self.root/'worker.html').read_text(encoding='utf-8')
        self.assertIn('class="cell"',html); self.assertIn('Copper-loop AC drop RMS',html)

    def test_report_stale_source_and_paired_publication_rollback(self):
        bundle = result_bundle(); source = self.root/'saved.kicad_pcb'; source.write_bytes(b'unchanged source')
        bundle.update(board_path=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        target = self.root/'ac.html'; data = target.with_suffix('.json')
        target.write_bytes(b'OLD_HTML'); data.write_bytes(b'OLD_JSON')
        real_replace = os.replace; calls = []
        def fail_second(source,target):
            calls.append(target)
            if len(calls)==2: raise OSError('injected publication failure')
            return real_replace(source,target)
        with patch('quick_pi_plugin.ac_report.os.replace',side_effect=fail_second):
            with self.assertRaisesRegex(OSError,'publication failure'): write_report(target,bundle)
        self.assertEqual(target.read_bytes(),b'OLD_HTML'); self.assertEqual(data.read_bytes(),b'OLD_JSON')
        self.assertEqual(set(self.root.iterdir()),{target,data,source})
        bundle['study_input_path'] = str(data)
        with self.assertRaisesRegex(ValueError,'overwrite'): write_report(target,bundle)
        bundle.pop('study_input_path'); source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,'changed'): write_report(target,bundle)


try:
    import wx
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg, NavigationToolbar2WxAgg
    from quick_pi_plugin.ac_ui import ACStudyDialog
except ImportError:
    wx = None

_native_app = None


@unittest.skipIf(wx is None,'Native wx runtime required')
class ACNativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        global _native_app
        _native_app = wx.GetApp() or wx.App(False)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            if not dialog._closed: dialog._close()
        wx.CallLater(50,_native_app.ExitMainLoop); _native_app.MainLoop()

    def dialog(self,runner=None):
        runner = runner or (lambda request,cancel:result_bundle())
        dialog = ACStudyDialog(None,runner,(FigureCanvasWxAgg,NavigationToolbar2WxAgg))
        self.dialogs.append(dialog); return dialog

    def wait_for(self,condition):
        deadline = time.monotonic()+30
        while not condition():
            wx.YieldIfNeeded()
            if time.monotonic()>deadline: self.fail('AC native worker did not finish.')
            time.sleep(.005)
        wx.YieldIfNeeded()

    def test_guided_inputs_plot_table_and_invalidation(self):
        dialog = self.dialog(); dialog.Show(); dialog.Layout(); dialog._run()
        self.wait_for(lambda:not dialog._busy)
        self.assertIsNotNone(dialog.result,dialog.status.GetLabel()); self.assertEqual(len(dialog.figure.axes),3)
        self.assertEqual(dialog.table.GetItemCount(),1); dialog._select_harmonic(0)
        self.assertTrue(dialog.table.IsSelected(0)); self.assertEqual(len(dialog._focus),2)
        dialog._select_conductor(0);self.assertTrue(dialog.conductor_table.IsSelected(0))
        dialog.fields['dc_current_a'].SetValue('6'); self.wait_for(lambda:dialog.result is None)
        self.assertFalse(dialog.export.IsEnabled())

    def test_close_cancels_worker_and_discards_partial_result(self):
        started = threading.Event()
        def runner(request,cancel):
            started.set()
            while not cancel(): time.sleep(.002)
            return result_bundle()
        dialog = self.dialog(runner); dialog._run(); self.wait_for(started.is_set); dialog._close()
        self.wait_for(lambda:dialog._closed)
        self.assertIsNone(dialog.result)

    def test_real_field_hover_and_conductor_selection(self):
        try: import scipy
        except ImportError: self.skipTest('Scientific runtime required for the actual AC field')
        from quick_pi_plugin.service import execute
        dialog = self.dialog(lambda request,cancel:execute(request));dialog.Show();dialog.Layout();dialog._run()
        self.wait_for(lambda:not dialog._busy)
        self.assertIsNotNone(dialog.result,dialog.status.GetLabel())
        self.assertGreater(len(dialog.figure.axes[0].collections),0)
        cell = dialog.result['ac']['cells'][0]
        dialog._hover(Namespace(inaxes=dialog.figure.axes[0],xdata=cell['x_mm'],ydata=cell['y_mm']))
        self.assertIn('RMS J',dialog.status.GetLabel())
        dialog._select_conductor(1);self.assertTrue(dialog.conductor_table.IsSelected(1))
        capture = os.environ.get('AC_UI_CAPTURE')
        if capture:
            dialog.canvas.draw();wx.YieldIfNeeded()
            width,height = dialog.GetClientSize()
            bitmap = wx.Bitmap(width,height);memory = wx.MemoryDC(bitmap)
            memory.Blit(0,0,width,height,wx.ClientDC(dialog),0,0);memory.SelectObject(wx.NullBitmap)
            bitmap.SaveFile(capture,wx.BITMAP_TYPE_PNG)

    def test_manual_waveform_change_discards_generated_metadata(self):
        from quick_pi_plugin.ac_analysis import waveform_harmonics
        dialog = self.dialog();study = example()
        config = {'kind':'triangle','frequency_hz':100000.,'amplitude_a':2.,'terms':8,'duty':.5,'dc_current_a':5.}
        generated = waveform_harmonics(**config)
        study.update(dc_current_a=generated['dc_current_a'],harmonics=generated['harmonics'],waveform=config)
        dialog._load_controls(study)
        self.assertEqual(dialog._study()['waveform'],config)
        dialog.fields['dc_current_a'].SetValue('7');wx.YieldIfNeeded()
        self.assertNotIn('waveform',dialog._study())


if __name__=='__main__': unittest.main()
