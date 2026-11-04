"""Pin-aware placement hints from saved drawn-wire paths, never connectivity."""
from collections import Counter
import math

MAX_SPRINGS = 8192


def bind(footprints, metadata, paths=None):
    """Match schematic occurrences and pin numbers to actual same-net PCB pads."""
    by_ref = {fp.reference: fp for fp in footprints}
    references={fp.key:fp.reference for fp in footprints}
    paths = paths or {}
    symbols = metadata.get('symbols', [])
    occurrences = {}
    for symbol in symbols:
        occurrences.setdefault(symbol['reference'], []).append(symbol)
    unique = {}
    omitted = 0
    for row in metadata.get('pin_links', []):
        if row.get('kind') != 'drawn_wire':
            continue
        a, b = (by_ref.get(row.get(side+'_reference')) for side in ('from', 'to'))
        if a is None or b is None:
            continue  # Outside the selected placement scope.
        if a.key == b.key:
            continue  # Connections between units of one package cannot place it.
        valid = True
        for side, fp in (('from', a), ('to', b)):
            path = paths.get(fp.key, '').rstrip('/')
            symbol = row[side+'_symbol'].rstrip('/')
            members=occurrences.get(fp.reference,[])
            ids={item.get('id') for item in members}
            units={item.get('unit') for item in members}
            multiunit=(len(members)>1 and len(ids)==len(members) and None not in ids and
                len({item['sheet_path'] for item in members})==1 and
                len({item.get('lib_id') for item in members})==1 and
                bool(members[0].get('lib_id')) and len(units)==len(members) and
                all(isinstance(unit,int) and not isinstance(unit,bool) and unit>0 for unit in units))
            # A different UUID on the same sheet alone is not a unit identity.
            if path and (symbol not in ids or path != symbol and not (multiunit and path in ids)):
                valid = False
            if len(members)!=1 and not multiunit:
                valid = False
        pins_a = [p for p in a.pads if p.number == row['from_pin']]
        pins_b = [p for p in b.pads if p.number == row['to_pin']]
        nets = {p.net for p in [*pins_a, *pins_b]}
        length = row['length_mm']
        if (not valid or not pins_a or not pins_b or len(nets) != 1 or not next(iter(nets), '') or
                isinstance(length, bool) or not isinstance(length, (int, float)) or
                not math.isfinite(length) or length < 0):
            omitted += 1
            continue
        ends = sorted(((a.key, row['from_pin']), (b.key, row['to_pin'])))
        key = (*ends[0], *ends[1], next(iter(nets)))
        unique[key] = min(length, unique.get(key, math.inf))
    if len(unique) > MAX_SPRINGS:
        raise ValueError('Too many schematic pin springs; choose a smaller placement group.')
    degree = Counter(endpoint for key in unique for endpoint in ((key[0], key[1]), (key[2], key[3])))
    springs = tuple(dict(from_key=a, from_pin=ap, to_key=b, to_pin=bp, net=net,
                         from_reference=references[a],to_reference=references[b],
                         wire_length_mm=length,
                         weight=1.0 / (1.0+length) / max(degree[a, ap], degree[b, bp]))
                    for (a, ap, b, bp, net), length in sorted(unique.items()))
    warnings = (() if not omitted else
                (f'{omitted} schematic pin links had ambiguous occurrence/pad/net mapping; no spring added.',))
    return springs, warnings


def validate(footprints, springs, strength):
    if (isinstance(strength, bool) or not isinstance(strength, (int, float)) or
            not math.isfinite(strength) or not 0 <= strength <= 10):
        raise ValueError('Pin attraction strength must be finite from 0 to 10.')
    if len(springs) > MAX_SPRINGS:
        raise ValueError('Too many schematic pin springs.')
    pads = {(fp.key, p.number, p.net) for fp in footprints for p in fp.pads if p.net}
    seen = set()
    for row in springs:
        a, b = (row.get(side+'_key') for side in ('from', 'to'))
        if (a == b or any((row.get(side+'_key'), row.get(side+'_pin'), row.get('net')) not in pads
                          for side in ('from', 'to'))):
            raise ValueError('Schematic attraction must join actual same-net PCB pins on different parts.')
        for name in ('wire_length_mm', 'weight'):
            value = row.get(name)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or value < 0 or name == 'weight' and not 0 < value <= 1):
                raise ValueError('Invalid schematic attraction length or weight.')
        key = tuple(sorted(((a, row['from_pin']), (b, row['to_pin']))))
        if key in seen:
            raise ValueError('Repeated schematic pin spring.')
        seen.add(key)


def _positions(footprints, transform):
    points = {}
    for fp in footprints:
        for pad in fp.pads:
            points.setdefault((fp.key, pad.number, pad.net), []).append(transform((pad.x, pad.y), fp))
    return points


def measure(footprints, springs, strength, transform):
    """Quadratic spring proxy in mm: 0.5 * strength * weight * d_mm² / 1 mm."""
    if not springs:
        return 0.0, 0.0
    points = _positions(footprints, transform)
    energy, distance = [], []
    for row in springs:
        ends = [points[row[side+'_key'], row[side+'_pin'], row['net']] for side in ('from', 'to')]
        d = min(math.dist(a, b) for a in ends[0] for b in ends[1])
        energy.append(.5 * strength * row['weight'] * d*d)
        distance.append(d)
    return math.fsum(energy), math.fsum(distance)


def target(footprint, footprints, springs, transform):
    """Weighted desired centre placing this part's pin at its partner pin."""
    points = _positions(footprints, transform)
    centres = []
    for row in springs:
        for side, other in (('from', 'to'), ('to', 'from')):
            if row[side+'_key'] != footprint.key:
                continue
            own = points[footprint.key, row[side+'_pin'], row['net']]
            peer = points[row[other+'_key'], row[other+'_pin'], row['net']]
            a, b = min(((a, b) for a in own for b in peer), key=lambda pair: (math.dist(*pair), pair))
            centres.append((row['weight'], footprint.x+b[0]-a[0], footprint.y+b[1]-a[1]))
    weight = math.fsum(row[0] for row in centres)
    return ((math.fsum(w*x for w, x, _ in centres)/weight,
             math.fsum(w*y for w, _, y in centres)/weight) if weight else None)
