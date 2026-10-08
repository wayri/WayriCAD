import math
import tempfile
import unittest
from pathlib import Path
from signal_integrity_advisor_plugin.measurement import PathMeasurement
from signal_integrity_advisor_plugin.quick_si import screen,html_report
from signal_integrity_advisor_plugin.cli import write_report


class QuickSITests(unittest.TestCase):
    def path(self,**kwargs):
        values=dict(status='ok',length_mm=299.792458,impedance_valid=True,impedance_ohm=50.,propagation_delay_ns=2.)
        values.update(kwargs)
        return PathMeasurement('SIGNAL','U1.1','J1.1',**values)

    def test_matched_resistive_endpoints_have_no_reflection(self):
        r=screen(self.path(),source_ohm=50,load_ohm=50,rise_ns=10,frequency_mhz=100)
        self.assertEqual(r['status'],'SCREENED');self.assertEqual(r['source_reflection'],0);self.assertEqual(r['load_reflection'],0)
        self.assertAlmostEqual(r['electrical_length_deg'],72);self.assertEqual(r['round_trip_ns'],4)
        self.assertEqual(r['first_load_step_per_source_step'],.5);self.assertEqual(r['series_match_candidate_ohm'],0)

    def test_open_and_short_load_limits_and_series_candidate(self):
        opened=screen(self.path(),source_ohm=20)
        self.assertEqual(opened['load_reflection'],1);self.assertEqual(opened['series_match_candidate_ohm'],30)
        self.assertAlmostEqual(opened['first_load_step_per_source_step'],100/70)
        shorted=screen(self.path(),source_ohm=20,load_ohm=0)
        self.assertEqual(shorted['load_reflection'],-1);self.assertEqual(shorted['first_load_step_per_source_step'],0)
        self.assertIsNone(screen(self.path(),source_ohm=100)['series_match_candidate_ohm'])

    def test_partial_totals_never_presented_as_complete_delay(self):
        r=screen(self.path(status='partial',impedance_valid=False,propagation_delay_ns=1.))
        self.assertEqual(r['status'],'INCOMPLETE');self.assertIsNone(r['delay_ns']);self.assertIsNone(r['z0_ohm']);self.assertIsNone(r['source_reflection'])
        assumed=screen(self.path(status='partial',impedance_valid=False),epsilon_eff=4,z0_ohm=60)
        self.assertAlmostEqual(assumed['delay_ns'],2);self.assertEqual(assumed['z0_ohm'],60)
        self.assertIn('User-assumed',assumed['delay_source']);self.assertIn('User-assumed',assumed['z0_source'])
        self.assertEqual({'COMPLETE_DELAY_UNAVAILABLE','UNIFORM_Z0_UNAVAILABLE'},
                         {item['code'] for item in r['blockers']})

    def test_automatic_timing_keeps_reference_and_via_blockers(self):
        path=self.path(status='partial',impedance_valid=False)
        path.screening_delay_ns=2.1
        path.screening_model='Ideal saved-stackup timing; via dielectric travel'
        path.screening_notes=['Continuous ideal reference planes assumed.']
        path.blockers=[dict(code='VIA_DISCONTINUITY_UNMODELED',message='unknown reflection',action='field model')]
        report=screen(path)
        self.assertEqual(report['status'],'APPROXIMATE')
        self.assertEqual(report['delay_ns'],2.1)
        self.assertIsNone(report['z0_ohm'])
        self.assertIsNone(report['source_reflection'])
        self.assertIn('VIA_DISCONTINUITY_UNMODELED',{b['code'] for b in report['blockers']})
        self.assertNotIn('COMPLETE_DELAY_UNAVAILABLE',{b['code'] for b in report['blockers']})
        override=screen(path,epsilon_eff=4,z0_ohm=50)
        self.assertEqual(override['status'],'SCREENED')
        self.assertAlmostEqual(override['delay_ns'],2)

    def test_report_shows_valid_sections_without_inventing_uniform_impedance(self):
        path=self.path(status='partial',impedance_valid=False)
        path.segments=[dict(kind='track',layer='F.Cu',length_mm=10,resistance_ohm=.1,impedance_ohm=45,model='microstrip'),
                       dict(kind='via',layer='F.Cu',length_mm=1,resistance_ohm=.01,impedance_ohm=None,model='barrel'),
                       dict(kind='track',layer='B.Cu',length_mm=20,resistance_ohm=.2,impedance_ohm=55,model='microstrip')]
        report=screen(path)
        self.assertEqual(report['route_summary']['modeled_impedance_length_mm'],30)
        self.assertEqual(report['route_summary']['modeled_impedance_min_ohm'],45)
        self.assertEqual(report['route_summary']['modeled_impedance_max_ohm'],55)
        self.assertIsNone(report['z0_ohm'])
        rendered=html_report(report)
        self.assertEqual(rendered.count('data:image/png;base64,'),3)
        self.assertIn('Section impedance along route',rendered)
        self.assertIn('Routed sections',rendered)
        self.assertIn('barrel',html_report(report))

    def test_nonfinite_automatic_timing_does_not_become_a_result(self):
        path=self.path(status='partial',impedance_valid=False)
        path.screening_delay_ns=float('nan');path.screening_z0_ohm=float('inf')
        report=screen(path)
        self.assertIsNone(report['delay_ns']);self.assertIsNone(report['z0_ohm'])
        self.assertEqual(report['status'],'INCOMPLETE')

    def test_local_endpoint_reflections_use_separate_section_impedance(self):
        path=self.path(status='partial',impedance_valid=False)
        path.segments=[dict(kind='track',layer='F.Cu',length_mm=10,resistance_ohm=.1,impedance_ohm=50,model='microstrip'),
                       dict(kind='via',layer='F.Cu',length_mm=1,impedance_ohm=None),
                       dict(kind='track',layer='B.Cu',length_mm=10,resistance_ohm=.1,impedance_ohm=None,screening_z0_ohm=60,screening_model='ideal plane')]
        report=screen(path,source_ohm=20,load_ohm=60)
        self.assertAlmostEqual(report['endpoint_screen']['source']['reflection'],-30/70)
        self.assertEqual(report['endpoint_screen']['source']['series_match_candidate_ohm'],30)
        self.assertEqual(report['endpoint_screen']['receiver']['reflection'],0)
        self.assertIsNone(report['source_reflection'])
        self.assertIsNone(report['z0_ohm'])

    def test_path_blockers_are_preserved_with_actions(self):
        path=self.path(status='partial',impedance_valid=False)
        path.blockers=[{'code':'STACKUP_DIELECTRIC_MISSING','message':'missing','action':'define stackup'}]
        report=screen(path)
        blocker=next(item for item in report['blockers'] if item['code']=='STACKUP_DIELECTRIC_MISSING')
        self.assertEqual('define stackup',blocker['action'])
        self.assertIn('STACKUP_DIELECTRIC_MISSING',html_report(report))

    def test_disconnected_route_cannot_be_overridden_into_result(self):
        r=screen(self.path(status='disconnected'),epsilon_eff=4,z0_ohm=50)
        self.assertEqual(r['status'],'UNRESOLVED');self.assertIsNone(r['delay_ns']);self.assertIsNone(r['load_reflection'])

    def test_nonfinite_and_nonphysical_inputs_rejected(self):
        for settings in ({'rise_ns':0},{'rise_ns':float('nan')},{'load_ohm':float('inf')},{'z0_ohm':0},{'source_ohm':-1},{'epsilon_eff':.9},{'frequency_mhz':-1},{'rise_ns':None}):
            with self.subTest(settings=settings),self.assertRaises(ValueError):screen(self.path(),**settings)

    def test_html_is_offline_escaped_and_design_outputs_protected(self):
        path=self.path();path.notes=['<script>unsafe</script>'];r=screen(path,terminal_count=3)
        html=html_report(r)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert',html);self.assertIn('click to pin a probe',html);self.assertIn('branches/stubs',html)
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'board.kicad_pcb';source.write_text('original')
            with self.assertRaises(ValueError):write_report(source,html,source,'.html')
            self.assertEqual(source.read_text(),'original')
            report=Path(temp)/'report.html';write_report(report,html,source,'.html');self.assertEqual(report.read_text(encoding='utf-8'),html)


if __name__=='__main__':unittest.main()
