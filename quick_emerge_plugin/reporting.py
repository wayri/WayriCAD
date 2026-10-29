"""Offline, custody-checked HTML/PDF evidence for Quick EMerge studies.

Matplotlib and the optional PDF renderer are imported only on export. All chart
assets and complete JSON evidence are embedded; scripts and remote assets are
unnecessary. Export snapshots the input and checks source/config before and
again after rendering. Printed figures preserve the original sampled values.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from html import escape
import hashlib
import io
import json
from pathlib import Path
import re

from .model import config_digest, source_identity, validate_config
from .network import from_result
from .inspection import FieldInspection


def fit_validation_notice(fit):
    """Distinguish training interpolation from held-out predictive evidence."""
    if not fit: return ''
    error = fit.get('holdout_max_abs_error')
    if error is None: return 'Fit needs validation: held-out sample checks are unavailable.'
    if error > fit.get('absolute_tolerance_requested', 0):
        return 'Fit needs validation: held-out sample error exceeds the requested tolerance.'
    return ''


def result_digest(result):
    """Digest the complete JSON result, including solver and geometry evidence."""
    try:
        payload = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError('Result contains nonfinite or non-JSON evidence') from exc
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def validate_report_result(result, *, expected_config=None, expected_source=None, verify_source=True):
    """Reject malformed or stale results; return the validated sampled network.

    ``verify_source=False`` is an explicit archival path: reports prominently
    disclose that present source bytes were not checked. All recorded hashes,
    scope and finite numerical data must still be structurally valid.
    """
    import numpy as np
    if not isinstance(result,dict) or result.get('schema') not in (1,2):
        raise ValueError('Unsupported Quick EMerge result schema')
    result_digest(result)
    config = validate_config(result.get('config'))
    study=config.get('advanced',{}).get('study','driven')
    nonnetwork=study in ('thermal','scattering')
    if nonnetwork:
        if result.get('port_count') != 0 or result.get('s_parameters') != {}:
            raise ValueError('Thermal/scattering studies must not contain a fictitious network')
        network=None
        frequencies=np.asarray(result.get('frequencies_hz',[]),dtype=float)
        if frequencies.ndim!=1 or not np.isfinite(frequencies).all() or np.any(frequencies<=0) or np.any(np.diff(frequencies)<=0):
            raise ValueError('Invalid solved frequency axis')
        if study=='scattering' and not len(frequencies):
            raise ValueError('Scattering study requires solved frequencies')
        if study=='thermal' and len(frequencies):
            raise ValueError('Thermal studies do not have an RF sweep')
    else:
        network=from_result(result)
        frequencies=network.frequencies_hz
    if result.get('config_sha256') != config_digest(config):
        raise ValueError('Result configuration hash is invalid; rerun the reviewed study')
    if expected_config is not None and config_digest(expected_config) != result['config_sha256']:
        raise ValueError('Setup changed after solve; report would be stale')
    source = result.get('source')
    if (not isinstance(source, dict) or not isinstance(source.get('path'), str)
            or not source['path'] or not isinstance(source.get('sha256'), str)
            or re.fullmatch('[0-9a-f]{64}', source['sha256']) is None):
        raise ValueError('Result must retain a source path and SHA-256 custody record')
    if expected_source is not None and source != expected_source:
        raise ValueError('Result does not match the reviewed source')
    if verify_source and source_identity(source['path']) != source:
        raise ValueError('Source PCB changed after solve; report would be stale')
    scope = result.get('model_scope')
    if config['mode'] == 'pcb_region':
        if scope != ('saved-rule-area-substrate-thermal' if study=='thermal' else 'saved-rule-area-copper'):
            raise ValueError('Result geometry scope does not match PCB region mode')
        from .region_backend import region_digest, validate_region
        region = result.get('region')
        validate_region(region, config)
        if region['source'] != source or result.get('region_sha256') != region_digest(region):
            raise ValueError('Region geometry or source hash changed after solve')
    elif scope not in {'driven':('parametric-template','four-layer-via-template'),'optimization':('parametric-template',),'periodic':('periodic-patch-template',),'array':('finite-patch-array-template',),'waveguide':('rectangular-waveguide-template',),'scattering':('pec-sphere-scattering','step-pec-scattering'),'thermal':('substrate-thermal-template',)}.get(study,()):
        raise ValueError('Result geometry scope does not match its study type')
    if len(frequencies) and (frequencies[0] < config['f_start_hz']*(1-1e-12)
            or frequencies[-1] > config['f_stop_hz']*(1+1e-12)):
        raise ValueError('Solved frequencies fall outside the recorded sweep')
    if not isinstance(result.get('backend'), dict) or not result['backend'].get('version'):
        raise ValueError('Result must identify the solver version')
    if not isinstance(result.get('assumptions'), list) or not all(isinstance(v, str) for v in result['assumptions']):
        raise ValueError('Result must retain its model assumptions')
    if 'thermal' in result:
        _thermal_data(result)
    if study=='thermal':
        if 'field' in result or 'radiation' in result:
            raise ValueError('Thermal temperature data cannot be labeled as RF fields')
    if study=='scattering':
        _scattering_data(result,frequencies)
    if result.get('import_source'):
        imported=result['import_source']
        if not isinstance(imported,dict) or not isinstance(imported.get('path'),str) or re.fullmatch('[0-9a-f]{64}',str(imported.get('sha256',''))) is None:
            raise ValueError('Invalid imported geometry custody')
        if verify_source and hashlib.sha256(Path(imported['path']).read_bytes()).hexdigest()!=imported['sha256']:
            raise ValueError('Imported STEP geometry changed; report would be stale')
    if 'optimization' in result:
        best=validate_config(result['optimization']['best_config'])
        if best.get('advanced',{}).get('study','driven')!='driven':
            raise ValueError('Optimization best_config must identify the solved driven setup')
    if 'field' in result:
        field = FieldInspection(result['field'])
        if not np.any(np.isclose(frequencies, field.frequency, rtol=1e-12, atol=0)):
            raise ValueError('Field frequency is not in the solved sweep')
    if 'radiation' in result:
        try:
            r = result['radiation']
            theta, phi, norm = (np.asarray(r[k], dtype=float) for k in ('theta_rad','phi_rad','norm_e'))
            frequency = float(r['frequency_hz'])
            if (theta.ndim != 1 or phi.ndim != 1 or len(theta)<2 or len(phi)<2
                    or norm.shape != (len(theta),len(phi))
                    or any(not np.isfinite(a).all() for a in (theta,phi,norm))
                    or np.any(np.diff(theta)<=0) or np.any(np.diff(phi)<=0)
                    or theta[0]<0 or theta[-1]>np.pi+1e-12
                    or np.any(norm<0) or not np.isfinite(frequency)
                    or not np.any(np.isclose(frequencies,frequency,rtol=1e-12,atol=0))):
                raise ValueError('Invalid radiation axes, magnitudes or frequency')
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError('Invalid radiation structure') from exc
    return network


def _format(value):
    import math
    if value is None:
        return 'Unknown / unavailable'
    if isinstance(value, (int, float)):
        if math.isnan(value):
            return 'Unavailable'
        if math.isinf(value):
            return '+infinity' if value>0 else '-infinity'
        return f'{value:.7g}'
    return str(value)


def _table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(_format(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def _png(figure):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    buffer = io.BytesIO()
    FigureCanvasAgg(figure).print_png(buffer)
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def _figure(title, draw):
    from matplotlib.figure import Figure
    figure = Figure(figsize=(9,5), dpi=200, facecolor='white')
    try:
        draw(figure)
        return '<figure><img loading="lazy" alt="'+escape(title,quote=True)+'" src="data:image/png;base64,'+_png(figure)+'"><figcaption>'+escape(title)+'</figcaption></figure>'
    finally:
        figure.clear()


def _charts(network, analysis):
    import numpy as np
    freq = network.frequencies_hz/1e9
    def response(fig):
        ax = fig.subplots()
        for i in range(network.port_count):
            for j in range(network.port_count):
                values = analysis['magnitude_db'][:,i,j]
                ax.plot(freq, np.where(np.isfinite(values), values, np.nan), 'o-', ms=3,
                        label=f'S{i+1}{j+1}')
        ax.set(xlabel='Frequency [GHz]',ylabel='20 log10 |S| [dB]', title='Complete sampled S matrix')
        ax.grid(alpha=.2); ax.legend(ncol=min(4,network.port_count),fontsize=8)
        fig.tight_layout()
    def phase(fig):
        axes = fig.subplots(2,1,sharex=True)
        for i in range(network.port_count):
            for j in range(network.port_count):
                axes[0].plot(freq,analysis['phase_rad'][:,i,j]*180/np.pi,'o-',ms=3,label=f'S{i+1}{j+1}')
                axes[1].plot(freq,analysis['group_delay_s'][:,i,j]*1e9,'o-',ms=3)
        axes[0].set(ylabel='Unwrapped phase [deg]',title='Sampled phase and finite-difference delay')
        axes[1].set(xlabel='Frequency [GHz]',ylabel='Group delay [ns]')
        axes[0].legend(ncol=min(4,network.port_count),fontsize=8)
        for ax in axes: ax.grid(alpha=.2)
        fig.tight_layout()
    def reflection(fig):
        ax = fig.subplots()
        angle = np.linspace(0,2*np.pi,361)
        ax.plot(np.cos(angle),np.sin(angle),color='#bacad1',lw=1)
        ax.axhline(0,color='#bacad1',lw=.6); ax.axvline(0,color='#bacad1',lw=.6)
        for i in range(network.port_count):
            v=network.s[:,i,i]
            ax.plot(v.real,v.imag,'o-',ms=4,label=f'S{i+1}{i+1}; {network.z0_ohm[i]:g} ohm')
        ax.set(xlabel='Real reflection coefficient',ylabel='Imaginary reflection coefficient',title='Reflection in the complex plane')
        ax.set_aspect('equal',adjustable='datalim'); ax.legend(fontsize=8); ax.grid(alpha=.2)
        fig.tight_layout()
    return _figure('S matrix magnitude; exact zero magnitudes have -infinity dB and are omitted from the chart.',response)+_figure('Phase and delay; phase below the 1e-12 magnitude floor is unavailable. Sampling can alias phase.',phase)+_figure('Reflection coefficients at each recorded port reference.',reflection)


def _selections(result, probes, line_profile):
    from .field_display import field_for_display
    def inspect(item):
        quantity=item.get('quantity', 'Temperature' if 'thermal' in result and 'field' not in result else 'E magnitude')
        iz=item.get('iz')
        if iz is None and item.get('z_mm') is not None and quantity != 'Temperature' and result.get('field',{}).get('volume'):
            zs=result['field']['volume']['z_mm']
            matches=[i for i,z in enumerate(zs) if abs(z-float(item['z_mm'])) <= 1e-9]
            if not matches: raise ValueError('Probe Z is not an original volume layer')
            iz=matches[0]
        field=FieldInspection(field_for_display(result,quantity,iz))
        sample=field.probe(item['x_mm'],item['y_mm'])
        if iz is not None: sample['iz']=iz
        if quantity=='Temperature': sample['value_k']=sample['temperature_k']
        return sample
    selected=[]
    for index,p in enumerate(probes or []):
        if not isinstance(p,dict): raise ValueError('Probes must contain coordinates')
        if p.get('kind','field') != 'field': continue
        sample=inspect(p)
        selected.append({'label':str(p.get('label',f'P{index+1}')),'requested_x_mm':p['x_mm'],'requested_y_mm':p['y_mm'],**sample})
    if line_profile is None: return selected,[]
    if isinstance(line_profile,dict):
        q=line_profile.get('quantity','Temperature' if 'thermal' in result and 'field' not in result else 'E magnitude')
        field=FieldInspection(field_for_display(result,q,line_profile.get('iz')))
        line=field.line(line_profile['start'],line_profile['end'],line_profile.get('count',100))
        if q=='Temperature':
            for item in line: item['value_k']=item['temperature_k']
        return selected,line
    if not isinstance(line_profile,list) or not 2<=len(line_profile)<=2000: raise ValueError('Line profile must contain 2 to 2000 original samples')
    import math
    line=[]; previous=-1
    for item in line_profile:
        sample=inspect(item); distance=float(item['distance_mm'])
        if not math.isfinite(distance) or distance<0 or distance<previous: raise ValueError('Line profile distance must be finite, nonnegative and ordered')
        line.append({**sample,'distance_mm':distance}); previous=distance
    return selected,line


def _selection_html(selected,line,include_figures):
    chunks=['<h3>Selected / pinned probes</h3>']
    if selected:
        chunks.append(_table(['Probe','X [mm]','Y [mm]','Z [mm]','Quantity','Value','Unit'],[[p['label'],p['x_mm'],p['y_mm'],p['z_mm'],p['quantity'],p.get({'E magnitude':'value_v_m','H magnitude':'value_a_m','Power-flow magnitude':'value_w_m2','Temperature':'temperature_k'}[p['quantity']]),p['unit']] for p in selected]))
    else: chunks.append('<p>No field probes were retained with this export.</p>')
    if line:
        chunks.append('<h3>Retained line profile</h3><p>Nearest original grid samples; repeated samples are expected. Distance follows the requested path in millimetres.</p>')
        def val(p): return p.get({'E magnitude':'value_v_m','H magnitude':'value_a_m','Power-flow magnitude':'value_w_m2','Temperature':'temperature_k'}[p['quantity']])
        if include_figures:
            def draw(fig):
                import numpy as np
                ax=fig.subplots(); ax.plot([p['distance_mm'] for p in line],[np.nan if val(p) is None else val(p) for p in line],'-o',ms=3)
                ax.set(xlabel='Distance [mm]',ylabel=line[0]['quantity']+' ['+line[0]['unit']+']'); ax.grid(alpha=.2); fig.tight_layout()
            chunks.append(_figure('Nearest original sample line profile; unknown values remain gaps.',draw))
        chunks.append(_table(['Distance [mm]','Sample X [mm]','Sample Y [mm]','Z [mm]','Quantity','Value','Unit'],[[p['distance_mm'],p['x_mm'],p['y_mm'],p['z_mm'],p['quantity'],val(p),p['unit']] for p in line]))
    return ''.join(chunks)


def _derived_section(derived,network,result,include_figures):
    from .network_extensions import deserialize_network
    if not isinstance(derived,dict) or derived.get('schema')!=1 or derived.get('kind')!='derived-network': raise ValueError('Invalid derived network evidence')
    if derived.get('original_network_sha256')!=network.digest() or derived.get('source_board')!=result['source']: raise ValueError('Derived network source does not match original result')
    source=derived.get('source_result',{})
    if not isinstance(source,dict) or not source.get('path') or not re.fullmatch('[0-9a-f]{64}',str(source.get('sha256',''))): raise ValueError('Invalid derived source result custody')
    path=Path(source['path'])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']: raise ValueError('Derived source result changed or unavailable')
    try: saved=json.loads(path.read_bytes())
    except (ValueError,OSError) as exc: raise ValueError('Invalid derived source result') from exc
    if result_digest(saved)!=result_digest(result): raise ValueError('Derived source result differs from original')
    transformed=deserialize_network(derived['derived_network'])
    section=['<section><h2>Derived network postprocessing</h2><p>These transformed scalar network results are separate from the original solve. Original electromagnetic field excitation and geometry are unchanged.</p>',
             _table(['Evidence','Value'],[('Operation',json.dumps(derived.get('operation'),sort_keys=True)),('Original network SHA-256',network.digest()),('Derived network SHA-256',transformed.digest()),('Source result bytes SHA-256',source['sha256'])])]
    notice = fit_validation_notice(derived.get('fit'))
    if notice: section.append('<p class="notice">'+escape(notice)+' Fitted values are separate from solved samples.</p>')
    if include_figures: section.append(_charts(transformed,transformed.analyze()))
    section.append('<details><summary>Diagnostics, fit and limits</summary><pre>'+escape(json.dumps({k:derived.get(k) for k in ('diagnostics','fit','limits')},indent=2,allow_nan=False))+'</pre></details>')
    encoded=base64.b64encode(json.dumps(derived,allow_nan=False,indent=2).encode()).decode()
    section.append('<a class="download" download="quick-emerge-derived-network.json" href="data:application/json;base64,'+encoded+'">Download derived network JSON</a><details><summary>Derived network evidence</summary><pre>'+escape(json.dumps(derived,indent=2,allow_nan=False))+'</pre></details></section>')
    return ''.join(section)


_CSS='''
:root{--ink:#163344;--accent:#087e84;--muted:#58717d;--line:#dbe6eb}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf3f5;color:var(--ink);font:15px/1.65 system-ui,Arial,sans-serif}.page{max-width:1140px;margin:auto;background:white;padding:36px 54px;box-shadow:0 10px 60px #143f4b12}header{padding:20px 0 30px;border-bottom:3px solid var(--accent)}.eyebrow{text-transform:uppercase;letter-spacing:.19em;font-size:12px;font-weight:750;color:var(--accent)}h1{font-size:38px;line-height:1.15;letter-spacing:-.025em;margin:10px 0 20px}h2{font-size:24px;margin:36px 0 12px;border-bottom:1px solid var(--line);padding-bottom:8px}h3{font-size:18px}p{max-width:95ch}nav{display:flex;flex-wrap:wrap;gap:16px;padding:16px 0;font-size:13px}a{color:var(--accent)}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}.card{padding:18px;background:#f1f8f8;border-top:3px solid var(--accent);border-radius:4px}.card strong{display:block;font-size:23px;line-height:1.3}.card span,.note,figcaption{color:var(--muted);font-size:13px}.notice{padding:14px 18px;border-left:4px solid #d29c38;background:#fff8e9}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0 22px}th,td{text-align:left;vertical-align:top;padding:9px 12px;border-bottom:1px solid var(--line);overflow-wrap:anywhere;font-variant-numeric:tabular-nums}th{background:#eef5f7}tbody tr:nth-child(even){background:#f8fafb}figure{margin:24px 0}img{max-width:100%;height:auto;display:block}figcaption{margin:5px 12px 18px}details{border:1px solid var(--line);border-radius:5px;margin:16px 0;padding:12px 16px}summary{cursor:pointer;font-weight:650}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;max-height:400px;overflow:auto}.hash{font-family:monospace;font-size:11px;overflow-wrap:anywhere}.download{display:inline-block;padding:8px 15px;background:var(--accent);color:white;border-radius:5px;text-decoration:none}@media(max-width:700px){.page{padding:20px}.cards{grid-template-columns:1fr}h1{font-size:30px}}@page{size:A4;margin:15mm}@media print{body{background:white;font-size:10pt}.page{padding:0;box-shadow:none}nav,.download{display:none}h1{font-size:25pt}h2{font-size:17pt;break-after:avoid}figure,.card,tr{break-inside:avoid}details>*{display:block}pre{max-height:none}thead{display:table-header-group}img{max-height:220mm;object-fit:contain}}
'''


def build_html_report(result, *, expected_config=None, expected_source=None,
                      verify_source=True, probes=None, line_profile=None,
                      title='Quick EMerge study', include_figures=True, derived_network=None):
    """Create a self-contained report; no files are written or network accessed."""
    snapshot=deepcopy(result)
    network=validate_report_result(snapshot,expected_config=expected_config,expected_source=expected_source,verify_source=verify_source)
    if network is None:
        if derived_network is not None: raise ValueError('Derived network requires an original sampled network')
        return _build_nonnetwork(snapshot,result,expected_config,expected_source,verify_source,probes,line_profile,title,include_figures)
    derived_snapshot=deepcopy(derived_network) if derived_network is not None else None
    derived_html=_derived_section(derived_snapshot,network,snapshot,include_figures) if derived_snapshot is not None else ''
    analysis=network.analyze()
    selected,line=_selections(snapshot,probes,line_profile)
    custody=result_digest(snapshot)
    c=snapshot['config']
    summary=[('Mode',c['mode']),('Geometry scope',snapshot['model_scope']),('Solver',snapshot['backend'].get('backend','EMerge')),
             ('Solver version',snapshot['backend']['version']),('Port ordering','; '.join(f'{i+1}: {name}' for i,name in enumerate(network.port_names))),
             ('Reference impedances [ohm]',', '.join(_format(v) for v in network.z0_ohm)),
             ('Wave convention','Real-reference power waves; S[receiver, source]'),
             ('Originating source',Path(snapshot['source']['path']).name),('Source verification','Current bytes checked' if verify_source else 'ARCHIVAL: current source bytes NOT checked')]
    chunks=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
            '<title>'+escape(str(title))+'</title><style>'+_CSS+'</style></head><body><main class="page">',
            '<header><p class="eyebrow">WayriCAD / Quick EMerge / RF study evidence</p><h1>'+escape(str(title))+'</h1>',
            '<p>Sampled electromagnetic response with traceable setup and explicit model boundaries.</p></header>',
            '<nav aria-label="Report sections"><a href="#scope">Scope</a><a href="#network">RF response</a><a href="#fields">Fields & probes</a><a href="#limits">Mesh & limitations</a><a href="#custody">Evidence</a></nav>',
            '<div class="cards"><div class="card"><strong>'+str(len(network.frequencies_hz))+'</strong> <span>Solved frequency samples</span></div>',
            '<div class="card"><strong>'+_format(network.frequencies_hz[0]/1e9)+' – '+_format(network.frequencies_hz[-1]/1e9)+'</strong> <span>Sweep [GHz]</span></div>',
            '<div class="card"><strong>'+str(network.port_count)+'</strong> <span>Ports / full S matrix</span></div></div>',
            '<p class="notice">'+('Current source custody checked. ' if verify_source else 'ARCHIVAL EXPORT: current source bytes were not checked. ')+
            'Sample diagnostics do not establish mesh convergence, causality or hardware performance.</p>',
            '<section id="scope"><h2>Geometry and model scope</h2>',_table(['Evidence','Recorded value'],summary)]
    if include_figures:
        if snapshot['model_scope']=='periodic-patch-template':
            chunks.append(_figure('Periodic unit-cell geometry in millimetres; infinite repeated array, no finite-array edge effects.',lambda f:_special_geometry(f,snapshot)))
        elif c['mode']=='pcb_region':
            from .region_view import geometry
            chunks.append(_figure('Reviewed clipped saved copper and port locations; exterior PCB and components are omitted.',lambda f: geometry(f,snapshot['region'])))
        else:
            from .plots import geometry
            chunks.append(_figure('Parametric geometry in millimetres; originating KiCad board supplies context only.',lambda f: geometry(f,snapshot.get('optimization',{}).get('best_config',c))))
    if c['mode'] == 'pcb_region':
        chunks.append('<p class="note">Physical dimensions come from the saved copper geometry above. Patch, line and substrate-extent template settings in the stored configuration below are inactive defaults for this PCB-region study.</p>')
    if 'optimization' in snapshot:
        chunks.append('<h3>Bounded optimization evidence</h3><p>Plots and geometry correspond to the best recorded driven configuration. The review configuration records the requested optimization bounds.</p><pre>'+escape(json.dumps(snapshot['optimization'],indent=2,allow_nan=False))+'</pre>')
    chunks.extend(['<details><summary>Full stored configuration (includes inactive defaults)</summary>',_table(['Configuration key (unit in key)','Value'],sorted(c.items())),'</details></section>',
                   '<section id="network"><h2>Sampled RF response</h2>',
                   '<p>Magnitude uses 20 log10 |S|; return loss is its negative on the diagonal. Exact zeros are -infinity dB. No interpolated or fitted samples are added. Off-diagonal entries retain receiver/source direction.</p>'])
    if include_figures:
        chunks.append(_charts(network,analysis))
    diagnostic_rows=[]
    for k,f in enumerate(network.frequencies_hz):
        diagnostic_rows.append([f/1e9,analysis['largest_singular_value'][k],analysis['passivity_excess'][k],analysis['reciprocity_error'][k]])
    chunks.extend(['<h3>Sample diagnostics</h3>',_table(['Frequency [GHz]','Largest singular value','Excess above 1','max |Sij − Sji|'],diagnostic_rows),
                   '<p class="note">A passive real-reference power-wave sample has largest singular value ≤ 1. Reciprocity is symmetry of S for the stated references. Interpret either expectation for the device being modeled; no result is rejected merely for apparent gain or asymmetry. Diagnostic tolerance: 1e-9.</p>',
                   '<details><summary>Reflection and transmission sample table</summary>'])
    rows=[]
    for k,f in enumerate(network.frequencies_hz):
        for i in range(network.port_count):
            for j in range(network.port_count):
                v=network.s[k,i,j]
                rows.append([f/1e9,f'S{i+1}{j+1}',v.real,v.imag,analysis['magnitude_db'][k,i,j],analysis['phase_rad'][k,i,j]*180/3.141592653589793,analysis['group_delay_s'][k,i,j]*1e9])
    chunks.extend([_table(['Frequency [GHz]','Entry','Real','Imaginary','Magnitude [dB]','Phase [deg]','Delay [ns]'],rows),
                   '<p class="note">Phase and delay are unavailable at magnitude ≤ 1e-12. Delay is −dφ/d(2πf), using nonuniform central differences and one-sided endpoint differences. Samples may alias phase. Two samples give only a secant estimate.</p></details></section>',
                   '<section id="fields"><h2>Fields, radiation and retained probes</h2>'])
    if 'field' in snapshot:
        field=FieldInspection(snapshot['field'])
        unknown=sum(v is None for row in field.values for v in row)
        chunks.append('<p>Electric-field norm |E| [V/m] at '+_format(field.frequency/1e9)+' GHz, Z = '+_format(field.z)+' mm; solver excitation normalization applies. '+str(unknown)+' outside-mesh/unknown samples remain unknown. The sample grid is not a tetrahedral mesh view.</p>')
        if include_figures:
            from .plots import near_field
            chunks.append(_figure('Original sampled electric-field plane; no interpolation or replacement of unknown values.',lambda f:near_field(f,snapshot)))
    else:
        chunks.append('<p>Near-field data were not recorded.</p>')
    if 'radiation' in snapshot:
        chunks.append('<p>Far-field |E| is shown as a relative pattern normalized to its recorded maximum; absolute gain, efficiency and radiated power are unavailable.</p>')
        if include_figures:
            import numpy as np
            if np.max(snapshot['radiation']['norm_e'])>0:
                from .plots import radiation
                chunks.append(_figure('Relative far-field pattern at '+_format(snapshot['radiation']['frequency_hz']/1e9)+' GHz; normalized radius has no length unit.',lambda f:radiation(f,snapshot)))
            else:
                chunks.append('<p>All recorded far-field magnitudes are zero; a normalized pattern is unavailable.</p>')
    else:
        chunks.append('<p>Radiation data were not recorded for this study.</p>')
    chunks.append(_selection_html(selected,line,include_figures))
    if 'thermal' in snapshot:
        chunks.append(_thermal_section(snapshot,include_figures))
    chunks.append(derived_html)
    chunks.extend(['</section><section id="limits"><h2>Mesh, convergence and interpretation limits</h2>',
                   _table(['Requested mesh / sweep control','Value'],[(k,c[k]) for k in ('mesh_edge_mm','resolution','adaptive_steps','convergence','max_tets','sweep','points')]),
                   '<p class="notice">Requested refinement settings do not demonstrate convergence. The report does not infer a converged mesh from a completed solver run. Tetrahedron counts, achieved error and refinement history are unknown unless supplied as explicit solver evidence below.</p>'])
    for key in ('mesh','mesh_statistics','convergence','convergence_history','mesh_convergence'):
        if key in snapshot:
            chunks.append('<details><summary>Recorded '+escape(key.replace('_',' '))+' evidence</summary><pre>'+escape(json.dumps(snapshot[key],indent=2,allow_nan=False))+'</pre></details>')
    chunks.append('<ul>'+''.join('<li>'+escape(v)+'</li>' for v in snapshot['assumptions']+analysis['limits'])+'</ul></section>')
    evidence={'result':snapshot,'report_selections':{'probes':selected,'line_profile':line},'result_sha256':custody,
              'network_sha256':network.digest(),'source_verified_at_export':bool(verify_source)}
    encoded=base64.b64encode(json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')).decode('ascii')
    chunks.extend(['<section id="custody"><h2>Source and result custody</h2>',
                   _table(['Identity','SHA-256'],[('Source PCB bytes',snapshot['source']['sha256']),('Normalized configuration',snapshot['config_sha256']),('Complete result JSON (canonical)',custody),('Sampled network (canonical)',network.digest())]+([('Region geometry',snapshot['region_sha256'])] if 'region_sha256' in snapshot else [])),
                   '<p class="note">These hashes identify the recorded data; they do not authenticate an author or prove numerical accuracy. The complete embedded evidence retains solver version, configuration, port order, units, raw samples, geometry scope and export selections.</p>',
                   '<p><a class="download" download="quick-emerge-evidence.json" href="data:application/json;base64,'+encoded+'">Download complete JSON evidence</a></p>',
                   '<details><summary>Recorded evidence and selections</summary><pre>'+escape(json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2))+'</pre></details>',
                   '<p class="note">Method references: scikit-rf documentation, network.s2z / s2y and Network.se2gmm. All report assets are embedded. No scripts or remote resources are required. Use browser Print / save as PDF for a print copy.</p></section></main></body></html>'])
    validate_report_result(snapshot,expected_config=expected_config,expected_source=expected_source,verify_source=verify_source)
    if derived_snapshot is not None: _derived_section(derived_snapshot,network,snapshot,False)
    if result_digest(result)!=custody:
        raise ValueError('Result changed during report generation; retry from current data')
    return ''.join(chunks)


def _publish(path,result,content,extension,validation):
    from wayricad_runtime.report_ui import publish_documents
    target=Path(path)
    if target.suffix.lower()!=extension:
        raise ValueError('Choose a '+extension+' report destination')
    validate_report_result(result,**validation)
    # Protect the source even when the caller explicitly chooses archival mode.
    publish_documents({target:content},sources=[result['source']['path']]+([result['import_source']['path']] if result.get('import_source') else []))
    return str(target)


def export_html(path,result,**kwargs):
    """Render and publish a complete offline HTML report without partial writes."""
    snapshot=deepcopy(result)
    content=build_html_report(snapshot,**kwargs)
    if result_digest(snapshot)!=result_digest(result):
        raise ValueError('Result changed while preparing the report')
    validation={k:kwargs[k] for k in ('expected_config','expected_source','verify_source') if k in kwargs}
    return _publish(path,snapshot,content,'.html',validation)


def export_pdf(path,result,**kwargs):
    """Export static text, tables and embedded raster figures with shared engine.

    ReportLab is optional. Missing dependencies fail before publication and do
    not replace an existing report. The HTML companion retains complete data.
    """
    from wayricad_runtime.pdf_report import pdf_bytes
    snapshot=deepcopy(result)
    content=build_html_report(snapshot,**kwargs)
    # The shared PDF renderer supplies its own title and image-alt captions.
    # Avoid repeating the generated HTML h1 and matching figcaptions there.
    printable=re.sub(r'<figcaption>.*?</figcaption>','',content,flags=re.S)
    printable=re.sub(r'<h1>.*?</h1>','',printable,count=1,flags=re.S)
    payload=pdf_bytes(printable,title=str(kwargs.get('title','Quick EMerge study')),
                      interaction_note='The offline HTML report retains the evidence and charts. Use the Quick EMerge workbench for interactive probing and 3D navigation.')
    if result_digest(snapshot)!=result_digest(result):
        raise ValueError('Result changed while preparing the PDF')
    validation={k:kwargs[k] for k in ('expected_config','expected_source','verify_source') if k in kwargs}
    return _publish(path,snapshot,payload,'.pdf',validation)


def _thermal_data(result):
    """Validate a nullable Y-by-X absolute-temperature plane in kelvin."""
    import numpy as np
    from .network import _numeric
    try:
        t=result['thermal']
        # Same rectangular sampling contract as fields, with a different quantity.
        inspection=FieldInspection({'x_mm':t['x_mm'],'y_mm':t['y_mm'],'z_mm':t['z_mm'],
                                    'frequency_hz':1,'norm_e_v_m':t['temperature_k']})
        keys=['peak_k','time_s']+([k for k in ('reference_peak_k','heat_source_w_m3') if k in t])
        scalars={k:_numeric(t[k],float,'thermal '+k) for k in keys}
        if any(v.ndim or v<0 for v in scalars.values()):
            raise ValueError('Thermal summary values must be finite, scalar and nonnegative')
        known=[v for row in inspection.values for v in row if v is not None]
        if not known or not np.isclose(max(known),float(scalars['peak_k']),rtol=1e-10,atol=1e-10):
            raise ValueError('Thermal peak must match the recorded sampled temperature plane')
        return inspection
    except (KeyError,TypeError) as exc:
        raise ValueError('Invalid thermal result structure') from exc



def _thermal_section(result,include_figures):
    import numpy as np
    t=result['thermal']; _thermal_data(result)
    rows=[('Peak sampled temperature [K]',t['peak_k']),('Recorded time [s]',t['time_s']),('Plane Z [mm]',t['z_mm'])]
    rows.extend((key,t[key]) for key in ('reference_peak_k','reference_scope','heat_source_w_m3','rf_frequency_hz','rf_input_power_w','coupling') if key in t)
    chunks=['<section><h2>Sampled substrate temperature [K]</h2>',_table(['Thermal evidence','Value'],rows)]
    chunks.append('<details><summary>Original temperature samples</summary>'+_table(['X [mm]','Y [mm]','Temperature [K]'],[[x,y,t['temperature_k'][iy][ix]] for iy,y in enumerate(t['y_mm']) for ix,x in enumerate(t['x_mm'])])+'</details>')
    if t.get('coupling'): chunks.append('<p>One-way dielectric RF heating only; conductor surface heating and thermal feedback into the EM model are excluded. The uniform-slab reference does not apply.</p>')
    else: chunks.append('<p>Temperature is absolute kelvin; unknown samples remain unknown.</p>')
    if include_figures:
        def draw(fig):
            ax=fig.subplots(); values=np.array([[np.nan if v is None else v for v in row] for row in t['temperature_k']]); image=ax.pcolormesh(t['x_mm'],t['y_mm'],np.ma.masked_invalid(values),shading='nearest',cmap='inferno'); fig.colorbar(image,ax=ax,label='Temperature [K]'); ax.set(xlabel='X [mm]',ylabel='Y [mm]');fig.tight_layout()
        chunks.append(_figure('Original sampled substrate temperature [K].',draw))
    return ''.join(chunks)+'</section>'

def _scattering_data(result,frequencies):
    import numpy as np
    from .network import _numeric
    try:
        r=result['scattering']
        theta,phi,rcs=(_numeric(r[k],float,'scattering '+k) for k in ('theta_rad','phi_rad','rcs_m2'))
        f=_numeric(r['frequency_hz'],float,'scattering frequency')
        power=_numeric(r['incident_power_w_m2'],float,'incident power density')
        if (theta.ndim!=1 or phi.ndim!=1 or len(theta)<2 or len(phi)<2
                or rcs.shape!=(len(theta),len(phi)) or np.any(rcs<0)
                or np.any(np.diff(theta)<=0) or np.any(np.diff(phi)<=0)
                or theta[0]<0 or theta[-1]>np.pi+1e-12
                or f.ndim or not np.any(np.isclose(frequencies,float(f),rtol=1e-12,atol=0))
                or power.ndim or power<=0):
            raise ValueError('Invalid scattering axes, RCS or excitation')
        return theta,phi,rcs
    except (KeyError,TypeError) as exc:
        raise ValueError('Invalid scattering result structure') from exc


def _special_geometry(fig,result):
    """Render only recorded template geometry; STEP is explicitly an enclosure."""
    import numpy as np
    from matplotlib.patches import Rectangle
    c=result['config'];scope=result['model_scope']
    if scope=='periodic-patch-template':
        ax=fig.subplots()
        sx,sy,w,l=(c[k] for k in ('substrate_x_mm','substrate_y_mm','patch_width_mm','patch_length_mm'))
        ax.add_patch(Rectangle((-sx/2,-sy/2),sx,sy,facecolor='#dbeee9',edgecolor='#1a7d70'))
        ax.add_patch(Rectangle((-w/2,-l/2),w,l,facecolor='#d6ad5a',edgecolor='#a37a2c'))
        ax.set(xlim=(-sx*.6,sx*.6),ylim=(-sy*.6,sy*.6),xlabel='X [mm]',ylabel='Y [mm]',title='Periodic unit cell and conducting patch; top view')
        ax.set_aspect('equal');fig.tight_layout();return
    if scope=='pec-sphere-scattering':
        radius=c.get('advanced',{}).get('scatter_radius_mm',result.get('scene_geometry',{}).get('radius',0))
        theta,phi=np.meshgrid(np.linspace(0,np.pi,25),np.linspace(0,2*np.pi,41),indexing='ij')
        ax=fig.add_subplot(111,projection='3d')
        ax.plot_surface(radius*np.sin(theta)*np.cos(phi),radius*np.sin(theta)*np.sin(phi),radius*np.cos(theta),color='#a8c6cd',edgecolor='none')
        ax.set(xlabel='X [mm]',ylabel='Y [mm]',zlabel='Z [mm]',title='PEC sphere template')
        ax.set_box_aspect((1,1,1));fig.tight_layout();return
    if scope=='step-pec-scattering':
        ax=fig.subplots();bounds=result.get('scene_geometry',{}).get('bounds')
        if bounds:
            x0,y0,_,x1,y1,_=bounds
            ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,fill=False,edgecolor='#668d98',linestyle='--'))
            ax.set_xlim(x0-(x1-x0)*.1,x1+(x1-x0)*.1);ax.set_ylim(y0-(y1-y0)*.1,y1+(y1-y0)*.1)
        ax.set(xlabel='X [mm]',ylabel='Y [mm]',title='Imported STEP bounding enclosure only; solid shape is retained in source geometry')
        ax.set_aspect('equal');fig.tight_layout();return
    # Thermal studies show the substrate outline only; copper is not modeled.
    ax=fig.subplots()
    if 'region' in result:
        from .region_view import _path
        from matplotlib.patches import PathPatch
        for shape in result['region']['substrate']['outline']:
            ax.add_patch(PathPatch(_path(shape),facecolor='#dbeee9',edgecolor='#1a7d70'))
        ax.autoscale_view()
    else:
        sx,sy=c['substrate_x_mm'],c['substrate_y_mm']
        ax.add_patch(Rectangle((-sx/2,-sy/2),sx,sy,facecolor='#dbeee9',edgecolor='#1a7d70'))
        ax.set_xlim(-sx*.6,sx*.6);ax.set_ylim(-sy*.6,sy*.6)
    ax.set(xlabel='X [mm]',ylabel='Y [mm]',title='Thermal substrate top view; copper, vias and components omitted')
    ax.set_aspect('equal');fig.tight_layout()


def _build_nonnetwork(snapshot,original,expected_config,expected_source,verify_source,probes,line_profile,title,include_figures):
    import numpy as np
    c=snapshot['config'];thermal='thermal' in snapshot
    custody=result_digest(snapshot)
    selected,line=_selections(snapshot,probes,line_profile)
    peak=float(snapshot['thermal']['peak_k']) if thermal else float(np.max(snapshot['scattering']['rcs_m2']))
    chunks=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
            '<title>'+escape(str(title))+'</title><style>'+_CSS+'</style></head><body><main class="page">',
            '<header><p class="eyebrow">WayriCAD / Quick EMerge / '+('Heat conduction' if thermal else 'Electromagnetic scattering')+'</p><h1>'+escape(str(title))+'</h1>',
            '<p>'+('Sampled substrate temperature with explicit thermal source and boundary conditions.' if thermal else 'Sampled plane-wave scattering and bistatic radar cross section.')+'</p></header>',
            '<nav><a href="#scope">Scope</a><a href="#fields">Results & probes</a><a href="#limits">Limitations</a><a href="#custody">Evidence</a></nav>',
            '<div class="cards"><div class="card"><strong>'+_format(peak)+'</strong> <span>'+('Peak sampled temperature [K]' if thermal else 'Peak sampled RCS [m²]')+'</span></div>',
            '<div class="card"><strong>'+('No RF ports' if thermal else 'Plane wave')+'</strong> <span>'+('Heat-conduction study' if thermal else 'Scattered-field excitation')+'</span></div>',
            '<div class="card"><strong>'+('Transient' if thermal and snapshot['thermal']['time_s'] else 'Steady state' if thermal else str(len(snapshot['frequencies_hz']))+' frequencies')+'</strong> <span>Recorded study domain</span></div></div>',
            '<p class="notice">'+('Current source custody checked. ' if verify_source else 'ARCHIVAL EXPORT: current source bytes were not checked. ')+
            'Mesh convergence and physical measurement agreement are not established by a completed solve.</p>',
            '<section id="scope"><h2>Geometry and model scope</h2>',
            _table(['Evidence','Recorded value'],[('Geometry scope',snapshot['model_scope']),('Solver version',snapshot['backend']['version']),('Originating source',Path(snapshot['source']['path']).name),('Source verification','Current bytes checked' if verify_source else 'ARCHIVAL: current source bytes NOT checked')])]
    if include_figures:chunks.append(_figure('Recorded geometry scope; dimensions in millimetres.',lambda f:_special_geometry(f,snapshot)))
    chunks.extend(['<details><summary>Full stored configuration (includes inactive defaults)</summary>',_table(['Configuration key (unit in key)','Value'],sorted(c.items())),'</details></section>',
                   '<section id="fields"><h2>'+('Sampled temperature' if thermal else 'Scattering and radiation')+'</h2>'])
    if thermal:
        t=snapshot['thermal'];inspection=_thermal_data(snapshot)
        unknown=sum(v is None for row in inspection.values for v in row)
        chunks.append(_table(['Thermal evidence','Value'],[('Peak sampled temperature [K]',t['peak_k']),('1D steady-state reference peak [K]',t['reference_peak_k']),('Reference applicability',t.get('reference_scope','Not supplied')),('Recorded time [s]',t['time_s']),('Volumetric heat source [W/m³]',t['heat_source_w_m3']),('Plane Z [mm]',t['z_mm']),('Unknown samples',unknown)]))
        chunks.append('<p>Temperature is absolute kelvin. Outside-mesh samples remain unknown. The 1D reference is a steady-state comparison; a transient result is not required to equal it. Heating is an explicit input rather than inferred RF dissipation.</p>')
        if include_figures:
            def temperatures(fig):
                ax=fig.subplots();values=np.array([[np.nan if v is None else v for v in row] for row in t['temperature_k']])
                image=ax.pcolormesh(t['x_mm'],t['y_mm'],np.ma.masked_invalid(values),shading='nearest',cmap='inferno')
                fig.colorbar(image,ax=ax,label='Temperature [K]')
                ax.set(xlabel='X [mm]',ylabel='Y [mm]',title='Sampled substrate temperature at '+_format(t['time_s'])+' s' if t['time_s'] else 'Steady-state sampled substrate temperature');ax.set_aspect('equal');fig.tight_layout()
            chunks.append(_figure('Original temperature sample plane [K]; masked regions are unknown.',temperatures))
    else:
        theta,phi,rcs=_scattering_data(snapshot,np.array(snapshot['frequencies_hz']))
        s=snapshot['scattering'];imax=np.unravel_index(np.argmax(rcs),rcs.shape)
        chunks.append(_table(['Scattering evidence','Value'],[('RCS frequency [GHz]',s['frequency_hz']/1e9),('Incident power density [W/m²]',s['incident_power_w_m2']),('Maximum sampled bistatic RCS [m²]',float(rcs[imax])),('Maximum theta [deg]',float(theta[imax[0]]*180/np.pi)),('Maximum phi [deg]',float(phi[imax[1]]*180/np.pi))]))
        chunks.append('<p>Bistatic radar cross section is an area in square metres. It is not antenna gain or efficiency. Angular samples describe one recorded frequency; no unrecorded frequency or angle is fitted.</p>')
        if include_figures:
            def rcs_plot(fig):
                ax=fig.subplots();image=ax.pcolormesh(phi*180/np.pi,theta*180/np.pi,rcs,shading='nearest',cmap='viridis')
                fig.colorbar(image,ax=ax,label='Bistatic RCS [m²]');ax.set(xlabel='Phi [deg]',ylabel='Theta [deg]',title='Sampled bistatic radar cross section');fig.tight_layout()
            chunks.append(_figure('Bistatic RCS in square metres at '+_format(s['frequency_hz']/1e9)+' GHz.',rcs_plot))
            if 'field' in snapshot:
                from .plots import near_field
                chunks.append(_figure('Sampled electric-field norm [V/m] for the recorded plane-wave excitation.',lambda f:near_field(f,snapshot)))
            if 'radiation' in snapshot and np.max(snapshot['radiation']['norm_e'])>0:
                from .plots import radiation
                chunks.append(_figure('Relative scattered far-field |E|; normalized radius, not gain or efficiency.',lambda f:radiation(f,snapshot)))
        chunks.append('<details><summary>Complete angular RCS samples</summary>'+_table(['Theta [deg]','Phi [deg]','RCS [m²]'],[[theta[i]*180/np.pi,phi[j]*180/np.pi,rcs[i,j]] for i in range(len(theta)) for j in range(len(phi))])+'</details>')
    chunks.append(_selection_html(selected,line,include_figures))
    chunks.extend(['</section><section id="limits"><h2>Mesh, convergence and interpretation limits</h2>',
                   _table(['Requested control','Value'],[(k,c[k]) for k in ('mesh_edge_mm','resolution','adaptive_steps','convergence','max_tets')]),
                   '<p class="notice">Requested mesh controls do not establish achieved error. Mesh/time refinement history and tetrahedron counts are unknown unless supplied explicitly below.</p>',
                   '<ul>'+''.join('<li>'+escape(v)+'</li>' for v in snapshot['assumptions'])+'</ul>'])
    for key in ('mesh','mesh_statistics','convergence','convergence_history','mesh_convergence'):
        if key in snapshot:chunks.append('<details><summary>Recorded '+escape(key.replace('_',' '))+'</summary><pre>'+escape(json.dumps(snapshot[key],indent=2))+'</pre></details>')
    evidence={'result':snapshot,'report_selections':{'probes':selected,'line_profile':line},'result_sha256':custody,'source_verified_at_export':bool(verify_source)}
    encoded=base64.b64encode(json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode()).decode()
    hashes=[('Source PCB bytes',snapshot['source']['sha256']),('Normalized configuration',snapshot['config_sha256']),('Complete result JSON (canonical)',custody)]
    for key in ('region_sha256',):
        if snapshot.get(key):hashes.append((key,snapshot[key]))
    if snapshot.get('import_source'):hashes.append(('Imported STEP bytes',snapshot['import_source']['sha256']))
    chunks.extend(['</section><section id="custody"><h2>Source and result custody</h2>',_table(['Identity','SHA-256'],hashes),
                   '<p><a class="download" download="quick-emerge-evidence.json" href="data:application/json;base64,'+encoded+'">Download complete JSON evidence</a></p>',
                   '<details><summary>Recorded evidence and selections</summary><pre>'+escape(json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2))+'</pre></details>',
                   '<p class="note">All report assets are embedded. No scripts or remote resources are required. These hashes identify recorded data; they do not authenticate the author or establish numerical accuracy.</p></section></main></body></html>'])
    validate_report_result(snapshot,expected_config=expected_config,expected_source=expected_source,verify_source=verify_source)
    if result_digest(original)!=custody:raise ValueError('Result changed during report generation')
    return ''.join(chunks)
