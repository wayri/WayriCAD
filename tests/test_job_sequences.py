"""Real subprocess/report checks for the shared job sequence contract."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime import jobs


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wayricad job tests ')
        self.root = Path(self.temp.name)
        self.project = self.root/'Demo.kicad_pro';self.project.write_text('{}')
        self.board = self.root/'Demo.kicad_pcb';self.board.write_text('(kicad_pcb)')
        self.config_path = self.root/'wayricad-jobs.json'
        self.config = {'schema': jobs.SCHEMA, 'project': self.project.name, 'steps': []}
        self.environment = patch.dict(os.environ, {'JOBSET_OUTPUT_WORK_PATH': ''})
        self.environment.start()

    def tearDown(self):
        self.environment.stop();self.temp.cleanup()

    def step(self, name='report', code=None, **kwargs):
        code = code or "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('result');print('generated')"
        return dict(id=name, argv=[sys.executable, '-c', code, '${step_dir}/result.txt'], outputs=['result.txt'], **kwargs)

    def run_config(self, **kwargs):
        self.config_path.write_text(json.dumps(self.config))
        return jobs.run_sequence(self.config, self.project, self.config_path, **kwargs)

    def test_success_fresh_runs_hashes_html_and_literal_arguments(self):
        self.config['variables'] = {'name': 'a b & literal $HOME'}
        step = self.step(code="from pathlib import Path;import sys;Path(sys.argv[1]).write_text(sys.argv[2])")
        step['argv'].append('${name}');step['label'] = '<unsafe title>'
        self.config['steps'] = [step]
        first, code = self.run_config();second, second_code = self.run_config()
        self.assertEqual((0, 0), (code, second_code))
        self.assertNotEqual(first['run_id'], second['run_id'])
        run = Path(first['report_directory'])
        result = run/'report/result.txt'
        self.assertEqual(result.read_text(), 'a b & literal $HOME')
        artifact = next(a for a in first['steps'][0]['artifacts'] if a['path'].endswith('result.txt'))
        self.assertEqual(artifact['sha256'], jobs.digest(result))
        self.assertIn('&lt;unsafe title&gt;', (run/'index.html').read_text())
        self.assertEqual(json.loads((run/'summary.json').read_text())['status'], 'PASS')

    def test_nonzero_and_dependencies_fail_even_if_output_exists(self):
        bad = self.step('failed', "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('not approved');sys.exit(3)")
        dependent = self.step('dependent', depends_on=['failed'])
        independent = self.step('independent')
        self.config['steps'] = [bad, dependent, independent]
        report, code = self.run_config(keep_going=True)
        self.assertEqual(code, 1)
        self.assertEqual([s['status'] for s in report['steps']], ['FAIL', 'SKIPPED', 'PASS'])
        self.assertEqual(report['steps'][0]['exit_code'], 3)

    def test_stop_on_error_missing_artifact_and_logs_retained(self):
        self.config['steps'] = [self.step('empty', "print('No file generated')"), self.step('later')]
        report, code = self.run_config()
        self.assertEqual(code, 1)
        self.assertEqual([s['status'] for s in report['steps']], ['FAIL', 'SKIPPED'])
        self.assertIn('Missing/empty', report['steps'][0]['message'])
        self.assertTrue(any(a['path'].endswith('stdout.log') for a in report['steps'][0]['artifacts']))

    def test_timeout_is_failure_with_report(self):
        self.config['steps'] = [self.step(code='import time;time.sleep(30)', timeout_seconds=.1)]
        report, code = self.run_config()
        self.assertEqual(code, 1);self.assertEqual(report['steps'][0]['status'], 'TIMEOUT')
        self.assertTrue((Path(report['report_directory'])/'index.html').is_file())

    def test_interrupt_during_artifact_finalization_writes_cancelled_report(self):
        self.config['steps'] = [self.step('first'), self.step('later')]
        with patch.object(jobs, 'files_in', side_effect=KeyboardInterrupt):
            report, code = self.run_config()
        run = Path(report['report_directory'])
        self.assertEqual(code, 130)
        self.assertEqual(report['status'], 'CANCELLED')
        self.assertEqual([s['status'] for s in report['steps']], ['CANCELLED', 'SKIPPED'])
        self.assertEqual(json.loads((run/'summary.json').read_text())['status'], 'CANCELLED')
        self.assertIn(report['run_id']+'/index.html', (run.parent/'latest.html').read_text())

    def test_artifact_io_error_is_a_reported_failure(self):
        self.config['steps'] = [self.step()]
        with patch.object(jobs, 'files_in', side_effect=OSError('artifact unavailable')):
            report, code = self.run_config()
        self.assertEqual(code, 1)
        self.assertEqual(report['steps'][0]['status'], 'FAIL')
        self.assertIn('artifact unavailable', report['steps'][0]['message'])
        self.assertEqual(json.loads((Path(report['report_directory'])/'summary.json').read_text())['status'], 'FAIL')

    def test_missing_executable_is_reported(self):
        self.config['steps'] = [dict(id='missing', argv=['wayricad-nonexistent-executable-12345'])]
        report, code = self.run_config()
        self.assertEqual(code, 1);self.assertEqual(report['steps'][0]['status'], 'FAIL')
        self.assertTrue(report['steps'][0]['message'])

    def test_design_change_invalidates_run(self):
        self.config['steps'] = [self.step(code="from pathlib import Path;import sys;Path('Demo.kicad_pcb').write_text('changed');Path(sys.argv[1]).write_text('report')")]
        report, code = self.run_config()
        self.assertEqual(code, 1);self.assertIn('inputs changed', report['errors'][0])

    def test_jobset_collects_reports_and_preserves_failure_diagnostics(self):
        destination = self.root/'jobset output';destination.mkdir()
        self.config['steps'] = [self.step(code='import sys;sys.exit(4)')]
        with patch.dict(os.environ, {'JOBSET_OUTPUT_WORK_PATH': str(destination)}):
            report, code = self.run_config()
        self.assertEqual(code, 1)
        collected = destination/'wayricad'/report['run_id']/'summary.json'
        self.assertEqual(json.loads(collected.read_text())['status'], 'FAIL')
        self.assertTrue((Path(report['report_directory'])/'summary.json').is_file())

    def test_invalid_jobset_collection_path_does_not_succeed(self):
        self.config['steps'] = [self.step()]
        with patch.dict(os.environ, {'JOBSET_OUTPUT_WORK_PATH': 'relative/not-valid'}):
            report, code = self.run_config()
        self.assertEqual(code, 1);self.assertIn('collection failed', report['errors'][0])

    def test_validation_unknown_tokens_and_dry_run_make_no_reports(self):
        self.config['steps'] = [self.step()]
        result, code = self.run_config(dry_run=True)
        self.assertEqual(code, 0);self.assertTrue(result['dry_run'])
        self.assertFalse((self.root/'reports').exists())
        self.config['steps'][0]['argv'].append('${undefined}')
        with self.assertRaisesRegex(ValueError, 'undefined'):
            self.run_config(dry_run=True)

    def test_rejects_invalid_schema_and_paths_before_execution(self):
        base = dict(self.config, steps=[self.step()])
        cases = []
        for field, value in [('outputs', ['../outside']), ('depends_on', ['unknown']), ('timeout_seconds', float('nan')), ('argv', 'echo shell')]:
            value_config = copy.deepcopy(base);value_config['steps'][0][field] = value;cases.append(value_config)
        duplicate = copy.deepcopy(base);duplicate['steps'] *= 2;cases.append(duplicate)
        unknown = copy.deepcopy(base);unknown['stpes'] = [];cases.append(unknown)
        for config in cases:
            with self.subTest(config=config), self.assertRaises(ValueError):jobs.validate(config)

    def test_native_jobset_merge_preserves_original_and_destination_order(self):
        self.config['steps'] = [self.step()];self.config_path.write_text(json.dumps(self.config))
        existing = {'meta': {'version': 1}, 'jobs': [{'id': 'first', 'type': 'a'}, {'id': 'last', 'type': 'b'}],
                    'outputs': [{'id': 'folder', 'only': ['first', 'last'], 'settings': {'output_path': 'output'}}, {'id': 'all', 'only': []}]}
        original = copy.deepcopy(existing)
        output = jobs.jobset_document(self.project, self.config_path, existing=existing, position=1, python=sys.executable)
        self.assertEqual(existing, original)
        inserted = output['jobs'][1]
        self.assertEqual(inserted['type'], 'special_execute')
        self.assertFalse(inserted['settings']['ignore_exit_code'])
        self.assertEqual(output['outputs'][0]['only'], ['first', inserted['id'], 'last'])
        self.assertEqual(output['outputs'][1]['only'], [])

    def test_native_jobset_merge_rejects_ambiguous_ids_and_only_lists(self):
        self.config['steps'] = [self.step()];self.config_path.write_text(json.dumps(self.config))
        duplicate_jobs = {'meta': {'version': 1},
                          'jobs': [{'id': 'same'}, {'id': 'same'}], 'outputs': []}
        with self.assertRaisesRegex(ValueError, 'unique'):
            jobs.jobset_document(self.project, self.config_path, existing=duplicate_jobs)
        duplicate_only = {'meta': {'version': 1}, 'jobs': [{'id': 'one'}],
                          'outputs': [{'id': 'folder', 'only': ['one', 'one']}]}
        with self.assertRaisesRegex(ValueError, 'references'):
            jobs.jobset_document(self.project, self.config_path, existing=duplicate_only)

    def test_shell_boundaries_and_exclusive_creation(self):
        self.assertTrue(jobs.shell_command(['C:/Program Files/python.exe', 'x y'], 'windows').startswith('call "'))
        with self.assertRaises(ValueError):jobs.shell_command(['bad%PATH%'], 'windows')
        self.assertEqual(jobs.shell_command(['runner', 'a b'], 'posix'), "runner 'a b'")
        path = self.root/'new.json';jobs.write_new(path, {})
        with self.assertRaises(FileExistsError):jobs.write_new(path, {})
        with self.assertRaises(ValueError):jobs.write_new(self.board, {})

    def test_duplicate_json_keys_rejected(self):
        self.config_path.write_text('{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):jobs.load_json(self.config_path)


if __name__ == '__main__':unittest.main()
