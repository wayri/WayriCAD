"""Native KiCad custody, transform, detached DRC and GUI integration checks."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import pcbnew as api
    import wx
except ImportError:
    api = wx = None


@unittest.skipIf(api is None, 'KiCad native Python and wxPython required')
class NativeTests(unittest.TestCase):
    def setUp(self):
        from component_arranger_plugin import native
        self.native = native
        self.temp = tempfile.TemporaryDirectory(prefix='component-arranger-test-')
        self.path = Path(self.temp.name) / 'example.kicad_pcb'
        self.path.with_suffix('.kicad_pro').write_text('{}', encoding='utf-8')
        self.board = api.BOARD()
        self.board.SetFileName(str(self.path))
        self.v = lambda x, y: api.VECTOR2I(api.FromMM(x), api.FromMM(y))
        corners = [(0, 0), (40, 0), (40, 30), (0, 30)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            item = api.PCB_SHAPE(self.board)
            item.SetShape(api.SHAPE_T_SEGMENT)
            item.SetLayer(api.Edge_Cuts)
            item.SetStart(self.v(*a)); item.SetEnd(self.v(*b))
            item.SetWidth(api.FromMM(.05)); self.board.Add(item)
        self.nets = []
        for number, name in enumerate(('SIGNAL_A', 'SIGNAL_B'), 1):
            net = api.NETINFO_ITEM(self.board, name, number)
            self.board.Add(net); self.nets.append(net)
        self.parts = [self.make_part('U1', 15, 15), self.make_part('R1', 25, 15)]
        api.SaveBoard(str(self.path), self.board)

    def make_part(self, reference, x, y):
        fp = api.FOOTPRINT(self.board); fp.SetReference(reference); fp.SetValue('10k')
        self.board.Add(fp)
        fp.Reference().SetVisible(False); fp.Value().SetVisible(False)
        corners = [(-1, -.8), (1, -.8), (1, .8), (-1, .8)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            item = api.PCB_SHAPE(fp); item.SetShape(api.SHAPE_T_SEGMENT)
            item.SetLayer(api.F_CrtYd); item.SetStart(self.v(*a)); item.SetEnd(self.v(*b))
            item.SetWidth(api.FromMM(.05)); fp.Add(item)
        for number, point in enumerate(((.6, .3), (-.6, -.3))):
            pad = api.PAD(fp); pad.SetNumber(str(number + 1)); pad.SetPosition(self.v(*point))
            pad.SetSize(self.v(.4, .4)); pad.SetShape(api.PAD_SHAPE_RECT)
            pad.SetAttribute(api.PAD_ATTRIB_SMD); pad.SetLayerSet(pad.SMDMask())
            pad.SetNet(self.nets[number]); fp.Add(pad)
        fp.SetPosition(self.v(x, y))
        return fp

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, **options):
        return self.native.propose(self.board, api, ['U1', 'R1'], anchor='U1',
                                   area=(10, 10, 30, 20), max_candidates=300,
                                   passes=1, **options)

    def test_pose_transforms_all_eight_angles_and_both_sides(self):
        from component_arranger_plugin import engine
        fp = self.parts[1]
        original = self.native.model(fp, api)
        local = {p.number: (p.x, p.y) for p in original.pads}
        for side in ('top', 'bottom'):
            for angle in range(0, 360, 45):
                with self.subTest(side=side, angle=angle):
                    value = (24, 14, angle, side)
                    self.native.set_pose(fp, value, api)
                    model = replace(original, x=24, y=14, angle=angle, side=side)
                    self.assertEqual(self.native.pose(fp, api), value)
                    for pad in fp.Pads():
                        expected = engine.transform(local[pad.GetNumber()], model)
                        actual = pad.GetPosition()
                        self.assertAlmostEqual(api.ToMM(actual.x), expected[0], places=5)
                        self.assertAlmostEqual(api.ToMM(actual.y), expected[1], places=5)

    def test_model_and_proposal_are_read_only(self):
        before = self.native.fingerprint(self.board, api)
        text = self.path.read_bytes()
        model = self.native.model(self.parts[1], api)
        self.assertTrue(model.courtyards)
        import json
        from dataclasses import asdict
        json.dumps(asdict(model))
        plan = self.plan()
        self.assertTrue(plan.result.complete)
        self.assertEqual(before, self.native.fingerprint(self.board, api))
        self.assertEqual(text, self.path.read_bytes())

    def test_full_native_snapshot_restores_custom_children_metadata_and_group(self):
        """Full-image recovery fixture; the injected digest is not DRC acceptance."""
        fp = self.parts[1]
        for index, (name, text) in enumerate((('MPN', 'ABC123'), ('Tolerance', '1%'),
                                              ('Temperature Max', '125 C'))):
            field = api.PCB_FIELD(fp, api.FIELD_T_USER, name)
            field.SetText(text); field.SetVisible(index == 0)
            field.SetPosition(self.v(24, 13 + index))
            field.SetTextAngle(api.EDA_ANGLE(45 * (index + 1), api.DEGREES_T))
            fp.Add(field)
        model = api.FP_3DMODEL()
        model.m_Filename = '${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0805_2012Metric.step'
        model.m_Offset = api.VECTOR3D(.1, .2, .3)
        model.m_Rotation = api.VECTOR3D(15, 30, 45)
        model.m_Scale = api.VECTOR3D(1.2, .8, 1.1)
        model.m_Opacity = .7; fp.Add3DModel(model)
        pads = list(fp.Pads())
        pads[0].SetShape(api.PAD_SHAPE_ROUNDRECT); pads[0].SetRoundRectRadiusRatio(.2)
        pads[1].SetAttribute(api.PAD_ATTRIB_PTH)
        pads[1].SetDrillSize(self.v(.2, .3)); pads[1].SetDrillShape(api.PAD_DRILL_SHAPE_OBLONG)
        pads[1].SetLayerSet(pads[1].PTHMask())
        group = api.PCB_GROUP(self.board); group.SetName('Metadata recovery stage')
        self.board.Add(group); group.AddItem(fp)
        fp.SetSelected(); fp.SetLocked(True)
        self.board.BuildConnectivity()
        plan = self.plan()
        plan.validated_digest = self.native.digest(plan)
        tx = self.native.Transaction(self.board, api, plan)
        images = tx.capture()
        before = self.native.serialize(self.board, api)
        pad_ids = sorted(self.native.uid(p) for p in fp.Pads())
        pointer = self.native.identity(fp)
        group_pointer = self.native.identity(fp.GetParentGroup().AsEdaItem())
        for side in ('top', 'bottom'):
            for angle in range(0, 360, 45):
                with self.subTest(side=side, angle=angle):
                    self.native.set_pose(fp, (20, 12, angle, side), api)
                    tx.restore(images)
                    self.assertEqual(self.native.serialize(self.board, api), before)
                    self.assertEqual(sorted(self.native.uid(p) for p in fp.Pads()), pad_ids)
                    self.assertEqual(self.native.identity(fp), pointer)
                    self.assertEqual(self.native.identity(fp.GetParentGroup().AsEdaItem()), group_pointer)
                    self.assertTrue(fp.GetParentGroup().ContainsItem(fp))
                    self.assertEqual(len(list(group.GetItems())), 1)
                    self.assertTrue(fp.IsSelected()); self.assertTrue(fp.IsLocked())

    def test_native_group_selection_and_clone_never_join_source_group(self):
        from component_arranger_plugin import grouping
        group = api.PCB_GROUP(self.board)
        group.SetName('Filter stage'); self.board.Add(group)
        for fp in self.parts: group.AddItem(fp)
        group.SetSelected()
        before = self.native.serialize(self.board, api)
        result = grouping.board_groups(self.board)
        self.assertEqual(result['clusters'][0]['references'], ['R1', 'U1'])
        for fp in self.parts: self.native.model(fp, api)
        self.assertEqual(len(list(group.GetItems())), 2)
        self.assertEqual(self.native.serialize(self.board, api), before)

    def test_native_models_round_trip_bottom_and_rotated_courtyards(self):
        from component_arranger_plugin import engine
        fp = self.parts[1]
        for side in ('top', 'bottom'):
            for angle in range(0, 360, 45):
                with self.subTest(side=side, angle=angle):
                    self.native.set_pose(fp, (25, 15, angle, side), api)
                    before = self.native.serialize(self.board, api)
                    model = self.native.model(fp, api)
                    expected = sorted((round(x, 5), round(y, 5)) for p in self.native.courtyard(fp, api) for x, y in p)
                    actual = sorted((round(x, 5), round(y, 5)) for p in engine.world_courtyards(model) for x, y in p)
                    self.assertEqual(actual, expected)
                    self.assertEqual(self.native.serialize(self.board, api), before)

    def test_routed_footprint_held_fixed(self):
        pad = next(iter(self.parts[1].Pads()))
        track = api.PCB_TRACK(self.board)
        track.SetStart(pad.GetPosition()); track.SetEnd(self.v(28, 16))
        track.SetWidth(api.FromMM(.2)); track.SetLayer(api.F_Cu); track.SetNet(self.nets[0])
        self.board.Add(track)
        before = self.native.pose(self.parts[1], api)
        plan = self.plan()
        result = next(f for f in plan.result.footprints if f.reference == 'R1')
        self.assertEqual((result.x, result.y, result.angle, result.side), before)
        self.assertTrue(any('held fixed: R1' in w for w in plan.result.warnings))

    def test_six_part_decoupling_group_all_angles_both_sides_real_drc(self):
        from component_arranger_plugin import engine
        self.nets = [api.NETINFO_ITEM(self.board, name, i + 3) for i, name in enumerate(('VDD', 'GND'))]
        for net in self.nets:self.board.Add(net)
        for fp in self.parts:
            for pad in fp.Pads():pad.SetNet(self.nets[int(pad.GetNumber())-1])
        for ref,x,y,value in [('C1',23,20,'100 nF'),('C2',11,9,'1 uF'),('C3',26,9,'10 uF'),('R2',10,21,'10k')]:
            fp=self.make_part(ref,x,y);fp.SetValue(value);self.parts.append(fp)
        plan=self.native.propose(self.board,api,[fp.GetReference() for fp in self.parts],anchor='U1',
                area=(4,6,26,24),allowed_angles=tuple(range(0,360,45)),allowed_sides=('top','bottom'),
                capacitor_targets={'C1':'1','C2':'1','C3':'1'})
        self.assertTrue(plan.result.complete)
        self.assertEqual(plan.result.after.capacitor_order_violations,0)
        anchor=next(f for f in plan.result.footprints if f.reference=='U1')
        pin=next(p for p in anchor.pads if p.number=='1')
        target=engine.transform((pin.x,pin.y),anchor)
        import math
        distances=[]
        for ref in ('C1','C2','C3'):
            fp=next(f for f in plan.result.footprints if f.reference==ref)
            distances.append(min(math.dist(target,engine.transform((p.x,p.y),fp)) for p in fp.pads if p.net=='VDD'))
        self.assertLess(distances[0],distances[1]);self.assertLess(distances[1],distances[2])
        self.native.validate(self.board,api,plan)
        before=self.native.serialize(self.board,api)
        tx=self.native.Transaction(self.board,api,plan).exchange(True)
        tx.exchange(False)
        self.assertEqual(before,self.native.serialize(self.board,api))

    def test_live_netclass_changes_stale_and_unsaved_rules_reject_validation(self):
        plan = self.plan()
        nc = self.board.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
        nc.SetClearance(api.FromMM(.45))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.native.check(self.board, api, plan)
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, 'Live Board Setup'):
            self.native.validate(self.board, api, plan)
        self.assertFalse(plan.validated_digest)

    def test_worker_rejects_overlapping_materialized_courtyards(self):
        plan = self.plan()
        anchor = next(f for f in plan.result.footprints if f.reference == 'U1')
        plan.result = replace(plan.result, footprints=tuple(replace(f, x=anchor.x, y=anchor.y)
                              if f.reference == 'R1' else f for f in plan.result.footprints))
        source = self.native.serialize(self.board, api)
        with self.assertRaisesRegex(ValueError, 'findings|connectivity'):
            self.native.validate(self.board, api, plan)
        self.assertFalse(plan.validated_digest)
        self.assertEqual(source, self.native.serialize(self.board, api))

    def test_bottom_candidate_real_validation_and_reversible_apply(self):
        plan = self.plan(allowed_sides=('bottom',))
        self.assertTrue(plan.result.complete)
        moved = next(f for f in plan.result.footprints if f.reference == 'R1')
        self.assertEqual(moved.side, 'bottom')
        self.native.validate(self.board, api, plan)
        before = self.native.serialize(self.board, api)
        tx = self.native.Transaction(self.board, api, plan).exchange(True)
        self.assertTrue(self.parts[1].IsFlipped())
        tx.exchange(False)
        self.assertEqual(before, self.native.serialize(self.board, api))

    def test_initial_rotated_bottom_pose_restores_exactly(self):
        self.native.set_pose(self.parts[1], (25, 15, 45, 'bottom'), api)
        plan = self.plan(allowed_sides=('top', 'bottom'), allowed_angles=(0, 45, 90))
        self.assertTrue(plan.result.complete)
        self.native.validate(self.board, api, plan)
        before = self.native.serialize(self.board, api)
        tx = self.native.Transaction(self.board, api, plan).exchange(True)
        tx.exchange(False)
        self.assertEqual(before, self.native.serialize(self.board, api))

    def test_native_drc_apply_undo_redo_and_exact_source_custody(self):
        before = self.native.serialize(self.board, api)
        source = self.path.read_bytes()
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, 'Validate'):
            self.native.Transaction(self.board, api, plan)
        self.native.validate(self.board, api, plan)
        self.assertEqual(plan.evidence['new_findings'], 0)
        self.assertEqual(plan.evidence['routing'], 'unchanged')
        tx = self.native.Transaction(self.board, api, plan).exchange(True)
        self.assertTrue(tx.applied)
        self.assertTrue(tx.backup.is_file())
        self.assertNotEqual(self.native.serialize(self.board, api), before)
        tx.exchange(False)
        self.assertEqual(self.native.serialize(self.board, api), before)
        tx.exchange(True); tx.exchange(False)
        self.assertEqual(self.native.serialize(self.board, api), before)
        self.assertEqual(source, self.path.read_bytes())

    def test_stale_board_and_unvalidated_digest_mutation_blocked(self):
        plan = self.plan()
        self.parts[1].SetPosition(self.v(26, 15))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.native.validate(self.board, api, plan)
        plan = self.plan()
        plan.validated_digest = self.native.digest(plan)  # Fault-injection gate fixture only.
        plan.result = replace(plan.result, footprints=tuple(replace(f, x=f.x + .1) if f.reference == 'R1' else f for f in plan.result.footprints))
        with self.assertRaisesRegex(ValueError, 'exact proposal'):
            self.native.Transaction(self.board, api, plan)

    def test_selection_saved_rules_and_origin_board_staleness(self):
        plan = self.plan()
        self.parts[0].SetSelected()
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.native.check(self.board, api, plan)
        self.parts[0].ClearSelected()
        plan = self.plan()
        self.path.with_suffix('.kicad_pro').write_text('{"meta":{"version":1}}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.native.check(self.board, api, plan)
        plan = self.plan()
        other = api.LoadBoard(str(self.path))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.native.check(other, api, plan)
        plan = self.plan()
        self.path.write_bytes(self.path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.native.check(self.board, api, plan)

    def test_set_pose_post_mutation_failure_rolls_back_exactly(self):
        plan = self.plan()
        plan.validated_digest = self.native.digest(plan)  # Exercise recovery, not DRC acceptance.
        before = self.native.serialize(self.board, api)
        original = self.native.set_pose
        called = [False]
        def fail_once(*args):
            original(*args)
            if not called[0]:
                called[0] = True
                raise RuntimeError('Injected native pose failure after mutation')
        tx = self.native.Transaction(self.board, api, plan)
        with patch.object(self.native, 'set_pose', side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, 'Injected native pose'):
                tx.exchange(True)
        self.assertEqual(self.native.serialize(self.board, api), before)

    def test_native_ui_constructs_and_runs_real_preview(self):
        if wx.GetApp() is None:
            self.skipTest('Run GUI checks inside the normal wx main-loop harness.')
        from component_arranger_plugin.ui import ArrangerFrame
        for fp in self.parts: fp.SetSelected()
        frame = ArrangerFrame(None, self.board)
        errors = []
        frame.error = lambda error: errors.append(str(error))
        try:
            frame.Show(); wx.YieldIfNeeded()
            frame.find_groups(None)
            frame.area_w.SetValue('20'); frame.area_h.SetValue('10')
            before = self.native.fingerprint(self.board, api)
            frame.preview(None)
            self.assertEqual(errors, [])
            self.assertIsNotNone(frame.plan)
            self.assertTrue(frame.plan.result.complete)
            self.assertTrue(frame.canvas.models)
            self.assertEqual(before, self.native.fingerprint(self.board, api))
            self.assertFalse(frame.apply_button.IsEnabled())
            self.assertTrue(frame.validate_button.IsEnabled())
        finally:
            frame.Destroy(); wx.YieldIfNeeded()


if __name__ == '__main__':
    unittest.main()
