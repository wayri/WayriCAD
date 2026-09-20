import copy
import json
import unittest
from signal_integrity_advisor_plugin.protocol_profiles import list_profiles, get_profile
from signal_integrity_advisor_plugin.protocol_suite import screen_suite


def route(delay=1, start='U1.1', end='U2.1', role='', group=''):
    return dict(schema='wayricad.quick-si/v1', status='SCREENED',
                path=dict(status='ok', net_name='DATA', start_pad=start, end_pad=end,
                          via_count=0, layer_changes=0,
                          segments=[dict(kind='track', reference_layer='B.Cu', reference_net='GND')]),
                delay_ns=delay, delay_to_rise_ratio=.5, z0_ohm=50,
                delay_source='Complete modeled routed sections and board stackup',
                z0_source='Uniform routed-line approximation from board/reference geometry',
                suite_role=role, suite_group=group)


class ProtocolSuiteTests(unittest.TestCase):
    def test_catalog_unique_serializable_and_independent(self):
        profiles = list_profiles()
        self.assertEqual(len(profiles), len({p['id'] for p in profiles}))
        json.dumps(profiles, allow_nan=False)
        profiles[0]['title'] = 'changed'
        self.assertNotEqual(profiles[0]['title'], get_profile(profiles[0]['id'])['title'])
        self.assertTrue(all(p['references'] for p in profiles))

    def test_rates_units_and_form_factor(self):
        self.assertEqual(8, get_profile('pcie-gen4')['nyquist_GHz'])
        self.assertEqual('GT/s NRZ', get_profile('pcie-gen4')['rate_kind'])
        self.assertEqual(.125, get_profile('rgmii')['nyquist_GHz'])
        self.assertEqual('interface-required', get_profile('m2')['topology'])
        self.assertEqual('sata-6', get_profile('m2-sata-6')['base_profile'])
        self.assertIsNone(get_profile('can-classic')['target_impedance_ohm'])

    def test_empty_unresolved_and_mixed_boards_blocked(self):
        self.assertEqual('BLOCKED', screen_suite('uart', [])['status'])
        self.assertEqual('BLOCKED', screen_suite('m2', [route()])['status'])
        a, b = route(), route(start='U1.2')
        a['board_sha256'], b['board_sha256'] = 'a', 'b'
        self.assertEqual('BLOCKED', screen_suite('uart', [a, b])['status'])
        a['path']['status'] = 'missing'
        self.assertEqual('BLOCKED', screen_suite('uart', [a])['status'])

    def test_user_budget_boundary_and_failure(self):
        budgets = dict(max_delay_ns=1, max_delay_to_rise_ratio=.5)
        self.assertEqual('WITHIN_BUDGET', screen_suite('uart', [route()], budgets=budgets)['status'])
        self.assertEqual('REVIEW', screen_suite('uart', [route(1.01)], budgets=budgets)['status'])
        self.assertEqual('INCOMPLETE', screen_suite('uart', [route()])['status'])

    def test_explicit_pair_skew_and_no_doubled_impedance(self):
        a, b = route(1, role='P', group='lane'), route(1.125, start='U1.2', role='N', group='lane')
        b['path']['net_name']='DATA_N'
        result = screen_suite('pcie-gen4', [a, b], budgets={'max_skew_ps': 125})
        skew = next(c for c in result['checks'] if c['id'] == 'group.lane.skew')
        self.assertEqual(125, skew['measured'])
        self.assertEqual('WITHIN_BUDGET', skew['status'])
        self.assertEqual('UNKNOWN', next(c for c in result['checks'] if c['id'] == 'route.0.impedance')['status'])
        a.pop('suite_role')
        result = screen_suite('pcie-gen4', [a, b])
        self.assertFalse(any(c['id'].endswith('.skew') for c in result['checks']))

    def test_bus_skew_and_assumed_impedance_not_measurement(self):
        a, b = route(role='clock', group='byte'), route(1.2, start='U1.2', role='data', group='byte')
        a['path']['net_name']='CLK'
        a['z0_source'] = 'User-assumed uniform line; discontinuities are not modeled'
        result = screen_suite('ddr4', [a, b], budgets={'max_skew_ps': 100, 'max_impedance_error_percent': 10})
        checks = {c['id']: c for c in result['checks']}
        self.assertEqual('REVIEW', checks['group.byte.skew']['status'])
        self.assertEqual('UNKNOWN', checks['route.0.impedance']['status'])
        self.assertEqual('WITHIN_BUDGET', checks['route.1.impedance']['status'])

    def test_numeric_validation_and_no_mutation(self):
        for value in (True, float('nan'), float('inf'), -1, '2', 10**400):
            with self.assertRaises(ValueError):
                screen_suite('uart', [route()], budgets={'max_delay_ns': value})
        a = route(); original = copy.deepcopy(a)
        screen_suite('uart', [a])
        self.assertEqual(original, a)
        with self.assertRaises(ValueError):
            screen_suite('uart', [a], budgets={'max_delay': 1})

    def test_duplicate_route_cannot_fake_a_pair(self):
        a, b = route(role='P', group='lane'), route(role='N', group='lane')
        self.assertEqual('BLOCKED', screen_suite('lvds', [a, b])['status'])
        b['path']['start_pad'],b['path']['end_pad']=b['path']['end_pad'],b['path']['start_pad']
        self.assertEqual('BLOCKED', screen_suite('lvds', [a, b])['status'])
        b['path']['start_pad']='U3.1'
        self.assertEqual('BLOCKED', screen_suite('lvds', [a, b])['status'])

    def test_optional_eye_rate_evidence(self):
        a = route()
        a['eye'] = dict(status='ILLUSTRATIVE', inputs=dict(bitrate_mbps=5000))
        def check(profile):
            return next(c for c in screen_suite(profile, [a])['checks'] if c['id'].endswith('eye_rate'))
        self.assertEqual('INFO', check('pcie-gen2')['status'])
        self.assertEqual('REVIEW', check('pcie-gen4')['status'])
        self.assertEqual('UNKNOWN', check('i2c-fast')['status'])
        a['eye'] = dict(status='UNAVAILABLE', reason='Incomplete route')
        self.assertEqual('UNKNOWN', check('pcie-gen2')['status'])

    def test_reference_and_transition_missing_evidence(self):
        a = route()
        a['path']['segments'][0]['reference_net'] = ''
        a['path']['via_count'] = 2
        a['path']['layer_changes'] = 2
        checks = {c['id']: c for c in screen_suite('uart', [a])['checks']}
        self.assertEqual('UNKNOWN', checks['route.0.reference_coverage']['status'])
        self.assertEqual('UNKNOWN', checks['route.0.return_transitions']['status'])
        self.assertEqual(2, checks['route.0.return_transitions']['measured'])
        a['path'].pop('segments')
        checks = {c['id']: c for c in screen_suite('uart', [a])['checks']}
        self.assertIsNone(checks['route.0.reference_coverage']['limit'])
        self.assertIsNone(get_profile('i2c-fast')['nyquist_GHz'])

    def test_malformed_json_fields_are_blocked(self):
        for value in ([], {}, '', None, 12):
            a = route(); a['path']['start_pad'] = value
            self.assertEqual('BLOCKED', screen_suite('uart', [a])['status'])
        for value in ({}, None, [1], ['track']):
            a = route(); a['path']['segments'] = value
            self.assertEqual('BLOCKED', screen_suite('uart', [a])['status'])
        for key in ('inputs', 'eye', 'board_sha256', 'suite_role', 'suite_group'):
            a = route(); a[key] = []
            self.assertEqual('BLOCKED', screen_suite('uart', [a])['status'])
        a = route(); a['eye'] = {'inputs': []}
        self.assertEqual('BLOCKED', screen_suite('uart', [a])['status'])

    def test_route_cap_and_boolean_counts(self):
        with self.assertRaisesRegex(ValueError, '64'):
            screen_suite('uart', [route()] * 65)
        a = route(); a['path']['via_count'] = False
        check = next(c for c in screen_suite('uart', [a])['checks'] if c['id'].endswith('return_transitions'))
        self.assertEqual('UNKNOWN', check['status'])


if __name__ == '__main__':
    unittest.main()
