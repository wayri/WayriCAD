"""Run a Quick SI path against an owned snapshot of the launching editor."""
from __future__ import annotations

from pathlib import Path


def watched_nets(request):
    """Track the signal and any explicitly selected return copper."""
    return tuple(sorted({request['net'], *request['inputs'].get('return_nets', ())} - {''}))


def require_endpoints(board, net, reviewed):
    """Verify the captured endpoint pads still have the reviewed UUIDs."""
    current = {label: [] for label in reviewed}
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        for pad in footprint.Pads():
            label = reference + '.' + pad.GetNumber()
            if label in current and pad.GetNetname() == net:
                current[label].append(str(pad.m_Uuid.AsString()))
    if any(current[label] != [identifier] for label, identifier in reviewed.items()):
        raise ValueError('A reviewed source or receiver changed identity or net in KiCad. Review the endpoints and run again.')


def run_live_screen(request, origin, nets, reviewed, cancelled, capture_stamp):
    """Return native preview objects from the same immutable copy the worker used."""
    from wayricad_runtime.live_pcb import capture_live_pcb, route_stamp
    from wayricad_runtime.saved_board import load_board
    from .service import require_source, restore_path, run_job, source_fingerprints

    path = request['board_path']
    require_source(request)
    with capture_live_pcb(path, origin, watch_nets=nets) as (snapshot, evidence):
        stamp = evidence['route_stamp']
        capture_stamp(stamp)
        if evidence['origin_sha256'] != request['source_fingerprints'][str(Path(path).resolve())]:
            raise ValueError('The saved PCB changed while capturing the live route.')
        worker_request = dict(request, board_path=str(snapshot),
                              source_fingerprints=source_fingerprints(snapshot))
        if cancelled():
            raise InterruptedError('Live Quick SI cancelled.')
        board = load_board(snapshot)
        if board is None:
            raise ValueError('KiCad could not load the private live PCB preview.')
        require_endpoints(board, request['net'], reviewed)
        payload = run_job(worker_request, cancelled=cancelled, background=True)
        if cancelled():
            raise InterruptedError('Live Quick SI cancelled.')
        measured_path = restore_path(payload, board)
        report = dict(payload['report'])
        for key in ('source_path', 'source_sha256', 'source_fingerprints', 'saved_board_provenance'):
            report.pop(key, None)
        report['live_editor_preview'] = True
    if route_stamp(path, origin, nets) != stamp:
        return None
    require_source(request)
    return report, measured_path, board
