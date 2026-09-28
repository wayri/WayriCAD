from types import SimpleNamespace

import pytest

from quick_pi_plugin import thermal_selection
from wayricad_runtime import context


class FakeBoard:
    def __init__(self):
        self.parts = [SimpleNamespace(id=SimpleNamespace(value='AAAA')),
                      SimpleNamespace(id=SimpleNamespace(value='BBBB'))]
        self.selected = [self.parts[1]]
    def get_footprints(self):return list(self.parts)
    def get_selection(self):return list(self.selected)
    def clear_selection(self):self.selected = []
    def add_to_selection(self, items):self.selected += items


def test_exact_cross_selection_and_readback(monkeypatch, tmp_path):
    path = tmp_path / 'board.kicad_pcb';path.write_text('board', encoding='utf-8')
    board = FakeBoard()
    client = SimpleNamespace(get_board=lambda:board, run_action=lambda action:1)
    monkeypatch.setattr(context, 'connect', lambda:client)
    monkeypatch.setattr(context, 'saved_board', lambda caller:path.resolve())
    assert thermal_selection.selected_origin_component_ids(path) == ['bbbb']
    result = thermal_selection.select_origin_component(path, 'aaaa')
    assert result == {'selected_id':'aaaa', 'focus':'requested'}
    assert thermal_selection.selected_origin_component_ids(path) == ['aaaa']


def test_stale_or_missing_footprint_does_not_change_selection(monkeypatch, tmp_path):
    path = tmp_path / 'board.kicad_pcb';path.write_text('board', encoding='utf-8')
    board = FakeBoard()
    client = SimpleNamespace(get_board=lambda:board)
    monkeypatch.setattr(context, 'connect', lambda:client)
    monkeypatch.setattr(context, 'saved_board', lambda caller:path.resolve())
    with pytest.raises(ValueError, match='changed'):
        thermal_selection.select_origin_component(path, 'aaaa', expected_sha256='bad')
    with pytest.raises(ValueError, match='uniquely'):
        thermal_selection.select_origin_component(path, 'missing')
    assert board.selected == [board.parts[1]]
