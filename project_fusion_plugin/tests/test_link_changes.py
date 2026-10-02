"""Electrical change severity is independent of net naming and reannotation."""
import copy
import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest

ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_link_changes_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
m=importlib.import_module(PACKAGE+'.link_changes')

def snapshot():
    symbols={key:{'reference':ref,'unit':1,'uuid':key,'sheet_path':'/root','lib_id':'Device:R',
                  'value':'10k','footprint':'R0603','fields':{},'flags':{'on_board':'yes'}}
             for key,ref in [('a','R1'),('b','R2'),('c','R3')]}
    return {'symbols':symbols,'components':{key:{'reference':item['reference'],'value':'10k','footprint':'R0603'} for key,item in symbols.items()},
            'sheets':[{'path':'/root','name':'Root'}], 'nets':[{'name':'SIGNAL','pins':[['a','1'],['b','1']]},
                     {'name':'SECOND','pins':[['c','1']]}], 'board_items':{}}

class LinkChangeTests(unittest.TestCase):
    def test_net_rename_is_not_pin_rewire(self):
        old=snapshot();new=copy.deepcopy(old);new['nets'][0]['name']='RENAMED'
        report=m.compare_snapshots(old,new)
        self.assertEqual(report['major_changes'],0)
        self.assertEqual(report['changes'][0]['category'],'net_label')

    def test_same_name_rewire_flags_every_affected_pin(self):
        old=snapshot();new=copy.deepcopy(old)
        new['nets'][0]['pins']=[['a','1'],['c','1']];new['nets'][1]['pins']=[['b','1']]
        report=m.compare_snapshots(old,new)
        pins=[c for c in report['changes'] if c['category']=='pin_connection']
        self.assertEqual({c['reference'] for c in pins},{'R1','R2','R3'})
        self.assertTrue(report['requires_major_acknowledgement'])

    def test_pin_removal_and_join_are_major(self):
        old=snapshot();new=copy.deepcopy(old)
        new['nets']=[{'name':'ONE','pins':[['a','1'],['b','1'],['c','1']]}]
        self.assertEqual(m.compare_snapshots(old,new)['summary']['pin_connections'],3)
        new['nets'][0]['pins'].remove(['c','1'])
        changes=m.compare_snapshots(old,new)['changes']
        self.assertTrue(any(c.get('pin_removed') for c in changes))

    def test_reannotation_preserves_identity_and_field_edit_is_minor(self):
        old=snapshot();new=copy.deepcopy(old);new['symbols']['a']['reference']='R99';new['components']['a']['reference']='R99'
        new['symbols']['b']['fields']={'MPN':'new'}
        self.assertEqual(m.compare_snapshots(old,new)['major_changes'],0)
        self.assertTrue(all(item['automatic'] for item in m.suggest_auto_links(old,new)))

    def test_footprint_layout_and_hierarchy_are_major(self):
        old=snapshot();new=copy.deepcopy(old);new['symbols']['a']['footprint']='R0805'
        new['board_items']['via1']={'kind':'via','geometry':'changed'}
        new['sheets'].append({'path':'/root/new','name':'Extra'})
        self.assertEqual(m.compare_snapshots(old,new)['major_changes'],3)

    def test_resolved_project_variable_changes_are_detected(self):
        old=snapshot();new=copy.deepcopy(old);new['components']['a']['value']='20k'
        changes=m.compare_snapshots(old,new)['changes']
        self.assertEqual(changes[0]['category'],'resolved_value')

    def test_recreated_symbol_is_review_proposal_only(self):
        old=snapshot();new=copy.deepcopy(old)
        new['symbols']['new']=new['symbols'].pop('a');new['symbols']['new']['uuid']='new'
        proposals=m.suggest_auto_links(old,new)
        self.assertTrue(any(p.get('candidates')==['new'] and not p['automatic'] for p in proposals))

    def test_pin_electrical_type_change_is_major(self):
        old=snapshot();new=copy.deepcopy(old)
        old['symbols']['a']['pin_definitions']=[{'number':'1','electrical_type':'passive'}]
        new['symbols']['a']['pin_definitions']=[{'number':'1','electrical_type':'output'}]
        change=m.compare_snapshots(old,new)['changes'][0]
        self.assertEqual((change['category'],change['severity']),('pin_definition','major'))

    def test_saved_json_snapshot_has_no_false_layout_change(self):
        import json
        old=snapshot();old['board_items']={'fp':{'kind':'footprint','geometry':'same','pad_connections':[('pad','1','net')]}}
        saved=json.loads(json.dumps(old))
        self.assertEqual(m.compare_snapshots(saved,old)['major_changes'],0)

if __name__=='__main__':unittest.main()
