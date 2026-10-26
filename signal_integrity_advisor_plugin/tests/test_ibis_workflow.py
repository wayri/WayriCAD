"""Explicit case/model bindings, portable config paths and stale source checks."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signal_integrity_advisor_plugin.ibis_workflow import circuit_cases,read_json,relative_model_paths
from signal_integrity_advisor_plugin.service import source_fingerprints
from signal_integrity_advisor_plugin.tests.test_ibis_models import SAMPLE


class IBISWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.board=self.root/'board.kicad_pcb';self.board.write_text('(kicad_pcb)')
        self.model=self.root/'models.ibs';self.model.write_text(SAMPLE)
        self.report={'schema':'wayricad.quick-si/v1','source_fingerprints':source_fingerprints(self.board)}
        self.assignments={'cases':{'route':{
            'source':{'path':str(self.model),'component':'DeviceA','pin':'5','model':'DriveA'},
            'sink':{'path':str(self.model),'component':'DeviceA','pin':'4','model':'InputModel'}}}}
        for value in self.assignments['cases']['route'].values():
            value['sha256']=hashlib.sha256(self.model.read_bytes()).hexdigest()

    def tearDown(self):self.directory.cleanup()

    def test_assignments_normalize_once_per_model_and_detect_stale_input(self):
        from signal_integrity_advisor_plugin.ibis_models import load_ibis
        with patch('signal_integrity_advisor_plugin.ibis_models.load_ibis',wraps=load_ibis) as loader:
            cases=circuit_cases(self.report,self.assignments)
            self.assertEqual(loader.call_count,1)
        self.assertEqual(cases[0]['source']['corners']['vcc'],'typ')
        self.assertEqual(cases[0]['sink']['role'],'sink')
        self.assignments['cases']['route']['source']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'changed'):circuit_cases(self.report,self.assignments)

    def test_unbound_model_file_is_not_silently_reviewed_on_export(self):
        del self.assignments['cases']['route']['source']['sha256']
        with self.assertRaisesRegex(ValueError,'reviewed IBIS sha256'):
            circuit_cases(self.report,self.assignments)

    def test_source_changes_and_missing_endpoints_do_not_export(self):
        self.board.write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):circuit_cases(self.report,self.assignments)
        self.report['source_fingerprints']=source_fingerprints(self.board)
        del self.assignments['cases']['route']['sink']
        with self.assertRaisesRegex(ValueError,'both source and sink'):circuit_cases(self.report,self.assignments)

    def test_selected_study_cases_are_explicit_and_failures_not_silently_dropped(self):
        study={'schema':'wayricad.quick-si-study/v1','source_fingerprints':self.report['source_fingerprints'],
               'cases':[{'id':'route','report':self.report},{'id':'failed','error':'No route'}]}
        self.assertEqual(len(circuit_cases(study,self.assignments,['route'])),1)
        with self.assertRaisesRegex(ValueError,'completed route'):circuit_cases(study,self.assignments)
        with self.assertRaisesRegex(ValueError,'distinct existing'):circuit_cases(study,self.assignments,['route','route'])

    def test_shared_board_is_hashed_once_at_each_guard_boundary(self):
        from signal_integrity_advisor_plugin.ibis_workflow import require_case_sources,require_report_source
        cases=[{'report':self.report} for _ in range(32)]
        with patch('signal_integrity_advisor_plugin.ibis_workflow.require_report_source',wraps=require_report_source) as check:
            require_case_sources(cases)
            self.assertEqual(check.call_count,1)
            self.board.write_text('changed after first boundary')
            with self.assertRaisesRegex(ValueError,'changed'):require_case_sources(cases)
            self.assertEqual(check.call_count,2)

    def test_paths_relative_to_config_and_json_size_finiteness(self):
        self.assignments['cases']['route']['source']['path']='models.ibs'
        resolved=relative_model_paths(self.assignments,self.root/'assignments.json')
        self.assertEqual(resolved['cases']['route']['source']['path'],str(self.model.resolve()))
        self.assertEqual(self.assignments['cases']['route']['source']['path'],'models.ibs')
        file=self.root/'input.json';file.write_text('{"a":NaN}')
        with self.assertRaisesRegex(ValueError,'Non-finite'):read_json(file)
        with self.assertRaisesRegex(ValueError,'allowed JSON size'):read_json(file,3)


if __name__=='__main__':unittest.main()
