"""Regression for runtime modules whose names begin with test_."""
from pathlib import Path
import tempfile
import unittest
import zipfile
import subprocess
import sys
from build_pcm import create_plugin_zip

class PackageContentsTests(unittest.TestCase):
    def test_analytics_samples_are_available_in_independent_package(self):
        plugin=Path(__file__).resolve().parents[1]/'bom_studio_plugin'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path,_=create_plugin_zip(plugin,'3.6.32',root/'out',{})
            with zipfile.ZipFile(path) as archive:
                archive.extractall(root/'installed')
            code=("import sys;sys.path.insert(0,"+repr(str(root/'installed'/'plugins'))+");"
                  "from bomstudio.server import Application;"
                  "a=Application(demo=True);assert a.workspace;"
                  "a=Application(analytics_demo=True);assert a.workspace;"
                  "a=Application(engineering_demo=True);assert a.workspace")
            result=subprocess.run([sys.executable,'-I','-c',code],cwd=root,
                                  stdin=subprocess.DEVNULL,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_installed_automation_return_audit_has_its_dependencies(self):
        plugin=Path(__file__).resolve().parents[1]/'extract_pins_plugin'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path,_=create_plugin_zip(plugin,'3.4.0',root/'out',{})
            with zipfile.ZipFile(path) as archive:
                archive.extractall(root/'installed')
            code=("import sys;sys.path.insert(0,"+repr(str(root/'installed'))+");"
                  "from plugins import automation;"
                  "module=automation._module('signal_integrity_advisor_plugin/return_path/analysis.py','return_test');"
                  "assert module.ReturnPathAnalyzer().audit([],[],[]).findings==[]")
            result=subprocess.run([sys.executable,'-I','-c',code],cwd=root,
                                  stdin=subprocess.DEVNULL,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

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


class AssistantBackendBundleTests(unittest.TestCase):
    def test_backend_payload_is_inert_complete_and_excludes_private_test_files(self):
        from build_pcm import bundle_assistant_backends
        import json
        import runpy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'LICENSE').write_text('Suite license', encoding='utf-8')
            plugin = root / 'sample_backend_plugin'
            plugin.mkdir()
            (plugin / 'metadata.json').write_text(json.dumps({'versions': [{'version': '1.2.3'}]}))
            (plugin / '__init__.py').write_text('raise RuntimeError("must not register actions")')
            for name in ('cli.py', 'help.html', 'LICENSE.thirdparty', 'test_points/fixture.py',
                         'tests/test_hidden.py', '.private/token.txt', '__pycache__/cached.pyc',
                         '.env', 'build.log'):
                source = plugin / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text('production' if name.endswith('.html') else '# fixture')
            assistant = root / 'suite_assistant_plugin'
            assistant.mkdir()
            (assistant / 'metadata.json').write_text('{}')
            target = root / 'assistant.zip'
            with zipfile.ZipFile(target, 'w') as archive:
                bundle_assistant_backends(archive, root)
            prefix = 'plugins/_suite/sample_backend_plugin/'
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                for name in ('cli.py', 'help.html', 'LICENSE', 'LICENSE.thirdparty', 'test_points/fixture.py'):
                    self.assertIn(prefix + name, names)
                self.assertFalse(any('/tests/' in name or '/.private/' in name or
                                     name.endswith(('.pyc', '.env', '.log')) for name in names))
                self.assertFalse(any('/suite_assistant_plugin/' in name for name in names))
                archive.extractall(root / 'installed')
            initializer = root / 'installed' / prefix / '__init__.py'
            self.assertEqual(runpy.run_path(str(initializer))['__version__'], '1.2.3')
