"""Verified result navigation; saved hashes cannot certify unsaved live geometry."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace


def identity(item):
    value=getattr(getattr(item,'id',None),'value',None)
    # SDK Field.id is a FieldId enum; its text owns the selectable UUID.
    if not isinstance(value,str) or not value:
        value=getattr(getattr(getattr(item,'text',None),'id',None),'value',None)
    return value.casefold() if isinstance(value,str) else ''


def _selection_ids(items):
    """Require identities that can confirm and restore the entire selection."""
    values=[identity(item) for item in items]
    if any(not value for value in values) or len(set(values))!=len(values):
        raise ValueError('KiCad returned a selection with missing or ambiguous item identities. '
                         'The selection cannot be safely changed or confirmed; retry after selecting items in PCB Editor.')
    return set(values)


def _origin(board_or_path, expected_sha256, *, launch_context=None):
    from .context import connect
    from .saved_board import _sha
    name = board_or_path.GetFileName() if hasattr(board_or_path, 'GetFileName') else board_or_path
    if not name:
        raise ValueError('Save the analysed PCB before navigating results.')
    path = Path(name).resolve()
    if expected_sha256 and _sha(path) != expected_sha256:
        raise ValueError('The saved PCB changed after analysis. Reload and rerun before cross-selection.')
    client = connect() if launch_context is None else connect(launch_context=launch_context)
    return client, _board_for_origin(client, path)


def _board_for_origin(client, path):
    from .context import saved_board
    board = client.get_board()
    if saved_board(SimpleNamespace(get_board=lambda: board)) != path:
        raise ValueError('The originating PCB Editor changed boards. Reopen the tool from this board.')
    return board


class SavedSelectionChanged(ValueError):
    """Selection following must wait for the refreshed saved inputs."""


class SavedSelectionReader:
    """Watch one saved revision through the authenticated launching editor."""

    def __init__(self, board_path, *, expected_sha256, expected_fingerprints=None,
                 launch_context=None, timeout_ms=1000):
        from .context import LaunchContext
        self.path = Path(board_path).resolve()
        self.origin = launch_context if launch_context is not None else LaunchContext.capture()
        self.expected_sha256 = expected_sha256
        self.expected_fingerprints = {str(self.path): expected_sha256}
        allowed = {str(self.path.with_suffix(suffix)) for suffix in ('.kicad_pro', '.kicad_dru')}
        for name, digest in (expected_fingerprints or {}).items():
            if name in allowed:
                self.expected_fingerprints[name] = digest
        self.timeout_ms = timeout_ms
        self._verified_stamp = None

    @property
    def available(self):
        return bool(self.origin.socket and self.origin.token and self.expected_sha256)

    def _check_stamp(self):
        from .editor_refresh import source_stamp
        stamp = source_stamp(self.path)
        if self._verified_stamp is None:
            from .saved_board import _sha
            try:
                for name, expected in self.expected_fingerprints.items():
                    candidate = Path(name)
                    actual = _sha(candidate) if candidate.is_file() else None
                    if actual != expected:
                        raise SavedSelectionChanged('Saved sources changed. Wait for the board to refresh before following selection.')
            except OSError as error:
                raise SavedSelectionChanged('Save the originating PCB and refresh before following selection.') from error
            if source_stamp(self.path) != stamp:
                raise SavedSelectionChanged('Saved sources changed while validating PCB selection.')
            self._verified_stamp = stamp
        elif stamp != self._verified_stamp:
            raise SavedSelectionChanged('Saved sources changed. Wait for the board to refresh before following selection.')
        return stamp

    def read(self, resolve=_selection_ids):
        from .context import connect
        from .editor_refresh import source_stamp
        if not self.available:
            raise ValueError('Open this tool from the originating PCB Editor and save the PCB to follow selection.')
        stamp = self._check_stamp()
        client = connect(launch_context=self.origin, timeout_ms=self.timeout_ms)
        board = _board_for_origin(client, self.path)
        if not callable(getattr(board, 'get_selection', None)):
            raise ValueError('The originating KiCad editor does not expose PCB selection.')
        values = resolve(board.get_selection())
        if source_stamp(self.path) != stamp:
            raise SavedSelectionChanged('Saved sources changed while reading PCB selection.')
        return sorted(values)


def _items(board):
    for footprint in board.get_footprints():
        yield footprint
        yield from footprint.definition.pads
    for collection in ('get_tracks', 'get_vias', 'get_zones'):
        yield from getattr(board, collection, lambda: ())()


def _request_ids(values):
    from kipy.proto.common.types import KIID
    return [KIID(value=value) for value in values]


def _request_nets(values):
    from kipy.board_types import Net
    return [Net(name=value) for value in values]


def _is_footprint(item):
    from kipy.board_types import FootprintInstance
    return isinstance(item, FootprintInstance)


def _resolve(board, wanted, nets, footprints_only=False):
    """Use KiCad 10 bulk queries; never reuse an index of changing live items."""
    by_id = getattr(board, 'get_items_by_id', None)
    by_net = getattr(board, 'get_items_by_net', None)
    # Older/mock hosts can enumerate once. API errors deliberately do not fall
    # back to broad scans or partially resolved selections.
    enumerated = (wanted and not callable(by_id)) or (nets and not callable(by_net))
    if enumerated:
        groups = [list(board.get_footprints()) if footprints_only else list(_items(board))]
    else:
        groups = [list(by_id(_request_ids(sorted(wanted))))] if wanted else []
        if nets:groups.append(list(by_net(_request_nets(sorted(nets)))))
    if nets:
        covered = {getattr(getattr(item, 'net', None), 'name', None) for item in groups[-1]}
        if nets-covered:
            raise ValueError('Some requested nets no longer resolve in the originating PCB Editor: '
                             + ', '.join(sorted(nets-covered)))
    index = {}
    for candidates in groups:
        local = {}
        for item in candidates:
            if footprints_only and not enumerated and not _is_footprint(item):continue
            key = identity(item)
            if not key:
                raise ValueError('KiCad returned a requested item without a selectable identity. '
                                 'The existing selection was not changed; refresh the analysis and retry.')
            local.setdefault(key, []).append(item)
        for key, values in local.items():
            # One UUID may appear once in each independent bulk query. Keep
            # duplicates within either response ambiguous, never hide them.
            if key not in index:index[key] = values
            elif len(index[key]) != 1 or len(values) != 1:index[key].extend(values)
    return index


def select_origin(board_or_path, identifiers=(), net=None, *, nets=(), expected_sha256=None,
                  focus=False, additive=False, footprints_only=False, return_details=False,
                  launch_context=None):
    """Resolve every UUID before changing selection, then confirm or restore it."""
    options = {} if launch_context is None else {'launch_context': launch_context}
    client, board = _origin(board_or_path, expected_sha256, **options)
    wanted = {str(value).casefold() for value in identifiers if value}
    net_names = {str(value) for value in nets if value}
    if net:
        net_names.add(str(net))
    if not wanted and not net_names:
        raise ValueError('Choose a result with PCB UUIDs or an explicit net first.')
    index = _resolve(board, wanted, net_names, footprints_only)
    unresolved = [key for key in wanted if len(index.get(key, ())) != 1]
    if unresolved:
        raise ValueError('Reviewed items no longer resolve uniquely in the originating PCB Editor. '
                         'Reload and rerun analysis. UUIDs: ' + ', '.join(sorted(unresolved)))
    selected = {key: index[key][0] for key in wanted}
    if net_names:
        resolved_nets = {getattr(getattr(values[0], 'net', None), 'name', None)
                         for values in index.values() if len(values) == 1}
        if net_names - resolved_nets:
            raise ValueError('Some requested nets no longer resolve in the originating PCB Editor: '
                             + ', '.join(sorted(net_names - resolved_nets)))
        if any(len(values) != 1 and any(getattr(getattr(item, 'net', None), 'name', None) in net_names
                                       for item in values) for values in index.values()):
            raise ValueError('Requested net items no longer resolve uniquely in the originating PCB Editor.')
        for key, values in index.items():
            if len(values) == 1 and getattr(getattr(values[0], 'net', None), 'name', None) in net_names:
                selected[key] = values[0]
    if not selected:
        raise ValueError('No matching items remain in the originating PCB Editor.')
    previous = list(board.get_selection())
    previous_ids = _selection_ids(previous)
    if additive:
        selected = {**{identity(item): item for item in previous}, **selected}
    try:
        board.clear_selection()
        board.add_to_selection(list(selected.values()))
        if _selection_ids(board.get_selection()) != set(selected):
            raise RuntimeError('KiCad did not confirm the complete requested selection.')
    except Exception as exc:
        try:
            board.clear_selection()
            if previous:
                board.add_to_selection(previous)
            if _selection_ids(board.get_selection()) != previous_ids:
                raise RuntimeError('Previous selection was not restored.')
        except Exception as restore_error:
            raise RuntimeError('Cross-selection failed and KiCad could not restore the previous '
                               'selection. The PCB design was not edited.') from restore_error
        raise exc
    focus_state = 'not requested'
    if focus:
        try:
            status = client.run_action('common.Control.zoomFitSelection')
            focus_state = 'requested' if status is not None and int(status) == 1 else 'unavailable'
        except Exception:
            focus_state = 'unavailable'
    if return_details:
        return dict(selected_ids=sorted(selected), count=len(selected), focus=focus_state)
    return len(selected)


def selected_origin_ids(board_or_path, *, expected_sha256=None, launch_context=None):
    """Read only the launching editor's selection for explicit reverse sync."""
    options = {} if launch_context is None else {'launch_context': launch_context}
    _, board = _origin(board_or_path, expected_sha256, **options)
    return sorted(_selection_ids(board.get_selection()))
