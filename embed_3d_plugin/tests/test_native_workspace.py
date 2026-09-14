"""Opt-in real wx tests for the new window, distinct from KiCad-host acceptance.

WAYRICAD_EMBED3D_NATIVE_TESTS=1 plus real wxPython and an active desktop are required.
The bridge here does not emulate native PCB IO: these tests only exercise wx UI.
"""
from pathlib import Path
import importlib.util
import os
import unittest
AVAILABLE=importlib.util.find_spec('wx') is not None and os.environ.get('WAYRICAD_EMBED3D_NATIVE_TESTS')=='1'

class EmptyBridge:
    board=None
    def project_path(self):return Path.home()

@unittest.skipUnless(AVAILABLE,'Real wx display unavailable/not enabled')
class NativeWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx=wx;cls.app=wx.GetApp() or wx.App(False)
    def setUp(self):
        from embed_3d_plugin.workspace_ui import WorkspaceDialog
        self.window=WorkspaceDialog(None,EmptyBridge(),auto_scan=False)
    def tearDown(self):self.window.Destroy();self.app.Yield()
    def test_window_construction_and_title(self):self.assertIn('WayriCAD Embed3D',self.window.GetTitle())
    def test_all_primary_actions_exist(self):
        self.assertEqual(self.window.operation.GetCount(),5)
        self.assertIs(self.window.preview_button.GetParent(),self.window.apply_button.GetParent())
    def test_empty_window_disables_apply(self):self.assertFalse(self.window.apply_button.IsEnabled())
    def test_native_matrix_toggle_updates_global_state(self):
        from embed_3d_plugin.workspace import Component,Inventory
        row=Component('one','R1','1k',board_uuid='one',models=[{}])
        self.window.inventory=Inventory(None,None,[row],{},[]);self.window.valid=True
        self.window.filter_rows();self.window.refresh_controls()
        self.assertTrue(self.window.model.SetValueByRow(True,0,4))
        self.assertEqual(self.window.inventory.state('models'),'all')
    def test_filter_does_not_clear_checked_assets(self):
        from embed_3d_plugin.workspace import Component,Inventory
        rows=[Component('a','R1','1k',board_uuid='a'),Component('b','R2','2k',board_uuid='b')]
        inv=Inventory(None,None,rows,{},[]);inv.select_all()
        self.window.inventory=inv;self.window.valid=True;self.window.filter_rows()
        self.window.search.SetValue('R1');self.app.Yield()
        self.assertEqual(len(self.window.model.rows),1);self.assertEqual(len(inv.selection().footprints),2)
