"""Explicit forward-drop models for a prescribed-current DC series path.

No device values are inferred from a KiCad symbol. The diode equation is
anchored at a user-supplied (current, voltage) point and evaluated only at the
DC operating current requested by Quick PI.
"""
from __future__ import annotations

import math
import re


_QUANTITY = re.compile(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(m|u|µ|μ|k)?\s*(V|A|C)?$')
_SCALE = {None: 1., 'm': 1e-3, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'k': 1e3}
_K_OVER_Q = 8.617333262145e-5  # V/K


def _quantity(text, unit):
    match = _QUANTITY.fullmatch(str(text).strip())
    if not match or match[3] != unit or (unit == 'C' and match[2]):
        raise ValueError(f'Enter a finite {unit} value: {text}')
    value = float(match[1]) * _SCALE[match[2]]
    if not math.isfinite(value) or (unit != 'C' and value < 0):
        raise ValueError(f'Enter a finite valid {unit} value: {text}')
    return value


def parse_drop(text):
    """Parse 1V/500mV or diode(Vf=0.7V,Iref=1A,n=2,T=25C)."""
    value = str(text).strip()
    if value.lower().startswith('diode(') and value.endswith(')'):
        fields = {}
        for item in value[6:-1].split(','):
            key, separator, raw = item.partition('=')
            if not separator or key.strip() not in {'Vf', 'Iref', 'n', 'T'} or key.strip() in fields:
                raise ValueError('Use diode(Vf=0.7V,Iref=1A,n=2,T=25C).')
            fields[key.strip()] = raw.strip()
        if set(fields) != {'Vf', 'Iref', 'n', 'T'}:
            raise ValueError('A diode needs Vf, Iref, n and T.')
        model = {'vf_ref_v': _quantity(fields['Vf'], 'V'),
                 'reference_current_a': _quantity(fields['Iref'], 'A'),
                 'ideality': float(fields['n']),
                 'temperature_c': _quantity(fields['T'], 'C')}
        validate_model({'diode': model})
        return {'resistance_ohm': 0., 'inductance_h': 0., 'diode': model}
    if value.endswith('V'):
        drop = _quantity(value, 'V')
        if drop <= 0:
            raise ValueError('A fixed forward drop must be positive.')
        return {'resistance_ohm': 0., 'inductance_h': 0., 'fixed_drop_v': drop}
    return None


def validate_model(branch):
    """Validate direct JSON requests as well as console-generated models."""
    if 'fixed_drop_v' in branch and 'diode' in branch:
        raise ValueError('Choose one forward-drop model per component.')
    if 'fixed_drop_v' in branch:
        value = float(branch['fixed_drop_v'])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Fixed forward drop must be finite and positive.')
    if 'diode' in branch:
        model = branch['diode']
        if not isinstance(model, dict) or set(model) != {'vf_ref_v', 'reference_current_a', 'ideality', 'temperature_c'}:
            raise ValueError('Diode needs Vf, Iref, n and T.')
        values = {key: float(value) for key, value in model.items()}
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError('Diode parameters must be finite.')
        if values['vf_ref_v'] <= 0 or values['reference_current_a'] <= 0 or not 1 <= values['ideality'] <= 4 or not -273.15 < values['temperature_c'] <= 250:
            raise ValueError('Diode needs positive Vf/Iref, 1 ≤ n ≤ 4 and -273.15 < T ≤ 250 C.')


def forward_drop(branch, current_a):
    """Return forward Vf at the known DC current; reverse current is unsupported."""
    validate_model(branch)
    current = float(current_a)
    if not math.isfinite(current) or current <= 0:
        raise ValueError('A forward-drop element needs a known positive path current; reverse/off-state diode solving is unsupported.')
    if 'fixed_drop_v' in branch:
        return float(branch['fixed_drop_v'])
    diode = branch['diode']
    thermal_v = float(diode['ideality']) * _K_OVER_Q * (float(diode['temperature_c']) + 273.15)
    anchor = float(diode['vf_ref_v']) / thermal_v
    if not math.isfinite(anchor):
        raise ValueError('Diode anchor is outside the supported numerical range.')
    # log(expm1(anchor)) without overflow, then log(1+exp(x)) without overflow.
    log_expm1 = anchor + math.log1p(-math.exp(-anchor)) if anchor > 50 else math.log(math.expm1(anchor))
    x = math.log(current) - math.log(float(diode['reference_current_a'])) + log_expm1
    drop = thermal_v * (max(x, 0) + math.log1p(math.exp(-abs(x))))
    if not math.isfinite(drop):
        raise ValueError('Computed diode forward drop is non-finite.')
    return drop
