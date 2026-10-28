"""Export destination custody and optional native chooser cancellation."""
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from wayricad_runtime.blender_ui import destination


class BlenderDestinationTests(unittest.TestCase):
    def test_new_child_without_creating_it(self):
        with tempfile.TemporaryDirectory() as raw:
            parent=Path(raw)
            target=destination(parent,'pi-result')
            self.assertEqual(target,parent.resolve()/'pi-result')
            self.assertFalse(target.exists())

    def test_invalid_names_cannot_escape_parent(self):
        with tempfile.TemporaryDirectory() as raw:
            for name in ('', '.', '..', '../elsewhere', 'a/b', 'a\\b', 'C:drive', 'CON', 'nul.txt', 'LPT1', 'a*', 'a\n'):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    destination(raw,name)

    def test_existing_bundle_is_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            folder=Path(raw)/'result';folder.mkdir()
            evidence=folder/'scene.json';evidence.write_text('original',encoding='utf-8')
            with self.assertRaises(ValueError):destination(raw,'result')
            self.assertEqual(evidence.read_text(encoding='utf-8'),'original')


try:
    import wx
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native wx runtime required')
class BlenderChooserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_cancel_never_submits_or_launches(self):
        from wayricad_runtime.blender_ui import choose_export
        frame=wx.Frame(None)
        calls=[]
        try:
            with patch.object(wx.Dialog,'ShowModal',return_value=wx.ID_CANCEL):
                choose_export(frame,{},'pi',lambda *args:calls.append(args),calls.append)
            self.assertEqual(calls,[])
        finally:frame.Destroy();self.app.Yield()

    def test_export_is_submitted_without_automatic_launch(self):
        from wayricad_runtime.blender_ui import choose_export
        frame=wx.Frame(None);calls=[];messages=[];bundle={'completed':'fixture'}
        target=Path('new-blender-bundle')
        def submit(operation,finished,message):
            calls.append(message);finished(operation())
        try:
            with patch.object(wx.Dialog,'ShowModal',return_value=wx.ID_OK), \
                    patch('wayricad_runtime.blender_ui.destination',return_value=target), \
                    patch('wayricad_runtime.blender_export.export_bundle',return_value={'directory':str(target)}) as export, \
                    patch('wayricad_runtime.blender_export.run_blender') as launch:
                choose_export(frame,bundle,'therm',submit,messages.append)
            export.assert_called_once_with(bundle,target,tool='therm',metric='temperature')
            launch.assert_not_called()
            self.assertEqual(len(calls),1)
            self.assertIn(str(target),messages[-1])
        finally:frame.Destroy();self.app.Yield()

    def test_si_worker_repaints_and_discards_stale_completion(self):
        try:
            # A standalone wx test is not PCB Editor's action-plugin host.
            with patch.object(wx,'GetApp',return_value=None):
                from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        except ImportError as exc:
            self.skipTest('Native SI imports unavailable: '+str(exc))
        frame=wx.Frame(None);button=wx.Button(frame);status=wx.StaticText(frame)
        original=threading.get_ident()
        try:
            for stale in (False,True):
                with self.subTest(stale=stale):
                    started=threading.Event();release=threading.Event();done=[];worker=[]
                    panel=SimpleNamespace(_closed=False,_busy=False,_circuit_busy=False,
                        _generation=0,run_button=button,status=status,_update_circuit_buttons=lambda:None)
                    def operation():
                        worker.append(threading.get_ident());started.set();release.wait(3);return 'result'
                    QuickSIPanel._blender_task(panel,operation,lambda answer:done.append((answer,threading.get_ident())),'Exporting')
                    self.assertTrue(started.wait(1));self.assertTrue(panel._circuit_busy)
                    if stale:panel._generation+=1
                    release.set();deadline=time.monotonic()+4
                    while panel._circuit_busy and time.monotonic()<deadline:
                        self.app.Yield();time.sleep(.01)
                    self.assertFalse(panel._circuit_busy)
                    self.assertNotEqual(worker,[original])
                    self.assertTrue(button.IsEnabled())
                    if stale:
                        self.assertEqual(done,[])
                        self.assertIn('previous completed result',status.GetLabel())
                    else:self.assertEqual(done,[('result',original)])
        finally:frame.Destroy();self.app.Yield()


if __name__=='__main__':unittest.main()
