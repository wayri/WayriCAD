"""Run-readiness guidance and complete result-table copying in native windows."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from quick_pi_plugin.inspector_tables import table_text

try:
    import wx, pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
    from quick_pi_plugin.inspector_tables import InspectorTable
    from quick_pi_plugin.tests.test_workspace_ui import portrait_board
except ImportError:
    wx=None

_app=None


class TableCopyTests(unittest.TestCase):
    def test_copy_retains_complete_values_unknowns_and_one_row_per_record(self):
        rows=[{'cells':('Long\tcomponent\nname',.123456789012345,None)},
              {'cells':('Other',float('nan'),'W')}]
        text=table_text(['Copper','Loss','Unit'],rows)
        self.assertEqual(text,'Copper\tLoss\tUnit\nLong component name\t0.123456789012345\tUnknown\nOther\tUnknown\tW')
        self.assertEqual(len(text.splitlines()),3)


@unittest.skipIf(wx is None,'Native KiCad/wx required')
class NativePolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        cls.path=Path(cls.directory.name)/'power-demo.kicad_pcb'
        portrait_board(cls.path)
        # Initialize KiCad's native manager before wx for a normal clean exit.
        cls.board=pcbnew.LoadBoard(str(cls.path))
        global _app
        _app=wx.GetApp() or wx.App(False);cls.app=_app

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def setUp(self):
        self.before=self.path.read_bytes()
        with patch.object(QuickPIFrame,'_inspect'):
            self.frame=QuickPIFrame(None,str(self.path))
        f=self.frame
        f.net.Set(['5V_DEMO']);f.net.SetValue('5V_DEMO')
        f._terminals=[{'id':'A','label':'U1.1'},{'id':'B','label':'U2.1'}]
        for choice,index in ((f.source,0),(f.sink,1)):
            choice.Set(['U1.1','U2.1']);choice.SetSelection(index)
        f.Maximize(False);f.SetSize((1000,700));f.Show();f._buttons();self.app.Yield()

    def tearDown(self):
        self.frame._end();self.app.Yield()
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_same_endpoint_and_stale_source_disable_both_run_buttons_with_reason(self):
        f=self.frame
        self.assertTrue(f.run.IsEnabled());self.assertTrue(f.toolbar_run.IsEnabled())
        self.assertIn('Ready.',f.toolbar_run.GetToolTipText())
        self.assertGreaterEqual(f.run_hint.GetSize().height,f.run_hint.GetBestSize().height)
        f.sink.SetSelection(0);f._buttons()
        self.assertFalse(f.run.IsEnabled());self.assertFalse(f.toolbar_run.IsEnabled())
        self.assertIn('different source and sink',f.run_hint.GetToolTipText())
        f.sink.SetSelection(1);f._saved_source_current=False;f._buttons()
        self.assertFalse(f.toolbar_run.IsEnabled())
        self.assertIn('Reload saved board',f.toolbar_run.GetToolTipText())
        self.assertLessEqual(f.run_hint.GetBestSize().width,f.run_hint.wrap_width+1)
        self.assertGreaterEqual(f.run_hint.GetSize().height,f.run_hint.GetBestSize().height)
        f._saved_source_current=True;f._buttons();self.assertTrue(f.toolbar_run.IsEnabled())
        f._pin_peer_ids['source']=['B'];f.source_pins.SetValue(True);f._buttons()
        self.assertFalse(f.run.IsEnabled());self.assertIn('groups overlap',f.run.GetToolTipText())
        f.source_pins.SetValue(False);f._buttons();self.assertTrue(f.run.IsEnabled())

    def test_unsupported_3d_and_heating_combinations_explain_the_next_action(self):
        f=self.frame
        f.model_dimension.SetSelection(1);f.load_mode.SetSelection(1);f._buttons()
        self.assertFalse(f.run.IsEnabled());self.assertIn('specified sink current',f.run.GetToolTipText())
        f.load_mode.SetSelection(0);f.source_current_limit.ChangeValue('2');f._buttons()
        self.assertFalse(f.run.IsEnabled());self.assertIn('Clear these fields',f.run.GetToolTipText())
        f.source_current_limit.ChangeValue('');f._buttons();self.assertTrue(f.run.IsEnabled())
        f.joule_feedback.SetValue(True);f._buttons()
        self.assertFalse(f.run.IsEnabled());self.assertIn('2.5D specified-current',f.run.GetToolTipText())
        f.model_dimension.SetSelection(0);f._buttons()
        self.assertTrue(f.run.IsEnabled());self.assertIn('Materials + cooling',f.run.GetToolTipText())
        f._busy=True;f._buttons()
        self.assertFalse(f.run.IsEnabled());self.assertIn('Cancel stops',f.run.GetToolTipText())
        f._busy=False

    def test_copy_keyboard_shortcuts_use_sorted_rows_without_changing_selection(self):
        selected=[]
        table=InspectorTable(self.frame,[('Copper',120),('Loss',100)],selected.append)
        rows=[{'cells':('wide reference name',.1234567890123),'target':'A'},
              {'cells':('second',2.),'target':'B'}]
        table.set_rows(rows);table.Select(0)
        self.app.Yield();before=list(selected)
        from wayricad_runtime.layout import install_accessibility
        install_accessibility(self.frame);self.app.Yield()
        def key(code,shift=False):
            event=wx.KeyEvent(wx.EVT_KEY_DOWN.typeId);event.SetKeyCode(code)
            event.SetControlDown(True);event.SetShiftDown(shift)
            table.GetEventHandler().ProcessEvent(event)
        clipboard=Mock();clipboard.Open.return_value=True;clipboard.SetData.return_value=True
        with patch.object(wx,'TheClipboard',clipboard):
            key(ord('C'))
            self.assertEqual(clipboard.SetData.call_args.args[0].GetText(),'Copper\tLoss\nwide reference name\t0.1234567890123')
            key(ord('C'),True)
            self.assertIn('second\t2.0',clipboard.SetData.call_args.args[0].GetText())
            self.assertEqual(clipboard.Close.call_count,2)
            def inspect_menu(menu):
                items=menu.GetMenuItems()
                self.assertEqual(len(items),2)
                self.assertTrue(all(item.IsEnabled() for item in items))
                menu.ProcessEvent(wx.CommandEvent(wx.EVT_MENU.typeId,items[1].GetId()))
            with patch.object(table,'PopupMenu',side_effect=inspect_menu):
                table._menu(SimpleNamespace(GetPosition=lambda:wx.DefaultPosition))
            self.assertIn('second\t2.0',clipboard.SetData.call_args.args[0].GetText())
        with patch('wayricad_runtime.layout.read_table') as reader:
            key(wx.WXK_RETURN,True);reader.assert_called_once_with(table)
        self.assertEqual(selected,before)
        table._hover(SimpleNamespace(GetPosition=lambda:wx.Point(-10,-10),Skip=lambda:None))
        self.assertFalse(table.GetToolTipText())
        table.Destroy()


if __name__=='__main__':unittest.main()
