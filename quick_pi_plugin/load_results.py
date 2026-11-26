"""Shared limit evaluation for DC load copper FEM results."""
import math


def fixed_current_results(sink_specs, voltage_drops, source_voltage, sink_current, source_current_limit):
    sink_results = []
    for spec, drop in zip(sink_specs, voltage_drops):
        sink_drop = float(drop)
        voltage = source_voltage - sink_drop
        maximum = spec['max_voltage_V']
        minimum_tolerance = 1e-12 * max(abs(voltage), abs(spec['min_voltage_V']))
        maximum_tolerance = None if maximum is None else 1e-12 * max(abs(voltage), abs(maximum))
        sink_results.append({key: spec[key] for key in ('id', 'label', 'current_A', 'min_voltage_V', 'max_voltage_V')})
        sink_results[-1].update(voltage_V=voltage, voltage_drop_V=sink_drop,
                                voltage_limit_tolerances_V={'minimum':minimum_tolerance,'maximum':maximum_tolerance},
                                within_voltage_limits=voltage >= spec['min_voltage_V'] - minimum_tolerance and
                                (maximum is None or voltage <= maximum + maximum_tolerance))
    over_limit = source_current_limit is not None and sink_current > source_current_limit and not math.isclose(
        sink_current, source_current_limit, rel_tol=1e-12, abs_tol=0.)
    violations = []
    if over_limit:
        violations.append(f'Required source current {sink_current:.9g} A exceeds its {source_current_limit:.9g} A limit.')
    for row in sink_results:
        if not row['within_voltage_limits']:
            violations.append(f"Sink {row['label']} voltage {row['voltage_V']:.9g} V is outside its specified voltage limits.")
    feasible = not violations
    feasibility = {'status': 'FEASIBLE' if feasible else 'INFEASIBLE', 'feasible': feasible,
        'source_current_limit_A': source_current_limit,
        'source_current_headroom_A': None if source_current_limit is None else
                                    (source_current_limit - sink_current if over_limit else max(0., source_current_limit - sink_current)),
        'source_current_limit_exceeded': over_limit, 'violations': violations,
        'operating_point_valid': feasible, 'basis': 'requested_constant_current_loads_at_source_voltage',
        'notice': 'Feasibility covers the declared DC current budget and sink voltage windows only. '
                  'An infeasible result is a requested-load diagnostic, not an attainable operating point. '
                  'Current-limit foldback, load undervoltage response and return-path losses are not modeled.'}

    return sink_results, feasibility
