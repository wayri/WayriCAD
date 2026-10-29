"""Full-bank alternation and conservative inward rejection on native fixtures."""
import math
import unittest
import test_perimeter_expansion as fixture
p = fixture.p
from wayricad_runtime.routing import plan_fanout
from wayricad_runtime.perimeter_escape import bank


@unittest.skipIf(p is None, 'Native KiCad required')
class PerimeterStaggerTests(unittest.TestCase):
    def fixture(self, rotation=0):
        return fixture.PerimeterExpansionTests().fixture(qfp=True, rotation=rotation)

    def plan(self, board, **options):
        settings = dict(pattern='Staggered rows', width=.15, clearance=.1,
                        via_diameter=.5, via_drill=.2, length=1.5, stagger_pitch=.7)
        settings.update(options)
        return plan_fanout(board, p, settings)

    @staticmethod
    def geometry(plans):
        return {plan.pad.GetNumber(): [(v.x,v.y) for v in plan.path] for plan in plans}

    def test_every_side_alternates_short_long_at_arbitrary_rotation(self):
        for rotation in (0, 37, 90, 180):
            board, fp = self.fixture(rotation)
            plans, rejected = self.plan(board)
            self.assertFalse(rejected);self.assertEqual(len(plans),32)
            for plan in plans:
                normal, _, _, index, _ = bank(fp, plan.pad, p)
                delta = (plan.end.x-plan.start.x,plan.end.y-plan.start.y)
                reach = 1.5+(index%2)*.7
                self.assertAlmostEqual(p.ToMM(delta[0]*normal[0]+delta[1]*normal[1]),reach,places=5)
                self.assertAlmostEqual(plan.length_mm,reach,places=5)
            again, rejected = self.plan(board)
            self.assertEqual(self.geometry(again),self.geometry(plans))
            self.assertFalse(list(board.GetTracks()))

    def test_selection_filters_and_groups_do_not_restart_alternation(self):
        board, fp = self.fixture(37)
        baseline, rejected = self.plan(board)
        expected = self.geometry(baseline)
        selected = {'2','4','7','10','17','30'}
        for pad in fp.Pads():
            if pad.GetNumber() in selected:pad.SetSelected()
        for options in (dict(scope='Selected pads'),dict(pad_filter=','.join(selected)),
                        dict(groups=[dict(name='Subset',match=dict(pad=','.join(selected)),settings={})],unmatched='skip')):
            plans, rejected = self.plan(board,**options)
            self.assertTrue(all('unmatched pad skipped' in reason for reason in rejected));self.assertEqual(set(self.geometry(plans)),selected)
            for number, points in self.geometry(plans).items():self.assertEqual(points,expected[number])

    def test_alternating_directions_and_reach_on_each_side(self):
        board, fp = self.fixture(37)
        plans, rejected = self.plan(board,pattern='Perimeter alternating inward / outward',length=1,stagger_pitch=.4)
        self.assertFalse(rejected);self.assertEqual(len(plans),32)
        for plan in plans:
            normal, _, _, index, _ = bank(fp,plan.pad,p)
            reach = p.ToMM((plan.end.x-plan.start.x)*normal[0]+(plan.end.y-plan.start.y)*normal[1])
            self.assertAlmostEqual(reach,-1.4 if index%2 else 1,places=5)

    def test_exposed_pad_rejects_inward_routes_without_flipping_them(self):
        board, fp = self.fixture()
        net=p.NETINFO_ITEM(board,'EP');board.Add(net)
        ep=p.PAD(fp);ep.SetNumber('EP');ep.SetAttribute(p.PAD_ATTRIB_SMD)
        ep.SetShape(p.PAD_SHAPE_RECT);ep.SetSize(fixture.PerimeterExpansionTests.xy(5,5))
        ep.SetPosition(fp.GetPosition());ep.SetNet(net)
        layers=p.LSET();layers.AddLayer(p.F_Cu);ep.SetLayerSet(layers);fp.Add(ep)
        plans, rejected = self.plan(board,pattern='Perimeter alternating inward / outward')
        self.assertEqual(len(plans),16);self.assertEqual(len(rejected),17)
        self.assertTrue(any('center/exposed pad' in reason for reason in rejected))
        self.assertTrue(any('copper' in reason for reason in rejected))
        for plan in plans:
            _, _, _, index, _ = bank(fp,plan.pad,p)
            self.assertEqual(index%2,0)
        self.assertFalse(list(board.GetTracks()))

    def test_inward_keepout_and_other_layer_via_obstacles_are_checked(self):
        for kind in ('keepout','back-copper'):
            board, fp = self.fixture()
            if kind == 'keepout':
                zone=p.ZONE(board);zone.SetIsRuleArea(True);zone.SetLayer(p.F_Cu)
                zone.SetDoNotAllowTracks(True);zone.SetDoNotAllowVias(True)
                outline=zone.Outline();outline.NewOutline()
                for x,y in ((17,17),(23,17),(23,23),(17,23)):outline.Append(p.FromMM(x),p.FromMM(y))
                board.Add(zone)
            else:
                net=p.NETINFO_ITEM(board,'BLOCK');board.Add(net)
                obstacle=p.PAD(fp);obstacle.SetNumber('BLOCK');obstacle.SetAttribute(p.PAD_ATTRIB_SMD)
                obstacle.SetPosition(fp.GetPosition());obstacle.SetSize(fixture.PerimeterExpansionTests.xy(5,5))
                obstacle.SetShape(p.PAD_SHAPE_RECT);obstacle.SetNet(net)
                layers=p.LSET();layers.AddLayer(p.B_Cu);obstacle.SetLayerSet(layers);fp.Add(obstacle)
            plans,rejected=self.plan(board,pattern='Perimeter alternating inward / outward',pad_filter='[0-9]*')
            self.assertEqual(len(plans),16);self.assertEqual(len(rejected),16)
            self.assertTrue(all(('keepout' if kind=='keepout' else 'via clearance') in reason for reason in rejected))

    def test_grid_and_heading_overrides_and_adaptive_are_rejected(self):
        board, fp = self.fixture()
        for options in (dict(angle_mode='Board absolute'),dict(offset_x=.1),dict(routing_mode='Adaptive'),dict(pair_mode='Auto differential pairs')):
            plans,rejected=self.plan(board,**options)
            self.assertFalse(plans);self.assertTrue(rejected)
        next(iter(fp.Pads())).SetPosition(fixture.PerimeterExpansionTests.xy(23,18.25))
        plans,rejected=self.plan(board)
        self.assertTrue(any('Multiple pad rows' in reason for reason in rejected))


if __name__=='__main__':unittest.main()
