'''Read-only saved PCB inventory for the local Assistant.'''

from collections import defaultdict
import hashlib
from heapq import nsmallest
import math
from pathlib import Path
import re


def fingerprint(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        return digest.hexdigest()


def load_inventory(path):
    import pcbnew

    if Path(path).stat().st_size > 512 * 1024 * 1024:
        raise ValueError("Saved PCB exceeds the Assistant input limit.")
    before = fingerprint(path)
    board = pcbnew.LoadBoard(str(path))
    if board is None:
        raise ValueError('KiCad could not read the saved PCB.')
    parts = {}
    repeated = set()
    pads = defaultdict(set)
    ambiguous_pads = set()
    seen_pads = set()
    nets = {str(row.GetNetname()) for row in board.GetNetsByNetcode().values() if row.GetNetname()}
    for footprint in board.GetFootprints():
        ref = str(footprint.GetReference())
        if ref in parts:
            repeated.add(ref)
        parts[ref] = str(footprint.GetValue())
        for pad in footprint.Pads():
            net = str(pad.GetNetname())
            if pad.GetNumber():
                label = f'{ref}.{pad.GetNumber()}'
                if label in seen_pads:
                    ambiguous_pads.add(label)
                seen_pads.add(label)
                if net:
                    pads[label].add(net)
    if fingerprint(path) != before:
        raise ValueError('The saved PCB changed while reading circuit names. Reload it and try again.')
    for ref in repeated:
        del parts[ref]
    unique_pads = {name: values for name, values in pads.items()
                   if name.rsplit('.', 1)[0] not in repeated and name not in ambiguous_pads}
    return CircuitInventory(nets, parts, unique_pads, before)


class CircuitInventory:
    def __init__(self, nets, parts, pads, sha256=None):
        self.nets = tuple(sorted(nets, key=lambda name: (name.casefold(), name)))
        self.parts = parts
        self.pads = pads
        self.sha256 = sha256
        self.net_aliases = defaultdict(set)
        for name in self.nets:
            for alias in {name.casefold(), name.rsplit('/', 1)[-1].casefold()}:
                self.net_aliases[alias].add(name)
        self.pad_aliases = {name.casefold(): name for name in pads}
        self.ref_aliases = {name.casefold(): name for name in parts}
        self._pads_by_ref = defaultdict(list)
        for pad in self.pads:
            self._pads_by_ref[pad.rsplit('.', 1)[0].casefold()].append(pad)

    def pads_for(self, reference, net=None):
        return [pad for pad in self._pads_by_ref.get(reference.casefold(), ())
                if net is None or net in self.pads[pad]]

    def contact_nets(self, reference, pads):
        if not pads:
            return set().union(*(self.pads[pad] for pad in self.pads_for(reference)))
        return set.intersection(*(set(self.pads.get(self.pad_aliases.get(pad.casefold()), ())) for pad in pads))

    def net_matches(self, name):
        exact = name in self.nets
        if exact:
            return [name]
        return sorted(self.net_aliases.get(name.casefold(), ()), key=lambda name: (name.casefold(), name))

    def infer_net(self, endpoints):
        candidates = []
        for endpoint in endpoints:
            if not endpoint:
                return None
            name = self.pad_aliases.get(endpoint.casefold())
            if name is None:
                return None
            candidates.append(self.pads[name])
        shared = set.intersection(*candidates)
        return next(iter(shared)) if len(shared) == 1 else None

    def suggestions(self, fragment, limit=8):
        key = fragment.casefold()
        if not key:
            return []
        def matches():
            for kind, values in (('Net', self.nets), ('Part', self.parts), ('Pad', self.pads)):
                for value in values:
                    full = value.casefold()
                    short = full.rsplit('/', 1)[-1]
                    detail = self.parts.get(value, '') if kind == 'Part' else ''
                    if full.startswith(key) or short.startswith(key):
                        score = 0 if full == key or short == key else 1
                    elif key in full or (len(key) > 2 and key in detail.casefold()):
                        score = 2
                    else:
                        continue
                    yield score, kind, value, detail

        rows = nsmallest(limit, matches(), key=lambda row: (row[0], row[2].casefold(), row[1]))
        return [(kind, value, detail) for _, kind, value, detail in rows]


def completion_span(text, cursor):
    '''Current token or unfinished quoted hierarchical net, including spaces.'''
    left = text[:cursor]
    if left.count('"') % 2:
        start = left.rfind('"') + 1
        end = text.find('"', cursor)
        return start, len(text) if end < 0 else end, left[start:], True
    token = re.search(r'[^\s,;"]+$', left)
    end = re.match(r'[^\s,;"]*', text[cursor:]).end()+cursor
    return (token.start(), end, token.group(), False) if token else (cursor, end, '', False)


def result_message(value):
    '''Format only recognized fields from a completed local tool report.'''
    if not isinstance(value, dict):
        return ''
    if value.get('schema') == 'wayricad.assistant-capabilities/v1':
        tools = sorted({row['tool'] for row in value.get('actions', []) if row.get('tool') != 'assistant'})
        return 'Registered tools: ' + ', '.join(tools) + '. Ask about a tool for available actions.'
    batch = value.get('batch')
    if isinstance(batch, dict) and isinstance(batch.get('cases'), list):
        rows = [row for row in batch['cases'] if isinstance(row, dict)]
        lines = [f'{sum(row.get("status") == "COMPLETED" for row in rows)}/{len(rows)} rail cases completed']
        for row in rows[:6]:
            result = row.get('electrical', {}).get('result', {})
            line = result_message(result) or str(row.get('status', 'Unknown'))
            lines.append(f"{row.get('name', 'Rail')} · {line}")
        if len(rows) > 6:
            lines.append('Open the study report for the remaining rails.')
        return '\n'.join(lines)
    transient = value.get('transient')
    if isinstance(transient, dict) and isinstance(transient.get('loads'), list):
        lines = ['Load-step transient']
        limits = transient.get('limits', {}).get('within_all_specified_limits')
        if limits is False:
            lines.append('Voltage or current limit violation')
        for row in transient['loads'][:6]:
            if not isinstance(row, dict):
                continue
            low, high = row.get('min_voltage_V'), row.get('max_voltage_V')
            if all(isinstance(x, (float, int)) and math.isfinite(x) for x in (low, high)):
                lines.append(f"{row.get('label', row.get('id', 'Load'))} · {low:.5g}–{high:.5g} V")
        return '\n'.join(lines)
    fields = (('voltage_drop_V', 'Voltage drop', 'mV', 1000),
              ('sink_voltage_V', 'Sink voltage', 'V', 1),
              ('total_power_W', 'Power loss', 'W', 1),
              ('delay_ns', 'Delay', 'ns', 1),
              ('single_ended_z0_ohm', 'Impedance', 'Ω', 1),
              ('peak_temperature_c', 'Peak temperature', '°C', 1),
              ('maximum_temperature_c', 'Maximum temperature', '°C', 1))
    numbers = [f'{label} {value[key]*scale:.5g} {unit}' for key, label, unit, scale in fields
               if isinstance(value.get(key), (float, int)) and not isinstance(value[key], bool)
               and math.isfinite(value[key])]
    status = value.get('status')
    if numbers and isinstance(status, str):
        numbers.insert(0, status)
    summary = ' · '.join(numbers)
    sinks = value.get('sinks')
    if not isinstance(sinks, list) or len(sinks) < 2:
        return summary
    readings = []
    for row in sinks[:6]:
        if not isinstance(row, dict):
            continue
        current, voltage = row.get('current_A'), row.get('voltage_V')
        if all(type(v) in (float, int) and math.isfinite(v) for v in (current, voltage)):
            readings.append(f"{row.get('label') or row.get('id') or 'Load'} · {current:.5g} A at {voltage:.5g} V")
    if len(sinks) > 6:
        readings.append('Open the study report for the remaining load groups.')
    return '\n'.join(([summary] if summary else []) + readings)
