from __future__ import annotations

import json
import re

_NUMBER = r'(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?'
_NET = r'(?P<quoted>"(?:[^"\\]|\\.)+")|(?P<plain>[^"\s,]+)'
_PAD = r'[A-Z][\w-]*\d\.[\w.+-]+'
_RAIL = re.compile(
    rf'(?:net|rail)\s+(?:{_NET})\s+from\s+(?P<source>{_PAD})\s+to\s+(?P<sink>{_PAD})'
    rf'\s+at\s+(?P<voltage>{_NUMBER})\s*V\s+(?:with|drawing)\s+'
    rf'(?P<current>{_NUMBER})\s*(?P<scale>m?A)', re.I)
_RAIL_SPLIT = re.compile(r'\s*(?:,|\band\b)\s*(?=(?:net|rail)\s)', re.I)
_RAIL_HINT = 'Use net NAME from J1.1 to U1.1 at 3.3 V with 500 mA.'


def rail_cases(text, inventory=None):
    """Parse independent rail cases and optionally resolve exact saved identities."""
    cases = []
    text = text.strip()
    cursor = 0
    while cursor < len(text):
        match = _RAIL.match(text, cursor)
        if not match:
            raise ValueError(_RAIL_HINT + ' Separate complete cases with commas.')
        net = json.loads(match['quoted']) if match['quoted'] else match['plain']
        if not net.strip() or net.startswith('-') or any(ord(char) < 32 for char in net):
            raise ValueError('Use a nonempty net name from the saved PCB.')
        cursor = match.end()
        if cursor < len(text):
            separator = _RAIL_SPLIT.match(text, cursor)
            if not separator:
                raise ValueError(_RAIL_HINT + ' Separate complete cases with commas.')
            cursor = separator.end()
        source, sink = match['source'], match['sink']
        if inventory is not None:
            candidates = inventory.net_matches(net)
            if len(candidates) != 1:
                hint = ' Choose ' + ', '.join(candidates[:12]) + '.' if candidates else ''
                raise ValueError(f'Use an exact saved net name for {net}.' + hint)
            net = candidates[0]
            endpoints = (inventory.pad_aliases.get(ref.casefold()) for ref in (source, sink))
            for label, entered, resolved in zip(('source', 'sink'), (source, sink), endpoints):
                if not resolved or net not in inventory.pads[resolved]:
                    raise ValueError(f'Choose a saved {label} pad on {net}. {entered} does not match.')
                if label == 'source':
                    source = resolved
                else:
                    sink = resolved
        voltage = float(match['voltage'])
        current = float(match['current']) * (.001 if match['scale'].lower() == 'ma' else 1.)
        if not 0 < voltage <= 1e12 or not 0 <= current <= 1e12 or source.casefold() == sink.casefold():
            raise ValueError(f'{net} needs distinct pads, positive finite voltage and nonnegative finite current.')
        cases.append((net, source, sink, voltage, current))
    if not 2 <= len(cases) <= 32 or len({row[0].casefold() for row in cases}) != len(cases):
        raise ValueError('Specify 2–32 distinct nets. Use a reviewed batch JSON for multiple cases on the same net.')
    return cases


def resolved_rail_cases(text, inventory):
    """Store canonical native names in the plan so review and execution agree."""
    return ', '.join(f'net {json.dumps(net, ensure_ascii=False)} from {source} to {sink} at {voltage} V with {current} A'
                     for net, source, sink, voltage, current in rail_cases(text, inventory))


def batch_study(text, *, mesh_backend=None):
    return {'schema': 'wayricad.pi-batch/v1', 'cases': [
        {'name': net, 'electrical': {
            'net': net, 'source_terminal': source, 'sink_terminal': sink,
            'source_voltage': voltage, 'sink_current': current, 'mesh_sizing': 'auto',
            **({'mesh_backend': mesh_backend} if mesh_backend else {}),
        }} for net, source, sink, voltage, current in rail_cases(text)]}


