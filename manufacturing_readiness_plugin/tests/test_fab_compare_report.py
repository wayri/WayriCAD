"""Canonical report/source safety checks using actual core comparisons."""
import copy
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manufacturing_readiness_plugin.fab_compare import load_netlist, compare_netlists
from manufacturing_readiness_plugin.fab_compare_report import (
    build_report, export_report, render_report, report_rows, source_snapshot, validate_report,
)


class FabCompareReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fab-report-')
        self.root = Path(self.temp.name)
        self.reference, self.observed = self.root/'reference.json', self.root/'cam.json'
        terminals = [dict(reference=ref, pin=str(pin), net='DESIGN_'+str(pin))
                     for pin in range(1,10) for ref in ('J1','U1')]
        self.reference.write_text(json.dumps(dict(schema='wayricad.fab-netlist/v1', units='mm',
            terminals=terminals, provenance={'origin':'synthetic test reference'})))
        self.observed.write_text(json.dumps(dict(schema='wayricad.fab-netlist/v1', units='mm',
            terminals=[{**pin,'net':'168'} for pin in terminals], provenance={'origin':'synthetic test CAM'})))

    def tearDown(self):
        self.temp.cleanup()

    def report(self, observed=None, confirmed=True):
        observed = observed or self.observed
        sources = [source_snapshot(self.reference,'reference'),source_snapshot(observed,'observed CAM')]
        result = compare_netlists(load_netlist(self.reference),load_netlist(observed),confirmed)
        return build_report(result,sources=sources)

    def test_one_nine_net_short_preserves_original_names_and_eighteen_endpoints(self):
        report = self.report()
        rows = report_rows(report)
        self.assertEqual(report['status'],'FAIL')
        self.assertFalse(report['fabrication_verified'])
        self.assertEqual(len([row for row in rows if row['kind']=='SHORT']),1)
        row = rows[0]
        self.assertEqual(len(row['details']['design_groups']),9)
        self.assertEqual(len(row['details']['endpoints']),18)
        self.assertIn('DESIGN_9',row['reference_nets'])
        self.assertIn('U1.9',row['pins'])
        self.assertEqual(row['observed_nets'],'168')
        text = render_report(report,'.txt')
        self.assertIn('Total net compare errors: 1',text)
        self.assertIn('Shorts in Job',text)
        self.assertIn('CAM net 168 joins 9 design nets:',text)
        self.assertIn('DESIGN_9: J1.9, U1.9',text)
        self.assertNotIn('"endpoints":',text)
        self.assertEqual(json.loads(render_report(report,'json')),report)

    def test_open_group_and_coverage_issues_are_present(self):
        reference = json.loads(self.reference.read_text())
        observed = copy.deepcopy(reference)
        for pin in observed['terminals']:
            pin['net'] = 'CAM_'+pin['reference']+'_'+pin['pin']
        observed['terminals'].pop()
        self.observed.write_text(json.dumps(observed))
        report = self.report()
        rows = report_rows(report)
        self.assertTrue(any(row['kind']=='OPEN' for row in rows))
        self.assertTrue(any(row['kind']=='MISSING' for row in rows))
        self.assertTrue(any(row['kind']=='ISSUE' for row in rows))
        self.assertIn('Opens in Job',render_report(report,'txt'))

    def test_unknown_self_comparison_and_renamed_match_are_not_fabrication_approval(self):
        unknown = self.report(observed=self.reference)
        self.assertEqual(unknown['status'],'UNKNOWN')
        self.assertTrue(unknown['independence']['identical_source'])
        renamed = json.loads(self.reference.read_text())
        for terminal in renamed['terminals']:
            terminal['net']='CAM_'+terminal['pin']
        self.observed.write_text(json.dumps(renamed))
        match = self.report()
        self.assertEqual(match['status'],'MATCH')
        self.assertFalse(match['fabrication_verified'])
        self.assertEqual(self.report(confirmed=False)['status'],'UNKNOWN')

    def test_mutated_report_and_stale_source_block_all_exports(self):
        report = self.report()
        report['summary']['short_groups']=0
        with self.assertRaisesRegex(ValueError,'contents changed'):
            export_report(report,self.root/'mutated.html')
        report = self.report()
        self.reference.write_bytes(self.reference.read_bytes()+b'\n')
        for format in ('json','html','csv','txt'):
            with self.subTest(format=format), self.assertRaisesRegex(ValueError,'Source changed'):
                export_report(report,self.root/('stale.'+format))
            self.assertFalse((self.root/('stale.'+format)).exists())

    def test_parsed_bytes_must_match_snapshot_even_if_current_file_was_restored(self):
        comparison = compare_netlists(self.reference,self.observed,True)
        self.reference.write_bytes(self.reference.read_bytes()+b'\n')
        sources = [source_snapshot(self.reference,'reference'),source_snapshot(self.observed,'observed CAM')]
        with self.assertRaisesRegex(ValueError,'Parsed reference bytes'):
            build_report(comparison,sources=sources)

    def test_untrusted_names_are_escaped_and_csv_formulas_are_inert(self):
        data = json.loads(self.observed.read_text())
        for terminal in data['terminals']:
            terminal['net']='=HYPERLINK("bad")<img>'
        self.observed.write_text(json.dumps(data))
        report = self.report()
        html = render_report(report,'html')
        self.assertNotIn('<img>',html)
        self.assertIn('&lt;img&gt;',html)
        self.assertIn("connect-src 'none'",html)
        rows = list(csv.DictReader(io.StringIO(render_report(report,'csv'))))
        self.assertTrue(rows[0]['cam_nets'].startswith("'=HYPERLINK"))
        self.assertEqual(report['shorts'][0]['observed_net'],'=HYPERLINK("bad")<img>')

    def test_atomic_output_protects_input_aliases_and_rolls_back(self):
        report = self.report()
        with self.assertRaisesRegex(ValueError,'overwrite'):
            export_report(report,self.reference)
        alias = self.root/'alias.csv'
        os.link(self.reference,alias)
        with self.assertRaises(ValueError):
            export_report(report,alias)
        output = self.root/'report.html'
        output.write_bytes(b'old approved report')
        with patch('wayricad_runtime.report_ui.os.replace',side_effect=OSError('publish failed')):
            with self.assertRaises(OSError):
                export_report(report,output)
        self.assertEqual(output.read_bytes(),b'old approved report')
        validate_report(report)

    def test_all_formats_export_and_row_limit_never_changes_canonical_findings(self):
        report = self.report()
        exact = copy.deepcopy(report)
        self.assertEqual(report_rows(report,limit=0),[])
        self.assertEqual(len(report_rows(report,limit=1)),1)
        for format in ('json','html','csv','txt'):
            path = self.root/('report.'+format)
            self.assertEqual(export_report(report,path),path)
            self.assertGreater(path.stat().st_size,100)
        self.assertEqual(report,exact)
        with self.assertRaises(ValueError):
            export_report(report,self.root/'bad.json',format='html')
