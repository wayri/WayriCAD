"""Adiabatic copper melting screening; never fuse opening or clearing I²t.

d_m c_p(T) dT/dt = rho_e(T) J²; frozen DC current distribution,
constant density, piecewise-linear NIST copper Cp, linear rho(T).
"""
from __future__ import annotations
import heapq
import math

# NIST-JANAF Cu(cr), June 1977, J/(mol K); molar mass kg/mol.
_CP=((250.,23.782),(298.15,24.442),(300.,24.462),(350.,24.975),
     (400.,25.318),(450.,25.686),(500.,25.912),(600.,26.481),
     (700.,26.996),(800.,27.494),(900.,28.049),(1000.,28.662),
     (1100.,29.479),(1200.,30.519),(1300.,32.143),(1358.,33.353))
SOURCES=['https://janaf.nist.gov/tables/Cu-002.html',
         'https://janaf.nist.gov/tables/Cu-004.html',
         'https://arxiv.org/abs/1503.01279']
NOTICE=('Adiabatic melting screen, not fuse opening, clearing I²t or certified ampacity. '
        'No cooling, substrate heat flow, expansion, arcing or current redistribution. '
        'The linear resistivity law is an explicit high-temperature approximation; '
        'Cp is interpolated NIST pure-copper data. Local peaks depend on mesh and contacts. '
        'A DC imposed-current pattern is held fixed during heating; long predicted times are particularly affected by omitted cooling.')


def material_screen(material,thermal,options=None):
    options=options or {}
    def number(value,label,positive=False):
        if isinstance(value,bool):raise ValueError(label+' must be finite.')
        try:value=float(value)
        except (TypeError,ValueError) as exc:raise ValueError(label+' must be finite.') from exc
        if not math.isfinite(value) or (positive and value<=0):raise ValueError(label+' must be finite'+(' and positive.' if positive else '.'))
        return value
    initial=number(thermal['ambient_c'],'Initial copper temperature')
    melt=number(options.get('melting_temperature_c',1084.62),'Melting temperature')
    latent=number(options.get('latent_heat_J_kg',206750.),'Latent heat',True)
    if melt<=initial:raise ValueError('Melting temperature must exceed initial copper temperature.')
    density=number(thermal['density_kg_m3'],'Density',True)
    rho=number(material['resistivity_at_20C_ohm_m'],'Reference resistivity',True)
    alpha=number(material['temperature_coefficient'],'Resistivity temperature coefficient')
    out={'status':'available','model':'adiabatic temperature-dependent copper melting screen',
         'initial_temperature_c':initial,'melting_temperature_c':melt,'latent_heat_J_kg':latent,
         'density_kg_m3':density,'resistivity_at_20C_ohm_m':rho,'temperature_coefficient':alpha,
         'pulse_duration_s':thermal.get('pulse_duration_s'),'sources':SOURCES,'notice':NOTICE,
         'onset_action_A2s_mm4':None,'melt_action_A2s_mm4':None,
         'heat_capacity_model':'piecewise-linear NIST-JANAF Cu(cr), 250–1358 K; fixed molar mass 0.063546 kg/mol'}
    if not _CP[0][0]<=initial+273.15<melt+273.15<=_CP[-1][0]:
        out.update(status='unavailable',reason='Initial and melting temperatures must lie within the copper Cp table (250–1358 K).')
        return out
    if min(1+alpha*(initial-20),1+alpha*(melt-20))<=0:
        out.update(status='unavailable',reason='Declared linear resistivity becomes nonpositive before melting.')
        return out
    # Eight-point Gauss-Legendre integration on each linear-Cp interval. This
    # avoids cancellation in the analytic logarithmic form as alpha tends to 0.
    nodes=(.1834346424956498,.525532409916329,.7966664774136267,.9602898564975363)
    weights=(.362683783378362,.3137066458778873,.2223810344533745,.1012285362903763)
    integral=0.
    for (ta,ca),(tb,cb) in zip(_CP,_CP[1:]):
        lo=max(initial+273.15,ta);hi=min(melt+273.15,tb)
        if hi<=lo:continue
        ra=1+alpha*(lo-293.15);rb=1+alpha*(hi-293.15)
        if max(ra,rb)/min(ra,rb)>4:
            out.update(status='unavailable',reason='Resistivity varies too steeply within a Cp interval for the supported quadrature; review the declared temperature coefficient.')
            return out
        mid=(lo+hi)/2;half=(hi-lo)/2
        for node,weight in zip(nodes,weights):
            for sign in (-1,1):
                t=mid+sign*half*node
                cp=(ca+(cb-ca)*(t-ta)/(tb-ta))/.063546
                integral+=half*weight*cp/(rho*(1+alpha*(t-293.15)))
    onset=density*integral*1e-12
    out['onset_action_A2s_mm4']=onset
    out['melt_action_A2s_mm4']=onset+density*latent/(rho*(1+alpha*(melt-20)))*1e-12
    return out


