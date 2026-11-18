import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile

from quick_therm_plugin import solver_setup as setup


class SolverSetupTests(unittest.TestCase):
    def test_pinned_install_cache_reuse_and_corruption_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'solver.zip'
            binary = b'reviewed fixture executable'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr(setup.MEMBER, binary)
                bundle.writestr('calculix_2.23_4win/README_Install', 'source and license')
                bundle.writestr('../never-extract.txt', 'not selected')
            with patch.object(setup.sys, 'platform', 'win32'), \
                 patch.object(setup.platform, 'machine', return_value='AMD64'), \
                 patch.object(setup, 'ARCHIVE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                 patch.object(setup, 'BINARY_SHA256', hashlib.sha256(binary).hexdigest()), \
                 patch.object(setup.subprocess, 'run', return_value=Mock(stdout='Version 2.23', stderr='')) as run:
                installed = Path(setup.ensure_calculix(root=root, archive=archive))
                self.assertEqual(installed.read_bytes(), binary)
                self.assertTrue(installed.with_name('provenance.json').is_file())
                self.assertFalse((root / 'never-extract.txt').exists())
                self.assertEqual(setup.ensure_calculix(root=root), str(installed))
                self.assertEqual(run.call_count, 1)
                installed.write_bytes(b'corrupt')
                with self.assertRaisesRegex(RuntimeError, 'integrity'):
                    setup.ensure_calculix(root=root)
                self.assertEqual(installed.read_bytes(), b'corrupt')

    def test_bad_archive_never_launches_or_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'bad.zip'
            archive.write_bytes(b'bad')
            with patch.object(setup.sys, 'platform', 'win32'), \
                 patch.object(setup.platform, 'machine', return_value='AMD64'), \
                 patch.object(setup.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    setup.ensure_calculix(root=root, archive=archive)
                run.assert_not_called()
                self.assertFalse((root / 'calculix-2.23-win64').exists())

    def test_non_windows_setup_gives_offline_path(self):
        with patch.object(setup.sys, 'platform', 'linux'):
            self.assertIsNone(setup.cached_calculix())
            with self.assertRaisesRegex(RuntimeError, 'OS package manager'):
                setup.ensure_calculix()
