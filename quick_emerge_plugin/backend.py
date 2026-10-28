"""EMerge 3 adapter. Only this worker imports the solver."""
from __future__ import annotations

import importlib.metadata
import json
import math
from .advanced import check_mesh_budget
import os
from pathlib import Path
import tempfile

from .model import config_digest, source_identity, validate_config
from .advanced import (configure_solver, dielectric, assign_conductor, conductor_boundaries,
                       air_region, outer_boundary, field_payload, physics_assumptions)


SUPPORTED_VERSION = '3.0.0b9'
UPSTREAM_REVISION = '446232037d175a596606c6c9ea986e372560566f'


def atomic_json(path, value):
    path = Path(path)
    # Unique temporary names also avoid collisions between worker and UI writes.
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, allow_nan=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def runtime_info(*, qualifying=False):
    try:
        version = importlib.metadata.version('emerge')
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeError(f'EMerge is missing from the selected solver Python. Configure Python 3.10â€“3.13 with emerge=={SUPPORTED_VERSION}.') from None
    from packaging.version import Version
    from .compatibility import runtime_certificate
    import sys
    if Version(version).major < 3:
        raise RuntimeError(f'Quick EMerge requires EMerge 3+ (tested baseline {SUPPORTED_VERSION}); selected environment has {version}.')
    certificate = runtime_certificate(sys.prefix)
    if version != SUPPORTED_VERSION and not qualifying and (not certificate or certificate['version'] != version):
        raise RuntimeError(f'EMerge {version} has not passed compatibility checks for this plugin. Use dependency setup to qualify an isolated runtime (baseline {SUPPORTED_VERSION}).')
    return {'backend': 'EMerge', 'version': version, 'adapter_revision': UPSTREAM_REVISION}


def build_geometry(em, np, c):
    """Dimensions cross the millimetre-to-metre boundary exactly once."""
    mm = 0.001
    model = em.Simulation('QuickEMerge')
    configure_solver(em, model, c)
    material = dielectric(em, c)
    sx, sy, th = (c[k] * mm for k in ('substrate_x_mm', 'substrate_y_mm', 'thickness_mm'))
    port_height = th
    vias = []
    if c['advanced']['study'] == 'array':
        from .advanced_studies import build_array_geometry
        return build_array_geometry(em, np, c)
    if c['mode'] == 'patch':
        em.geo.Box(sx, sy, th, position=(-sx/2, -sy/2, -th)).set_material(material)
        w, length, feed, slot, inset = (c[k] * mm for k in (
            'patch_width_mm', 'patch_length_mm', 'feed_width_mm', 'inset_width_mm', 'inset_length_mm'))
        offset_y = c['advanced']['patch_offset_y_mm'] * mm
        patch_y = offset_y - length/2
        patch = em.geo.XYPlate(w, length, position=(-w/2, patch_y, 0))
        for x in (-feed/2-slot, feed/2):
            cutout = em.geo.XYPlate(slot, inset, position=(x, patch_y, 0))
            patch = em.geo.remove(patch, cutout)
        extension = c['advanced']['patch_feed_extension_mm'] * mm
        feed_y = patch_y - extension
        if extension:
            # Public EMerge union yields one continuous patch/feed surface.
            feedline = em.geo.XYPlate(feed, extension, position=(-feed/2, feed_y, 0))
            patch = em.geo.add(patch, feedline)
        assign_conductor(em, patch, c)
        ports = [em.geo.Plate(np.array([-feed/2, feed_y, -th]),
                             np.array([feed, 0, 0]), np.array([0, 0, th]))]
        conductor = patch
        widths = [feed]
    else:
        # EMerge 3 PCB takes layer indices, not the old z= routing argument.
        multilayer = c['advanced']['line_geometry'] == 'stripline_via'
        if multilayer:
            port_height = th/3
        pcb = em.geo.PCB(c['thickness_mm'], unit=mm, material=material,
                            trace_material=em.lib.PEC if c['advanced']['conductor'] == 'pec' else em.lib.AIR, layers=4 if multilayer else 2)
        length, width = c['line_length_mm'], c['line_width_mm']
        route = pcb.new(-length/2, 0, width, (1, 0), trace_layer=1).store('in')
        if multilayer:
            radius = c['advanced']['via_radius_mm']
            route.straight(length/4).via(2, radius, extra=0).straight(length/2).via(1, radius, extra=0).straight(length/4).store('out')
            vias = pcb.generate_vias(False, material=em.lib.PEC)
        else:
            route.straight(length).store('out')
        conductor = pcb.compile_paths(True)
        pcb.set_bounds(-c['substrate_x_mm']/2, -c['substrate_y_mm']/2,
                       c['substrate_x_mm']/2, c['substrate_y_mm']/2)
        pcb.generate_pcb()
        # Explicit sheets avoid creating an automatic PCB port attribute and
        # then registering a duplicate boundary condition. Preserve user Z0.
        ports = [em.geo.Plate(np.array([x*mm, -width*mm/2, -th]),
                              np.array([0, width*mm, 0]), np.array([0, 0, port_height]))
                 for x in (-length/2, length/2)]
        widths = [width*mm, width*mm]
    ground = assign_conductor(em, em.geo.XYPlate(sx, sy, position=(-sx/2, -sy/2, -th)), c)
    model._quick_conductors = [conductor, ground]
    if c['mode'] == 'pcb_line' and c['advanced']['line_geometry'] == 'stripline_via':
        model._quick_conductors.append(assign_conductor(em, em.geo.XYPlate(sx, sy, position=(-sx/2, -sy/2, 0)), c))
    model._quick_shunt = None
    if c['advanced']['shunt_component'] != 'none':
        model._quick_shunt = em.geo.Plate(np.array([0, -c['line_width_mm']*mm/2, -th]),
                                         np.array([0, c['line_width_mm']*mm, 0]), np.array([0, 0, th]))
    air = air_region(em, c, sx, sy, th, -sx/2, -sy/2)
    model.mw.set_resolution(c['resolution'])
    model.mw.set_frequency_range(c['f_start_hz'], c['f_stop_hz'], c['points'])
    model.commit_geometry()
    model.mesher.set_boundary_size(conductor, c['mesh_edge_mm']*mm)
    for via in vias:
        model.mesher.set_boundary_size(via, c['advanced']['via_radius_mm']*mm)
    if model._quick_shunt is not None:
        model.mesher.set_face_size(model._quick_shunt, min(c['line_width_mm']*mm, th)/2)
    for port, width in zip(ports, widths):
        model.mesher.set_face_size(port, min(width, th)/2)
    return model, air, ports, widths, port_height