# Each conversational value names its physical quantity and unit explicitly.
_TRANSIENT_FIELDS = {
    'voltage': (r'source\s+voltage', 'v'),
    'source_mohm': (r'source\s+resistance', 'ohm'),
    'source_nh': (r'source\s+inductance', 'h'),
    'initial_a': (r'(?:initial|starting)\s+current', 'a'),
    'step_a': (r'(?:step|final)\s+current', 'a'),
    'event_ms': (r'(?:step\s+time|event\s+time)', 's'),
    'path_mohm': (r'path\s+resistance', 'ohm'),
    'path_nh': (r'path\s+inductance', 'h'),
    'cap_uf': (r'(?:load\s+)?capacitance', 'f'),
    'esr_mohm': (r'(?:load\s+)?esr', 'ohm'),
    'duration_ms': (r'duration', 's'),
    'step_us': (r'(?:time\s*step|timestep|sample\s+step)', 's'),
    'min_voltage': (r'(?:minimum|min)\s+(?:load\s+)?voltage', 'v'),
    'max_voltage': (r'(?:maximum|max)\s+(?:load\s+)?voltage', 'v'),
    'budget_a': (r'(?:source\s+)?current\s+limit', 'a'),
}
_UNITS = {
    'v': ({'v': 1., 'mv': .001, 'volts': 1., 'volt': 1.}, 1.),
    'ohm': ({'ohm': 1., 'ohms': 1., 'mohm': .001, 'mohms': .001,
             'Ω': 1., 'mΩ': .001}, .001),
    'h': ({'h': 1., 'mh': .001, 'uh': 1e-6, 'nh': 1e-9, 'ph': 1e-12}, 1e-9),
    'a': ({'a': 1., 'ma': .001, 'ua': 1e-6, 'amps': 1., 'amp': 1.}, 1.),
    's': ({'s': 1., 'ms': .001, 'us': 1e-6, 'ns': 1e-9}, .001),
    'f': ({'f': 1., 'mf': .001, 'uf': 1e-6, 'nf': 1e-9, 'pf': 1e-12}, 1e-6),
}


def transient_slots(query):
    fields = {}
    query = query.replace("\u00b5", "u").replace("\u03bc", "u")
    for name, (label, kind) in _TRANSIENT_FIELDS.items():
        scales, base = _UNITS[kind]
        unit = '|'.join(map(re.escape, sorted(scales, key=len, reverse=True)))
        match = re.search(rf'\b{label}\s*[:=]?\s*(-?{_NUMBER})\s*({unit})(?![\wΩ])', query, re.I)
        if match:
            scale = scales.get(match[2].lower().replace('ω', 'Ω'))
            base = 1e-6 if name == 'step_us' else base
            fields[name] = float(match[1]) * scale / base
    return fields


def bind_transient(values):
    if values['event_ms'] > values['duration_ms']:
        raise ValueError('Put the load step inside the simulation duration.')
    if values['duration_ms'] / values['step_us'] > 10.:
        raise ValueError('Choose a time step that keeps the study within 10,000 intervals.')
    if 'min_voltage' in values and 'max_voltage' in values and values['min_voltage'] > values['max_voltage']:
        raise ValueError('The maximum load voltage must be at least its minimum.')
    load = dict(id=values.get('sink', 'Load 1'),
                initial_current_A=values['initial_a'], step_current_A=values['step_a'],
                step_time_s=values['event_ms'] * 1e-3, path_resistance_ohm=values['path_mohm'] * 1e-3,
                path_inductance_H=values['path_nh'] * 1e-9, capacitance_F=values['cap_uf'] * 1e-6,
                esr_ohm=values['esr_mohm'] * 1e-3)
    for field in ('min_voltage', 'max_voltage'):
        if field in values:
            load[field + '_V'] = values[field]
    study = dict(source_voltage_V=values['voltage'], source_resistance_ohm=values['source_mohm'] * 1e-3,
                 source_inductance_H=values['source_nh'] * 1e-9, duration_s=values['duration_ms'] * 1e-3,
                 step_s=values['step_us'] * 1e-6, loads=[load])
    if 'budget_a' in values:
        study['source_current_limit_A'] = values['budget_a']
    return study
