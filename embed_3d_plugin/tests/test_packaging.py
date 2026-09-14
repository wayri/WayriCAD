"""Contracts for Embed3D in the unified WayriCAD package builder."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from build_pcm import create_plugin_zip, normalize_metadata
from embed_3d_plugin import __version__

ROOT = Path(__file__).resolve().parents[1]

class PackageTests(unittest.TestCase):
    def metadata(self):
        return normalize_metadata(json.loads((ROOT/'metadata.json').read_text()), ROOT, 'develop')

    def test_runtime_and_metadata_agree(self):
        metadata = self.metadata()
        self.assertEqual(__version__, metadata['versions'][0]['version'])
        self.assertEqual('ipc', metadata['versions'][0]['runtime'])
        self.assertEqual('testing', metadata['versions'][0]['status'])
        self.assertEqual('10.0', metadata['versions'][0]['kicad_version'])
        manifest = json.loads((ROOT/'plugin.json').read_text())
        self.assertEqual(metadata['identifier'], manifest['identifier'])
        self.assertTrue((ROOT/manifest['actions'][0]['entrypoint']).is_file())

    def test_invalid_runtime_rejected(self):
        metadata = self.metadata()
        metadata['versions'][0]['runtime'] = 'imaginary'
        with self.assertRaises(ValueError):
            normalize_metadata(metadata, ROOT, 'develop')

    def test_independent_reproducible_flat_archive(self):
        with tempfile.TemporaryDirectory() as raw, contextlib.redirect_stdout(io.StringIO()):
            path, _ = create_plugin_zip(ROOT, __version__, raw, self.metadata())
            first = path.read_bytes()
            path, _ = create_plugin_zip(ROOT, __version__, raw, self.metadata())
            self.assertEqual(first, path.read_bytes())
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                for name in ('plugins/__init__.py', 'plugins/plugin.py', 'plugins/plugin.json',
                             'plugins/wayricad_runtime/ipc.py', 'plugins/LICENSE', 'resources/icon.png'):
                    self.assertIn(name, names)
                self.assertFalse(any(n.startswith('plugins/embed_3d_plugin/') for n in names))
                self.assertFalse(any('/tests/' in n or '/__pycache__/' in n for n in names))
                self.assertEqual(archive.read('plugins/plugin.py'), (ROOT/'plugin.py').read_bytes())
