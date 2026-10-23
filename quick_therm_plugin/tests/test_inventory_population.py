"""Bulk saved inventory updates preserve inputs and always restore native redraw."""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_therm_plugin.ui import QuickThermFrame
    from quick_therm_plugin.service import execute
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native KiCad wxPython is required')
class InventoryPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=wx.GetApp() or wx.App(False)
        cls.board=Path(__file__).resolve().parents[1]/'examples/thermal-demo.kicad_pcb'
        cls.original=hashlib.sha256(cls.board.read_bytes()).hexdigest()
        cls.inventory=execute({'action':'inspect','board_path':str(cls.board)})

    def setUp(self):
        with patch.object(QuickThermFrame,'_inspect'):
            self.frame=QuickThermFrame(None,self.board)
        self.frame._job=lambda request,finished,message:finished(self.inventory)

    def tearDown(self):
        self.frame.Destroy()
        self.app.ProcessPendingEvents()
        self.assertEqual(hashlib.sha256(self.board.read_bytes()).hexdigest(),self.original)

    def test_batched_reload_keeps_field_mappings_selection_and_manual_inputs(self):
        self.frame._inspect()
        references=self.inventory['component_references']
        self.assertEqual(self.frame.therm_refs.GetStrings(),references)
        self.assertEqual(self.frame.therm_inputs.table.references,references)
        self.assertFalse(self.frame.main_panel.IsFrozen())
        self.frame.therm_refs.Check(0,True)
        ref=references[0]
        self.frame.manual_values={ref:{'power_w':0.75}}
        mapping=self.frame._thermal_field_map()
        self.frame._inspect()
        self.assertEqual(self.frame._thermal_field_map(),mapping)
        self.assertTrue(self.frame.therm_refs.IsChecked(0))
        self.assertEqual(self.frame.manual_values,{ref:{'power_w':0.75}})
        self.assertFalse(self.frame.main_panel.IsFrozen())

    def test_native_redraw_is_restored_when_inventory_application_fails(self):
        with patch.object(self.frame.therm_inputs,'load',side_effect=ValueError('Invalid inventory')):
            with self.assertRaisesRegex(ValueError,'Invalid inventory'):
                self.frame._inspect()
        self.assertFalse(self.frame.main_panel.IsFrozen())


if __name__=='__main__':unittest.main()
