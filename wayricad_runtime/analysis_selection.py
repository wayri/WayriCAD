"""Verified result navigation; saved hashes cannot certify unsaved live geometry."""
from __future__ import annotations
import hashlib
from pathlib import Path


def identity(item):
    return str(getattr(getattr(item, 'id', None), 'value', '')).casefold()


def _origin(board_or_path, expected_sha256):
    from .context import connect, saved_board
    name = board_or_path.GetFileName() if hasattr(board_or_path, 'GetFileName') else board_or_path
    if not name:
        raise ValueError('Save the analysed PCB before navigating results.')
    path = Path(name).resolve()
    if expected_sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('The saved PCB changed after analysis. Reload and rerun before cross-selection.')
    client = connect()
    if saved_board(client) != path:
        raise ValueError('The originating PCB Editor changed boards. Reopen the tool from this board.')
    return client, client.get_board()


def _items(board):
    for footprint in board.get_footprints():
        yield footprint
        yield from footprint.definition.pads
    yield from board.get_tracks()
    yield from board.get_vias()


def select_origin(board_or_path, identifiers=(), net=None, *, expected_sha256=None, focus=False):
    """Resolve every UUID before changing selection, then confirm or restore it."""
    client, board = _origin(board_or_path, expected_sha256)
    wanted = {str(value).casefold() for value in identifiers if value}
    if not wanted and not net:
        raise ValueError('Choose a result with PCB UUIDs or an explicit net first.')
    index = {}
    for item in _items(board):
        key = identity(item)
        if key:
            index.setdefault(key, []).append(item)
    unresolved = [key for key in wanted if len(index.get(key, ())) != 1]
    if unresolved:
        raise ValueError('Reviewed items no longer resolve uniquely in the originating PCB Editor. '
                         'Reload and rerun analysis. UUIDs: ' + ', '.join(sorted(unresolved)))
    selected = {key: index[key][0] for key in wanted}
    if net:
        for key, values in index.items():
            if len(values) == 1 and getattr(getattr(values[0], 'net', None), 'name', None) == net:
                selected[key] = values[0]
    if not selected:
        raise ValueError('No matching items remain in the originating PCB Editor.')
    previous = list(board.get_selection())
    try:
        board.clear_selection()
        board.add_to_selection(list(selected.values()))
        if {identity(item) for item in board.get_selection()} != set(selected):
            raise RuntimeError('KiCad did not confirm the complete requested selection.')
    except Exception as exc:
        try:
            board.clear_selection()
            if previous:
                board.add_to_selection(previous)
            if {identity(item) for item in board.get_selection()} != {identity(item) for item in previous}:
                raise RuntimeError('Previous selection was not restored.')
        except Exception as restore_error:
            raise RuntimeError('Cross-selection failed and KiCad could not restore the previous '
                               'selection. The PCB design was not edited.') from restore_error
        raise exc
    if focus:
        try:
            client.run_action('common.Control.zoomFitSelection')
        except Exception:
            pass  # Selection remains valid when optional zoom is unavailable.
    return len(selected)


def selected_origin_ids(board_or_path, *, expected_sha256=None):
    """Read only the launching editor's selection for explicit reverse sync."""
    _, board = _origin(board_or_path, expected_sha256)
    return sorted({identity(item) for item in board.get_selection() if identity(item)})
