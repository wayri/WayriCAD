"""EMerge 3 adapter. Only this worker imports the solver."""
from __future__ import annotations

import importlib.metadata
import json
import math
import os
from pathlib import Path
import tempfile

from .model import config_digest, source_identity, validate_config


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
        raise RuntimeError(f'EMerge is missing from the selected solver Python. Configure Python 3.10–3.13 with emerge=={SUPPORTED_VERSION}.') from None
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
    model.set_solver(em.EMSolver[c['solver']])
    material = em.Material(er=c['er'], color='#268568', opacity=0.35)
    sx, sy, th = (c[k] * mm for k in ('substrate_x_mm', 'substrate_y_mm', 'thickness_mm'))
    if c['mode'] == 'patch':
        em.geo.Box(sx, sy, th, position=(-sx/2, -sy/2, -th)).set_material(material)
        w, length, feed, slot, inset = (c[k] * mm for k in (
            'patch_width_mm', 'patch_length_mm', 'feed_width_mm', 'inset_width_mm', 'inset_length_mm'))
        patch = em.geo.XYPlate(w, length, position=(-w/2, -length/2, 0))
        for x in (-feed/2-slot, feed/2):
            cutout = em.geo.XYPlate(slot, inset, position=(x, -length/2, 0))
            patch = em.geo.remove(patch, cutout)
        patch.set_material(em.lib.PEC)
        ports = [em.geo.Plate(np.array([-feed/2, -length/2, -th]),
                             np.array([feed, 0, 0]), np.array([0, 0, th]))]
        conductor = patch
        widths = [feed]
    else:
        # EMerge 3 PCB takes layer indices, not the old z= routing argument.
        pcb = em.geo.PCB(c['thickness_mm'], unit=mm, material=material,
                            trace_material=em.lib.PEC, layers=2)
        length, width = c['line_length_mm'], c['line_width_mm']
        pcb.new(-length/2, 0, width, (1, 0), trace_layer=1).store('in').straight(length).store('out')
        conductor = pcb.compile_paths(True)
        pcb.set_bounds(-c['substrate_x_mm']/2, -c['substrate_y_mm']/2,
                       c['substrate_x_mm']/2, c['substrate_y_mm']/2)
        pcb.generate_pcb()
        # Explicit sheets avoid creating an automatic PCB port attribute and
        # then registering a duplicate boundary condition. Preserve user Z0.
        ports = [em.geo.Plate(np.array([x*mm, -width*mm/2, -th]),
                              np.array([0, width*mm, 0]), np.array([0, 0, th]))
                 for x in (-length/2, length/2)]
        widths = [width*mm, width*mm]
    em.geo.XYPlate(sx, sy, position=(-sx/2, -sy/2, -th)).set_material(em.lib.PEC)
    margin = c['air_margin_mm']*mm
    air = em.geo.Box(sx+2*margin, sy+2*margin, th+2*margin,
                     position=(-sx/2-margin, -sy/2-margin, -th-margin)).background()
    model.mw.set_resolution(c['resolution'])
    model.mw.set_frequency_range(c['f_start_hz'], c['f_stop_hz'], c['points'])
    model.commit_geometry()
    model.mesher.set_boundary_size(conductor, c['mesh_edge_mm']*mm)
    for port, width in zip(ports, widths):
        model.mesher.set_face_size(port, min(width, th)/2)
    return model, air, ports, widths, th


