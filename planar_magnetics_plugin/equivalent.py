"""Inspectable reduced magnetic equivalents; no field-extracted parasitic claim."""
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import math
from pathlib import Path
import uuid
from .magnetic_circuit import MU0, operating_point


def _positive(value, label, zero=False):
    value=float(value)
    if not math.isfinite(value) or value<0 or (not zero and value==0):
        raise ValueError(label+' must be finite and '+('nonnegative' if zero else 'positive'))
    return value


def equivalent(result, *, secondary_resistance_ohm=None, primary_capacitance_f=None,
               secondary_capacitance_f=None, interwinding_capacitance_f=None, coupling=None,
               actuator=None, field_model=None, primary_resistance_ohm=None, capacitance_evidence=None):
    """Build a DC-biased incremental equivalent from explicit inputs.

    k is a supplied model parameter, not estimated from leakage geometry. C is
    omitted unless explicitly supplied. Actuator uses constant reciprocal Bl.
    """
    spec,core=result.spec,result.core
    turns=spec.turns*(spec.layers if spec.layer_connection=='Series' else 1)
    point=operating_point(core,turns,0. if field_model else spec.current_a)
    if field_model is None and core.family!='Air' and not point['model_valid']:
        raise ValueError('Linear core model is saturated; provide supported B-H data before exporting.')
    lp=_positive(result.inductance_uh*1e-6,'Primary inductance')
    rp=_positive(result.resistance_dc_ohm if primary_resistance_ohm is None else primary_resistance_ohm,'Primary resistance',True)
    area=core.effective_area_mm2*1e-6;length=core.path_length_mm*1e-3;gap=core.gap_mm*1e-3
    b=point['flux_density_t']; flux=point['flux_wb']; mmf=turns*spec.current_a
    h=(mmf-b*gap/MU0)/length
    differential_reluctance=turns*turns/point['differential_inductance_h'] if point['differential_inductance_h'] else None
    secant=abs(mmf/flux) if flux else differential_reluctance
    data={'schema':'wayricad.magnetic-equivalent/v1','model':'reduced small-signal lumped equivalent',
          'bias_current_A':spec.current_a,'primary_turns':turns,'primary_Rdc_ohm':rp,'primary_L_H':lp,
          'primary_Rac_screen_ohm':result.resistance_ac_ohm,'Rac_screen_frequency_Hz':spec.frequency_khz*1000,
          'core':{'name':core.name,'B_T':b,'H_A_per_m':h,'flux_Wb':flux,'mean_path_m':length,
                  'effective_area_m2':area,'gap_m':gap,'gap_reluctance_A_per_Wb':gap/(MU0*area),
                  'secant_total_reluctance_A_per_Wb':secant,'differential_total_reluctance_A_per_Wb':differential_reluctance,
                  'saturation_threshold_T':core.saturation_t,'threshold_exceeded':point['saturation_threshold_exceeded']},
          'missing':[],'assumptions':['Rdc and L use generated-winding reduced models, not field extraction.',
              'SPICE uses incremental L at the specified DC bias; it does not reproduce saturation, hysteresis or core loss.',
              'AC resistance is a frequency-specific screening estimate and is not substituted into DC winding resistance.',
              'Capacitances and secondary resistance are explicit inputs, not inferred from heuristic winding estimates.']}
    if core.family=='Air':
        data['core']=None
        data['missing'].append('No effective closed core: H, mean magnetic path and reluctance are undefined for this open air winding model.')
    elif field_model is None:
        data['core']['secant_core_reluctance_A_per_Wb']=max(0.,secant-gap/(MU0*area))
        data['core']['differential_core_reluctance_A_per_Wb']=max(0.,differential_reluctance-gap/(MU0*area))
    for name,value in [('primary_C_F',primary_capacitance_f),('secondary_C_F',secondary_capacitance_f),('interwinding_C_F',interwinding_capacitance_f)]:
        data[name]=None if value is None else _positive(value,name,True)
    if capacitance_evidence:
        data['capacitance_evidence']={}
        for name,evidence in capacitance_evidence.items():
            if name not in ('primary_C_F','secondary_C_F','interwinding_C_F'):raise ValueError('Unknown capacitance evidence target.')
            expected=_positive(evidence['capacitance_F'],'Computed capacitance')
            if data[name] is not None and math.isclose(data[name],expected,rel_tol=1e-9):
                data['capacitance_evidence'][name]=evidence
        if data['capacitance_evidence']:
            data['assumptions'].append('Computed capacitance uses only the geometry, dielectric and explicit terminal-potential reduction recorded in capacitance_evidence; no arbitrary 3D extraction is claimed.')
    if primary_capacitance_f is None:data['missing'].append('Primary capacitance unknown; omitted from SPICE.')
    ls=result.secondary_inductance_uh*1e-6
    if field_model is not None:
        if primary_resistance_ohm is None:raise ValueError('Coaxial FEM geometry is independent: enter its primary Rdc explicitly.')
        matrix=field_model['L_matrix_H'];lp=_positive(matrix[0][0],'FEM primary L');ls=_positive(matrix[1][1],'FEM secondary L')
        mutual=float(matrix[0][1]);other=float(matrix[1][0])
        if not math.isfinite(mutual) or not math.isfinite(other) or not math.isclose(mutual,other,rel_tol=1e-7,abs_tol=1e-18):raise ValueError('FEM inductance matrix must be finite and reciprocal.')
        coupling=mutual/math.sqrt(lp*ls)
        data.update(primary_L_H=lp,core=None,primary_turns=field_model['primary_field']['spec']['turns'],bias_current_A=0.,model='linear coaxial magnetostatic FEM inductance with explicit lumped parasitics',
                    field_evidence=field_model.get('evidence',{}),field_geometry=field_model['primary_field']['spec'])
        data['assumptions']=['L and mutual inductance extracted from independent linear coaxial FEM geometry; not the displayed PCB winding.',
            'Primary and secondary winding resistance and capacitances are supplied; no conductor-loss or electrostatic extraction.',
            'Finite air boundary, discretization and constant permeability affect extracted inductance. Review convergence evidence.',
            'No nonlinear saturation, hysteresis, eddy currents or rotating motor model.']
        data['missing']=[item for item in data['missing'] if not item.startswith('No effective closed core')]
        data['secondary_field_geometry']=field_model.get('secondary_spec',field_model.get('evidence',{}).get('secondary'))
        field=field_model['primary_field']
        data['field_summary']={key:field.get(key) for key in ('peak_b_t','core_peak_b_t','axis_center_b_t','relative_residual','triangle_count')}
        data['field_summary']['excitation']=f"Primary {field['spec'].get('current_a',1.):g} A, secondary open; linear material"
        if field.get('br_t'):
            h_values=[math.hypot(br,bz)/(MU0*(field['spec'].get('core_mu_r',1.) if region==2 else 1.)) for br,bz,region in zip(field['br_t'],field['bz_t'],field['regions'])]
            data['field_summary']['peak_H_A_per_m']=max(h_values)
            core_h=[h for h,region in zip(h_values,field['regions']) if region==2]
            data['field_summary']['core_peak_H_A_per_m']=max(core_h) if core_h else None
        data.pop('primary_Rac_screen_ohm',None);data.pop('Rac_screen_frequency_Hz',None)
    if spec.secondary_turns or field_model is not None:
        ls=_positive(ls,'Secondary inductance');k=float(spec.coupling if coupling is None else coupling)
        if not math.isfinite(k) or abs(k)>=1:raise ValueError('Coupling must satisfy |k| < 1 for a strictly passive nonsingular inductance matrix.')
        rs=None if secondary_resistance_ohm is None else _positive(secondary_resistance_ohm,'Secondary resistance',True)
        mutual=k*math.sqrt(lp*ls)
        data.update(secondary_L_H=ls,secondary_Rdc_ohm=rs,k=k,mutual_H=mutual,
                    L_matrix_H=[[lp,mutual],[mutual,ls]],L_matrix_determinant_H2=lp*ls-mutual*mutual,
                    primary_short_circuit_leakage_H=lp*(1-k*k),secondary_short_circuit_leakage_H=ls*(1-k*k))
        data['coupling_origin']='linear coaxial FEM energy/mutual extraction' if field_model else 'user supplied'
        data['assumptions'].append('Leakage is the short-circuit equivalent L(1-k²), not a separate local field region.' if field_model else 'Leakage is the short-circuit equivalent L(1-k²) from supplied k; no geometry-derived leakage/coupling extraction is claimed.')
        if rs is None:data['missing'].append('Secondary Rdc required before transformer SPICE export.')
        if secondary_capacitance_f is None:data['missing'].append('Secondary capacitance unknown; omitted from SPICE.')
        if interwinding_capacitance_f is None:data['missing'].append('Interwinding capacitance unknown; omitted from SPICE.')
    elif secondary_capacitance_f is not None or interwinding_capacitance_f is not None:
        raise ValueError('Secondary/interwinding capacitance requires a secondary winding.')
    if actuator is not None:
        if spec.secondary_turns or field_model:raise ValueError('Moving-coil equivalent requires a single winding.')
        data['actuator']={key:_positive(actuator[key],key,key in ('damping_Ns_per_m','spring_N_per_m')) for key in ('Bl_N_per_A','mass_kg','damping_Ns_per_m','spring_N_per_m')}
        motion=actuator.get('motion_type','linear')
        if motion not in ('linear','rotary'):raise ValueError('Motion type must be linear or rotary.')
        data['actuator']['motion_type']=motion
        data['actuator']['units']=('Bl_N_per_A denotes Kt=Ke (N m/A = V s/rad); mass_kg denotes rotor J (kg m²); damping_Ns_per_m denotes b (N m s/rad); spring_N_per_m denotes torsional stiffness (N m/rad).' if motion=='rotary' else 'Bl N/A, mass kg, damping N s/m, spring N/m.')
        data['assumptions'].append('Moving-coil model uses constant Bl, reciprocal back EMF Bl*v, mass/damping/spring, small displacement and zero initial state. No rotating motor, stroke stop, friction or magnetic-position dependence.')
        if motion=='rotary':data['assumptions'][-1]='Explicit-parameter brushed DC motor equivalent: constant reciprocal Kt=Ke, rotor inertia, damping and optional torsional spring. No geometry-derived torque constant, commutation, cogging, BLDC phases or rotating-field solve.'
    cap=data.get('capacitance_evidence',{}).get('interwinding_C_F',{})
    if cap.get('maxwell_mapping'):
        if 'secondary_L_H' not in data:raise ValueError('Interwinding electrostatic mapping requires a secondary inductive winding.')
        data['environment_primary_C_F']=_positive(cap['primary_environment_F'],'Primary environment capacitance',True)
        data['environment_secondary_C_F']=_positive(cap['secondary_environment_F'],'Secondary environment capacitance',True)
        matrix=cap['C_matrix_F']
        if len(matrix)!=2 or any(len(row)!=2 for row in matrix) or any(not math.isfinite(v) for row in matrix for v in row):raise ValueError('Electrostatic evidence requires a finite 2x2 Maxwell matrix.')
        if not math.isclose(matrix[0][1],matrix[1][0],rel_tol=1e-7,abs_tol=1e-24) or matrix[0][0]<=0 or matrix[1][1]<=0 or matrix[0][0]*matrix[1][1]-matrix[0][1]*matrix[1][0]<=0:raise ValueError('Electrostatic matrix must be reciprocal and positive definite.')
        checks=[(cap['capacitance_F'],-matrix[0][1]),(cap['primary_environment_F'],sum(matrix[0])),(cap['secondary_environment_F'],sum(matrix[1]))]
        if any(not math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-24) for a,b in checks):raise ValueError('Capacitance branches do not reproduce the Maxwell matrix.')
        data['assumptions'].append('Electrostatic common-mode surrogate: each winding is equipotential at its dotted terminal P/S; outer grounded environment is tied to primary return N. Maxwell row sums add P–N and S–N capacitances. This is not a distributed turn-voltage extraction.')
    if data.get('capacitance_evidence'):
        data['assumptions']=[s for s in data['assumptions'] if s not in ('Capacitances and secondary resistance are explicit inputs, not inferred from heuristic winding estimates.','Primary and secondary winding resistance and capacitances are supplied; no conductor-loss or electrostatic extraction.')]
        data['assumptions'].append('Computed C follows the separately recorded dielectric, geometry and potential assumptions; other capacitances and winding resistances remain explicit inputs. Partial sidewall C excludes fringing and is not validated total winding capacitance.')
    return data


