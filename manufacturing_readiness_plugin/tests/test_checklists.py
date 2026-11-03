"""Portable vendor-rule and checklist evidence contracts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manufacturing_readiness_plugin import checklists as c


def profile():
    return dict(schema=c.PROFILE_SCHEMA, id='example-standard', name='Example reviewed limits',
                vendor='Example', service='Standard', revision='1',
                process=dict(board_type='rigid', copper_oz=[1], layers=[2, 4]),
                sources=[dict(id='capabilities', url='https://example.com/capabilities', title='Published capabilities',
                              retrieved='2026-11-03', verified='2026-11-03')],
                rules=[dict(id='track', title='Minimum track', category='DRC', backend='native_drc',
                            constraint='track_width', unit='mm', minimum=.15, maximum=None,
                            source_ids=['capabilities']),
                       dict(id='assembly', title='Assembler review', category='DFA', backend='manual',
                            constraint=None, unit=None, minimum=None, maximum=None, source_ids=[])])


class ChecklistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_root = Path(__file__).resolve().parents[2] / '.validation' / 'checklist-tests'
        cls.temporary_root.mkdir(parents=True, exist_ok=True)

    def test_profile_and_checklist_round_trip_preserves_evidence_waivers(self):
        value = c.new_checklist(profile())
        value = c.add_manual_evidence(value, 'assembly', 'a' * 64, 'Assembler checked orientation.', author='Engineer')
        value = c.set_waiver(value, 'track', 'a' * 64, 'Approved local exception.', 'Engineer')
        value = c.record_run(value, 'a' * 64, [dict(rule_id='track', status='FAIL', message='0.12 mm'),
                                             dict(rule_id='assembly', status='PASS', message='Reviewed')])
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            path = Path(directory) / 'checklist.json'
            c.save_checklist(path, value)
            self.assertEqual(value, c.load_checklist(path))
            c.save_profile(path, profile())
            self.assertEqual(profile(), c.load_profile(path))
        state = c.checklist_state(value, 'a' * 64)
        self.assertFalse(state['passed'])
        self.assertEqual(state['results'][0]['status'], 'FAIL')
        self.assertTrue(state['results'][0]['waiver_current'])
        self.assertEqual(state['results'][1]['status'], 'PASS')

    def test_board_and_profile_change_invalidate_run_and_evidence(self):
        value = c.new_checklist(profile())
        value = c.add_manual_evidence(value, 'assembly', 'a' * 64, 'Checked')
        value = c.record_run(value, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='')])
        self.assertFalse(c.checklist_state(value, 'a' * 64)['stale'])
        self.assertTrue(c.checklist_state(value, 'b' * 64)['stale'])
        value['profile']['rules'][0]['minimum'] = .2
        self.assertTrue(c.checklist_state(value, 'a' * 64)['stale'])
        value = c.record_run(value, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='')])
        self.assertEqual(c.checklist_state(value, 'a' * 64)['results'][1]['status'], 'UNKNOWN')

    def test_manual_pass_needs_current_evidence(self):
        value = c.record_run(c.new_checklist(profile()), 'a' * 64,
                             [dict(rule_id='assembly', status='PASS', message='Imported result')])
        self.assertEqual(c.checklist_state(value, 'a' * 64)['results'][1]['status'], 'UNKNOWN')

    def test_missing_result_stays_unknown(self):
        value = c.record_run(c.new_checklist(profile()), 'a' * 64, [])
        self.assertEqual([row['status'] for row in c.checklist_state(value, 'a' * 64)['results']], ['UNKNOWN', 'UNKNOWN'])

    def test_waiver_does_not_make_pass(self):
        value = c.set_waiver(c.new_checklist(profile()), 'track', 'a' * 64, 'Reviewed exception', 'Engineer')
        value = c.record_run(value, 'a' * 64, [dict(rule_id='track', status='PASS', message='')])
        self.assertFalse(c.checklist_state(value, 'a' * 64)['passed'])

    def test_native_preview_enforces_scope_and_omits_manual_rules(self):
        context = dict(board_type='rigid', copper_oz=1, layers=4)
        result = c.compile_native_rules(profile(), context)
        self.assertEqual(result['compiled_rule_ids'], ['track'])
        self.assertIn('(constraint track_width (min 0.15mm))', result['text'])
        self.assertEqual(result['omitted'][0]['rule_id'], 'assembly')
        for context in (dict(board_type='rigid', copper_oz=2, layers=4),
                        dict(board_type='rigid', copper_oz=True, layers=4),
                        dict(board_type='rigid', copper_oz=1, layers=None)):
            with self.assertRaises(ValueError):
                c.compile_native_rules(profile(), context)

    def test_unknown_scope_and_extra_applicability_not_broadened(self):
        value = profile()
        value['process']['copper_oz'] = None
        with self.assertRaises(ValueError):
            c.compile_native_rules(value, dict(board_type='rigid', copper_oz=1, layers=4))
        value = profile()
        value['rules'][0]['applicability'] = dict(layer='outer')
        result = c.compile_native_rules(value, dict(board_type='rigid', copper_oz=1, layers=4))
        self.assertEqual(result['compiled_rule_ids'], [])

    def test_unverified_source_cannot_compile(self):
        value = profile()
        value['sources'][0]['verified'] = None
        self.assertEqual(c.compile_native_rules(value, dict(board_type='rigid', copper_oz=1, layers=4))['compiled_rule_ids'], [])

    def test_duplicate_unconditional_native_constraints_cannot_shadow_limits(self):
        value = profile()
        duplicate = deepcopy(value['rules'][0])
        duplicate.update(id='track-maximum', title='Maximum track width', minimum=None, maximum=1.)
        value['rules'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'last matching constraint'):
            c.compile_native_rules(value, dict(board_type='rigid', copper_oz=1, layers=4))
        value['rules'][0]['maximum'] = 1.
        value['rules'].pop()
        self.assertIn('(min 0.15mm) (max 1mm)',
                      c.compile_native_rules(value, dict(board_type='rigid', copper_oz=1, layers=4))['text'])

    def test_omitted_conditions_do_not_shadow_compiled_native_rule(self):
        value = profile()
        conditional = deepcopy(value['rules'][0])
        conditional.update(id='inner-track', applicability=dict(layer='inner'))
        value['rules'].append(conditional)
        result = c.compile_native_rules(value, dict(board_type='rigid', copper_oz=1, layers=4))
        self.assertEqual(result['compiled_rule_ids'], ['track'])
        self.assertTrue(any(row['rule_id'] == 'inner-track' for row in result['omitted']))

    def test_material_scope_requires_matching_material(self):
        value = profile()
        value['process']['material'] = 'FR4'
        context = dict(board_type='rigid', copper_oz=1, layers=4)
        with self.assertRaises(ValueError):
            c.compile_native_rules(value, context)
        with self.assertRaises(ValueError):
            c.compile_native_rules(value, dict(context, material='PTFE'))
        self.assertEqual(c.compile_native_rules(value, dict(context, material='FR4'))['compiled_rule_ids'], ['track'])

    def test_copper_basis_and_inner_weight_require_exact_selected_scope(self):
        value = profile()
        value['process'].update(copper_basis='vendor_order_option', inner_copper_oz=[.5])
        context = dict(board_type='rigid', copper_oz=1, layers=4)
        for selected in (context, dict(context, copper_basis='vendor_order_option'),
                         dict(context, copper_basis='finished', inner_copper_oz=.5),
                         dict(context, copper_basis='starting', inner_copper_oz=.5),
                         dict(context, copper_basis='vendor_order_option', inner_copper_oz=1),
                         dict(context, copper_basis='vendor_order_option', inner_copper_oz=None),
                         dict(context, copper_basis='vendor_order_option', inner_copper_oz=True)):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    c.compile_native_rules(value, selected)
        selected = dict(context, copper_basis='vendor_order_option', inner_copper_oz=.5)
        self.assertEqual(c.compile_native_rules(value, selected)['compiled_rule_ids'], ['track'])
        value['process']['inner_copper_oz'] = None
        with self.assertRaises(ValueError):
            c.compile_native_rules(value, selected)

    def test_invalid_copper_basis_and_inner_weight_scope_rejected(self):
        for scope in (dict(copper_basis='unknown'), dict(copper_basis=None), dict(copper_basis=[]),
                      dict(inner_copper_oz=[True]), dict(inner_copper_oz=[0]),
                      dict(inner_copper_oz=[float('nan')]), dict(inner_copper_oz=[])):
            with self.subTest(scope=scope):
                value = profile(); value['process'].update(scope)
                with self.assertRaises(ValueError):
                    c.validate_profile(value)

    def test_typed_copper_context_round_trip_and_stale_manual_binding(self):
        value = profile()
        value['process'].update(copper_basis='finished', inner_copper_oz=[.5, 1])
        context = dict(board_type='rigid', copper_oz=1, layers=4, copper_basis='finished', inner_copper_oz=.5)
        document = c.new_checklist(value, selected_context=context)
        document = c.add_manual_evidence(document, 'assembly', 'a' * 64, 'Supplier approved selected copper stack.')
        document = c.record_run(document, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='Reviewed')])
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            path = Path(directory) / 'copper-context.json'
            c.save_checklist(path, document)
            restored = c.load_checklist(path)
        self.assertEqual(restored['selected_context'], context)
        self.assertEqual(c.checklist_state(restored, 'a' * 64)['results'][1]['status'], 'PASS')
        restored['selected_context']['inner_copper_oz'] = 1
        self.assertTrue(c.checklist_state(restored, 'a' * 64)['stale'])
        restored = c.record_run(restored, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='Old copper evidence')])
        self.assertEqual(c.checklist_state(restored, 'a' * 64)['results'][1]['status'], 'UNKNOWN')

    def test_equivalent_numeric_context_keeps_run_and_manual_evidence_current(self):
        value = profile()
        value['process'].update(copper_basis='finished', inner_copper_oz=[1], thickness_mm=[1])
        context = dict(board_type='rigid', copper_oz=1, layers=4, copper_basis='finished', inner_copper_oz=1, thickness_mm=1)
        document = c.new_checklist(value, selected_context=context)
        document = c.add_manual_evidence(document, 'assembly', 'a' * 64, 'Quote checked')
        document = c.set_waiver(document, 'track', 'a' * 64, 'Reviewed exception', 'Engineer')
        document = c.record_run(document, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='Checked')])
        document['selected_context'] = dict(context, copper_oz=1., layers=4., inner_copper_oz=1., thickness_mm=1.)
        state = c.checklist_state(document, 'a' * 64)
        self.assertFalse(state['stale'])
        self.assertEqual(state['results'][1]['status'], 'PASS')
        self.assertTrue(state['results'][0]['waiver_current'])
        document['selected_context']['layers'] = 2
        self.assertTrue(c.checklist_state(document, 'a' * 64)['stale'])

    def test_context_canonicalization_preserves_unknowns_strings_and_other_keys(self):
        value = dict(copper_oz=1, inner_copper_oz=None, layers=4., material='FR4 ', quote='001',
                     custom=dict(number=1), thickness_mm=None)
        actual = c.canonical_context(value)
        self.assertIsInstance(actual['copper_oz'], float)
        self.assertIsInstance(actual['layers'], int)
        self.assertEqual(actual['material'], 'FR4 ')
        self.assertEqual(actual['quote'], '001')
        self.assertIsNone(actual['inner_copper_oz'])
        self.assertIsNone(actual['thickness_mm'])
        self.assertEqual(actual['custom'], dict(number=1))
        self.assertIsInstance(actual['custom']['number'], int)
        self.assertIsInstance(value['copper_oz'], int)
        self.assertEqual(c.canonical_context({}), {})

    def test_context_canonicalization_rejects_invalid_numeric_types(self):
        for value in (dict(copper_oz=True), dict(inner_copper_oz='1'), dict(thickness_mm=0),
                      dict(copper_oz=float('inf')), dict(inner_copper_oz=float('nan')),
                      dict(layers=True), dict(layers=2.5), dict(layers='2')):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    c.canonical_context(value)

    def test_thickness_and_finish_scope_require_exact_selected_values(self):
        value = profile()
        value['process'].update(thickness_mm=[.8, 1.6], finish=['ENIG'])
        context = dict(board_type='rigid', copper_oz=1, layers=4)
        for selected in (context, dict(context, thickness_mm=1.6),
                         dict(context, thickness_mm=1.2, finish='ENIG'),
                         dict(context, thickness_mm=1.6, finish='HASL'),
                         dict(context, thickness_mm=None, finish='ENIG')):
            with self.assertRaises(ValueError):
                c.compile_native_rules(value, selected)
        self.assertEqual(c.compile_native_rules(value, dict(context, thickness_mm=1.6, finish='ENIG'))['compiled_rule_ids'], ['track'])
        value['process']['finish'] = None
        with self.assertRaises(ValueError):
            c.compile_native_rules(value, dict(context, thickness_mm=1.6, finish='ENIG'))

    def test_selected_context_round_trip_and_change_invalidate_evidence(self):
        context = dict(board_type='rigid', copper_oz=1, layers=4)
        value = c.new_checklist(profile(), selected_context=context)
        value = c.add_manual_evidence(value, 'assembly', 'a' * 64, 'Assembly checked')
        value = c.set_waiver(value, 'track', 'a' * 64, 'Approved exception', 'Engineer')
        value = c.record_run(value, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='Reviewed')])
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            path = Path(directory) / 'context.json'
            c.save_checklist(path, value)
            restored = c.load_checklist(path)
            self.assertEqual(restored['selected_context'], context)
            self.assertFalse(c.checklist_state(restored, 'a' * 64)['stale'])
        value['selected_context']['layers'] = 2
        self.assertTrue(c.checklist_state(value, 'a' * 64)['stale'])
        value = c.record_run(value, 'a' * 64, [dict(rule_id='assembly', status='PASS', message='Old evidence')])
        state = c.checklist_state(value, 'a' * 64)
        self.assertEqual(state['results'][1]['status'], 'UNKNOWN')
        self.assertFalse(state['results'][0]['waiver_current'])

    def test_invalid_selected_context_rejected_on_load_validation(self):
        value = c.new_checklist(profile())
        value['selected_context'] = dict(board_type='rigid', copper_oz=2, layers=4)
        with self.assertRaises(ValueError):
            c.validate_checklist(value)

    def test_malformed_thickness_and_finish_scopes_rejected(self):
        for scope in (dict(thickness_mm=[0]), dict(thickness_mm=[True]),
                      dict(thickness_mm=[float('inf')]), dict(finish=[]),
                      dict(finish=['ENIG', 'ENIG']), dict(finish=[''])):
            value = profile(); value['process'].update(scope)
            with self.assertRaises(ValueError):
                c.validate_profile(value)

    def test_invalid_limits_units_duplicates_and_sources_rejected(self):
        mutations = [lambda p: p['rules'][0].update(minimum=float('nan')),
                     lambda p: p['rules'][0].update(minimum=10 ** 400),
                     lambda p: p['rules'][0].update(minimum=True),
                     lambda p: p['rules'][0].update(minimum=.3, maximum=.2),
                     lambda p: p['rules'][0].update(unit='mil'),
                     lambda p: p['rules'][0].update(source_ids=[]),
                     lambda p: p['rules'][0].update(source_ids=[{}]),
                     lambda p: p['rules'].append(deepcopy(p['rules'][0])),
                     lambda p: p['sources'][0].update(url='https://user:password@example.com/'),
                     lambda p: p.update(unrecognized=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = profile(); mutation(value)
                with self.assertRaises(ValueError):
                    c.validate_profile(value)

    def test_invalid_result_status_and_unknown_rule_rejected(self):
        for rule, status in [('missing', 'PASS'), ('track', 'WAIVED'), ('track', 'unknown'), ([], 'PASS'), ('track', {})]:
            with self.assertRaises(ValueError):
                c.record_run(c.new_checklist(profile()), 'a' * 64, [dict(rule_id=rule, status=status, message='')])

    def test_malformed_duplicate_and_oversized_json_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            path = Path(directory) / 'checklist.json'
            for payload in (b'{}', b'{"schema":1,"schema":2}', b'{"value":NaN}', b'\xff'):
                path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    c.load_checklist(path)
            with patch.object(c, 'MAX_DOCUMENT_BYTES', 10):
                path.write_bytes(b' ' * 11)
                with self.assertRaises(ValueError):
                    c.load_checklist(path)

    def test_interrupted_atomic_write_preserves_destination(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            path = Path(directory) / 'checklist.json'
            path.write_text('existing', encoding='utf-8')
            with patch.object(c.os, 'replace', side_effect=OSError('Interrupted')):
                with self.assertRaises(OSError):
                    c.save_checklist(path, c.new_checklist(profile()))
            self.assertEqual(path.read_text(encoding='utf-8'), 'existing')
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
