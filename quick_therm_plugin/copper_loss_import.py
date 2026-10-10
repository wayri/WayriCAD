"""Conservative, source-bound import of Quick PI 2.5D conductor losses.

This imports one computed operating point. It does not re-solve currents during
thermal playback; Quick PI's electrothermal tool owns temperature feedback.
"""
import math
from collections.abc import Mapping


def _number(value,label):
    if isinstance(value,bool):raise ValueError(label+' must be a finite nonnegative number.')
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):raise ValueError(label+' must be a finite nonnegative number.') from None
    if not math.isfinite(value) or value<0:raise ValueError(label+' must be a finite nonnegative number.')
    return value


def import_losses(bundle,source_sha256):
    if not isinstance(bundle,Mapping):raise ValueError('Choose a Quick PI JSON report.')
    if bundle.get('electrothermal'):
        bundle=bundle['electrothermal']
    if bundle.get('mode')=='steady_electrothermal':
        if not bundle.get('converged'):raise ValueError('Electrothermal report must have converged.')
        mesh,result=bundle.get('mesh'),bundle.get('hot')
        binding=bundle.get('bindings',{}).get('source_sha256')
        layers=(bundle.get('thermal') or {}).get('layers',[])
    else:
        mesh,result=bundle.get('mesh'),bundle.get('result')
        geometry=bundle.get('geometry') or {}
        binding=geometry.get('source_sha256',bundle.get('source_sha256'))
        layers=geometry.get('layers',[])
    if not binding or binding!=source_sha256:
        raise ValueError('Quick PI losses must come from the exact saved PCB loaded in QuickTherm. Re-run PI after board changes.')
    if not isinstance(mesh,Mapping) or not isinstance(result,Mapping) or not str(result.get('model','')).startswith('2.5D'):
        raise ValueError('Import a solved 2.5D DC Quick PI report; sweeps and tetrahedral 3D fields need a separate transfer model.')
    if result.get('feasibility',{}).get('operating_point_valid') is not True:
        raise ValueError('Quick PI operating point must be feasible before its losses can heat the board.')
    triangles=mesh.get('triangles',[]);powers=result.get('cell_power_W',[]);cell_layers=result.get('cell_layer',[])
    if not triangles or len(triangles)!=len(powers) or len(triangles)!=len(cell_layers):
        raise ValueError('PI mesh and cell losses are incomplete.')
    points=mesh.get('points_mm',[]);sources=[]
    thicknesses=mesh.get('triangle_thickness_mm',[])
    if len(thicknesses)!=len(triangles):raise ValueError('PI triangle thicknesses are incomplete.')
    # Older electrothermal fields omit thickness, but the source-bound electrical
    # mesh exports it explicitly for every triangle. Require a consistent value
    # for each declared layer; never substitute a nominal copper thickness.
    measured={}
    for layer,raw in zip(cell_layers,thicknesses):
        value=_number(raw,'PI copper thickness')
        if value<=0:raise ValueError('PI copper thickness must be positive.')
        if layer in measured and not math.isclose(value,measured[layer],rel_tol=1e-6,abs_tol=1e-9):
            raise ValueError('PI triangles disagree on copper layer thickness.')
        measured[layer]=value
    layers=[dict(row) for row in layers]
    for row in layers:
        if 'thickness_mm' not in row:
            if row['id'] not in measured:
                raise ValueError('PI report has no explicit thickness for a declared copper layer. Export a complete 2.5D mesh.')
            row['thickness_mm']=measured[row['id']]
    layer_map={row['id']:row for row in layers}
    for index,(triangle,power,layer) in enumerate(zip(triangles,powers,cell_layers)):
        if power is None:continue  # Disconnected/unexcited copper has no computed loss.
        watts=_number(power,'Triangle loss')
        if watts==0:continue
        if len(triangle)!=3 or any(isinstance(i,bool) or not isinstance(i,int) or i<0 or i>=len(points) for i in triangle):
            raise ValueError('PI triangle indices are invalid.')
        polygon=[list(points[i][:2]) for i in triangle]
        if any(len(p)!=2 or any(not math.isfinite(float(v)) for v in p) for p in polygon):
            raise ValueError('PI triangle geometry must be finite XY millimetres.')
        declared=layer_map.get(layer)
        if not declared or not math.isclose(float(thicknesses[index]),float(declared['thickness_mm']),rel_tol=1e-6,abs_tol=1e-9) or any(
                len(points[i])<3 or not math.isclose(float(points[i][2]),float(declared['z_mm']),abs_tol=1e-6) for i in triangle):
            raise ValueError('PI triangle depth/thickness disagrees with its declared copper layer.')
        sources.append({'id':'copper:triangle:'+str(index),'layer_id':layer,'polygon_mm':polygon,'power_w':watts})
    vias=mesh.get('vias',[]);losses=result.get('vias',[])
    if len(vias)!=len(losses):raise ValueError('PI barrel losses are incomplete.')
    for index,(via,loss) in enumerate(zip(vias,losses)):
        if str(via.get('id'))!=str(loss.get('id')):raise ValueError('PI barrel identities disagree.')
        if loss.get('power_W') is None:continue
        watts=_number(loss['power_W'],'Barrel loss')
        if watts==0:continue
        source=str(via['id']);base=source.rsplit(':',1)[0]
        if 'top_layer' not in via or 'bottom_layer' not in via:raise ValueError('PI barrel segment has no explicit layer span.')
        sources.append({'id':'copper:via:'+source,'barrel_id':base,'top_layer':via['top_layer'],
                        'bottom_layer':via['bottom_layer'],'power_w':watts})
    total=math.fsum(row['power_w'] for row in sources)
    expected=_number(result.get('conductor_power_W'),'PI conductor power')
    if not math.isclose(total,expected,rel_tol=1e-8,abs_tol=1e-10):
        raise ValueError('PI conductor energy balance does not match the imported planar and barrel losses.')
    if len(sources)>50000:raise ValueError('Loss transfer exceeds 50,000 sources; use a smaller PI mesh.')
    package_losses=[]
    from wayricad_runtime.package_conduction import normalize_paths
    for contact in result.get('package_contacts',[]):
        definition=normalize_paths([contact.get('definition')],physics='electrical')[0]
        watts=_number(contact.get('power_W'),'Package contact loss')
        current=contact.get('current_A')
        if isinstance(current,bool) or current is None or not math.isfinite(float(current)):
            raise ValueError('Package contact current must be known before thermal transfer.')
        if not math.isclose(float(current)**2*definition['electrical_resistance_ohm'],watts,rel_tol=1e-8,abs_tol=1e-10):
            raise ValueError('PI package contact current/resistance/heat disagree.')
        package_losses.append({'id':definition['definition']['id'],'definition':definition['definition'],
                               'current_a':float(current),'power_w':watts})
    if not math.isclose(math.fsum(row['power_w'] for row in package_losses),
                        _number(result.get('package_power_W',0),'PI package power'),rel_tol=1e-8,abs_tol=1e-10):
        raise ValueError('PI package contact energy balance is incomplete.')
    return {'sources':sources,'source_sha256':binding,'input_w':total,
            'package_joule_losses':package_losses,
            'package_joule_input_w':math.fsum(row['power_w'] for row in package_losses),
            'component_power_excluded_w':_number(result.get('component_power_W',0),'PI component power'),
            'layers':[{key:row[key] for key in ('id','z_mm','thickness_mm')} for row in layers],
            'meaning':'Imported fixed-operating-point conductor I²R heat; package contact I²R is separate and needs matching thermal paths. Component/load power is separate; no current re-solve during playback.'}


def validate_layer_binding(binding,geometry):
    actual={row['id']:row for row in geometry['layers']}
    if not binding.get('layers'):raise ValueError('PI loss transfer needs explicit saved layer depths and thicknesses.')
    for row in binding['layers']:
        if row['id'] not in actual or any(not math.isclose(float(row[key]),float(actual[row['id']][key]),rel_tol=1e-6,abs_tol=1e-6)
                                        for key in ('z_mm','thickness_mm')):
            raise ValueError('PI and QuickTherm layer stackups disagree; regenerate the PI report.')
