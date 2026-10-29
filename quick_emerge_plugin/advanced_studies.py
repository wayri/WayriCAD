"""Executable advanced EMerge studies with bounded geometry and provenance."""
import math
from .advanced import check_mesh_budget

from .advanced import (configure_solver, dielectric, assign_conductor,
                       conductor_boundaries, field_payload, verify_step)
from .model import config_digest, validate_config


def _base(c, info, scope, assumptions):
    return dict(schema=1, backend=info, model_scope=scope, config=c,
                config_sha256=config_digest(c), assumptions=assumptions,
                port_count=0, s_parameters={}, frequencies_hz=[])


def _frequencies(np, c):
    return np.linspace(c['f_start_hz'], c['f_stop_hz'], c['points'])


def _network(np, data, count):
    frequencies = np.asarray(data.scalar.grid.freq).reshape(-1)
    order = np.argsort(frequencies)
    values = {}
    for i in range(1, count+1):
        for j in range(1, count+1):
            v = np.asarray(data.scalar.grid.S(i, j)).reshape(-1)[order]
            if not np.all(np.isfinite(v)):
                raise ValueError('Advanced study returned nonfinite network samples')
            values[f'S{i}{j}'] = np.stack((v.real, v.imag), axis=-1).tolist()
    return frequencies[order].tolist(), values


