"""macOS OS-owned aliases must not be confused with project symlink escapes."""
from pathlib import Path
import unittest
from unittest.mock import patch
from embed_3d_plugin import board_package


class SystemAliasTests(unittest.TestCase):
    def check(self, path, links, platform='darwin'):
        with patch.object(board_package.sys, 'platform', platform), \
             patch.object(Path, 'is_symlink', lambda item: item.as_posix() in links), \
             patch.object(Path, 'resolve', lambda item: Path(links.get(item.as_posix(), item.as_posix()))):
            board_package._no_symlinks(Path(path))

    def test_macos_temporary_folder_alias_is_allowed(self):
        self.check('/var/folders/project/output', {'/var': '/private/var'})
        self.check('/tmp/project/output', {'/tmp': '/private/tmp'})
        self.check('/etc/project/output', {'/etc': '/private/etc'})

    def test_arbitrary_project_symlink_remains_rejected(self):
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.check('/var/folders/project/output', {'/var': '/private/var',
                       '/var/folders/project': '/elsewhere'})

    def test_root_alias_with_unexpected_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.check('/var/folders/project/output', {'/var': '/elsewhere'})

    def test_alias_exception_is_macos_only(self):
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.check('/var/folders/project/output', {'/var': '/private/var'}, platform='linux')


if __name__ == '__main__':
    unittest.main()
