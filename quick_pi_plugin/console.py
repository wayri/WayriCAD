"""Local, non-executable QuickPI command language and completions.

All electrical connectivity comes from the supplied terminal inventory. Series
components describe user-specified R/L models; their values are never inferred.
"""
from __future__ import annotations

import math
import re
import shlex


HELP = '''QuickPI commands:
  nets
  pads [net-name]
  run pi [net-name] START END
  run pi START R1.1 5m R1.2 END
  run pi START L1.1 5mH+30m L1.2 END
  run pi START R1:5m:10nH END
Quote names containing spaces. Pads use reference.number or their unique ID.
Each intervening copper section must share an actual net. Component shortcuts
require exactly two distinct pads and an unambiguous incoming net.
Resistance defaults to ohms; inductance requires H. Prefixes are case-sensitive:
m = milli, M/Meg = mega, u/µ/μ = micro. All series values must be nonnegative.'''

_PREFIX = {'': 1., 'f': 1e-15, 'p': 1e-12, 'n': 1e-9,
           'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'm': 1e-3,
           'k': 1e3, 'K': 1e3, 'M': 1e6, 'Meg': 1e6,
           'G': 1e9, 'T': 1e12}
_VALUE = re.compile(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
                    r'(Meg|[fpnuµμmkKMGT]?)(ohms?|Ω|H)?')


def _rl(text):
    """Parse one or more plus-separated SI quantities, never Python code."""
    text = str(text).strip()
    if not text:
        raise ValueError('Enter a resistance or an inductance with an explicit H unit.')
    result = {'resistance_ohm': 0., 'inductance_h': 0.}
    seen = set()
    position = 0
    while position < len(text):
        match = _VALUE.match(text, position)
        if not match:
            raise ValueError('Invalid series value: ' + text)
        number, prefix, unit = match.groups()
        value = float(number) * _PREFIX[prefix]
        if not math.isfinite(value) or value < 0:
            raise ValueError('Series values must be finite and nonnegative: ' + text)
        kind = 'inductance_h' if unit == 'H' else 'resistance_ohm'
        if kind in seen:
            raise ValueError('Specify each resistance/inductance once; inductance requires H: ' + text)
        seen.add(kind)
        result[kind] = value
        position = match.end()
        if position < len(text):
            if text[position] != '+' or position + 1 == len(text):
                raise ValueError('Invalid series value: ' + text)
            position += 1
    if not any(result.values()):
        raise ValueError('A series component needs positive resistance or inductance.')
    return result


def _inventory(inventory):
    rows = inventory.get('terminals', [])
    lookup = {}
    by_component = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get('id') or not row.get('label'):
            raise ValueError('Terminal inventory requires nonempty IDs and labels.')
        for key in {str(row['id']), str(row['label'])}:
            lookup.setdefault(key, []).append(row)
        if '.' in str(row['label']):
            reference, pad = str(row['label']).rsplit('.', 1)
            if reference and pad:
                by_component.setdefault(reference, []).append(row)
    return lookup, by_component


def _terminal(token, lookup):
    matches = lookup.get(token, [])
    if len(matches) != 1:
        raise ValueError(('Ambiguous' if matches else 'Unknown') + ' terminal: ' + token)
    row = matches[0]
    if not isinstance(row.get('net'), str) or not row['net']:
        raise ValueError('Terminal has no assigned net: ' + token)
    return row


