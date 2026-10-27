"""Native protocol timing controls and stale-result invalidation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from signal_integrity_advisor_plugin.tests.test_pair_timing import route


@unittest.skipUnless(importlib.util.find_spec('wx'), 'Native wxPython required')
class PairTimingUITests(unittest.TestCase):
    def test_frequency_results_and_invalidation(self):
        import wx
        from signal_integrity_advisor_plugin.protocol_ui import ProtocolPanel
        app=wx.GetApp() or wx.App(False)
        class Preview(wx.Panel):
            def __init__(self,parent):
                super().__init__(parent);self.route_endpoints=[];self.tracks=[]
            def fit(self):pass
            def show_result(self,result):pass
            def zoom_in(self):pass
            def zoom_out(self):pass
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'board.kicad_pcb';source.write_text('(kicad_pcb)')
            frame=wx.Frame(None,size=(1300,850))
            quick=SimpleNamespace(board=SimpleNamespace(GetFileName=lambda:str(source)),report=None)
            panel=ProtocolPanel(frame,quick,Preview)
            try:
                for role,delay in [('P',1),('N',1.125)]:
                    report=route(role,delay);report['board_sha256']=panel.digest
                    panel.snapshots.append(dict(report=report,path=SimpleNamespace(segments=[]),endpoints=[]))
                    row=panel.routes.GetNumberRows();panel.routes.AppendRows()
                    panel.routes.SetCellValue(row,1,role);panel.routes.SetCellValue(row,2,'lane0')
                panel.timing_frequency.SetValue('1000');frame.Show();app.Yield()
                panel.run()
                self.assertIsNotNone(panel.result,panel.status.GetLabel())
                self.assertEqual(panel.pair_results.GetItemText(0,5),'-45')
                panel.select_pair(SimpleNamespace(GetIndex=lambda:0))
                self.assertIn('N - P',panel.pair_detail.GetValue())
                panel.timing_frequency.SetValue('500');app.Yield()
                self.assertIsNone(panel.result)
                self.assertEqual(panel.pair_results.GetItemCount(),0)
                panel.run();self.assertEqual(panel.pair_results.GetItemText(0,5),'-22.5')
            finally:frame.Destroy();app.Yield()
