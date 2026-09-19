"""Ordered mixed fanouts on real KiCad pads, copper and generated items."""
import json
import tempfile
import unittest
from pathlib import Path
from wayricad_runtime.routing import FanoutPlanner, plan_fanout, plan_document, fanout_items
from wayricad_runtime.fanout_groups import validate_groups
from wayricad_runtime.geometry import board_fingerprint
import test_advanced_fanout as fixture
pcbnew=fixture.pcbnew


class GroupSchemaTests(unittest.TestCase):
    def test_invalid_nested_options_and_duplicate_names_fail(self):
        for groups in ([{'name':'A','settings':{'scope':'All SMD pads'}}],
                       [{'name':'A','match':{'typo':'*'}}],
                       [{'name':'A'},{'name':'A'}], [{'name':'Defaults'}]):
            with self.assertRaises(ValueError):validate_groups(groups,'defaults',FanoutPlanner.defaults)


@unittest.skipIf(pcbnew is None,'KiCad native Python required')
class NativeGroupTests(unittest.TestCase):
    setUp=fixture.AdvancedFanoutTests.setUp
    pos=staticmethod(fixture.AdvancedFanoutTests.pos)
    pad=fixture.AdvancedFanoutTests.pad
    plan=fixture.AdvancedFanoutTests.plan

    def test_mixed_via_custom_angle_and_default_in_one_plan(self):
        self.pad('VDD',22,18);self.pad('CLOCK',22,22);self.pad('DATA',18,20)
        settings={'pattern':'Radial outward','add_vias':False,'groups':[
            {'name':'Power','match':{'net':'V*','ref':'u1','pad':'1'},'settings':{'output_mode':'Via-in-pad','via_diameter':.5,'via_drill':.25}},
            {'name':'Clock','match':{'net':'CLOCK'},'settings':{'pattern':'Custom-angle spread','escape_angle':30,'length':2,'escape_layer':'B.Cu'}}]}
        before=board_fingerprint(self.board)
        document=plan_document('fanout',self.board,pcbnew,settings)
        self.assertFalse(document['rejected'])
        records={p['net']:p for p in document['candidates']}
        self.assertFalse(records['VDD']['add_track']);self.assertTrue(records['VDD']['add_via'])
        self.assertEqual(records['CLOCK']['pattern'],'Custom-angle spread');self.assertEqual(records['CLOCK']['layer'],'B.Cu')
        self.assertTrue(records['CLOCK']['start_via']);self.assertEqual(records['DATA']['group_name'],'Defaults')
        self.assertEqual(document['unmatched_count'],1)
        plans,_=plan_fanout(self.board,pcbnew,settings)
        self.assertEqual(len(fanout_items(self.board,pcbnew,plans)),4)
        self.assertEqual(board_fingerprint(self.board),before)

    def test_first_match_wins_and_global_filter_limits_groups(self):
        self.pad('A',22,18);self.pad('B',22,22)
        groups=[{'name':'First','match':{'pad':'1'},'settings':{'output_mode':'Via-in-pad'}},
                {'name':'Catch all','settings':{'length':3}}]
        plans,rejected=self.plan(groups=groups,net_filter='A')
        self.assertFalse(rejected);self.assertEqual(len(plans),1);self.assertEqual(plans[0].group_name,'First');self.assertFalse(plans[0].add_track)

    def test_unmatched_modes_are_explicit(self):
        self.pad('A',22,20)
        document=plan_document('fanout',self.board,pcbnew,{'groups':[{'name':'Other','match':{'net':'B'}}],'unmatched':'skip'})
        self.assertFalse(document['candidates']);self.assertEqual(document['skipped_count'],1);self.assertIn('unmatched',document['rejected'][0])
        with self.assertRaisesRegex(ValueError,'Unmatched'):self.plan(groups=[{'name':'Other','match':{'net':'B'}}],unmatched='error')
        plans,_=self.plan(groups=[],unmatched='skip');self.assertFalse(plans)

    def test_cross_group_clearance_uses_larger_requirement(self):
        self.pad('A',15,20);self.pad('B',17,17)
        groups=[{'name':'Wide clearance','match':{'net':'A'},'settings':{'angle_mode':'Board absolute','escape_angle':0,'length':4,'clearance':.8}},
                {'name':'Narrow clearance','match':{'net':'B'},'settings':{'angle_mode':'Board absolute','escape_angle':90,'length':2.5,'clearance':.1}}]
        plans,rejected=self.plan(groups=groups)
        self.assertEqual([p.pad.GetNetname() for p in plans],['A']);self.assertIn('generated copper collision',rejected[0])
        groups[0]['settings']['clearance']=.1
        plans,rejected=self.plan(groups=groups)
        self.assertEqual(len(plans),2);self.assertFalse(rejected)

    def test_pair_split_between_rules_rejects_both_polarities(self):
        self.pad('TX_P',22,19.5);self.pad('TX_N',22,20.5)
        groups=[{'name':'Positive','match':{'net':'TX_P'},'settings':{'pair_mode':'Auto differential pairs'}},
                {'name':'Negative','match':{'net':'TX_N'},'settings':{'output_mode':'Via-in-pad'}}]
        plans,rejected=self.plan(groups=groups)
        self.assertFalse(plans);self.assertEqual(len(rejected),2);self.assertTrue(all('different groups' in r for r in rejected))

    def test_pair_collision_with_prior_group_rejects_whole_pair(self):
        self.pad('TX_P',22,19.5);self.pad('TX_N',22,20.5);self.pad('BLOCK',27,20.2)
        groups=[{'name':'Existing escape','match':{'net':'BLOCK'},'settings':{'angle_mode':'Board absolute','escape_angle':180,'length':3.5}},
                {'name':'Pair','match':{'net':'TX_*'},'settings':{'pair_mode':'Auto differential pairs'}}]
        plans,rejected=self.plan(groups=groups)
        self.assertEqual([p.pad.GetNetname() for p in plans],['BLOCK'])
        self.assertEqual(len(rejected),2)
        self.assertTrue(all('differential pair rejected' in r for r in rejected))

    def test_saved_netclass_rule_applies_exact_group_dimensions(self):
        self.pad('VDD',22,20)
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'board.kicad_pcb';self.board.SetFileName(str(filename))
            filename.with_suffix('.kicad_pro').write_text(json.dumps({'net_settings':{'classes':[{'name':'Power','track_width':.35,'via_diameter':.7,'via_drill':.3,'clearance':.2}],'netclass_assignments':{'VDD':['Power']}}}))
            plans,rejected=self.plan(groups=[{'name':'Power','match':{'netclass':'Power'},'settings':{'use_netclass_rules':True}}])
            self.assertFalse(rejected);self.assertEqual(plans[0].width,pcbnew.FromMM(.35))
