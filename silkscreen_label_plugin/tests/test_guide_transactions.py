"""Native fault injection for atomic managed-guide replacement and undo."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch
import test_placement as fixture
from silkscreen_label_plugin import placement as m
from silkscreen_label_plugin import lifecycle

p=fixture.api


@unittest.skipIf(p is None,'Native KiCad required')
class GuideTransactionTests(unittest.TestCase):
    def replacement(self):
        case=fixture.PlacementTests();case.setUp()
        settings=dict(leaders=True,leader_distance=.1,body_clearance=.2)
        first=m.apply(case.board,p,m.plan(case.board,p,settings))
        self.assertTrue(first.leaders)
        self.assertEqual(lifecycle.verified_group_ids(case.board,p),{m.item_id(g) for g in first.groups})
        preview=m.plan(case.board,p,dict(settings,height=1.2,auto_size=False))
        self.assertTrue(preview.changes)
        self.assertTrue(preview.changes[0].previous_guides)
        return case,first,m.Transaction(case.board,p,preview)

    @staticmethod
    def snapshot(board):
        return (m.fingerprint(board,p),lifecycle._properties(board),
            sorted((m.item_id(g),g.GetName(),sorted((m.item_id(item),item.GetParentGroupId().AsString())
                for item in g.GetItems())) for g in board.Groups()))

    @contextmanager
    def fault(self,board,first,stage,after):
        old_groups={m.item_id(g) for g in first.groups}
        old_shapes={m.item_id(s) for s in first.leaders}
        membership=stage.endswith('membership')
        adding='add_' in stage
        method=('AddItem' if adding else 'RemoveItem') if membership else ('Add' if adding else 'Remove')
        old='_old_' in stage
        group_operation=stage.endswith('group')
        fired=[]
        if membership:
            native=getattr(p.PCB_GROUP,method)
            def wrapped(group,item):
                wanted=(m.item_id(group) in old_groups)==old
                if wanted and not fired:
                    fired.append(True)
                    if after:native(group,item)
                    raise RuntimeError('Injected '+stage)
                return native(group,item)
            with patch.object(p.PCB_GROUP,method,wrapped):yield fired
        else:
            native=getattr(board,method)
            def wrapped(item):
                kind=isinstance(item,p.PCB_GROUP) if group_operation else isinstance(item,p.PCB_SHAPE)
                identifiers=old_groups if group_operation else old_shapes
                wanted=kind and (m.item_id(item) in identifiers)==old
                if wanted and not fired:
                    fired.append(True)
                    if after:native(item)
                    raise RuntimeError('Injected '+stage)
                return native(item)
            with patch.object(board,method,side_effect=wrapped):yield fired

    def failed_redo(self,stage,after,reuse=False):
        case,first,transaction=self.replacement()
        if reuse:transaction.redo();transaction.undo()
        before=self.snapshot(case.board);expected=transaction.expected
        with self.fault(case.board,first,stage,after) as fired:
            with self.assertRaisesRegex(RuntimeError,'Injected'):transaction.redo()
        self.assertTrue(fired)
        self.assertEqual(before,self.snapshot(case.board))
        self.assertFalse(transaction.applied);self.assertEqual(transaction.expected,expected)
        transaction.redo();self.assertTrue(transaction.applied)
        self.assertEqual(lifecycle.verified_group_ids(case.board,p),{m.item_id(g) for g in transaction.groups})
        transaction.undo();self.assertEqual(before,self.snapshot(case.board))

    def failed_undo(self,stage,after):
        case,first,transaction=self.replacement();original=self.snapshot(case.board)
        transaction.redo();applied=self.snapshot(case.board);expected=transaction.expected
        with self.fault(case.board,first,stage,after) as fired:
            with self.assertRaisesRegex(RuntimeError,'Injected'):transaction.undo()
        self.assertTrue(fired)
        self.assertEqual(applied,self.snapshot(case.board))
        self.assertTrue(transaction.applied);self.assertEqual(transaction.expected,expected)
        transaction.undo();self.assertEqual(original,self.snapshot(case.board))
        transaction.redo();self.assertEqual(applied,self.snapshot(case.board))

    def test_old_guide_removal_rolls_back_before_and_after_native_mutation(self):
        for stage in ('remove_old_membership','remove_old_shape','remove_old_group'):
            for after in (False,True):
                with self.subTest(stage=stage,after=after):self.failed_redo(stage,after)

    def test_new_guide_creation_rolls_back_before_and_after_native_mutation(self):
        for stage in ('add_new_shape','add_new_membership','add_new_group'):
            for after in (False,True):
                with self.subTest(stage=stage,after=after):self.failed_redo(stage,after)

    def test_reused_redo_objects_remain_consistent_after_native_failure(self):
        for stage in ('add_new_shape','add_new_membership','add_new_group'):
            for after in (False,True):
                with self.subTest(stage=stage,after=after):self.failed_redo(stage,after,reuse=True)

    def test_undo_removal_rolls_back_before_and_after_native_mutation(self):
        for stage in ('remove_new_membership','remove_new_group','remove_new_shape'):
            for after in (False,True):
                with self.subTest(stage=stage,after=after):self.failed_undo(stage,after)

    def test_undo_restoration_rolls_back_before_and_after_native_mutation(self):
        for stage in ('add_old_group','add_old_shape','add_old_membership'):
            for after in (False,True):
                with self.subTest(stage=stage,after=after):self.failed_undo(stage,after)


if __name__=='__main__':unittest.main()
