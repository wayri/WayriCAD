"""Native test-point net annotations preserve schematic/reference identity."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
try:
    import pcbnew as api
except ImportError:
    api=None

from silkscreen_label_plugin import placement as core


@unittest.skipIf(api is None,'Native KiCad bindings required')
class NetAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.board=api.BOARD()
        self.v=lambda x,y:api.VECTOR2I(api.FromMM(x),api.FromMM(y))
        corners=[(0,0),(100,0),(100,60),(0,60)]
        for a,b in zip(corners,corners[1:]+corners[:1]):
            edge=api.PCB_SHAPE(self.board);edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetLayer(api.Edge_Cuts);edge.SetStart(self.v(*a));edge.SetEnd(self.v(*b));self.board.Add(edge)
        self.fp=api.FOOTPRINT(self.board);self.fp.SetReference('TP1');self.fp.SetValue('TestPoint')
        self.fp.SetPosition(self.v(30,30));self.board.Add(self.fp)
        self.reference=self.fp.Reference();self.reference.SetPosition(self.v(30,30))
        self.reference.SetLayer(api.F_SilkS);self.reference.SetTextSize(self.v(1,1));self.reference.SetTextThickness(api.FromMM(.15))
        self.fp.Value().SetVisible(False)
        self.pad=api.PAD(self.fp);self.pad.SetPosition(self.v(30,30));self.pad.SetSize(self.v(1,1))
        self.pad.SetAttribute(api.PAD_ATTRIB_SMD);self.pad.SetLayerSet(self.pad.SMDMask());self.fp.Add(self.pad)
        self.net('/Power/3V3_TEST')
        court=api.PCB_SHAPE(self.fp);court.SetShape(api.SHAPE_T_RECT)
        court.SetStart(self.v(27,27));court.SetEnd(self.v(33,33));court.SetLayer(api.F_CrtYd);self.fp.Add(court)

    def net(self,name,pad=None):
        net=api.NETINFO_ITEM(self.board,name);self.board.Add(net);(pad or self.pad).SetNet(net)

    def plan(self,**settings):
        options=dict(testpoint_net_names=True,leaders=False)
        options.update(settings)
        return core.plan(self.board,api,options)

    def owned(self):
        return [group for group in self.board.Groups() if group.GetName().startswith(core.NET_PREFIX)]

    def test_multiple_owned_labels_restore_exactly_after_disable_undo(self):
        fp=api.FOOTPRINT(self.board);fp.SetReference('TP2');fp.SetValue('TestPoint')
        fp.SetPosition(self.v(70,30));self.board.Add(fp);fp.Value().SetVisible(False)
        reference=fp.Reference();reference.SetLayer(api.F_SilkS);reference.SetPosition(self.v(70,30))
        reference.SetTextSize(self.v(1,1));reference.SetTextThickness(api.FromMM(.15))
        pad=api.PAD(fp);pad.SetPosition(self.v(70,30));pad.SetSize(self.v(1,1))
        pad.SetAttribute(api.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask());fp.Add(pad)
        self.net('SECOND_NET',pad)
        review=self.plan(leaders=True,leader_distance=1);self.assertEqual(len(review.changes),2)
        core.apply(self.board,api,review);before=core.fingerprint(self.board,api)
        restore=self.plan(testpoint_net_names=False,leaders=True,leader_distance=1)
        tx=core.apply(self.board,api,restore)
        tx.undo();self.assertEqual(core.fingerprint(self.board,api),before)
        tx.redo();tx.undo();self.assertEqual(core.fingerprint(self.board,api),before)
        text=next(iter(self.owned()[0].GetItems()));text.SetText('CHANGED')
        self.assertNotEqual(core.fingerprint(self.board,api),before)

    def test_create_keeps_identity_and_is_reversible_idempotent(self):
        before=core.fingerprint(self.board,api)
        identity=(self.fp.GetReference(),self.fp.GetValue(),core.item_id(self.reference),core.item_id(self.fp))
        preview=self.plan()
        self.assertEqual(core.fingerprint(self.board,api),before)
        self.assertEqual(len(preview.changes),1,preview.rejected)
        change=preview.changes[0]
        self.assertEqual(change.preview_item.GetText(),'/Power/3V3_TEST')
        self.assertEqual(change.label,'TP1 / /Power/3V3_TEST')
        self.assertEqual(change.suppressed_reference_id,core.item_id(self.reference))
        self.assertNotEqual(core.item_id(change.item),core.item_id(self.reference))
        tx=core.apply(self.board,api,preview)
        self.assertFalse(self.reference.IsVisible())
        self.assertEqual((self.fp.GetReference(),self.fp.GetValue(),core.item_id(self.reference),core.item_id(self.fp)),identity)
        self.assertEqual(len(self.owned()),1)
        self.assertEqual(list(self.owned()[0].GetItems())[0].GetText(),'/Power/3V3_TEST')
        self.assertFalse(self.plan().changes)
        tx.undo();self.assertEqual(core.fingerprint(self.board,api),before)
        tx.redo();self.assertEqual(len(self.owned()),1)

    def test_net_update_and_disable_restore_reference_with_undo_redo(self):
        core.apply(self.board,api,self.plan())
        annotation=list(self.owned()[0].GetItems())[0]
        self.net('/Power/VOLTAGE_SENSE_WITH_A_FULL_HIERARCHICAL_NAME')
        preview=self.plan();self.assertEqual(annotation.GetText(),'/Power/3V3_TEST')
        tx=core.apply(self.board,api,preview)
        self.assertEqual(annotation.GetText(),self.pad.GetNetname())
        tx.undo();self.assertEqual(annotation.GetText(),'/Power/3V3_TEST')
        tx.redo()
        before_disable=core.fingerprint(self.board,api)
        restore=self.plan(testpoint_net_names=False,references=False,testpoint_pattern='')
        self.assertEqual(len(restore.changes),1)
        cleanup=core.apply(self.board,api,restore)
        self.assertTrue(self.reference.IsVisible())
        self.assertEqual(self.fp.GetReference(),'TP1')
        self.assertFalse(self.owned())
        self.assertFalse(list(self.board.GetDrawings())[4:] if len(list(self.board.GetDrawings()))>4 else [])
        cleanup.undo();self.assertEqual(core.fingerprint(self.board,api),before_disable)
        cleanup.redo();self.assertTrue(self.reference.IsVisible());self.assertFalse(self.owned())

    def test_ambiguous_or_missing_net_is_unchanged_with_reason(self):
        second=api.PAD(self.fp);second.SetNumber('2');second.SetPosition(self.v(31,30))
        second.SetSize(self.v(1,1));second.SetAttribute(api.PAD_ATTRIB_SMD);second.SetLayerSet(second.SMDMask());self.fp.Add(second)
        self.net('OTHER',second)
        before=core.fingerprint(self.board,api)
        preview=self.plan();self.assertFalse(preview.changes)
        self.assertTrue(any('Ambiguous' in reason for _,reason in preview.skipped))
        self.assertEqual(core.fingerprint(self.board,api),before)
        self.pad.SetNetCode(0);second.SetNetCode(0)
        preview=self.plan();self.assertFalse(preview.changes)
        self.assertTrue(any('No connected' in reason for _,reason in preview.skipped))

    def test_hidden_locked_and_unselected_references_stay_unchanged(self):
        self.reference.SetVisible(False)
        self.assertFalse(self.plan().changes)
        self.reference.SetVisible(True);self.reference.SetLocked(True)
        self.assertFalse(self.plan().changes)
        self.reference.SetLocked(False)
        self.assertFalse(self.plan(selected_only=True).changes)
        self.reference.SetSelected()
        self.assertTrue(self.plan(selected_only=True).changes)

    def test_save_load_ownership_and_pattern_change_restore(self):
        core.apply(self.board,api,self.plan())
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';api.SaveBoard(str(source),self.board)
            loaded=api.LoadBoard(str(source))
        before=core.fingerprint(loaded,api)
        self.assertFalse(core.plan(loaded,api,dict(testpoint_net_names=True,leaders=False)).changes)
        preview=core.plan(loaded,api,dict(testpoint_net_names=True,testpoint_pattern='OTHER*',leaders=False))
        self.assertTrue(preview.changes)
        tx=core.apply(loaded,api,preview)
        self.assertTrue(next(iter(loaded.GetFootprints())).Reference().IsVisible())
        tx.undo();self.assertEqual(core.fingerprint(loaded,api),before)

    def test_partial_annotation_add_failure_restores_everything(self):
        preview=self.plan();before=core.fingerprint(self.board,api)
        original=self.board.Add
        annotation=preview.changes[0].item
        def add(item):
            original(item)
            if item==annotation:raise RuntimeError('after annotation add')
        with patch.object(self.board,'Add',side_effect=add):
            with self.assertRaisesRegex(RuntimeError,'after annotation add'):
                core.apply(self.board,api,preview)
        self.assertEqual(core.fingerprint(self.board,api),before)
        self.assertTrue(self.reference.IsVisible());self.assertFalse(self.owned())

    def test_partial_visibility_failure_and_disable_removal_failure_restore(self):
        preview=self.plan();before=core.fingerprint(self.board,api)
        reference=preview.changes[0].annotation.reference
        original=reference.SetVisible
        def hide(value):
            original(value)
            if not value:raise RuntimeError('after reference hide')
        with patch.object(reference,'SetVisible',side_effect=hide):
            with self.assertRaisesRegex(RuntimeError,'after reference hide'):
                core.apply(self.board,api,preview)
        self.assertEqual(core.fingerprint(self.board,api),before)

        core.apply(self.board,api,self.plan())
        restore=self.plan(testpoint_net_names=False)
        before=core.fingerprint(self.board,api);original_remove=self.board.Remove
        def remove(item):
            original_remove(item)
            if isinstance(item,api.PCB_TEXT):raise RuntimeError('after annotation removal')
        with patch.object(self.board,'Remove',side_effect=remove):
            with self.assertRaisesRegex(RuntimeError,'after annotation removal'):
                core.apply(self.board,api,restore)
        self.assertEqual(core.fingerprint(self.board,api),before)

    def test_text_variables_are_not_silently_expanded(self):
        self.net('/Path/${REFERENCE}/SENSE')
        before=core.fingerprint(self.board,api)
        preview=self.plan()
        self.assertFalse(preview.changes)
        self.assertTrue(any('displayed literally' in reason for _,reason in preview.skipped))
        self.assertEqual(core.fingerprint(self.board,api),before)

    def test_guides_and_annotation_groups_are_independent_and_reversible(self):
        before=core.fingerprint(self.board,api)
        preview=self.plan(leaders=True,leader_distance=.1,body_clearance=.2)
        self.assertEqual(len(preview.changes),1,preview.rejected)
        self.assertTrue(preview.changes[0].leader)
        tx=core.apply(self.board,api,preview)
        self.assertEqual(len(self.owned()),1)
        self.assertEqual(len([group for group in self.board.Groups() if group.GetName().startswith(core.GUIDE_PREFIX)]),1)
        self.assertFalse(self.plan(leaders=True,leader_distance=.1,body_clearance=.2).changes)
        tx.undo();self.assertEqual(core.fingerprint(self.board,api),before)
        tx.redo()
        restore=self.plan(testpoint_net_names=False,leaders=True,leader_distance=.1,body_clearance=.2)
        applied=core.fingerprint(self.board,api)
        cleanup=core.apply(self.board,api,restore)
        self.assertFalse(self.owned());self.assertTrue(self.reference.IsVisible())
        cleanup.undo();self.assertEqual(core.fingerprint(self.board,api),applied)

    def test_membership_failure_after_mutation_rolls_back(self):
        preview=self.plan();action=preview.changes[0].annotation
        before=core.fingerprint(self.board,api);original=action.group.AddItem
        def add(item):
            original(item)
            raise RuntimeError('after group membership')
        with patch.object(action.group,'AddItem',side_effect=add):
            with self.assertRaisesRegex(RuntimeError,'after group membership'):
                core.apply(self.board,api,preview)
        self.assertEqual(core.fingerprint(self.board,api),before)

    def test_update_text_and_undo_visibility_failures_restore_applied_state(self):
        initial=self.plan();tx=core.apply(self.board,api,initial)
        action=initial.changes[0].annotation;applied=core.fingerprint(self.board,api)
        original_visibility=action.reference.SetVisible
        def show(value):
            original_visibility(value)
            if value:raise RuntimeError('after undo visibility')
        with patch.object(action.reference,'SetVisible',side_effect=show):
            with self.assertRaisesRegex(RuntimeError,'after undo visibility'):tx.undo()
        self.assertEqual(core.fingerprint(self.board,api),applied)
        tx.undo();tx.redo()
        self.net('UPDATED_NET')
        update=self.plan();action=update.changes[0].annotation
        before=core.fingerprint(self.board,api);original_text=action.text.SetText
        def rename(value):
            original_text(value)
            if value=='UPDATED_NET':raise RuntimeError('after annotation text')
        with patch.object(action.text,'SetText',side_effect=rename):
            with self.assertRaisesRegex(RuntimeError,'after annotation text'):
                core.apply(self.board,api,update)
        self.assertEqual(core.fingerprint(self.board,api),before)

    def test_existing_annotation_hidden_or_locked_and_scope_are_respected(self):
        core.apply(self.board,api,self.plan())
        annotation=list(self.owned()[0].GetItems())[0]
        self.net('CHANGED')
        annotation.SetVisible(False)
        before=core.fingerprint(self.board,api)
        self.assertFalse(self.plan().changes)
        self.assertEqual(core.fingerprint(self.board,api),before)
        annotation.SetVisible(True);self.owned()[0].SetLocked(True)
        self.assertFalse(self.plan().changes)
        self.assertFalse(self.plan(testpoint_net_names=False).changes)
        self.owned()[0].SetLocked(False)
        self.assertFalse(self.plan(selected_only=True).changes)
        self.fp.SetSelected()
        self.assertTrue(self.plan(selected_only=True).changes)

    def test_invalid_ownership_and_stale_net_never_mutate_design(self):
        preview=self.plan()
        self.net('LATER_NET')
        before=core.fingerprint(self.board,api)
        with self.assertRaisesRegex(ValueError,'Board changed'):
            core.apply(self.board,api,preview)
        self.assertEqual(core.fingerprint(self.board,api),before)
        core.apply(self.board,api,self.plan())
        group=self.owned()[0]
        extra=api.PCB_TEXT(self.board);extra.SetText('User owned extra');self.board.Add(extra);group.AddItem(extra)
        before=core.fingerprint(self.board,api)
        with self.assertRaisesRegex(ValueError,'ownership is invalid'):self.plan()
        self.assertEqual(core.fingerprint(self.board,api),before)

    def test_bottom_net_annotation_preserves_mirroring_and_roundtrips(self):
        self.fp.Flip(self.fp.GetPosition(), False)
        self.assertEqual(self.reference.GetLayer(), api.B_SilkS)
        self.assertTrue(self.reference.IsMirrored())
        before=core.fingerprint(self.board,api)
        preview=self.plan(leaders=True)
        self.assertEqual(len(preview.changes),1,preview.rejected)
        change=preview.changes[0]
        self.assertEqual(change.preview_item.GetLayer(),api.B_SilkS)
        self.assertTrue(change.preview_item.IsMirrored())
        self.assertEqual(change.preview_item.GetText(),self.pad.GetNetname())
        tx=core.apply(self.board,api,preview)
        annotation=list(self.owned()[0].GetItems())[0]
        self.assertEqual(annotation.GetLayer(),api.B_SilkS)
        self.assertTrue(annotation.IsMirrored())
        self.assertFalse(self.reference.IsVisible())
        self.assertFalse(self.plan(leaders=True).changes)
        tx.undo();self.assertEqual(core.fingerprint(self.board,api),before)
        tx.redo()
        restore=core.apply(self.board,api,self.plan(testpoint_net_names=False))
        self.assertTrue(self.reference.IsVisible())
        self.assertEqual(self.reference.GetLayer(),api.B_SilkS)
        self.assertTrue(self.reference.IsMirrored())
        restore.undo();restore.redo()

    def test_multiple_pads_on_same_net_and_unconnected_pads_are_unambiguous(self):
        for number in ('2','3'):
            pad=api.PAD(self.fp);pad.SetNumber(number);pad.SetPosition(self.v(31,30))
            pad.SetSize(self.v(.5,.5));pad.SetAttribute(api.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask());self.fp.Add(pad)
            if number=='2':pad.SetNet(self.pad.GetNet())
        preview=self.plan()
        self.assertTrue(preview.changes,preview.skipped)
        self.assertEqual(preview.changes[0].preview_item.GetText(),self.pad.GetNetname())


if __name__=='__main__':unittest.main()