def local_screen(model,density,cross_section=None):
    """Local J²t budget; None means unavailable, zero current has no finite time."""
    out={'time_to_onset_s':None,'time_to_melt_s':None,'pulse_melt_ratio':None,
         'i2t_to_melt_A2s':None,'cross_section_mm2':cross_section}
    if model.get('status')!='available' or density is None:return out
    if cross_section is not None:
        out['i2t_to_melt_A2s']=model['melt_action_A2s_mm4']*cross_section**2
    if density<=0:
        if model.get('pulse_duration_s') is not None:out['pulse_melt_ratio']=0.
        return out
    out['time_to_onset_s']=model['onset_action_A2s_mm4']/density**2
    out['time_to_melt_s']=model['melt_action_A2s_mm4']/density**2
    duration=model.get('pulse_duration_s')
    if duration is not None:out['pulse_melt_ratio']=duration/out['time_to_melt_s']
    return out


def summarize(mesh,result,options=None):
    model=material_screen(result['material'],result['thermal_assumptions'],options)
    geometry=mesh.get('geometry',{})
    names={str(row['id']):row.get('name',str(row['id'])) for row in geometry.get('layers',[])}
    # Spatial suppression keeps adjacent corner/contact triangles from filling
    # the whole list. This is local J region detection, not a geometric minimum
    # cut, ampacity calculation or proof that a native trace is the only path.
    points=mesh['points_mm'];span=max(max(p[k] for p in points)-min(p[k] for p in points) for k in (0,1))
    radius=max(.05,span/64)
    tiles={}
    for i,vector in enumerate(result['cell_J_A_mm2']):
        if vector is None:continue
        density=math.hypot(*vector);x,y=result['cell_centroid_mm'][i][:2]
        key=str(result['cell_layer'][i]),math.floor(x/radius),math.floor(y/radius)
        if key not in tiles or density>tiles[key][0]:tiles[key]=density,i
    cells=[]
    for density,i in heapq.nlargest(256,tiles.values()):
        x,y=result['cell_centroid_mm'][i][:2];layer=str(result['cell_layer'][i])
        if any(str(result['cell_layer'][j])==layer and math.dist((x,y),result['cell_centroid_mm'][j][:2])<2*radius for _,j in cells):continue
        cells.append((density,i))
        if len(cells)==12:break
    model['region_separation_mm']=2*radius
    model['ranking_basis']='Local J-based regions separated in board XY per layer; not geometric neck/minimum-cut detection. Corner/contact peaks require mesh refinement.'
    rows=[]
    for density,i in cells:
        layer=result['cell_layer'][i];location=result['cell_centroid_mm'][i]
        row={'kind':'sheet','id':i,'layer':layer,'layer_name':names.get(str(layer),str(layer)),
             'location_mm':location,'current_density_A_mm2':density,'source_ids':[],
             'section_basis':'mesh cell; a physical track cross-section has not been identified'}
        # Associate only explicit straight native tracks containing this cell's
        # centroid. A plane/arc-only cell keeps its section and track I²t unknown.
        candidates=[]
        for feature in geometry.get('mesh_features',[]):
            if feature.get('kind')!='track' or str(feature['layer'])!=str(layer):continue
            a,b=feature['start_mm'],feature['end_mm'];dx,dy=b[0]-a[0],b[1]-a[1]
            length2=dx*dx+dy*dy
            t=max(0.,min(1.,((location[0]-a[0])*dx+(location[1]-a[1])*dy)/length2)) if length2 else 0.
            if math.hypot(location[0]-a[0]-t*dx,location[1]-a[1]-t*dy)<=feature['width_mm']/2:
                candidates.append(feature)
        section=None
        if len(candidates)==1:
            feature=candidates[0];section=feature['width_mm']*mesh['triangle_thickness_mm'][i]
            row.update(source_ids=[feature['id']],nominal_track_width_mm=feature['width_mm'],
                       section_basis='nominal straight-track width × local solved copper thickness; local J, not integrated track current')
        row.update(local_screen(model,density,section));rows.append(row)
    metadata={str(v['id']):v for v in mesh.get('vias',[])}
    vias=heapq.nlargest(12,(v for v in result.get('vias',[]) if v.get('current_density_A_mm2') is not None),key=lambda v:v['current_density_A_mm2'])
    for via in vias:
        meta=metadata.get(str(via['id']),{});span=[meta.get('top_layer'),meta.get('bottom_layer')]
        points=[mesh['points_mm'][i] for name in ('top_nodes','bottom_nodes') for i in meta.get(name,[])]
        location=[sum(p[k] for p in points)/len(points) for k in range(3)] if points else None
        if location and 'x_mm' in meta:location[:2]=[meta['x_mm'],meta['y_mm']]
        section=via['volume_mm3']/meta['length_mm'] if meta.get('length_mm',0)>0 else None
        row={'kind':'via','id':via['id'],'layer':span,'layer_name':' → '.join(names.get(str(l),str(l)) for l in span),
             'location_mm':location,'current_density_A_mm2':via['current_density_A_mm2'],
             'current_A':via.get('current_A'),'source_ids':[],
             'section_basis':'actual solved axial barrel metal area; uniform axial current density'}
        row.update(local_screen(model,via['current_density_A_mm2'],section));rows.append(row)
    rows.sort(key=lambda row:(row['time_to_melt_s'] is None,row['time_to_melt_s'] or math.inf))
    model['bottlenecks']=[dict(row,rank=i+1) for i,row in enumerate(rows)]
    return model


