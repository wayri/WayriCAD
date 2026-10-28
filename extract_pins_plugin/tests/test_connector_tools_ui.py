"""Native connector workflows, reviewed copies and source-change guards."""
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native KiCad Python and wx are required')
class ConnectorToolsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=wx.GetApp() or wx.App(False)
        cls.registration=patch.object(pcbnew.ActionPlugin,'register',lambda self:None)
        cls.registration.start()

    @classmethod
    def tearDownClass(cls):
        cls.registration.stop()

    def setUp(self):
        from extract_pins_plugin.connector_tools_ui import ConnectorToolsPanel
        self.board=pcbnew.BOARD()
        self.footprint=pcbnew.FOOTPRINT(self.board);self.footprint.SetReference('J1');self.board.Add(self.footprint)
        for i in range(6):
            net=pcbnew.NETINFO_ITEM(self.board,'DATA_'+str(i+1));self.board.Add(net)
            pad=pcbnew.PAD(self.footprint);pad.SetNumber(str(i+1))
            pad.SetPosition(pcbnew.VECTOR2I((i%2)*2540000,(i//2)*2540000));pad.SetNet(net);self.footprint.Add(pad)
        self.frame=wx.Frame(None,size=(1100,780))
        self.panel=ConnectorToolsPanel(self.frame,self.board,['J1'])
        box=wx.BoxSizer(wx.VERTICAL);box.Add(self.panel,1,wx.EXPAND);self.frame.SetSizer(box)
        self.frame.Layout();self.app.Yield()

    def tearDown(self):
        self.frame.Destroy();self.app.Yield()

    def test_pair_edits_cross_select_and_stale_guard(self):
        p=self.panel;p.preview_pair()
        self.assertEqual(p.mate_table.GetNumberRows(),6)
        self.assertEqual(p.mate_table.GetCellValue(0,0),'1')
        self.assertEqual(p.mate_table.GetCellValue(0,2),'2')
        p.select_contact(1,'2');self.assertEqual(p.contact_preview.selected,('1','2'))
        p.mate_table.SetCellValue(0,1,'EDITED')
        with patch('extract_pins_plugin.connector_tools_ui.copy_text') as copy:
            p.copy_pair('a',True)
            self.assertEqual(copy.call_args.args[0].count('(global_label '),1)
            self.assertIn('EDITED',copy.call_args.args[0])
            p.a_prefix.SetValue('STALE_')
            with self.assertRaisesRegex(ValueError,'Preview'):p.copy_pair('a')
            self.assertEqual(copy.call_count,1)
        p.a_prefix.SetValue('');p.preview_pair()
        next(iter(self.footprint.Pads())).SetPosition(pcbnew.VECTOR2I(9000000,9000000))
        with self.assertRaisesRegex(ValueError,'Preview'):p.copy_pair('b')

    def test_paste_bulk_individual_and_invalid_edit_never_copies(self):
        p=self.panel;p.paste_text.SetValue('SCL\nSDA\nGND\n3V3')
        p.sequence.SetStringSelection('odd-even');p.preview_paste()
        self.assertEqual([p.paste_table.GetCellValue(i,0) for i in range(4)],['1','3','2','4'])
        p.paste_table.SelectRow(2);p.paste_kind.SetStringSelection('hierarchical')
        with patch('extract_pins_plugin.connector_tools_ui.copy_text') as copy:
            p.copy_paste(True);self.assertIn('(hierarchical_label "GND"',copy.call_args.args[0])
            self.assertEqual(copy.call_args.args[0].count('(uuid '),1)
            p.copy_paste(False);self.assertEqual(copy.call_args.args[0].count('(uuid '),4)
            p.paste_table.SetCellValue(1,1,'')
            with self.assertRaises(ValueError):p.copy_paste(False)
            self.assertEqual(copy.call_count,2)

    def test_physical_rows_columns_and_bottom_view_preserve_pin_ids(self):
        p=self.panel;p.preview_physical()
        top=p._physical_text
        self.assertEqual((p.physical_table.GetNumberRows(),p.physical_table.GetNumberCols()),(3,2))
        p.phys_side.SetStringSelection('bottom')
        with self.assertRaisesRegex(ValueError,'Preview'):p.copy_physical()
        p.preview_physical();self.assertNotEqual(p._physical_text,top)
        for i in range(1,7):self.assertIn(str(i)+' · DATA_'+str(i),p._physical_text)
        p.phys_order.SetStringSelection('columns');p.preview_physical()
        self.assertEqual((p.physical_table.GetNumberRows(),p.physical_table.GetNumberCols()),(2,3))

    def test_pasted_assignment_uses_exact_pins_and_is_atomic(self):
        p=self.panel;p.preview_pair()
        p.paste_text.SetValue('1,CLK\n3,SDA');p.preview_paste();p.assign_pasted_names()
        self.assertEqual(p.mate_table.GetCellValue(0,1),'CLK')
        self.assertEqual(p.mate_table.GetCellValue(0,3),'CLK')
        self.assertEqual(p.mate_table.GetCellValue(2,1),'SDA')
        before=[[p.mate_table.GetCellValue(i,j) for j in range(6)] for i in range(6)]
        p.paste_text.SetValue('1,NEW\n99,UNKNOWN');p.preview_paste()
        with self.assertRaisesRegex(ValueError,'not in'):p.assign_pasted_names()
        self.assertEqual(before,[[p.mate_table.GetCellValue(i,j) for j in range(6)] for i in range(6)])

    def test_main_pin_extractor_exposes_the_connector_tools_page(self):
        from extract_pins_plugin.plugin_dialog_v2 import PluginDialogV2
        with patch.object(pcbnew,'GetBoard',return_value=self.board):
            frame=PluginDialogV2(None,[self.footprint])
        try:
            names=[frame.notebook.GetPageText(i) for i in range(frame.notebook.GetPageCount())]
            self.assertIn('Connector tools',names)
            frame.connector_tools.preview_pair()
            self.assertEqual(frame.connector_tools.mate_table.GetNumberRows(),6)
        finally:
            frame.Close();self.app.Yield()


if __name__=='__main__':unittest.main()
