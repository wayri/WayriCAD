"""Compact operating-point and series-topology evidence for batch Results."""
from __future__ import annotations

import math

from .voltage_tolerance import show_exact, voltage_text


def _metric(result,key,label,unit):
    value=result.get(key)
    known=type(value) in (int,float) and math.isfinite(value)
    return label+': '+(f'{value:.6g} {unit}' if known else 'Unavailable')


def case_result_text(row):
    """Keep failures visible and show only metrics supplied by solved evidence."""
    lines=[row['name']+' · '+row['status']]
    if row.get('error'):lines.append(row['error'])
    electrical=row.get('electrical') or {}
    result=electrical.get('result')
    if isinstance(result,dict):
        current_key='total_sink_current_A' if 'total_sink_current_A' in result else 'sink_current_A'
        exact=show_exact(electrical)

        def volts(section,key,label,drop=False):
            return label+': '+voltage_text(result,section.get(key),exact=exact,drop=drop)

        lines.extend((volts(result,'source_voltage_V','Source voltage'),
                      _metric(result,current_key,'Load current','A'),
                      volts(result,'sink_voltage_V','Load voltage'),
                      volts(result,'voltage_drop_V','Path drop',drop=True),
                      _metric(result,'total_power_W','Total loss','W')))
        if len(result.get('sinks') or [])>1:
            for sink in result['sinks']:
                label='Load '+str(sink.get('label') or sink.get('id') or 'Unknown')
                lines.append(' · '.join((label,_metric(sink,'current_A','Current','A'),
                    volts(sink,'voltage_V','Voltage'),volts(sink,'voltage_drop_V','Drop',drop=True))))
        loop=row.get('loop')
        if isinstance(loop,dict):
            lines.extend(('Supply and return loop',
                          volts(loop,'delivered_load_voltage_V','Delivered load voltage'),
                          volts(loop,'total_drop_V','Total loop drop',drop=True),
                          _metric(loop,'total_loss_W','Total loop loss','W')))
        shared=row.get('shared_return',{})
        if shared.get('loads'):
            lines.append('Shared return · '+shared['group'])
            for load in shared['loads']:
                lines.append(' · '.join((load['sink'],volts(load,'ground_rise_V','Ground rise',drop=True),
                    volts(load,'delivered_load_voltage_V','Delivered load voltage'),
                    'Pass' if load['voltage_limits_met'] else 'Infeasible')))
    from .series_power_tree import build_series_power_tree,tree_text
    topology=tree_text(build_series_power_tree(electrical))
    if topology:lines.extend(('',topology))
    return '\n'.join(lines)
