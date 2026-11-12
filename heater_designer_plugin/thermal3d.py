"""Explicit rectilinear solid studies for generated single-foil heaters.

The raster is a discretized conductor, not an exact curved/bent foil CAD model.
Automatic studies reject under-resolved gaps and multilayer via approximations.
"""
from dataclasses import asdict
import hashlib
import json
import math

from .materials import MATERIALS


def construction_layers(form, width_mm, substrate_k=.3, conductor_um=35.):
    """Illustrative constructions, never inferred from a PCB or a material name."""
    foil = dict(name='Heater foil', role='heater', thickness_mm=conductor_um/1000)
    if form == 'free foil': return [foil]
    if form == 'rigid':
        return [dict(name='Reviewed rigid substrate', role='substrate', thickness_mm=1.6,
                     thermal_conductivity_w_mk=substrate_k), foil]
    if form == 'flex':
        return [dict(name='Reviewed flexible substrate', role='substrate', thickness_mm=.125,
                     thermal_conductivity_w_mk=substrate_k), foil]
    if form == 'rigid-flex':
        return [dict(name='Continuous flexible substrate', role='substrate', thickness_mm=.125,
                     thermal_conductivity_w_mk=substrate_k), foil,
                dict(name='Right-half stiffener (illustrative)', role='substrate', thickness_mm=1.475,
                     thermal_conductivity_w_mk=substrate_k, region_mm=[width_mm/2, 0, width_mm, None])]
    raise ValueError('Choose rigid, flex, rigid-flex or free foil; films use their actual substrate construction.')


