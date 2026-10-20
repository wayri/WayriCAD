"""Native saved-board batch extraction, explicit return audit and GUI case review."""
from pathlib import Path
import tempfile
import time
import unittest
try:
    import pcbnew,wx
except ImportError:
    pcbnew=wx=None


def make_board(path):
    board=pcbnew.BOARD()
    point=lambda x,y:pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))
    for code,name in enumerate(('DATA','CLOCK','GND'),1):board.Add(pcbnew.NETINFO_ITEM(board,name,code))
    for reference,x in [('U1',5),('J1',65)]:
        fp=pcbnew.FOOTPRINT(board);fp.SetReference(reference);fp.SetPosition(point(x,10));board.Add(fp)
        for number,net,y in [('1',1,10),('2',2,20),('3',3,30)]:
            pad=pcbnew.PAD(fp);pad.SetNumber(number);pad.SetPosition(point(x,y));pad.SetSize(point(1.5,1.5))
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH);pad.SetDrillSize(point(.7,.7));pad.SetLayerSet(pcbnew.LSET.AllCuMask());pad.SetNetCode(net);fp.Add(pad)
    for code,y in [(1,10),(2,20)]:
        for x in (25,45):
            via=pcbnew.PCB_VIA(board);via.SetPosition(point(x,y));via.SetWidth(pcbnew.F_Cu,pcbnew.FromMM(.6));via.SetDrill(pcbnew.FromMM(.3));via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);via.SetNetCode(code);board.Add(via)
        for start,end,layer in [(5,25,pcbnew.F_Cu),(25,45,pcbnew.B_Cu),(45,65,pcbnew.F_Cu)]:
            track=pcbnew.PCB_TRACK(board);track.SetStart(point(start,y));track.SetEnd(point(end,y));track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(layer);track.SetNetCode(code);board.Add(track)
    ground=pcbnew.PCB_TRACK(board);ground.SetStart(point(5,30));ground.SetEnd(point(65,30));ground.SetWidth(pcbnew.FromMM(1));ground.SetLayer(pcbnew.B_Cu);ground.SetNetCode(3);board.Add(ground)
    pcbnew.SaveBoard(str(path),board)
    inputs={'rise_ns':1.,'frequency_mhz':100.,'source_ohm':20.,'z0_ohm':50.,'epsilon_eff':3.,
            'return_nets':['GND'],'return_terminal_ids':['U1.3','J1.3'],'return_terminal_roles':{'source':'U1.3','load':'J1.3'}}
    return {'schema':'wayricad.quick-si-study-input/v1','cases':[
        {'id':'data','net':'DATA','start':'U1.1','end':'J1.1','reference':'Auto','inputs':dict(inputs)},
        {'id':'clock','net':'CLOCK','start':'U1.2','end':'J1.2','reference':'Auto','inputs':dict(inputs)},
        {'id':'unassigned','net':'DATA','start':'','end':'J1.1','inputs':{}}]}


@unittest.skipIf(pcbnew is None,'Native KiCad Python required')
class NativeStudyTests(unittest.TestCase):
    def test_saved_worker_extracts_two_via_routes_and_explicit_returns(self):
        from signal_integrity_advisor_plugin.service import source_fingerprints,run_job
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'study.kicad_pcb';config=make_board(path);fingerprints=source_fingerprints(path)
            payload=run_job({'mode':'study','board_path':str(path),'source_fingerprints':fingerprints,'study':config},python=__import__('sys').executable)
            report=payload['study'];self.assertEqual(report['summary'],{'cases':3,'reported':2,'errors':1})
            for case in report['cases'][:2]:
                self.assertGreater(case['report']['delay_ns'],0);self.assertEqual(case['path_data']['via_count'],2)
                self.assertEqual(case['report']['return_path']['return_nets'],['GND'])
                self.assertEqual(set(case['report']['return_path']['return_terminal_roles']),{'source','load'})
                self.assertEqual(case['source_fingerprints'] if 'source_fingerprints' in case else report['source_fingerprints'],fingerprints)
            self.assertEqual(source_fingerprints(path),fingerprints)


_app=None
@unittest.skipIf(pcbnew is None or wx is None,'Native KiCad wx runtime required')
class NativeStudyUITests(unittest.TestCase):
    def test_gui_worker_case_switch_preserves_errors_and_reviewed_return_selection(self):
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
        global _app
        _app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'study.kicad_pcb';config=make_board(path);board=pcbnew.LoadBoard(str(path))
            frame=wx.Frame(None,size=(1024,720));panel=QuickSIPanel(frame,board,RoutePreview,saved_board=True)
            layout=wx.BoxSizer(wx.VERTICAL);layout.Add(panel,1,wx.EXPAND);frame.SetSizer(layout)
            try:
                panel.study_cases=config['cases'];frame.Show();panel.run_study()
                deadline=time.monotonic()+30
                while panel._busy and time.monotonic()<deadline:_app.Yield();time.sleep(.05)
                self.assertFalse(panel._busy,panel.status.GetLabel());self.assertIsNotNone(panel.study_report,panel.status.GetLabel())
                self.assertEqual(panel.study_choice.GetCount(),3);self.assertIsNotNone(panel.path)
                self.assertEqual(panel._review_return_nets(),['GND'])
                panel.study_choice.SetSelection(2);panel._select_study_case()
                self.assertIsNone(panel.path);self.assertIn('Case failed',panel.status.GetLabel());self.assertTrue(panel.export.IsEnabled())
                panel.study_choice.SetSelection(1);panel._select_study_case()
                self.assertEqual(panel.path.net_name,'CLOCK');self.assertEqual(panel._review_return_nets(),['GND'])
                panel.changed(None);self.assertIsNone(panel.study_report);self.assertFalse(panel.export.IsEnabled())
            finally:frame.Destroy();_app.Yield()