def _reference(row):
    parts = str(row['label']).rsplit('.', 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError('Series terminals need reference.pad labels: ' + str(row['label']))
    return parts[0]


def parse_command(text, inventory):
    """Return a solve request or console output; invalid input raises ValueError."""
    try:
        tokens = shlex.split(str(text), posix=True)
    except ValueError as exc:
        raise ValueError('Close the quoted name before running the command.') from exc
    if not tokens or tokens == ['help'] or tokens == ['?']:
        return {'console_output': HELP}
    nets = list(inventory.get('nets', []))
    if tokens == ['nets']:
        return {'console_output': '\n'.join(sorted(set(nets))) or 'No nets available.'}
    lookup, components = _inventory(inventory)
    if tokens[0] == 'pads':
        if len(tokens) > 2:
            raise ValueError('Use pads [net-name]; quote names containing spaces.')
        if len(tokens) == 2 and tokens[1] not in nets:
            raise ValueError('Unknown net: ' + tokens[1])
        rows = inventory.get('terminals', [])
        labels = [str(row['label']) + '  [' + str(row.get('net') or 'unassigned') + ']'
                  for row in rows if len(tokens) == 1 or row.get('net') == tokens[1]]
        return {'console_output': '\n'.join(sorted(labels)) or 'No matching pads.'}
    if tokens[:2] != ['run', 'pi']:
        raise ValueError('Unknown command. Type help for QuickPI syntax.')
    args = tokens[2:]
    explicit_net = None
    if len(args) >= 3 and args[0] in nets:
        explicit_net = args.pop(0)
    if len(args) < 2:
        raise ValueError('Use run pi [net-name] START END.')
    source, sink = _terminal(args[0], lookup), _terminal(args[-1], lookup)
    if explicit_net is not None and source['net'] != explicit_net:
        raise ValueError('Source terminal is not on the selected net: ' + explicit_net)
    seen = set()

    def reserve(row):
        if row['id'] in seen:
            raise ValueError('Each endpoint must be distinct; repeated terminal: ' + row['label'])
        seen.add(row['id'])

    reserve(source)
    reserve(sink)
    cursor = source
    series = []
    middle = args[1:-1]
    index = 0
    while index < len(middle):
        token = middle[index]
        if ':' in token and token not in lookup:
            parts = token.split(':')
            if len(parts) not in (2, 3):
                raise ValueError('Use component:resistance[:inductanceH].')
            reference = parts[0]
            pads = components.get(reference, [])
            if len(pads) != 2 or len({p['id'] for p in pads}) != 2:
                raise ValueError('Shortcut needs exactly two unique pads: ' + reference)
            incoming = [p for p in pads if p.get('net') == cursor['net']]
            if len(incoming) != 1:
                raise ValueError('Shortcut direction is ambiguous or disconnected: ' + reference)
            entry = _terminal(str(incoming[0]['id']), lookup)
            exit_pad = _terminal(str(next(p for p in pads if p['id'] != entry['id'])['id']), lookup)
            model = _rl('+'.join(parts[1:]))
            index += 1
        else:
            if len(middle) - index < 3:
                raise ValueError('A series branch needs FROM_PAD VALUE TO_PAD.')
            entry = _terminal(token, lookup)
            model = _rl(middle[index + 1])
            exit_pad = _terminal(middle[index + 2], lookup)
            reference = _reference(entry)
            if reference != _reference(exit_pad):
                raise ValueError('Series branch pads must belong to the same component.')
            index += 3
        reserve(entry)
        reserve(exit_pad)
        if cursor['net'] != entry['net']:
            raise ValueError('Copper section is disconnected: ' + cursor['label'] + ' → ' + entry['label'])
        series.append({'id': reference, 'from_pad': entry['id'], 'to_pad': exit_pad['id'], **model})
        cursor = exit_pad
    if cursor['net'] != sink['net']:
        raise ValueError('Copper section is disconnected: ' + cursor['label'] + ' → ' + sink['label'])
    return {'action': 'solve', 'net': explicit_net or source['net'],
            'source_terminal': source['id'], 'sink_terminal': sink['id'], 'series': series}


def suggestions(text, inventory):
    """Return complete, shell-quoted replacement command lines (no execution)."""
    text = str(text)
    unfinished_quote = False
    try:
        tokens = shlex.split(text)
    except ValueError:
        unfinished_quote = True
        tokens = None
        for quote in ('"', "'"):
            try:
                tokens = shlex.split(text + quote)
                break
            except ValueError:
                pass
        if tokens is None:
            return []
    if text and text[-1].isspace() and not unfinished_quote:
        completed, prefix = tokens, ''
    else:
        completed, prefix = tokens[:-1], tokens[-1] if tokens else ''
    if not completed:
        candidates = ['help', 'nets', 'pads', 'run pi']
        return [candidate for candidate in candidates if candidate.startswith(prefix)]
    if completed == ['run']:
        candidates = ['pi']
    elif completed == ['pads']:
        candidates = inventory.get('nets', [])
    elif completed[:2] == ['run', 'pi']:
        candidates = [row['label'] for row in inventory.get('terminals', [])]
        if completed == ['run', 'pi']:
            candidates = list(inventory.get('nets', [])) + candidates
    else:
        return []
    return [shlex.join([*completed, candidate]) for candidate in sorted(set(candidates))
            if candidate.startswith(prefix)]
