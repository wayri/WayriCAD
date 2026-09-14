"""Controller-model contract tests with a minimal wx stand-in, NOT GUI rendering."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from embed_3d_plugin.workspace import Component, Inventory
ROOT=Path(__file__).resolve().parents[1]

class FakeIndexModel:
    def __init__(self,count=0):self.count=count
    def Reset(self,count):self.count=count
    def GetRow(self,item):return item.row
class Item:
    def __init__(self,row):self.row=row
    def IsOk(self):return self.row>=0

def isolated_module():
    wx=types.ModuleType('wx');dv=types.ModuleType('wx.dataview');wx.Dialog=type('Dialog',(),{})
    dv.DataViewIndexListModel=FakeIndexModel;wx.dataview=dv
    name='embed_3d_plugin._workspace_ui_test'
    spec=importlib.util.spec_from_file_location(name,ROOT/'workspace_ui.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'wx':wx,'wx.dataview':dv,name:module}):spec.loader.exec_module(module)
    return module

class MatrixContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.mod=isolated_module()
    def setUp(self):
        self.called=0
        def changed():self.called+=1
        self.model=self.mod.ComponentModel(changed)
        self.a=Component('a','R10','10k',board_uuid='a',models=[{}],symbol_instances=[('main','one')])
        self.b=Component('b','R2','2k',board_uuid='b')
        self.model.replace([self.a,self.b])
    def test_all_three_checkbox_columns_present(self):self.assertEqual(set(self.mod.KIND_COLUMNS.values()),{'symbols','footprints','models'})
    def test_toggle_one_asset_only(self):
        self.assertTrue(self.model.SetValueByRow(True,0,2));self.assertTrue(self.a.checked['symbols'])
        self.assertFalse(self.a.checked['models']);self.assertFalse(self.b.checked['symbols']);self.assertEqual(self.called,1)
    def test_absent_asset_not_editable(self):
        self.assertFalse(self.model.HasValue(Item(1),2));self.assertFalse(self.model.IsEnabled(Item(1),2))
        self.assertFalse(self.model.SetValueByRow(True,1,2));self.assertEqual(self.called,0)
    def test_busy_prevents_editing(self):
        self.model.locked=True;self.assertFalse(self.model.SetValueByRow(True,0,3))
    def test_filter_uses_same_objects_keeps_hidden_checks(self):
        self.a.checked['models']=True;self.model.replace([self.b]);self.assertTrue(self.a.checked['models'])
        self.model.replace([self.a,self.b]);self.assertTrue(self.model.GetValueByRow(0,4))
    def test_numeric_reference_sort(self):self.assertGreater(self.model.Compare(Item(0),Item(1),0,True),0)
    def test_buttons_include_separate_and_combined_actions(self):
        self.assertEqual(set(self.mod.ACTION_LABELS.values()),{'Embed checked','Embed all','Unbundle','Relink','Unbundle & relink'})
    def test_plugin_opens_new_workspace_not_old_model_dialog(self):
        text=(ROOT/'plugin.py').read_text();tree=ast.parse(text)
        imports=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertTrue(any(n.module=='workspace_ui' for n in imports));self.assertNotIn('dialog = EmbedDialog',text)
    def test_ui_avoids_whole_window_fit_and_hardcoded_colours(self):
        text=(ROOT/'workspace_ui.py').read_text()
        self.assertNotIn('SetForegroundColour',text);self.assertNotIn('self.Fit()',text)
        self.assertIn('wx.ScrolledWindow',text)
