"""Advanced routing regressions, executed with KiCad 10's native Python."""
import math
import unittest
import tempfile
import json
from pathlib import Path
from wayricad_runtime.routing import FanoutPlanner, plan_fanout, fanout_items, plan_document
from wayricad_runtime.fanout_profiles import SIGNAL_PROFILES, profile_defaults
try:
    import pcbnew
except ImportError:
    pcbnew=None


class ProfileTests(unittest.TestCase):
    def test_profiles_are_explicit_geometry_suggestions(self):
        for name in SIGNAL_PROFILES:
            defaults=profile_defaults(name)
            self.assertEqual(defaults['signal_profile'],name)
            self.assertNotIn('width',defaults)
            self.assertNotIn('via_diameter',defaults)
            self.assertTrue(defaults['net_filter'])
        self.assertEqual(profile_defaults('PXI')['pair_mode'],'Independent')
        self.assertEqual(profile_defaults('PXIe')['pair_mode'],'Auto differential pairs')

    def test_profile_defaults_preserve_explicit_settings(self):
        planner=FanoutPlanner(None,None,{'signal_profile':'PCIe','width':0.17,'net_filter':'TX*'})
        self.assertEqual(planner.settings['pair_mode'],'Auto differential pairs')
        self.assertEqual(planner.settings['net_filter'],'TX*')
        self.assertEqual(planner.settings['width'],0.17)

    def test_suffix_styles_are_not_mixed_or_case_folded(self):
        self.assertEqual(FanoutPlanner._pair_key('DQS0P')[0],FanoutPlanner._pair_key('DQS0N')[0])
        self.assertNotEqual(FanoutPlanner._pair_key('USB_P')[0],FanoutPlanner._pair_key('USB-')[0])
        self.assertIsNone(FanoutPlanner._pair_key('USB_p'))
        self.assertEqual(FanoutPlanner._pair_key('/DDR/CK_T')[0],FanoutPlanner._pair_key('/DDR/CK_C')[0])


