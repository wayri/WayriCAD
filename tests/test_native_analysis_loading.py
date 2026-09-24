"""The electrical loader clears a canceled or failed saved-board load."""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wayricad_runtime import native_analysis


def _fixture(tmp_path):
    root = tmp_path / 'trace'
    root.mkdir()
    (root / 'trace_impedance_plugin.py').write_text(
        "class TraceFrame:\n"
        "    def __init__(self, parent, board, saved_board=False):\n"
        "        self.saved_board = saved_board\n", encoding='utf-8')
    return root


def test_saved_board_load_updates_status_before_frame(tmp_path):
    root = _fixture(tmp_path)
    messages = []
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
    pcbnew = SimpleNamespace(LoadBoard=lambda _path: object())
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        _, frame = native_analysis.create_frame(
            root, 'trace_impedance_plugin', tmp_path / 'board.kicad_pcb',
            status=messages.append, cancelled=lambda: False)
    assert messages == ['Preparing the analysis window…']
    assert frame.saved_board


def test_cancel_after_board_read_prevents_analysis_frame(tmp_path):
    root = _fixture(tmp_path)
    closed = [False]
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
    pcbnew = SimpleNamespace(LoadBoard=lambda _path: object())
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        with pytest.raises(native_analysis.LoadingCancelled):
            native_analysis.create_frame(
                root, 'trace_impedance_plugin', tmp_path / 'board.kicad_pcb',
                status=lambda _text: closed.__setitem__(0, True),
                cancelled=lambda: closed[0])


def test_invalid_saved_board_reports_error(tmp_path):
    root = _fixture(tmp_path)
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
    pcbnew = SimpleNamespace(LoadBoard=lambda _path: None)
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        with pytest.raises(ValueError, match='could not load'):
            native_analysis.create_frame(root, 'trace_impedance_plugin',
                                         tmp_path / 'board.kicad_pcb')