def solve(config, progress=print, *, qualifying=False, region=None, export_context=None):
    info = runtime_info(qualifying=qualifying)
    import numpy as np
    import emerge as em
    c = validate_config(config)
    if c['advanced']['export_dxf'] or c['advanced']['export_optycal']:
        if not export_context:
            raise ValueError('Live exports require a reviewed run directory and originating source; use the study session')
        from .advanced_exports import require_export_dependencies
        require_export_dependencies(c)
    if c['advanced']['study'] not in ('driven', 'array'):
        from .advanced_studies import solve_advanced
        return solve_advanced(em, np, c, info, progress, region, qualifying)
    if c['mode'] == 'pcb_region':
        from .region_backend import build_region
        progress('Building actual saved copper clipped to the reviewed rule-area enclosure.', flush=True)
        model, air, ports, widths, thickness, bbox = build_region(em, np, c, region)
    else:
        progress('Building reviewed template geometry (not imported KiCad copper).', flush=True)
        model, air, ports, widths, thickness = build_geometry(em, np, c)
        bbox = [-c['substrate_x_mm']/2, -c['substrate_y_mm']/2, c['substrate_x_mm']/2, c['substrate_y_mm']/2]
    progress('Generating finite-element mesh.', flush=True)
    model.generate_mesh()
    check_mesh_budget(model, c)
    for i, (port, width) in enumerate(zip(ports, widths), 1):
        model.mw.bc.LumpedPort(port, i, width=width, height=thickness,
                               direction=em.ZAX, Z0=c['z0_ohm'])
    if getattr(model, '_quick_shunt', None) is not None:
        from .advanced import element_impedance
        a = c['advanced']
        model.mw.bc.LumpedElement(model._quick_shunt, impedance_function=lambda f: element_impedance(a['shunt_component'], a['shunt_value'], f), width=c['line_width_mm']*.001, height=thickness)
    conductor_boundaries(em, model, model._quick_conductors, c)
    boundary = outer_boundary(model, air, c)
    if c['adaptive_steps']:
        progress('Running adaptive mesh refinement (inspect convergence evidence in solver log).', flush=True)
        model.adaptive_mesh_refinement(max_steps=c['adaptive_steps'], convergence=c['convergence'],
                                       max_tets=c['max_tets'], frequency=(c['f_start_hz']+c['f_stop_hz'])/2,
                                       show_mesh=False)
    progress('Solving frequency sweep.', flush=True)
    if c['sweep'] == 'adaptive':
        data = model.mw.run_adaptive_sweep(n_initial=min(5, c['points']),
                                          max_samples=c['points'], tol=c['convergence'])
    else:
        data = model.mw.run_sweep()
    frequencies = np.asarray(data.scalar.grid.freq).reshape(-1)
    ordering = np.argsort(frequencies)
    frequencies = frequencies[ordering]
    s = {}
    for excitation in range(1, len(ports)+1):
        for port in range(1, len(ports)+1):
            values = np.asarray(data.scalar.grid.S(port, excitation)).reshape(-1)[ordering]
            s[f'S{port}{excitation}'] = [[float(v.real), float(v.imag)] for v in values]
    frequency = float(frequencies[len(frequencies)//2])
    field = data.field.find(freq=frequency)
    if c['advanced']['study'] == 'array':
        a = c['advanced']
        weights = [np.sqrt(a['array_power_w']/len(ports))*np.exp(1j*np.deg2rad(ix*a['array_phase_x_deg']+iy*a['array_phase_y_deg'])) for iy in range(a['array_count_y']) for ix in range(a['array_count_x'])]
        field.set_excitations(*weights)
    progress('Sampling near field and radiation.', flush=True)
    fields = field_payload(np, field, frequency, bbox, c)
    result = {'schema': 1, 'backend': info, 'model_scope': 'parametric-template',
              'config': c, 'config_sha256': config_digest(c),
              'frequencies_hz': frequencies.tolist(), 's_parameters': s,
              'field': fields, 'assumptions': physics_assumptions(c)}
    result['port_count'] = len(ports)
    if c['advanced']['study'] == 'array':
        result['model_scope'] = 'finite-patch-array-template'
        result['array'] = dict(port_centers_mm=model._quick_array_centers, incident_power_w=c['advanced']['array_power_w'], excitation_weights=[[float(w.real),float(w.imag)] for w in weights])
        result['scene_geometry'] = dict(kind='patch_array', unit='mm', centers_mm=model._quick_array_centers, patch_size=[c['patch_width_mm'],c['patch_length_mm']], substrate_size=[c['substrate_x_mm'],c['substrate_y_mm']], thickness=c['thickness_mm'])
        result['field']['excitation'] = 'Coherent finite array, weights and total incident power recorded in array metadata'
        result['assumptions'].append('Finite common-ground patch array; full mutual S coupling included; incident power is not accepted or radiated power')
    if c['mode'] == 'pcb_line' and c['advanced']['line_geometry'] == 'stripline_via':
        result['model_scope'] = 'four-layer-via-template'
        result['scene_geometry'] = dict(kind='stripline_via', unit='mm', bounds=[-c['substrate_x_mm']/2,-c['substrate_y_mm']/2,-c['thickness_mm'],c['substrate_x_mm']/2,c['substrate_y_mm']/2,0], trace_width=c['line_width_mm'], line_length=c['line_length_mm'], layer_z_mm=[-c['thickness_mm'],-2*c['thickness_mm']/3,-c['thickness_mm']/3,0], via_radius=c['advanced']['via_radius_mm'], via_x_mm=[-c['line_length_mm']/4,c['line_length_mm']/4])
        result['assumptions'].append('Four conductor levels, two ideal solid PEC internal vias; not an imported multilayer PCB or plated-barrel model')
    if c['advanced']['shunt_component'] != 'none':
        result['assumptions'].append('Ideal typed shunt '+c['advanced']['shunt_component']+' sheet at line center; no component package parasitics')
    if c['mode'] == 'pcb_region':
        from .region_backend import region_digest
        result.update(model_scope='saved-rule-area-copper', region=region, region_sha256=region_digest(region))
        result['assumptions'][-1] = 'Polygon-clipped saved two-layer copper; ideal boundary ports; external PCB and components omitted'
    if c['advanced']['boundary'] in ('absorbing', 'pml') and (c['mode'] == 'patch' or (c['mode'] == 'pcb_region' and len(ports) == 1)):
        theta = np.linspace(0, np.pi, 31)
        phi = np.linspace(-np.pi, np.pi, 61)
        ff = field.farfield_3d(boundary, thetas=theta, phis=phi,
                              origin=((bbox[0]+bbox[2])*.0005, (bbox[1]+bbox[3])*.0005, -thickness/2))
        norm = ff.E.norm
        if c['advanced']['study'] == 'array':
            per_port = field.farfield_3d_ports(boundary, thetas=theta, phis=phi, origin=((bbox[0]+bbox[2])*.0005,(bbox[1]+bbox[3])*.0005,-thickness/2))
            reference = sum(weight*np.asarray([per_port[i].Ex,per_port[i].Ey,per_port[i].Ez]) for i,weight in enumerate(weights,1))
            combined = np.asarray([ff.Ex,ff.Ey,ff.Ez])
            result['array']['superposition_relative_error'] = float(np.max(np.abs(reference-combined))/max(float(np.max(np.abs(reference))),1e-30))
            result['assumptions'].append('Pattern null depth requires mesh and air-boundary convergence; coherent superposition is separately checked against individual port fields')
        result['radiation'] = {'frequency_hz': frequency, 'theta_rad': theta.tolist(),
                               'phi_rad': phi.tolist(), 'norm_e': norm.tolist(),
                               'quantity': 'Far-field |E|; relative pattern, not gain or efficiency'}
    if c['advanced']['export_dxf'] or c['advanced']['export_optycal']:
        from .advanced_exports import export_live_outputs
        result['exports'] = export_live_outputs(model,data,c,boundary,export_context['run_dir'],export_context['source'],config_digest(c))
    if c['advanced']['coupled_thermal']:
        from .advanced_studies import solve_thermal
        thermal_result = solve_thermal(em, np, c, info, progress, region, em_field=field, port_count=len(ports))
        result['thermal'] = thermal_result['thermal']
        result['assumptions'].extend(thermal_result['assumptions'])
    return result


def run_request(request_path, *, qualifying=False):
    request_path = Path(request_path).resolve()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    config = validate_config(request['config'])
    if config_digest(config) != request['config_sha256']:
        raise ValueError('Setup changed after review; prepare a new run.')
    if source_identity(request['source']['path']) != request['source']:
        raise ValueError('Originating PCB changed; reopen/review setup before solving.')
    region = request.get('region')
    export_context = dict(run_dir=request_path.parent, source=request['source'])
    if config['mode'] == 'pcb_region':
        from .region_backend import region_digest, validate_region
        validate_region(region, config)
        if region_digest(region) != request.get('region_sha256') or region['source'] != request['source']:
            raise ValueError('Region geometry or source changed after review.')
        result = solve(config, region=region, export_context=export_context, qualifying=qualifying)
    else:
        result = solve(config, export_context=export_context, qualifying=qualifying)
    if source_identity(request['source']['path']) != request['source']:
        raise ValueError('PCB changed during simulation; result cannot be associated with its reviewed context.')
    result['source'] = request['source']
    json.dumps(result, allow_nan=False)
    write_touchstone(request_path.parent, result)
    if result.get('exports'):
        from .advanced_exports import publish_exports
        publish_exports(request_path.parent, result['exports'])
    # Publication happens only after the entire result is finite and serializable.
    atomic_json(request_path.parent/'result.json', result)
    return result


def write_touchstone(directory, result):
    """Export Touchstone: classic 2-port column order, N>=3 row order."""
    count = result.get('port_count', 1 if result['config']['mode'] == 'patch' else 2)
    if not count:
        return None
    impedance = result.get('reference_impedance_ohm', result['config']['z0_ohm'])
    lines = ['! Quick EMerge study; inspect result.json geometry scope and assumptions',
             f'# Hz S RI R {impedance:g}']
    for index, frequency in enumerate(result['frequencies_hz']):
        row = [f'{frequency:.17g}']
        pairs = [(response, excitation) for excitation in range(1,count+1) for response in range(1,count+1)] if count == 2 else [(response, excitation) for response in range(1,count+1) for excitation in range(1,count+1)]
        for response, excitation in pairs:
            pair = result['s_parameters'][f'S{response}{excitation}'][index]
            if not all(math.isfinite(v) for v in pair):
                raise ValueError('Non-finite S-parameter cannot be exported.')
            row.extend(f'{v:.17g}' for v in pair)
        lines.append(' '.join(row))
    destination = Path(directory)/f'network.s{count}p'
    destination.write_text('\n'.join(lines)+'\n', encoding='utf-8')
