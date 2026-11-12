"""Partition references and fixed-column/native IPC regression fixtures.

The retained native record strings below are unchanged excerpts from the
public KiCad 10 PIC programmer demo exported by KiCad 10.0.6. They contain
no private design identifiers. Generated analytical fixtures are independent
of the parser's column slicing and cover the documented exporter layout.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manufacturing_readiness_plugin import fab_compare as fab


NATIVE_RECORDS = [
    '317/CLOCK-RB6       VIA        MD0236PA00X+050250Y+017000X0630Y0000R000S3',
    '317VCC              C1    -1    D0472PA00X+019000Y+029450X0945Y0945R180S0',
    '317GND              C1    -2    D0472PA00X+009157Y+029450X0945Y0000R180S0',
    '367N/C              P101        D1693UA00X+006000Y+007000X1693Y0000R000S0',
    '327VCC              JP1   -1          A02X+033515Y+022000X0118Y0118R000S1',
]


def terminal(reference, pin, net, **extra):
    return dict(reference=reference, pin=pin, net=net, **extra)


def normalized(records, **extra):
    return dict(schema=fab.INPUT_SCHEMA, units='mm', terminals=records, **extra)


def ipc_record(net='GND', reference='U1', pin='1', code='317', x=100, y=-200,
               midpoint=False, padded=False):
    # Exporter's fixed fields: op 3, signal 14, gap 3, ref 6, sep 1,
    # pin 4, midpoint 1, hole 6, access 3, XY 8+8, dimensions 5+5, rotation 4.
    hole = '      ' if code == '327' else 'D0100U' if code == '367' else 'D0100P'
    value = (f'{code}{net:<14}   {reference:<6}{"-" if pin else " "}{pin:<4}'
             f'{"M" if midpoint else " "}{hole}A00X{x:+07d}Y{y:+07d}X0200Y0000R000')
    return value + (' S0      ' if padded else 'S0')


def ipc(records, units='CUST 0', code='00', header=(), end=True):
    return '\n'.join([f'P  CODE {code}', f'P  UNITS {units}', 'P  arrayDim   N',
                      *header, *records, *(['999'] if end else [])])+'\n'


class FabCompareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TEMP'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def load(self, value):
        self.serial += 1
        path = self.root/f'netlist-{self.serial}.txt'
        data = json.dumps(value).encode() if isinstance(value, dict) else value.encode('ascii')
        path.write_bytes(data)
        return fab.load_netlist(path)

    def compare(self, a, b, confirm=True):
        return fab.compare_netlists(self.load(normalized(a)), self.load(normalized(b)), confirm)

    def test_nine_design_nets_merge_into_one_observed_short_group(self):
        names = ['GND']+[f'8FORCE{i}' for i in range(8)]
        a = [terminal(f'J{i}', str(pin), net) for i, net in enumerate(names) for pin in (1, 2)]
        b = [dict(t, net='168') for t in a]
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['summary']['short_groups'], 1)
        self.assertEqual(result['summary']['open_groups'], 0)
        self.assertEqual(set(result['shorts'][0]['design_nets']), set(names))
        self.assertEqual(result['shorts'][0]['observed_net'], '168')
        self.assertEqual(len(result['shorts'][0]['endpoints']), 18)
        self.assertEqual(len(result['shorts'][0]['design_groups']), 9)
        json.dumps(result, allow_nan=False)

    def test_renumbered_partitions_match_without_name_correspondence(self):
        a = [terminal('U1', '1', '/Long/full/original/GND'), terminal('R1', '2', '/Long/full/original/GND'),
             terminal('U1', '2', 'POWER')]
        b = [dict(t, net='42' if t['net'] == 'POWER' else '168') for t in a]
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'MATCH')
        self.assertFalse(result['fabrication_verified'])
        self.assertEqual(result['summary']['matched_pins'], 3)

    def test_split_is_one_open_group(self):
        a = [terminal('J1', str(i), 'GND') for i in range(1, 5)]
        b = [dict(t, net='100' if i < 2 else '200') for i, t in enumerate(a)]
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(len(result['opens']), 1)
        self.assertEqual(result['opens'][0]['observed_nets'], ['100', '200'])
        self.assertEqual(result['opens'][0]['design_net'], 'GND')
        self.assertEqual(len(result['opens'][0]['endpoints']), 4)

    def test_short_and_open_are_both_preserved(self):
        a = [terminal('U1', '1', 'A'), terminal('U1', '2', 'A'), terminal('U2', '1', 'B')]
        b = [terminal('U1', '1', '100'), terminal('U1', '2', '200'), terminal('U2', '1', '100')]
        result = self.compare(a, b)
        self.assertEqual((len(result['shorts']), len(result['opens'])), (1, 1))

    def test_missing_extra_pins_are_unknown_not_a_false_open_or_match(self):
        a = [terminal('U1', str(i), 'GND') for i in range(1, 4)]
        b = [terminal('U1', str(i), '168') for i in range(1, 3)]+[terminal('X1', '1', '168')]
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['summary']['missing_pins'], 1)
        self.assertEqual(result['summary']['extra_pins'], 1)
        self.assertEqual(result['shorts'], [])
        self.assertEqual(result['opens'], [])
        self.assertEqual(result['coverage']['missing_pins'], [dict(reference='U1', pin='3')])

    def test_reference_pin_matching_is_case_sensitive_and_never_name_only(self):
        result = self.compare([terminal('U1', 'A1', 'GND')], [terminal('u1', 'a1', 'GND')])
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['summary']['matched_pins'], 0)

    def test_unconnected_terminals_are_independent_singletons(self):
        a = [terminal('J1', '1', None), terminal('J1', '2', 'N/C')]
        b = [terminal('J1', '1', '168'), terminal('J1', '2', '169')]
        self.assertEqual(self.compare(a, b)['status'], 'MATCH')
        b[1]['net'] = '168'
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(len(result['shorts']), 1)
        self.assertEqual(len(result['shorts'][0]['design_groups']), 2)

    def test_observed_unconnected_splits_expected_net(self):
        a = [terminal('J1', str(i), 'GND') for i in (1, 2)]
        result = self.compare(a, [dict(t, net=None) for t in a])
        self.assertEqual(len(result['opens']), 1)

    def test_independence_requires_explicit_confirmation(self):
        a = [terminal('U1', '1', 'A')]
        b = [terminal('U1', '1', '168')]
        result = self.compare(a, b, confirm=False)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertTrue(any(i['code'] == 'independence_unconfirmed' for i in result['issues']))
        with self.assertRaises(ValueError):
            fab.compare_netlists(self.load(normalized(a)), self.load(normalized(b)), 1)

    def test_identical_sources_or_semantics_cannot_match(self):
        model = self.load(normalized([terminal('U1', '1', 'A')]))
        self.assertEqual(fab.compare_netlists(model, model, True)['status'], 'UNKNOWN')
        other = self.load(normalized([terminal('U1', '1', 'A')], provenance={'origin': 'cam'}))
        result = fab.compare_netlists(model, other, True)
        self.assertFalse(result['independence']['identical_source'])
        self.assertTrue(result['independence']['identical_normalized_content'])
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_proven_short_overrides_missing_or_incomplete_coverage(self):
        a = self.load(normalized([terminal('U1', '1', 'A'), terminal('U1', '2', 'B'),
                                  terminal('U1', '3', 'C'), terminal('', '4', 'bad')]))
        b = self.load(normalized([terminal('U1', '1', '168'), terminal('U1', '2', '168')]))
        result = fab.compare_netlists(a, b)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['summary']['short_groups'], 1)
        self.assertFalse(result['summary']['complete'])

    def test_duplicate_and_conflicting_assignments_exclude_endpoint(self):
        for net in ('A', 'B'):
            a = self.load(normalized([terminal('U1', '1', 'A'), terminal('U1', '1', net), terminal('U2', '1', 'A')]))
            b = self.load(normalized([terminal('U1', '1', '168'), terminal('U2', '1', '168')]))
            self.assertFalse(a['complete'])
            self.assertEqual(a['coverage']['duplicate_records'], 1)
            self.assertEqual([t['reference'] for t in a['terminals']], ['U2'])
            self.assertEqual(fab.compare_netlists(a, b, True)['status'], 'UNKNOWN')

    def test_native_export_records_and_decimil_conversion(self):
        model = self.load(ipc(NATIVE_RECORDS))
        self.assertTrue(model['complete'], model['issues'])
        self.assertEqual(model['coverage']['accepted_terminals'], 3)
        self.assertEqual(model['coverage']['ignored_vias'], 1)
        self.assertEqual(model['coverage']['ignored_mechanical'], 1)
        c1 = next(t for t in model['terminals'] if t['reference'] == 'C1' and t['pin'] == '1')
        self.assertAlmostEqual(c1['x_mm'], 48.26)
        self.assertAlmostEqual(c1['y_mm'], 74.803)
        self.assertEqual(model['source']['units'], 'decimil (0.00254 mm)')

    def test_padded_80_column_modern_records(self):
        record = ipc_record(padded=True)
        self.assertEqual(len(record), 80)
        model = self.load(ipc([record], header=['P  VER   IPC-D-356A', 'P  IMAGE PRIMARY']))
        self.assertTrue(model['complete'], model['issues'])
        self.assertEqual(model['terminals'][0]['y_mm'], -.508)

    def test_nname_retains_full_original_display_names(self):
        alias = 'M0001'
        name = '/Power/ground_return/complete_original'
        header = f'P  NNAME{alias:<5} {name:<58}'.ljust(80)
        model = self.load(ipc([ipc_record(net=alias)], header=[header]))
        self.assertTrue(model['complete'], model['issues'])
        self.assertEqual(model['terminals'][0]['net_name'], name)

    def test_conflicting_aliases_cannot_invent_two_distinct_reference_nets(self):
        headers = [f'P  NNAME{alias:<5} /same/original'.ljust(80) for alias in ('M0001', 'M0002')]
        model = self.load(ipc([ipc_record(net='M0001'), ipc_record(net='M0002', pin='2')], header=headers))
        self.assertFalse(model['complete'])
        self.assertEqual(model['terminals'], [])
        self.assertTrue(any(i['code'] == 'conflicting_aliases' for i in model['issues']))

    def test_blank_signal_is_not_an_unconnected_assignment(self):
        model = self.load(ipc([ipc_record(net='')]))
        self.assertFalse(model['complete'])
        self.assertEqual(model['terminals'], [])
        self.assertTrue(any(i['code'] == 'missing_net' for i in model['issues']))

    def test_full_width_identity_and_net_fields_are_ambiguous(self):
        for record in (ipc_record(reference='U12345'), ipc_record(pin='1000'), ipc_record(net='12345678901234')):
            model = self.load(ipc([record]))
            self.assertFalse(model['complete'])
            self.assertEqual(model['terminals'], [])
            self.assertEqual(model['coverage']['ambiguous_records'], 1)

    def test_blank_component_pin_is_unknown_but_vias_can_be_counted(self):
        model = self.load(ipc([ipc_record(reference='P3', pin=''), ipc_record(reference='VIA', pin='', midpoint=True)]))
        self.assertEqual(model['coverage']['ignored_unidentified'], 1)
        self.assertEqual(model['coverage']['ignored_vias'], 1)
        self.assertFalse(model['complete'])
        self.assertEqual(model['terminals'], [])

    def test_empty_and_only_vias_never_pass(self):
        for text in ('', ipc([]), ipc([ipc_record(reference='VIA', pin='', midpoint=True)])):
            model = self.load(text)
            self.assertFalse(model['complete'])
            self.assertEqual(fab.compare_netlists(model, model, True)['status'], 'UNKNOWN')

    def test_units_code_records_end_and_transforms_are_not_guessed(self):
        cases = [ipc([ipc_record()], units='CUST 1'), ipc([ipc_record()], code='01'),
                 ipc([ipc_record()], end=False), ipc([ipc_record(), '307unsupported']),
                 ipc([ipc_record()], header=['P  IMAGE MIRRORED']),
                 ipc([ipc_record()], header=['P  ROTATION 90']),
                 ipc([ipc_record()])+'317after end\n']
        for text in cases:
            with self.subTest(text=text):
                model = self.load(text)
                self.assertFalse(model['complete'])
                self.assertEqual(fab.compare_netlists(model, model, True)['status'], 'UNKNOWN')

    def test_malformed_records_and_coordinates_are_incomplete(self):
        good = ipc_record()
        cases = [good[:60], good[:42]+'+nan000'+good[49:], good.replace('X+000100', 'X0000100'),
                 good[:26]+' '+good[27:], good+'trailing', good.replace('R000', 'R999')]
        for record in cases:
            with self.subTest(record=record):
                model = self.load(ipc([record]))
                self.assertFalse(model['complete'])
                self.assertEqual(model['coverage']['invalid_records'], 1)
                self.assertEqual(model['terminals'], [])

    def test_clamped_coordinates_are_disclosed(self):
        model = self.load(ipc([ipc_record(x=999999)]))
        self.assertFalse(model['complete'])
        self.assertTrue(any(i['code'] == 'coordinate_clamp' for i in model['issues']))

    def test_duplicate_parameters_aliases_and_records_are_not_accepted_as_complete(self):
        alias = 'P  NNAMEM0001 Source'.ljust(80)
        cases = [ipc([ipc_record()], header=['P  UNITS CUST 0']),
                 ipc([ipc_record(net='M0001')], header=[alias, alias]),
                 ipc([ipc_record(), ipc_record()])]
        for text in cases:
            model = self.load(text)
            self.assertFalse(model['complete'])

    def test_strict_json_rejects_duplicate_unknown_nonfinite_and_deep_values(self):
        cases = ['{"schema":1,"schema":2}', '{"x":NaN}', '{"x":1e999}',
                 '{"x":'+'['*20+'0'+']'*20+'}', json.dumps(dict(normalized([]), surprise=True)),
                 json.dumps(dict(normalized([]), schema='other/v2')),
                 json.dumps(dict(normalized([]), units='inch')), '{"__proto__":{"polluted":true}}']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)

    def test_normalized_coordinates_are_optional_but_strict_pairs(self):
        for extra in ({'x_mm':1}, {'x_mm':True, 'y_mm':0}, {'x_mm':10**500, 'y_mm':0}, {'x_mm':'2', 'y_mm':0}):
            model = self.load(normalized([terminal('U1', '1', 'GND', **extra)]))
            self.assertFalse(model['complete'])
        model = self.load(normalized([terminal('U1', '1', 'GND', x_mm=-1, y_mm=2)]))
        self.assertTrue(model['complete'])

    def test_bounds_and_control_characters(self):
        with patch.object(fab, 'MAX_BYTES', 8), self.assertRaisesRegex(ValueError, '16 MiB'):
            self.load(normalized([]))
        with patch.object(fab, 'MAX_RECORDS', 1), self.assertRaisesRegex(ValueError, '100000'):
            self.load(normalized([terminal('U1', '1', 'A'), terminal('U1', '2', 'A')]))
        with patch.object(fab, 'MAX_NODES', 2), self.assertRaisesRegex(ValueError, 'node/depth'):
            self.load(normalized([]))
        with self.assertRaisesRegex(ValueError, 'control'):
            self.load(ipc([ipc_record()]).replace('\n', '\v'))

    def test_actual_source_hash_sealed_model_and_path_api(self):
        value = normalized([terminal('U1', '1', 'GND')], provenance={'origin':'design', 'producer':'Fixture'})
        model = self.load(value)
        self.assertEqual(model['source']['sha256'], hashlib.sha256(json.dumps(value).encode()).hexdigest())
        self.assertEqual(model['provenance']['origin'], 'design')
        changed = copy.deepcopy(model); changed['terminals'][0]['net'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'changed'):
            fab.compare_netlists(model, changed, True)
        path = self.root/'other.json'; path.write_text(json.dumps(normalized([terminal('U1', '1', '168')])))
        self.assertEqual(fab.compare_netlists(model, path, True)['status'], 'MATCH')

    def test_large_net_uses_groups_not_pairwise_pin_cliques(self):
        size = 10000
        a = [terminal('J1', str(i), 'GND') for i in range(size)]
        b = [terminal('J1', str(i), '168') for i in range(size)]
        result = self.compare(a, b)
        self.assertEqual(result['status'], 'MATCH')
        self.assertEqual(result['summary']['matched_pins'], size)
        self.assertEqual(result['shorts'], [])

    @unittest.skipUnless(os.environ.get('WAYRICAD_NATIVE_D356_FIXTURE'), 'native IPC fixture not selected')
    def test_installed_native_fixture_never_self_verifies(self):
        model = fab.load_netlist(os.environ['WAYRICAD_NATIVE_D356_FIXTURE'])
        self.assertGreater(model['coverage']['accepted_terminals'], 50)
        self.assertGreater(model['coverage']['ignored_vias'], 0)
        self.assertGreater(model['coverage']['ignored_mechanical'], 0)
        self.assertEqual(fab.compare_netlists(model, model, True)['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
