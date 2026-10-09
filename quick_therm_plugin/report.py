"""Self-contained QuickTherm HTML/JSON evidence."""
from __future__ import annotations
import base64
from html import escape
import io
import json
from pathlib import Path


def _number(value,unit='',scale=1.):
    return 'Unknown' if value is None else f'{float(value)*scale:.6g} {unit}'.strip()


def write_diagnostic_report(path,bundle):
    """Export mapped QuickTherm findings without remote assets."""
    thermal=bundle.get('quick_therm')
    if not thermal:raise ValueError('No QuickTherm result is available.')
    path=Path(path).with_suffix('.html');path.parent.mkdir(parents=True,exist_ok=True)
    json_path=path.with_suffix('.json')
    json_path.write_text(json.dumps(bundle,indent=2,allow_nan=False),encoding='utf-8')
    heading='QuickTherm'
    html=('<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD '+heading+'</title>'
          '<style>body{font:15px system-ui,sans-serif;max-width:1500px;margin:32px auto;padding:0 20px;color:#173039}'
          'table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style>'
          '<h1>WayriCAD '+heading+'</h1><p>Read-only saved-board analysis. '
          '<a href="'+escape(json_path.name)+'">Complete JSON evidence</a>.</p>')
    if thermal:
        html+='<p>'+escape(thermal['model'])+' · '+escape(thermal['environment'])+' · ambient '+_number(thermal['ambient_c'],'°C')+'</p>'
        if thermal.get('input_source'):
            html+='<p><strong>Input source:</strong> '+escape(thermal['input_source'])+'</p>'
            if 'manual_values' in thermal:
                html+='<details><summary>Explicit component inputs</summary><pre>'+escape(json.dumps(thermal['manual_values'],indent=2,sort_keys=True))+'</pre></details>'
            if thermal.get('component_input_sources'):
                html+='<details><summary>Scanned values and override provenance</summary><pre>'+escape(json.dumps(thermal['component_input_sources'],indent=2,sort_keys=True))+'</pre></details>'
        else:
            html+='<p><strong>Input source:</strong> saved footprint fields '+escape(json.dumps(thermal.get('field_map',{}),sort_keys=True))+'</p>'
        html+='<p>Coverage: '+str(thermal['coverage']['solved'])+'/'+str(thermal['coverage']['scoped'])+' scoped components solved.</p>'
        view=bundle.get('board_thermal_view',{});analytics=view.get('analytics',{})
        network=bundle.get('thermal_network')
        calculix=bool(network and network.get('model')=='CalculiX 3D steady conduction')
        if view:
            from .thermal_interactive import interactive_board_html
            html += interactive_board_html(view, network, bundle.get("temperature_limits"))
            from wayricad_runtime.interactive_plots import interactive_plot
            components = (network or {}).get('components') or thermal.get('components', [])
            rows = [[index, row.get('junction_c', row.get('junction_temperature_c')),
                     row.get('junction_c', row.get('junction_temperature_c')), row['reference']]
                    for index, row in enumerate(components)
                    if row.get('junction_c', row.get('junction_temperature_c')) is not None]
            if rows:
                html += interactive_plot('Component junction estimates', rows, unit='°C',
                                         x_unit='component index', y_unit='°C')
            if network and network.get('transient'):
                from .thermal_review import transient_frame_network
                time_rows = []
                for index, frame in enumerate(network['transient']['frames']):
                    selected = transient_frame_network(network, index)
                    for row in selected['components']:
                        value = row.get('junction_c')
                        time_rows.append([frame['time_s'], value, value, row['reference']])
                time_rows.sort(key=lambda row: (row[3], row[0]))
                html += interactive_plot('Junction estimates over time', time_rows, unit='°C',
                                         x_unit='s', y_unit='°C', connect=True)
                html += '<p>Time curves use stored frames and explicit package resistance; missing junction inputs remain unknown. Board surface probes are available in the interactive board above.</p>'
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from .thermal_plot import draw_thermal_view, draw_temperature_comparison
            modes=(['Top board model', 'Bottom board model'] if network else ['Top-side map', 'Bottom-side map'])
            modes.extend(['Component temperature comparison', '3D overview', 'Top-side contour', 'Bottom-side contour'])
            if network and network.get('layers'):
                modes.extend('Layer model: '+row['name'] for row in network['layers'])
            for mode in modes:
                figure=Figure(figsize=(10,5),dpi=115);FigureCanvasAgg(figure)
                if mode == 'Component temperature comparison':
                    draw_temperature_comparison(figure, bundle)
                else:
                    draw_thermal_view(figure,view,mode,network=network)
                image=io.BytesIO();figure.savefig(image,format='png',dpi=115)
                html+='<h2>'+escape(mode)+' — printable snapshot</h2><img style="max-width:100%" alt="'+escape(mode)+'" src="data:image/png;base64,'+base64.b64encode(image.getvalue()).decode('ascii')+'">'
            html+='<p>Contour: '+escape(view.get('field',{}).get('meaning','Interpolation of component junction estimates; not a physical board-surface solve.'))+'</p>'
            stats=analytics.get('temperature_c',{})
            summary=' · '.join(escape(label)+' '+_number(stats.get(key),'°C') for label,key in
                               (('Minimum','min'),('Maximum','max'),('Mean','mean'),('Median','median')))
            html+='<h2>Temperature analytics</h2><p>'+summary+' · Hottest '+escape(str(analytics.get('hottest_reference') or '—'))+'</p>'
        if network:
            balance=network['heat_balance']
            html+='<h2>Optional board heat model</h2><p>'+escape(network['model'])+' · '+escape(network['status'])+'</p>'
            if network.get('layers'):
                html+=('<p>Imported CalculiX nodal temperatures from an extruded 3D copper/dielectric mesh. The entire lower face is fixed; other faces are adiabatic. This is not CFD or a measurement.</p>'
                        if calculix else
                        '<p>Saved copper geometry and stackup; user-supplied material and fixture data. This is a layer-resolved steady-state approximation, not validated CFD or a measurement.</p>')
                html+='<table><tr><th>Copper layer</th><th>Depth mm</th><th>Minimum °C</th><th>Maximum °C</th></tr>'
                for layer in network['layers']:
                    html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in (layer['name'],
                        _number(layer['z_mm']),_number(layer['sampled_min_c']),_number(layer['sampled_max_c'])))+'</tr>'
                html+='</table>'
                if calculix:
                    html+=('<p>Input '+_number(balance.get('source_w'),'W')+
                            ' · lower-face outflow '+_number(balance.get('bottom_outflow_w'),'W')+
                            ' · residual '+_number(balance.get('residual_w'),'W')+'</p>')
                else:
                    html+=('<p>Input '+_number(balance.get('input_w'),'W')+' · convection '+_number(balance.get('convection_w'),'W')+
                        ' · radiation '+_number(balance.get('radiation_w'),'W')+' · fixture flux '+_number(balance.get('mount_flux_w'),'W')+
                        ' · residual '+_number(balance.get('residual_w'),'W')+'</p>')
                if network.get('mounts'):
                    html+='<h3>Fixed-temperature contacts</h3><table><tr><th>Pad ID</th><th>Setpoint °C</th><th>Heat flow to fixture W</th></tr>'
                    for mount in network['mounts']:
                        html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in (
                            mount['id'],_number(mount['temperature_c']),_number(mount['heat_flux_w'])))+'</tr>'
                    html+='</table><p>Positive fixture heat flow leaves the board; negative flow enters it.</p>'
            else:
                field=network['board_field']
                html+='<p>The top and bottom board views show one shared thin-sheet midplane field, not separate surface solves.</p>'
                html+=('<p>Board cell range '+_number(field.get('sampled_min_c'),'°C')+' to '+_number(field.get('sampled_max_c'),'°C')+
                    ' · mesh '+str(field.get('grid_cells_long_axis','—'))+' long-axis / '+str(field.get('active_cells','—'))+' active cells'+
                    ' · input '+_number(balance.get('input_w'),'W')+' · board convection '+_number(balance.get('board_convection_w'),'W')+
                    ' · board radiation '+_number(balance.get('board_radiation_w'),'W')+' · sink convection '+_number(balance.get('sink_convection_w'),'W')+
                    ' · sink radiation '+_number(balance.get('sink_radiation_w'),'W')+' · residual '+_number(balance.get('residual_w'),'W')+'</p>')
            html+='<h3>Model inputs and assumptions</h3><pre>'+escape(json.dumps(network['settings'],indent=2))+'</pre><ul>'+''.join(
                '<li>'+escape(item)+'</li>' for item in network.get('assumptions',[]))+'</ul>'
        html+='<h2>Component results</h2><table><tr><th>Reference</th><th>Side</th><th>Heat path</th><th>Power W</th><th>Rθ K/W</th><th>Junction °C</th><th>Rise K</th><th>X mm</th><th>Y mm</th><th>Status</th></tr>'
        solved={row['reference']:row for row in thermal['components']}
        parts=[(item,solved.get(item['reference'])) for item in view.get('components',[]) if item.get('in_scope')] if view else [(None,row) for row in thermal['components']]
        for item,row in parts:
            if row is None:
                xy=item.get('position_mm') or [None,None]
                values=(item['reference'],item.get('side','—'),'—','—','—','—','—',_number(xy[0]),_number(xy[1]),'; '.join(item.get('issues',[])) or 'Excluded')
                html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in values)+'</tr>'
                continue
            sink=row.get('heatsink')
            heat_path=(sink['shape'].replace('_',' ') +
                       (' · '+ ' × '.join(_number(sink[key], 'mm') for key in ('width_mm','depth_mm','height_mm'))
                        if sink.get('width_mm') is not None else ' · no envelope')) if sink else (
                        'CalculiX board field' if calculix else
                        'Air RθJA' if thermal['environment']=='air' else 'Shared board')
            xy=item.get('position_mm') or [None,None] if item else [None,None]
            html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in (
                row['reference'],item.get('side','—') if item else '—',heat_path,_number(row['power_w']),
                _number(row['resistance_k_per_w']),_number(row['junction_c']),_number(row.get('rise_above_ambient_k')),
                _number(xy[0]),_number(xy[1]),
                'Solved' if row.get('junction_c') is not None else 'Board solved; Tj unknown'))+'</tr>'
        html+='</table>'
        limits=bundle.get('temperature_limits',{})
        if limits:
            html+=('<h2>Mapped junction-temperature limits</h2><p>Overall '+escape(limits['status'])+
                   ' · PASS '+str(limits['counts']['PASS'])+' · FAIL '+str(limits['counts']['FAIL'])+
                   ' · UNKNOWN '+str(limits['counts']['UNKNOWN'])+'</p>')
            html+='<p>Field mapping: '+escape(json.dumps(limits.get('field_map',{}),sort_keys=True))+'</p>'
            html+='<table><tr><th>Reference</th><th>Estimated Tj °C</th><th>Minimum °C</th><th>Maximum °C</th><th>Result</th><th>Reason</th></tr>'
            for row in limits['rows']:
                values=(row['reference'],_number(row.get('junction_c')),_number(row.get('minimum_c')),
                        _number(row.get('maximum_c')),row['status'],'; '.join(row['issues']))
                html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in values)+'</tr>'
            html+='</table>'
        probes=bundle.get('probes',[])
        if probes:
            html+='<h2>Virtual temperature probes</h2><p>Nearest valid field cell; no extrapolation. Component interpolation is not a board-surface result.</p>'
            html+='<table><tr><th>Probe</th><th>Side</th><th>X mm</th><th>Y mm</th><th>Temperature °C</th><th>Source</th><th>Status / reason</th></tr>'
            for probe in probes:
                values=(probe['label'],probe['side'],_number(probe['x_mm']),_number(probe['y_mm']),
                        _number(probe.get('temperature_c')),probe.get('source') or '—',
                        probe['status']+(' · '+probe['reason'] if probe.get('reason') else ''))
                html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in values)+'</tr>'
            html+='</table>'
        if network:
            html+='<h3>Board-network component sites</h3><table><tr><th>Reference</th><th>Side</th><th>Source path</th><th>Mean source cell °C</th><th>Hottest source cell °C</th><th>Virtual sink °C</th><th>Mean-contact junction estimate °C</th><th>Hot-cell junction proxy °C</th><th>Area-equivalent source cells</th></tr>'
            for row in network.get('components',[]):
                html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in (
                    row['reference'],row.get('side','—'),row.get('source_heat_path',row.get('heat_path',row.get('source_distribution','board'))),
                    _number(row.get('board_site_c'),'°C'),_number(row.get('source_peak_c'),'°C'),
                    _number(row.get('sink_c'),'°C'),_number(row.get('junction_c'),'°C'),
                    _number(row.get('junction_peak_proxy_c'),'°C'),
                    _number(row.get('effective_source_cells'))))+'</tr>'
            html+='</table><p>The model junction estimate uses board-site temperature plus an explicitly supplied RθJB; it is not a resolved die maximum. Legacy RθJA is not substituted.</p>'
            if network.get('layers'):
                html+='<h3>Layer temperature peaks</h3><table><tr><th>Layer</th><th>Sampled minimum °C</th><th>Sampled maximum °C</th></tr>'
                for layer in network['layers']:
                    html+='<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in (
                        layer['name'],_number(layer['sampled_min_c']),
                        _number(layer['sampled_max_c'])))+'</tr>'
                html+=('</table><p>These are interpolated CalculiX board-surface temperatures; smaller copper features may be missed by triangle-centroid material classification.</p>'
                        if calculix else
                        '</table><p>These are finite-volume cell temperatures. A peak cell may span a drilled void or subcell copper feature; inspect source geometry and mesh acceptance before interpreting it physically.</p>')
            acceptance=network.get('mesh_acceptance')
            if acceptance:
                html+='<h3>Mesh acceptance: '+escape(acceptance['status'])+'</h3><p>Largest component change '+escape(_number(acceptance['maximum_change_c'],'°C'))+', layer-peak change '+escape(_number(acceptance['maximum_layer_peak_change_c'],'°C'))+', source-peak change '+escape(_number(acceptance['maximum_source_peak_change_c'],'°C'))+', spatial-field change '+escape(_number(acceptance['maximum_field_change_c'],'°C'))+'. Phase check: '+escape(acceptance['phase_sensitivity']['status'])+'.</p>'
                if acceptance['underresolved_sources']:
                    html+='<p>Underresolved sources: '+escape(', '.join(acceptance['underresolved_sources']))+'</p>'
        if thermal['coverage']['excluded']:
            html+='<h2>Incomplete field mapping</h2><ul>'+''.join('<li>'+escape(row['reference']+': '+', '.join(row['issues']))+'</li>'
                for row in thermal['coverage']['excluded'])+'</ul>'
        html+='<h2>Assumptions</h2><ul>'+''.join('<li>'+escape(note)+'</li>' for note in thermal['assumptions'])+'</ul>'
    path.write_text(html+'</html>',encoding='utf-8')
    return {'html':str(path),'json':str(json_path)}

write_report = write_diagnostic_report