@unittest.skipIf(pcbnew is None,'KiCad native Python required')
class AdvancedFanoutTests(unittest.TestCase):
    def setUp(self):
        self.board=pcbnew.BOARD()
        for a,b in (((0,0),(40,0)),((40,0),(40,40)),((40,40),(0,40)),((0,40),(0,0))):
            line=pcbnew.PCB_SHAPE(self.board);line.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line.SetStart(self.pos(*a));line.SetEnd(self.pos(*b));line.SetLayer(pcbnew.Edge_Cuts);self.board.Add(line)
        self.fp=pcbnew.FOOTPRINT(self.board);self.fp.SetReference('U1');self.fp.SetPosition(self.pos(20,20));self.board.Add(self.fp)

    @staticmethod
    def pos(x,y):return pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))

    def pad(self,name,x,y,number=None):
        net=pcbnew.NETINFO_ITEM(self.board,name);self.board.Add(net)
        pad=pcbnew.PAD(self.fp);pad.SetNumber(number or str(len(list(self.fp.Pads()))+1))
        pad.SetPosition(self.pos(x,y));pad.SetSize(self.pos(.3,.3));pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        layers=pcbnew.LSET();layers.AddLayer(pcbnew.F_Cu);pad.SetLayerSet(layers);pad.SetNet(net);self.fp.Add(pad)
        return pad

    def plan(self,**settings):
        return plan_fanout(self.board,pcbnew,dict({'add_vias':False,'pattern':'Radial outward'},**settings))

    def test_45_and_custom_angles_on_rotated_footprint(self):
        pad=self.pad('SIGNAL',22,20)
        for rotation in (0,30,90,180):
            self.fp.SetOrientationDegrees(rotation)
            # Native SetOrientation rotates the pad about the footprint center.
            plans,rejected=self.plan(pattern='45-degree spread')
            self.assertFalse(rejected);self.assertEqual(len(plans),1)
            plan=plans[0]
            observed=math.atan2(plan.end.y-plan.start.y,plan.end.x-plan.start.x)
            expected=math.radians(45-rotation)
            self.assertAlmostEqual(math.cos(observed),math.cos(expected),places=5)
            self.assertAlmostEqual(math.sin(observed),math.sin(expected),places=5)
        self.fp.SetOrientationDegrees(0)
        plans,_=self.plan(pattern='Custom-angle spread',escape_angle=30)
        plan=plans[0]
        self.assertAlmostEqual(math.degrees(math.atan2(plan.end.y-plan.start.y,plan.end.x-plan.start.x)),30,places=4)

    def test_absolute_and_relative_angle_modes(self):
        self.pad('SIGNAL',22,20);self.fp.SetOrientationDegrees(90)
        for mode,expected in [('Board absolute',30),('Footprint relative',-60)]:
            plans,rejected=self.plan(angle_mode=mode,escape_angle=30)
            self.assertFalse(rejected)
            p=plans[0]
            self.assertAlmostEqual(math.degrees(math.atan2(p.end.y-p.start.y,p.end.x-p.start.x)),expected,places=4)

    def test_segmented_items_and_document_contain_every_leg(self):
        self.pad('SIGNAL',22,20)
        settings={'pattern':'Straight + angled escape','length':2,'launch_length':.5,'escape_angle':45,'add_vias':False}
        plans,rejected=plan_fanout(self.board,pcbnew,settings)
        self.assertFalse(rejected);self.assertEqual(len(plans[0].path),3)
        self.assertAlmostEqual(plans[0].length_mm,2,places=5)
        items=fanout_items(self.board,pcbnew,plans);self.assertEqual(len(items),2)
        self.assertEqual(items[0].GetEnd(),items[1].GetStart())
        doc=plan_document('fanout',self.board,pcbnew,settings)
        self.assertEqual(len(doc['candidates'][0]['path_mm']),3)
        self.assertAlmostEqual(doc['candidates'][0]['length_mm'],2,places=5)

    def test_obstacle_on_second_leg_rejects_whole_route(self):
        self.pad('SIGNAL',22,20)
        obstacle=self.pad('BLOCK',23.2,20.7)
        plans,rejected=self.plan(net_filter='SIGNAL',pattern='Straight + angled escape',length=2,launch_length=.5)
        self.assertFalse(plans);self.assertIn('copper',rejected[0])

    def test_copper_on_other_layer_does_not_block_traces_but_blocks_vias(self):
        self.pad('SIGNAL',22,20)
        net=pcbnew.NETINFO_ITEM(self.board,'OTHER');self.board.Add(net)
        track=pcbnew.PCB_TRACK(self.board);track.SetStart(self.pos(23.5,19));track.SetEnd(self.pos(23.5,21))
        track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(pcbnew.B_Cu);track.SetNet(net);self.board.Add(track)
        plans,rejected=self.plan();self.assertEqual(len(plans),1);self.assertFalse(rejected)
        plans,rejected=self.plan(add_vias=True);self.assertFalse(plans);self.assertIn('via clearance',rejected[0])

    def test_staggered_rows_alternate_reach(self):
        self.pad('A',22,19);self.pad('B',22,21)
        plans,rejected=self.plan(pattern='Staggered rows',stagger_pitch=.7)
        self.assertFalse(rejected)
        self.assertEqual(sorted(round(p.length_mm,4) for p in plans),[1.5,2.2])

    def pair(self):
        return self.pad('TX_P',22,19.5),self.pad('TX_N',22,20.5)

    def pair_plan(self,**settings):
        values={'pair_mode':'Auto differential pairs','net_filter':'TX_*','angle_mode':'Board absolute',
                'escape_angle':0,'length':3,'add_vias':True}
        values.update(settings)
        return self.plan(**values)

    def test_pair_parallel_gap_via_flare_and_measured_skew(self):
        self.pair()
        plans,rejected=self.pair_plan()
        self.assertFalse(rejected);self.assertEqual(len(plans),2)
        self.assertTrue(plans[0].pair_id);self.assertEqual(plans[0].pair_id,plans[1].pair_id)
        self.assertAlmostEqual(plans[0].length_mm,plans[1].length_mm,places=6)
        self.assertEqual([len(p.path) for p in plans],[4,4])
        self.assertAlmostEqual(abs(plans[0].path[1].y-plans[1].path[1].y)/1e6,.4,places=6)
        self.assertGreaterEqual(abs(plans[0].end.y-plans[1].end.y)/1e6,.8)
        self.assertEqual(len(fanout_items(self.board,pcbnew,plans)),8)

    def test_pair_failure_is_atomic(self):
        self.pair();self.pad('BLOCK',24.8,20.4)
        plans,rejected=self.pair_plan()
        self.assertFalse(plans);self.assertEqual(len(rejected),2)
        self.assertTrue(all('differential pair rejected' in item for item in rejected))

    def test_orphans_ambiguous_and_filtered_mates_reject(self):
        self.pad('TX_P',22,19.5)
        plans,rejected=self.pair_plan();self.assertFalse(plans);self.assertIn('mate',rejected[0])
        self.pad('TX_N',22,20.5)
        plans,rejected=self.pair_plan(net_filter='TX_P');self.assertFalse(plans);self.assertIn('mate',rejected[0])
        self.pad('TX_N',23,22)
        plans,rejected=self.pair_plan();self.assertFalse(plans);self.assertEqual(len(rejected),3)

    def test_pair_skew_and_unequal_transitions_reject(self):
        _,pad=self.pair();pad.SetPosition(self.pos(22.4,20.5))
        plans,rejected=self.pair_plan(max_pair_skew=.01)
        self.assertFalse(plans);self.assertIn('skew',rejected[0])
        pad.SetPosition(self.pos(22,20.5));layers=pcbnew.LSET();layers.AddLayer(pcbnew.B_Cu);pad.SetLayerSet(layers);pad.SetLayer(pcbnew.B_Cu)
        plans,rejected=self.pair_plan(escape_layer='F.Cu')
        self.assertFalse(plans);self.assertIn('transitions',rejected[0])

    def test_saved_netclass_dimensions_are_used_in_review(self):
        self.pad('SIGNAL',22,20)
        with tempfile.TemporaryDirectory() as directory:
            filename=Path(directory)/'board.kicad_pcb';self.board.SetFileName(str(filename))
            filename.with_suffix('.kicad_pro').write_text(json.dumps({'net_settings':{
                'classes':[{'name':'HS','track_width':.15,'via_diameter':.5,'via_drill':.25,'clearance':.1}],
                'netclass_assignments':{'SIGNAL':['HS']}}}))
            plans,rejected=self.plan(netclass_filter='HS',use_netclass_rules=True)
            self.assertFalse(rejected);self.assertEqual(plans[0].width,pcbnew.FromMM(.15))
            self.assertEqual(plans[0].via_diameter,pcbnew.FromMM(.5))

    def test_pair_gap_cannot_bypass_clearance(self):
        self.pair();plans,rejected=self.pair_plan(pair_gap=.1,clearance=.2)
        self.assertFalse(plans);self.assertIn('below configured clearance',rejected[0])

    def test_same_net_existing_via_overlap_is_rejected(self):
        pad=self.pad('SIGNAL',22,20)
        via=pcbnew.PCB_VIA(self.board);via.SetPosition(self.pos(23.5,20))
        via.SetWidth(pcbnew.FromMM(.6));via.SetDrill(pcbnew.FromMM(.3));via.SetNet(pad.GetNet())
        via.SetViaType(pcbnew.VIATYPE_THROUGH);via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);self.board.Add(via)
        plans,rejected=self.plan(add_vias=True)
        self.assertFalse(plans);self.assertIn('existing via overlap',rejected[0])

    def test_pair_offsets_preserve_parallel_lane_gap(self):
        self.pair()
        plans,rejected=self.pair_plan(offset_y=.15,max_pair_skew=1)
        self.assertFalse(rejected);self.assertEqual(len(plans),2)
        for p in plans:self.assertEqual(p.path[1].y,p.path[2].y)
        self.assertAlmostEqual(abs(plans[0].path[1].y-plans[1].path[1].y)/1e6,.4,places=6)

    def test_zero_pair_gap_is_rejected_even_without_general_clearance(self):
        self.pair();plans,rejected=self.pair_plan(pair_gap=0,clearance=0)
        self.assertFalse(plans);self.assertIn('must be positive',rejected[0])

    def test_rotated_four_corner_stays_in_pad_world_quadrant(self):
        self.pad('SIGNAL',22,21);self.fp.SetOrientationDegrees(90)
        plans,rejected=self.plan(pattern='Four-corner outward')
        self.assertFalse(rejected)
        p=plans[0]
        self.assertGreaterEqual(p.end.x,p.start.x)
        self.assertLessEqual(p.end.y,p.start.y)

    def test_second_leg_cannot_leave_board(self):
        self.pad('SIGNAL',38,20)
        plans,rejected=self.plan(pattern='Straight + angled escape',length=4,launch_length=.5)
        self.assertFalse(plans);self.assertIn('edge',rejected[0])

    def test_invalid_angles_and_zero_segment_lengths_are_rejected(self):
        self.pad('SIGNAL',22,20)
        for settings in ({'escape_angle':float('nan')},{'escape_angle':361},{'launch_length':0}):
            with self.assertRaises(ValueError):self.plan(**settings)
        plans,rejected=self.plan(pattern='Straight + angled escape',length=.4,launch_length=.5)
        self.assertFalse(plans);self.assertIn('launch length',rejected[0])


if __name__=='__main__':unittest.main()
