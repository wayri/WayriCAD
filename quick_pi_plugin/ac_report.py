"""Offline AC cross-section plots, selection tables and paired evidence."""
from __future__ import annotations

import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import shutil
import tempfile


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value):
    if value is None: return 'Unknown'
    return format(value, '.7g') if _number(value) else str(value)


def summary(bundle):
    """Return scalar results and the solver's declared applicability checks."""
    result = bundle['ac']
    return json.dumps({key: value for key, value in result.items()
                       if key not in ('cells', 'harmonics', 'conductors')},
                      indent=2, allow_nan=False)


def draw(figure, bundle):
    """Draw cross-section geometry, frequency impedance and harmonic copper loss."""
    from matplotlib.patches import Rectangle
    figure.clear()
    geometry, impedance, losses = [figure.add_subplot(1, 3, index) for index in (1, 2, 3)]
    cells = bundle['ac'].get('cells', [])
    if cells:
        from matplotlib.collections import PolyCollection
        vertices = [[(cell['x_mm']-cell['width_mm']/2,cell['y_mm']-cell['height_mm']/2),
                     (cell['x_mm']+cell['width_mm']/2,cell['y_mm']-cell['height_mm']/2),
                     (cell['x_mm']+cell['width_mm']/2,cell['y_mm']+cell['height_mm']/2),
                     (cell['x_mm']-cell['width_mm']/2,cell['y_mm']+cell['height_mm']/2)] for cell in cells]
        field = PolyCollection(vertices, cmap='viridis', edgecolors='none')
        values = [cell['current_density_rms_a_mm2'] for cell in cells]
        field.set_array(values);field.set_clim(0,max(values) or 1.);geometry.add_collection(field)
        bar = geometry.inset_axes([0,-.62,1,.05])
        figure.colorbar(field,cax=bar,orientation='horizontal',label='Total RMS J (A/mm²)')
    for row in bundle['study']['conductors']:
        geometry.add_patch(Rectangle((row['x_mm'] - row['width_mm']/2,
                                      row['y_mm'] - row['thickness_mm']/2),
                                     row['width_mm'], row['thickness_mm'],
                                     facecolor='none' if cells else '#df9d35' if row['current_scale'] > 0 else '#5fa8c9',
                                     edgecolor='#20323b', label=row['name']))
        geometry.annotate(row['name'], (row['x_mm'], row['y_mm']), xytext=(0, 8),
                          textcoords='offset points', ha='center', fontsize=8)
    geometry.autoscale_view(); geometry.margins(.2); geometry.set_aspect('equal')
    geometry.set_xlabel('Cross-section x (mm)'); geometry.set_ylabel('Cross-section y (mm)')
    geometry.set_title('Copper cross-section')
    rows = bundle['ac'].get('harmonics', [])
    for key, label in (('resistance_ohm', 'Resistance'), ('reactance_ohm', 'Reactance')):
        values = [(row.get('frequency_hz'), row.get(key)) for row in rows
                  if _number(row.get('frequency_hz')) and _number(row.get(key))]
        if values:
            impedance.semilogx([v[0] for v in values], [v[1] for v in values], 'o-', label=label)
    if impedance.lines: impedance.legend(fontsize=8)
    impedance.set_xlabel('Frequency (Hz)'); impedance.set_ylabel('Loop impedance (Ω)')
    impedance.set_title('Loop impedance'); impedance.grid(alpha=.2)
    values = [(row.get('frequency_hz'), row.get('loss_w')) for row in rows
              if _number(row.get('frequency_hz')) and _number(row.get('loss_w'))]
    if values:
        losses.semilogx([v[0] for v in values], [v[1] for v in values], 'o-', color='#d87822')
    losses.set_xlabel('Frequency (Hz)'); losses.set_ylabel('Harmonic copper loss (W)')
    losses.set_title('Harmonic Joule loss'); losses.grid(alpha=.2)
    figure.tight_layout()


def _table(identifier, rows, columns, selection=None):
    headings = ''.join('<th tabindex="0">' + escape(label) + '</th>' for _, label in columns)
    body = []
    for index, row in enumerate(rows):
        attrs = ' data-index="' + str(index) + '"'
        if selection: attrs += ' data-conductor="' + escape(str(row.get(selection, '')), quote=True) + '"'
        body.append('<tr tabindex="0"' + attrs + '>' + ''.join(
            '<td>' + escape(_text(row.get(key))) + '</td>' for key, _ in columns) + '</tr>')
    return '<div class="scroll"><table id="' + identifier + '"><thead><tr>' + headings + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>'


