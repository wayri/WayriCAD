"""Reviewed capacitor-bank inputs and exact saved-pad candidate discovery."""
from __future__ import annotations

from collections import defaultdict
import math
import re
from .transient import MAX_SHUNTS_PER_LOAD


SCALES = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'm': 1e-3, '': 1.}


def capacitance_value(text, *, bare_scale=None, allow_description=False):
    """Parse explicit SI capacitance; bare values need a declared display unit.

    Saved component descriptions may follow a recognized leading value. Bare
    capacitor codes such as 104 are ambiguous and are not decoded implicitly.
    """
    raw = str(text).strip()
    if allow_description:
        # BOM-style names such as CC0402_100NF_25V carry an explicit unit.
        # Never interpret package numbers, voltage ratings or bare chip codes.
        matches=re.findall(r'(?<![A-Za-z0-9.])([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([pPnNuUµμm]?)[fF](?![A-Za-z0-9])',raw)
        values={float(number)*SCALES[prefix.lower()] for number,prefix in matches}
        if values:
            if len(values)!=1:raise ValueError('Several capacitance values are present; enter one reviewed effective C.')
            value=values.pop()
            if not math.isfinite(value) or value<=0:raise ValueError('Capacitance must be finite and positive.')
            return value
    end = r'(?=$|\s)' if allow_description else r'\s*$'
    match = re.match(r'^(\d+)([pnuµμm])(\d+)(?:[fF])?'+end, raw)
    if match:
        value = float(match[1]+'.'+match[3])*SCALES[match[2]]
    else:
        match = re.match(r'^([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([pnuµμm]?)([fF]?)'+end, raw)
        if not match:
            raise ValueError('Enter capacitance such as 100nF, 4n7 or 0.1uF.')
        prefix, suffix = match[2], match[3]
        scale = SCALES[prefix] if prefix or suffix else bare_scale
        if scale is None:
            raise ValueError('Saved capacitance needs a unit; bare codes are not inferred.')
        value = float(match[1])*scale
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Capacitance must be finite and positive.')
    return value


def candidates(terminals, signal_net, return_net, assigned=()):
    """Find two-pad C-reference footprints on an explicitly chosen net pair.

    Inventory entries must have saved footprint and pad UUIDs. Discovery is a
    review aid only: ESR, mounting ESL, bias derating and inclusion are not inferred.
    """
    if not signal_net or not return_net or signal_net == return_net:
        return []
    groups = defaultdict(list)
    for pad in terminals:
        if pad.get('footprint_uuid'):
            groups[pad['footprint_uuid']].append(pad)
    found = []
    for owner, pads in groups.items():
        if (len(pads) != 2 or any(p.get('footprint_pad_count')!=2 for p in pads) or
                len({p.get('id') for p in pads}) != 2 or any(not p.get('id') for p in pads)):
            continue
        refs = {p.get('reference', '') for p in pads}
        if len(refs) != 1 or not re.fullmatch(r'C\d+[A-Za-z]?', next(iter(refs))):
            continue
        if {p.get('net') for p in pads} != {signal_net, return_net}:
            continue
        reference = next(iter(refs)); identifier = reference+'@'+owner
        if identifier in assigned:
            continue
        raw = str(pads[0].get('component_value', ''))
        try: capacity = capacitance_value(raw,allow_description=True)
        except ValueError: capacity = None
        found.append(dict(id=identifier, reference=reference, value=raw,
                          capacitance_F=capacity, footprint_uuid=owner))
    return sorted(found, key=lambda row:(row['reference'], row['footprint_uuid']))


def bank_from_rows(rows):
    """Convert explicit branch rows (C or bare µF, ESR mΩ, total ESL nH)."""
    if len(rows)>MAX_SHUNTS_PER_LOAD:
        raise ValueError(f'At most {MAX_SHUNTS_PER_LOAD} capacitor branches per load.')
    bank=[];seen=set()
    for index, values in enumerate(rows, 1):
        if len(values)!=4:
            raise ValueError('Each branch needs ID, C, ESR and ESL.')
        identifier, capacity, resistance, inductance = values
        identifier=str(identifier).strip()
        if not identifier or len(identifier)>128 or identifier in seen:
            raise ValueError(f'Row {index}: use a unique capacitor ID of 1–128 characters.')
        seen.add(identifier)
        def number(text, label, scale):
            try:
                if not str(text).strip():raise ValueError()
                value=float(text)*scale
            except (TypeError,ValueError,OverflowError) as error:
                raise ValueError(f'{identifier}: enter explicit {label}; zero deliberately omits it.') from error
            if not math.isfinite(value) or value<0:
                raise ValueError(f'{identifier}: {label} must be finite and nonnegative.')
            return value
        bank.append(dict(id=identifier, capacitance_F=capacitance_value(capacity,bare_scale=1e-6),
                         esr_ohm=number(resistance,'ESR in mΩ',1e-3),
                         esl_H=number(inductance,'total ESL in nH',1e-9)))
    return bank


def bank_rows(bank):
    """Render normalized per-branch values without reducing unlike components."""
    return [[row['id'],f"{row['capacitance_F']/1e-6:.12g}",f"{row['esr_ohm']/1e-3:.12g}",
             f"{row['esl_H']/1e-9:.12g}"] for row in bank]