def spice(model):
    """Portable SPICE subcircuit; mechanical node velocity is numerically m/s."""
    def n(value):return format(value,'.12g')
    transformer='secondary_L_H' in model
    if transformer and model['secondary_Rdc_ohm'] is None:raise ValueError('Enter secondary Rdc before exporting transformer SPICE.')
    actuator=model.get('actuator')
    speed='OMEGA' if actuator and actuator['motion_type']=='rotary' else 'VEL'
    pins='P N S T' if transformer else 'P N '+speed if actuator else 'P N'
    lines=['* WayriCAD reduced magnetic equivalent; SI units; see companion JSON assumptions.',
           '* Incremental model at bias current '+n(model['bias_current_A'])+' A.',
           '.subckt WayriCADMagnetic '+pins,'Vsense P a 0','Rprimary a b '+n(max(model['primary_Rdc_ohm'],1e-15)),
           'Lprimary b '+('emf' if actuator else 'N')+' '+n(model['primary_L_H'])]
    if model['primary_Rdc_ohm']==0:lines.append('* Zero primary R represented by 1e-15 ohm numerical short.')
    if transformer:
        lines+=['Rsecondary S c '+n(max(model['secondary_Rdc_ohm'],1e-15)),
                'Lsecondary c T '+n(model['secondary_L_H']),
                'Kcoupling Lprimary Lsecondary '+n(model['k'])]
    for key,a,b in [('primary_C_F','P','N'),('secondary_C_F','S','T'),('interwinding_C_F','P','S')]:
        if model.get(key):lines.append('C'+key+' '+a+' '+b+' '+n(model[key]))
    for key,a,b in [('environment_primary_C_F','P','N'),('environment_secondary_C_F','S','N')]:
        if model.get(key):lines.append('C'+key+' '+a+' '+b+' '+n(model[key]))
    if actuator:
        lines+=['* Mechanical analogy: V(VEL)=velocity m/s; injected current=force N.',
                'Eback emf N VEL 0 '+n(actuator['Bl_N_per_A']),
                'Fforce 0 VEL Vsense '+n(actuator['Bl_N_per_A']),
                'Cmass VEL 0 '+n(actuator['mass_kg'])]
        if actuator['damping_Ns_per_m']:lines.append('Rdamping VEL 0 '+n(1/actuator['damping_Ns_per_m']))
        if actuator['spring_N_per_m']:lines.append('Lspring VEL 0 '+n(1/actuator['spring_N_per_m']))
        if actuator['motion_type']=='rotary':
            lines=[line.replace('VEL','OMEGA') for line in lines]
            lines=[line.replace('velocity m/s; injected current=force N.','angular speed rad/s; injected current=torque N m.') for line in lines]
    lines.append('.ends WayriCADMagnetic')
    return '\n'.join(lines)+'\n'


