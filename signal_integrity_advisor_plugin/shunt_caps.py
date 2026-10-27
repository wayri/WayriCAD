"""Explicit endpoint shunt capacitors for native transient circuit exports.

Each branch is signal--ESR--ESL--C--ideal reference. Zero ESR/ESL omits that
element. Values are entered assumptions, not inferred PCB/package parasitics.
"""
from __future__ import annotations

import math

MAX_CASE_CAPACITORS = 64
MAX_TOTAL_CAPACITORS = 256


def _number(value, label, *, positive=False, maximum=1e12):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(label+' must be a finite number.') from error
    if not math.isfinite(number) or number < 0 or (positive and number == 0) or number > maximum:
        raise ValueError(label+' must be finite, '+('positive' if positive else 'nonnegative')+f' and at most {maximum:g}.')
    return number


def capacitor_branches(rows):
    """Validate and detach one case's capacitor branches in F, Ω and H."""
    if not isinstance(rows, list) or len(rows) > MAX_CASE_CAPACITORS:
        raise ValueError(f'Enter at most {MAX_CASE_CAPACITORS} shunt capacitors per case.')
    result = []; identifiers = set()
    for row in rows:
        if not isinstance(row, dict) or set(row)-{'id', 'at', 'capacitance_F', 'esr_ohm', 'esl_H'}:
            raise ValueError('Shunt capacitor fields are id, at, capacitance_F, esr_ohm and esl_H.')
        ident = row.get('id')
        if isinstance(ident, str):ident = ident.strip()
        if not isinstance(ident, str) or not ident or len(ident) > 128 or ident in identifiers:
            raise ValueError('Shunt capacitor IDs must be unique nonempty strings up to 128 characters.')
        if row.get('at') not in ('source', 'receiver'):
            raise ValueError(ident+': choose source or receiver; arbitrary along-route placement is unsupported.')
        identifiers.add(ident)
        result.append(dict(id=ident, at=row['at'],
                           capacitance_F=_number(row.get('capacitance_F'), ident+' capacitance_F', positive=True, maximum=1000),
                           esr_ohm=_number(row.get('esr_ohm', 0), ident+' esr_ohm'),
                           esl_H=_number(row.get('esl_H', 0), ident+' esl_H', maximum=1000)))
    return result


def editor_branches(rows, case_ids):
    """Convert reviewed grid rows [case,id,at,C nF,ESR mΩ,ESL nH] to SI."""
    result = {key: [] for key in case_ids}
    if len(rows) > MAX_TOTAL_CAPACITORS:
        raise ValueError(f'Enter at most {MAX_TOTAL_CAPACITORS} shunt capacitors in one export.')
    for index, values in enumerate(rows, 1):
        if len(values) != 6:
            raise ValueError(f'Row {index}: six shunt capacitor fields are required.')
        case, ident, position, capacitance, esr, esl = [str(value).strip() for value in values]
        # A fresh placeholder is harmless only if its capacitor ID/value are empty.
        if not ident and not capacitance and not esr and not esl:
            continue
        if case not in result:
            raise ValueError(f'Row {index}: select an exported case.')
        result[case].append(dict(id=ident, at=position,
                                 capacitance_F=_number(capacitance, f'Row {index} C · nF', positive=True, maximum=1e12)*1e-9,
                                 esr_ohm=_number(esr or 0, f'Row {index} ESR · mΩ')*1e-3,
                                 esl_H=_number(esl or 0, f'Row {index} ESL · nH')*1e-9))
    return {key: capacitor_branches(value) for key, value in result.items()}


def editor_rows(mapping):
    """Preserve reviewed identities and convert SI branch values for the grid."""
    return [[case, row['id'], row['at'], f"{row['capacitance_F']*1e9:.12g}",
             f"{row['esr_ohm']*1e3:.12g}", f"{row['esl_H']*1e9:.12g}"]
            for case, branches in mapping.items() for row in capacitor_branches(branches)]
