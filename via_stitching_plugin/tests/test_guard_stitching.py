"""Exact-scope, clearance and source-custody checks for guard-via planning."""
import json
import math
from pathlib import Path
import tempfile
import unittest

try:
    import pcbnew as p
except ImportError:
    p = None

from wayricad_runtime.routing import plan_stitching, plan_document
from wayricad_runtime.geometry import board_fingerprint, item_id


@unittest.skipIf(p is None, 'Requires native KiCad Python')
class GuardStitchingTests(unittest.TestCase):
    @staticmethod
    def pos(x, y):
        return p.VECTOR2I(p.FromMM(x), p.FromMM(y))

    def setUp(self):
        self.board = p.BOARD()
        self.nets = {}
        for name in ('GND', 'SIGNAL', 'CLOCK'):
            net = p.NETINFO_ITEM(self.board, name); self.board.Add(net); self.nets[name] = net
        for a,b in (((0,0),(40,0)), ((40,0),(40,30)), ((40,30),(0,30)), ((0,30),(0,0))):
            shape = p.PCB_SHAPE(self.board); shape.SetShape(p.SHAPE_T_SEGMENT)
            shape.SetStart(self.pos(*a)); shape.SetEnd(self.pos(*b)); shape.SetLayer(p.Edge_Cuts)
            self.board.Add(shape)
        self.signal = self.track((5,10),(35,10),'SIGNAL')
        self.clock = self.track((5,20),(35,20),'CLOCK')
        self.settings = dict(mode='Guard selected routes', guard_nets=['SIGNAL'],
            net_choice='GND', guard_offset=1, spacing=3, diameter=.6, drill=.3,
            clearance=.2, edge=.5, require_target_zone=False, skip_parts=False)

    def track(self, start, end, net):
        track = p.PCB_TRACK(self.board); track.SetStart(self.pos(*start)); track.SetEnd(self.pos(*end))
        track.SetWidth(p.FromMM(.25)); track.SetLayer(p.F_Cu); track.SetNet(self.nets[net])
        self.board.Add(track); return track

    def plan(self, **overrides):
        return plan_stitching(self.board, p, dict(self.settings, **overrides))

    def test_both_sides_exact_scope_and_source_unchanged(self):
        before = board_fingerprint(self.board)
        vias, rejected = self.plan()
        self.assertEqual(len(vias), 22)
        self.assertFalse(rejected)
        self.assertEqual({round(p.ToMM(v.GetPosition().y), 6) for v in vias}, {9,11})
        self.assertTrue(all(v.GetNetname() == 'GND' and v.GetViaType() == p.VIATYPE_THROUGH for v in vias))
        self.assertEqual(board_fingerprint(self.board), before)
        self.assertEqual(len(list(self.board.GetTracks())), 2)

    def test_track_ids_and_multiple_exact_nets(self):
        vias, _ = self.plan(guard_nets=[], guard_tracks=[item_id(self.clock)])
        self.assertEqual({round(p.ToMM(v.GetPosition().y),6) for v in vias}, {19,21})
        vias, _ = self.plan(guard_nets=['SIGNAL','CLOCK'])
        self.assertEqual(len(vias), 44)
        with self.assertRaisesRegex(ValueError, 'no longer exist'):
            self.plan(guard_tracks=['missing'])
        with self.assertRaisesRegex(ValueError, 'no saved tracks'):
            self.plan(guard_nets=['NOT_A_NET'])

    def test_guard_net_cannot_be_the_signal_net(self):
        with self.assertRaisesRegex(ValueError, 'differ'):
            self.plan(net_choice='SIGNAL')
        with self.assertRaisesRegex(ValueError, 'signal net'):
            self.plan(guard_nets=[], guard_tracks=[item_id(self.signal)], net_choice='SIGNAL')

    def test_one_side_and_diagonal_clearance(self):
        vias, _ = self.plan(guard_side='Left')
        self.assertEqual(len(vias),11)
        self.assertTrue(all(p.ToMM(v.GetPosition().y) == 9 for v in vias))
        self.board.Remove(self.signal)
        self.signal = self.track((5,5),(25,25),'SIGNAL')
        vias, _ = self.plan()
        self.assertGreater(len(vias), 10)
        for via in vias:
            x,y = p.ToMM(via.GetPosition().x), p.ToMM(via.GetPosition().y)
            self.assertAlmostEqual(abs(y-x)/math.sqrt(2), 1, places=5)

    def test_clearance_existing_vias_and_proposal_separation(self):
        existing = p.PCB_VIA(self.board); existing.SetPosition(self.pos(8,11))
        existing.SetWidth(p.FromMM(.6)); existing.SetDrill(p.FromMM(.3)); existing.SetNet(self.nets['GND'])
        self.board.Add(existing)
        vias, rejected = self.plan()
        self.assertTrue(rejected)
        self.assertNotIn((8,11), [(p.ToMM(v.GetPosition().x),p.ToMM(v.GetPosition().y)) for v in vias])
        points = [v.GetPosition() for v in vias]
        self.assertTrue(all(math.hypot(a.x-b.x,a.y-b.y) >= p.FromMM(.8) for i,a in enumerate(points) for b in points[i+1:]))
        vias, rejected = self.plan(guard_offset=.2)
        self.assertFalse(vias)
        self.assertGreater(rejected.get('other-net track/via', 0), 0)

    def test_arc_is_reported_without_silent_chord_conversion(self):
        arc = p.PCB_ARC(self.board); arc.SetStart(self.pos(5,5)); arc.SetMid(self.pos(10,2)); arc.SetEnd(self.pos(15,5))
        arc.SetWidth(p.FromMM(.2)); arc.SetLayer(p.F_Cu); arc.SetNet(self.nets['SIGNAL']); self.board.Add(arc)
        vias, rejected = self.plan()
        self.assertTrue(vias)
        self.assertEqual(rejected.get('unsupported arc target'), 1)
        with self.assertRaisesRegex(ValueError, 'No supported straight'):
            self.plan(guard_nets=[], guard_tracks=[item_id(arc)])

    def test_budget_cancel_and_bad_scope_fail_without_partial_outputs(self):
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.plan(guard_budget=10)
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            plan_stitching(self.board,p,self.settings,cancel=lambda: True)
        with self.assertRaisesRegex(ValueError, 'bounded list'):
            self.plan(guard_nets='SIGNAL')
        for value in (float('nan'), -1, 0):
            with self.assertRaises(ValueError): self.plan(guard_offset=value)
        for values in (dict(diameter=1e-6,drill=1e-7),dict(guard_offset=1e-7),dict(spacing=1e-7)):
            with self.assertRaisesRegex(ValueError,'resolution'):
                self.plan(**values)
        with self.assertRaisesRegex(ValueError,'resolution'):
            plan_stitching(self.board,p,dict(require_target_zone=False,diameter=1e-6,drill=1e-7))

    def test_native_polygon_hole_distances_match_independent_python_geometry(self):
        from wayricad_runtime.routing import StitchingPlanner
        from wayricad_runtime.geometry import disk_inside
        native=p.SHAPE_POLY_SET();native.NewOutline()
        outer=[(0,0),(100,0),(100,100),(0,100)]
        hole=[(40,40),(60,40),(60,60),(40,60)]
        for x,y in outer:native.Append(x,y)
        native.NewHole(0)
        for x,y in hole:native.Append(x,y,0,0)
        planner=StitchingPlanner(self.board,p,{})
        shapes=planner._guard_geometry(native)
        for x in range(-3,104,7):
            for y in range(-3,104,7):
                for radius in (1,5,10):
                    self.assertEqual(planner._guard_inside(p.VECTOR2I(x,y),radius,shapes),
                                     disk_inside((x,y),radius,outer,[hole]),(x,y,radius))

    def test_filled_target_copper_is_required_by_default(self):
        with self.assertRaisesRegex(ValueError,'No copper zones'):
            self.plan(require_target_zone=True)
        zone = p.ZONE(self.board); zone.SetLayer(p.F_Cu); zone.SetNet(self.nets['GND'])
        outline=zone.Outline(); outline.NewOutline()
        for point in ((1,1),(39,1),(39,29),(1,29)):
            outline.Append(self.pos(*point).x,self.pos(*point).y)
        self.board.Add(zone)
        with self.assertRaisesRegex(ValueError,'Fill the target'):
            self.plan(require_target_zone=True)
        zone.SetFilledPolysList(p.F_Cu,outline); zone.SetIsFilled(True)
        vias, _ = self.plan(require_target_zone=True)
        self.assertTrue(vias)

    def test_grid_mode_retains_grid_and_rejection_priority(self):
        default, reasons = plan_stitching(self.board,p,dict(require_target_zone=False,skip_parts=False))
        explicit, explicit_reasons = plan_stitching(self.board,p,dict(mode='Grid',require_target_zone=False,skip_parts=False))
        coordinates = lambda vias: [(v.GetPosition().x,v.GetPosition().y) for v in vias]
        self.assertEqual(coordinates(default), coordinates(explicit))
        self.assertEqual(reasons, explicit_reasons)

    def test_saved_board_manufacturing_floors_cannot_be_reduced(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'rules.kicad_pcb'
            self.board.SetFileName(str(source))
            for rule, floor in [('min_clearance',.3),('min_via_diameter',.8),
                                ('min_through_hole_diameter',.4),('min_via_annular_width',.2)]:
                project=dict(board=dict(design_settings=dict(rules={rule:floor})))
                source.with_suffix('.kicad_pro').write_text(json.dumps(project),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'floor|clearance'):
                    self.plan()

    def test_cli_review_roundtrip_and_saved_rules_are_bound(self):
        from types import SimpleNamespace
        from wayricad_runtime.cli import execute
        footprint = p.FOOTPRINT(self.board); footprint.SetReference('GND1')
        pad = p.PAD(footprint); pad.SetNumber('1'); pad.SetPosition(self.pos(2,2))
        pad.SetSize(self.pos(1,1)); pad.SetAttribute(p.PAD_ATTRIB_SMD)
        layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers);pad.SetNet(self.nets['GND'])
        footprint.Add(pad); self.board.Add(footprint)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'source.kicad_pcb'
            p.SaveBoard(str(source),self.board)
            project = source.with_suffix('.kicad_pro'); project.write_text(json.dumps(dict(net_settings=dict(classes=[dict(name='Default',clearance=.2)]))),encoding='utf-8')
            settings = root/'settings.json'; settings.write_text(json.dumps(self.settings),encoding='utf-8')
            plan = root/'plan.json'; output = root/'candidate.kicad_pcb'
            original = source.read_bytes()
            execute(SimpleNamespace(kind='stitching',operation='plan',board=source,settings=settings,output=plan,svg=root/'preview.svg'))
            args = SimpleNamespace(kind='stitching',operation='apply',board=source,plan=plan,output=output)
            result = execute(args)
            self.assertEqual(result['created_items'],22)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(len(list(p.LoadBoard(str(output)).GetTracks())),24)
            project.write_text(project.read_text().replace('0.2','0.3'),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'clearance|changed'):
                execute(args)
            self.assertEqual(source.read_bytes(),original)


if __name__ == '__main__':
    unittest.main()
