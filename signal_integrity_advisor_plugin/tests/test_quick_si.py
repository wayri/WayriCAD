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

    def test_disconnected_route_cannot_be_overridden_into_result(self):
        r=screen(self.path(status='disconnected'),epsilon_eff=4,z0_ohm=50)
        self.assertEqual(r['status'],'UNRESOLVED');self.assertIsNone(r['delay_ns']);self.assertIsNone(r['load_reflection'])

    def test_nonfinite_and_nonphysical_inputs_rejected(self):
        for settings in ({'rise_ns':0},{'rise_ns':float('nan')},{'load_ohm':float('inf')},{'z0_ohm':0},{'source_ohm':-1},{'epsilon_eff':.9},{'frequency_mhz':-1},{'rise_ns':None}):
            with self.subTest(settings=settings),self.assertRaises(ValueError):screen(self.path(),**settings)

    def test_html_is_offline_escaped_and_design_outputs_protected(self):
        path=self.path();path.notes=['<script>unsafe</script>'];r=screen(path,terminal_count=3)
        html=html_report(r)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html);self.assertIn('branches/stubs',html)
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'board.kicad_pcb';source.write_text('original')
            with self.assertRaises(ValueError):write_report(source,html,source,'.html')
            self.assertEqual(source.read_text(),'original')
            report=Path(temp)/'report.html';write_report(report,html,source,'.html');self.assertEqual(report.read_text(encoding='utf-8'),html)


if __name__=='__main__':unittest.main()
