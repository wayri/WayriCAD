"""Independent SI study evidence, explicit roles, isolation and CLI contracts."""
import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from signal_integrity_advisor_plugin.study import cases_from_config,checked_case,run_study
from signal_integrity_advisor_plugin.cli import parser


def case(identifier='a',net='DATA',**changes):
    row={'id':identifier,'net':net,'start':'U1.1','end':'J1.1','reference':'Auto',
         'inputs':{'rise_ns':1.,'source_ohm':20.,'frequency_mhz':100.}}
    row.update(changes);return row


def result(status='SCREENED',**extras):
    return {'status':status,**extras},NS(board_items=[],net_name='DATA',status='ok')


class StudyTests(unittest.TestCase):
    def test_requested_unavailable_eye_keeps_study_incomplete(self):
        report=run_study(object(),{'cases':[case(inputs={'eye_bitrate_mbps':1000})]},
            analyzer=lambda *a,**k:result(eye={'status':'UNAVAILABLE','reason':'missing reference'}))
        self.assertEqual(report['status'],'INCOMPLETE')
        self.assertEqual(report['summary']['unavailable_eyes'],1)

    def test_routes_are_independent_with_exact_inputs(self):
        calls=[]
        def analyze(board,net,start,end,reference,**inputs):
            calls.append((board,net,start,end,reference,inputs));return result()
        board=object();config={'cases':[case(),case('b','CLOCK',start='U1.2',end='J1.2',inputs={'rise_ns':.2,'source_ohm':35.})]}
        report=run_study(board,config,analyzer=analyze)
        self.assertEqual(report['status'],'COMPLETE');self.assertEqual(report['summary'],{'cases':2,'reported':2,'errors':0})
        self.assertEqual(calls[1],(board,'CLOCK','U1.2','J1.2','Auto',{'rise_ns':.2,'source_ohm':35.}))
        self.assertIn('no inter-net coupling',report['model'])
        self.assertEqual(config['cases'][0]['inputs']['rise_ns'],1.)
    def test_one_invalid_case_keeps_other_measured_results(self):
        def analyze(board,net,*args,**kwargs):
            if net=='BAD':raise ValueError('ambiguous terminal')
            return result()
        report=run_study(object(),{'cases':[case('bad','BAD'),case('ok')]},analyzer=analyze)
        self.assertEqual(report['status'],'INCOMPLETE');self.assertEqual(report['summary']['errors'],1)
        self.assertIn('ambiguous',report['cases'][0]['error']);self.assertEqual(report['cases'][1]['status'],'SCREENED')
    def test_source_change_aborts_instead_of_publishing_partial_results(self):
        count=0
        def guard():
            nonlocal count
            count+=1
            if count==3:raise ValueError('project rules changed')
        with self.assertRaisesRegex(ValueError,'project rules changed'):
            run_study(object(),{'cases':[case(),case('b')]},guard=guard,analyzer=lambda *a,**k:result())
    def test_return_nets_and_endpoint_roles_are_passed_to_real_audit_entry(self):
        inputs={'return_nets':['GND'],'return_terminal_ids':['U1.2','J1.2'],'return_terminal_roles':{'source':'U1.2','load':'J1.2'}}
        with patch('signal_integrity_advisor_plugin.quick_si.analyze',return_value=result(return_path={'status':'INCOMPLETE'})) as analyze:
            report=run_study(object(),{'cases':[case(inputs=inputs)]})
        self.assertEqual(analyze.call_args.kwargs,inputs)
        self.assertEqual(report['cases'][0]['return_status'],'INCOMPLETE');self.assertEqual(report['status'],'INCOMPLETE')
    def test_return_warning_cannot_become_complete_status(self):
        report=run_study(object(),{'cases':[case()]},analyzer=lambda *a,**k:result(return_path={'status':'REVIEW'}))
        self.assertEqual(report['status'],'REVIEW')
    def test_missing_direction_never_chooses_first_or_last_terminal(self):
        with patch('signal_integrity_advisor_plugin.quick_si.analyze') as analyze:
            report=run_study(object(),{'cases':[case(start='')]})
        analyze.assert_not_called();self.assertEqual(report['cases'][0]['status'],'ERROR');self.assertIn('direction is never inferred',report['cases'][0]['error'])
    def test_explicit_roles_expand_terminal_ids_without_mutating_input(self):
        original=case(inputs={'return_nets':['GND'],'return_terminal_roles':{'source':'U1.2','load':'J1.2'}})
        inputs=checked_case(original)
        self.assertEqual(inputs['return_terminal_ids'],['U1.2','J1.2'])
        self.assertNotIn('return_terminal_ids',original['inputs'])
    def test_unknown_geometry_stays_incomplete(self):
        report=run_study(object(),{'cases':[case()]},analyzer=lambda *a,**k:result('INCOMPLETE',z0_ohm=None))
        self.assertIsNone(report['cases'][0]['report']['z0_ohm']);self.assertEqual(report['status'],'INCOMPLETE')
    def test_duplicate_ids_and_oversized_study_are_rejected(self):
        for config in ({'cases':[case(),case()]},{'cases':[case(str(i)) for i in range(65)]}):
            with self.assertRaises(ValueError):cases_from_config(config)
    def test_invalid_values_and_return_assignments_fail_per_case(self):
        for inputs in ({'source_ohm':float('nan')},{'rise_ns':True},{'return_nets':['DATA']},{'return_nets':['GND','GND']},{'return_terminal_roles':{'source':'U1.2'}},{'unexpected':1}):
            report=run_study(object(),{'cases':[case(inputs=inputs)]},analyzer=lambda *a,**k:result())
            self.assertEqual(report['cases'][0]['status'],'ERROR',inputs)
    def test_parser_exposes_explicit_return_and_study_inputs(self):
        args=parser().parse_args(['screen','board.kicad_pcb','--net','D','--start','U1.1','--end','J1.1','--return-net','GND','--return-net','AGND','--return-source','U1.2','--return-load','J1.2'])
        self.assertEqual(args.return_net,['GND','AGND']);self.assertEqual(args.return_source,'U1.2')
        args=parser().parse_args(['study','board.kicad_pcb','--config','study.json']);self.assertEqual(args.config.name,'study.json')

try:
    import wx
except ImportError:
    wx=None

@unittest.skipIf(wx is None,'Native wx runtime required')
class StudyUIStalenessTests(unittest.TestCase):
    def test_changed_generation_does_not_show_study_result(self):
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        messages=[];shown=[]
        panel=NS(_closed=False,_job_serial=2,_generation=8,_busy=True,
                 run_button=NS(Enable=lambda:None),cancel_button=NS(Disable=lambda:None),
                 status=NS(SetLabel=messages.append),_show_study=shown.append)
        QuickSIPanel._study_finished(panel,2,7,{}, {'study':{}},None)
        self.assertFalse(shown);self.assertIn('inputs changed',messages[0])
