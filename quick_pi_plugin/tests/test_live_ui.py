"""Native wheel/current controls: coalescing, view reuse and stale-file guards."""
import hashlib
import tempfile
import time
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None

_app=None


@unittest.skipIf(wx is None,'Native KiCad wx runtime required')
class LiveUITests(unittest.TestCase):
    def setUp(self):
        global _app
        _app=wx.GetApp() or wx.App(False)
        self.loop=wx.GUIEventLoop();self.activator=wx.EventLoopActivator(self.loop)
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'live-strip.kicad_pcb'
        pcbnew.SaveBoard(str(self.path),pcbnew.BOARD())
        with patch.object(QuickPIFrame,'_inspect'):
            self.frame=QuickPIFrame(None,str(self.path))
        from quick_pi_plugin.tests.test_report import bundle
        value=bundle();value['request'].update(action='solve',source_voltage=1,sink_current=2)
        value['geometry']['source_sha256']=hashlib.sha256(self.path.read_bytes()).hexdigest()
        value['board_scene']={'bounds':[0,0,10,1],'layers':{0:'F.Cu'},'primitives':[],'warnings':[]}
        self.frame.net.Set(['Analytical strip']);self.frame.net.SetValue('Analytical strip')
        self.frame._terminals=[{'id':'A','label':'A.1'},{'id':'B','label':'B.1'}]
        for control in (self.frame.source,self.frame.sink):control.Set(['A.1','B.1'])
        self.frame.source.SetSelection(0);self.frame.sink.SetSelection(1)
        self.frame._accept_result(value,value['request'],'solve');self.frame.Show()
        self.until(lambda:self.frame._live_model is not None)
        self.frame.views[2][1].draw();_app.Yield()

    def tearDown(self):
        self.frame._end();_app.Yield();self.directory.cleanup();self.activator=None

    def until(self,condition):
        deadline=time.monotonic()+5
        while not condition() and time.monotonic()<deadline:_app.Yield();time.sleep(.005)
        self.assertTrue(condition(),str({'current':self.frame.bundle.get('result',{}).get('sink_current_A'),'control':self.frame.live_current.GetValue(),'pending':self.frame._live_pending,'running':self.frame._live_running,'note':self.frame.live_note.GetLabel(),'busy':self.frame._busy}))

    def event(self,**changes):
        args=dict(inaxes=self.frame.views[2][0].axes[0],xdata=5.,ydata=.5,key=None,guiEvent=None,step=1.)
        args.update(changes);return SimpleNamespace(**args)

    def test_wheel_burst_coalesces_without_rebuilding_or_changing_zoom(self):
        frame=self.frame;figure,canvas,_=frame.views[2];ax=figure.axes[0]
        axes=id(ax);artists=[id(x) for x in ax.collections];limits=(ax.get_xlim(),ax.get_ylim())
        update=frame._live_model.update
        with patch.object(frame._live_model,'update',wraps=update) as calls,patch.object(frame,'_draw',side_effect=AssertionError('Live update rebuilt the board')):
            for _ in range(10):self.assertTrue(frame._live_wheel(self.event()))
            self.until(lambda:abs(frame.bundle['result']['sink_current_A']-3)<1e-8 and not frame._live_running)
            self.assertEqual(calls.call_count,1)
        self.assertEqual(id(figure.axes[0]),axes);self.assertEqual(artists,[id(x) for x in ax.collections])
        self.assertEqual((ax.get_xlim(),ax.get_ylim()),limits)
        self.assertAlmostEqual(float(frame.current.GetValue()),3)
        self.assertTrue(frame.export.IsEnabled())

    def test_empty_space_ctrl_zoom_and_disabled_scroll_do_not_change_load(self):
        self.assertFalse(self.frame._live_wheel(self.event(key='control')))
        self.assertFalse(self.frame._live_wheel(self.event(xdata=50,ydata=50)))
        self.frame.live_scroll.SetValue(False)
        self.assertFalse(self.frame._live_wheel(self.event()))
        self.assertEqual(self.frame.bundle['result']['sink_current_A'],2)

    def test_changed_saved_board_disables_live_basis(self):
        self.path.write_bytes(self.path.read_bytes()+b'\n')
        self.frame._queue_live_current(3)
        self.assertIsNone(self.frame._live_model);self.assertFalse(self.frame.live_current.IsEnabled())
        self.assertIn('changed',self.frame.status.GetLabel())

    def test_superseded_worker_never_publishes_and_selection_survives(self):
        frame=self.frame;started=threading.Event();release=threading.Event();original=frame._live_model.update
        from quick_pi_plugin.report import inspection_record
        frame._inspection=inspection_record(frame.bundle,'sheet',0,'drop');frame._inspection['source_ids']=['saved-track']
        def slow(value):
            if value==2.5:started.set();release.wait(3)
            return original(value)
        with patch.object(frame._live_model,'update',side_effect=slow),patch.object(frame,'_show_live_current',wraps=frame._show_live_current) as shown:
            frame._live_pending=2.5;frame._start_live_current();self.until(started.is_set)
            frame.live_current.SetValue(3.5);frame._queue_live_current(3.5);release.set()
            self.until(lambda:frame.bundle['result']['sink_current_A']==3.5 and not frame._live_running)
            self.assertEqual(shown.call_count,1)
        self.assertEqual(frame._inspection['source_ids'],['saved-track'])

    def test_toolbar_mode_defers_wheel_and_context_job_retains_basis(self):
        frame=self.frame;model=frame._live_model
        frame.views[2][2].mode='pan/zoom'
        self.assertFalse(frame._live_wheel(self.event()))
        frame.views[2][2].mode=''
        with patch.object(frame,'_task'):
            frame._job({'action':'inspect'},lambda result:None,'Reading context')
        self.assertIs(frame._live_model,model)


if __name__=='__main__':unittest.main()
