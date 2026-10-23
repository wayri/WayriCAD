"""Snapshot write guards and bounded isolated preview lifecycle."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wayricad_runtime import routing_worker as worker


class RoutingWorkerTests(unittest.TestCase):
    def test_invalid_budgets_never_start_a_thread(self):
        for value in (float('nan'), float('inf'), 0, -1, 301, True):
            with self.subTest(value=value), patch.object(worker.threading, 'Thread') as thread:
                with self.assertRaises(ValueError):worker.start_job(None,None,{},timeout=value)
                thread.assert_not_called()

    def test_saved_guard_reuses_fresh_checked_fingerprint_and_binds_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'board.kicad_pcb';source.write_text('board')
            rule=source.with_suffix('.kicad_dru');rule.write_text('rules')
            board=Mock();board.GetFileName.return_value=str(source)
            identity={'mode':'saved','source':str(source.resolve()),'source_fingerprint':'checked',
                      'companions':{'.kicad_dru':worker._hash(b'rules')}}
            with patch('wayricad_runtime.geometry.board_fingerprint',side_effect=AssertionError('duplicate scan')):
                worker.assert_current(board,None,identity,current_fingerprint='checked')
                rule.write_text('changed')
                with self.assertRaisesRegex(ValueError,'rules changed'):
                    worker.assert_current(board,None,identity,current_fingerprint='checked')

    def test_saved_guard_rejects_geometry_and_selected_scope_changes(self):
        board=Mock();board.GetFileName.return_value='example.kicad_pcb'
        identity={'mode':'saved','source':str(Path('example.kicad_pcb').resolve()),
                  'source_fingerprint':'original'}
        with self.assertRaisesRegex(ValueError,'Board changed'):
            worker.assert_current(board,None,identity,current_fingerprint='edited')
        identity.update(selection_scope='Selected pads',selection={'pads':['one'],'footprints':[]})
        with self.assertRaisesRegex(ValueError,'selection changed'):
            worker.assert_current(board,None,identity,selection={'pads':['two'],'footprints':[]},current_fingerprint='original')

    def test_cancel_during_runtime_setup_never_launches_a_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=worker.RoutingJob.__new__(worker.RoutingJob)
            job._directory=Path(temporary);job._saved=False;job._native_identity={'source':'','snapshot_sha256':'x'}
            job._cancel=worker.threading.Event();job._process=None;job._closed=False;job._error=None
            job.kind='identity';job.include_context=False;job.settings={};job.timeout=10;job.started=worker.time.monotonic()
            def runtime(*args,**kwargs):job.cancel();return 'unused'
            with patch('wayricad_runtime.runtime_setup.ensure_runtime',side_effect=runtime),patch.object(worker.subprocess,'Popen') as process:
                job._work();process.assert_not_called()
            self.assertIn('cancelled',str(job._error))

    def test_exited_worker_still_obeys_log_budget_and_is_reaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=worker.RoutingJob.__new__(worker.RoutingJob)
            job._directory=Path(temporary);job._saved=False;job._native_identity={'source':'','snapshot_sha256':'x'}
            job._cancel=worker.threading.Event();job._process=None;job._closed=False;job._error=None
            job.kind='identity';job.include_context=False;job.settings={};job.timeout=10;job.started=worker.time.monotonic()
            process=Mock();process.poll.return_value=0
            def launch(*args,**kwargs):
                kwargs['stdout'].truncate(8*1024*1024+1)
                return process
            with patch('wayricad_runtime.runtime_setup.ensure_runtime',return_value='unused'),patch.object(worker.subprocess,'Popen',side_effect=launch):
                job._work()
            self.assertIn('log budget',str(job._error));process.wait.assert_called_once()


if __name__=='__main__':unittest.main()