def rescale(model,factor):
    import copy
    out=copy.deepcopy(model)
    for row in out.get('bottlenecks',[]):
        row['current_density_A_mm2']*=factor
        if row.get('current_A') is not None:row['current_A']*=factor
        for field in ('time_to_onset_s','time_to_melt_s'):
            if row.get(field) is not None:row[field]/=factor**2
        if row.get('pulse_melt_ratio') is not None:row['pulse_melt_ratio']*=factor**2
    return out


def details_text(model):
    if not model:return 'Copper melting screening unavailable for this model.'
    lines=['COPPER MELTING / BOTTLENECK SCREEN',model['notice']]
    if model.get('reason'):lines.append(model['reason'])
    for row in model.get('bottlenecks',[]):
        text=f"{row['rank']}. {row['kind']} {row['id']} | {row['layer_name']} | J {row['current_density_A_mm2']:.5g} A/mm²"
        for key,label,unit in [('time_to_onset_s','onset','s'),('time_to_melt_s','full melt','s'),('i2t_to_melt_A2s','nominal melting I²t','A²s'),('pulse_melt_ratio','pulse/melting action','')]:
            text+=' | '+label+' '+('Unknown' if row.get(key) is None else f'{row[key]:.6g} {unit}')
        lines.extend([text,row['section_basis']])
    return '\n'.join(lines)
