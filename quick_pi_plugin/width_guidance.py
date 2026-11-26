"""Bounded, read-only trace widening estimates from a solved 2.5D DC mesh."""

import math

import numpy as np


_STATIONS = (.183, .347, .503, .671, .817)
_HEADROOM = .10
_CURRENT_ERROR = .03
_DROP_ERROR = .10
_NOTICE = (
    "Screening estimate for the sampled straight part of one saved trace. "
    "It assumes the solved current and all other drops stay fixed. "
    "Each row considers widening that trace alone; recommendations are not additive. "
    "Review stackup, clearance and manufacturing limits, then re-solve the edited design."
)


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float, np.number))
            and math.isfinite(value))


def _slice(x, y, potentials, sheet_flux, station, width):
    """Integrate flux and mean potential on one transverse line through the mesh."""
    # Half-open triangle membership avoids counting both sides of a mesh edge.
    crosses = ((x.min(axis=1) <= station) & (station < x.max(axis=1))
               & (y.min(axis=1) <= width/2) & (y.max(axis=1) >= -width/2))
    intervals = []
    tolerance = max(2e-6, width * .01)
    for i in np.flatnonzero(crosses):
        cut = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            xa, xb = x[i, a], x[i, b]
            if not min(xa, xb) <= station <= max(xa, xb):
                continue
            if xa == xb:
                continue
            t = (station-xa)/(xb-xa)
            v = (1-t)*potentials[i, a]+t*potentials[i, b]
            cut.append(((1-t)*y[i, a]+t*y[i, b], v))
        if len(cut) < 2:
            continue
        (low, v_low), (high, v_high) = min(cut, key=lambda p: p[0]), max(cut, key=lambda p: p[0])
        if high-low <= 1e-10:
            continue
        if low < -width/2-tolerance or high > width/2+tolerance:
            return None
        intervals.append((low, high, sheet_flux[i], (v_low+v_high)/2))
    if not intervals:
        return None
    edge = -width/2
    current = unsigned_current = voltage = total = 0.
    for low, high, flux, voltage_mean in sorted(intervals, key=lambda item: item[0]):
        if abs(low-edge) > tolerance or not math.isfinite(flux) or not math.isfinite(voltage_mean):
            return None
        distance = high-low
        current += distance*flux
        unsigned_current += distance*abs(flux)
        voltage += distance*voltage_mean
        total += distance
        edge = high
    if abs(edge-width/2) > tolerance or abs(total-width) > tolerance:
        return None
    # Strong counterflow is incompatible with a one-dimensional trace model.
    if unsigned_current <= 0 or abs(current) < .95*unsigned_current:
        return None
    return current, voltage/total


