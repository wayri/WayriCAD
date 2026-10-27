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


def engineering(value, unit):
    """Format an engineering quantity for display; retain the underlying SI data."""
    if not _number(value):return 'Unknown'
    scale, shown = _display_unit([value],unit)
    return f'{value*scale:.4g} {shown}'


def _display_unit(values, unit):
    maximum=max((abs(value) for value in values if _number(value)),default=0.)
    if unit=='Hz':
        if maximum>=1e9:return 1e-9,'GHz'
        if maximum>=1e6:return 1e-6,'MHz'
        if maximum>=1e3:return 1e-3,'kHz'
    elif unit in ('Ω','W','V','A') and 0<maximum<1:
        if maximum<1e-3:return 1e6,'µ'+unit
        return 1e3,'m'+unit
    return 1.,unit


def check_rows(bundle):
    """Readable scalar checks; nested evidence remains in the paired JSON."""
    rows=[]
    def visit(value,path):
        if isinstance(value,dict):
            for key,item in value.items():visit(item,path+[str(key).replace('_',' ')])
        elif not isinstance(value,(list,tuple)):
            rows.append((' / '.join(path), 'Unknown' if value is None else 'Yes' if value is True else 'No' if value is False else _text(value)))
    result=bundle['ac']
    for key in ('checks','convergence','mesh_convergence','boundary_convergence','waveform_band'):
        if key in result:visit(result[key],[key.replace('_',' ')])
    return rows


def summary(bundle):
    """Readable results and solver checks, with full evidence kept in JSON."""
    result=bundle['ac']
    lines=['AC copper study: '+str(result.get('status','Unknown')),
           'Total copper heating: '+engineering(result.get('total_loss_w'),'W'),
           'DC copper heating: '+engineering(result.get('dc_loss_w'),'W'),
           'AC ripple copper heating: '+engineering(result.get('ac_loss_w'),'W'),
           'Copper-loop AC drop RMS: '+engineering(result.get('ripple_voltage_rms_v'),'V'),
           'Reference waveform RMS: '+engineering(result.get('total_current_rms_a'),'A'),'',
           'Solver checks']
    lines.extend(label+': '+value for label,value in check_rows(bundle))
    if not check_rows(bundle):lines.append('No scalar solver checks supplied.')
    lines+=['','Model limits',*map(str,result.get('limitations',[]))]
    return '\n'.join(lines)


