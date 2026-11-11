"""Native DRC attribution, saved-input identity and worker lifetime contracts."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from manufacturing_readiness_plugin import checklists as c
from manufacturing_readiness_plugin import dfm_checks as d


def profile():
    return dict(schema=c.PROFILE_SCHEMA, id='fixture', name='Synthetic vendor', vendor='Fixture',
                service='Test', revision='1', process=dict(board_type='rigid', copper_oz=[1], layers=[2]),
                sources=[dict(id='source', url='https://example.com/test', title='Test only',
                              retrieved='2026-11-04', verified='2026-11-04')],
                rules=[dict(id='track', title='Track minimum', category='DRC', backend='native_drc',
                            constraint='track_width', unit='mm', minimum=.5, maximum=None, source_ids=['source']),
                       dict(id='assembly', title='Assembly review', category='DFA', backend='manual',
                            constraint=None, unit=None, minimum=None, maximum=None, source_ids=[])])


CONTEXT = dict(board_type='rigid', copper_oz=1, layers=2)


def report(rows=None):
    return dict(violations=[] if rows is None else rows, unconnected_items=[], schematic_parity=[])


def violation(name='fixture:track'):
    return dict(description="Track width (rule '" + name + "' min width 0.5000 mm; actual 0.3000 mm)",
                type='track_width', severity='error',
                items=[dict(uuid='track-uuid', pos=dict(x=12.5, y=8.5))])


class NativeResultTests(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.preview = c.compile_native_rules(self.profile, CONTEXT)

    def classify(self, value, code=0):
        return d.classify_native_results(self.profile, self.preview, value, code)[0]

    def test_clean_native_result_passes_only_compiled_rules(self):
        rows = self.classify(report())
        self.assertEqual([row['status'] for row in rows], ['PASS', 'UNKNOWN'])

    def test_native_failure_retains_object_identity_and_location(self):
        rows = self.classify(report([violation()]), 5)
        self.assertEqual(rows[0]['status'], 'FAIL')
        self.assertEqual(rows[0]['object_ids'], ['track-uuid'])
        self.assertEqual(rows[0]['positions_mm'], [[12.5, 8.5]])

    def test_unattributed_native_findings_are_unknown(self):
        for name in ('fixture:track-wide', 'otherfixture:track', 'fixture:track.more'):
            with self.subTest(name=name):
                self.assertEqual(self.classify(report([violation(name)]), 5)[0]['status'], 'UNKNOWN')

    def test_failed_or_contradictory_exit_is_not_a_pass(self):
        for code in (1, 2, 5, -1):
            with self.subTest(code=code):
                self.assertEqual(self.classify(report(), code)[0]['status'], 'UNKNOWN')

    def test_malformed_report_shapes_are_rejected(self):
        for value in ([], dict(violations=None, unconnected_items=[]),
                      dict(violations=['bad'], unconnected_items=[]),
                      report([dict(description='bad', items=None)]),
                      report([dict(description='bad', items=['bad'])])):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.classify(value)


class SnapshotCleanupTests(unittest.TestCase):
    def test_transient_owned_cleanup_lock_is_retried_with_bound(self):
        owner = SimpleNamespace(name='owned-test-workspace', cleanup=Mock(side_effect=[PermissionError(), NotADirectoryError(), None]))
        with patch.object(d.tempfile, 'TemporaryDirectory', return_value=owner), patch.object(d.time, 'sleep') as sleep:
            with d._snapshot_directory() as directory:
                self.assertEqual(directory, owner.name)
        self.assertEqual(owner.cleanup.call_count, 3)
        self.assertEqual([row.args[0] for row in sleep.call_args_list], [.1, .2])

    def test_persistent_owned_cleanup_failure_is_not_hidden(self):
        owner = SimpleNamespace(name='owned-test-workspace', cleanup=Mock(side_effect=PermissionError('Locked')))
        with patch.object(d.tempfile, 'TemporaryDirectory', return_value=owner), patch.object(d.time, 'sleep') as sleep:
            with self.assertRaisesRegex(OSError, 'owned-test-workspace'):
                with d._snapshot_directory():
                    pass
        self.assertEqual(owner.cleanup.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_retry_preserves_original_cancellation(self):
        owner = SimpleNamespace(name='owned-test-workspace', cleanup=Mock(side_effect=[PermissionError(), None]))
        with patch.object(d.tempfile, 'TemporaryDirectory', return_value=owner), patch.object(d.time, 'sleep'):
            with self.assertRaisesRegex(InterruptedError, 'Cancelled'):
                with d._snapshot_directory():
                    raise InterruptedError('Cancelled')
        self.assertEqual(owner.cleanup.call_count, 2)


class SnapshotWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2] / '.validation' / 'dfm-unit-tests'
        cls.root.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.owner = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.owner.cleanup)
        self.directory = Path(self.owner.name)
        self.board = self.directory / 'source.kicad_pcb'
        self.board.write_text('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)))', encoding='utf-8')
        self.board.with_suffix('.kicad_pro').write_text('{}', encoding='utf-8')
        self.board.with_suffix('.kicad_dru').write_text('(version 1)\n# original custom rules\n', encoding='utf-8')
        self.created = []

    def process_factory(self, *, value=None, code=0, running=False, mutate=None, diagnostics=None, missing=False):
        parent = self
        class Process:
            def __init__(self, command, **kwargs):
                self.command = command; self.returncode = None if running else code
                self.terminated = False; self.killed = False
                output = Path(command[command.index('--output') + 1])
                self.snapshot = Path(command[-1])
                self.project_bytes = self.snapshot.with_suffix('.kicad_pro').read_bytes()
                rules_path = self.snapshot.with_suffix('.kicad_dru')
                self.rules_bytes = rules_path.read_bytes() if rules_path.is_file() else None
                self.rules_text = rules_path.read_text(encoding='utf-8') if rules_path.is_file() else None
                if not missing:
                    output.write_text(json.dumps(report() if value is None else value), encoding='utf-8')
                if diagnostics:
                    kwargs['stderr'].write(diagnostics.encode('utf-8')); kwargs['stderr'].flush()
                if mutate:
                    mutate()
                parent.created.append(self)
            def poll(self):
                return self.returncode
            def terminate(self):
                self.terminated = True; self.returncode = -15
            def kill(self):
                self.killed = True; self.returncode = -9
            def wait(self, timeout=None):
                return self.returncode
        return Process

    def audit(self, factory=None, **kwargs):
        temporary = tempfile.TemporaryDirectory
        def owned_directory(**options):
            return temporary(dir=self.directory, **options)
        with patch.object(d.tempfile, 'TemporaryDirectory', side_effect=owned_directory), \
                patch.object(d.subprocess, 'Popen', factory or self.process_factory()):
            selected_profile = kwargs.pop('selected_profile', None) or profile()
            return d.audit_snapshot(self.board, selected_profile, CONTEXT, cli='fixture-cli', **kwargs)

    def test_snapshot_does_not_modify_originals_and_clears_hook(self):
        files, digest = d.source_inputs(self.board, CONTEXT)
        hooks = []
        result = self.audit(process_hook=hooks.append)
        self.assertEqual(d.source_inputs(self.board, CONTEXT), (files, digest))
        self.assertEqual(result['source_sha256'], digest)
        self.assertEqual(result['results'][0]['status'], 'PASS')
        self.assertNotEqual(self.created[0].snapshot, self.board)
        self.assertIn("(rule \"fixture:track\"", self.created[0].rules_text)
        self.assertNotIn('; Vendor', self.created[0].rules_text)
        self.assertEqual(hooks, [self.created[0], None])

    def test_project_custom_rule_and_context_changes_affect_source_key(self):
        original = d.source_inputs(self.board, CONTEXT)[1]
        for suffix in ('.kicad_pro', '.kicad_dru'):
            path = self.board.with_suffix(suffix); old = path.read_bytes()
            path.write_bytes(old + b' ')
            self.assertNotEqual(d.source_inputs(self.board, CONTEXT)[1], original)
            path.write_bytes(old)
        self.assertNotEqual(d.source_inputs(self.board, dict(CONTEXT, layers=4))[1], original)

    def test_vendor_run_enables_ignored_provider_and_removes_only_private_exclusions(self):
        original = dict(board=dict(design_settings=dict(
            rule_severities=dict(track_width='ignore', silk_overlap='warning'),
            drc_exclusions=['saved-exclusion'])), text_variables=dict(KEEP='unchanged'))
        self.board.with_suffix('.kicad_pro').write_text(json.dumps(original), encoding='utf-8')
        before = d.source_inputs(self.board, CONTEXT)
        result = self.audit()
        settings = json.loads(self.created[0].project_bytes)['board']['design_settings']
        self.assertEqual(settings['rule_severities'], dict(track_width='error', silk_overlap='warning'))
        self.assertEqual(settings['drc_exclusions'], [])
        self.assertEqual(json.loads(self.created[0].project_bytes)['text_variables'], original['text_variables'])
        self.assertEqual(result['snapshot_overrides']['provider_severities']['track_width'],
                         dict(original='ignore', applied='error'))
        self.assertEqual(result['snapshot_overrides']['excluded_findings_removed'], 1)
        self.assertEqual(d.source_inputs(self.board, CONTEXT), before)

    def test_vendor_run_without_project_creates_only_private_provider_settings(self):
        self.board.with_suffix('.kicad_pro').unlink()
        result = self.audit()
        self.assertEqual(json.loads(self.created[0].project_bytes)['board']['design_settings']
                         ['rule_severities']['track_width'], 'error')
        self.assertFalse(self.board.with_suffix('.kicad_pro').exists())
        self.assertNotIn('source.kicad_pro', result['input_sha256'])

    def test_malformed_project_cannot_produce_a_vendor_pass(self):
        for text in ('not JSON', '[]', '{"board": []}', '{"board": {"design_settings": {"rule_severities": []}}}'):
            with self.subTest(text=text):
                self.board.with_suffix('.kicad_pro').write_text(text, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'private vendor DRC'):
                    self.audit()
        self.assertEqual(self.created, [])

    def test_cancelled_worker_terminates_and_clears_hook(self):
        hooks = []
        cancelled = [False]
        with self.assertRaises(InterruptedError):
            self.audit(self.process_factory(running=True, mutate=lambda: cancelled.__setitem__(0, True)),
                       cancelled=lambda: cancelled[0], process_hook=hooks.append)
        self.assertTrue(self.created[0].terminated)
        self.assertEqual(hooks[-1], None)

    def test_timeout_terminates_worker(self):
        with patch.object(d.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaises(TimeoutError):
                self.audit(self.process_factory(running=True), timeout_s=1)
        self.assertTrue(self.created[0].terminated)

    def test_cancelled_hook_terminated_process_stays_cancelled(self):
        cancelled = [False]
        def hook(process):
            if process is not None:
                cancelled[0] = True; process.terminate()
        with self.assertRaises(InterruptedError):
            self.audit(self.process_factory(running=True), cancelled=lambda: cancelled[0], process_hook=hook)

    def test_pre_cancelled_check_does_not_launch_process(self):
        with self.assertRaises(InterruptedError):
            self.audit(self.process_factory(running=True), cancelled=lambda: True)
        self.assertEqual(self.created, [])

    def test_source_change_during_check_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed during'):
            self.audit(self.process_factory(mutate=lambda: self.board.write_text('new PCB', encoding='utf-8')))

    def test_native_diagnostics_or_missing_report_never_pass(self):
        for factory in (self.process_factory(diagnostics='Could not compile custom rule'),
                        self.process_factory(missing=True), self.process_factory(value=[])):
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    self.audit(factory)

    def test_manual_profile_requires_explicit_project_mode(self):
        manual = profile()
        manual['rules'][0]['backend'] = 'manual'
        with self.assertRaisesRegex(ValueError, 'no verified native rules'):
            self.audit(selected_profile=manual)
        self.assertEqual(self.created, [])

    def test_project_mode_preserves_original_rules_and_vendor_requirements_unknown(self):
        manual = profile(); manual['rules'][0]['backend'] = 'manual'
        self.board.with_suffix('.kicad_pro').write_text(json.dumps(dict(board=dict(design_settings=dict(
            rule_severities=dict(track_width='ignore'), drc_exclusions=['retained'])))), encoding='utf-8')
        before = d.source_inputs(self.board, CONTEXT)
        result = self.audit(selected_profile=manual, project_drc=True)
        self.assertEqual(d.source_inputs(self.board, CONTEXT), before)
        self.assertEqual(self.created[0].rules_bytes, before[0]['source.kicad_dru'])
        self.assertEqual(self.created[0].project_bytes, before[0]['source.kicad_pro'])
        self.assertIsNone(result['snapshot_overrides'])
        self.assertEqual(result['rule_mode'], 'project')
        self.assertIn('Project DRC only', result['notice'])
        self.assertTrue(all(row['status'] == 'UNKNOWN' for row in result['results']))
        self.assertEqual(result['input_sha256']['source.kicad_dru'],
                         hashlib.sha256(before[0]['source.kicad_dru']).hexdigest())

    def test_project_mode_does_not_synthesize_rules_when_project_has_none(self):
        manual = profile(); manual['rules'][0]['backend'] = 'manual'
        self.board.with_suffix('.kicad_dru').unlink()
        result = self.audit(selected_profile=manual, project_drc=True)
        self.assertIsNone(self.created[0].rules_text)
        self.assertNotIn('source.kicad_dru', result['input_sha256'])
        self.assertTrue(all(row['status'] == 'UNKNOWN' for row in result['results']))

    def test_project_mode_cannot_replace_native_vendor_run(self):
        with self.assertRaisesRegex(ValueError, 'has native vendor rules'):
            self.audit(project_drc=True)
        self.assertEqual(self.created, [])


if __name__ == '__main__':
    unittest.main()
