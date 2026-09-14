"""Bounded decimal quantities for analytics and threshold filters.

No expressions, network calls, locale guesses or unit guesses from MPNs.
Canonical quantities are grams, watts, degrees Celsius and percent.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import re

D = Decimal
# token -> (dimension, multiplier, offset); canonical = scalar * multiplier + offset
UNITS = {
    'number': ('number', D(1), D(0)),
    'g': ('mass', D(1), D(0)), 'mg': ('mass', D('.001'), D(0)),
    'ug': ('mass', D('.000001'), D(0)), 'kg': ('mass', D(1000), D(0)),
    'W': ('power', D(1), D(0)), 'mW': ('power', D('.001'), D(0)),
    'uW': ('power', D('.000001'), D(0)), 'kW': ('power', D(1000), D(0)),
    'C': ('temperature', D(1), D(0)), 'K': ('temperature', D(1), D('-273.15')),
    'F': ('temperature', None, None),  # use (F - 32) * 5 / 9, without a rounded scale
    '%': ('percent', D(1), D(0)), 'ratio': ('percent', D(100), D(0)),
    'V': ('voltage', D(1), D(0)), 'mV': ('voltage', D('.001'), D(0)),
    'kV': ('voltage', D(1000), D(0)),
    'A': ('current', D(1), D(0)), 'mA': ('current', D('.001'), D(0)),
    'uA': ('current', D('.000001'), D(0)),
    'mm': ('length', D(1), D(0)), 'cm': ('length', D(10), D(0)),
    'm': ('length', D(1000), D(0)),
}
ALIASES = {'': 'number', '1': 'number', 'µg': 'ug', 'μg': 'ug', 'µW': 'uW',
           'μW': 'uW', 'µA': 'uA', 'μA': 'uA', '°C': 'C', 'degC': 'C',
           '°F': 'F', 'degF': 'F', 'celsius': 'C', 'fahrenheit': 'F',
           'kelvin': 'K', 'gram': 'g', 'grams': 'g', 'watt': 'W', 'watts': 'W',
           'percent': '%'}
CANONICAL = {'mass':'g', 'power':'W', 'temperature':'C', 'number':'number',
             'percent':'%', 'voltage':'V', 'current':'A', 'length':'mm'}
_NUM = r'[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,2})?'
_QUANTITY = re.compile(r'^\s*(' + _NUM + r')(?:\s*/\s*(' + _NUM + r'))?\s*([^\d\s].*?)?\s*$')
MISSING = {'', 'n/a', 'na', 'unknown', 'tbd', 'none', 'null', '-', '—', '?'}

@dataclass(frozen=True)
class Quantity:
    value: Decimal | None
    status: str
    dimension: str | None = None
    input_unit: str | None = None
    reason: str = ''
    assumed_unit: bool = False


def unit_name(unit: str) -> str:
    if not isinstance(unit, str):
        raise ValueError('Unit must be text.')
    unit = unit.strip()
    name = ALIASES.get(unit, unit)
    if name not in UNITS:
        raise ValueError('Unsupported unit: ' + unit + '. Choose an explicit supported unit.')
    return name


def scalar(text) -> Decimal | None:
    """Decimal with dot separator and optional English thousands groups; bounded."""
    if isinstance(text, bool):
        return None
    s = str(text).strip()
    if len(s) > 96 or not re.fullmatch(_NUM, s):
        return None
    try:
        n = D(s.replace(',', ''))
        return n if n.is_finite() and abs(n) <= D('1e18') and (not n or n.adjusted() >= -18) else None
    except (ValueError, InvalidOperation):
        return None


def parse(value, default_unit='number', *, dimension=None, nonnegative=False) -> Quantity:
    default_unit = unit_name(default_unit)
    expected = dimension or UNITS[default_unit][0]
    s = str(value if value is not None else '').strip()
    if s.casefold() in MISSING:
        return Quantity(None, 'missing', expected, reason='No numeric observation.')
    if isinstance(value, bool) or len(s) > 160:
        return Quantity(None, 'invalid', expected, reason='Not a bounded numeric quantity.')
    m = _QUANTITY.fullmatch(s)
    if not m:
        return Quantity(None, 'invalid', expected, reason='Use one number (dot decimal), optionally followed by a supported unit.')
    n = scalar(m[1])
    if n is None:
        return Quantity(None, 'invalid', expected, reason='Number outside supported finite range.')
    if m[2] is not None:
        den = scalar(m[2])
        if den is None or den == 0:
            return Quantity(None, 'invalid', expected, reason='Invalid fraction denominator.')
        with localcontext() as ctx:
            ctx.prec = 40
            n = n / den
    try:
        u = unit_name(m[3]) if m[3] else default_unit
    except ValueError as exc:
        return Quantity(None, 'invalid', expected, reason=str(exc))
    dim, scale, offset = UNITS[u]
    if dim != expected:
        return Quantity(None, 'invalid', expected, u, 'Unit dimension does not match the configured field.')
    with localcontext() as ctx:
        ctx.prec = 40
        canonical = (n - 32) * 5 / 9 if u == 'F' else n * scale + offset
    if not canonical.is_finite() or abs(canonical) > D('1e18') or (canonical and canonical.adjusted() < -18):
        return Quantity(None, 'invalid', dim, u, 'Converted quantity outside supported range.')
    if dim == 'temperature' and canonical < D('-273.15'):
        return Quantity(None, 'invalid', dim, u, 'Temperature is below absolute zero.')
    if nonnegative and canonical < 0:
        return Quantity(None, 'invalid', dim, u, 'Negative values are not permitted for this metric.')
    return Quantity(canonical, 'known', dim, u, assumed_unit=not bool(m[3]))


def literal(value, default_unit='number') -> Quantity:
    """Parse a threshold. An explicit literal unit may establish its dimension."""
    m = _QUANTITY.fullmatch(str(value).strip())
    unit = unit_name(default_unit)
    if m and m[3] and unit == 'number':
        try:
            unit = unit_name(m[3])
        except ValueError:
            pass
    return parse(value, unit)


def compare(left: Decimal, operator: str, right: Decimal) -> bool:
    if operator == '<': return left < right
    if operator == '<=': return left <= right
    if operator == '>': return left > right
    if operator == '>=': return left >= right
    if operator == '=': return left == right
    if operator == '!=': return left != right
    raise ValueError('Unsupported numeric comparator.')


def compact_condition(condition: str):
    if not isinstance(condition, str) or len(condition) > 256:
        raise ValueError('Threshold condition must be text of at most 256 characters.')
    m = re.fullmatch(r'\s*(<=|>=|!=|=|<|>)\s*(.+?)\s*', condition)
    if not m:
        raise ValueError('Enter a comparator and value, for example <80 or >=0.25 W.')
    return m[1], m[2]


def text(value: Decimal | int | None):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        return str(value)
    # Plain decimal JSON strings preserve precision. Do not round per component.
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result