def solve_periodic(em, np, c, info, progress):
    a = c['advanced']
    model = em.Simulation('QuickEMergePeriodic')
    configure_solver(em, model, c)
    sx, sy, th, margin = (c[k]*.001 for k in ('substrate_x_mm', 'substrate_y_mm', 'thickness_mm', 'air_margin_mm'))
    cell = em.RectCell(sx, sy)
    model.set_periodic_cell(cell)
    cell.volume(-th, 0).set_material(dielectric(em, c))
    cell.volume(-th-margin, margin).background()
    w, length = c['patch_width_mm']*.001, c['patch_length_mm']*.001
    patch = assign_conductor(em, em.geo.XYPlate(w, length, position=(-w/2, -length/2, 0)), c)
    top, bottom = cell.port_face(margin), cell.port_face(-th-margin)
    model.mw.set_resolution(c['resolution'])
    model.mw.set_frequency_range(c['f_start_hz'], c['f_stop_hz'], c['points'])
    model.commit_geometry()
    model.mesher.set_boundary_size(patch, c['mesh_edge_mm']*.001)
    progress('Meshing periodic patch cell with paired side faces and two Floquet ports.', flush=True)
    model.generate_mesh()
    check_mesh_budget(model, c)
    p1 = model.mw.bc.floquet_port(top, 1)
    p2 = model.mw.bc.floquet_port(bottom, 2)
    p1.set_polarization(a['polarization_deg'])
    p2.set_polarization(a['polarization_deg'])
    cell.set_scanangle(a['scan_theta_deg'], a['scan_phi_deg'])
    conductor_boundaries(em, model, [patch], c)
    data = model.mw.run_sweep()
    result = _base(c, info, 'periodic-patch-template', [
        'Infinite rectangular array of identical patches; no finite-array edge effects',
        'Two fundamental Floquet modes; higher diffraction orders are not reported',
        'No convergence qualification; originating PCB is context only'])
    result['frequencies_hz'], result['s_parameters'] = _network(np, data, 2)
    result['port_count'] = 2
    # Floquet ports use the free-space wave impedance, not the lumped Z0 input.
    result['reference_impedance_ohm'] = float(em.lib.Z0)
    frequency = result['frequencies_hz'][len(result['frequencies_hz'])//2]
    result['field'] = field_payload(np, data.field.find(freq=frequency), frequency, [-sx*500, -sy*500, sx*500, sy*500], c)
    result['scene_geometry'] = dict(kind='periodic_patch', unit='mm', cell_size=[sx*1000, sy*1000],
                                    patch_size=[w*1000, length*1000], thickness=th*1000,
                                    z_bounds=[(-th-margin)*1000, margin*1000])
    return result


def solve_scattering(em, np, c, info, progress):
    a = c['advanced']
    imported = None
    if a['import_kind'] != 'none':
        from .advanced_imports import verify_import
        identity = verify_import(a)
    else:
        identity = verify_step(a) if a['step_path'] else None
    model = em.Simulation('QuickEMergeScattering')
    configure_solver(em, model, c)
    if a['import_kind'] != 'none':
        from .advanced_imports import build_import
        imported = build_import(em, a)
        scatterers = imported['objects']
        identity = imported['identity']
    elif identity:
        items = em.geo.STEPItems('Scatterer', identity['path'], unit=a['step_unit_m'])
        if not items.volumes or len(items.volumes) > 100:
            raise ValueError('STEP scattering requires between 1 and 100 solid volumes')
        for volume in items.volumes:
            volume.set_material(em.lib.PEC)
        scatterers = items.volumes
    else:
        scatterers = [em.geo.Sphere(a['scatter_radius_mm']*.001).set_material(em.lib.PEC)]
    x0, x1, y0, y1, z0, z1 = [float(v) for v in em.geo.bounding_box()]
    if max(x1-x0, y1-y0, z1-z0) > 2:
        raise ValueError('Scatterer exceeds 2 m; inspect imported STEP units')
    margin = c['air_margin_mm']*.001
    air = em.geo.open_region(margin, margin, margin)
    model.mw.set_resolution(c['resolution'])
    model.mw.set_frequency_range(c['f_start_hz'], c['f_stop_hz'], c['points'])
    model.commit_geometry()
    for item in scatterers:
        model.mesher.set_boundary_size(item, c['mesh_edge_mm']*.001)
    progress('Meshing PEC scatterer and applying a plane-wave excitation.', flush=True)
    model.generate_mesh()
    check_mesh_budget(model, c)
    boundary = air.boundary()
    excitation = model.mw.bc.ScatteredField(boundary, power_density=a['incident_power_w_m2'], definition='SPH')
    excitation.set_excitations(a['scan_theta_deg'], a['scan_phi_deg'], a['polarization_deg'])
    data = model.mw.run_scattered()
    frequencies = _frequencies(np, c)
    frequency = float(frequencies[len(frequencies)//2])
    field = data.field.find(freq=frequency)
    result = _base(c, info, imported['scope'] if imported else ('step-pec-scattering' if identity else 'pec-sphere-scattering'), [
        'PEC scatterer in air; first-order scattered-field outer boundary',
        'Incident angles use the upstream standard spherical convention in degrees',
        'Bistatic RCS at the middle solved frequency; no convergence qualification',
        'Imported STEP materials/components are replaced by PEC' if identity else 'Sphere template; originating PCB is context only'])
    if imported:
        result['assumptions'] = imported['assumptions'] + ['Scattered field from imported geometry with reviewed materials; no driven network ports', 'No convergence qualification']
    result['frequencies_hz'] = frequencies.tolist()
    result['field'] = field_payload(np, field, frequency, [x0*1000, y0*1000, x1*1000, y1*1000], c)
    theta, phi = np.linspace(0, np.pi, 31), np.linspace(-np.pi, np.pi, 61)
    ff = field.relative.farfield_3d(boundary, thetas=theta, phis=phi,
                                   origin=((x0+x1)/2, (y0+y1)/2, (z0+z1)/2))
    norm = np.asarray(ff.E.norm)
    # Far-field E is normalized to r=1 m. sigma = 4*pi*r^2*|Es|^2/|Ei|^2.
    rcs = 4*np.pi*norm**2/(2*float(em.lib.Z0)*a['incident_power_w_m2'])
    if not np.all(np.isfinite(rcs)):
        raise ValueError('Scattering result contains nonfinite RCS samples')
    result['radiation'] = dict(frequency_hz=frequency, theta_rad=theta.tolist(), phi_rad=phi.tolist(),
                               norm_e=norm.tolist(), quantity='Scattered far-field |E| at 1 m')
    result['scattering'] = dict(frequency_hz=frequency, theta_rad=theta.tolist(), phi_rad=phi.tolist(),
                                rcs_m2=rcs.tolist(), incident_power_w_m2=a['incident_power_w_m2'])
    result['scene_geometry'] = dict(kind='step' if identity else 'sphere', unit='mm',
                                    bounds=[v*1000 for v in (x0, y0, z0, x1, y1, z1)],
                                    radius=a['scatter_radius_mm'] if not identity else None)
    if identity:
        tags = [tag for obj in scatterers for tag in (obj.boundary().tags if obj.dim == 3 else obj.tags)]
        skin = model.mesh.boundary_surface(tags)
        if skin.tris.shape[1] <= 20000:
            result['scene_geometry']['vertices_mm'] = (skin.nodes.T*1000).tolist()
            result['scene_geometry']['triangles'] = skin.tris.T.tolist()
        else:
            result['scene_geometry']['preview_warning'] = 'Surface mesh exceeds the 20,000-triangle display budget; exact bounds only.'
        result['import_source'] = identity
        if imported:
            from .advanced_imports import verify_import
            verify_import(a)
        else:
            verify_step(a)
    return result


def _area(shape):
    def ring_area(ring):
        return abs(sum(p[0]*q[1]-q[0]*p[1] for p, q in zip(ring, ring[1:]+ring[:1])))/2
    return ring_area(shape['outer_mm'])-sum(ring_area(r) for r in shape.get('holes_mm', []))


def solve_thermal(em, np, c, info, progress, region=None, em_field=None, port_count=1):
    a = c['advanced']
    model = em.Simulation('QuickEMergeThermal')
    model.set_physics(microwave=False, heatconduction=True)
    configure_solver(em, model, c)
    model.hc.solveroutine.set_solver(em.EMSolver[c['solver']])
    material = em.Material(cond_thermal=a['thermal_conductivity_w_mk'],
                           density=a['density_kg_m3'], specific_heat=a['specific_heat_j_kgk'])
    if c['mode'] == 'pcb_region':
        from .region_backend import _surface, validate_region
        region, bbox = validate_region(region, c)
        thickness = region['substrate']['thickness_mm']*.001
        shapes = region['substrate']['outline']
        solids = [em.geo.extrude(_surface(em, shape, 0), dz=-thickness).set_material(material) for shape in shapes]
        area = sum(_area(s) for s in shapes)*1e-6
    else:
        sx, sy, thickness = (c[k]*.001 for k in ('substrate_x_mm', 'substrate_y_mm', 'thickness_mm'))
        solids = [em.geo.Box(sx, sy, thickness, position=(-sx/2, -sy/2, -thickness)).set_material(material)]
        bbox, area = [-sx*500, -sy*500, sx*500, sy*500], sx*sy
    model.commit_geometry()
    for solid in solids:
        model.mesher.set_domain_size(solid, c['mesh_edge_mm']*.001)
    # Mesh settings above, not microwave wavelength, define the thermal mesh.
    progress('Solving substrate heat conduction with fixed bottom and adiabatic sides/top.', flush=True)
    model.generate_mesh()
    check_mesh_budget(model, c)
    bottom = model.select.inplane(0, 0, -thickness, em.ZAX)
    model.hc.bc.FixedTemperatureBoundary(bottom, a['ambient_k'])
    qv = a['thermal_power_w']/(area*thickness)
    for solid in solids:
        if em_field is not None:
            model.hc.bc.CoupledEMHeating(solid, em_field, excitation_W=[a['rf_input_power_w']]+[0.]*(port_count-1))
        else:
            model.hc.bc.HeatFluxVolume(solid, heatflux=qv)
    model.hc.set_initial_temperature(a['ambient_k'])
    if a['thermal_time_s']:
        from .advanced_thermal import run_transient
        data, transient = run_transient(model.hc, a['thermal_time_s'], a['thermal_step_s'], a['solver_threads'])
        thermal_field = data.field.find(time=a['thermal_time_s'])
    else:
        data = model.hc.run_steady_state(nthreads=a['solver_threads'])
        thermal_field = data.field.find()
    xs = np.linspace(bbox[0], bbox[2], c['field_grid'])
    ys = np.linspace(bbox[1], bbox[3], c['field_grid'])
    x, y = np.meshgrid(xs, ys)
    # Sample just inside the top face, including holes as unknown.
    sample_z_m = -thickness*1e-6
    sampled = thermal_field.interpolate(x*.001, y*.001, np.full(x.shape, sample_z_m))
    temperatures = np.asarray(sampled.T)
    valid = temperatures[np.isfinite(temperatures)]
    if not valid.size:
        raise ValueError('Thermal study contains no finite interior temperature samples')
    result = _base(c, info, 'saved-rule-area-substrate-thermal' if region else 'substrate-thermal-template', [
        'Uniform volumetric heat source; bottom fixed temperature; sides and top adiabatic',
        'Substrate only: copper, vias, components and radiation/convection are omitted',
        'Thermal power is an explicit input, not inferred from RF loss',
        'No mesh/time convergence qualification'])
    values = [[float(v) if math.isfinite(v) else None for v in row] for row in temperatures]
    result['thermal'] = dict(temperature_k=values, x_mm=xs.tolist(), y_mm=ys.tolist(),
                             z_mm=sample_z_m*1000, peak_k=float(valid.max()),
                             reference_peak_k=a['ambient_k']+qv*thickness**2/(2*a['thermal_conductivity_w_mk']),
                             reference_scope='1D uniform slab steady-state; compare only steady runs',
                             time_s=a['thermal_time_s'], heat_source_w_m3=qv)
    if a['thermal_time_s']:
        from .advanced_thermal import slab_transient_peak
        result['thermal']['transient'] = transient
        result['thermal']['reference_transient_peak_k'] = slab_transient_peak(a['ambient_k'], a['thermal_power_w'], area, thickness, a['thermal_conductivity_w_mk'], a['density_kg_m3'], a['specific_heat_j_kgk'], a['thermal_time_s'])
    if em_field is not None:
        result['thermal'].pop('reference_peak_k')
        result['thermal'].pop('heat_source_w_m3')
        result['thermal'].pop('reference_transient_peak_k', None)
        result['thermal']['reference_scope'] = 'Nonuniform dielectric RF losses; uniform-slab analytic reference does not apply'
        result['thermal']['rf_frequency_hz'] = float(em_field.freq)
        result['thermal']['rf_input_power_w'] = a['rf_input_power_w']
        result['thermal']['coupling'] = 'EMerge CoupledEMHeating dielectric volumetric loss; conductor surface heating excluded'
        result['assumptions'][0] = 'One-way coupling of sampled dielectric RF volumetric loss; fixed bottom and adiabatic sides/top'
        result['assumptions'][2] = 'Conductor surface loss is excluded; no temperature feedback into EM materials'
    result['scene_geometry'] = dict(kind='thermal_substrate', unit='mm', bounds=[bbox[0], bbox[1], -thickness*1000, bbox[2], bbox[3], 0])
    if region:
        from .region_backend import region_digest
        result.update(region=region, region_sha256=region_digest(region))
    return result


def solve_optimization(c, info, progress, qualifying=False):
    from scipy.optimize import minimize_scalar
    from .backend import solve
    a = c['advanced']
    key = a['optimize_parameter']
    # Validate the entire interval endpoints before launching any costly solve.
    for dimension in (a['optimize_min_mm'], a['optimize_max_mm']):
        validate_config(dict(c, **{key: dimension}, advanced=dict(a, study='driven')))
    samples, best = [], [None]
    def objective(dimension):
        progress(f'Optimization solve {len(samples)+1}/{a["optimize_evaluations"]}: {key}={dimension:g} mm', flush=True)
        candidate = dict(c, **{key: float(dimension)}, advanced=dict(a, study='driven'))
        result = solve(candidate, progress, qualifying=qualifying)
        s11 = [complex(*p) for p in result['s_parameters']['S11']]
        score = max(abs(v)**2 for v in s11)
        samples.append(dict(dimension_mm=float(dimension), worst_reflected_power_fraction=score))
        if best[0] is None or score < best[0][0]:
            best[0] = (score, result, float(dimension))
        return score
    optimum = minimize_scalar(objective, bounds=(a['optimize_min_mm'], a['optimize_max_mm']),
                              method='bounded', options={'maxiter': a['optimize_evaluations'], 'xatol': 1e-3})
    result = best[0][1]
    candidate_config = result['config']
    result.update(config=c, config_sha256=config_digest(c))
    result['optimization'] = dict(parameter=key, samples=samples, best_dimension_mm=best[0][2],
                                  best_score=best[0][0], best_config=candidate_config,
                                  converged=bool(optimum.success), message=str(optimum.message),
                                  objective='Minimize worst sampled |S11|^2; finite evaluation budget')
    result['assumptions'].append('Optimization is bounded by solve budget; no global optimum or continuous-band guarantee')
    return result



def solve_waveguide(em, np, c, info, progress):
    a = c['advanced']
    width, height, length = (a[k]*.001 for k in ('waveguide_width_mm','waveguide_height_mm','waveguide_length_mm'))
    model = em.Simulation('QuickEMergeWaveguide')
    configure_solver(em, model, c)
    guide = em.geo.Box(width, height, length, position=(-width/2,-height/2,0))
    model.mw.set_resolution(c['resolution'])
    model.mw.set_frequency_range(c['f_start_hz'], c['f_stop_hz'], c['points'])
    model.commit_geometry()
    model.mesher.set_domain_size(guide, c['mesh_edge_mm']*.001)
    model.generate_mesh()
    check_mesh_budget(model, c)
    for i, (face, z) in enumerate(((guide.bottom, 0), (guide.top, length)), 1):
        port = model.mw.bc.RectangularWaveguide(face, i, mode=(1,0), mode_type='TE', er=1.,
                  cs=em.GCS.displace(0,0,z), dims=(width,height))
        port.align_modes(em.YAX)
    progress('Solving dominant TE10 waveguide ports; comparing propagation to analytic cutoff.', flush=True)
    data = model.mw.run_sweep()
    frequencies, native = _network(np, data, 2)
    fc = 299792458/(2*width)
    f = np.asarray(frequencies)
    zte = float(em.lib.Z0)/np.sqrt(1-(fc/f)**2)
    renormalized = {name:[] for name in native}
    for k, z in enumerate(zte):
        smat = np.array([[complex(*native[f'S{i}{j}'][k]) for j in (1,2)] for i in (1,2)])
        gamma = (c['z0_ohm']-z)/(c['z0_ohm']+z)
        new = np.linalg.solve((np.eye(2)-gamma*smat).T, (smat-gamma*np.eye(2)).T).T
        for i in (1,2):
            for j in (1,2):
                v = new[i-1,j-1]
                renormalized[f'S{i}{j}'].append([float(v.real),float(v.imag)])
    result = _base(c, info, 'rectangular-waveguide-template', [
        'Straight air-filled PEC guide with analytic dominant TE10 ports',
        'Sweep restricted above TE10 cutoff and below the next propagating mode',
        'Main S matrix renormalized from frequency-dependent TE impedance to the entered real Z0',
        'Analytic uniform-guide comparison is a reference check, not arbitrary-waveguide qualification'])
    result.update(port_count=2, frequencies_hz=frequencies, s_parameters=renormalized, reference_impedance_ohm=c['z0_ohm'])
    beta = 2*np.pi*f/299792458*np.sqrt(1-(fc/f)**2)
    reference = np.exp(-1j*beta*length)
    # Mode sign is fixed by aligning both analytic port fields to global +Y.
    actual = np.array([complex(*p) for p in native['S21']])
    result['waveguide'] = dict(cutoff_hz=fc, next_mode_cutoff_hz=min(299792458/width,299792458/(2*height)),
            native_s_parameters=native, native_reference_impedance_ohm=zte.tolist(),
            analytic_s21=[[float(v.real),float(v.imag)] for v in reference],
            maximum_s21_complex_error=float(np.max(np.abs(actual-reference))))
    frequency = frequencies[len(frequencies)//2]
    result['field'] = field_payload(np, data.field.find(freq=frequency), frequency, [-width*500,-height*500,width*500,height*500], c)
    result['scene_geometry'] = dict(kind='waveguide', unit='mm', bounds=[-width*500,-height*500,0,width*500,height*500,length*1000])
    return result


def solve_advanced(em, np, c, info, progress, region=None, qualifying=False):
    study = c['advanced']['study']
    if study == 'waveguide':
        return solve_waveguide(em, np, c, info, progress)
    if study == 'periodic':
        return solve_periodic(em, np, c, info, progress)
    if study == 'scattering':
        return solve_scattering(em, np, c, info, progress)
    if study == 'thermal':
        return solve_thermal(em, np, c, info, progress, region)
    if study == 'optimization':
        return solve_optimization(c, info, progress, qualifying)
    raise ValueError('Unsupported advanced study')


def build_array_geometry(em, np, c):
    from .advanced import air_region
    a = c['advanced']
    model = em.Simulation('QuickEMergeFiniteArray')
    configure_solver(em, model, c)
    sx, sy, th = (c[k]*.001 for k in ('substrate_x_mm','substrate_y_mm','thickness_mm'))
    em.geo.Box(sx,sy,th,position=(-sx/2,-sy/2,-th)).set_material(dielectric(em,c))
    w, length, feed, slot, inset = (c[k]*.001 for k in ('patch_width_mm','patch_length_mm','feed_width_mm','inset_width_mm','inset_length_mm'))
    conductors, ports, centers = [], [], []
    for iy in range(a['array_count_y']):
        for ix in range(a['array_count_x']):
            x = (ix-(a['array_count_x']-1)/2)*a['array_pitch_x_mm']*.001
            y = (iy-(a['array_count_y']-1)/2)*a['array_pitch_y_mm']*.001
            patch = em.geo.XYPlate(w,length,position=(x-w/2,y-length/2,0))
            for offset in (-feed/2-slot, feed/2):
                patch = em.geo.remove(patch,em.geo.XYPlate(slot,inset,position=(x+offset,y-length/2,0)))
            conductors.append(assign_conductor(em,patch,c))
            ports.append(em.geo.Plate(np.array([x-feed/2,y-length/2,-th]),np.array([feed,0,0]),np.array([0,0,th])))
            centers.append([x*1000,y*1000])
    conductors.append(assign_conductor(em,em.geo.XYPlate(sx,sy,position=(-sx/2,-sy/2,-th)),c))
    model._quick_conductors = conductors
    model._quick_array_centers = centers
    air = air_region(em,c,sx,sy,th,-sx/2,-sy/2)
    model.mw.set_resolution(c['resolution'])
    model.mw.set_frequency_range(c['f_start_hz'],c['f_stop_hz'],c['points'])
    model.commit_geometry()
    for surface in conductors:
        model.mesher.set_boundary_size(surface,c['mesh_edge_mm']*.001)
    for port in ports:
        model.mesher.set_face_size(port,min(feed,th)/2)
    return model,air,ports,[feed]*len(ports),th
