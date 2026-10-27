"""Constant-power DC loads on a fixed, linear, passive copper mesh.

Reduce the FEM to its power ports once; nonlinear iterations never remesh or
re-solve a full field. The high-voltage branch must have positive incremental
stiffness. This is a DC operating point, not converter dynamic stability.
"""
from __future__ import annotations

import math


def requested(request):
    return request.get('load_power_W') is not None or any(
        isinstance(row, dict) and 'power_W' in row for row in request.get('sinks', []) or [])


def guard(request):
    if not requested(request):
        return
    if (request.get('action', 'inspect') not in ('solve', 'geometry', 'mesh', 'inspect') or
            request.get('model_dimension', '2.5d') != '2.5d' or request.get('series') or
            request.get('package_conduction') or request.get('load_resistance_ohm') is not None):
        raise ValueError('Constant-power loads require fixed-temperature 2.5D copper; '
                         'series, package, resistive-load, sweep, convergence, AC, electrothermal and transient modes are unsupported.')
    source = request.get('source_voltage', 1.)
    if isinstance(source, bool):
        raise ValueError('Constant-power source voltage must be finite and positive.')
    try:
        source = float(source)
    except (TypeError, ValueError) as exc:
        raise ValueError('Constant-power source voltage must be finite and positive.') from exc
    if not math.isfinite(source) or source <= 0:
        raise ValueError('Constant-power source voltage must be finite and positive.')


def seed_specs(specs, source_voltage):
    """Positive seed currents used only for terminal resolution and reduction."""
    return [dict(row, current_A=row['power_W']/float(source_voltage)) if 'power_W' in row else dict(row)
            for row in specs]


def high_voltage_solution(open_voltage, resistance, powers):
    """Solve V = Voc - R(P/V), staying on the positive incremental branch."""
    import numpy as np
    a = np.asarray(open_voltage, dtype=float)
    r = np.asarray(resistance, dtype=float)
    p = np.asarray(powers, dtype=float)
    if (a.ndim != 1 or not len(a) or p.shape != a.shape or r.shape != (len(a), len(a)) or
            not all(np.all(np.isfinite(x)) for x in (a, r, p)) or np.any(a <= 0) or np.any(p <= 0)):
        raise ValueError('Constant-power inputs require finite positive open-circuit voltages and powers.')
    scale = max(float(np.max(np.abs(r))), 1e-30)
    if np.max(np.abs(r-r.T)) > scale*1e-7 or np.min(r) < -scale*1e-9:
        raise ValueError('Power-port reduction is not reciprocal/passive; refine or repair the mesh.')
    r = (r+r.T)*.5
    if np.linalg.eigvalsh(r)[0] < -scale*1e-9:
        raise ValueError('Power-port reduction is not passive; refine or repair the mesh.')
    v = a.copy()

    def margin(voltage):
        weight = np.sqrt(p)/voltage
        return 1.-float(np.linalg.eigvalsh(weight[:, None]*r*weight[None, :])[-1])

    for iteration in range(100):
        f = v-a+r@(p/v)
        residual = float(np.max(np.abs(f)/a))
        stable_margin = margin(v)
        if residual < 1e-12:
            if stable_margin <= 1e-5:
                raise ValueError('Constant-power voltage collapse: marginal DC branch; reduce demand or path resistance.')
            return v, {'iterations': iteration, 'relative_voltage_residual': residual,
                       'incremental_stability_margin': stable_margin}
        if stable_margin <= 0:
            break
        jacobian = np.eye(len(v))-r*(p/v**2)[None, :]
        try:
            step = np.linalg.solve(jacobian, -f)
        except np.linalg.LinAlgError:
            break
        fraction = 1.
        for _ in range(60):
            candidate = v+fraction*step
            if np.all(candidate > 0) and margin(candidate) > 0:
                error = float(np.max(np.abs(candidate-a+r@(p/candidate))/a))
                if error < residual:
                    v = candidate
                    break
            fraction *= .5
        else:
            break
    raise ValueError('Constant-power voltage collapse or unresolved operating point: '
                     'no converged high-voltage stable DC branch; reduce demand or path resistance.')