def _geometry(study, cells=()):
    rows = study['conductors']
    left = min(row['x_mm'] - row['width_mm']/2 for row in rows)
    right = max(row['x_mm'] + row['width_mm']/2 for row in rows)
    bottom = min(row['y_mm'] - row['thickness_mm']/2 for row in rows)
    top = max(row['y_mm'] + row['thickness_mm']/2 for row in rows)
    span = max(right-left, top-bottom, 1e-9)
    scale = 700 / span
    # Physical aspect ratio is retained. Selection outlines do not enlarge copper.
    shapes = []
    maximum = max((cell['current_density_rms_a_mm2'] for cell in cells),default=0) or 1.
    for row in rows:
        x = 40 + (row['x_mm']-row['width_mm']/2-left)*scale
        y = 40 + (top-row['y_mm']-row['thickness_mm']/2)*scale
        name = escape(str(row['name']), quote=True)
        copper = []
        for cell in cells:
            if cell['conductor'] != row['name']: continue
            cx = 40+(cell['x_mm']-cell['width_mm']/2-left)*scale
            cy = 40+(top-cell['y_mm']-cell['height_mm']/2)*scale
            density = cell['current_density_rms_a_mm2']; fraction = max(0.,min(1.,density/maximum))
            detail = escape('Total RMS J: '+_text(density)+' A/mm²; Joule loss density: '+_text(cell['loss_density_w_mm3'])+' W/mm³')
            copper.append(f'<rect class="cell" x="{cx}" y="{cy}" width="{cell["width_mm"]*scale}" height="{cell["height_mm"]*scale}" fill="hsl({240*(1-fraction)},80%,48%)"><title>{detail}</title></rect>')
        shapes.append('<g data-conductor="'+name+'" tabindex="0"><rect class="outline" x="'+str(x)+'" y="'+str(y)+'" width="'+str(row['width_mm']*scale)+'" height="'+str(row['thickness_mm']*scale)+'" fill="'+('none' if cells else '#df9d35' if row['current_scale'] > 0 else '#5fa8c9')+'"><title>'+name+' · '+escape(_text(row['current_scale']))+' × loop current; click to select</title></rect>'+''.join(copper)+'<text x="'+str(x+row['width_mm']*scale/2)+'" y="'+str(y-9)+'" text-anchor="middle">'+name+'</text></g>')
    legend = '<p>Cell colours: total RMS current density, blue = 0, red = '+_text(maximum)+' A/mm². Hover a cell for Joule loss density.</p>' if cells else ''
    return '<svg id="cross-section" viewBox="0 0 780 '+str(80+(top-bottom)*scale)+'" role="img" aria-label="Explicit conductor cross-section; click to cross-select table">'+''.join(shapes)+'</svg>'+legend


def _chart(rows, keys, labels, title):
    points = [(index, row) for index, row in enumerate(rows)
              if _number(row.get('frequency_hz')) and row['frequency_hz'] > 0]
    if not points: return '<p>No harmonic data.</p>'
    low = min(math.log10(row['frequency_hz']) for _, row in points)
    high = max(math.log10(row['frequency_hz']) for _, row in points)
    values = [row[key] for _, row in points for key in keys if _number(row.get(key))]
    limit = max(values, default=0) or 1
    colors = ('#087e8b', '#b7591c')
    shapes = []
    for series, (key, label) in enumerate(zip(keys, labels)):
        positions = []
        for index, row in points:
            if not _number(row.get(key)): continue
            x = 50 + 640*(math.log10(row['frequency_hz'])-low)/(high-low or 1)
            y = 230 - 190*row[key]/limit
            positions.append(f'{x},{y}')
            detail = escape(f"{row['frequency_hz']:.7g} Hz · {label}: {_text(row[key])}")
            shapes.append(f'<circle data-harmonic="{index}" tabindex="0" cx="{x}" cy="{y}" r="5" fill="{colors[series]}"><title>{detail}; click to pin</title></circle>')
        shapes.append('<polyline points="'+' '.join(positions)+'" fill="none" stroke="'+colors[series]+'" pointer-events="none"/>')
    return '<svg class="chart" viewBox="0 0 740 270" role="img" aria-label="'+escape(title, quote=True)+'"><text x="50" y="20">'+escape(title)+' · hover / click to pin</text><path d="M50 35 V230 H710" fill="none" stroke="#647580"/>'+''.join(shapes)+'<text x="50" y="255">'+_text(10**low)+' Hz</text><text x="605" y="255">'+_text(10**high)+' Hz</text></svg>'