def draw(figure, bundle, view='overview'):
    """Show physical copper, then supplied-frequency impedance and Joule loss.

    Frequency coordinates stay in Hz for native picking. Engineering units only
    change tick labels; impedance/loss ordinates use their displayed unit scale.
    One supplied frequency is a discrete result, never drawn as a frequency sweep.
    """
    if view not in ('overview','geometry','impedance','losses'):raise ValueError('Unknown AC result chart view.')
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    figure.clear()
    grid=figure.add_gridspec(2,2,width_ratios=(1.15,1.),hspace=1.25 if figure.get_figheight()<4.2 else .7,wspace=.36)
    geometry=figure.add_subplot(grid[:,0]);impedance=figure.add_subplot(grid[0,1]);losses=figure.add_subplot(grid[1,1])
    field=None
    # A frequency-chart switch must not rebuild a potentially large spatial field.
    cells=bundle['ac'].get('cells',[]) if view in ('overview','geometry') else []
    values=[cell.get('current_density_rms_a_mm2') for cell in cells]
    finite=[value for value in values if _number(value)]
    varied=bool(finite) and max(finite)-min(finite)>1e-6*max(1.,max(map(abs,finite)))
    if finite:
        from matplotlib.collections import PolyCollection
        vertices=[[(cell['x_mm']-cell['width_mm']/2,cell['y_mm']-cell['height_mm']/2),
                   (cell['x_mm']+cell['width_mm']/2,cell['y_mm']-cell['height_mm']/2),
                   (cell['x_mm']+cell['width_mm']/2,cell['y_mm']+cell['height_mm']/2),
                   (cell['x_mm']-cell['width_mm']/2,cell['y_mm']+cell['height_mm']/2)] for cell,value in zip(cells,values) if _number(value)]
        if varied:
            field=PolyCollection(vertices,cmap='viridis',edgecolors='none');field.set_array(finite)
            field.set_clim(min(finite),max(finite));geometry.add_collection(field)
        else:
            geometry.add_collection(PolyCollection(vertices,facecolors='#d9a441',edgecolors='none'))
            geometry.text(.5,.03,'Uniform RMS current density: '+f'{finite[0]:.4g} A/mm²',ha='center',transform=geometry.transAxes,fontsize=9)
    if not finite:
        geometry.text(.5,.03,'Conductor geometry; no solved current-density field supplied.',ha='center',transform=geometry.transAxes,fontsize=8)
    for row in bundle['study']['conductors']:
        role='Outgoing' if row['current_scale']>0 else 'Return' if row['current_scale']<0 else 'Unpowered shield'
        geometry.add_patch(Rectangle((row['x_mm']-row['width_mm']/2,row['y_mm']-row['thickness_mm']/2),row['width_mm'],row['thickness_mm'],
            facecolor='none' if finite else '#d9a441' if row['current_scale']>0 else '#78b4cd',edgecolor='#20323b',label=row['name']))
        caption=row['name']+'\n'+role+' · '+f"{row['width_mm']:.4g} × {row['thickness_mm']:.4g} mm"
        if view=='geometry':
            geometry.annotate(caption,(row['x_mm']+row['width_mm']/2,row['y_mm']),xytext=(12,0),textcoords='offset points',ha='left',va='center',fontsize=9)
        else:geometry.annotate(caption,(row['x_mm'],row['y_mm']),xytext=(0,12),textcoords='offset points',ha='center',fontsize=9)
    geometry.autoscale_view();geometry.margins(x=.15,y=.45);geometry.set_aspect('equal')
    geometry.set_xlabel('Horizontal position (mm)');geometry.set_ylabel('Stack height (mm)');geometry.set_title('1 · Copper and return path',loc='left',fontsize=11,fontweight='bold')
    geometry.spines[['top','right']].set_visible(False)
    rows=bundle['ac'].get('harmonics',[])
    frequencies=[row['frequency_hz'] for row in rows if _number(row.get('frequency_hz')) and row['frequency_hz']>0]
    frequency_scale,frequency_unit=_display_unit(frequencies,'Hz')
    rscale,runit=_display_unit([row.get(key) for row in rows for key in ('resistance_ohm','reactance_ohm')],'Ω')
    pscale,punit=_display_unit([row.get('loss_w') for row in rows],'W')
    single=len(set(frequencies))==1
    for key,label,color,offset in [('resistance_ohm','R · resistive','#156b76',-.12),('reactance_ohm','X · reactive','#b36a20',.12)]:
        points=[(row['frequency_hz'],row[key]) for row in rows if _number(row.get('frequency_hz')) and row['frequency_hz']>0 and _number(row.get(key))]
        if not points:continue
        if single:
            frequency,value=points[0];impedance.bar(frequency*(1+offset),value*rscale,width=frequency*.19,label=label,color=color)
            impedance.annotate(f'{value*rscale:.4g} {runit}',(frequency*(1+offset),value*rscale),xytext=(0,5),textcoords='offset points',ha='center',fontsize=9)
        else:impedance.plot([x for x,_ in points],[y*rscale for _,y in points],'o-',label=label,color=color,markersize=5)
    if impedance.patches or impedance.lines:impedance.legend(fontsize=8,frameon=False)
    points=[(row['frequency_hz'],row['loss_w']) for row in rows if _number(row.get('frequency_hz')) and row['frequency_hz']>0 and _number(row.get('loss_w'))]
    if points:
        if single:
            frequency,value=points[0];losses.bar(frequency,value*pscale,width=frequency*.38,color='#d87822')
            losses.annotate(f'{value*pscale:.4g} {punit}',(frequency,value*pscale),xytext=(0,5),textcoords='offset points',ha='center',fontsize=10,fontweight='bold')
        else:
            spacing=min((b-a for a,b in zip(sorted(set(frequencies)),sorted(set(frequencies))[1:])),default=max(frequencies))
            widths=[frequency*.15 if max(frequencies)/min(frequencies)>=10 else spacing*.45 for frequency,_ in points]
            losses.bar([x for x,_ in points],[y*pscale for _,y in points],width=widths,color='#d87822')
    for axis,ylabel,title in [(impedance,'Loop impedance ('+runit+')','2 · Resistance and reactance'),(losses,'Copper heating ('+punit+')','3 · Heating from each harmonic')]:
        axis.set_title(title,loc='left',fontsize=11,fontweight='bold');axis.set_ylabel(ylabel);axis.set_xlabel('Supplied frequency ('+frequency_unit+')')
        axis.xaxis.set_major_formatter(FuncFormatter(lambda value,_:f'{value*frequency_scale:g}'))
        if single:
            axis.set_xlim(frequencies[0]*.5,frequencies[0]*1.5);axis.set_xticks([frequencies[0]])
        elif frequencies and max(frequencies)/min(frequencies)>=10:axis.set_xscale('log');axis.xaxis.set_major_formatter(FuncFormatter(lambda value,_:f'{value*frequency_scale:g}'))
        else:axis.xaxis.set_major_locator(MaxNLocator(nbins=5))
        if points or axis.patches or axis.lines:axis.margins(y=.25)
        if axis.get_ylim()[0]>0:axis.set_ylim(bottom=0)
        axis.spines[['top','right']].set_visible(False);axis.grid(axis='y',alpha=.18);axis.set_axisbelow(True)
    for axis,keys in ((impedance,('resistance_ohm','reactance_ohm')),(losses,('loss_w',))):
        if not any(_number(row.get(key)) for row in rows for key in keys):axis.text(.5,.5,'No supplied harmonic result',transform=axis.transAxes,ha='center')
    figure.subplots_adjust(left=.075,right=.975,top=.91,bottom=.17)
    axes={'geometry':geometry,'impedance':impedance,'losses':losses}
    if view=='overview':
        # Reserve a real band below geometry for its xlabel and colour scale,
        # even in a short desktop canvas. Right-hand plots keep their own space.
        geometry.set_position([.075,.34,.4,.56])
    else:
        for name,axis in axes.items():axis.set_visible(name==view)
        axes[view].set_position([.10,.44 if view=='geometry' else .20,.85,.43 if view=='geometry' else .66])
    if field is not None:
        # Insets remain children of the geometry axis, so native selection keeps
        # geometry/impedance/losses as the first three axes in stable order.
        geometry.apply_aspect()
        height_inches=max(geometry.get_position().height*figure.get_figheight(),.01)
        # Reserve physical text space rather than a fraction of a shallow axis.
        bar=geometry.inset_axes([0.,-.58/height_inches,1.,.07/height_inches])
        bar.set_visible(view in ('overview','geometry'))
        figure.colorbar(field,cax=bar,orientation='horizontal',label='RMS current density (A/mm²) · solved range')
        bar.tick_params(labelsize=8)
        bar.xaxis.label.set_size(9)



