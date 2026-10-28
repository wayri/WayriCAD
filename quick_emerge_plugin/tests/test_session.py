import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from quick_emerge_plugin.session import StudySession


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
    def poll(self): return self.returncode
    def terminate(self):
        self.terminated = True
        self.returncode = -15
    def wait(self, timeout=None): return self.returncode
    def kill(self): self.returncode = -9


class SessionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / '.tmp'
        root.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / 'board.kicad_pcb'
        self.board.write_bytes(b'board')
        self.session = StudySession(self.board)
        self.disk = patch('quick_emerge_plugin.session.shutil.disk_usage', return_value=type('Disk', (), {'free': 2 * 1024**3})())
        self.disk.start()
        self.addCleanup(self.disk.stop)

    def test_preview_required_and_changes_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Preview'):
            self.session.start({}, sys.executable, self.root)
        self.session.preview({})
        with self.assertRaisesRegex(ValueError, 'Preview'):
            self.session.start({'er': 4}, sys.executable, self.root)
        self.board.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'PCB changed'):
            self.session.start({}, sys.executable, self.root)

    def test_solver_library_hint_is_child_local_and_other_environment_keys_rejected(self):
        import os
        self.session.preview({})
        before=os.environ.get('EMERGE_PARDISO_PATH')
        proc=FakeProcess()
        with patch('quick_emerge_plugin.session.subprocess.Popen',return_value=proc) as popen:
            self.session.start({},sys.executable,self.root,solver_environment={'EMERGE_PARDISO_PATH':'C:/Runtime/mkl_rt.dll'})
        self.assertEqual(popen.call_args.kwargs['env']['EMERGE_PARDISO_PATH'],'C:/Runtime/mkl_rt.dll')
        self.assertEqual(os.environ.get('EMERGE_PARDISO_PATH'),before)
        self.session.cancel()
        with self.assertRaisesRegex(ValueError,'solver-library'):
            self.session.start({},sys.executable,self.root,solver_environment={'PYTHONPATH':'unreviewed'})

    def test_worker_command_and_isolated_run(self):
        self.session.preview({})
        proc = FakeProcess()
        with patch('quick_emerge_plugin.session.subprocess.Popen', return_value=proc) as popen:
            self.session.start({}, sys.executable, self.root)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], str(Path(sys.executable).resolve()))
        self.assertEqual(args[0][1], '-I')
        self.assertEqual(args[0][-2], '--worker')
        self.assertEqual(Path(args[0][-1]), self.session.run_dir / 'request.json')
        self.assertEqual(kwargs['cwd'], self.session.run_dir)
        self.assertEqual(self.session.run_dir.parent, self.root)
        self.assertNotEqual(self.session.run_dir, self.root)
        self.session.cancel()

    def test_success_and_mismatched_result(self):
        for mismatch in (False, True):
            session = StudySession(self.board)
            review = session.preview({})
            proc = FakeProcess()
            with patch('quick_emerge_plugin.session.subprocess.Popen', return_value=proc):
                session.start({}, sys.executable, self.root)
            result = {'source': review['source'], 'config_sha256': 'wrong' if mismatch else review['config_sha256']}
            (session.run_dir / 'result.json').write_text(json.dumps(result), encoding='utf-8')
            (session.run_dir / 'status.json').write_text(json.dumps({'status': 'completed'}), encoding='utf-8')
            proc.returncode = 0
            if mismatch:
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    session.collect()
            else:
                self.assertEqual(session.collect(), result)
            self.assertTrue(session.log.closed)

    def test_cancel_status_and_log(self):
        self.session.preview({})
        proc = FakeProcess()
        with patch('quick_emerge_plugin.session.subprocess.Popen', return_value=proc):
            self.session.start({}, sys.executable, self.root)
        self.session.cancel()
        self.assertTrue(proc.terminated)
        self.assertTrue(self.session.log.closed)
        self.assertEqual(json.loads((self.session.run_dir / 'status.json').read_text())['status'], 'cancelled')
        self.assertIsNone(self.session.process)

    @unittest.skipIf(importlib.util.find_spec('emerge') is not None, 'requires environment without EMerge')
    def test_missing_runtime_worker(self):
        self.session.preview({})
        self.session.start({}, sys.executable, self.root)
        self.session.process.wait(timeout=30)
        with self.assertRaisesRegex(RuntimeError, 'EMerge is missing'):
            self.session.collect()
        self.assertTrue(self.session.log.closed)
        self.assertEqual(json.loads((self.session.run_dir / 'status.json').read_text())['status'], 'failed')


if __name__ == '__main__': unittest.main()
