"""Offline catalogue integrity, discovery and custom-profile boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from manufacturing_readiness_plugin import checklists as c
from manufacturing_readiness_plugin import vendor_catalog as v


class VendorCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = v.load_catalog()

    def test_bundled_catalog_retains_original_ids(self):
        original = {
            'lion-mii-1oz', 'lion-custom-1oz', 'lion-rush-1oz',
            'jlc-rigid-2l-1oz', 'jlc-rigid-multilayer-1oz',
            'pcbway-normal-2l-1oz', 'pcbpower-rigid-2l-1oz-start',
            'pban-general-2l-1oz', 'oshpark-prototype-2l-1oz',
            'sierra-notouch-2l-1oz', 'multicb-pool-2l-1oz',
            'aisler-4l-35um-enig', 'lion-custom-2oz', 'lion-custom-3oz',
            'lion-rush-2oz', 'jlc-rigid-2l-2oz', 'jlc-rigid-multilayer-2oz',
            'nextpcb-rigid-2l-1oz', 'seeed-fusion-2l-1oz',
            'seeed-fusion-2l-2oz', 'seeed-fusion-2l-3oz'}
        self.assertTrue(original <= {p['id'] for p in self.catalog['profiles']})
        self.assertEqual(28, len(self.catalog['vendors']))

    def test_new_profiles_match_published_service_limits(self):
        cases = [('oshpark-prototype-4l-1oz', 4, 1, .127, .1016, .254),
                 ('oshpark-prototype-6l-1oz', 6, 1, .127, .1016, .2032),
                 ('oshpark-2l-2oz-08mm', 2, 2, .1524, .127, .254)]
        for identifier, layers, copper, width, ring, drill in cases:
            with self.subTest(identifier=identifier):
                profile, = v.search_profiles(self.catalog, identifier)
                self.assertEqual([layers], profile['process']['layers'])
                self.assertEqual([copper], profile['process']['copper_oz'])
                self.assertEqual('vendor_order_option', profile['process']['copper_basis'])
                rules = {r['id']: r for r in profile['rules']}
                self.assertEqual(width, rules['track-width']['minimum'])
                self.assertEqual(width, rules['copper-clearance']['minimum'])
                self.assertEqual(ring, rules['annular-ring']['minimum'])
                self.assertEqual(drill, rules['mechanical-drill']['minimum'])
                self.assertEqual('manual', rules['mechanical-drill']['backend'])
                self.assertEqual(.381, rules['circuit-edge']['minimum'])
                self.assertEqual(.508, rules['drill-slot']['minimum'])
                if layers > 2:
                    self.assertEqual([.5], profile['process']['inner_copper_oz'])
                    self.assertEqual('manual', rules['inner-drill-clearance']['backend'])
                    self.assertEqual(.254, rules['inner-drill-clearance']['minimum'])
                for source in profile['sources']:
                    self.assertEqual('2026-11-11', source['verified'])
                    self.assertTrue(source['url'].startswith('https://docs.oshpark.com/services/'))

    def test_only_existing_supported_native_constraints(self):
        for profile in self.catalog['profiles']:
            for rule in profile['rules']:
                if rule['backend'] == 'native_drc':
                    self.assertIn(rule['constraint'], c.NATIVE_CONSTRAINTS)

    def test_new_profiles_compile_only_with_the_full_explicit_process_scope(self):
        for profile in self.catalog['profiles'][-3:]:
            context = {key: value[0] if isinstance(value, list) else value
                       for key, value in profile['process'].items() if key != 'notes'}
            preview = c.compile_native_rules(profile, context)
            self.assertEqual(4, len(preview['compiled_rule_ids']))
            self.assertNotIn('mechanical-drill', preview['compiled_rule_ids'])
            context['copper_oz'] = 3
            with self.assertRaisesRegex(ValueError, 'incompatible process scope'):
                c.compile_native_rules(profile, context)

    def test_scoped_case_insensitive_multiword_search_is_detached(self):
        profiles = v.search_profiles(self.catalog, 'OSH prototype', vendor='osh park',
                                     layers=4, copper_oz=1, copper_basis='vendor_order_option')
        self.assertEqual(['oshpark-prototype-4l-1oz'], [p['id'] for p in profiles])
        profiles[0]['rules'].clear()
        self.assertTrue(v.search_profiles(self.catalog, layers=4, vendor='OSH Park')[0]['rules'])
        self.assertFalse(v.search_profiles(self.catalog, vendor='OSH Park', layers=6, copper_oz=2))

    def test_unknown_scope_is_not_a_positive_filter_match(self):
        catalog = deepcopy(self.catalog)
        catalog['profiles'][0]['process']['layers'] = None
        catalog['profiles'][0]['process']['copper_oz'] = None
        self.assertFalse(v.search_profiles(catalog, catalog['profiles'][0]['id'], layers=4))
        self.assertFalse(v.search_profiles(catalog, catalog['profiles'][0]['id'], copper_oz=1))

    def test_invalid_filters_rejected(self):
        for kwargs in ({'layers': True}, {'layers': 2.5}, {'layers': 0},
                       {'copper_oz': float('nan')}, {'copper_basis': 'guess'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                v.search_profiles(self.catalog, **kwargs)

    def test_directory_search_retains_unprofiled_vendors(self):
        vendors = v.search_vendors(self.catalog, 'shogini')
        self.assertEqual('needs_vendor_confirmation', vendors[0]['status'])
        self.assertFalse(v.search_profiles(self.catalog, vendor=vendors[0]['name']))
        vendors[0]['name'] = 'Changed'
        self.assertNotEqual('Changed', v.search_vendors(self.catalog, 'shogini')[0]['name'])

    def test_catalog_duplicate_and_missing_cross_reference_rejected(self):
        for mutation in ('profile', 'vendor', 'missing', 'url', 'schema'):
            catalog = deepcopy(self.catalog)
            if mutation == 'profile':
                catalog['profiles'].append(deepcopy(catalog['profiles'][0]))
            elif mutation == 'vendor':
                catalog['vendors'].append(deepcopy(catalog['vendors'][0]))
            elif mutation == 'missing':
                catalog['profiles'][0]['vendor'] = 'No such vendor'
            elif mutation == 'url':
                catalog['vendors'][0]['source_urls'] = ['file:///private']
            else:
                catalog['schema'] = 'future'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                v.validate_catalog(catalog)

    def custom(self):
        profile, = v.search_profiles(self.catalog, 'oshpark-prototype-4l-1oz')
        profile['id'] = 'custom-reviewed-process'
        return profile

    def test_custom_profile_round_trip_and_input_not_mutated(self):
        before = deepcopy(self.catalog)
        profile = self.custom()
        payload = v.export_profile(profile)
        result = v.import_custom_profile(self.catalog, payload)
        self.assertEqual(profile, result['profiles'][-1])
        self.assertEqual(before, self.catalog)
        self.assertEqual(payload, v.export_profile(result['profiles'][-1]))

    def test_new_vendor_is_explicitly_user_supplied(self):
        profile = self.custom()
        profile['vendor'] = 'Example Custom Fab'
        result = v.import_custom_profile(self.catalog, v.export_profile(profile))
        vendor, = v.search_vendors(result, 'Example Custom Fab')
        self.assertEqual('User supplied', vendor['region'])
        self.assertIn('independent confirmation', vendor['notes'])
        self.assertEqual(29, len(result['vendors']))
        self.assertEqual(28, len(self.catalog['vendors']))

    def test_custom_collision_never_overwrites(self):
        payload = v.export_profile(self.catalog['profiles'][0])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            v.import_custom_profile(self.catalog, payload)
        self.assertEqual(24, len(self.catalog['profiles']))

    def test_case_variant_vendor_reuses_canonical_directory_name(self):
        profile = self.custom()
        profile['vendor'] = 'osh park'
        result = v.import_custom_profile(self.catalog, v.export_profile(profile))
        self.assertEqual('OSH Park', result['profiles'][-1]['vendor'])
        self.assertEqual(28, len(result['vendors']))

    def test_malformed_oversized_and_duplicate_json_imports(self):
        payload = v.export_profile(self.custom())
        invalid = ['{', payload.replace('"id": "custom-reviewed-process",',
                                       '"id": "first", "id": "second",', 1),
                   payload.replace('0.127', 'NaN', 1),
                   ' ' * (c.MAX_DOCUMENT_BYTES + 1), '\ud800', None]
        for text in invalid:
            with self.subTest(prefix=repr(text)[:60]), self.assertRaises(ValueError):
                v.import_custom_profile(self.catalog, text)

    def test_catalog_loader_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text('{"schema": "a", "schema": "b"}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
                v.load_catalog(path)

    def test_unsupported_native_constraint_import_rejected(self):
        profile = self.custom()
        profile['rules'][0]['constraint'] = 'solder_mask_web'
        with self.assertRaisesRegex(ValueError, 'Unsupported native'):
            v.import_custom_profile(self.catalog, json.dumps(profile))


if __name__ == '__main__':
    unittest.main()