def solve(config, progress=print, *, qualifying=False, region=None):
    info = runtime_info(qualifying=qualifying)
    import numpy as np
    import emerge as em
    c = validate_config(config)
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
    for i, (port, width) in enumerate(zip(ports, widths), 1):
        model.mw.bc.LumpedPort(port, i, width=width, height=thickness,
                               direction=em.ZAX, Z0=c['z0_ohm'])
    boundary = air.boundary()
    model.mw.bc.AbsorbingBoundary(boundary)
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
    progress('Sampling near field and radiation.', flush=True)
    xs = np.linspace(bbox[0], bbox[2], c['field_grid'])
    ys = np.linspace(bbox[1], bbox[3], c['field_grid'])
    x, y = np.meshgrid(xs, ys)
    z = np.full(x.shape, c['field_z_mm'])
    sampled = field.interpolate(x*0.001, y*0.001, z*0.001)
    magnitude = np.linalg.norm(sampled.E, axis=0)
    # Outside-mesh samples are unknown, never replaced by zero.
    magnitude = [[float(v) if math.isfinite(v) else None for v in row] for row in magnitude]
    result = {'schema': 1, 'backend': info, 'model_scope': 'parametric-template',
              'config': c, 'config_sha256': config_digest(c),
              'frequencies_hz': frequencies.tolist(), 's_parameters': s,
              'field': {'frequency_hz': frequency, 'z_mm': c['field_z_mm'],
                        'x_mm': xs.tolist(), 'y_mm': ys.tolist(), 'norm_e_v_m': magnitude},
              'assumptions': ['PEC conductors', 'Real, nondispersive dielectric; no loss tangent',
                              'First-order absorbing air boundary', 'No convergence qualification',
                              'Template geometry; originating PCB is context only']}
    result['port_count'] = len(ports)
    if c['mode'] == 'pcb_region':
        from .region_backend import region_digest
        result.update(model_scope='saved-rule-area-copper', region=region, region_sha256=region_digest(region))
        result['assumptions'][-1] = 'Polygon-clipped saved two-layer copper; ideal boundary ports; external PCB and components omitted'
    if c['mode'] == 'patch' or (c['mode'] == 'pcb_region' and len(ports) == 1):
        theta = np.linspace(0, np.pi, 31)
        phi = np.linspace(-np.pi, np.pi, 61)
        ff = field.farfield_3d(boundary, thetas=theta, phis=phi,
                              origin=((bbox[0]+bbox[2])*.0005, (bbox[1]+bbox[3])*.0005, -thickness/2))
        norm = ff.E.norm
        result['radiation'] = {'frequency_hz': frequency, 'theta_rad': theta.tolist(),
                               'phi_rad': phi.tolist(), 'norm_e': norm.tolist(),
                               'quantity': 'Far-field |E|; relative pattern, not gain or efficiency'}
    return result


def run_request(request_path):
    request_path = Path(request_path).resolve()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    config = validate_config(request['config'])
    if config_digest(config) != request['config_sha256']:
        raise ValueError('Setup changed after review; prepare a new run.')
    if source_identity(request['source']['path']) != request['source']:
        raise ValueError('Originating PCB changed; reopen/review setup before solving.')
    region = request.get('region')
    if config['mode'] == 'pcb_region':
        from .region_backend import region_digest, validate_region
        validate_region(region, config)
        if region_digest(region) != request.get('region_sha256') or region['source'] != request['source']:
            raise ValueError('Region geometry or source changed after review.')
        result = solve(config, region=region)
    else:
        result = solve(config)
    if source_identity(request['source']['path']) != request['source']:
        raise ValueError('PCB changed during simulation; result cannot be associated with its reviewed context.')
    result['source'] = request['source']
    write_touchstone(request_path.parent, result)
    # Publication happens only after the entire result is finite and serializable.
    atomic_json(request_path.parent/'result.json', result)
    return result


def write_touchstone(directory, result):
    """Export actual solved samples in standard port-major Touchstone order."""
    count = result.get('port_count', 1 if result['config']['mode'] == 'patch' else 2)
    lines = ['! Quick EMerge study; inspect result.json geometry scope and assumptions',
             f'# Hz S RI R {result["config"]["z0_ohm"]:g}']
    for index, frequency in enumerate(result['frequencies_hz']):
        row = [f'{frequency:.17g}']
        for excitation in range(1, count+1):
            for response in range(1, count+1):
                pair = result['s_parameters'][f'S{response}{excitation}'][index]
                if not all(math.isfinite(v) for v in pair):
                    raise ValueError('Non-finite S-parameter cannot be exported.')
                row.extend(f'{v:.17g}' for v in pair)
        lines.append(' '.join(row))
    destination = Path(directory)/f'network.s{count}p'
    destination.write_text('\n'.join(lines)+'\n', encoding='utf-8')