def solve_power(mesh, source_nodes, sinks, *, source_voltage=1., source_current_limit=None,
                options=None, **budgets):
    """Compute port response, then one final conservative FEM field solution."""
    import numpy as np
    from .solver import solve
    specs = sinks
    indices = [i for i, row in enumerate(specs) if 'power_W' in row]
    if not indices:
        raise ValueError('At least one constant-power sink is required.')
    source_voltage = float(source_voltage)
    powers = np.asarray([specs[i]['power_W'] for i in indices], dtype=float)
    if not math.isfinite(source_voltage) or source_voltage <= 0 or np.any(~np.isfinite(powers)) or np.any(powers <= 0):
        raise ValueError('Source voltage and constant powers must be finite and positive.')
    seeds = seed_specs(specs, source_voltage)
    def field(rows):
        return solve(mesh, source_nodes, source_voltage=source_voltage, sinks=rows,
                     source_current_limit=source_current_limit, options=options, **budgets)
    basis = field(seeds)
    base_drop = np.asarray([row['voltage_drop_V'] for row in basis['sinks']])
    del basis
    response = np.empty((len(specs), len(indices)))
    # Unit perturbations need only the selected power ports, even for many
    # fixed-current endpoints. Existing positive-current FEM checks stay intact.
    for column, index in enumerate(indices):
        probe = [dict(row) for row in seeds]
        delta = max(1., seeds[index]['current_A'])
        probe[index]['current_A'] += delta
        measured = field(probe)
        response[:, column] = (np.asarray([row['voltage_drop_V'] for row in measured['sinks']])-base_drop)/delta
        del measured
    seeded_power_current = np.asarray([seeds[i]['current_A'] for i in indices])
    open_voltage = source_voltage-base_drop+response@seeded_power_current
    voltage, evidence = high_voltage_solution(open_voltage[indices], response[indices, :], powers)
    currents = powers/voltage
    final_specs = [dict(row) for row in seeds]
    for index, current in zip(indices, currents):
        final_specs[index]['current_A'] = float(current)
    result = field(final_specs)
    for spec, row in zip(specs, result['sinks']):
        row['load_mode'] = 'constant_power' if 'power_W' in spec else 'constant_current'
        row['delivered_power_W'] = row['voltage_V']*row['current_A']
        if 'power_W' in spec:
            row['power_W'] = spec['power_W']
            if not math.isclose(row['delivered_power_W'], spec['power_W'], rel_tol=1e-8, abs_tol=1e-12):
                raise ValueError('Constant-power final FEM field disagrees with the reduced operating point; refine the mesh.')
    delivered = math.fsum(row['delivered_power_W'] for row in result['sinks'])
    source_power = source_voltage*result['source_current_A']
    balance = abs(source_power-delivered-result['total_power_W'])/max(abs(source_power), 1e-30)
    if balance > 1e-6:
        raise ValueError('Constant-power source/load/loss energy balance failed.')
    result.update(operating_mode='constant_power_loads', load_power_W=delivered,
                  requested_constant_power_W=float(powers.sum()), source_power_W=source_power,
                  load_current_A=result['total_sink_current_A'], power_balance_relative_error=balance,
                  nonlinear_operating_point={**evidence, 'power_ports': len(indices),
                      'fem_solves': len(indices)+2, 'method': 'fixed-mesh terminal-response reduction and damped Newton',
                      'branch': 'high_voltage_positive_incremental_stiffness',
                      'notice': 'Fixed-temperature DC operating point; converter control, startup, transient stability, '
                                'return-path impedance and source foldback are not modeled.'})
    result['feasibility']['basis'] = 'constant_power_and_current_loads_at_solved_dc_voltage'
    return result