def build_study(heater, config):
    """Create a standalone 3D request with source geometry and assumptions bound.

    Conductor thermal conductivity and optional Seebeck coefficient are explicit
    user inputs. A sheet resistor needs physical film thickness as well as R/sq.
    A rigid-flex construction may contain local rectangular substrate regions;
    it does not model mechanical bending, adhesives or contact resistance.
    """
    import numpy as np
    spec = heater.spec
    if spec.layers != 1 or heater.vias:
        raise ValueError('Automatic 3D heater meshing currently requires one foil layer without vias. Use an explicit 3D solid study for vertical conductors.')
    dx, dy = float(config['cell_mm']), float(config.get('cell_y_mm', config['cell_mm']))
    smallest = min(segment.width_mm for segment in heater.segments)
    if not all(math.isfinite(v) and v > 0 for v in (dx, dy)):
        raise ValueError('3D cell dimensions must be positive and finite.')
    aligned = config.get('mesh_mode','auto') != 'uniform' and all(
        abs(row.x2_mm-row.x1_mm)<1e-10 or abs(row.y2_mm-row.y1_mm)<1e-10 for row in heater.segments)
    if spec.spacing_mm <= 0 or (not aligned and max(dx, dy) > min(smallest, spec.spacing_mm)/2 + 1e-12):
        raise ValueError('Resolve both the narrowest strip and gap with at least two cells. Refine the mesh; do not bridge gaps with a coarse preview.')
    layers=config['layers']
    if not isinstance(layers,list) or not layers or len(layers)>64 or any(not isinstance(row,dict) for row in layers) or sum(row.get('role')=='heater' for row in layers)!=1:
        raise ValueError('Provide explicit construction layers containing exactly one heater foil.')
    ratios=(spec.width_mm/dx,spec.height_mm/dy)
    if any(not math.isfinite(value) or value>50000 for value in ratios) or math.ceil(ratios[0])*math.ceil(ratios[1])*len(layers)>50000:
        raise ValueError('3D study exceeds the bounded 50,000-cell budget before allocation.')
    def axis_edges(axis,length,maximum):
        if not aligned:return np.linspace(0,length,math.ceil(length/maximum)+1)
        seeds={0.,length}
        for layer in layers:
            region=layer.get('region_mm')
            if region is not None:
                if not isinstance(region,list) or len(region)!=4:raise ValueError('A local region needs four millimetre bounds.')
                for value in (region[0],region[2]) if axis=='x' else (region[1],region[3]):
                    if value is not None:
                        if not math.isfinite(float(value)):raise ValueError('Region bounds must be finite.')
                        seeds.add(round(max(0.,min(length,float(value))),9))
        for row in heater.segments:
            for value in (getattr(row,axis+'1_mm'),getattr(row,axis+'2_mm')):
                seeds.update(round(max(0.,min(length,value+offset)),9) for offset in (-row.width_mm/2,0.,row.width_mm/2))
        seeds=sorted(seeds);edges=[seeds[0]]
        for start,end in zip(seeds,seeds[1:]):
            count=max(1,math.ceil((end-start)/maximum))
            if len(edges)+count>50001:raise ValueError('Geometry-aligned axis exceeds the cell budget.')
            edges.extend(start+(end-start)*i/count for i in range(1,count+1))
        return np.asarray(edges)
    xe,ye=axis_edges('x',spec.width_mm,dx),axis_edges('y',spec.height_mm,dy)
    nx,ny=len(xe)-1,len(ye)-1
    if nx*ny*len(layers) > 50000:
        raise ValueError('3D study exceeds 50,000 cells. Reduce the study envelope or revise the pattern; coarse shorted geometry is not silently substituted.')
    x, y = np.meshgrid((xe[:-1]+xe[1:])/2, (ye[:-1]+ye[1:])/2)
    metal = np.zeros((ny,nx),dtype=bool)
    for segment in heater.segments:
        vx, vy = segment.x2_mm-segment.x1_mm, segment.y2_mm-segment.y1_mm
        length2 = vx*vx+vy*vy
        if length2 <= 0: continue
        fraction = np.clip(((x-segment.x1_mm)*vx+(y-segment.y1_mm)*vy)/length2, 0, 1)
        covered = (x-(segment.x1_mm+fraction*vx))**2+(y-(segment.y1_mm+fraction*vy))**2 <= (segment.width_mm/2)**2
        if not covered.any(): raise ValueError('A conductor segment disappeared from the mesh; refine the grid.')
        metal |= covered
    foil_thickness = float(next(row['thickness_mm'] for row in layers if row.get('role') == 'heater'))
    if not math.isfinite(foil_thickness) or foil_thickness <= 0: raise ValueError('Physical foil/film thickness must be positive.')
    material = spec.material
    rho = (material.resistivity_ohm_m if material.resistivity_ohm_m is not None
           else material.sheet_resistance_ohm_sq*foil_thickness*1e-3)
    k = config['conductor_k_w_mk']
    conductor = dict(thermal_conductivity_w_mk=k, resistivity_ohm_m=rho,
                     reference_c=material.reference_c)
    if material.temperature_factors: conductor['temperature_factors'] = [list(row) for row in material.temperature_factors]
    elif material.tcr_per_k is not None: conductor['tcr_per_k'] = material.tcr_per_k
    elif config.get('constant_resistivity_reviewed') is not True:
        raise ValueError('This alloy/film has no unique temperature correction. Supply measured data or explicitly review a constant-resistivity assumption.')
    if 'seebeck_v_k' in config:
        if not str(config.get('seebeck_reference_note','')).strip():
            raise ValueError('Record the Seebeck reference/lead material; an alloy name does not define a thermocouple.')
        conductor['seebeck_v_k'] = config['seebeck_v_k']
    if material.tcr_range_c is not None:conductor['material_temperature_range_c']=list(material.tcr_range_c)
    materials, ids, ze = {'conductor': conductor}, [], [0.]
    foil_index = None
    for iz, layer in enumerate(layers):
        thickness = float(layer['thickness_mm'])
        if not math.isfinite(thickness) or thickness <= 0: raise ValueError('Construction thicknesses must be positive.')
        ze.append(ze[-1]+thickness)
        if layer.get('role') == 'heater':
            foil_index = iz
            ids.extend(['conductor' if value else None for value in metal.ravel()])
        else:
            name = 'substrate-'+str(iz)
            materials[name] = dict(thermal_conductivity_w_mk=layer['thermal_conductivity_w_mk'])
            region = layer.get('region_mm', [0,0,spec.width_mm,spec.height_mm])
            if len(region) != 4: raise ValueError('A local substrate region requires [xmin,ymin,xmax,ymax] millimetres.')
            a,b,c,d = region; d=spec.height_mm if d is None else d
            if not all(math.isfinite(float(v)) for v in (a,b,c,d)) or c <= a or d <= b:
                raise ValueError('Local substrate regions must have finite positive area.')
            mask = (x>=a)&(x<=c)&(y>=b)&(y<=d)
            ids.extend([name if value else None for value in mask.ravel()])
    active = np.flatnonzero(metal.ravel())
    if len(active) < 2: raise ValueError('The resolved conductor needs distinct terminal cells.')
    points = np.column_stack((x.ravel()[active], y.ravel()[active]))
    start, end = heater.segments[0], heater.segments[-1]
    terminal = [int(active[np.argmin(np.sum((points-np.array(point))**2,axis=1))])+foil_index*nx*ny
                for point in ((start.x1_mm,start.y1_mm),(end.x2_mm,end.y2_mm))]
    if terminal[0] == terminal[1]: raise ValueError('Mesh terminals coincide; refine the grid or change the contact geometry.')
    geometry = dict(spec=asdict(spec), segments=[asdict(row) for row in heater.segments], construction=layers)
    binding = hashlib.sha256(json.dumps(geometry,sort_keys=True,allow_nan=False).encode()).hexdigest()
    settings=dict(config.get('settings',{}));settings.setdefault('max_cells',50000)
    return dict(schema_version=1, grid=dict(edges_mm=dict(x=xe.tolist(),y=ye.tolist(),z=ze)),
                materials=materials, material_ids=ids,
                fixed_voltage_v={str(terminal[0]):spec.voltage_v,str(terminal[1]):0.},
                fixed_temperature_c=config.get('fixed_temperature_c',{}),
                boundary=dict(config.get('boundary',{})), settings=settings,
                provenance=dict(source_kind='generated-heater',geometry_sha256=binding,
                    material=asdict(material),nominal_centerline_resistance_ohm=heater.resistance_ohm,
                    seebeck_reference_note=config.get('seebeck_reference_note','Not supplied; thermoelectric terms disabled.'),
                    constant_resistivity_reviewed=config.get('constant_resistivity_reviewed',False),
                    construction=layers, mesh_shape=[nx,ny,len(layers)],mesh_mode='geometry-aligned' if aligned else 'uniform',
                    assumptions=['Cell-centred voxel staircase geometry; mesh refinement is required.',
                                 'Ideal single-cell electrical contacts; no contact resistance.',
                                 'No mechanical bend strain, adhesive or fabrication-tolerance inference.',
                                 'Film resistivity derives from reviewed sheet resistance and physical thickness.']))


def solve_study(heater, config, cancel=None):
    from wayricad_runtime.thermoelectric_study import run_study
    request = build_study(heater, config)
    return run_study(request, cancel=cancel)


def main(argv=None):
    from wayricad_runtime.thermoelectric_study import cli
    return cli(argv)


if __name__=='__main__':raise SystemExit(main())
