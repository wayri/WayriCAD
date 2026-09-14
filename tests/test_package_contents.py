"""Regression for runtime modules whose names begin with test_."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from build_pcm import create_plugin_zip

class PackageContentsTests(unittest.TestCase):
    def test_runtime_test_point_module_is_shipped_and_test_directory_is_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);plugin=root/'sample_plugin'
            (plugin/'core').mkdir(parents=True);(plugin/'tests').mkdir()
            (plugin/'core/test_point_extractor.py').write_text('VALUE = 42\n')
            (plugin/'tests/test_case.py').write_text('raise RuntimeError("test only")\n')
            path,_=create_plugin_zip(plugin,'3.0.0',root/'out',{})
            with zipfile.ZipFile(path) as archive:
                self.assertIn('plugins/core/test_point_extractor.py',archive.namelist())
                self.assertNotIn('plugins/tests/test_case.py',archive.namelist())
