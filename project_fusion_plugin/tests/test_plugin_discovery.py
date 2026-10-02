"""Exercise the IPC readiness prerequisite and real bundled SWIG module loader."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class DiscoveryTests(unittest.TestCase):
    def test_ipc_readiness_inputs_are_bundled(self):
        metadata=json.loads((ROOT/'metadata.json').read_text(encoding='utf-8'))
        if metadata['versions'][0].get('runtime')=='swig':
            self.assertFalse((ROOT/'plugin.json').exists(),'Compatibility package must not enable IPC discovery')
            for name in ('__init__.py','action.py','icon.png','desktop_entrypoint.py'):
                self.assertTrue((ROOT/name).is_file())
            return
        manifest = json.loads((ROOT / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['runtime']['type'], 'python')
        requirements = ROOT / 'requirements.txt'
        self.assertTrue(requirements.is_file(), 'KiCad cannot mark the IPC action ready without requirements.txt')
        self.assertFalse([line for line in requirements.read_text(encoding='utf-8').splitlines()
                          if line.strip() and not line.lstrip().startswith('#')])
        for action in manifest['actions']:
            self.assertIn('pcb', action['scopes'])
            self.assertTrue((ROOT / action['entrypoint']).is_file())
            for icon in action['icons-light'] + action['icons-dark']:
                self.assertTrue((ROOT / icon).is_file())

    def test_native_swig_loader_requests_exact_action_registration(self):
        try:
            import pcbnew
        except ImportError:
            self.skipTest('Native KiCad Python required')
        name = ROOT.name
        registered = []
        # C++ registration needs a running PCB Editor. Intercept that one boundary,
        # retaining KiCad's actual Python import/discovery and ActionPlugin classes.
        self.assertNotIn(name, sys.modules, 'Run discovery in an isolated process')
        sys.path.insert(0, str(ROOT.parent))
        try:
            with patch.object(pcbnew.PYTHON_ACTION_PLUGINS, 'register_action',
                              side_effect=registered.append):
                pcbnew.LoadPluginModule(str(ROOT.parent), name, ROOT.name)
            self.assertIn(name, pcbnew.KICAD_PLUGINS, pcbnew.GetWizardsBackTrace())
            self.assertEqual([action.name for action in registered], ['Wayri Project Fusion'])
            self.assertTrue(registered[0].show_toolbar_button)
        finally:
            pcbnew.KICAD_PLUGINS.pop(name, None)
            sys.path.remove(str(ROOT.parent))
            for key in list(sys.modules):
                if key == name or key.startswith(name + '.'):
                    sys.modules.pop(key, None)


if __name__ == '__main__':
    unittest.main()
