"""Native study editor selections produce the public grouped-pad contract."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import wx
    from quick_pi_plugin.batch_ui import BatchStudyDialog
except ImportError:
    wx=None

_app=None


@unittest.skipIf(wx is None,'Native wx runtime required')
class BatchUnitEditorTests(unittest.TestCase):
    def test_source_unit_and_shared_return_wizards_preserve_explicit_total_current(self):
        global _app
        _app=wx.GetApp() or wx.App(False)
        initial={'schema':'wayricad.pi-batch/v1','cases':[{'name':'Rail','electrical':{
            'net':'VCC','source_terminal':'S1','source_voltage':3.3,
            'sinks':[{'terminal':'L1','current_A':.2}]}}]}
        inventory={'nets':['VCC','GND'],'terminals':[{'id':p,'label':p,'net':net}
            for net,pads in [('VCC',['S1','S2','L1']),('GND',['G0','G1','G2'])] for p in pads]}
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'board.kicad_pcb';path.write_text('(kicad_pcb)')
            dialog=BatchStudyDialog(None,initial,inventory,None,path,'fixture')
            try:
                self.assertTrue(dialog.units.IsEnabled());self.assertTrue(dialog.returns.IsEnabled())
                def select_first(choice):
                    choice.SetSelection(0);return wx.ID_OK
                def source_pads(choice):
                    choice.SetSelections([0,1]);choice.accepted=[0,1];return wx.ID_OK
                # The native multi-choice dialog commits its result only in
                # its OK handler; provide that accepted selection with the
                # modal result while keeping real dialog/control construction.
                with patch.object(wx.SingleChoiceDialog,'ShowModal',select_first),patch.object(wx.MultiChoiceDialog,'ShowModal',source_pads),patch.object(wx.MultiChoiceDialog,'GetSelections',lambda c:c.accepted):
                    dialog.edit_units()
                edited=dialog.study()['cases'][0]['electrical']
                self.assertEqual(edited['source_terminals'],['S1','S2'])
                self.assertNotIn('source_terminal',edited)
                selections=iter([[0],[0,1],[2]])
                def choose_many(choice):
                    choice.accepted=next(selections);choice.SetSelections(choice.accepted);return wx.ID_OK
                def return_net(choice):
                    choice.SetSelection(1);return wx.ID_OK
                with patch.object(wx.MultiChoiceDialog,'ShowModal',choose_many),patch.object(wx.MultiChoiceDialog,'GetSelections',lambda c:c.accepted),patch.object(wx.SingleChoiceDialog,'ShowModal',return_net),patch.object(wx.TextEntryDialog,'ShowModal',return_value=wx.ID_OK):
                    dialog.add_shared_return()
                result=dialog.study()
                self.assertEqual(result['shared_returns'][0]['source_terminals'],['G0','G1'])
                self.assertEqual(result['shared_returns'][0]['loads'],[{'case':'Rail','sink':'load-1','terminals':['G2']}])
                self.assertEqual(result['cases'][0]['electrical']['sinks'][0]['current_A'],.2)
                self.assertFalse(dialog.export.IsEnabled())
                self.assertIsNone(dialog.result)
            finally:
                dialog.Destroy();wx.CallLater(50,_app.ExitMainLoop);_app.MainLoop()


if __name__=='__main__':unittest.main()
