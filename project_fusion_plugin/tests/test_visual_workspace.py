"""Native wx gesture, placement undo, sheet geometry and stale-review tests."""
import importlib,os,sys,tempfile,unittest
from pathlib import Path
from types import ModuleType,SimpleNamespace
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
pkg=ModuleType('_fusion_visual');pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
try:
    import wx
except ImportError:wx=None

@unittest.skipIf(wx is None,'Native wxPython required')
class VisualWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=wx.GetApp() or wx.App(False)
        cls.gui=importlib.import_module(pkg.__name__+'.gui')
        cls.pv=importlib.import_module(pkg.__name__+'.preview')
    def setUp(self):self.dialog=self.gui.FusionDialog()
    def tearDown(self):self.dialog.Destroy()
    def test_real_geometry_moves_rigidly_and_undo_invalidates_plan(self):
        d=self.dialog
        d.append_source('C:/Example/module.kicad_pro','MODULE',variant='<Default>',variant_choices=['<Default>'])
        d.preview.boxes=[('MODULE',10,20,30,40)]
        p=self.pv.Primitive('MODULE','F.Cu','line',((11,21),(15,24)),.2)
        d.preview.primitives=[p];d.import_plan={'old':'review'}
        d.preview.translate('MODULE',3,-2);d.move_preview_source('MODULE',13,18,(3,-2))
        self.assertEqual(d.preview.primitives[0].points,((14,19),(18,22)))
        self.assertIsNone(d.import_plan);self.assertEqual(float(d.grid.GetCellValue(0,3)),13)
        d.undo_placement(None)
        self.assertEqual(d.preview.primitives[0],p);self.assertEqual(d.grid.GetCellValue(0,3),'')
    def test_sheet_move_persists_and_undo(self):
        d=self.dialog;d.append_source('C:/Example/module.kicad_pro','MODULE',variant='<Default>',variant_choices=['<Default>'])
        d.move_sheet_source('MODULE',50,70,(5,7))
        self.assertEqual(d.options().sources[0].sheet_position_mm,[50,70])
        d.undo_placement(None);self.assertEqual(d.options().sources[0].sheet_position_mm,[])
    def test_existing_target_cannot_be_dragged(self):
        d=self.dialog;v=d.preview;v.boxes=[('Target',0,0,20,20)];v.locked_aliases={'Target'}
        v.scale=10;v.center=(10,10)
        event=SimpleNamespace(GetPosition=lambda:wx.Point(v.GetClientSize().width//2,v.GetClientSize().height//2),ShiftDown=lambda:False)
        with mock.patch.object(v,'CaptureMouse'):
            v._down(event)
        self.assertIsNone(v._move_alias)
    def test_generated_sheet_preview_preserves_saved_root_position(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'root.kicad_sch'
            path.write_text('(kicad_sch (sheet (at 45 63) (size 30 20) (property "Sheetname" "MODULE") (pin "EN" input (at 45 70 180))))')
            self.dialog.sheet_preview.show_schematic(path,{'MODULE'})
            self.assertEqual(self.dialog.sheet_preview.boxes,[('MODULE',45,63,75,83)])
            self.assertEqual(len(self.dialog.sheet_preview.primitives),2)

    def test_schematic_only_scan_does_not_require_a_pcb(self):
        model=importlib.import_module(pkg.__name__+'.model')
        with mock.patch.object(wx,'CallAfter',side_effect=lambda callback,*args:callback(*args)):
            self.dialog.scan_worker_issues([model.SourceSpec('C:/Example/sheet.kicad_sch','Sheet')],False)
        self.assertEqual(self.dialog.merge_issues,[])

    def test_native_validation_failure_is_visible_without_overwriting_repairs(self):
        d=self.dialog;d.show_validation_failure('Extra PCB pad on Q3')
        self.assertEqual(d.review_inspector.GetSelection(),3)
        self.assertIn('Extra PCB pad',d.issue_list.GetItemText(0,1))
        existing=list(d.merge_issues);d.show_validation_failure('Second report')
        self.assertEqual(d.merge_issues,existing)
        d.clear_results();self.assertEqual(d.merge_issues,[]);self.assertEqual(d.issue_list.GetItemCount(),0)

    def test_preflight_failures_are_inline_and_non_mutating(self):
        model=importlib.import_module(pkg.__name__+'.model')
        issues=importlib.import_module(pkg.__name__+'.merge_issues')
        spec=model.SourceSpec('C:/Example/missing.kicad_pro','Missing')
        with mock.patch.object(issues,'scan_source',side_effect=model.MergeError('Missing child schematic')),mock.patch.object(wx,'CallAfter',side_effect=lambda callback,*args:callback(*args)):
            with self.assertRaisesRegex(model.MergeError,'Merge issues panel'):self.dialog.scan_worker_issues([spec])
        self.assertEqual(self.dialog.issue_list.GetItemCount(),1)
        self.assertIsNone(self.dialog.merge_issues[0][2]['action'])

    def test_each_issue_has_a_reviewed_choice_and_only_advisories_can_be_ignored(self):
        model=importlib.import_module(pkg.__name__+'.model')
        spec=model.SourceSpec('C:/Example/module.kicad_pro','MODULE')
        blocked={'id':'MODULE:pcb:1','reference':'J1','error':'Reference differs',
                 'action':'restore_schematic_reference','suggested_reference':'J2',
                 'severity':'blocking','ignore_allowed':False}
        advisory={'id':'MODULE:pcb:2','reference':'TP1','error':'Board-only copper',
                  'action':'keep_board_only','severity':'warning','ignore_allowed':True}
        self.dialog.show_merge_issues([(spec,{'issues':[blocked,advisory]})])
        self.assertEqual(self.dialog.issue_list.GetItemCount(),2)
        self.assertEqual(self.dialog.issue_choices[blocked['id']],blocked['action'])
        self.dialog.show_issue_choices(0)
        self.assertNotIn('ignore',self.dialog._issue_option_actions)
        self.dialog.issue_list.Select(1)
        self.dialog.show_issue_choices(1)
        self.assertIn('ignore',self.dialog._issue_option_actions)
        self.dialog.issue_choice.SetSelection(self.dialog._issue_option_actions.index('ignore'))
        self.dialog.choose_issue_resolution(None)
        self.assertEqual(self.dialog.issue_choices[advisory['id']],'ignore')
        self.assertEqual(self.dialog.issue_list.GetItemText(1,2),'Ignore advisory')

    def test_auto_fix_requires_every_blocking_issue_to_have_a_safe_decision(self):
        model=importlib.import_module(pkg.__name__+'.model')
        spec=model.SourceSpec('C:/Example/module.kicad_pro','MODULE')
        blocked={'id':'MODULE:pcb:1','reference':'J1','error':'Ambiguous PCB owner',
                 'action':None,'severity':'blocking','ignore_allowed':False}
        self.dialog.show_merge_issues([(spec,{'issues':[blocked]})])
        with mock.patch.object(wx,'MessageBox') as confirm:
            self.dialog.auto_fix_issues(None)
        confirm.assert_not_called()
        self.assertIn('Ambiguous PCB owner',self.dialog.status.GetLabel())