def _width_row(feature, field, material, sink, budget, observed_drop, comfortable_drop):
    triangles, vertices, bounds, layers, thicknesses, potentials, sheet = field
    try:
        start = np.asarray(feature['start_mm'], dtype=float)
        end = np.asarray(feature['end_mm'], dtype=float)
        width = float(feature['width_mm'])
        layer = str(feature['layer'])
    except (KeyError, TypeError, ValueError):
        return None
    if start.shape != (2,) or end.shape != (2,) or not math.isfinite(width) or width <= 0:
        return None
    displacement = end-start
    length = math.hypot(*displacement)
    if not math.isfinite(length) or length < 2*width:
        return None
    direction = displacement / length
    normal = np.array([-direction[1], direction[0]])
    lower, upper = bounds
    corners = (start + displacement * np.array([[_STATIONS[0]], [_STATIONS[-1]]]))
    padding = abs(normal)*width/2 + 2e-6
    low, high = corners.min(axis=0)-padding, corners.max(axis=0)+padding
    indices = np.flatnonzero((layers == layer) & (lower <= high).all(axis=1)
                             & (upper >= low).all(axis=1))
    if not len(indices):
        return None
    local = vertices[indices]-start
    x, y = local @ direction, local @ normal
    near = ((x.max(axis=1) >= length*_STATIONS[0]) & (x.min(axis=1) <= length*_STATIONS[-1])
            & (y.min(axis=1) <= width/2) & (y.max(axis=1) >= -width/2))
    indices, x, y = indices[near], x[near], y[near]
    if not len(indices):
        return None
    thickness = thicknesses[indices]
    rho = _field_resistivity(material, indices, len(triangles))
    if rho is None or not np.isfinite(thickness).all() or thickness[0] <= 0:
        return None
    if not np.allclose(thickness, thickness[0], rtol=1e-6, atol=0):
        return None
    local_potentials = potentials[triangles[indices]]
    axial_flux = sheet[indices] @ direction
    samples = [_slice(x, y, local_potentials, axial_flux, station*length, width)
               for station in _STATIONS]
    if any(sample is None for sample in samples):
        return None
    currents, voltages = zip(*samples)
    current = math.fsum(currents)/len(currents)
    demand = sink['current_A']
    if not math.isclose(abs(current), demand, rel_tol=_CURRENT_ERROR):
        return None
    if any(not math.isclose(sample, current, rel_tol=_CURRENT_ERROR) for sample in currents):
        return None
    span_mm = (_STATIONS[-1]-_STATIONS[0])*length
    modeled_drop = abs(current)*rho*span_mm*1000/(width*float(thickness[0]))
    measured_drop = math.copysign(1., current)*(voltages[0]-voltages[-1])
    if measured_drop <= 0 or not math.isclose(measured_drop, modeled_drop, rel_tol=_DROP_ERROR, abs_tol=1e-9):
        return None
    if measured_drop > observed_drop + max(1e-9, observed_drop*1e-6):
        return None
    other_drop = max(0., observed_drop-measured_drop)
    allowance = budget-other_drop
    comfortable_allowance = comfortable_drop-other_drop
    minimum = None if allowance <= 1e-12 else width*max(1., measured_drop/allowance)
    suggested = None if comfortable_allowance <= 1e-12 else width*max(1., measured_drop/comfortable_allowance)
    if not all(value is None or math.isfinite(value) for value in (minimum, suggested)):
        return None
    if minimum is None:
        row_status = 'other_drop_exceeds_limit'
    elif suggested is None:
        row_status = 'widen_to_limit' if minimum > width*(1+1e-9) else 'headroom_target_unavailable'
        suggested = minimum
    else:
        row_status = 'widen'
    return dict(source_ids=[feature['id']], layer=feature['layer'], status=row_status,
                location_mm=((start+end)/2).tolist(),
                existing_width_mm=width, minimum_width_mm=minimum, recommended_width_mm=suggested,
                width_change_mm=None if suggested is None else suggested-width,
                sampled_current_A=abs(current), copper_thickness_mm=float(thickness[0]),
                sampled_length_mm=span_mm, sampled_drop_V=measured_drop,
                remaining_trace_budget_V=allowance, voltage_headroom_V=budget-observed_drop,
                recommended_sink_voltage_V=None if suggested is None else
                sink['voltage_V']+measured_drop*(1-width/suggested))


def _field_resistivity(material, indices, ntriangles):
    if not isinstance(material, dict):
        return None
    per_triangle = material.get('triangle_resistivity_ohm_m')
    if per_triangle is None:
        value = material.get('resistivity_ohm_m')
        return float(value) if _number(value) and value > 0 else None
    values = np.asarray(per_triangle, dtype=float)
    if values.shape != (ntriangles,):
        return None
    local = values[indices]
    if not np.isfinite(local).all() or local[0] <= 0 or not np.allclose(local, local[0], rtol=1e-6, atol=0):
        return None
    return float(local[0])


