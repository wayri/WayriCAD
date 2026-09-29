"""Exact, read-only-to-design cross-selection in the originating PCB Editor."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _origin(board_path, expected_sha256=None):
    from wayricad_runtime.context import connect, saved_board
    path = Path(board_path).resolve()
    if expected_sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('The saved PCB changed after QuickTherm ran. Reload and rerun before cross-selection.')
    client = connect()
    if saved_board(client) != path:
        raise ValueError('The originating PCB Editor changed boards. Reopen QuickTherm from this board.')
    return client, client.get_board()


def _identity(item):
    identifier = getattr(item, 'id', None)
    return str(getattr(identifier, 'value', '')).lower()


def select_origin_component(board_path, footprint_id, *, expected_sha256=None, focus=True):
    """Select one exact saved footprint UUID; restore prior selection on failure."""
    client, board = _origin(board_path, expected_sha256)
    matches = [fp for fp in board.get_footprints() if _identity(fp) == str(footprint_id).lower()]
    if len(matches) != 1:
        raise ValueError('The selected footprint no longer resolves uniquely in the originating PCB Editor.')
    previous = list(board.get_selection())
    try:
        board.clear_selection()
        board.add_to_selection(matches)
        if {_identity(item) for item in board.get_selection()} != {_identity(matches[0])}:
            raise RuntimeError('KiCad did not confirm the requested footprint selection.')
    except Exception:
        try:
            board.clear_selection()
            if previous:board.add_to_selection(previous)
        except Exception:pass
        raise
    focus_result = 'not requested'
    if focus:
        try:
            status = client.run_action('common.Control.zoomFitSelection')
            focus_result = 'requested' if int(status) == 1 else 'unavailable'
        except Exception:
            focus_result = 'unavailable'
    return {'selected_id': _identity(matches[0]), 'focus': focus_result}


def selected_origin_component_ids(board_path, *, expected_sha256=None):
    """Read exact selected footprint UUIDs for on-demand table/map sync."""
    _, board = _origin(board_path, expected_sha256)
    ids = {_identity(item) for item in board.get_selection()}
    return sorted(_identity(fp) for fp in board.get_footprints() if _identity(fp) in ids)
