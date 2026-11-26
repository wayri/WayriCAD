'''Supply-relative DC compliance and presentation. Solver evidence remains in volts.'''

import math


def limits(nominal, percent):
    if isinstance(percent, bool) or isinstance(nominal, bool):
        raise ValueError('Voltage tolerance needs a nominal voltage and percentage.')
    try:
        nominal, percent = float(nominal), float(percent)
    except (TypeError, ValueError) as error:
        raise ValueError('Voltage tolerance needs a nominal voltage and percentage.') from error
    if not math.isfinite(nominal) or nominal <= 0:
        raise ValueError('Voltage tolerance requires a positive nominal source voltage.')
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError('Voltage tolerance must be between 0 and 100%.')
    fraction = percent / 100
    lower, upper = nominal * (1 - fraction), nominal * (1 + fraction)
    if not math.isfinite(upper):
        raise ValueError('Computed voltage limits must be finite.')
    return lower, upper


def request_limits(request):
    percent = request.get('voltage_tolerance_pct')
    return None if percent is None else limits(request.get('source_voltage', 1.), percent)


def intersect(minimum, maximum, tolerance):
    if tolerance is None:
        return minimum, maximum
    lower = max(minimum, tolerance[0])
    upper = min(maximum, tolerance[1]) if maximum is not None else tolerance[1]
    if lower > upper:
        raise ValueError('Explicit load voltage limits do not overlap the percentage tolerance.')
    return lower, upper


def annotate(result, request):
    '''Use the final operating point, including current adjustments and load limits.'''
    window = request_limits(request)
    if window is None:
        return
    result['voltage_tolerance'] = dict(nominal_V=float(request.get('source_voltage', 1.)),
        tolerance_pct=float(request['voltage_tolerance_pct']), min_voltage_V=window[0], max_voltage_V=window[1])
    refresh(result)


def refresh(result):
    compliance = result.get('voltage_tolerance')
    if not compliance:
        return
    nominal = compliance['nominal_V']
    rows = []
    for sink in result.get('sinks', []):
        voltage = sink.get('voltage_V')
        if voltage is None or not math.isfinite(voltage):
            rows.append(dict(id=sink['id'], state='Unavailable'))
            continue
        lower, upper = intersect(sink.get('min_voltage_V', 0.), sink.get('max_voltage_V'),
                                 (compliance['min_voltage_V'], compliance['max_voltage_V']))
        headroom = min(voltage - lower, upper - voltage)
        outside = sink.get('within_voltage_limits') is False or headroom < -1e-12 * nominal
        near = headroom <= nominal * compliance['tolerance_pct'] / 1000
        rows.append(dict(id=sink['id'], state='Fail' if outside else 'Near limit' if near else 'Pass',
                         voltage_pct=100*(voltage/nominal), drop_pct=100*((nominal-voltage)/nominal),
                         min_pct=100*(lower/nominal), max_pct=100*(upper/nominal),
                         headroom_pct_points=100*(headroom/nominal)))
    compliance['loads'] = rows


def nominal_voltage(result):
    nominal = result.get('source_voltage_V')
    if isinstance(nominal, (int, float)) and not isinstance(nominal, bool) and math.isfinite(nominal) and nominal > 0:
        return nominal
    return None


def show_exact(bundle):
    settings = bundle.get('view_settings', {})
    request = bundle.get('request', {})
    return settings.get('show_exact_voltages', request.get('show_exact_voltages',
                        request.get('voltage_tolerance_pct') is None))


def voltage_text(result, value, *, exact=True, drop=False):
    if value is None or not math.isfinite(value):
        return 'Unavailable'
    nominal = nominal_voltage(result)
    percent = f'{100*(value/nominal):.5g}%' if nominal else None
    absolute = f'{value*1000:.6g} mV' if drop else f'{value:.6g} V'
    if percent and exact:
        return f'{percent} ({absolute})'
    return percent if percent else absolute if exact else 'Unavailable'
