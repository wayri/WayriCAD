"""Return setup suggestions, never inferred electrical connectivity or models."""
from __future__ import annotations

import re


def suggest_return_nets(names, signal_net=None):
    """Rank recognizable ground names for explicit user confirmation.

    A name only helps navigation. It does not establish reference coverage,
    ground-domain identity, current continuity or a closed return loop.
    """
    choices = []
    for name in set(str(n) for n in names if n):
        if name == signal_net:
            continue
        leaf = re.split(r'[/\\]', name)[-1].upper()
        if leaf in ('GND', 'GROUND', '0V', '0_V', 'VSS'):
            rank = 0
        elif re.fullmatch(r'(?:A|D|P|S|CHASSIS|EARTH|ISO)?GND(?:[_-]?\d+)?', leaf):
            rank = 1
        elif re.search(r'(?:^|[_-])(?:GND|GROUND|VSS|0V)(?:$|[_-])', leaf):
            rank = 2
        else:
            continue
        choices.append((rank, name.count('/'), name.casefold(), {
            'name': name, 'reason': 'Ground-like name only; confirm this is the actual return domain.'}))
    return [row[-1] for row in sorted(choices, key=lambda row: row[:3]+(row[-1]['name'],))]


def return_pad_candidates(terminals, nets, reference=None):
    """Return saved pads on selected nets, optionally on one endpoint footprint.

    IDs and labels are preserved so callers can distinguish duplicate pad
    numbers. Returned dictionaries are copies; suggestions never assign pads.
    """
    selected = set(nets); rows = []
    for terminal in terminals:
        if terminal.get('net') not in selected:
            continue
        row = dict(terminal)
        row.setdefault('reference', str(row.get('label', '')).rsplit('.', 1)[0])
        if reference is None or row['reference'] == reference:
            rows.append(row)
    return sorted(rows, key=lambda row: (str(row.get('reference', '')).casefold(),
                                        str(row.get('label', '')).casefold(), str(row.get('id', ''))))
