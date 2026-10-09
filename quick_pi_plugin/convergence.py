"""Bounded fixed-input refinement studies; stability is not measured accuracy."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path


def assess(samples, tolerance_percent=1., failure=None):
    tolerance=float(tolerance_percent)
    if not math.isfinite(tolerance) or not 0 < tolerance <= 20:
        raise ValueError('Convergence tolerance must be greater than 0 and at most 20 percent.')
    changes=[];balances=[];refined=True;sink_identity=None
    for index,row in enumerate(samples):
        required=('edge_mm','voltage_drop_V','resistance_ohm','power_W','sheet_power_W','current_A',
                  'current_error_A','nodal_error_A','energy_error','peak_J_A_mm2')
        if any(not isinstance(row.get(k),(float,int)) or isinstance(row.get(k),bool) or not math.isfinite(row[k]) for k in required):
            raise ValueError('Refinement samples need finite electrical and mesh metrics.')
        if any(row[k]<=0 for k in ('edge_mm','voltage_drop_V','resistance_ohm','power_W','current_A')):
            raise ValueError('Refinement samples need positive mesh size, current, drop, resistance and loss.')
        if any(row[k]<0 for k in ('current_error_A','nodal_error_A','energy_error','peak_J_A_mm2','sheet_power_W')):
            raise ValueError('Conservation errors and peak current density must be nonnegative.')
        balances.append(row['current_error_A']/row['current_A']<=1e-6 and row['nodal_error_A']/row['current_A']<=1e-6 and row['energy_error']<=1e-6)
        if any(isinstance(row.get(k),bool) or not isinstance(row.get(k),int) or row[k]<=0 for k in ('nodes','triangles')):
            raise ValueError('Refinement samples need positive integer node and triangle counts.')
        sink_rows=row.get('sinks')
        if sink_rows is not None:
            if not isinstance(sink_rows,list) or not sink_rows:
                raise ValueError('Refinement samples need a nonempty sink list.')
            if any(not isinstance(sink,dict) or not isinstance(sink.get('id'),str) or
                   any(isinstance(sink.get(key),bool) or not isinstance(sink.get(key),(int,float)) or
                       not math.isfinite(sink[key]) or sink[key]<=0 for key in ('current_A','voltage_drop_V'))
                   for sink in sink_rows):
                raise ValueError('Refinement sink currents and voltage drops must be finite and positive.')
            stamp=sorted((sink['id'],sink['current_A']) for sink in sink_rows)
            if len({key for key,_ in stamp})!=len(stamp):raise ValueError('Repeated refinement sink identity.')
            if sink_identity is not None and stamp!=sink_identity:raise ValueError('Sink identities or currents changed between meshes.')
            sink_identity=stamp
        if index and (sink_rows is None)!=(samples[index-1].get('sinks') is None):
            raise ValueError('Sink evidence changed between meshes.')
        if index:
            previous=samples[index-1]
            if not row['edge_mm']<previous['edge_mm']:raise ValueError('Mesh edge sizes must strictly decrease.')
            if not math.isclose(row['current_A'],previous['current_A'],rel_tol=1e-12):raise ValueError('Load current changed between meshes.')
            refined &= row['triangles']>previous['triangles'] and row['nodes']>previous['nodes']
            changes.append({key:100*abs(row[field]-previous[field])/max(abs(row[field]),1e-30)
                            for key,field in [('drop_percent','voltage_drop_V'),('resistance_percent','resistance_ohm'),('power_percent','power_W'),('sheet_power_percent','sheet_power_W'),('peak_J_percent','peak_J_A_mm2')]})
            if sink_rows is not None:
                previous_sinks={sink['id']:sink for sink in previous['sinks']}
                changes[-1]['sink_drop_percent']=max(100*abs(sink['voltage_drop_V']-previous_sinks[sink['id']]['voltage_drop_V'])/
                                                   max(abs(sink['voltage_drop_V']),1e-30) for sink in sink_rows)
    stable=(len(samples)>=3 and refined and all(balances) and
            all(c[key]<=tolerance for c in changes[-2:] for key in ('drop_percent','resistance_percent','power_percent','sheet_power_percent')) and
            all(c.get('sink_drop_percent',0)<=tolerance for c in changes[-2:]))
    status='INCOMPLETE' if failure or len(samples)<3 else 'BALANCE_FAILED' if not all(balances) else 'MESH_NOT_REFINED' if not refined else 'STABLE_WITHIN_TOLERANCE' if stable else 'NOT_STABLE'
    return {'schema':'wayricad.pi-convergence/v1','status':status,'tolerance_percent':tolerance,
            'samples':deepcopy(samples),'successive_changes':changes,'failure':failure,
            'terminal_drop_stable':stable and not failure,'peak_current_converged':False,
            'criteria':'At least three distinct successively finer meshes; both final refinement steps meet every sink drop, aggregate drop, resistance, total-power and copper-sheet-power tolerances; current/nodal/energy balance errors <= 1e-6.',
            'limitations':[
                'Observed stability of terminal quantities, not a rigorous error bound or measured PCB validation.',
                'Geometry, contacts, source/load, layer thickness, plating and material inputs are held fixed; their modeling and measurement errors are not covered.',
                'Peak current density and pulse/fusing risk remain unverified. Ideal contact edges and re-entrant corners can be singular; an unchanged terminal drop does not validate a local peak.',
                'Richardson/GCI is not inferred from nominal edge size: these unstructured meshes are not demonstrated to form an asymptotic, uniformly refined family.']}


def run_study(request, execute):
    levels=request.get('convergence_levels',4)
    if isinstance(levels,bool) or not isinstance(levels,int) or not 3<=levels<=5:
        raise ValueError('Choose 3 to 5 refinement levels.')
    tolerance=float(request.get('convergence_tolerance_percent',1.))
    assess([],tolerance)
    edge=float(request.get('edge_mm',.5))
    if not math.isfinite(edge) or edge<=0:raise ValueError('Starting mesh edge must be positive and finite.')
    base=deepcopy(request)
    for key in ('html_output','convergence_levels','convergence_tolerance_percent'):base.pop(key,None)
    base['action']='solve';samples=[];last=None;identity=None;failure=None
    for level in range(levels):
        current={**base,'edge_mm':edge/(2**level)}
        try:
            bundle=execute(current)
        except (ValueError,RuntimeError) as exc:
            if last is None:raise
            if hashlib.sha256(Path(base['board_path']).read_bytes()).hexdigest()!=identity[0]:
                raise ValueError('The board changed during refinement; discard the study.') from exc
            failure={'edge_mm':current['edge_mm'],'reason':str(exc)};break
        geometry=bundle['geometry'];stamp=(geometry.get('source_sha256'),geometry.get('geometry_sha256'))
        if not all(stamp):raise ValueError('A refinement study requires saved-board and geometry hashes.')
        if identity is not None and stamp!=identity:raise ValueError('Board or extracted geometry changed between meshes; no convergence result is valid.')
        identity=stamp;r=bundle['result'];m=bundle['mesh']
        samples.append(dict(edge_mm=current['edge_mm'],nodes=len(m['points_mm']),triangles=len(m['triangles']),
            voltage_drop_V=r['voltage_drop_V'],resistance_ohm=r['drop_over_current_ohm'],power_W=r['total_power_W'],
            sheet_power_W=r['planar_power_W'],current_A=r['sink_current_A'],current_error_A=r['current_balance_error_A'],
            nodal_error_A=r['max_nodal_residual_A'],energy_error=r['energy_relative_error'],peak_J_A_mm2=r['max_current_density_A_mm2']))
        if r.get('sinks'):
            samples[-1]['sinks']=[{key:sink[key] for key in ('id','current_A','voltage_drop_V')} for sink in r['sinks']]
        last=bundle
    if hashlib.sha256(Path(base['board_path']).read_bytes()).hexdigest()!=identity[0]:
        raise ValueError('The board changed during refinement; discard the study.')
    last['convergence']=assess(samples,tolerance,failure)
    last['convergence'].update(source_sha256=identity[0],geometry_sha256=identity[1],requested_levels=levels)
    return last


def summary(study):
    if not study:return 'Mesh convergence not verified.'
    state=study['status'].replace('_',' ').capitalize()
    changes=study.get('successive_changes',[])
    tail=f" Last drop change {changes[-1]['drop_percent']:.3g}%." if changes else ''
    return f"{state}: {len(study['samples'])} meshes, {study['tolerance_percent']:g}% tolerance.{tail} Peak current is not convergence-certified."


def html_section(study):
    from html import escape
    rows=''.join('<tr>'+''.join('<td>'+escape(f'{row[k]:.7g}')+'</td>' for k in ('edge_mm','triangles','voltage_drop_V','resistance_ohm','power_W','sheet_power_W','peak_J_A_mm2'))+'</tr>' for row in study['samples'])
    return '<h2>Fixed-input mesh refinement</h2><p>'+escape(summary(study))+'</p><p>'+escape(study['criteria'])+'</p><table><tr><th>Edge mm</th><th>Triangles</th><th>Drop V</th><th>R Ω</th><th>Loss W</th><th>Sheet loss W</th><th>Peak J A/mm²</th></tr>'+rows+'</table>'+('<p>Stopped: '+escape(str(study['failure']))+'</p>' if study.get('failure') else '')+'<ul>'+''.join('<li>'+escape(s)+'</li>' for s in study['limitations'])+'</ul>'
