from copy import deepcopy
from test_core import Fixture, BASE
from bomstudio.simple_exports import preview, download, is_test_point


class SimpleExportTests(Fixture):
    def refs(self, options):
        p = preview(self.ws, BASE, {'grouped': False, **options})
        return {r[p['columns'].index('Reference')] for r in p['rows']}

    def test_conditions_and_separate_lists_include_excluded(self):
        self.edit('R1', {'TestPoint': 'yes', 'in_bom': False})
        self.ws.set_population([self.row('R2')['id']], BASE, 'DNP')
        self.assertEqual(self.refs({'kind': 'testpoints'}), {'R1'})
        self.assertEqual(self.refs({'kind': 'dnp'}), {'R2', 'R4'})
        refs = self.refs({'kind': 'bom'})
        self.assertNotIn('R1', refs)
        self.assertNotIn('R2', refs)
        self.assertIn('R2', self.refs({'kind': 'bom', 'exclude_dnp': False}))

    def test_staged_edits_and_template_survive_without_mutation(self):
        self.edit('R1', {'Value': 'staged value'})
        before = deepcopy(self.ws.state)
        p = preview(self.ws, BASE, {'template': 'Engineering', 'grouped': False})
        self.assertTrue(any('staged value' in r for r in p['rows']))
        data, name, mime = download(self.ws, BASE, {'template': 'Engineering'}, 'csv', True)
        self.assertIn(b'staged value', data)
        self.assertIn('DRAFT', name)
        self.assertEqual(before, self.ws.state)

    def test_individual_vs_grouped(self):
        # Identical resistors retain independent rows when grouping is disabled.
        p = preview(self.ws, BASE, {'exclude_dnp': False, 'grouped': False})
        self.assertTrue(all(r[p['columns'].index('Qty')] == 1 for r in p['rows']))
        g = preview(self.ws, BASE, {'exclude_dnp': False, 'grouped': True})
        self.assertLessEqual(g['groups'], p['groups'])

    def test_invalid_options(self):
        for options in ([], {'kind': 'other'}, {'grouped': 'false'}, {'template': 'missing'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                preview(self.ws, BASE, options)

    def test_testpoint_detection_overrides(self):
        self.assertTrue(is_test_point({'ref': 'TP12', 'fields': {}}))
        self.assertFalse(is_test_point({'ref': 'TP12', 'fields': {'TestPoint': 'no'}}))
        self.assertFalse(is_test_point({'ref': 'TP_POWER', 'fields': {}}))


