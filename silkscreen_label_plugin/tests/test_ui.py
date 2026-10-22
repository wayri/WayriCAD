"""Simple native flow and originating-board replacement guard."""
import unittest
from unittest.mock import patch
import test_placement as fixture
api=fixture.api
try:
    import wx
except ImportError:
    wx=None
@unittest.skipIf(wx is None or api is None,'Native KiCad wxPython required')
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        with patch.object(api.ActionPlugin,'register'):
            from silkscreen_label_plugin.ui import SilkscreenFrame
        self.fixture=fixture.PlacementTests();self.fixture.setUp()
        self.open=True
        self.frame=SilkscreenFrame(None,self.fixture.board,board_guard=lambda:self.open)
    def tearDown(self):self.frame.Destroy();wx.Yield()
    def test_review_expands_into_resizable_split_and_options_resize(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog
        self.frame.SetSize((1024,720));self.frame.Show();wx.Yield()
        self.frame.details.Expand();self.frame.toggle_details(None);wx.Yield()
        self.assertTrue(self.frame.review_splitter.IsSplit())
        split=self.frame.review_splitter;before=self.frame.list.GetSize()
        split.SetSashPosition(split.GetSashPosition()-40);wx.Yield()
        self.assertGreater(self.frame.list.GetSize().height,before.height)
        self.frame.details.Collapse();self.frame.toggle_details(None);wx.Yield()
        self.assertFalse(split.IsSplit())
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.SetSize((560,470));dialog.Show();wx.Yield()
            self.assertTrue(dialog.GetWindowStyle()&wx.RESIZE_BORDER)
            self.assertGreater(dialog.controls['testpoint_pattern'].GetSize().height,15)
        finally:dialog.Destroy();wx.Yield()

    def test_preview_apply_undo_redo(self):
        from silkscreen_label_plugin.placement import fingerprint
        before=fingerprint(self.fixture.board,api)
        self.frame.on_preview();wx.Yield();self.assertTrue(self.frame.apply_button.IsEnabled())
        with patch.object(api,'Refresh'):
            self.frame.on_apply();self.assertEqual(len(self.frame.transactions),1)
            self.frame.undo();self.assertEqual(fingerprint(self.fixture.board,api),before)
            self.frame.redo();self.assertEqual(len(self.frame.transactions),1)

    def test_preserved_reference_renders_native_glyphs_instead_of_only_a_box(self):
        from silkscreen_label_plugin import placement as m
        tx=m.apply(self.fixture.board,api,m.plan(self.fixture.board,api))
        preview=m.plan(self.fixture.board,api)
        self.assertFalse(preview.changes)
        self.frame.canvas.preview=preview
        bitmap=wx.Bitmap(900,650);dc=wx.MemoryDC(bitmap)
        try:self.frame.canvas.draw(dc,(900,650))
        finally:dc.SelectObject(wx.NullBitmap)
        self.assertTrue(any(polygons for polygons in self.frame.canvas._glyphs.values()))
        self.assertTrue(any(key[0]==m.item_id(self.fixture.text) for key in self.frame.canvas._glyphs))
        tx.undo()

    def test_references_only_overrides_custom_categories(self):
        self.frame.settings.update(references=False,values=True,board_text=True)
        settings=self.frame.current_settings()
        self.assertTrue(settings['references'])
        self.assertFalse(settings['values']);self.assertFalse(settings['board_text'])
        self.frame.text_scope.SetSelection(1)
        self.assertTrue(self.frame.current_settings()['board_text'])
        self.frame.SetSize((850,600));self.frame.Show();wx.Yield()
        self.assertLessEqual(self.frame.text_scope.GetRect().GetRight(),self.frame.text_scope.GetParent().GetClientSize().width)

    def test_partial_apply_retains_unresolved_review_and_red_originals(self):
        fp=api.FOOTPRINT(self.fixture.board);fp.SetReference('R99')
        fp.SetPosition(self.fixture.v(100,100));self.fixture.board.Add(fp)
        fp.Reference().SetLayer(api.F_SilkS);fp.Reference().SetVisible(True)
        fp.Reference().SetPosition(self.fixture.v(100,100))
        self.frame.on_preview()
        self.assertEqual(len(self.frame.preview.rejected),1)
        self.assertEqual(self.frame.preview.stats['placed'],1)
        reviewed=self.frame.preview
        with patch.object(api,'Refresh'):self.frame.on_apply()
        self.assertIsNone(self.frame.preview)
        self.assertIs(self.frame.canvas.preview,reviewed)
        self.assertIn('1 unresolved',self.frame.status.GetLabel())
        self.assertIn(str(fp.Reference().m_Uuid.AsString()),reviewed.unresolved_ids)
        self.assertFalse(self.frame.apply_button.IsEnabled())
    def test_replaced_origin_blocks_generated_object_audit_and_cleanup(self):
        self.open=False
        with patch.object(wx,'MessageBox') as warning:self.frame.on_generated_objects()
        self.assertIn('closed or replaced',warning.call_args.args[0])
        with self.assertRaisesRegex(ValueError,'closed or replaced'):
            self.frame.cleanup_verified_leaders(None,confirmed=True)

    def test_replaced_board_blocks_apply_and_preview(self):
        self.frame.on_preview();self.open=False
        with patch.object(wx,'MessageBox') as warning:self.frame.on_apply()
        self.assertIn('closed or replaced',warning.call_args.args[0])
        self.assertFalse(self.frame.transactions)
        self.frame.on_preview();self.assertIn('closed or replaced',self.frame.status.GetLabel())
    def test_reopening_preserves_existing_net_label_mode(self):
        from silkscreen_label_plugin.placement import plan,apply
        from silkscreen_label_plugin.ui import SilkscreenFrame
        case=self.fixture;case.fp.SetReference('TP1')
        net=api.NETINFO_ITEM(case.board,'SENSE');case.board.Add(net);case.pad.SetNet(net)
        apply(case.board,api,plan(case.board,api,dict(testpoint_net_names=True)))
        other=SilkscreenFrame(None,case.board)
        try:
            self.assertTrue(other.settings['testpoint_net_names'])
            self.assertEqual(other.settings['testpoint_pattern'],'TP1')
            review=plan(case.board,api,other.current_settings())
            self.assertTrue(all(c.annotation is None or not c.annotation.remove for c in review.changes))
            self.assertFalse(case.fp.Reference().IsVisible())
        finally:other.Destroy();wx.Yield()

    def test_angle_controls_accept_custom_values_and_scroll(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.Show();dialog.Layout();wx.Yield()
            dialog.other_angles.SetValue('17, 22.5')
            result=dialog.result()
            self.assertIn(45,result['allowed_rotations'])
            self.assertIn(17,result['allowed_rotations'])
            self.assertIn(22.5,result['allowed_rotations'])
            page=dialog.other_angles.GetParent()
            self.assertIsInstance(page,wx.ScrolledWindow)
            page.FitInside()
            self.assertGreaterEqual(page.GetVirtualSize().height,page.GetSizer().GetMinSize().height)
            dialog.other_angles.SetValue('nan')
            with self.assertRaisesRegex(ValueError,'finite'):dialog.result()
        finally:dialog.Destroy()

    def test_typography_options_roundtrip_and_validation(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog, PRESETS, RuleDialog
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            dialog.controls['auto_size'].SetValue(True)
            dialog.controls['testpoint_net_names'].SetValue(True)
            dialog.controls['testpoint_pattern'].SetValue('TP*')
            dialog.controls['edge_margin'].SetValue('0')
            dialog.controls['height'].SetValue('1.2');dialog.controls['min_height'].SetValue('0.8')
            dialog.horizontal.SetValue(False);dialog.vertical.SetValue(True);dialog.diagonal.SetValue(False);dialog.other_angles.SetValue('');dialog.direction.SetSelection(1)
            dialog.rules.append(dict(PRESETS[0]));result=dialog.result()
            self.assertTrue(result['testpoint_net_names']);self.assertEqual(result['testpoint_pattern'],'TP*')
            self.assertEqual(result['edge_margin'],0)
            dialog.controls['edge_margin'].SetValue('-1')
            with self.assertRaisesRegex(ValueError,'edge_margin'):dialog.result()
            dialog.controls['edge_margin'].SetValue('0.5')
            self.assertEqual(result['allowed_rotations'],(90,));self.assertEqual(result['reading_direction'],'Top/left')
            self.assertEqual(result['min_height'],.8);self.assertTrue(result['formatting_rules'][0]['knockout'])
            self.assertFalse(self.frame.settings['formatting_rules'])
            dialog.vertical.SetValue(False)
            with self.assertRaisesRegex(ValueError,'orientation'):dialog.result()
        finally:dialog.Destroy()
        editor=RuleDialog(self.frame,PRESETS[1])
        try:
            rule=editor.result();self.assertTrue(rule['bold']);self.assertNotIn('italic',rule)
            editor.controls['italic'].SetSelection(2);self.assertFalse(editor.result()['italic'])
        finally:editor.Destroy()

    def test_readability_and_local_repack_controls_roundtrip(self):
        from silkscreen_label_plugin.options_ui import OptionsDialog
        dialog=OptionsDialog(self.frame,self.frame.settings)
        try:
            self.assertTrue(dialog.controls['preserve_acceptable'].GetValue())
            self.assertFalse(dialog.controls['leaders'].GetValue())
            self.assertEqual(dialog.orientation.GetStringSelection(),'Footprint axis')
            for key,value in [('normal_distance','2.0'),('min_width','0.6'),('min_width_ratio','0.75'),('repack_neighbours','6'),('repack_displacement','2.0'),('leader_limit','10'),('leader_max_length','3.0')]:
                dialog.controls[key].SetValue(value)
            result=dialog.result()
            self.assertEqual(result['orientation_preference'],'Footprint axis')
            self.assertEqual(result['repack_neighbours'],6)
            self.assertEqual(result['leader_limit'],10)
            self.assertEqual(result['normal_distance'],2.0)
            dialog.controls['repack_neighbours'].SetValue('13')
            with self.assertRaisesRegex(ValueError,'0 to 12'):dialog.result()
            dialog.controls['repack_neighbours'].SetValue('6')
            dialog.controls['leader_limit'].SetValue('100001')
            with self.assertRaisesRegex(ValueError,'0 to 100000'):dialog.result()
        finally:dialog.Destroy()

    def test_three_scope_choices_map_to_planner_settings(self):
        self.frame.scope.SetSelection(0)
        self.assertFalse(self.frame.current_settings()['selected_only'])
        self.assertFalse(self.frame.current_settings()['problem_only'])
        self.frame.scope.SetSelection(1)
        self.assertFalse(self.frame.current_settings()['selected_only'])
        self.assertTrue(self.frame.current_settings()['problem_only'])
        self.frame.scope.SetSelection(2)
        self.assertTrue(self.frame.current_settings()['selected_only'])
        self.assertFalse(self.frame.current_settings()['problem_only'])

    def test_verified_leader_cleanup_is_reversible_and_retains_text(self):
        from silkscreen_label_plugin import lifecycle
        from silkscreen_label_plugin.placement import GUIDE_PREFIX, item_id
        group=api.PCB_GROUP(self.fixture.board);group.SetName(GUIDE_PREFIX+item_id(self.fixture.text))
        self.fixture.board.Add(group)
        leader=api.PCB_SHAPE(self.fixture.board);leader.SetShape(api.SHAPE_T_SEGMENT)
        leader.SetStart(self.fixture.v(20,18));leader.SetEnd(self.fixture.v(21,18))
        leader.SetWidth(api.FromMM(.08));leader.SetLayer(api.F_SilkS)
        self.fixture.board.Add(leader);group.AddItem(leader)
        self.fixture.board.SetProperties(lifecycle.generation_properties(
            self.fixture.board,api,[(self.fixture.fp,self.fixture.text,group)],{'leaders':True}))
        reviewed=lifecycle.audit(self.fixture.board,api)
        self.assertEqual(reviewed.as_dict()['cleanup_group_ids'],[item_id(group)])
        text_id=item_id(self.fixture.text)
        text_state=(self.fixture.text.GetText(),self.fixture.text.GetPosition().x,self.fixture.text.GetPosition().y,
                    self.fixture.text.GetTextSize().x,self.fixture.text.GetTextSize().y)
        original_fingerprint=reviewed.source_fingerprint
        self.frame.preview=object();self.frame.canvas.preview=self.frame.preview
        self.frame.cleanup_verified_leaders(reviewed,confirmed=True)
        self.assertEqual(len(self.fixture.board.Groups()),0)
        self.assertEqual(item_id(self.fixture.fp.Reference()),text_id)
        self.assertEqual((self.fixture.text.GetText(),self.fixture.text.GetPosition().x,self.fixture.text.GetPosition().y,
                          self.fixture.text.GetTextSize().x,self.fixture.text.GetTextSize().y),text_state)
        self.assertIsNone(self.frame.preview);self.assertIsNone(self.frame.canvas.preview)
        self.assertTrue(self.frame.undo_button.IsEnabled())
        self.frame.undo()
        self.assertEqual(len(self.fixture.board.Groups()),1)
        self.assertEqual(lifecycle.audit(self.fixture.board,api).source_fingerprint,original_fingerprint)
        self.frame.redo()
        self.assertEqual(len(self.fixture.board.Groups()),0)

    def test_stale_generated_audit_cannot_clean_up(self):
        from silkscreen_label_plugin import lifecycle
        from silkscreen_label_plugin.placement import GUIDE_PREFIX, item_id
        group=api.PCB_GROUP(self.fixture.board);group.SetName(GUIDE_PREFIX+item_id(self.fixture.text))
        self.fixture.board.Add(group)
        leader=api.PCB_SHAPE(self.fixture.board);leader.SetShape(api.SHAPE_T_SEGMENT)
        leader.SetStart(self.fixture.v(20,18));leader.SetEnd(self.fixture.v(21,18))
        leader.SetWidth(api.FromMM(.08));leader.SetLayer(api.F_SilkS)
        self.fixture.board.Add(leader);group.AddItem(leader)
        self.fixture.board.SetProperties(lifecycle.generation_properties(
            self.fixture.board,api,[(self.fixture.fp,self.fixture.text,group)],{'leaders':True}))
        reviewed=lifecycle.audit(self.fixture.board,api)
        self.fixture.text.SetText('Changed after audit')
        with self.assertRaisesRegex(ValueError,'Board changed after the audit'):
            self.frame.cleanup_verified_leaders(reviewed,confirmed=True)
        self.assertEqual(len(self.fixture.board.Groups()),1)

    def test_unverified_legacy_group_is_audited_but_not_removable(self):
        from silkscreen_label_plugin import lifecycle
        from silkscreen_label_plugin.placement import GUIDE_PREFIX
        legacy=api.PCB_GROUP(self.fixture.board);legacy.SetName(GUIDE_PREFIX+'legacy-name-only')
        self.fixture.board.Add(legacy)
        reviewed=lifecycle.audit(self.fixture.board,api)
        self.assertIn('legacy_unverified',[row['status'] for row in reviewed.findings])
        self.assertEqual(reviewed.as_dict()['cleanup_group_ids'],[])
        with self.assertRaisesRegex(ValueError,'no verified generated leaders'):
            self.frame.cleanup_verified_leaders(reviewed,confirmed=True)
        self.assertEqual(len(self.fixture.board.Groups()),1)
if __name__=='__main__':unittest.main()
