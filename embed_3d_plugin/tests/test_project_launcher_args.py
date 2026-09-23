"""wx must never parse the already-consumed Embed3D command line."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from embed_3d_plugin import project_launcher


def test_project_window_receives_source_without_wx_reparsing():
    source = 'C:/Projects/Example/board.kicad_pcb'
    dialog = SimpleNamespace(ShowModal=Mock(), Destroy=Mock())

    def app(_redirect):
        assert sys.argv == ['project_launcher.py']
        return object()

    def module(name, _package):
        if name == '.project_launcher':
            return SimpleNamespace(saved_bridge=lambda value: ('bridge', value))
        assert name == '.project_ui'
        return SimpleNamespace(ProjectLibraryDialog=lambda parent, bridge, value: dialog)

    with patch.object(sys, 'argv', ['project_launcher.py', '--source', source]), \
         patch.dict(sys.modules, {'wx': SimpleNamespace(App=app)}), \
         patch.object(project_launcher.importlib, 'import_module', side_effect=module):
        assert project_launcher.main(['--source', source]) == 0
    dialog.ShowModal.assert_called_once_with()
    dialog.Destroy.assert_called_once_with()
