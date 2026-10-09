from types import SimpleNamespace as NS
import hashlib

import pytest

from wayricad_runtime import analysis_selection as selection, context


def item(identifier, net='GND'):
    return NS(id=NS(value=identifier), net=NS(name=net))


class Board:
    def __init__(self):
        self.pad = item('PAD')
        self.fp = item('FP');self.fp.definition = NS(pads=[self.pad])
        self.track = item('TRACK')
        self.via = item('VIA')
        self.selected = [self.fp]
        self.drop_once = False
    def get_footprints(self):return [self.fp]
    def get_tracks(self):return [self.track]
    def get_vias(self):return [self.via]
    def get_selection(self):return self.selected[:]
    def clear_selection(self):self.selected = []
    def add_to_selection(self, items):
        if self.drop_once:
            self.drop_once = False
            return
        self.selected += items


@pytest.fixture
def origin(monkeypatch, tmp_path):
    path = tmp_path / 'board.kicad_pcb';path.write_text('snapshot', encoding='utf-8')
    board = Board();actions = []
    client = NS(get_board=lambda:board, run_action=actions.append)
    monkeypatch.setattr(context, 'connect', lambda:client)
    monkeypatch.setattr(context, 'saved_board', lambda caller:path.resolve())
    return path, board, actions


def test_exact_full_selection_readback_and_focus(origin):
    path, board, actions = origin
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert selection.select_origin(path, ['PAD', 'TRACK', 'VIA'], expected_sha256=sha, focus=True) == 3
    assert selection.selected_origin_ids(path, expected_sha256=sha) == ['pad','track','via']
    assert actions == ['common.Control.zoomFitSelection']


def test_missing_uuid_never_clears_previous_selection(origin):
    path, board, _ = origin
    with pytest.raises(ValueError, match='uniquely'):
        selection.select_origin(path, ['PAD','missing'])
    assert board.selected == [board.fp]


def test_host_partial_selection_restores_prior(origin):
    path, board, _ = origin
    board.drop_once = True
    with pytest.raises(RuntimeError, match='confirm'):
        selection.select_origin(path, ['TRACK'])
    assert board.selected == [board.fp]


def test_changed_file_or_wrong_editor_refuses_navigation(origin, monkeypatch):
    path, board, _ = origin
    with pytest.raises(ValueError, match='changed after analysis'):
        selection.select_origin(path, ['TRACK'], expected_sha256='stale')
    monkeypatch.setattr(context, 'saved_board', lambda caller:path.with_name('other.kicad_pcb'))
    with pytest.raises(ValueError, match='changed boards'):
        selection.selected_origin_ids(path)
    assert board.selected == [board.fp]


def test_ambiguous_uuid_refuses_navigation(origin):
    path, board, _ = origin
    board.via.id.value = 'TRACK'
    with pytest.raises(ValueError, match='uniquely'):
        selection.select_origin(path, ['TRACK'])
    assert board.selected == [board.fp]


def test_explicit_net_and_legacy_board_object(origin):
    path, board, _ = origin
    board.via.net.name = 'VCC'
    legacy = NS(GetFileName=lambda:str(path))
    assert selection.select_origin(legacy, net='VCC') == 1
    assert board.selected == [board.via]
