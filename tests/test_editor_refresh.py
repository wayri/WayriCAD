import hashlib
from types import SimpleNamespace as NS

import pytest

from wayricad_runtime import analysis_selection, context
from wayricad_runtime.editor_refresh import RevisionState, source_stamp


def test_changes_invalidate_before_idle_reload(tmp_path):
    board = tmp_path / 'board.kicad_pcb'
    board.write_bytes(b'pcb')
    state = RevisionState(source_stamp(board))
    rules = board.with_suffix('.kicad_dru')
    rules.write_bytes(b'first rules')
    draft = source_stamp(board)
    assert state.observe(draft, ready=True, available=True) == 'invalidate'
    assert state.observe(draft, ready=False, available=True) is None
    rules.write_bytes(b'updated rules with a different length')
    saved = source_stamp(board)
    assert state.observe(saved, ready=True, available=True) == 'invalidate'
    assert state.observe(saved, ready=True, available=True) == 'reload'
    assert state.observe(saved, ready=True, available=True) is None


def test_atomic_save_gap_waits_for_board(tmp_path):
    board = tmp_path / 'board.kicad_pcb'
    board.write_bytes(b'pcb')
    state = RevisionState(source_stamp(board))
    board.rename(board.with_suffix('.old'))
    missing = source_stamp(board)
    assert state.observe(missing, ready=True, available=False) == 'invalidate'
    assert state.observe(missing, ready=True, available=False) is None
    board.write_bytes(b'new pcb')
    replaced = source_stamp(board)
    assert state.observe(replaced, ready=True, available=True) == 'invalidate'
    assert state.observe(replaced, ready=True, available=True) == 'reload'
    state.reset(replaced)
    assert state.observe(replaced, ready=True, available=True) is None


def test_selection_reader_captures_origin_and_refuses_changed_rules(tmp_path, monkeypatch):
    path = tmp_path / 'board.kicad_pcb'
    path.write_bytes(b'pcb')
    saved_hash = hashlib.sha256(b'pcb').hexdigest()
    origin = context.LaunchContext('ipc://launch-instance', 'test-token')
    selected = NS(id=NS(value='PAD'))
    board = NS(get_selection=lambda: [selected])
    connections = []

    def connect(**options):
        connections.append(options)
        return NS(get_board=lambda: board)

    monkeypatch.setattr(context, 'connect', connect)
    monkeypatch.setattr(context, 'saved_board', lambda caller: path)
    reader = analysis_selection.SavedSelectionReader(path, expected_sha256=saved_hash, launch_context=origin)
    assert reader.available and reader.read() == ['pad']
    assert reader.read() == ['pad']
    assert connections == [{'launch_context': origin, 'timeout_ms': 1000}]*2
    path.with_suffix('.kicad_pro').write_bytes(b'changed after snapshot')
    with pytest.raises(ValueError, match='Saved sources changed'):
        reader.read()
    assert len(connections) == 2


def test_selection_reader_rejects_other_editor_and_stale_board(tmp_path, monkeypatch):
    path = tmp_path / 'board.kicad_pcb'
    path.write_bytes(b'pcb')
    saved_hash = hashlib.sha256(b'pcb').hexdigest()
    origin = context.LaunchContext('ipc://launch-instance', 'test-token')
    monkeypatch.setattr(context, 'connect', lambda **options: NS(get_board=lambda: NS()))
    monkeypatch.setattr(context, 'saved_board', lambda caller: path.with_name('other.kicad_pcb'))
    reader = analysis_selection.SavedSelectionReader(path, expected_sha256=saved_hash, launch_context=origin)
    with pytest.raises(ValueError, match='changed boards'):
        reader.read()
    path.write_bytes(b'replaced pcb')
    refreshed = analysis_selection.SavedSelectionReader(path, expected_sha256=saved_hash, launch_context=origin)
    with pytest.raises(ValueError, match='Saved sources changed'):
        refreshed.read()



def test_selection_reader_checks_expected_absent_rules_before_first_read(tmp_path, monkeypatch):
    path = tmp_path / 'board.kicad_pcb'
    path.write_bytes(b'pcb')
    rules = path.with_suffix('.kicad_dru')
    reader = analysis_selection.SavedSelectionReader(
        path, expected_sha256=hashlib.sha256(b'pcb').hexdigest(),
        expected_fingerprints={str(rules): None},
        launch_context=context.LaunchContext('ipc://launch-instance', 'test-token'),
    )
    rules.write_bytes(b'new rules')
    monkeypatch.setattr(context, 'connect', lambda **options: pytest.fail('Stale rules must block IPC'))
    with pytest.raises(analysis_selection.SavedSelectionChanged):
        reader.read()
