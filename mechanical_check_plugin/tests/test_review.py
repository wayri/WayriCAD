"""Pure review filtering, threshold semantics and unchanged source evidence."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'src'))
from wayricad_mechanical.review import filtered_findings, finding_details, review_summary


def issue(identity, severity='error', **values):
    return dict(id=identity, severity=severity, refs=['U1', 'J2'],
                rule='solid.clearance', summary='Assembly clearance',
                evidence='exact STEP surfaces', action='Move the connector', waiver='',
                **values)


class UnreadGeometry:
    def __str__(self):
        raise AssertionError('Geometry must not be converted to review text')
    def __iter__(self):
        raise AssertionError('Geometry must not be traversed by review helpers')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.error = issue('error')
        self.warning = issue('warning', 'warning')
        self.info = issue('info', 'info')
        self.waived = dict(self.error, id='waived', waiver='Accepted service access')
        self.findings = [self.waived, self.info, self.warning, self.error]

    def test_filters_keep_waivers_out_of_open_errors_and_warnings(self):
        waived_warning = dict(self.warning, id='waived_warning', waiver='Reviewed')
        findings = self.findings + [waived_warning]
        self.assertEqual(filtered_findings(findings, severity='Errors'), [self.error])
        self.assertEqual(filtered_findings(findings, severity='Warnings'), [self.warning])
        self.assertEqual(filtered_findings(findings, severity='Waived'), [self.waived, waived_warning])
        self.assertEqual(filtered_findings(findings, severity='Open'), [self.error, self.warning, self.info])
        self.assertEqual(len(filtered_findings(findings)), 5)

    def test_query_tokens_match_across_human_fields_and_are_case_insensitive(self):
        self.assertEqual(filtered_findings(self.findings, query='J2  connector\nSTEP'),
                         [self.error, self.warning, self.info, self.waived])
        self.assertEqual(filtered_findings(self.findings, query='ACCEPTED access'), [self.waived])
        self.assertEqual(filtered_findings(self.findings, query='J2 absent'), [])
        self.assertEqual(filtered_findings(self.findings, query='  \t'), filtered_findings(self.findings))

    def test_search_and_details_never_serialize_geometry_or_sections(self):
        record = dict(self.error, mesh=UnreadGeometry(), sections=UnreadGeometry(),
                      points=UnreadGeometry(), bounds=UnreadGeometry(), label_position=UnreadGeometry())
        self.assertEqual(filtered_findings([record], query='exact connector'), [record])
        self.assertEqual(filtered_findings([record], query='mesh'), [])
        self.assertIn('exact STEP surfaces', finding_details(record))
        self.assertIn('1 open errors', review_summary({'findings': [record], 'coverage': {'gaps': []}, 'status': 'review_required'}))

    def test_sort_does_not_mutate_source_order_or_dictionaries(self):
        findings = [dict(self.error, id='z', refs=['Z1'], rule='b.rule'),
                    dict(self.warning, id='a', refs=['A1'], rule='a.rule')]
        before = copy.deepcopy(findings)
        self.assertEqual([r['id'] for r in filtered_findings(findings)], ['z', 'a'])
        self.assertEqual([r['id'] for r in filtered_findings(findings, sort_by='Parts')], ['a', 'z'])
        self.assertEqual([r['id'] for r in filtered_findings(findings, sort_by='Rule')], ['a', 'z'])
        self.assertEqual(findings, before)
        self.assertIs(filtered_findings(findings)[0], findings[0])
        ties = [dict(self.error, id='second'), dict(self.error, id='first')]
        self.assertEqual(filtered_findings(ties), ties)

    def test_unknown_options_are_actionable_instead_of_silent_empty_results(self):
        with self.assertRaisesRegex(ValueError, 'filter'):
            filtered_findings(self.findings, severity='Critical')
        with self.assertRaisesRegex(ValueError, 'sort'):
            filtered_findings(self.findings, sort_by='Distance')

    def test_height_details_use_maximum_and_excess_with_declared_units(self):
        record = dict(self.error, rule='height.maximum', measured=8.7, limit=8, unit='mm')
        before = copy.deepcopy(record)
        text = finding_details(record)
        for expected in ('Maximum: 8 mm', 'Measured: 8.7 mm', 'Excess: 0.7 mm',
                         'Parts: U1, J2', 'Unit: mm', 'Waiver: None', 'Suggested action: Move the connector'):
            self.assertIn(expected, text)
        self.assertNotIn('Required:', text)
        self.assertEqual(record, before)
        self.assertIn('Excess: 0.0007 m', finding_details(dict(record, measured=.0087, limit=.008, unit='m')))

    def test_regional_height_and_overlap_tolerances_are_explicit_maxima(self):
        regional = dict(self.error, rule='height.zone', measured=6.5, limit=5, unit='mm',
                        summary='Regional height limit exceeded', location_key='Enclosure lip')
        text = finding_details(regional)
        self.assertIn('Maximum: 5 mm', text)
        self.assertIn('Excess: 1.5 mm', text)
        self.assertNotIn('Required:', text)
        for rule in ('solid.collision', 'interboard.collision'):
            text = finding_details(dict(self.error, rule=rule, measured=.125, limit=.025, unit='mm³'))
            self.assertIn('Maximum: 0.025 mm³', text)
            self.assertIn('Measured: 0.125 mm³', text)
            self.assertIn('Excess: 0.1 mm³', text)
            self.assertNotIn('Required:', text)
        self.assertIn('Excess: Unknown', finding_details(dict(regional, limit=None)))

    def test_proximity_threshold_is_not_described_as_required_clearance(self):
        for rule in ('solid.proximity_warning', 'screen.proximity_warning'):
            text = finding_details(dict(self.warning, rule=rule, measured=.4, limit=1, unit='mm'))
            self.assertIn('Warning below: 1 mm', text)
            self.assertNotIn('Required:', text)
            self.assertIn('Excess: Not applicable', text)
        text = finding_details(dict(self.error, measured=.4, limit=.5, unit='mm'))
        self.assertIn('Required: 0.5 mm', text)
        self.assertNotIn('Warning below:', text)

    def test_unknown_numeric_values_and_absent_units_do_not_invent_measurements(self):
        for value in (None, True, '1.5', math.nan, math.inf):
            text = finding_details(dict(self.error, rule='height.maximum', measured=value, limit=1, unit='mm'))
            self.assertIn('Measured: Unknown', text)
            self.assertIn('Excess: Unknown', text)
        text = finding_details(dict(self.error, measured=0, limit=None))
        self.assertIn('Measured: 0\n', text)
        self.assertIn('Required: Unknown', text)
        self.assertIn('Unit: Not specified', text)
        self.assertNotIn(' mm', text)
        self.assertIn('Severity: Error (waived)', finding_details(self.waived))
        self.assertIn('Waiver: Accepted service access', finding_details(self.waived))

    def test_summary_counts_open_findings_and_preserves_incomplete_status(self):
        report = dict(findings=self.findings, coverage={'gaps': ['Missing model', 'Unresolved placement']}, status='incomplete')
        before = copy.deepcopy(report)
        text = review_summary(report)
        for expected in ('INCOMPLETE', '1 open errors', '1 open warnings', '1 waived', '2 coverage gaps'):
            self.assertIn(expected, text)
        self.assertEqual(report, before)
        self.assertIn('INCOMPLETE (reported: PASSED)', review_summary(dict(report, status='passed')))
        self.assertIn('Coverage unavailable', review_summary({'findings': [], 'status': 'passed'}))

    def test_empty_and_waived_completed_reports_keep_report_status_honest(self):
        report = dict(findings=[], coverage={'gaps': []}, status='passed')
        self.assertTrue(review_summary(report).startswith('PASSED ·'))
        self.assertIn('0 open errors', review_summary(report))
        text = review_summary(dict(report, findings=[self.waived], status='passed_with_waivers'))
        self.assertTrue(text.startswith('PASSED WITH WAIVERS'))
        self.assertIn('1 waived', text)
        self.assertIn('REVIEW REQUIRED (reported: PASSED)', review_summary(dict(report, findings=[self.error])))


if __name__ == '__main__':
    unittest.main()
