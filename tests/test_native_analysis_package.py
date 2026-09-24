"""Electrical windows must not run legacy ActionPlugin initializers."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

from wayricad_runtime import native_analysis


def test_repeated_native_frames_use_fresh_package_namespaces(tmp_path):
    roots = []
    for label in ('first', 'second'):
        root = tmp_path / label
        root.mkdir()
        (root / '__init__.py').write_text("raise RuntimeError('legacy ActionPlugin registered')\n",
                                          encoding='utf-8')
        (root / 'signal_integrity_advisor_plugin.py').write_text(
            f"class SignalIntegrityFrame:\n"
            f"    def __init__(self, parent, board, saved_board=False):\n"
            f"        self.identity={label!r}\n"
            f"        self.saved_board=saved_board\n", encoding='utf-8')
        roots.append(root)
    app = object()
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: app))
    pcbnew = SimpleNamespace(LoadBoard=lambda path: SimpleNamespace(path=path))
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        first_app, first = native_analysis.create_frame(roots[0], 'signal_integrity_advisor_plugin',
                                                        tmp_path/'first.kicad_pcb')
        second_app, second = native_analysis.create_frame(roots[1], 'signal_integrity_advisor_plugin',
                                                          tmp_path/'second.kicad_pcb')
    assert first_app is second_app is app
    assert (first.identity, second.identity) == ('first', 'second')
    assert first.saved_board and second.saved_board
    assert first.__class__.__module__ != second.__class__.__module__