def _table(identifier, rows, columns, selection=None):
    """Render numeric presentation columns; optional factors do not alter evidence."""
    headings=''.join('<th tabindex="0">'+escape(column[1])+'</th>' for column in columns)
    body=[]
    for index,row in enumerate(rows):
        attrs=' data-index="'+str(index)+'"'
        if selection:attrs+=' data-conductor="'+escape(str(row.get(selection,'')),quote=True)+'"'
        cells=[]
        for column in columns:
            value=row.get(column[0]);factor=column[2] if len(column)>2 else 1.
            if _number(value):value*=factor
            cells.append('<td>'+escape(_text(value))+'</td>')
        body.append('<tr tabindex="0"'+attrs+'>'+''.join(cells)+'</tr>')
    return '<div class="scroll"><table id="'+identifier+'"><thead><tr>'+headings+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


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
    densities=[cell['current_density_rms_a_mm2'] for cell in cells if _number(cell.get('current_density_rms_a_mm2'))]
    maximum=max(densities,default=0.);minimum=min(densities,default=0.)
    varied=maximum-minimum>1e-6*max(1.,abs(maximum))
    for row in rows:
        x = 40 + (row['x_mm']-row['width_mm']/2-left)*scale
        y = 40 + (top-row['y_mm']-row['thickness_mm']/2)*scale
        name = escape(str(row['name']), quote=True)
        copper = []
        for cell in cells:
            if cell['conductor'] != row['name']: continue
            cx = 40+(cell['x_mm']-cell['width_mm']/2-left)*scale
            cy = 40+(top-cell['y_mm']-cell['height_mm']/2)*scale
            density=cell['current_density_rms_a_mm2'];fraction=max(0.,min(1.,(density-minimum)/(maximum-minimum))) if varied and _number(density) else 0.
            color='#e3e7e8' if not _number(density) else f'hsl({240*(1-fraction)},80%,48%)' if varied else '#d9a441'
            detail = escape('Total RMS J: '+_text(density)+' A/mm²; Joule loss density: '+_text(cell['loss_density_w_mm3'])+' W/mm³')
            copper.append(f'<rect class="cell" x="{cx}" y="{cy}" width="{cell["width_mm"]*scale}" height="{cell["height_mm"]*scale}" fill="{color}"><title>{detail}</title></rect>')
        shapes.append('<g data-conductor="'+name+'" tabindex="0"><rect class="outline" x="'+str(x)+'" y="'+str(y)+'" width="'+str(row['width_mm']*scale)+'" height="'+str(row['thickness_mm']*scale)+'" fill="'+('none' if cells else '#df9d35' if row['current_scale'] > 0 else '#5fa8c9')+'"><title>'+name+' · '+escape(_text(row['current_scale']))+' × loop current; click to select</title></rect>'+''.join(copper)+'<text x="'+str(x+row['width_mm']*scale/2)+'" y="'+str(y-9)+'" text-anchor="middle">'+name+'</text></g>')
    legend=('<p>RMS current density: blue = '+_text(minimum)+', red = '+_text(maximum)+' A/mm². Colours show the solved spatial range; hover a cell for exact values.</p>' if varied else '<p>Uniform RMS current density: '+_text(maximum)+' A/mm²; no spatial colour scale is needed.</p>') if cells else ''
    if cells and not densities:legend='<p>No solved current-density field supplied. Gray cells are unknown.</p>'
    return '<svg id="cross-section" viewBox="0 0 780 '+str(80+(top-bottom)*scale)+'" role="img" aria-label="Explicit conductor cross-section; click to cross-select table">'+''.join(shapes)+'</svg>'+legend


