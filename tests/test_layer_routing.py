"""Layer routing contracts, including persistence, stale inputs and ownership."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace
from protocol_constraint_composer_plugin.constraint_studio.model import Rule, Constraint
from protocol_constraint_composer_plugin.constraint_studio import routing_profiles as rp
from protocol_constraint_composer_plugin.studio_model import mutation

BOARD = Path(__file__).resolve().parents[1]/'protocol_constraint_composer_plugin/examples/workflow_demo/workflow_demo.kicad_pcb'
STACK = '''(stackup
 (layer "F.Cu" (type "copper") (thickness 0.035))
 (layer "dielectric 1" (type "prepreg") (thickness 0.2) (epsilon_r 4.2))
 (layer "In1.Cu" (type "copper") (thickness 0.035))
 (layer "dielectric 2" (type "core") (thickness 1.0) (epsilon_r 4.2))
 (layer "In2.Cu" (type "copper") (thickness 0.035))
 (layer "dielectric 3" (type "prepreg") (thickness 0.3) (epsilon_r 4.2))
 (layer "B.Cu" (type "copper") (thickness 0.035)))'''


def fixture():
    w=Workspace.load(BOARD)
    w.board_text=w.board_text.replace('(setup (pad_to_mask_clearance 0))','(setup (pad_to_mask_clearance 0) '+STACK+')')
    w.board_text=w.board_text.replace('(31 "B.Cu" signal)','(1 "In1.Cu" signal) (2 "In2.Cu" signal) (31 "B.Cu" signal)')
    w.refresh_board_context()
    w.project['net_settings']['classes'].append(dict(name='CAN',clearance=.1))
    w.project['net_settings'].setdefault('netclass_patterns',[]).append(dict(pattern='CAN*',netclass='CAN'))
    w.project.setdefault('board',{}).setdefault('design_settings',{})['rules']={'min_track_width':.05,'min_clearance':.05}
    return w


def profile(w):
    return dict(name='CAN routing',netclass='CAN',type='differential',target_impedance=120,
                geometry_tolerance=5,restrict_layers=True,reviewed=True,stack_hash=rp.stack_hash(w),
                rows=[dict(signal_layer='F.Cu',bottom_reference_layer='In1.Cu',top_reference_layer='',width=.2,gap=.18),
                      dict(signal_layer='B.Cu',bottom_reference_layer='In2.Cu',top_reference_layer='',width=.3,gap=.25)])


class LayerRoutingTests(unittest.TestCase):
    def setUp(self): self.w=fixture();self.data=profile(self.w)
    def change(self, data=None):
        return mutation(self.w,'routing_profile',dict(data or self.data,revision=self.w.state()))

    def test_native_profile_and_layer_rules_persist_with_plugin_closed(self):
        staged=self.change();p=rp.native_profiles(staged)[0]
        self.assertEqual([200000,300000],[r['width'] for r in p['layer_entries']])
        self.assertEqual([180000,250000],[r['diff_pair_gap'] for r in p['layer_entries']])
        self.assertEqual('UNDEFINED',p['layer_entries'][0]['top_reference_layer'])
        self.assertFalse(p['enable_time_domain_tuning'])
        self.assertEqual('CAN routing',staged.project['net_settings']['classes'][-1]['tuning_profile'])
        self.assertEqual({'F.Cu','B.Cu','In1.Cu','In2.Cu'},{r.layer for r in staged.document.rules if r.name.startswith('CAN routing')})
        self.assertFalse(rp.issues(staged))
        with tempfile.TemporaryDirectory() as tmp:
            for ext,raw in staged.outputs().items():Path(tmp,'board'+ext).write_bytes(raw)
            loaded=Workspace.load(Path(tmp,'board.kicad_pcb'))
            self.assertEqual(p,rp.native_profiles(loaded)[0]);self.assertFalse(rp.issues(loaded))

    def test_no_live_file_or_original_workspace_changes(self):
        before=self.w.state();raw=BOARD.read_bytes();self.change()
        self.assertEqual(before,self.w.state());self.assertEqual(raw,BOARD.read_bytes())

    def test_managed_update_idempotent_preserves_other_profiles_and_rules(self):
        self.w.project['tuning_profiles']={rp.KEY:[{'profile_name':'external','opaque':True}], 'unknown':42}
        self.w.document.rules.append(Rule('Area exception',"A.enclosedByArea('escape')",constraints=[Constraint('track_width',{'opt':'.1mm'})]))
        self.w=self.change();again=self.change()
        self.assertEqual(self.w.state(),again.state())
        self.assertEqual(42,again.project['tuning_profiles']['unknown'])
        self.assertEqual('Area exception',again.document.rules[-1].name)
        self.assertEqual({'profile_name':'external','opaque':True},rp.native_profiles(again)[0])

    def test_stale_stackup_reported_after_reload(self):
        self.w=self.change();self.w.board_text=self.w.board_text.replace('(thickness 0.2)','(thickness 0.21)');self.w.refresh_board_context()
        self.assertIn('STALE',rp.issues(self.w)[0].message)
        with self.assertRaisesRegex(ValueError,'Stackup changed'):self.change()

    def test_independently_changed_profile_or_rules_not_overwritten(self):
        for native in (True,False):
            with self.subTest(native=native):
                self.w=fixture();self.w=self.change()
                if native:rp.native_profiles(self.w)[0]['layer_entries'][0]['width']=999
                else:next(r for r in self.w.document.rules if r.name=='CAN routing / F.Cu').constraints[0].values['opt']='.111mm'
                with self.assertRaisesRegex(ValueError,'independently'):self.change()

    def test_invalid_geometry_rejected_atomically(self):
        for value in ('nan',float('inf'),0,-1,.001):
            with self.subTest(value=value):
                d=copy.deepcopy(self.data);d['rows'][0]['width']=value
                with self.assertRaises(ValueError):self.change(d)
        self.assertFalse(rp.native_profiles(self.w))

    def test_missing_stackup_duplicate_layer_missing_review_wrong_class(self):
        for key,value in [('reviewed',False),('netclass','missing'),('rows',[self.data['rows'][0]]*2),('geometry_tolerance',90)]:
            with self.subTest(key=key):
                d=copy.deepcopy(self.data);d[key]=value
                with self.assertRaises(ValueError):self.change(d)
        self.w.board_text=self.w.board_text.replace(STACK,'');self.w.refresh_board_context();self.data['stack_hash']=rp.stack_hash(self.w)
        with self.assertRaises(ValueError):self.change()

    def test_existing_assignment_and_profile_are_preserved(self):
        self.w.project['net_settings']['classes'][-1]['tuning_profile']='Other'
        with self.assertRaisesRegex(ValueError,'another'):self.change()
        self.w.project['net_settings']['classes'][-1].pop('tuning_profile')
        self.w.project['tuning_profiles']={rp.KEY:[{'profile_name':self.data['name']}]}
        with self.assertRaisesRegex(ValueError,'not managed'):self.change()

    def test_estimate_depends_on_layer_height_and_fixed_gap(self):
        values=[rp.estimate(self.w,dict(row=r,type='differential',target_impedance=120)) for r in self.data['rows']]
        self.assertGreater(values[1]['width'],values[0]['width'])
        self.assertEqual(.18,values[0]['gap'])
        self.assertIn('Approximate',values[0]['qualification'])

    def test_intervening_copper_and_asymmetric_estimate_rejected(self):
        d=copy.deepcopy(self.data);d['rows'][0]['bottom_reference_layer']='In2.Cu'
        self.assertEqual('In2.Cu',rp.native_profiles(self.change(d))[0]['layer_entries'][0]['bottom_reference_layer'])
        with self.assertRaisesRegex(ValueError,'intervening'):
            rp.estimate(self.w,dict(row=d['rows'][0],type='differential',target_impedance=120))
        r=dict(signal_layer='In1.Cu',top_reference_layer='F.Cu',bottom_reference_layer='In2.Cu',gap=.2)
        with self.assertRaisesRegex(ValueError,'Asymmetric'):rp.estimate(self.w,dict(row=r,type='differential',target_impedance=120))

    def test_verified_dimensions_allow_internal_single_reference(self):
        d=copy.deepcopy(self.data)
        d['rows']=[dict(signal_layer='In1.Cu',top_reference_layer='',bottom_reference_layer='F.Cu',width=.17,gap=.14)]
        self.assertEqual('In1.Cu',rp.native_profiles(self.change(d))[0]['layer_entries'][0]['signal_layer'])
        with self.assertRaisesRegex(ValueError,'Internal signal layers'):
            rp.estimate(self.w,dict(row=d['rows'][0],type='differential',target_impedance=120))

    def test_single_ended_and_unrestricted_layer_policy(self):
        self.data.update(type='single',restrict_layers=False)
        staged=self.change();p=rp.native_profiles(staged)[0]
        self.assertEqual(0,p['type']);self.assertEqual(0,p['layer_entries'][0]['diff_pair_gap'])
        self.assertEqual(['track_width'],[c.kind for c in next(r for r in staged.document.rules if r.name=='CAN routing / F.Cu').constraints])
        self.assertEqual(2,len(staged.metadata['routing_profiles']['CAN routing']['rule_names']))

    def test_export_contains_routing_validation_in_offline_helper(self):
        staged=self.change()
        with tempfile.TemporaryDirectory() as tmp:
            out=staged.export_bundle(Path(tmp,'export'))
            self.assertTrue((out/'_apply/constraint_studio/routing_profiles.py').is_file())
            self.assertEqual(200000,json.loads((out/BOARD.with_suffix('.kicad_pro').name).read_text())[ 'tuning_profiles'][rp.KEY][0]['layer_entries'][0]['width'])

    def test_native_numeric_format_and_rule_precedence(self):
        from protocol_constraint_composer_plugin.constraint_studio.model import RuleDocument
        doc=RuleDocument.load('(version 1)\n(rule "original" (constraint track_width (min .2mm)) (opaque abc))')
        self.assertIn('(min 0.2mm)',doc.emit());self.assertIn('(opaque abc)',doc.emit())
        doc=RuleDocument.load('(version 1)\n(rule "comment" (condition "A.NetName == \'(min .2mm)\'") # (min .3mm)\n (constraint track_width (min .2mm)))')
        self.assertIn("'(min .2mm)'",doc.emit());self.assertIn('# (min .3mm)',doc.emit())
        self.assertIn('(constraint track_width (min 0.2mm))',doc.emit())
        staged=self.change();names=[r.name for r in staged.document.rules]
        self.assertLess(names.index('Illustrative working dimensions'),names.index('CAN routing / F.Cu'))
        self.assertLess(names.index('CAN routing / F.Cu'),names.index('U1 escape / routing'))

    def test_multiple_protocol_instances_with_exact_net_groups(self):
        original=copy.deepcopy(self.w.project['net_settings'])
        for name,protocol,nets,kind in [('CAN1','CAN',['D1','D2'],'differential'),
                                       ('CAN2','CAN',['D3','D4'],'differential'),
                                       ('DDR1 Data','DDR',['D5','D6','D7'],'single'),
                                       ('Ethernet1','Ethernet',['D8','D9'],'differential')]:
            d=copy.deepcopy(self.data);d.update(name=name,protocol=protocol,scope='nets',nets=nets,type=kind)
            self.w=self.change(d)
        self.assertEqual(4,len(rp.native_profiles(self.w)))
        self.assertEqual(original,self.w.project['net_settings'])
        self.assertFalse(rp.issues(self.w))
        rule=next(r for r in self.w.document.rules if r.name=='CAN1 / F.Cu')
        self.assertIn("A.NetName == 'D1'",rule.condition)
        self.assertNotIn('D3',rule.condition)
        self.assertIn('diff_pair_gap',[c.kind for c in rule.constraints])
        self.assertNotIn('B.NetName',rule.condition)  # native gap DRC evaluates a single item

    def test_net_group_overlap_missing_nets_and_unpaired_nets_rejected(self):
        d=dict(self.data,name='CAN1',scope='nets',nets=['D1','D2'])
        self.w=self.change(d)
        with self.assertRaisesRegex(ValueError,'already assigned'):self.change(dict(d,name='CAN2'))
        with self.assertRaisesRegex(ValueError,'missing'):self.change(dict(d,name='CAN2',nets=['MISSING','D4']))
        with self.assertRaisesRegex(ValueError,'both nets'):self.change(dict(d,name='CAN2',nets=['D4']))

    def test_group_membership_update_remove_and_reload(self):
        d=dict(self.data,name='DDR1',scope='nets',protocol='DDR',type='single',nets=['D1','D2'])
        self.w=self.change(d);d['nets']=['D3'];self.w=self.change(d)
        rule=next(r for r in self.w.document.rules if r.name=='DDR1 / F.Cu')
        self.assertNotIn('D1',rule.condition);self.assertIn('D3',rule.condition)
        with tempfile.TemporaryDirectory() as tmp:
            for ext,raw in self.w.outputs().items():Path(tmp,'board'+ext).write_bytes(raw)
            loaded=Workspace.load(Path(tmp,'board.kicad_pcb'))
            self.assertFalse(rp.issues(loaded));self.assertEqual(['D3'],loaded.metadata['routing_profiles']['DDR1']['nets'])
        changed=mutation(self.w,'routing_remove',dict(name='DDR1',revision=self.w.state()))
        self.assertFalse(rp.native_profiles(changed));self.assertFalse(changed.metadata['routing_profiles'])
        self.assertFalse(any(r.name.startswith('DDR1 /') for r in changed.document.rules))
        self.assertTrue(rp.native_profiles(self.w))

    def test_netclass_overlap_is_rejected_in_both_directions(self):
        d=dict(self.data,name='DDR1',scope='nets',type='single',nets=['D1'])
        self.w.project['net_settings']['classes'][1]['tuning_profile']='external'
        with self.assertRaisesRegex(ValueError,'inherits'):self.change(d)
        self.w.project['net_settings']['classes'][1].pop('tuning_profile')
        self.w=self.change(d)
        with self.assertRaisesRegex(ValueError,'overlaps'):self.change(dict(self.data,netclass='DemoSignals'))

    def test_renamed_net_is_reported(self):
        self.w=self.change(dict(self.data,name='Data',scope='nets',type='single',nets=['D1']))
        self.w.board_text=self.w.board_text.replace('"D1"','"RENAMED"');self.w.refresh_board_context()
        self.assertTrue(any('renamed' in i.message for i in rp.issues(self.w)))


if __name__=='__main__':unittest.main()
