import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quick_emerge_plugin import backend, compatibility, dependencies as dep


class DependencyTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / '.tmp'
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manager = dep.DependencyManager(self.root/'managed')
        self.manager.home.mkdir()
        self.commands = []
        self.failure = None
        self.bad_certificate = False
        self.installed_versions = {}
        self.patches = [patch.object(dep, 'latest_release', return_value='3.1.0'),
                        patch.object(dep, 'discover_python', return_value=Path('base-python')),
                        patch.object(dep, 'run_command', side_effect=self.runner),
                        patch.object(dep.shutil, 'disk_usage', return_value=SimpleNamespace(free=dep.MIN_FREE_BYTES)),
                        patch.object(dep.subprocess, 'run', side_effect=self.metadata_probe)]
        self.latest, self.discover, self.run, self.disk, self.probe = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def certificate(self, folder, version, output=None):
        backend.atomic_json(output or folder/compatibility.CERTIFICATE_NAME,
                            dict(schema=1, issuer=compatibility.CERTIFICATE_ISSUER, version=version,
                                 adapter_signature='stale' if self.bad_certificate else compatibility.adapter_signature()))

    def metadata_probe(self, argv, **kwargs):
        python = Path(argv[0])
        folder = python.parent.parent
        certificate = json.loads((folder/compatibility.CERTIFICATE_NAME).read_text())
        version = self.installed_versions.get(folder.name, certificate['version'])
        return SimpleNamespace(returncode=0, stdout=version+'\n')

    def runtime(self, name='old', version='3.0.0b9'):
        folder = self.manager.home/name
        folder.mkdir()
        python = dep.environment_python(folder)
        python.parent.mkdir(parents=True)
        python.touch()
        self.certificate(folder, version)
        return folder

    def state(self, **values):
        backend.atomic_json(self.manager.home/'active.json', dict(schema=1, **values))

    def runner(self, argv, **kwargs):
        argv = [str(v) for v in argv]
        self.commands.append(argv)
        # Every setup command must leave the previous active state intact.
        current = self.manager._read_state().get('active')
        self.assertIn(current, (None, 'old'))
        if self.failure and self.failure in argv:
            raise RuntimeError('injected command failure')
        if 'venv' in argv:
            python = dep.environment_python(argv[-1])
            python.parent.mkdir(parents=True, exist_ok=True)
            python.touch()
        if '--qualify-runtime' in argv:
            folder = Path(argv[-1]).parent
            version = json.loads((folder/'managed.json').read_text())['version']
            self.certificate(folder, version, output=Path(argv[-1]))

    def test_first_open_install_sequence_and_activation(self):
        result = self.manager.ensure()
        self.assertEqual(result['version'], '3.1.0')
        self.assertEqual(len(self.commands), 4)
        self.assertIn('venv', self.commands[0])
        self.assertIn('emerge==3.1.0', self.commands[1])
        self.assertIn('check', self.commands[2])
        self.assertIn('--qualify-runtime', self.commands[3])
        self.assertEqual(self.manager.active()['environment'], result['environment'])

    def test_first_open_latest_failure_falls_back_to_baseline(self):
        rejected = []

        def runner(argv, **kwargs):
            if '--qualify-runtime' in [str(v) for v in argv]:
                folder = Path(argv[-1]).parent
                version = json.loads((folder/'managed.json').read_text())['version']
                if version == '3.1.0':
                    rejected.append(folder)
                    raise RuntimeError('latest API incompatible')
            return self.runner(argv, **kwargs)

        self.run.side_effect = runner
        result = self.manager.ensure()
        self.assertEqual(result['version'], dep.SUPPORTED_VERSION)
        self.assertIn(dep.SUPPORTED_VERSION, result['message'])
        self.assertNotIn('3.1.0', result['message'])
        self.assertEqual(len(rejected), 1)
        self.assertFalse(rejected[0].exists())
        self.assertEqual(self.manager.active()['version'], dep.SUPPORTED_VERSION)
        self.assertIsNone(self.manager._read_state()['previous'])
        self.assertEqual([p.name for p in self.manager.home.iterdir() if p.is_dir()],
                         [result['environment']])

    def test_failed_candidate_keeps_old_and_preserves_unrelated_directories(self):
        old = self.runtime()
        unrelated = self.manager.home/'preexisting-candidate'
        unrelated.mkdir()
        (unrelated/'unique.txt').write_text('preserve')
        self.state(active='old', checked_at=0)
        self.failure = 'install'
        result = self.manager.ensure()
        self.assertEqual(result['environment'], 'old')
        self.assertTrue(old.exists())
        self.assertEqual((unrelated/'unique.txt').read_text(), 'preserve')
        self.assertEqual(sorted(p.name for p in self.manager.home.iterdir() if p.is_dir()), ['old', 'preexisting-candidate'])
        self.assertEqual(self.manager._read_state()['rejected'][0], '3.1.0')

    def test_daily_cache_skips_network_and_install(self):
        self.runtime()
        self.state(active='old', checked_at=dep.time.time())
        self.assertEqual(self.manager.ensure()['environment'], 'old')
        self.latest.assert_not_called()
        self.run.assert_not_called()

    def stale_owned_runtime(self):
        folder = self.runtime()
        backend.atomic_json(folder/'managed.json', dict(schema=1, owner='quick-emerge', version='3.0.0b9'))
        certificate = json.loads((folder/compatibility.CERTIFICATE_NAME).read_text())
        certificate['adapter_signature'] = 'old-adapter'
        backend.atomic_json(folder/compatibility.CERTIFICATE_NAME, certificate)
        self.state(active='old', checked_at=dep.time.time())
        return folder

    def test_stale_source_requalifies_existing_environment_without_install(self):
        folder = self.stale_owned_runtime()
        self.disk.return_value.free = 2 * 1024**3
        state_before = (self.manager.home/'active.json').read_bytes()
        marker = folder/'packages-unchanged.txt'
        marker.write_bytes(b'unchanged')
        result = self.manager.ensure()
        self.assertEqual(result['environment'], 'old')
        self.assertEqual(len(self.commands), 2)
        self.assertIn('check', self.commands[0])
        self.assertIn('--qualify-runtime', self.commands[1])
        self.assertIn('qualification-pending-', self.commands[1][-1])
        self.assertEqual((self.manager.home/'active.json').read_bytes(), state_before)
        self.assertEqual(marker.read_bytes(), b'unchanged')
        self.assertIsNotNone(compatibility.runtime_certificate(folder))
        self.assertEqual(list(folder.glob('qualification-pending-*')), [])
        self.latest.assert_not_called()
        self.discover.assert_not_called()

    def test_requalification_failure_retains_certificate_and_state(self):
        folder = self.stale_owned_runtime()
        old_certificate = (folder/compatibility.CERTIFICATE_NAME).read_bytes()
        old_state = (self.manager.home/'active.json').read_bytes()
        self.disk.return_value.free = 2 * 1024**3

        def fail_after_pending(argv, **kwargs):
            self.runner(argv, **kwargs)
            if '--qualify-runtime' in [str(v) for v in argv]:
                raise RuntimeError('injected qualification failure')

        self.run.side_effect = fail_after_pending
        with self.assertRaisesRegex(RuntimeError, 'requalification failed'):
            self.manager.ensure()
        self.assertEqual((folder/compatibility.CERTIFICATE_NAME).read_bytes(), old_certificate)
        self.assertEqual((self.manager.home/'active.json').read_bytes(), old_state)
        self.assertIsNone(self.manager.active())
        self.assertEqual(list(folder.glob('qualification-pending-*')), [])

    def test_requalification_cancel_retains_certificate_and_cleans_pending(self):
        folder = self.stale_owned_runtime()
        old_certificate = (folder/compatibility.CERTIFICATE_NAME).read_bytes()

        def cancel_after_pending(argv, **kwargs):
            self.runner(argv, **kwargs)
            if '--qualify-runtime' in [str(v) for v in argv]:
                raise dep.SetupCancelled('cancelled')

        self.run.side_effect = cancel_after_pending
        with self.assertRaises(dep.SetupCancelled):
            self.manager.ensure()
        self.assertEqual((folder/compatibility.CERTIFICATE_NAME).read_bytes(), old_certificate)
        self.assertEqual(list(folder.glob('qualification-pending-*')), [])

    def test_concurrent_lock_rejects_second_setup(self):
        with dep.setup_lock(self.manager.home):
            with self.assertRaisesRegex(RuntimeError, 'Another Quick EMerge'):
                self.manager.ensure()
        self.run.assert_not_called()

    def test_low_disk_blocks_first_install_and_defers_update(self):
        self.disk.return_value.free = dep.MIN_FREE_BYTES - 1
        with self.assertRaisesRegex(RuntimeError, '3 GiB'):
            self.manager.ensure()
        self.runtime()
        self.state(active='old', checked_at=0)
        result = self.manager.ensure()
        self.assertEqual(result['environment'], 'old')
        self.assertIn('deferred', result['message'])
        self.run.assert_not_called()

    def test_runner_cancellation_keeps_active_and_removes_candidate(self):
        self.runtime()
        self.state(active='old', checked_at=0)
        self.run.side_effect = dep.SetupCancelled('cancelled during process')
        with self.assertRaises(dep.SetupCancelled):
            self.manager.ensure()
        self.assertEqual(self.manager.active()['environment'], 'old')
        self.assertEqual([p.name for p in self.manager.home.iterdir() if p.is_dir()], ['old'])

    def test_cancel_before_work_does_not_create_candidate(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(dep.SetupCancelled):
            self.manager.ensure(cancel=cancel)
        self.run.assert_not_called()

    def test_rollback_swaps_compatible_environments(self):
        self.runtime()
        self.runtime('previous', '3.0.0b8')
        self.state(active='old', previous='previous', checked_at=0)
        self.assertEqual(self.manager.rollback()['environment'], 'previous')
        self.assertEqual(self.manager._read_state()['previous'], 'old')
        self.assertEqual(self.manager.rollback()['environment'], 'old')

    def test_stale_candidate_certificate_is_not_activated(self):
        self.runtime()
        self.state(active='old', checked_at=0)
        self.bad_certificate = True
        self.assertEqual(self.manager.ensure()['environment'], 'old')
        self.assertEqual([p.name for p in self.manager.home.iterdir() if p.is_dir()], ['old'])

    def test_stale_active_and_rollback_certificates_rejected(self):
        self.bad_certificate = True
        self.runtime()
        self.state(active='old', previous='old')
        self.assertIsNone(self.manager.active())
        with self.assertRaises(RuntimeError):
            self.manager.rollback()

    def test_installed_metadata_mismatch_rejects_active_and_rollback(self):
        self.runtime()
        self.runtime('previous', '3.0.0b8')
        self.state(active='old', previous='previous')
        self.installed_versions.update(old='3.2.0', previous='2.9.0')
        self.assertIsNone(self.manager.active())
        with self.assertRaises(RuntimeError):
            self.manager.rollback()

    def test_malformed_manifest_cannot_escape_home(self):
        outside = self.root/'outside'
        outside.mkdir()
        marker = outside/'keep.txt'
        marker.write_text('unique')
        for name in ('../outside', str(outside), '.', None, {}, ['old']):
            with self.subTest(name=name):
                self.state(active=name, previous=name)
                self.assertIsNone(self.manager.active())
                with self.assertRaises(RuntimeError):
                    self.manager.rollback()
                self.assertEqual(marker.read_text(), 'unique')
        (self.manager.home/'active.json').write_text('{bad json')
        self.assertIsNone(self.manager.active())

    def test_release_selection_includes_prereleases_excludes_yanked_and_dev(self):
        metadata = {'releases': {'2.9': [{}], '3.0.0b9': [{}], '3.0.0rc1': [{}],
                                 '3.1.0.dev1': [{}], '9.0': [{'yanked': True}],
                                 'bad': [{}], '8.0': [], '3.0.0b8': [{'yanked': True}, {}]}}
        self.assertEqual(dep.select_release(metadata), '3.0.0rc1')
        with self.assertRaises(RuntimeError):
            dep.select_release({'releases': {'2.9': [{}], '3.0': [{'yanked': True}]}})


class RunnerCancellationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / '.tmp'
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.log = Path(temporary.name)/'runner.log'

    def run_interrupted(self, *, taskkill_error, low_disk=False):
        cancel = threading.Event()
        process = Mock(pid=4321)
        process.poll.return_value = None
        process.wait.return_value = 0

        def spawn(*args, **kwargs):
            if not low_disk:
                cancel.set()  # Cancellation arrives after a process exists.
            return process

        # Replace this module's os reference without altering pathlib's host OS.
        windows = SimpleNamespace(name='nt', environ=dep.os.environ)
        with patch.object(dep, 'os', windows), \
                patch.object(dep.subprocess, 'Popen', side_effect=spawn) as popen, \
                patch.object(dep.subprocess, 'run', side_effect=taskkill_error) as taskkill, \
                patch.object(dep.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            expected = RuntimeError if low_disk else dep.SetupCancelled
            with self.assertRaises(expected) as raised:
                dep.run_command(['fake-python', 'installer'], log=self.log, cancel=cancel)
        if low_disk:
            self.assertIn('disk space', str(raised.exception))
        self.assertFalse(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(taskkill.call_args.args[0], ['taskkill', '/PID', '4321', '/T', '/F'])
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=10)
        process.kill.assert_not_called()

    def test_cancel_reaps_worker_when_taskkill_times_out(self):
        self.run_interrupted(taskkill_error=dep.subprocess.TimeoutExpired('taskkill', 15))

    def test_cancel_reaps_worker_when_taskkill_fails_to_start(self):
        self.run_interrupted(taskkill_error=OSError('taskkill unavailable'))

    def test_low_disk_during_command_reaps_worker(self):
        self.run_interrupted(taskkill_error=OSError('taskkill unavailable'), low_disk=True)


if __name__ == '__main__':
    unittest.main()
