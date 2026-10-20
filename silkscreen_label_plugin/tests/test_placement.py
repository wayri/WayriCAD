"""Native placement, no mutation, failure and reversible-edit contracts."""
import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path
try:
    import pcbnew as api
except ImportError:
    api = None
from silkscreen_label_plugin.placement import plan, apply, fingerprint


def dense_board(native, columns=10, rows=10, pitch=3.4):
    """Public synthetic dense two-pad assembly; references start over copper."""
    board=native.BOARD()
    v=lambda x,y:native.VECTOR2I(native.FromMM(x),native.FromMM(y))
    width,height=columns*pitch+8,rows*pitch+8
    corners=[(0,0),(width,0),(width,height),(0,height)]
    for i,a in enumerate(corners):
        edge=native.PCB_SHAPE(board);edge.SetShape(native.SHAPE_T_SEGMENT)
        edge.SetStart(v(*a));edge.SetEnd(v(*corners[(i+1)%4]));edge.SetLayer(native.Edge_Cuts)
        board.Add(edge)
    for y in range(rows):
        for x in range(columns):
            fp=native.FOOTPRINT(board);fp.SetReference('R'+str(y*columns+x+1))
            position=v(4+x*pitch,4+y*pitch);fp.SetPosition(position);board.Add(fp)
            text=fp.Reference();text.SetLayer(native.F_SilkS);text.SetPosition(position)
            text.SetTextSize(v(1,1));text.SetTextThickness(native.FromMM(.15));fp.Value().SetVisible(False)
            for offset in (-.6,.6):
                pad=native.PAD(fp);pad.SetPosition(v(4+x*pitch+offset,4+y*pitch))
                pad.SetSize(v(.6,.8));pad.SetShape(native.PAD_SHAPE_RECT)
                pad.SetAttribute(native.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask());fp.Add(pad)
    return board


