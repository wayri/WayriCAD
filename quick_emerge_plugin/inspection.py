"""Inspection of original sampled field data; no interpolation is performed."""

import math
from bisect import bisect_left


def _finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _axis(values, name):
    try:
        result = tuple(_finite(v, name) for v in values)
    except TypeError as exc:
        raise ValueError(f"{name} must be an axis") from exc
    if not result or any(a >= b for a, b in zip(result, result[1:])):
        raise ValueError(f"{name} must be nonempty and strictly increasing")
    return result


def _nearest(axis, value):
    i = bisect_left(axis, value)
    if i == 0:
        return 0
    if i == len(axis):
        return i - 1
    return i - 1 if value - axis[i - 1] <= axis[i] - value else i


class FieldInspection:
    """Validate and inspect a rectangular field sampled on ordered axes."""

    def __init__(self, field):
        try:
            self.x = _axis(field['x_mm'], 'x_mm')
            self.y = _axis(field['y_mm'], 'y_mm')
            self.z = _finite(field['z_mm'], 'z_mm')
            self.slice_index = field.get('display_z_index')
            self.quantity = field.get('display_quantity', 'Temperature' if 'temperature_k' in field else 'E magnitude')
            self.unit = field.get('display_unit', 'K' if 'temperature_k' in field else 'V/m')
            self.value_key = field.get('display_value_key', 'temperature_k' if 'temperature_k' in field else 'value_v_m')
            self.frequency = None if 'temperature_k' in field else _finite(field['frequency_hz'], 'frequency_hz')
            self.time = _finite(field.get('time_s', 0), 'time_s')
            if self.frequency is not None and self.frequency <= 0:
                raise ValueError('frequency_hz must be positive')
            rows = tuple(tuple(row) for row in field.get('display_values', field.get('temperature_k', field.get('norm_e_v_m'))))
        except (KeyError, TypeError) as exc:
            raise ValueError('invalid field structure') from exc
        if len(rows) != len(self.y) or any(len(row) != len(self.x) for row in rows):
            raise ValueError('field dimensions must match y and x axes')
        converted = []
        for row in rows:
            converted_row = []
            for value in row:
                if value is not None:
                    value = _finite(value, 'field value')
                    if value < 0:
                        raise ValueError('field values must be nonnegative')
                converted_row.append(value)
            converted.append(tuple(converted_row))
        self.values = tuple(converted)

    def _sample(self, ix, iy):
        value = self.values[iy][ix]
        sample = {'x_mm': self.x[ix], 'y_mm': self.y[iy], 'z_mm': self.z,
                  self.value_key: value, 'quantity': self.quantity, 'unit': self.unit,
                  'ix': ix, 'iy': iy, 'unknown': value is None}
        if self.frequency is None: sample['time_s'] = self.time
        else: sample['frequency_hz'] = self.frequency
        if self.slice_index is not None: sample['iz'] = self.slice_index
        return sample

    def probe(self, x, y):
        x, y = _finite(x, 'x'), _finite(y, 'y')
        if not (self.x[0] <= x <= self.x[-1] and self.y[0] <= y <= self.y[-1]):
            raise ValueError('probe is outside the field grid')
        return self._sample(_nearest(self.x, x), _nearest(self.y, y))

    def extrema(self):
        known = [(v, ix, iy) for iy, row in enumerate(self.values)
                 for ix, v in enumerate(row) if v is not None]
        if not known:
            return {'min': None, 'max': None}
        low = min(known, key=lambda item: item[0])
        high = max(known, key=lambda item: item[0])
        return {'min': self._sample(low[1], low[2]),
                'max': self._sample(high[1], high[2])}

    def line(self, start, end, count=100):
        """Sample nearest grid points along the requested line; duplicates are expected."""
        if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 2000:
            raise ValueError('count must be an integer from 2 to 2000')
        try:
            x0, y0 = start
            x1, y1 = end
        except (TypeError, ValueError) as exc:
            raise ValueError('line endpoints must be coordinate pairs') from exc
        x0, y0 = _finite(x0, 'x'), _finite(y0, 'y')
        x1, y1 = _finite(x1, 'x'), _finite(y1, 'y')
        self.probe(x0, y0)
        self.probe(x1, y1)
        distance = math.hypot(x1 - x0, y1 - y0)
        result = []
        for i in range(count):
            t = i / (count - 1)
            sample = self.probe(x0 * (1 - t) + x1 * t, y0 * (1 - t) + y1 * t)
            sample['distance_mm'] = distance * t
            result.append(sample)
        return result


def scale_limits(values, mode='linear', minimum=None, maximum=None):
    """Return display limits; log scales ignore zero and unknown samples."""
    if mode not in ('linear', 'log'):
        raise ValueError('unknown scale mode')
    if (minimum is None) != (maximum is None):
        raise ValueError('both manual limits are required')
    known = []
    for value in values:
        if value is None:
            continue
        value = _finite(value, 'scale value')
        if value < 0:
            raise ValueError('scale values must be nonnegative')
        if mode == 'linear' or value > 0:
            known.append(value)
    if not known:
        raise ValueError('no plottable values')
    if minimum is not None:
        lo, hi = _finite(minimum, 'minimum'), _finite(maximum, 'maximum')
        if lo >= hi or (mode == 'log' and lo <= 0):
            raise ValueError('invalid scale limits')
        return lo, hi
    lo, hi = min(known), max(known)
    if lo == hi:
        if mode == 'log':
            lo, hi = lo / 10, hi * 10
            if lo <= 0 or not math.isfinite(hi):
                raise ValueError('cannot expand scale limits')
        else:
            padding = max(abs(lo) * 0.01, 1e-12)
            lo, hi = lo - padding, hi + padding
            if not math.isfinite(lo) or not math.isfinite(hi):
                raise ValueError('cannot expand scale limits')
    return lo, hi
