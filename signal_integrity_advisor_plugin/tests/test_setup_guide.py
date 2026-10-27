"""Guided setup retains explicit endpoints/models and bounds timing advice."""
import unittest
from signal_integrity_advisor_plugin.setup_guide import (
    validate_setup, peer_labels, readiness_rows, circuit_timing_suggestion, timing_report_cases)

VALUES=dict(rise_ns='0.5',frequency_mhz='100',source_ohm='20',load_ohm='',
            z0_ohm='',epsilon_eff='',eye_bitrate_mbps='1000',eye_swing_v='1')

class SetupGuideTests(unittest.TestCase):
    def test_empty_models_stay_unknown_and_open_is_retained(self):
        result=validate_setup('DATA','U1.1','J1.2',['U1.1','J1.2'],VALUES,True)
        self.assertEqual(result['values']['z0_ohm'],'')
        self.assertEqual(result['values']['epsilon_eff'],'')
        self.assertEqual(result['values']['load_ohm'],'')
        self.assertEqual((result['start'],result['end']),('U1.1','J1.2'))

    def test_invalid_numbers_roles_and_duplicate_labels_rejected(self):
        for key,value in [('rise_ns','nan'),('rise_ns','0'),('frequency_mhz','-1'),
                          ('source_ohm','inf'),('z0_ohm','0'),('epsilon_eff','.9')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                validate_setup('DATA','U1.1','J1.2',['U1.1','J1.2'],dict(VALUES,**{key:value}),False)
        for labels,source,receiver in [(['U1.1','U1.1','J1.2'],'U1.1','J1.2'),
                                       (['U1.1','J1.2'],'U1.1','U1.1'),
                                       (['U1.1','J1.2'],'U1.1','J9.2')]:
            with self.assertRaises(ValueError):validate_setup('DATA',source,receiver,labels,VALUES,False)

    def test_disabled_eye_input_is_not_used(self):
        validate_setup('DATA','U1.1','J1.2',['U1.1','J1.2'],dict(VALUES,eye_bitrate_mbps='not reviewed'),False)
        with self.assertRaises(ValueError):
            validate_setup('DATA','U1.1','J1.2',['U1.1','J1.2'],dict(VALUES,eye_bitrate_mbps='not reviewed'),True)

    def test_peer_identity_is_physical_not_reference_or_another_net(self):
        rows=[dict(label='U1.1',net='DATA',footprint_uuid='physical1'),
              dict(label='U1.2',net='DATA',footprint_uuid='physical1'),
              dict(label='U1.3',net='GND',footprint_uuid='physical1'),
              dict(label='U1.4',net='DATA',footprint_uuid='physical2')]
        self.assertEqual(peer_labels(rows,'U1.1','DATA'),['U1.2'])
        self.assertEqual(peer_labels(rows+[rows[0]],'U1.1','DATA'),[])
        self.assertEqual(peer_labels([dict(label='U1.1',net='DATA')],'U1.1','DATA'),[])

    def test_blockers_include_next_action_and_topology_limit(self):
        rows=readiness_rows(dict(blockers=[dict(code='NO_Z0',message='Unknown',action='Review stackup')],
                                circuit_topology=dict(complete=False,notes=['Extra pads present'])))
        self.assertIn('Next: Review stackup',rows[0][1])
        self.assertIn('Incomplete',rows[1][1]);self.assertIn(('Channel coverage review','Extra pads present'),rows)
        self.assertEqual(readiness_rows({}),[])

    def test_advice_case_selection_is_explicit_and_cli_is_read_only(self):
        import tempfile,json,hashlib
        from pathlib import Path
        from signal_integrity_advisor_plugin.cli import parser,execute
        completed=dict(schema='wayricad.quick-si/v1',delay_ns=2.,inputs=dict(rise_ns=.5,frequency_mhz=100.))
        study=dict(schema='wayricad.quick-si-study/v1',cases=[dict(id='a',report=completed),dict(id='bad')])
        self.assertEqual(timing_report_cases(study,['a']),(['a'],[completed]))
        for selected in [None,['missing'],['a','a']]:
            with self.assertRaises(ValueError):timing_report_cases(study,selected)
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'route.json';source.write_text(json.dumps(completed),encoding='utf-8')
            before=source.read_bytes();out=Path(directory)/'advice.json'
            args=parser().parse_args(['timing-advice',str(source),'--output',str(out)])
            result=execute(args);self.assertEqual(result['cases'],['route'])
            self.assertEqual(result['report_sha256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(source.read_bytes(),before);self.assertAlmostEqual(result['timestep_ns'],.025)
            self.assertEqual(json.loads(out.read_text())['status'],'ADVICE')
            with self.assertRaises(ValueError):execute(parser().parse_args(['timing-advice',str(source),'--output',str(source)]))

    def test_timing_advice_uses_fastest_edges_longest_period_and_delay(self):
        report=lambda rise,delay,freq:dict(delay_ns=delay,inputs=dict(rise_ns=rise,frequency_mhz=freq))
        result=circuit_timing_suggestion([report(.5,2,100),report(1,20,50)])
        self.assertAlmostEqual(result['timestep_ns'],.025)
        self.assertAlmostEqual(result['duration_ns'],200)
        self.assertAlmostEqual(result['frequency_mhz'],50)
        self.assertEqual(result['estimated_points'],8000)
        for reports in [[],[report(0,2,100)],[report(1,None,100)],[report(1,1,0)],
                        [report(.000001,1,.0001)]]:
            with self.assertRaises(ValueError):circuit_timing_suggestion(reports)

if __name__=='__main__':unittest.main()
