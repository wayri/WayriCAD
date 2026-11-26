"""An owned, read-only copy of the originating editor's current PCB."""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def capture_live_pcb(board_path, origin, *, watch_nets=()):
    """Yield an IPC board copy and provenance without saving the working PCB."""
    from .analysis_selection import _board_for_origin
    from .context import connect
    from .saved_board import _inputs

    path = Path(board_path).resolve()
    before = _inputs(path)
    if before[str(path)] is None:
        raise ValueError('Save the PCB once to establish its project and rule context.')
    client = connect(launch_context=origin, timeout_ms=15000)
    board = _board_for_origin(client, path)
    serialize = getattr(board, 'get_as_string', None)
    if not callable(serialize):
        raise ValueError('This KiCad connection does not support reading the active PCB geometry.')
    watched = sorted(set(watch_nets))
    route = _route_digest(board, watched) if watched else None
    contents = serialize()
    if not isinstance(contents, str) or not contents.lstrip().startswith('(kicad_pcb'):
        raise ValueError('KiCad did not return usable active PCB geometry.')
    confirmed_board = _board_for_origin(client, path)
    if watched and _route_digest(confirmed_board, watched) != route:
        raise ValueError('Live routing changed during capture. Run again after the edit settles.')
    with tempfile.TemporaryDirectory(prefix='wayricad-live-pcb-',
                                     dir=os.environ.get('WAYRICAD_ANALYSIS_SCRATCH') or None) as folder:
        snapshot = Path(folder) / path.name
        snapshot.write_bytes(contents.encode('utf-8'))
        for suffix in ('.kicad_pro', '.kicad_dru'):
            source = path.with_suffix(suffix)
            if before[str(source)] is not None:
                shutil.copyfile(source, snapshot.with_suffix(suffix))
        if _inputs(path) != before:
            raise ValueError('Saved board or rules changed during capture. Run again.')
        path_hashes = _inputs(snapshot)
        record = {
            'mode': 'editor-copy',
            'origin_sha256': before[str(path)],
            'snapshot_sha256': path_hashes[str(snapshot)],
            'project_source': 'saved project and custom rules',
            'project_sha256': before[str(path.with_suffix('.kicad_pro'))],
            'custom_rules_sha256': before[str(path.with_suffix('.kicad_dru'))],
        }
        if watched:
            record.update(route_stamp=route, route_nets=watched)
        yield snapshot, record
        # The solver used only the sealed copy. Avoid any IPC when it finishes:
        # the user may already be routing again in the original editor.
        if _inputs(path) != before or _inputs(snapshot) != path_hashes:
            raise ValueError('The saved design or private analysis input changed during the live run. Run again.')

def route_stamp(board_path, origin, nets):
    """Fingerprint only the requested live copper; never serialize the board to poll."""
    from .analysis_selection import _board_for_origin
    from .context import connect

    names = sorted(set(nets))
    if not names:
        raise ValueError('Choose a solved net before watching editor routing.')
    client = connect(launch_context=origin, timeout_ms=2500)
    board = _board_for_origin(client, Path(board_path).resolve())
    return _route_digest(board, names)


def _route_digest(board, names):
    from hashlib import sha256
    from .analysis_selection import _request_nets, identity

    items = board.get_items_by_net(_request_nets(names))
    tracks = sorted((identity(item),item.proto.SerializeToString(deterministic=True)) for item in items)
    digest = sha256()
    for name in names:
        digest.update(name.encode('utf-8') + b'\0')
    for identifier,data in tracks:
        digest.update(identifier.encode('ascii') + len(data).to_bytes(8,'big') + data)
    return digest.hexdigest()
