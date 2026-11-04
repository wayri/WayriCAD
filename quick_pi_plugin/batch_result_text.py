"""Compact operating-point and series-topology evidence for batch Results."""
from __future__ import annotations

import math


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
        fields=[('source_voltage_V','Source voltage','V'),(current_key,'Load current','A'),
            ('sink_voltage_V','Load voltage','V'),('voltage_drop_V','Path drop','V'),
            ('total_power_W','Total loss','W')]
        lines.extend(_metric(result,*field) for field in fields)
        if len(result.get('sinks') or [])>1:
            for sink in result['sinks']:
                lines.append('Load '+str(sink.get('label') or sink.get('id') or 'Unknown')+' · '+
                    ' · '.join(_metric(sink,*field) for field in
                        [('current_A','Current','A'),('voltage_V','Voltage','V'),('voltage_drop_V','Drop','V')]))
    loop=row.get('loop')
    if isinstance(loop,dict):
        lines.append('Supply and return loop')
        lines.extend(_metric(loop,*field) for field in
            [('delivered_load_voltage_V','Delivered load voltage','V'),
             ('total_drop_V','Total loop drop','V'),('total_loss_W','Total loop loss','W')])
    from .series_power_tree import build_series_power_tree,tree_text
    topology=tree_text(build_series_power_tree(electrical))
    if topology:lines.extend(('',topology))
    return '\n'.join(lines)
