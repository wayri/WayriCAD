"""Read-only first-order signal timing and resistive termination screening."""
from __future__ import annotations
import html
import json
import math
from .measurement import TraceMeasurementEngine

C_MM_NS = 299.792458


def finite(value, name, minimum=0., strict=False):
    try:value=float(value)
    except (TypeError,ValueError) as exc:raise ValueError(name+" must be a number.") from exc
    if not math.isfinite(value) or value<minimum or (strict and value==minimum):
        raise ValueError(name+' must be finite and '+('greater than ' if strict else 'at least ')+str(minimum)+'.')
    return value


def screen(path, *, rise_ns=1., frequency_mhz=100., source_ohm=20., load_ohm=None,
           z0_ohm=None, epsilon_eff=None, terminal_count=2, eye_bitrate_mbps=None, eye_swing_v=1.):
    """Screen one resolved route; explicit assumptions never become extracted data."""
    rise_ns=finite(rise_ns,'Rise time',strict=True)
    frequency_mhz=finite(frequency_mhz,'Frequency')
    source_ohm=finite(source_ohm,'Source resistance')
    if load_ohm is not None:load_ohm=finite(load_ohm,'Load resistance')
    if z0_ohm is not None:z0_ohm=finite(z0_ohm,'Assumed Z0',strict=True)
    if epsilon_eff is not None:epsilon_eff=finite(epsilon_eff,'Effective permittivity',minimum=1.)
    notes=list(path.notes)
    resolved=path.status in ('ok','partial') and path.length_mm>0 and math.isfinite(path.length_mm)
    delay=None;z0=None;delay_source='unavailable';z0_source='unavailable'
    if resolved:
        if epsilon_eff is not None:
            delay=path.length_mm*math.sqrt(epsilon_eff)/C_MM_NS
            delay_source='User-assumed effective permittivity over the complete resolved path'
        elif path.status=='ok' and path.propagation_delay_ns>0 and math.isfinite(path.propagation_delay_ns):
            delay=path.propagation_delay_ns;delay_source='Complete modeled routed sections and board stackup'
        if z0_ohm is not None:
            z0=z0_ohm;z0_source='User-assumed uniform line; discontinuities are not modeled'
        elif path.impedance_valid and path.impedance_ohm>0 and math.isfinite(path.impedance_ohm):
            z0=path.impedance_ohm;z0_source='Uniform routed-line approximation from board/reference geometry'
    if not resolved:notes.append('No resolved route: no timing or reflection values are inferred from aggregate net length.')
    if delay is None:notes.append('Complete delay is unknown. Supply an explicit effective-permittivity assumption to screen the resolved route length.')
    if z0 is None:notes.append('Uniform Z0 is unknown. Supply an explicit Z0 assumption to screen terminations; it does not validate the actual impedance.')
    if terminal_count>2:notes.append(f'{terminal_count} terminals share this net. Other branches/stubs are not simulated; this is an endpoint-path screen.')
    if path.zone_count:notes.append('The route includes zone corridors, not a field solution for distributed plane propagation.')
    if path.via_count or path.layer_changes:notes.append('Vias and reference transitions require discontinuity review; reflections at those transitions are not calculated.')
    ratio=delay/rise_ns if delay is not None else None
    edge_review='unknown' if ratio is None else 'Transmission-line review' if ratio>=1/6 else 'Short relative to the entered edge (screen only)'
    gamma_source=(source_ohm-z0)/(source_ohm+z0) if z0 else None
    gamma_load=(1. if load_ohm is None else (load_ohm-z0)/(load_ohm+z0)) if z0 else None
    series=max(0.,z0-source_ohm) if z0 is not None and source_ohm<=z0 else None
    if z0 is not None and source_ohm>z0:notes.append('Source resistance exceeds Z0; adding a positive series resistor cannot source-match this line.')
    notes.append('Resistive, linear, uniform-line screening only. Receiver capacitance, driver IBIS/nonlinearity, crosstalk, differential coupling and eye diagrams are not solved.')
    report = {'schema':'wayricad.quick-si/v1','status':'UNRESOLVED' if not resolved else 'SCREENED' if delay is not None and z0 is not None else 'INCOMPLETE',
            'path':path.as_report(),'inputs':dict(rise_ns=rise_ns,frequency_mhz=frequency_mhz,source_ohm=source_ohm,load_ohm=load_ohm,assumed_z0_ohm=z0_ohm,assumed_epsilon_eff=epsilon_eff),
            'delay_ns':delay,'round_trip_ns':None if delay is None else 2*delay,
            'electrical_length_deg':None if delay is None else 360*frequency_mhz*delay/1000,
            'delay_to_rise_ratio':ratio,'edge_screen':edge_review,'z0_ohm':z0,
            'source_reflection':gamma_source,'load_reflection':gamma_load,
            'first_load_step_per_source_step':None if z0 is None else z0/(source_ohm+z0)*(1+gamma_load),
            'series_match_candidate_ohm':series,'delay_source':delay_source,'z0_source':z0_source,
            'terminal_count':terminal_count,'notes':list(dict.fromkeys(notes))}
    if eye_bitrate_mbps is not None:
        finite(eye_bitrate_mbps,'Eye bit rate',strict=True)
        finite(eye_swing_v,'Eye source swing',strict=True)
        if delay is None or z0 is None:
            report['eye']={'status':'UNAVAILABLE','reason':'Resolve the route, complete delay and uniform Z0 before generating an eye.'}
        elif terminal_count != 2 or path.zone_count:
            report['eye']={'status':'UNAVAILABLE','reason':'The simple eye requires a two-terminal trace/via path without zones or extra branches.'}
        else:
            from .eye_model import simulate_eye
            report['eye']=simulate_eye(z0_ohm=z0,delay_ns=delay,source_ohm=source_ohm,
                load_ohm=load_ohm,rise_ns=rise_ns,bitrate_mbps=eye_bitrate_mbps,swing_v=eye_swing_v)
        report['inputs'].update(eye_bitrate_mbps=eye_bitrate_mbps,eye_swing_v=eye_swing_v)
        report['notes']=[note.replace('and eye diagrams are not solved','are not solved by the route screen; the optional eye uses a separate ideal uniform-line model') for note in report['notes']]
    return report


