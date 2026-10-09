"""Windows report-publication locks cannot weaken atomic/fail-closed exports."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from bomstudio.automation import _publish_directory, pipeline, default_pipeline
from test_core import Fixture, BASE


def sharing_error(code=32):
    error = PermissionError('Synthetic Windows sharing/access denial')
    error.winerror = code
    return error


class DirectoryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / '.stage'
        self.stage.mkdir()
        (self.stage / 'report.txt').write_text('complete report')
        self.out = self.root / 'run'

    def test_temporary_lock_retries_atomic_rename(self):
        rename = Path.rename
        attempts = []
        def publish(stage, out):
            attempts.append(stage)
            if len(attempts) == 1:
                raise sharing_error()
            return rename(stage, out)
        validate = Mock()
        with patch.object(Path, 'rename', publish), patch('time.sleep'):
            _publish_directory(self.stage, self.out, validate)
        self.assertEqual((self.out / 'report.txt').read_text(), 'complete report')
        self.assertFalse(self.stage.exists())
        self.assertEqual(validate.call_count, 2)

    def test_destination_created_during_wait_is_preserved(self):
        def contender(_):
            self.out.mkdir()
            (self.out / 'other.txt').write_text('other run')
        with patch.object(Path, 'rename', side_effect=sharing_error()), patch('time.sleep', contender):
            with self.assertRaises(FileExistsError):
                _publish_directory(self.stage, self.out, lambda: None)
        self.assertEqual((self.out / 'other.txt').read_text(), 'other run')
        self.assertFalse((self.out / 'report.txt').exists())
        self.assertTrue(self.stage.exists())

    def test_changed_inputs_block_retry(self):
        validate = Mock(side_effect=[None, ValueError('Source or release evidence changed')])
        with patch.object(Path, 'rename', side_effect=sharing_error()), patch('time.sleep'):
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                _publish_directory(self.stage, self.out, validate)
        self.assertFalse(self.out.exists())
        self.assertTrue(self.stage.exists())

    def test_destination_created_during_revalidation_is_preserved(self):
        with patch.object(Path, 'rename') as rename:
            with self.assertRaises(FileExistsError):
                _publish_directory(self.stage, self.out, self.out.mkdir)
        rename.assert_not_called()
        self.assertTrue(self.out.is_dir())
        self.assertTrue(self.stage.exists())

    def test_permanent_windows_denial_is_bounded(self):
        with patch.object(Path, 'rename', side_effect=sharing_error(5)) as rename, patch('time.sleep'):
            with self.assertRaises(PermissionError):
                _publish_directory(self.stage, self.out, lambda: None)
        self.assertLessEqual(rename.call_count, 5)
        self.assertFalse(self.out.exists())
        self.assertTrue(self.stage.exists())

    def test_other_permission_denial_is_not_retried(self):
        with patch.object(Path, 'rename', side_effect=PermissionError('permanent ACL denial')) as rename, patch('time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                _publish_directory(self.stage, self.out, lambda: None)
        self.assertEqual(rename.call_count, 1)
        sleep.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Native Windows handle-sharing test')
    def test_native_windows_directory_lock_then_release(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(self.stage), 0x80000000, 3, None, 3, 0x02000000, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value, ctypes.get_last_error())
        timer = None
        try:
            with self.assertRaises(PermissionError) as blocked:
                self.stage.rename(self.out)
            self.assertIn(blocked.exception.winerror, (5, 32, 33))
            timer = threading.Timer(.12, kernel.CloseHandle, [handle])
            timer.start()
            _publish_directory(self.stage, self.out, lambda: None)
            self.assertEqual((self.out / 'report.txt').read_text(), 'complete report')
        finally:
            if timer is None:
                kernel.CloseHandle(handle)
            else:
                timer.join(5)


class PipelinePublicationTests(Fixture):
    def test_exhausted_lock_cleans_only_owned_stage(self):
        config = dict(default_pipeline(), variants=[BASE], reports=['checks'], formats=['csv'])
        before = self.ws.project.root.read_bytes()
        with patch.object(Path, 'rename', side_effect=sharing_error(5)), patch('time.sleep'):
            with self.assertRaises(PermissionError):
                pipeline(self.ws, config, self.dir / 'new-run')
        self.assertFalse((self.dir / 'new-run').exists())
        self.assertEqual(list(self.dir.glob('.wayricad-run-*')), [])
        self.assertEqual(self.ws.project.root.read_bytes(), before)
