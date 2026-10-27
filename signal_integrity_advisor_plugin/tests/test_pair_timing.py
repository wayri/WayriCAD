"""Analytical propagation-phase matching checks; no KiCad runtime required."""
import unittest
from signal_integrity_advisor_plugin.pair_timing import pair_timing
from signal_integrity_advisor_plugin.protocol_suite import screen_suite
from signal_integrity_advisor_plugin.protocol_view import html_report
from signal_integrity_advisor_plugin.cli import parser


def route(role, delay, group='lane0'):
    return dict(schema='wayricad.quick-si/v1', status='APPROXIMATE', board_sha256='abc',
                suite_role=role, suite_group=group, delay_ns=delay,
                delay_source='User-assumed effective permittivity over the complete resolved path',
                path=dict(status='ok',net_name=group+'_'+role,start_pad='U1.'+role,end_pad='J1.'+role))


class PairTimingTests(unittest.TestCase):
    def test_analytical_signed_phase_and_lane_mean(self):
        paths=[route('P',1),route('N',1.125),route('P',2,'lane1'),route('N',2.125,'lane1')]
        result=pair_timing(paths,frequency_hz=1e9)
        a,b=result['pairs']
        self.assertEqual(a['signed_skew_ps'],125)
        self.assertEqual(a['phase_mismatch_deg'],-45)
        self.assertEqual(a['mean_delay_ns'],1.0625)
        self.assertEqual(b['lane_skew_ps'],1000)
        self.assertEqual(b['lane_phase_deg'],-360)
        self.assertEqual(a['status'],'ESTIMATED')
        reverse=pair_timing(paths,frequency_hz=1e9,reference_group='lane1')
        self.assertEqual(reverse['pairs'][0]['lane_skew_ps'],-1000)

    def test_zero_delay_and_unknown_frequency(self):
        row=pair_timing([route('P',0),route('N',0)])['pairs'][0]
        self.assertEqual(row['signed_skew_ps'],0)
        self.assertIsNone(row['phase_mismatch_deg'])
        self.assertEqual(row['mean_delay_ns'],0)

    def test_wrap_and_polarity(self):
        row=pair_timing([route('P',2),route('N',.5)],frequency_hz=1e9)['pairs'][0]
        self.assertEqual(row['phase_mismatch_deg'],540)
        self.assertEqual(row['wrapped_phase_mismatch_deg'],-180)
        self.assertEqual(row['signed_skew_ps'],-1500)

    def test_missing_or_invalid_evidence_stays_unknown(self):
        for field,value in [('delay_ns',None),('delay_ns',float('nan')),('delay_ns',True),('delay_source','unavailable'),('board_sha256',''),('path',None),('status','BLOCKED')]:
            with self.subTest(field=field,value=value):
                a,b=route('P',1),route('N',1.1);b[field]=value
                row=pair_timing([a,b],frequency_hz=1e9)['pairs'][0]
                self.assertEqual(row['status'],'UNKNOWN')
                self.assertIsNone(row['signed_skew_ps'])
        row=pair_timing([route('P',1),route('P',1),route('N',1)])['pairs'][0]
        self.assertEqual(row['status'],'UNKNOWN')

    def test_revision_and_net_guards(self):
        a,b=route('P',1),route('N',1.1);b['board_sha256']='other'
        self.assertEqual(pair_timing([a,b])['pairs'][0]['status'],'BLOCKED')
        b['board_sha256']='abc';b['path']['net_name']=a['path']['net_name']
        self.assertEqual(pair_timing([a,b])['pairs'][0]['status'],'UNKNOWN')

    def test_duplicate_route_cannot_create_second_lane(self):
        a,b=route('P',1),route('N',1.1)
        c=route('P',2,'lane1');c['path']=dict(a['path'])
        rows=pair_timing([a,b,c,route('N',2.1,'lane1')])['pairs']
        self.assertTrue(all(row['status']=='BLOCKED' for row in rows))

    def test_invalid_inputs_and_overflow(self):
        for frequency in (0,-1,True,float('inf'),float('nan'),10**1000):
            with self.subTest(frequency=frequency):
                with self.assertRaises(ValueError):pair_timing([],frequency_hz=frequency)
        with self.assertRaises(ValueError):pair_timing([route('P',1)],reference_group='missing')
        with self.assertRaises(ValueError):pair_timing([route('P',0),route('N',1e307)],frequency_hz=1e308)
        with self.assertRaises(ValueError):pair_timing([route('P',1)]*65)

    def test_suite_html_and_cli_integration(self):
        paths=[route('P',1,'<lane>'),route('N',1.125,'<lane>')]
        result=screen_suite('lvds',paths,timing_frequency_hz=1e9)
        self.assertEqual(result['pair_timing']['pairs'][0]['phase_mismatch_deg'],-45)
        document=html_report(result)
        self.assertIn('Differential pair delay and phase matching',document)
        self.assertIn('&lt;lane&gt;',document)
        self.assertNotIn('<b><lane>',document)
        args=parser().parse_args(['suite','--profile','lvds','--reports','p.json','n.json','--timing-frequency-mhz','1000','--timing-reference-group','lane0'])
        self.assertEqual(args.timing_frequency_mhz,1000)
        self.assertEqual(args.timing_reference_group,'lane0')


if __name__=='__main__':unittest.main()
