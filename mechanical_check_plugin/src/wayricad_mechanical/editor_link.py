"""Resolve mechanical finding references against their reviewed primary PCB."""
from collections import defaultdict

from wayricad_runtime.analysis_selection import select_origin


def finding_footprints(report, finding):
    components = defaultdict(list)
    for item in report.get('board', {}).get('components', ()):
        components[item['ref']].append(item.get('uuid'))
    foreign = {body['ref'] for body in report.get('bodies', ())
               if body.get('kind') in ('comparison_component', 'comparison_board', 'enclosure', 'board')}
    identifiers, skipped = set(), []
    for ref in finding.get('refs', ()):
        candidates = components.get(ref, ())
        if not candidates:
            skipped.append(ref)
            continue
        if ref in foreign or len(candidates) != 1 or not candidates[0]:
            raise ValueError(f'{ref} has no unique primary-board footprint identity in this report. Run the check again.')
        identifiers.add(candidates[0])
    if not identifiers:
        raise ValueError('This finding has no primary-board footprint to locate.')
    return sorted(identifiers), skipped


def locate_report(report, identifiers, origin):
    if not report.get('board_path') or not report.get('board_sha256') or report.get('source_kind'):
        raise ValueError('Run a check on the saved PCB to locate this finding.')
    return select_origin(report['board_path'], identifiers=identifiers,
                         expected_sha256=report['board_sha256'], footprints_only=True,
                         focus=True, return_details=True, launch_context=origin)


def board_inventory(path, mounts, live_board=None):
    import pcbnew
    from .extract import is_mounting

    board = live_board if live_board is not None else pcbnew.LoadBoard(path)
    if board is None:
        raise ValueError('KiCad could not load the PCB.')
    footprints = list(board.GetFootprints())
    models = sum(bool(list(fp.Models())) for fp in footprints)
    thickness = pcbnew.ToMM(board.GetDesignSettings().GetBoardThickness())
    stats = f'{len(footprints):,} footprints    ·    {models:,} with model assignments    ·    {thickness:.2f} mm board'
    rows, ids = [], {}
    for fp in footprints:
        if not is_mounting(fp,mounts):
            continue
        for pad in fp.Pads():
            if max(pad.GetDrillSize().x,pad.GetDrillSize().y):
                ref = fp.GetReference()
                ids[ref] = None if ref in ids else fp.m_Uuid.AsString()
                rows.append((ref,'NPTH' if pad.GetAttribute()==pcbnew.PAD_ATTRIB_NPTH else 'PTH'))
                break
    return stats, sorted(rows), ids