@unittest.skipIf(api is None, 'KiCad native bindings are required.')
class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.board = api.BOARD()
        self.v = lambda x,y: api.VECTOR2I(api.FromMM(x),api.FromMM(y))
        points = [(0,0),(40,0),(40,40),(0,40)]
        for i,(x,y) in enumerate(points):
            edge = api.PCB_SHAPE(self.board)
            edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetStart(self.v(x,y)); edge.SetEnd(self.v(*points[(i+1)%4]))
            edge.SetLayer(api.Edge_Cuts); self.board.Add(edge)
        self.fp = api.FOOTPRINT(self.board)
        self.fp.SetReference('U1'); self.fp.SetPosition(self.v(20,20)); self.board.Add(self.fp)
        self.text = self.fp.Reference()
        self.text.SetPosition(self.v(20,20)); self.text.SetLayer(api.F_SilkS)
        self.text.SetTextSize(self.v(1,1)); self.text.SetTextThickness(api.FromMM(.15))
        self.pad = api.PAD(self.fp)
        self.pad.SetPosition(self.v(20,20)); self.pad.SetSize(self.v(2,2))
        self.pad.SetShape(api.PAD_SHAPE_RECT); self.pad.SetAttribute(api.PAD_ATTRIB_SMD)
        self.pad.SetLayerSet(self.pad.SMDMask()); self.fp.Add(self.pad)

    def test_preview_read_only_and_undo_redo(self):
        before = fingerprint(self.board,api)
        preview = plan(self.board,api)
        self.assertTrue(preview.changes)
        self.assertEqual(before,fingerprint(self.board,api))
        moved = preview.changes[0]
        self.assertFalse(moved.box.Intersects(self.pad.GetBoundingBox()))
        tx = apply(self.board,api,preview)
        self.assertNotEqual(before,fingerprint(self.board,api))
        tx.undo(); self.assertEqual(before,fingerprint(self.board,api))
        tx.redo(); self.assertEqual(tx.expected,fingerprint(self.board,api))

    def test_hidden_and_locked_untouched(self):
        self.text.SetVisible(False)
        self.assertFalse(plan(self.board,api).changes)
        self.text.SetVisible(True); self.text.SetLocked(True)
        self.assertFalse(plan(self.board,api).changes)

    def test_stale_content_and_undo(self):
        preview = plan(self.board,api)
        self.text.SetText('Renamed')
        with self.assertRaisesRegex(ValueError,'Board changed'):
            apply(self.board,api,preview)
        tx = apply(self.board,api,plan(self.board,api))
        self.pad.SetSize(self.v(3,3))
        with self.assertRaisesRegex(ValueError,'Board changed'):
            tx.undo()

    def test_search_exhaustion_never_forces(self):
        self.pad.SetSize(self.v(20,20))
        preview = plan(self.board,api,{'max_radius':1,'step':.5})
        self.assertFalse(preview.changes)
        self.assertTrue(preview.rejected)

    def test_bottom_and_mirroring(self):
        self.fp.SetLayer(api.B_Cu); self.text.SetLayer(api.B_SilkS)
        layers = api.LSET(); layers.AddLayer(api.B_Cu); layers.AddLayer(api.B_Mask); self.pad.SetLayerSet(layers)
        preview = plan(self.board,api)
        self.assertTrue(preview.changes)
        tx = apply(self.board,api,preview)
        self.assertTrue(self.text.IsMirrored())
        self.assertEqual(self.text.GetLayer(),api.B_SilkS)
        tx.undo()

    def test_leader_is_checked_and_reversible(self):
        preview = plan(self.board,api,{'leader_distance':.5})
        self.assertTrue(preview.changes)
        self.assertTrue(preview.changes[0].leader)
        before = len(list(self.board.GetDrawings()))
        tx = apply(self.board,api,preview)
        self.assertEqual(len(list(self.board.GetDrawings())),before+1)
        tx.undo(); self.assertEqual(len(list(self.board.GetDrawings())),before)

    def test_validation_and_missing_outline(self):
        for settings in ({'step':0},{'height':float('nan')},{'max_radius':1000}):
            with self.assertRaises(ValueError): plan(self.board,api,settings)
        with self.assertRaisesRegex(ValueError,'Edge.Cuts'):
            plan(api.BOARD(),api)

    def test_selection_and_native_floors(self):
        self.assertFalse(plan(self.board,api,{'selected_only':True}).changes)
        self.fp.SetSelected()
        self.board.GetDesignSettings().m_MinSilkTextHeight = api.FromMM(1.4)
        self.board.GetDesignSettings().m_MinSilkTextThickness = api.FromMM(.2)
        preview = plan(self.board,api,{'selected_only':True,'height':.7,'thickness':.1,'auto_size':False})
        self.assertTrue(preview.changes)
        self.assertGreaterEqual(preview.changes[0].size[0],api.FromMM(1.4))
        self.assertGreaterEqual(preview.changes[0].thickness,api.FromMM(.2))

    def test_selected_pad_includes_its_parent(self):
        self.pad.SetSelected()
        self.assertTrue(plan(self.board,api,{'selected_only':True}).changes)

    def test_native_mask_graphics_are_avoided(self):
        opening=api.PCB_SHAPE(self.board);opening.SetShape(api.SHAPE_T_RECT)
        opening.SetStart(self.v(17,14));opening.SetEnd(self.v(23,19))
        opening.SetLayer(api.F_Mask);self.board.Add(opening)
        preview=plan(self.board,api)
        self.assertTrue(preview.changes)
        for change in preview.changes:
            self.assertFalse(change.box.Intersects(opening.GetBoundingBox()))

    def test_leaders_do_not_cross_other_text(self):
        obstacle = api.PCB_TEXT(self.board)
        obstacle.SetText('BLOCK'); obstacle.SetLayer(api.F_SilkS)
        obstacle.SetPosition(self.v(20,17)); obstacle.SetTextSize(self.v(2,2))
        self.board.Add(obstacle)
        preview = plan(self.board,api,{'leader_distance':.5})
        self.assertTrue(preview.changes)
        from silkscreen_label_plugin.placement import segment_hits_box
        for change in preview.changes:
            if change.leader:
                x,y,a,b,w,_ = change.leader
                self.assertFalse(segment_hits_box(api.VECTOR2I(x,y),api.VECTOR2I(a,b),obstacle.GetBoundingBox(),w//2))

    def test_cutout_and_mask_graphic_are_obstacles(self):
        points=[(16,16),(24,16),(24,24),(16,24)]
        for i,a in enumerate(points):
            edge=api.PCB_SHAPE(self.board);edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetStart(self.v(*a));edge.SetEnd(self.v(*points[(i+1)%4]))
            edge.SetLayer(api.Edge_Cuts);self.board.Add(edge)
        preview=plan(self.board,api,{'max_radius':2})
        self.assertFalse(preview.changes)
        self.assertTrue(preview.rejected)

    def test_partial_set_failure_rolls_back(self):
        from silkscreen_label_plugin import placement
        original=placement._set
        preview=plan(self.board,api)
        before=fingerprint(self.board,api)
        calls=[]
        def fail_once(text,state,native):
            original(text,state,native)
            calls.append(1)
            if len(calls)==1:raise RuntimeError('Injected setter failure')
        with patch.object(placement,'_set',side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError,'Injected'):
                apply(self.board,api,preview)
        self.assertEqual(fingerprint(self.board,api),before)

    def test_leader_identity_and_chained_transactions(self):
        tx1=apply(self.board,api,plan(self.board,api,{'leader_distance':.5}))
        leader_ids=[shape.m_Uuid.AsString() for shape in tx1.leaders]
        tx2=apply(self.board,api,plan(self.board,api,{'height':1.3,'leader_distance':.5}))
        tx2.undo(); tx1.undo(); tx1.redo(); tx2.redo()
        self.assertEqual(leader_ids,[shape.m_Uuid.AsString() for shape in tx1.leaders])
        tx2.undo(); tx1.undo()

    def test_repeated_plan_does_not_duplicate_guides(self):
        settings={'leader_distance':.5}
        tx=apply(self.board,api,plan(self.board,api,settings))
        self.assertTrue(tx.leaders)
        self.assertFalse(plan(self.board,api,settings).changes)
        changed=plan(self.board,api,{'leader_distance':.5,'height':1.4})
        tx2=apply(self.board,api,changed)
        self.assertEqual(len(list(self.board.Groups())),1)
        tx2.undo();self.assertEqual(len(list(self.board.Groups())),1)
        tx.undo();self.assertFalse(list(self.board.Groups()))

    def test_guide_ownership_survives_save_reload(self):
        settings={'leader_distance':.5}
        apply(self.board,api,plan(self.board,api,settings))
        with tempfile.TemporaryDirectory() as folder:
            filename=str(Path(folder)/'labels.kicad_pcb')
            api.SaveBoard(filename,self.board)
            loaded=api.LoadBoard(filename)
            self.assertFalse(plan(loaded,api,settings).changes)
            self.assertEqual(len(list(loaded.Groups())),1)

    def test_failed_group_add_rolls_back_membership_and_text(self):
        preview=plan(self.board,api,{'leader_distance':.5})
        before=fingerprint(self.board,api)
        add=self.board.Add
        def fail_group(item):
            if isinstance(item,api.PCB_GROUP):raise RuntimeError('Injected group add failure')
            add(item)
        with patch.object(self.board,'Add',side_effect=fail_group):
            with self.assertRaisesRegex(RuntimeError,'Injected group'):
                apply(self.board,api,preview)
        self.assertEqual(fingerprint(self.board,api),before)
        self.assertFalse(list(self.board.Groups()))

    def test_failed_undo_restore_recovers_applied_state(self):
        settings={'leader_distance':.5}
        tx1=apply(self.board,api,plan(self.board,api,settings))
        tx2=apply(self.board,api,plan(self.board,api,dict(settings,height=1.4)))
        before=fingerprint(self.board,api); add=self.board.Add
        ids={shape.m_Uuid.AsString() for shape in tx1.leaders}
        failed=[]
        def fail_old_shape(item):
            if isinstance(item,api.PCB_SHAPE) and item.m_Uuid.AsString() in ids and not failed:
                failed.append(True);raise RuntimeError('Injected guide restore failure')
            add(item)
        with patch.object(self.board,'Add',side_effect=fail_old_shape):
            with self.assertRaisesRegex(RuntimeError,'Injected guide'):
                tx2.undo()
        self.assertEqual(fingerprint(self.board,api),before)
        self.assertTrue(tx2.applied)
        tx2.undo();tx1.undo()

    def test_rollback_failure_is_explicit(self):
        preview=plan(self.board,api,{'leader_distance':.5})
        add=self.board.Add
        def fail_group(item):
            if isinstance(item,api.PCB_GROUP):raise RuntimeError('Injected add failure')
            add(item)
        with patch.object(self.board,'Add',side_effect=fail_group), patch.object(self.board,'Remove',side_effect=RuntimeError('Injected recovery failure')):
            with self.assertRaisesRegex(RuntimeError,'recovery needs attention') as caught:
                apply(self.board,api,preview)
        self.assertTrue(hasattr(caught.exception,'transaction'))

    def test_cancelled_plan_is_read_only(self):
        before=fingerprint(self.board,api)
        with self.assertRaisesRegex(ValueError,'cancelled'):
            plan(self.board,api,progress=lambda *_:False)
        self.assertEqual(before,fingerprint(self.board,api))

    def test_dense_hundred_part_assembly(self):
        from silkscreen_label_plugin.placement import _inflate
        board=dense_board(api)
        before=fingerprint(board,api)
        preview=plan(board,api)
        self.assertEqual(before,fingerprint(board,api))
        self.assertEqual(preview.stats['eligible'],100)
        self.assertGreaterEqual(preview.stats['placed'],90)
        self.assertLess(preview.stats['elapsed_seconds'],15)
        apply(board,api,preview)
        texts=[fp.Reference() for fp in board.GetFootprints()]
        boxes=[t.GetBoundingBox() for t in texts]
        for i,box in enumerate(boxes):
            self.assertFalse(any(_inflate(box,api.FromMM(.2),api).Intersects(other) for other in boxes[i+1:]))
        self.assertFalse(plan(board,api).changes)

    def test_dense_search_finds_slot_outside_eight_rays(self):
        # Only a 2.7 x 2.2 mm mask-free window remains. Its centre is neither
        # on a cardinal/diagonal ray nor on the old 0.5 mm search grid.
        for left,top,right,bottom in ((0,0,40,16.1),(0,18.3,40,40),
                                     (0,16.1,20.05,18.3),(22.75,16.1,40,18.3)):
            opening=api.PCB_SHAPE(self.board);opening.SetShape(api.SHAPE_T_RECT)
            opening.SetStart(self.v(left,top));opening.SetEnd(self.v(right,bottom))
            opening.SetLayer(api.F_Mask);opening.SetFilled(True);opening.SetWidth(0);self.board.Add(opening)
        preview=plan(self.board,api,{'leaders':False,'max_radius':4})
        self.assertEqual(len(preview.changes),1)
        change=preview.changes[0]
        self.assertAlmostEqual(api.ToMM(change.position[0]),21.4,places=1)
        self.assertAlmostEqual(api.ToMM(change.position[1]),17.2,places=1)

    def test_difficult_long_labels_take_priority(self):
        # A large slot and a small slot: the long label cannot fit the latter.
        for left,top,right,bottom in ((0,0,40,15.8),(0,18.6,40,20.8),(0,23.2,40,40),
                                     (0,15.8,16.5,18.6),(23.5,15.8,40,18.6),
                                     (0,20.8,23,23.2),(25,20.8,40,23.2)):
            opening=api.PCB_SHAPE(self.board);opening.SetShape(api.SHAPE_T_RECT)
            opening.SetStart(self.v(left,top));opening.SetEnd(self.v(right,bottom))
            opening.SetLayer(api.F_Mask);opening.SetFilled(True);opening.SetWidth(0);self.board.Add(opening)
        self.text.SetVisible(False)
        for value in ('X','LARGE'):
            text=api.PCB_TEXT(self.board);text.SetText(value);text.SetLayer(api.F_SilkS)
            text.SetPosition(self.v(20,20));text.SetTextSize(self.v(1,1))
            text.SetTextThickness(api.FromMM(.15));self.board.Add(text)
        preview=plan(self.board,api,{'references':False,'board_text':True})
        self.assertEqual(len(preview.changes),2)
        self.assertEqual(preview.changes[0].label,'LARGE')
        self.assertEqual(preview.stats['unresolved'],0)

    def test_small_board_cutout_inside_text_envelope_is_avoided(self):
        self.text.SetPosition(self.v(20,17))
        corners=[(19.8,16.8),(20.2,16.8),(20.2,17.2),(19.8,17.2)]
        for i,a in enumerate(corners):
            edge=api.PCB_SHAPE(self.board);edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetStart(self.v(*a));edge.SetEnd(self.v(*corners[(i+1)%4]))
            edge.SetLayer(api.Edge_Cuts);self.board.Add(edge)
        preview=plan(self.board,api)
        self.assertTrue(preview.changes)
        hole=api.BOX2I(self.v(19.8,16.8),self.v(.4,.4))
        self.assertFalse(preview.changes[0].box.Intersects(hole))

    def test_mutation_during_progress_discards_preview(self):
        changed=[]
        def progress(*_):
            if not changed:
                self.text.SetText('CHANGED');changed.append(True)
            return True
        with self.assertRaisesRegex(ValueError,'Board changed during'):
            plan(self.board,api,progress=progress)

    def test_native_styled_rotated_field_matches_preview(self):
        self.fp.SetOrientationDegrees(45)
        self.text.SetTextAngle(api.EDA_ANGLE(45,api.DEGREES_T))
        self.text.SetBold(True); self.text.SetItalic(True)
        self.text.SetHorizJustify(api.GR_TEXT_H_ALIGN_RIGHT)
        preview=plan(self.board,api)
        self.assertTrue(preview.changes)
        apply(self.board,api,preview)
        actual=self.text.GetBoundingBox(); expected=preview.changes[0].box
        self.assertEqual((actual.GetLeft(),actual.GetTop(),actual.GetRight(),actual.GetBottom()),
                         (expected.GetLeft(),expected.GetTop(),expected.GetRight(),expected.GetBottom()))


if __name__ == '__main__': unittest.main()