def export_bundle(model, board_path, directory=None, field_model=None, simulation=None, capacitance_fields=None):
    """Create a unique project-local bundle; never overwrite existing files."""
    source=Path(board_path).resolve()
    if not source.is_file():raise ValueError('Save the project board before exporting project-local reports.')
    folder=Path(directory).expanduser().resolve() if directory else source.parent/'reports'/'wayricad-magnetics'
    if directory is None and not folder.resolve().is_relative_to(source.parent):
        raise ValueError('Default report folder resolves outside the project; choose a local folder without a redirected link.')
    payload=dict(model,source={'board_path':str(source),'saved_board_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                              'context':'Generated winding settings; not extracted from existing board copper.'})
    netlist=spice(model)
    folder.mkdir(parents=True,exist_ok=True)
    stem='magnetics-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    folder=folder/stem;folder.mkdir()
    paths={extension:folder/('model.'+extension) for extension in ('json','cir','html')}
    text=json.dumps(payload,indent=2,allow_nan=False)
    warning=''.join('<li>'+escape(s)+'</li>' for s in model['assumptions']+model['missing'])
    diagram='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 135" role="img" aria-label="Primary series resistance and inductance"><path d="M30 60H150M310 60H430M630 60H770" fill="none" stroke="#345" stroke-width="3"/><rect x="150" y="35" width="160" height="50" fill="#f5e2bd" stroke="#345"/><rect x="430" y="35" width="200" height="50" fill="#d3eaf3" stroke="#345"/><g font-family="sans-serif" font-size="18" text-anchor="middle"><text x="230" y="65">Rdc '+escape(f"{model['primary_Rdc_ohm']:.5g}")+' Ω</text><text x="530" y="65">L '+escape(f"{model['primary_L_H']*1e6:.5g}")+' µH</text><text x="400" y="120">Incremental primary equivalent; see SPICE for coupling and explicit C</text></g></svg>'
    visual=''
    for name,field in (capacitance_fields or {}).items():
        if name not in model.get('capacitance_evidence',{}):continue
        filename='capacitance-'+name+'.json';paths[filename]=folder/filename
        with paths[filename].open('x',encoding='utf-8') as stream:json.dump(field,stream,allow_nan=False)
        points=field['vertices_m'];rmax=max(p[0] for p in points);zmax=max(abs(p[1]) for p in points);polygons=[]
        for tri in field['triangles']:
            value=max(0,min(1,sum(field['potential_V'][i] for i in tri)/3));color=f'rgb({round(25+220*value)},{round(55+160*value)},{round(170-120*value)})'
            coordinates=' '.join(f'{30+420*points[i][0]/rmax:.2f},{30+440*(zmax-points[i][1])/(2*zmax):.2f}' for i in tri)
            polygons.append(f'<polygon points="{coordinates}" fill="{color}"/>')
        visual+='<h2>Computed electrostatic potential</h2><p>Primary 1 V; secondary and grounded enclosure 0 V. Blue=0 V, yellow=1 V. Independent coaxial geometry, uniform dielectric. Full mesh/potential: '+escape(filename)+'.</p><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500">'+''.join(polygons)+'</svg>'
    if simulation:
        paths['simulation_json']=folder/'simulation.json'
        with paths['simulation_json'].open('x',encoding='utf-8') as stream:json.dump(simulation,stream,allow_nan=False,indent=2)
        visual+='<h2>Actual KiCad SPICE simulation</h2><p>'+escape(simulation['analysis']+' · '+simulation['limits'])+'</p>'
        if simulation.get('samples'):
            rows=simulation['samples'];xs=[math.log10(row['frequency_Hz']) for row in rows];ys=[math.log10(max(row['input_impedance_magnitude_ohm'],1e-30)) for row in rows];lo,hi=min(ys),max(ys)
            if hi-lo<1e-9:hi=lo+1
            points=' '.join(f'{55+700*(x-xs[0])/max(xs[-1]-xs[0],1e-30):.3f},{300-240*(y-lo)/(hi-lo):.3f}' for x,y in zip(xs,ys))
            visual+='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 360"><path d="M55 40V300H760" fill="none" stroke="#345"/><polyline points="'+points+'" fill="none" stroke="#208bb5" stroke-width="3"/><text x="55" y="25">Input impedance magnitude (ohm), logarithmic axes</text><text x="55" y="330">'+escape(f"{rows[0]['frequency_Hz']:g} → {rows[-1]['frequency_Hz']:g} Hz; |Z| {10**lo:.5g} → {10**hi:.5g} ohm")+'</text></svg>'
        else:visual+='<pre>'+escape(json.dumps({k:v for k,v in simulation.items() if k not in ('engine','netlist')},indent=2))+'</pre>'
        visual+='<p>Full complex vectors, engine provenance, generated deck and numerical results are saved in simulation.json.</p>'
    if field_model:
        field=field_model['primary_field'];points=field['vertices_m'];rmax=max(p[0] for p in points);zmax=max(abs(p[1]) for p in points)
        values=[math.hypot(br,bz) for br,bz in zip(field['br_t'],field['bz_t'])];peak=max(values)
        polygons=[]
        for tri,value in zip(field['triangles'],values):
            fraction=value/max(peak,1e-30);color=f'rgb({round(25+220*fraction)},{round(55+150*math.sqrt(fraction))},{round(160-100*fraction)})'
            coordinates=' '.join(f'{30+420*points[i][0]/rmax:.2f},{30+440*(zmax-points[i][1])/(2*zmax):.2f}' for i in tri)
            polygons.append(f'<polygon points="{coordinates}" fill="{color}"/>')
        visual+='<h2>Solved primary-excitation field</h2><p>Meridian r ≥ 0, z upward. |B| scale: dark blue 0 → yellow '+escape(f'{peak*1000:.5g}')+' mT. Secondary open; finite air boundary. Full mesh, B components and extraction evidence: field.json.</p><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500">'+''.join(polygons)+'</svg>'
        paths['field_json']=folder/'field.json'
        with paths['field_json'].open('x',encoding='utf-8') as stream:json.dump(field_model,stream,allow_nan=False)
    html='<!doctype html><meta charset="utf-8"><title>WayriCAD magnetic equivalent</title><style>body{font:16px system-ui;max-width:1050px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;background:#f3f5f7;padding:18px}</style><h1>Magnetic equivalent</h1><p>'+escape(str(source))+'</p>'+diagram+visual+'<ul>'+warning+'</ul><h2>Model and units</h2><pre>'+escape(text)+'</pre><h2>SPICE subcircuit</h2><pre>'+escape(netlist)+'</pre>'
    for extension,content in [('json',text),('cir',netlist),('html',html)]:
        with paths[extension].open('x',encoding='utf-8') as stream:stream.write(content)
    return {key:str(value) for key,value in paths.items()}