def recommend_trace_widths(mesh, result, minimum_voltage_V=None):
    """Recommend candidate widths for a saved, constant-current single-sink DC solve.

    The measured drop of the central sampled span is the original contribution.
    Scaling only that contribution by old width / new width yields the estimate.
    If possible, the suggested width uses at most 90% of the declared drop budget.
    This never changes the board or promises a margin after current redistributes.
    """
    def output(status, reason, rows=()):
        return dict(status=status, reason=reason, notice=_NOTICE, rows=list(rows))

    sinks = result.get('sinks') or []
    if ('2.5D' not in str(result.get('model') or '') or len(sinks) != 1 or mesh.get('lumped_branches')
            or result.get('physical_return') or result.get('operating_mode') not in (None, 'constant_current')):
        return output('unavailable', 'Requires a 2.5D fixed-current single-sink solve without lumped branches.')
    sink = sinks[0]
    voltage = sink.get('voltage_V')
    source = result.get('source_voltage_V')
    lower = sink.get('min_voltage_V') if minimum_voltage_V is None else minimum_voltage_V
    upper = sink.get('max_voltage_V')
    demand = sink.get('current_A')
    if not all(_number(value) for value in (lower, voltage, source, demand)) or lower <= 0 or demand <= 0:
        return output('unavailable', 'Declare a positive minimum load voltage to compute a trace-drop budget.')
    if _number(upper) and (voltage >= upper or lower >= upper):
        return output('unavailable', 'A width increase cannot address the upper voltage limit.')
    budget = source-lower
    if budget <= 0:
        return output('unavailable', 'Source voltage leaves no positive allowable drop to the minimum load voltage.')
    drop = source-voltage
    if drop <= (1-_HEADROOM)*budget:
        return output('not_needed', 'The solved sink retains at least 10% of the declared drop budget.')
    comfortable_voltage = source-(1-_HEADROOM)*budget
    if _number(upper) and comfortable_voltage > upper:
        comfortable_voltage = upper

    geometry = mesh.get('geometry', {})
    candidates = list(dict.fromkeys(identifier for row in (result.get('fusing') or {}).get('bottlenecks', [])
                                    if row.get('kind') == 'sheet' and len(row.get('source_ids', [])) == 1
                                    for identifier in row['source_ids']))
    features = {feature['id']: feature for feature in geometry.get('mesh_features', [])
                if feature.get('kind') == 'track' and feature.get('id')}
    candidates = [identifier for identifier in candidates if identifier in features][:12]
    if not candidates:
        return output('unavailable', 'No bottleneck was tied to a saved straight trace UUID.')
    try:
        points = np.asarray(mesh['points_mm'], dtype=float)
        triangles = np.asarray(mesh['triangles'], dtype=int)
        layers = np.asarray(mesh['triangle_layer'], dtype=str)
        thickness = np.asarray(mesh['triangle_thickness_mm'], dtype=float)
        potentials = np.asarray(result['potential_V'], dtype=float)
        current = np.asarray([v if v is not None else (np.nan, np.nan)
                              for v in result['cell_sheet_current_A_mm']], dtype=float)
        if (points.ndim != 2 or points.shape[1] < 2 or triangles.ndim != 2 or triangles.shape[1] != 3
                or thickness.shape != (len(triangles),) or layers.shape != (len(triangles),)
                or potentials.shape != (len(points),) or current.shape != (len(triangles), 2)
                or triangles.min() < 0 or triangles.max() >= len(points)):
            return output('unavailable', 'The saved result has incomplete mesh or sheet-current evidence.')
        vertices = points[triangles, :2]
        bounds = vertices.min(axis=1), vertices.max(axis=1)
        field = triangles, vertices, bounds, layers, thickness, potentials, current
        material = result.get('material', {})
        rows = [row for identifier in candidates if
                (row := _width_row(features[identifier], field, material, sink, budget, drop,
                                   source-comfortable_voltage)) is not None]
    except (KeyError, TypeError, ValueError, OverflowError):
        return output('unavailable', 'The saved result has incomplete mesh or sheet-current evidence.')
    if not rows:
        return output('unavailable', 'No sampled bottleneck had an isolated, uniform strip carrying the solved sink current.')
    rows.sort(key=lambda row: (-row['sampled_drop_V'], str(row['source_ids'][0])))
    return output('available', 'Screened straight tracks carrying the solved sink current.', rows[:4])
