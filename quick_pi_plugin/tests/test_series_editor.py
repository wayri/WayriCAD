import unittest
from types import SimpleNamespace
from unittest.mock import patch

from quick_pi_plugin.console import parse_command
from quick_pi_plugin.series_editor import (SeriesPathDialog, build_command,compatible_components,
    current_pad_group,display_path_command,draft_from_request,grouped_pad_preview,path_from_command,selected_component_references)


INVENTORY={'nets':['VIN','MID','LOAD'],'terminals':[
    {'id':'source','label':'J1.1','net':'VIN'},
    {'id':'d1a','label':'D1.1','net':'VIN'},
    {'id':'d1b','label':'D1.2','net':'MID'},
    {'id':'r1a','label':'R1.1','net':'MID'},
    {'id':'r1b','label':'R1.2','net':'LOAD'},
    {'id':'sink','label':'U1.1','net':'LOAD'}]}


class SeriesEditorModelTests(unittest.TestCase):
    def test_manual_model_edit_keeps_reviewed_parallel_and_pin_groups(self):
        from quick_pi_plugin.tests.test_parallel_parts import inventory
        chosen=inventory()
        data={'schema':1,'source':'J1.1','sink':'U1.1','branches':[
            {'reference':'R1','from_pad':'R11','to_pad':'R12','model':'100m',
             'parallel':[{'footprint_uuid':'r2','model':'200m'}]}]}
        changed=path_from_command('run pi J1.1 R1:50m U1.1',chosen,existing=data)
        self.assertEqual(changed['branches'][0]['parallel'],data['branches'][0]['parallel'])
        self.assertEqual(changed['branches'][0]['model'],'50m')

    def test_compatible_parts_follow_actual_net_chain(self):
        self.assertEqual(compatible_components(INVENTORY,'VIN'),[('D1','MID')])
        self.assertEqual(compatible_components(INVENTORY,'MID',{'D1'}),[('R1','LOAD')])

    def test_editor_builds_same_request_as_console(self):
        command=build_command('J1.1','U1.1',[{'reference':'D1','model':'1V'},
                                             {'reference':'R1','model':'5m'}])
        request=parse_command(command,INVENTORY)
        self.assertEqual([row['id'] for row in request['series']],['D1','R1'])
        self.assertEqual(request['series'][0]['fixed_drop_v'],1.)
        self.assertEqual(request['series'][1]['resistance_ohm'],.005)

    def test_reordered_broken_path_is_rejected(self):
        command=build_command('J1.1','U1.1',[{'reference':'R1','model':'5m'},
                                             {'reference':'D1','model':'1V'}])
        with self.assertRaisesRegex(ValueError,'direction|disconnected'):
            parse_command(command,INVENTORY)

    def test_selected_footprints_are_available_to_editor(self):
        footprint=SimpleNamespace(reference_field=SimpleNamespace(text=SimpleNamespace(value='D1')))
        with patch('quick_pi_plugin.series_editor._editor_selection',return_value=[footprint,footprint]):
            self.assertEqual(selected_component_references('board.kicad_pcb'),['D1'])

    def test_manual_path_roundtrip_preserves_exact_q_current_pads_and_labels(self):
        from quick_pi_plugin.tests.test_series_groups import inventory
        chosen=inventory()
        data=path_from_command('run pi J1.1 Q1.1 100m Q1.3 U1.1',chosen)
        self.assertEqual((data['branches'][0]['from_pad'],data['branches'][0]['to_pad']),('a1','b1'))
        self.assertNotIn('gate',str(data))
        self.assertIn('Q1.1 100m Q1.3',display_path_command(data,chosen))
        self.assertEqual(parse_command(display_path_command(data,chosen),chosen)['series'][0]['id'],'Q1')

    def test_restored_grouped_request_seeds_schema_compatible_draft(self):
        from quick_pi_plugin.tests.test_series_groups import inventory,request
        from quick_pi_plugin.series_editor import parse_saved_path
        chosen=inventory();parsed=request()
        draft=draft_from_request(parsed,chosen)
        assert set(draft)=={'path','editor'}
        assert draft['path']['schema']==1
        assert draft['path']['source_terminals']==['s1','s2']
        assert draft['path']['branches'][0]['from_pads']==['a1','a2']
        assert parse_saved_path(draft['path'],chosen)['series'][0]['from_pads']==['a1','a2']
        preview=grouped_pad_preview(parsed,chosen)
        assert any('Source pads: J1.1, J1.2' in line for line in preview)
        assert any('Stage 1 Q1 incoming pads: Q1.1, Q1.2' in line for line in preview)
        assert all('Q1.5' not in line for line in preview)

    def test_new_current_groups_include_same_net_peers_only_when_selected(self):
        from quick_pi_plugin.tests.test_series_groups import inventory
        rows=inventory()['terminals']
        self.assertEqual(current_pad_group(rows,'a1',True),['a1','a2'])
        self.assertEqual(current_pad_group(rows,'b1',True),['b1','b2'])
        self.assertEqual(current_pad_group(rows,'a1',False),['a1'])
        self.assertNotIn('gate',current_pad_group(rows,'a1',True))

    def test_restored_parallel_request_keeps_reviewed_part_and_model(self):
        from quick_pi_plugin.tests.test_parallel_parts import inventory
        from quick_pi_plugin.series_editor import parse_saved_path
        chosen=inventory()
        original={'schema':1,'source':'J1.1','sink':'U1.1','branches':[
            {'reference':'R1','from_pad':'R11','to_pad':'R12','model':'100m',
             'parallel':[{'footprint_uuid':'r2','model':'200m'}]}]}
        parsed=parse_saved_path(original,chosen)
        draft=draft_from_request(parsed,chosen)
        restored=parse_saved_path(draft['path'],chosen)
        self.assertEqual(restored['series'],parsed['series'])
        self.assertEqual(draft['path']['branches'][0]['parallel'][0]['footprint_uuid'],'r2')

    def test_cancel_returns_draft_with_unrun_branch_and_control_values(self):
        class Choice:
            def __init__(self,value):self.value=value
            def GetSelection(self):return 0
            def GetStringSelection(self):return self.value
            def GetValue(self):return False
        class Text:
            def __init__(self,value):self.value=value
            def GetValue(self):return self.value
        class Dialog:
            destroyed=False
            def ShowModal(self):return 0
            def Destroy(self):self.destroyed=True
        editor=object.__new__(SeriesPathDialog)
        editor.inventory=INVENTORY;editor.wx=SimpleNamespace(ID_OK=1)
        editor.source=Choice('J1.1');editor.sink=Choice('U1.1')
        editor.source_all=Choice('');editor.sink_all=Choice('')
        editor.endpoint_groups={};editor.branches=[{'reference':'D1','model':'1V'}]
        editor.kind=Choice('');editor.component=Choice('');editor.candidates=[('R1','LOAD')]
        editor.values={'r':(None,Text('5m'))};editor.list=Choice('')
        editor.manual=Text('run pi J1.1 D1.1 1V D1.2 U1.1');editor._manual_pending=True
        editor.dialog=Dialog()
        editor.inference=SimpleNamespace(snapshot=lambda:{'query':['J1.1','U1.1',False]})
        editor.batch_setup=SimpleNamespace(snapshot=lambda:{'cases':[{'name':'Retained setup'}]})
        request,draft=editor.show_with_draft()
        self.assertIsNone(request)
        self.assertEqual(draft['path']['branches'][0]['reference'],'D1')
        self.assertEqual(draft['editor']['values']['r'],'5m')
        self.assertTrue(draft['editor']['manual_pending'])
        self.assertEqual(draft['editor']['inference']['query'][0],'J1.1')
        self.assertEqual(draft['editor']['batch']['cases'][0]['name'],'Retained setup')
        self.assertTrue(editor.dialog.destroyed)


if __name__=='__main__':unittest.main()
