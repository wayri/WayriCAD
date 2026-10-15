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


def test_bulk_uuid_lookup_avoids_full_board_reads(origin, monkeypatch):
    path, board, _ = origin
    calls = []
    monkeypatch.setattr(selection, '_request_ids', lambda values: values)
    board.get_items_by_id = lambda ids: calls.append(ids) or [board.pad, board.track]
    board.get_footprints = lambda: pytest.fail('Bulk UUID selection must not fetch all footprints')
    board.get_tracks = lambda: pytest.fail('Bulk UUID selection must not fetch all tracks')
    assert selection.select_origin(path, ['PAD', 'TRACK'], additive=True) == 3
    assert calls == [['pad', 'track']]
    assert {selection.identity(row) for row in board.selected} == {'fp', 'pad', 'track'}


def test_bulk_multinet_and_uuid_overlap_preserve_complete_request(origin, monkeypatch):
    path, board, _ = origin
    monkeypatch.setattr(selection, '_request_ids', lambda values: values)
    monkeypatch.setattr(selection, '_request_nets', lambda values: values)
    board.via.net.name = 'VCC'
    board.get_items_by_id = lambda ids: [board.track]
    board.get_items_by_net = lambda nets: [board.track, board.via]
    assert selection.select_origin(path, ['TRACK'], nets=['GND', 'VCC']) == 2
    previous = board.selected[:]
    with pytest.raises(ValueError, match='requested nets'):
        selection.select_origin(path, nets=['VCC', 'MISSING'])
    assert board.selected == previous


def test_duplicate_bulk_response_is_not_hidden_by_net_overlap(origin, monkeypatch):
    path, board, _ = origin
    monkeypatch.setattr(selection, '_request_ids', lambda values: values)
    monkeypatch.setattr(selection, '_request_nets', lambda values: values)
    board.get_items_by_id = lambda ids: [board.track, item('TRACK')]
    board.get_items_by_net = lambda nets: [board.track]
    with pytest.raises(ValueError, match='uniquely'):
        selection.select_origin(path, ['TRACK'], net='GND')
    assert board.selected == [board.fp]


def test_component_navigation_rejects_bulk_non_footprint_uuid(origin, monkeypatch):
    path, board, _ = origin
    monkeypatch.setattr(selection, '_request_ids', lambda values: values)
    monkeypatch.setattr(selection, '_is_footprint', lambda value: value is board.fp)
    board.get_items_by_id = lambda ids: [board.pad]
    with pytest.raises(ValueError, match='uniquely'):
        selection.select_origin(path, ['PAD'], footprints_only=True)
    assert board.selected == [board.fp]


def test_uuid_lookup_cannot_mask_incomplete_net_response(origin, monkeypatch):
    path, board, _ = origin
    monkeypatch.setattr(selection, '_request_ids', lambda values: values)
    monkeypatch.setattr(selection, '_request_nets', lambda values: values)
    board.pad.net.name='VCC'
    board.get_items_by_id=lambda ids:[board.pad]
    board.get_items_by_net=lambda nets:[board.track]
    with pytest.raises(ValueError,match='requested nets'):
        selection.select_origin(path,['PAD'],nets=['VCC','GND'])
    assert board.selected == [board.fp]


def field(identifier):
    # Matches the real SDK: Field.id is an enum, text.id is the KIID.
    return NS(id=1,text=NS(id=NS(value=identifier)))


def test_additive_selection_preserves_distinct_preselected_fields(origin):
    path,board,_=origin
    first,second=field('FIELD1'),field('FIELD2')
    board.selected=[first,second]
    assert selection.select_origin(path,['TRACK'],additive=True)==3
    assert {selection.identity(item) for item in board.selected}=={'field1','field2','track'}


def test_partial_selection_restores_every_preselected_field(origin):
    path,board,_=origin
    first,second=field('FIELD1'),field('FIELD2')
    board.selected=[first,second];board.drop_once=True
    with pytest.raises(RuntimeError,match='confirm'):
        selection.select_origin(path,['TRACK'],additive=True)
    assert board.selected==[first,second]


def test_missing_previous_identity_refuses_before_selection_write(origin):
    path,board,_=origin
    unknown=NS(id=1)
    board.selected=[unknown,board.fp]
    with pytest.raises(ValueError,match='missing or ambiguous'):
        selection.select_origin(path,['TRACK'],additive=True)
    assert board.selected==[unknown,board.fp]
    with pytest.raises(ValueError,match='missing or ambiguous'):
        selection.selected_origin_ids(path)


def test_ambiguous_previous_identity_refuses_before_selection_write(origin):
    path,board,_=origin
    board.selected=[field('SAME'),field('SAME')]
    previous=board.selected[:]
    with pytest.raises(ValueError,match='missing or ambiguous'):
        selection.select_origin(path,['TRACK'])
    assert board.selected==previous


def test_missing_readback_identity_restores_every_preselected_field(origin):
    path,board,_=origin
    first,second=field('FIELD1'),field('FIELD2')
    board.selected=[first,second]
    original=board.add_to_selection
    def incomplete_once(items):
        board.add_to_selection=original
        board.selected=[NS(id=1)]
    board.add_to_selection=incomplete_once
    with pytest.raises(ValueError,match='missing or ambiguous'):
        selection.select_origin(path,['TRACK'])
    assert board.selected==[first,second]


def test_net_response_with_unidentifiable_item_refuses_partial_selection(origin,monkeypatch):
    path,board,_=origin
    monkeypatch.setattr(selection,'_request_nets',lambda values:values)
    board.get_items_by_net=lambda nets:[board.track,NS(net=NS(name='GND'))]
    with pytest.raises(ValueError,match='without a selectable identity'):
        selection.select_origin(path,net='GND')
    assert board.selected==[board.fp]