def _chart(rows, keys, labels, title):
    """A labelled discrete comparison for one harmonic, or a supplied-point chart."""
    points=[(index,row) for index,row in enumerate(rows) if _number(row.get('frequency_hz')) and row['frequency_hz']>0]
    if not points:return '<p>No supplied harmonic result.</p>'
    base='W' if keys==('loss_w',) else 'Ω'
    scale,unit=_display_unit([row.get(key) for _,row in points for key in keys],base)
    frequencies=[row['frequency_hz'] for _,row in points]
    single=len(set(frequencies))==1
    logarithmic=not single and max(frequencies)/min(frequencies)>=10
    transform=math.log10 if logarithmic else lambda value:value
    low=min(map(transform,frequencies));high=max(map(transform,frequencies))
    values=[row[key]*scale for _,row in points for key in keys if _number(row.get(key))]
    if not values:return '<p>No solved harmonic values supplied for '+escape(title)+'.</p>'
    minimum=min([0.,*values]);maximum=max([0.,*values]);span=maximum-minimum or 1.
    y=lambda value:230-165*(value-minimum)/span
    colors=('#156b76','#b36a20');shapes=[]
    for tick in (minimum,(minimum+maximum)/2,maximum):
        shapes.append(f'<path d="M70 {y(tick)} H710" stroke="#dce5e8"/><text x="62" y="{y(tick)+4}" text-anchor="end">{tick:.4g}</text>')
    for series,(key,label) in enumerate(zip(keys,labels)):
        shapes.append(f'<text x="{80+series*240}" y="45" fill="{colors[series]}">{escape(label)} ({escape(unit)})</text>')
        positions=[]
        for index,row in points:
            if not _number(row.get(key)):continue
            value=row[key]*scale
            x=390+(series-(len(keys)-1)/2)*180 if single else 70+640*(transform(row['frequency_hz'])-low)/(high-low or 1)
            detail=escape(engineering(row['frequency_hz'],'Hz')+' · '+label+': '+engineering(row[key],base))
            if single or keys==('loss_w',):
                top=min(y(value),y(0));height=abs(y(value)-y(0))
                half=55 if single else min(25.,240/max(1,len(points)))
                shapes.append(f'<rect data-harmonic="{index}" tabindex="0" x="{x-half}" y="{top}" width="{half*2}" height="{height}" fill="{colors[series]}"><title>{detail}; click to pin</title></rect><text x="{x}" y="{y(value)-8}" text-anchor="middle">{value:.4g} {escape(unit)}</text>')
            else:
                positions.append(f'{x},{y(value)}');shapes.append(f'<circle data-harmonic="{index}" tabindex="0" cx="{x}" cy="{y(value)}" r="5" fill="{colors[series]}"><title>{detail}; click to pin</title></circle>')
        if positions:shapes.append('<polyline points="'+' '.join(positions)+'" fill="none" stroke="'+colors[series]+'" pointer-events="none"/>')
    caption=engineering(frequencies[0],'Hz')+' · one supplied harmonic' if single else engineering(min(frequencies),'Hz')+' to '+engineering(max(frequencies),'Hz')+' · supplied frequencies'
    return '<svg class="chart" viewBox="0 0 740 285" role="img" aria-label="'+escape(title,quote=True)+'"><text x="70" y="20">'+escape(title)+'</text><path d="M70 65 V230 H710" fill="none" stroke="#647580"/>'+''.join(shapes)+'<text x="390" y="267" text-anchor="middle">'+escape(caption)+'</text></svg>'


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
    html += '<div class="ac-metrics"><p><strong>Total copper Joule loss:</strong> '+escape(engineering(result.get('total_loss_w'),'W'))+'<br>'
    html += '<strong>Copper-loop AC drop RMS:</strong> '+escape(engineering(result.get('ripple_voltage_rms_v'),'V'))+'<br>'
    html += '<strong>Reference waveform RMS:</strong> '+escape(engineering(result.get('total_current_rms_a'),'A'))+'</p></div>'
    html += '<p>AC drop is across the modeled copper loop; it is not delivered rail ripple after filtering or regulation. Individual conductor currents follow their signed multipliers.</p>'
    html += '<h2>Conductor cross-selection</h2>'+_geometry(bundle['study'],result.get('cells',[]))
    html += _table('conductors', conductor_rows, [('name','Conductor'),('dc_loss_w','DC heating (mW)',1000.),('ac_loss_w','AC ripple heating (mW)',1000.),('total_loss_w','Total heating (mW)',1000.)], 'name')
    html += '<h2>Impedance and harmonic losses</h2>'+_chart(harmonics, ('resistance_ohm','reactance_ohm'), ('R · resistive','X · reactive'), 'Loop resistance and reactance')
    html += _chart(harmonics, ('loss_w',), ('Heating',), 'Copper heating from each harmonic')
    html += _table('harmonics', harmonics, [('frequency_hz','Frequency (kHz)',.001),('current_rms_a','Current RMS (A)'),('resistance_ohm','Resistance (mΩ)',1000.),('reactance_ohm','Reactance (mΩ)',1000.),('loss_w','Heating (mW)',1000.),('skin_depth_mm','Skin depth (mm)')])
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
    from wayricad_runtime.report_ui import enhance_report
    html=enhance_report(html,status=status,summary=[('DC copper heating',engineering(result.get('dc_loss_w'),'W')),('AC ripple heating',engineering(result.get('ac_loss_w'),'W')),('Total copper heating',engineering(result.get('total_loss_w'),'W'))],notice='Explicit straight-conductor cross-section. Copper-loop AC drop is not delivered rail ripple. Review convergence and model applicability before using estimates.')
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