def _check_sources(bundle):
    for key, digest in (('board_path', 'source_sha256'), ('study_input_path', 'study_file_sha256')):
        if bundle.get(key) and bundle.get(digest):
            if hashlib.sha256(Path(bundle[key]).read_bytes()).hexdigest() != bundle[digest]:
                raise ValueError('PCB or AC study changed. Rerun before exporting.')
    digest = hashlib.sha256(json.dumps(bundle['study'], sort_keys=True, separators=(',', ':'),
                                      allow_nan=False).encode('utf-8')).hexdigest()
    if digest != bundle.get('study_sha256'):
        raise ValueError('AC study settings changed. Rerun before exporting.')


def write_report(path, bundle):
    """Publish paired HTML/JSON atomically, preserving prior reports on failure."""
    from .ac_cli import protect_outputs
    path = Path(path).resolve().with_suffix('.html'); data_path = path.with_suffix('.json')
    protect_outputs((path, data_path), [bundle[key] for key in ('board_path', 'study_input_path') if bundle.get(key)])
    _check_sources(bundle)
    result = bundle['ac']; harmonics = result.get('harmonics', [])
    conductor_rows = result.get('conductors') or bundle['study']['conductors']
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Quick PI AC study</title><style>
body{font:15px system-ui;max-width:1150px;margin:25px auto;padding:0 18px;color:#20323b}table{border-collapse:collapse;width:100%}th,td{padding:9px;border:1px solid #c6d1d7;text-align:left;white-space:nowrap}th{cursor:pointer;background:#edf3f5}tr.selected{background:#ffe0a4}.scroll{overflow:auto;max-height:430px}svg{width:100%;max-height:440px;background:#f5f8fa}svg g{cursor:pointer}svg g.selected .outline{stroke:#dc5015;stroke-width:3}svg text{font:13px system-ui}.chart circle{cursor:crosshair}pre{white-space:pre-wrap;overflow-wrap:anywhere}#probe{position:sticky;bottom:0;background:#fff7df;padding:12px;border:1px solid #d3b35c;min-height:20px}button{padding:7px;margin:5px}
</style><h1>Quick PI · AC copper study</h1><p>Explicit straight-conductor / return cross-section. Includes DC and harmonic Joule loss. The saved PCB, when supplied, provides provenance only. No complete SMPS, dielectric breakdown, creepage, clearance or switching-device model is inferred.</p>'''
    status = result.get('status','Unknown');converged = status == 'CONVERGED'
    html += '<p role="status" style="padding:12px;border:2px solid '+('#268254' if converged else '#bd3a2d')+'"><strong>'+escape(status)+'</strong> · '
    html += ('Global loop-impedance mesh and air-boundary checks passed. Local cell maxima are not independently qualified.' if converged else 'Provisional result: global loop-impedance mesh or boundary checks did not pass. Review the checks before using these estimates.')+'</p>'
    band = result.get('waveform_band',{})
    html += '<p><strong>Finite harmonic band:</strong> '+escape(str(band.get('notice','Only the supplied harmonics are included; omitted frequency content and switching edges are unknown.')))
    if band.get('omitted_rms_a') is not None:html += ' Omitted AC RMS current: '+escape(_text(band['omitted_rms_a']))+' A.'
    html += '</p>'
    html += '<p><a href="'+escape(data_path.name, quote=True)+'">Raw results, inputs and provenance (JSON)</a></p>'
    html += '<p><strong>Total copper Joule loss:</strong> '+escape(_text(result.get('total_loss_w')))+' W · '
    html += '<strong>Copper-loop AC drop RMS:</strong> '+escape(_text(result.get('ripple_voltage_rms_v')))+' V · '
    html += '<strong>Reference waveform RMS:</strong> '+escape(_text(result.get('total_current_rms_a')))+' A.</p>'
    html += '<p>AC drop is across the modeled copper loop; it is not delivered rail ripple after filtering or regulation. Individual conductor currents follow their signed multipliers.</p>'
    html += '<h2>Conductor cross-selection</h2>'+_geometry(bundle['study'],result.get('cells',[]))
    html += _table('conductors', conductor_rows, [('name','Conductor'),('dc_loss_w','DC loss (W)'),('ac_loss_w','AC loss (W)'),('total_loss_w','Total loss (W)')], 'name')
    html += '<h2>Impedance and harmonic losses</h2>'+_chart(harmonics, ('resistance_ohm','reactance_ohm'), ('R (Ω)','X (Ω)'), 'Loop impedance (Ω)')
    html += _chart(harmonics, ('loss_w',), ('Loss (W)',), 'Harmonic copper loss (W)')
    html += _table('harmonics', harmonics, [('frequency_hz','Frequency (Hz)'),('current_rms_a','Current RMS (A)'),('resistance_ohm','Resistance (Ω)'),('reactance_ohm','Reactance (Ω)'),('loss_w','Loss (W)'),('skin_depth_mm','Skin depth (mm)')])
    html += '<p id="probe" aria-live="polite">Hover a point for values. Click a point or row to pin it.</p><button id="clear">Clear probe / selection</button>'
    html += '<h2>Solver checks and applicability</h2><pre>'+escape(summary(bundle))+'</pre><h2>Explicit inputs</h2><pre>'+escape(json.dumps(bundle['study'],indent=2,allow_nan=False))+'</pre>'
    html += '''<script>
const probe=document.getElementById('probe');
function pickConductor(name){document.querySelectorAll('[data-conductor]').forEach(e=>e.classList.toggle('selected',e.dataset.conductor===name));probe.textContent='Selected conductor: '+name;}
document.querySelectorAll('[data-conductor]').forEach(e=>{e.addEventListener('click',()=>pickConductor(e.dataset.conductor));e.addEventListener('keydown',k=>{if(k.key==='Enter')pickConductor(e.dataset.conductor)});});
function pickHarmonic(index){const row=document.querySelector('#harmonics tr[data-index="'+index+'"]');if(!row)return;document.querySelectorAll('#harmonics tbody tr').forEach(e=>e.classList.toggle('selected',e===row));probe.textContent=Array.from(row.cells).map((c,i)=>document.querySelectorAll('#harmonics th')[i].textContent+': '+c.textContent).join(' · ');}
document.querySelectorAll('[data-harmonic]').forEach(e=>{e.addEventListener('click',()=>pickHarmonic(e.dataset.harmonic));e.addEventListener('keydown',k=>{if(k.key==='Enter')pickHarmonic(e.dataset.harmonic)});});
document.querySelectorAll('#harmonics tbody tr').forEach(e=>e.addEventListener('click',()=>pickHarmonic(e.dataset.index)));
document.querySelectorAll('th').forEach((th,index)=>{th.onclick=()=>{const table=th.closest('table'),column=Array.from(th.parentNode.children).indexOf(th),body=table.tBodies[0];const dir=th.dataset.order==='up'?-1:1;th.dataset.order=dir===1?'up':'down';Array.from(body.rows).sort((a,b)=>{const x=a.cells[column].textContent,y=b.cells[column].textContent;if(x==='Unknown')return y==='Unknown'?0:1;if(y==='Unknown')return -1;const nx=Number(x),ny=Number(y);return dir*(Number.isFinite(nx)&&Number.isFinite(ny)?nx-ny:x.localeCompare(y));}).forEach(row=>body.appendChild(row));};th.onkeydown=e=>{if(e.key==='Enter')th.click();};});
document.getElementById('clear').onclick=()=>{document.querySelectorAll('.selected').forEach(e=>e.classList.remove('selected'));probe.textContent='Probe cleared.';};
</script></html>'''
    payload = json.dumps(bundle, indent=2, allow_nan=False)+'\n'
    _check_sources(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = []; backups = {}; published = []; retained = set()
    try:
        for target, text in ((data_path, payload), (path, html)):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as handle:
                handle.write(text); staged.append((Path(handle.name), target))
        for _, target in staged:
            backup = None
            if target.exists():
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                    backup = Path(handle.name); backups[target] = backup
                    with target.open('rb') as original: shutil.copyfileobj(original, handle)
            backups[target] = backup
        _check_sources(bundle)
        try:
            for temporary, target in staged:
                os.replace(temporary, target); published.append(target)
        except BaseException as failure:
            errors = []
            for target in reversed(published):
                try:
                    if backups[target] is None: target.unlink(missing_ok=True)
                    else: os.replace(backups[target], target)
                except OSError as rollback:
                    if backups[target] is not None: retained.add(backups[target])
                    errors.append(str(target)+': '+str(rollback))
            if errors:
                raise OSError('AC report publication and rollback failed. Recovery files: '+', '.join(str(p) for p in retained)+'. '+'; '.join(errors)) from failure
            raise
    finally:
        for temporary, _ in staged: temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None and backup not in retained: backup.unlink(missing_ok=True)
    return {'html': str(path), 'json': str(data_path)}
