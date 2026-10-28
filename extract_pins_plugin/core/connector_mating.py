"""Read-only connector geometry, physical tables and reviewed mating candidates.

Coordinates are millimetres in a board-top XY frame. A pose first centres the
pad bounding box, reflects X for a bottom-side view, applies an optional explicit
X reflection, rotates with the standard mathematical rotation matrix, then
translates. KiCad Y increases downwards, so positive angles appear clockwise
on an unflipped screen. No pose establishes a manufacturer's mating convention.
"""

from __future__ import annotations

import csv
from io import StringIO
from html import escape
import math
from collections.abc import Mapping

MAX_PINS = 2000
MAX_GRID_CELLS = 10000


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(name + ' must be a finite number.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + ' must be a finite number.') from exc
    if not math.isfinite(result):
        raise ValueError(name + ' must be a finite number.')
    return result


def _pins(pins):
    result = []
    seen = set()
    for index, pin in enumerate(pins):
        if index >= MAX_PINS:
            raise ValueError(f'Connector exceeds the {MAX_PINS}-pin review budget.')
        if not isinstance(pin, Mapping):
            raise ValueError('Each pin must contain pin, label, x_mm and y_mm fields.')
        number = '' if pin.get('pin') is None else str(pin['pin']).strip()
        if not number:
            raise ValueError('A connector pin number is empty.')
        if number in seen:
            raise ValueError('Duplicate pin number ' + number + '; review the padstack before mating.')
        seen.add(number)
        row = dict(pin)
        row.update(pin=number, label='' if pin.get('label') is None else str(pin['label']),
                   x_mm=_number(pin.get('x_mm'), 'Pin X'),
                   y_mm=_number(pin.get('y_mm'), 'Pin Y'))
        result.append(row)
    return result


def footprint_pins(footprint):
    """Read numbered native/IPC pads, in mm; collapse only identical repeats.

    Unnumbered mechanical pads are excluded. Repeated copper lands for a pin
    are accepted only at the same centre with the same net. Distinct positions
    cannot be represented by one mating contact and require explicit review.
    The footprint, pads and electrical values are never modified.
    """
    result = {}
    for index, pad in enumerate(footprint.Pads()):
        if index >= 20000:
            raise ValueError('Footprint pad inventory exceeds the review budget.')
        number = str((pad.GetNumber() if hasattr(pad, 'GetNumber') else pad.GetPadName()) or '').strip()
        if not number:
            continue
        position = pad.GetPosition()
        x = position.x if hasattr(position, 'x') else position.GetX()
        y = position.y if hasattr(position, 'y') else position.GetY()
        if hasattr(pad, 'GetNetname'):
            net = pad.GetNetname()
        else:
            item = pad.GetNet()
            net = item.GetNetname() if item is not None else ''
        row = dict(pin=number, label=str(net), x_mm=_number(x, 'Pad X') / 1e6,
                   y_mm=_number(y, 'Pad Y') / 1e6)
        previous = result.get(number)
        if previous is not None and previous != row:
            raise ValueError('Pin ' + number + ' has multiple positions or nets; define its mating contact explicitly.')
        result[number] = row
        if len(result) > MAX_PINS:
            raise ValueError(f'Connector exceeds the {MAX_PINS}-pin review budget.')
    return _pins(result.values())


def transform_pins(pins, side='top', rotation_deg=0, mirror=False, x_mm=0, y_mm=0):
    """Return copied pad rows in the explicit centred pose described above.

    ``side`` is top/bottom; ``mirror`` adds an independent X reflection;
    ``rotation_deg`` is finite degrees; x_mm/y_mm set the new pad-bounds centre.
    There is no implicit mating-face reflection in this function.
    """
    if side not in ('top', 'bottom'):
        raise ValueError('Connector side must be top or bottom.')
    if type(mirror) is not bool:
        raise ValueError('Mirror must be true or false.')
    rotation = math.radians(_number(rotation_deg, 'Rotation') % 360)
    tx, ty = _number(x_mm, 'Pose X'), _number(y_mm, 'Pose Y')
    rows = _pins(pins)
    if not rows:
        return []
    cx = min(p['x_mm'] for p in rows) / 2 + max(p['x_mm'] for p in rows) / 2
    cy = min(p['y_mm'] for p in rows) / 2 + max(p['y_mm'] for p in rows) / 2
    cosine, sine = math.cos(rotation), math.sin(rotation)
    sign = (-1 if side == 'bottom' else 1) * (-1 if mirror else 1)
    result = []
    for pin in rows:
        x, y = (pin['x_mm'] - cx) * sign, pin['y_mm'] - cy
        row = dict(pin, x_mm=_number(cosine*x - sine*y + tx, 'Transformed X'),
                   y_mm=_number(sine*x + cosine*y + ty, 'Transformed Y'))
        result.append(row)
    return result


def _clusters(values, tolerance):
    """Complete-span clusters avoid merging chains that exceed the tolerance."""
    groups = []
    for value in sorted(values):
        if not groups or value - groups[-1][0] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    lookup = {value: index for index, group in enumerate(groups) for value in group}
    return groups, lookup


def physical_grid(pins, tolerance_mm=.02, side='top', rotation_deg=0, mirror=False):
    """Return physical top-to-bottom rows, left-to-right columns, with holes.

    Coordinate clusters span at most tolerance_mm. Numbered contacts sharing a
    cell are rejected. Irregular/oblique patterns exceeding 10,000 cells must be
    viewed at another rotation or exported as coordinate rows rather than a
    misleading compact rectangle. No pin numbering order is invented.
    """
    tolerance = _number(tolerance_mm, 'Grid tolerance')
    if tolerance <= 0:
        raise ValueError('Grid tolerance must be positive.')
    rows = transform_pins(pins, side=side, rotation_deg=rotation_deg, mirror=mirror)
    if not rows:
        return []
    xs, xi = _clusters([p['x_mm'] for p in rows], tolerance)
    ys, yi = _clusters([p['y_mm'] for p in rows], tolerance)
    if len(xs) * len(ys) > MAX_GRID_CELLS:
        raise ValueError('Irregular connector grid exceeds 10,000 cells; change view rotation or use coordinate export.')
    grid = [[None for _ in xs] for _ in ys]
    for pin in rows:
        x, y = xi[pin['x_mm']], yi[pin['y_mm']]
        if grid[y][x] is not None:
            raise ValueError('Pins ' + grid[y][x]['pin'] + ' and ' + pin['pin'] +
                             ' occupy one grid cell; reduce tolerance or review the footprint.')
        grid[y][x] = pin
    return grid


def _pose(value, default):
    if value is None:
        return default
    if not isinstance(value, Mapping):
        raise ValueError('A connector pose must be a mapping.')
    if set(value) - {'side', 'rotation_deg', 'mirror', 'x_mm', 'y_mm'}:
        raise ValueError('Unknown connector pose field.')
    return dict(value)


def match_mating(a, b, tolerance_mm=.1, pose_a=None, pose_b=None):
    """Find reciprocal unique positional candidates in the two explicit poses.

    Default B adds an X reflection as a reviewable facing-view preset. Supplying
    pose_b overrides it entirely. A candidate must have exactly one contact in
    tolerance on both sides; no greedy nearest-choice or pin-number shortcut is
    accepted. Unmatched/ambiguous contacts remain visible. A geometrical match
    does not validate the connector keying, datasheet or existing B-net intent.
    """
    tolerance = _number(tolerance_mm, 'Mating tolerance')
    if tolerance <= 0:
        raise ValueError('Mating tolerance must be positive.')
    aa = transform_pins(a, **_pose(pose_a, {}))
    bb = transform_pins(b, **_pose(pose_b, {'mirror': True}))
    candidates_a = [[] for _ in aa]
    candidates_b = [[] for _ in bb]
    bins = {}
    def bin_key(pin):
        x, y = pin['x_mm']/tolerance, pin['y_mm']/tolerance
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('Mating tolerance is too small for these coordinates.')
        return math.floor(x), math.floor(y)
    for j, pin in enumerate(bb):
        key = bin_key(pin)
        bins.setdefault(key, []).append(j)
    for i, pin in enumerate(aa):
        x, y = bin_key(pin)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in bins.get((x+dx, y+dy), []):
                    distance = math.hypot(pin['x_mm']-bb[j]['x_mm'], pin['y_mm']-bb[j]['y_mm'])
                    if distance <= tolerance:
                        # Two candidates already establish ambiguity. Retaining
                        # all pairs could allocate millions of tuples for an
                        # invalid coincident-contact footprint.
                        if len(candidates_a[i]) < 2:candidates_a[i].append((j, distance))
                        if len(candidates_b[j]) < 2:candidates_b[j].append(i)
    pairs = []
    accepted_a, accepted_b = set(), set()
    issues = []
    for i, candidates in enumerate(candidates_a):
        if len(candidates) == 1:
            j, distance = candidates[0]
            if len(candidates_b[j]) == 1:
                pairs.append(dict(a=aa[i], b=bb[j], distance_mm=distance))
                accepted_a.add(i); accepted_b.add(j)
        if len(candidates) > 1:
            issues.append('A pin ' + aa[i]['pin'] + ' has multiple possible B contacts.')
    for j, candidates in enumerate(candidates_b):
        if len(candidates) > 1:
            issues.append('B pin ' + bb[j]['pin'] + ' has multiple possible A contacts.')
    unmatched_a = [p for i, p in enumerate(aa) if i not in accepted_a]
    unmatched_b = [p for j, p in enumerate(bb) if j not in accepted_b]
    if unmatched_a or unmatched_b:
        issues.append(f'Unresolved contacts: {len(unmatched_a)} on A, {len(unmatched_b)} on B. Review pose and tolerance.')
    if not aa or not bb:
        issues.append('Both connectors need numbered contacts before mating can be reviewed.')
    return dict(pairs=pairs, unmatched_a=unmatched_a, unmatched_b=unmatched_b, issues=issues)


def grid_text(grid, format='csv'):
    """Render each populated cell as ``pin: label`` in physical row order."""
    cells = [[('' if pin is None else pin['pin'] + ': ' + str(pin.get('label', ''))) for pin in row] for row in grid]
    if format == 'csv':
        output = StringIO(); csv.writer(output, lineterminator='\n').writerows(cells)
        return output.getvalue()
    if format not in ('md', 'markdown'):
        raise ValueError('Physical grid format must be csv or markdown.')
    if not cells:
        return ''
    def escaped(value):
        return escape(value.replace('\\', '\\\\').replace('|', '\\|'), quote=False).replace('\n', '<br>').replace('\r', '')
    headings = ['Column ' + str(i+1) for i in range(len(cells[0]))]
    return '\n'.join('| ' + ' | '.join(escaped(v) for v in row) + ' |'
                     for row in [headings, ['---']*len(headings), *cells]) + '\n'