def analyze(board,net,start,end,reference='Auto',**inputs):
    for key,label,strict in [('rise_ns','Rise time',True),('frequency_mhz','Frequency',False),('source_ohm','Source resistance',False)]:
        if key in inputs:inputs[key]=finite(inputs[key],label,strict=strict)
    engine=TraceMeasurementEngine(board)
    pads=engine.pads_for_net(net)
    if start==end or start not in pads or end not in pads:
        raise ValueError('Choose two distinct pads belonging to the selected net.')
    path=engine.measure(net,start,end,float(inputs.get('frequency_mhz',100.)),reference)
    return screen(path,terminal_count=len(pads),**inputs),path


def html_report(report):
    escape=lambda value:html.escape(str(value))
    rows=''.join('<tr><th>'+escape(key.replace('_',' '))+'</th><td>'+escape('Unknown' if value is None else value)+'</td></tr>'
                 for key,value in report.items() if key not in ('path','inputs','notes','schema','eye'))
    points=[]
    for segment in report['path'].get('segments',[]):
        if segment.get('start_mm') and segment.get('end_mm'):points.append((segment['start_mm'],segment['end_mm']))
    svg=''
    if points:
        xs=[p[0] for pair in points for p in pair];ys=[p[1] for pair in points for p in pair]
        x,y=min(xs)-1,min(ys)-1;w,h=max(xs)-min(xs)+2,max(ys)-min(ys)+2
        svg=f'<svg viewBox="{x} {y} {w} {h}" width="100%" height="280" aria-label="Resolved route geometry">'+''.join(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#287a9a" stroke-width=".12"/>' for a,b in points)+'</svg>'
    from .eye_view import eye_section
    eye=eye_section(report['eye']) if 'eye' in report else ''
    return '<!doctype html><meta charset="utf-8"><title>WayriCAD Quick SI</title><style>body{font:15px system-ui;max-width:950px;margin:30px auto;color:#20303c}td,th{padding:7px;text-align:left;border-bottom:1px solid #ddd}pre{white-space:pre-wrap}</style><h1>WayriCAD Quick SI</h1><p>Read-only first-order screening, not protocol signoff.</p>'+svg+'<table>'+rows+'</table>'+eye+'<h2>Assumptions and limitations</h2><ul>'+''.join('<li>'+escape(n)+'</li>' for n in report['notes'])+'</ul><h2>Inputs and path evidence</h2><pre>'+escape(json.dumps({'inputs':report['inputs'],'path':report['path']},indent=2,allow_nan=False))+'</pre>'
