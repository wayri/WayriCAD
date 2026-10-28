"""Bounded, data-only physics controls for the EMerge adapter.

Public EMerge 3 APIs are called only in the solver worker. No expressions or
Python supplied by a project are evaluated.
"""
import hashlib
import math
from pathlib import Path


def _f(key, label, default, kind='number', unit='', studies=(), choices=None, group='Physics'):
    item = dict(key=key, label=label, default=default, kind=kind, unit=unit,
                studies=list(studies), group=group)
    if choices:
        item['choices'] = list(choices)
    return item


ADVANCED_FIELDS = (
    _f('study', 'Study', 'driven', 'choice', choices=('driven', 'periodic', 'scattering', 'thermal', 'optimization', 'waveguide', 'array')),
    _f('array_count_x', 'Array elements X', 2, 'integer', studies=('array',), group='Array'),
    _f('array_count_y', 'Array elements Y', 1, 'integer', studies=('array',), group='Array'),
    _f('array_pitch_x_mm', 'Array pitch X', 60, unit='mm', studies=('array',), group='Array'),
    _f('array_pitch_y_mm', 'Array pitch Y', 60, unit='mm', studies=('array',), group='Array'),
    _f('array_phase_x_deg', 'Progressive phase X', 0, unit='deg', studies=('array',), group='Array'),
    _f('array_phase_y_deg', 'Progressive phase Y', 0, unit='deg', studies=('array',), group='Array'),
    _f('array_power_w', 'Total incident array power', 1, unit='W', studies=('array',), group='Array'),
    _f('patch_offset_y_mm', 'Patch center offset Y', 0, unit='mm', studies=('driven', 'optimization'), group='Patch feed'),
    _f('patch_feed_extension_mm', 'External patch feed length', 0, unit='mm', studies=('driven', 'optimization'), group='Patch feed'),
    _f('line_geometry', 'Line geometry', 'microstrip', 'choice', choices=('microstrip', 'stripline_via'), studies=('driven',), group='PCB template'),
    _f('via_radius_mm', 'Internal via radius', .2, unit='mm', studies=('driven',), group='PCB template'),
    _f('shunt_component', 'Mid-line shunt element', 'none', 'choice', choices=('none','resistor','capacitor','inductor'), studies=('driven',), group='Excitation'),
    _f('shunt_value', 'Shunt value', 50, unit='ohm / pF / nH', studies=('driven',), group='Excitation'),
    _f('waveguide_width_mm', 'Waveguide broad dimension', 22.86, unit='mm', studies=('waveguide',), group='Waveguide'),
    _f('waveguide_height_mm', 'Waveguide narrow dimension', 10.16, unit='mm', studies=('waveguide',), group='Waveguide'),
    _f('waveguide_length_mm', 'Waveguide length', 30, unit='mm', studies=('waveguide',), group='Waveguide'),
    _f('loss_tangent', 'Dielectric loss tangent', 0, studies=('driven', 'periodic', 'optimization', 'array'), group='Material'),
    _f('er_stop', 'Permittivity at stop frequency (0 = constant)', 0, studies=('driven', 'periodic', 'optimization', 'array'), group='Material'),
    _f('conductor', 'Conductor model', 'pec', 'choice', choices=('pec', 'finite'), studies=('driven', 'periodic', 'optimization', 'array'), group='Material'),
    _f('conductivity_s_m', 'Conductor conductivity', 58000000, unit='S/m', studies=('driven', 'periodic', 'optimization', 'array'), group='Material'),
    _f('conductor_thickness_um', 'Conductor thickness', 35, unit='um', studies=('driven', 'periodic', 'optimization', 'array'), group='Material'),
    _f('roughness_um', 'RMS surface roughness', 0, unit='um', studies=('driven', 'periodic', 'optimization', 'array'), group='Material'),
    _f('boundary', 'Outer boundary', 'absorbing', 'choice', choices=('absorbing', 'pec', 'pmc', 'pml'), studies=('driven', 'optimization', 'array'), group='Boundary'),
    _f('abc_order', 'Absorbing boundary order', 2, 'integer', studies=('driven', 'optimization', 'array'), group='Boundary'),
    _f('pml_thickness_mm', 'PML thickness', 5, unit='mm', studies=('driven', 'optimization', 'array'), group='Boundary'),
    _f('field_layers', 'Sampled field Z layers (1 = plane)', 1, 'integer', studies=('driven', 'periodic', 'scattering', 'optimization', 'waveguide', 'array'), group='Fields'),
    _f('field_z_min_mm', 'Volume lower Z', .1, unit='mm', studies=('driven', 'periodic', 'scattering', 'optimization', 'waveguide', 'array'), group='Fields'),
    _f('export_dxf', 'Export exact planar sheets as DXF', False, 'bool', studies=('driven','array'), group='Exports'),
    _f('export_dxf_z_mm', 'DXF sheet heights', '0', 'text', unit='mm, comma-separated', studies=('driven','array'), group='Exports'),
    _f('export_optycal', 'Export official Optycal far-field MsgPack', False, 'bool', studies=('driven','array'), group='Exports'),
    _f('solver_threads', 'Solver threads', 1, 'integer', group='Solver'),
    _f('sparta_mode', 'SPARTA compute mode', 'CPU', 'choice', choices=('CPU', 'GPU', 'HYBRID'), group='Solver'),
    _f('scan_theta_deg', 'Incidence theta', 0, unit='deg', studies=('periodic', 'scattering'), group='Excitation'),
    _f('scan_phi_deg', 'Incidence phi', 0, unit='deg', studies=('periodic', 'scattering'), group='Excitation'),
    _f('polarization_deg', 'Polarization', 0, unit='deg', studies=('periodic', 'scattering'), group='Excitation'),
    _f('scatter_radius_mm', 'PEC sphere radius', 5, unit='mm', studies=('scattering',), group='Scattering'),
    _f('incident_power_w_m2', 'Incident power density', 1, unit='W/m2', studies=('scattering',), group='Scattering'),
    _f('import_kind', 'Fabrication import', 'none', 'choice', choices=('none', 'gerber', 'gds', 'gds_xml', 'odb'), studies=('scattering',), group='Import'),
    _f('import_path', 'Fabrication source', '', 'path', studies=('scattering',), group='Import'),
    _f('import_recipe_path', 'Reviewed import recipe', '', 'path', studies=('scattering',), group='Import'),
    _f('import_sha256', 'Reviewed import manifest SHA-256', '', 'text', studies=('scattering',), group='Import'),
    _f('step_path', 'STEP scatterer (empty = sphere)', '', 'path', studies=('scattering',), group='Scattering'),
    _f('step_sha256', 'Reviewed STEP SHA-256', '', 'text', studies=('scattering',), group='Scattering'),
    _f('step_unit_m', 'STEP coordinate scale', .001, unit='m/unit', studies=('scattering',), group='Scattering'),
    _f('coupled_thermal', 'Solve dielectric RF heating', False, 'bool', studies=('driven',), group='Thermal'),
    _f('rf_input_power_w', 'Port 1 RF power for dielectric heating', 1, unit='W', studies=('driven',), group='Thermal'),
    _f('thermal_conductivity_w_mk', 'Substrate thermal conductivity', .3, unit='W/(m K)', studies=('thermal', 'driven'), group='Thermal'),
    _f('thermal_power_w', 'Uniform substrate heating power', 1, unit='W', studies=('thermal', 'driven'), group='Thermal'),
    _f('ambient_k', 'Fixed bottom temperature', 293.15, unit='K', studies=('thermal', 'driven'), group='Thermal'),
    _f('thermal_time_s', 'Transient duration (0 = steady)', 0, unit='s', studies=('thermal', 'driven'), group='Thermal'),
    _f('thermal_step_s', 'Transient time step', 1, unit='s', studies=('thermal', 'driven'), group='Thermal'),
    _f('density_kg_m3', 'Substrate density', 1850, unit='kg/m3', studies=('thermal', 'driven'), group='Thermal'),
    _f('specific_heat_j_kgk', 'Substrate specific heat', 1000, unit='J/(kg K)', studies=('thermal', 'driven'), group='Thermal'),
    _f('optimize_parameter', 'Optimized template dimension', 'line_width_mm', 'choice', choices=('line_width_mm', 'line_length_mm', 'patch_width_mm', 'patch_length_mm', 'inset_length_mm'), studies=('optimization',), group='Optimization'),
    _f('optimize_min_mm', 'Dimension lower bound', 1, unit='mm', studies=('optimization',), group='Optimization'),
    _f('optimize_max_mm', 'Dimension upper bound', 4, unit='mm', studies=('optimization',), group='Optimization'),
    _f('optimize_evaluations', 'Maximum real solves', 5, 'integer', studies=('optimization',), group='Optimization'),
)
_ALL_FIELDS = ADVANCED_FIELDS
# Thermal transient uses the source-bound b9 driver compatibility adapter.
ADVANCED_FIELDS = _ALL_FIELDS
ADVANCED_DEFAULTS = {f['key']: f['default'] for f in _ALL_FIELDS}


def validate_advanced(raw, config):
    if not isinstance(raw, dict) or set(raw) - set(ADVANCED_DEFAULTS):
        raise ValueError('advanced must contain only documented physics controls')
    a = {**ADVANCED_DEFAULTS, **raw}
    for f in _ALL_FIELDS:
        key, value = f['key'], a[f['key']]
        if f['kind'] == 'bool':
            if type(value) is not bool:
                raise ValueError(key+' must be boolean')
            continue
        if f['kind'] in ('choice', 'path', 'text'):
            if not isinstance(value, str) or ('choices' in f and value not in f['choices']):
                raise ValueError('Invalid advanced '+key)
            continue
        if isinstance(value, bool):
            raise ValueError(key+' must be a finite number')
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(key+' must be a finite number') from None
        if not math.isfinite(value):
            raise ValueError(key+' must be a finite number')
        if f['kind'] == 'integer':
            if not value.is_integer():
                raise ValueError(key+' must be an integer')
            value = int(value)
        a[key] = value
    zero_ok = ('patch_feed_extension_mm', 'loss_tangent', 'er_stop', 'roughness_um', 'thermal_power_w', 'thermal_time_s')
    signed = ('patch_offset_y_mm', 'scan_theta_deg', 'scan_phi_deg', 'polarization_deg', 'array_phase_x_deg', 'array_phase_y_deg')
    for f in _ALL_FIELDS:
        key = f['key']
        if f['kind'] not in ('number', 'integer') or key in signed:
            continue
        if a[key] < 0 or (a[key] == 0 and key not in zero_ok):
            raise ValueError(key+' must be positive (or a documented zero option)')
    if a['loss_tangent'] > 1 or a['abc_order'] not in (1, 2) or not 1 <= a['solver_threads'] <= 64:
        raise ValueError('Loss tangent, ABC order or solver thread limit is invalid')
    if abs(a['scan_phi_deg']) > 360 or abs(a['polarization_deg']) > 360 or not 0 <= a['scan_theta_deg'] < 90:
        raise ValueError('Incidence theta must be in [0, 90); phi and polarization must be within +/-360 degrees')
    if a['thermal_time_s'] and (a['thermal_step_s'] > a['thermal_time_s'] or a['thermal_time_s']/a['thermal_step_s'] > 1000):
        raise ValueError('Thermal transient requires 1 to 1000 time steps')
    if not 3 <= a['optimize_evaluations'] <= 30 or a['optimize_min_mm'] >= a['optimize_max_mm']:
        raise ValueError('Optimization requires ordered bounds and 3 to 30 evaluations')
    if not 1 <= a['field_layers'] <= 17 or config['field_grid']**2*a['field_layers'] > 100000:
        raise ValueError('Field volume is limited to 17 Z layers and 100,000 samples')
    if a['field_layers'] > 1 and a['field_z_min_mm'] >= config['field_z_mm']:
        raise ValueError('Field volume lower Z must be below the field plane Z')
    study = a['study']
    extension = a['patch_feed_extension_mm']
    offset_y = a['patch_offset_y_mm']
    if extension or offset_y:
        if config['mode'] != 'patch' or study not in ('driven', 'optimization'):
            raise ValueError('External patch feed and offset require a driven or optimization patch template')
        half_length = config['patch_length_mm']/2
        half_board = config['substrate_y_mm']/2
        if offset_y + half_length > half_board + 1e-9 or offset_y - half_length - extension < -half_board - 1e-9:
            raise ValueError('Patch offset and external patch feed must fit inside the substrate')
    if a['export_dxf'] or a['export_optycal']:
        if study not in ('driven','array'):
            raise ValueError('Live exports are currently supported by driven and finite-array studies')
        if a['export_dxf']:
            from .advanced_exports import parse_dxf_heights_mm
            parse_dxf_heights_mm(a['export_dxf_z_mm'])
        if a['export_optycal'] and (config['points'] > 8 or a['boundary'] not in ('absorbing','pml')):
            raise ValueError('Optycal far-field export requires an open boundary and at most 8 frequency samples')
    if study == 'array':
        if config['mode'] != 'patch' or not 1 <= a['array_count_x'] <= 3 or not 1 <= a['array_count_y'] <= 3 or not 2 <= a['array_count_x']*a['array_count_y'] <= 9:
            raise ValueError('Finite arrays require the patch template and 2 to 9 elements (up to 3 per axis)')
        for axis, size in (('x', 'patch_width_mm'), ('y', 'patch_length_mm')):
            pitch, count = a['array_pitch_'+axis+'_mm'], a['array_count_'+axis]
            if (count > 1 and pitch <= config[size]) or config[size]+(count-1)*pitch >= config['substrate_'+axis+'_mm']:
                raise ValueError('Separated array patches must fit inside the common substrate')
    if a['line_geometry'] == 'stripline_via':
        if study != 'driven' or config['mode'] != 'pcb_line' or a['conductor'] != 'pec':
            raise ValueError('Internal multilayer/via template requires a driven PCB line with PEC conductors')
        if a['via_radius_mm']*2 > config['line_width_mm'] or a['via_radius_mm']*4 >= config['line_length_mm']:
            raise ValueError('Internal via must fit in its trace and line length')
    if a['shunt_component'] != 'none' and (study != 'driven' or config['mode'] != 'pcb_line' or a['line_geometry'] != 'microstrip'):
        raise ValueError('The FEM shunt element is currently a driven microstrip-line feature')
    if study == 'waveguide':
        width, height = a['waveguide_width_mm']*.001, a['waveguide_height_mm']*.001
        cutoff = 299792458/(2*width)
        next_mode = min(299792458/width, 299792458/(2*height))
        if width <= height or not cutoff < config['f_start_hz'] < config['f_stop_hz'] < next_mode:
            raise ValueError('Waveguide sweep must be above TE10 cutoff and below the next mode; broad dimension must exceed narrow dimension')
        if config['field_z_mm'] >= a['waveguide_length_mm']:
            raise ValueError('Field plane must lie inside the waveguide length')
    if study in ('periodic', 'scattering', 'waveguide') and config['mode'] == 'pcb_region':
        raise ValueError('Periodic/scattering studies use their reviewed template or STEP geometry, not a cropped PCB')
    if study != 'driven' and (config['adaptive_steps'] or config['sweep'] != 'linear'):
        raise ValueError('Advanced study types currently require a linear sweep without mesh adaptation')
    if study == 'periodic' and config['f_stop_hz']*max(config['substrate_x_mm'], config['substrate_y_mm'])*.001*(1+math.sin(math.radians(a['scan_theta_deg']))) >= 299792458:
        raise ValueError('The periodic sweep reaches higher diffraction orders. Reduce frequency, scan angle, or cell period; only fundamental Floquet modes are integrated.')
    if study == 'periodic' and (config['patch_width_mm'] >= config['substrate_x_mm'] or config['patch_length_mm'] >= config['substrate_y_mm']):
        raise ValueError('Periodic patch must fit inside its unit cell')
    if study == 'optimization':
        allowed = ('line_width_mm', 'line_length_mm') if config['mode'] == 'pcb_line' else ('patch_width_mm', 'patch_length_mm', 'inset_length_mm')
        if config['mode'] == 'pcb_region' or a['optimize_parameter'] not in allowed:
            raise ValueError('Optimization dimension must belong to the selected parametric template')
    if a['import_kind'] != 'none':
        if study != 'scattering' or a['step_path'] or not a['import_path'] or not a['import_recipe_path']:
            raise ValueError('Fabrication imports require a scattering study, source and reviewed recipe; do not also select STEP')
        if len(a['import_sha256']) != 64 or any(v not in '0123456789abcdef' for v in a['import_sha256']):
            raise ValueError('Review and hash the fabrication source manifest before solving')
    elif a['import_path'] or a['import_recipe_path'] or a['import_sha256']:
        raise ValueError('Select the fabrication import format before providing source paths')
    if a['coupled_thermal'] and study != 'driven':
        raise ValueError('Dielectric RF heating is available on driven template/region studies')
    if a['step_path']:
        if study != 'scattering':
            raise ValueError('STEP import is currently a PEC scattering workflow')
        if len(a['step_sha256']) != 64 or any(c not in '0123456789abcdef' for c in a['step_sha256']):
            raise ValueError('Review the STEP file and record its SHA-256 before simulation')
    elif a['step_sha256']:
        raise ValueError('STEP hash requires an import path')
    return a


def verify_step(a):
    path = Path(a['step_path']).expanduser().resolve(strict=True)
    if path.suffix.lower() not in ('.step', '.stp') or not path.is_file():
        raise ValueError('Scattering import requires a STEP solid file')
    if path.stat().st_size > 50*1024*1024:
        raise ValueError('STEP import exceeds the 50 MiB bounded importer')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != a['step_sha256']:
        raise ValueError('STEP file changed after review')
    return dict(path=str(path), sha256=digest, coordinate_scale_m=a['step_unit_m'])


def configure_solver(em, model, c):
    a = c.get('advanced', ADVANCED_DEFAULTS)
    try:
        solver = model.set_solver(em.EMSolver[c['solver']])
        solver.set_nthreads(a['solver_threads'])
        if c['solver'] == 'SPARTA':
            solver.set_options(mode=a['sparta_mode'])
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        raise RuntimeError(f"Selected {c['solver']} backend is unavailable: {exc}. Install its official optional dependencies or select SUPERLU.") from exc


def dielectric(em, c):
    a = c.get('advanced', ADVANCED_DEFAULTS)
    er = c['er']
    if a['er_stop']:
        start, stop = c['f_start_hz'], c['f_stop_hz']
        er = em.FreqDependent(scalar=lambda f: c['er'] + (a['er_stop']-c['er'])*(f-start)/(stop-start))
    return em.Material(er=er, tand=a['loss_tangent'], color='#268568', opacity=.35)


def assign_conductor(em, surface, c):
    # Explicit finite-sheet BC is installed after meshing, avoiding automatic PEC.
    if c.get('advanced', ADVANCED_DEFAULTS)['conductor'] == 'pec':
        surface.set_material(em.lib.PEC)
    return surface


def conductor_boundaries(em, model, surfaces, c):
    a = c.get('advanced', ADVANCED_DEFAULTS)
    if a['conductor'] == 'finite':
        material = em.Material(cond=a['conductivity_s_m'])
        for surface in surfaces:
            model.mw.bc.ThinConductor(surface, material=material,
                                      thickness=a['conductor_thickness_um']*1e-6,
                                      surface_roughness=a['roughness_um']*1e-6)


def air_region(em, c, sx, sy, thickness, x0, y0):
    a = c.get('advanced', ADVANCED_DEFAULTS)
    margin = c['air_margin_mm']*.001
    if a['boundary'] == 'pml':
        return em.geo.open_pml_region(margin, margin, margin,
                    thickness=a['pml_thickness_mm']*.001, N_mesh_layers=2, sides='TBLRFA')[0].background()
    return em.geo.Box(sx+2*margin, sy+2*margin, thickness+2*margin,
                      position=(x0-margin, y0-margin, -thickness-margin)).background()


def outer_boundary(model, air, c):
    a = c.get('advanced', ADVANCED_DEFAULTS)
    boundary = air.boundary()
    if a['boundary'] == 'absorbing':
        model.mw.bc.AbsorbingBoundary(boundary, order=a['abc_order'])
    elif a['boundary'] == 'pec':
        model.mw.bc.PEC(boundary)
    elif a['boundary'] == 'pmc':
        model.mw.bc.PMC(boundary)
    # PML regions already contain stretched-coordinate material and outer PEC.
    return boundary


def field_payload(np, field, frequency, bbox, c):
    xs = np.linspace(bbox[0], bbox[2], c['field_grid'])
    ys = np.linspace(bbox[1], bbox[3], c['field_grid'])
    x, y = np.meshgrid(xs, ys)
    sampled = field.interpolate(x*.001, y*.001, np.full(x.shape, c['field_z_mm']*.001))
    def real(values):
        return np.where(np.isfinite(values), values, np.nan).tolist()
    def nullable(value):
        if isinstance(value, list):
            return [nullable(v) for v in value]
        return float(value) if math.isfinite(value) else None
    e, h = np.asarray(sampled.E), np.asarray(sampled.H)
    p = .5*np.real(np.cross(e, np.conj(h), axisa=0, axisb=0, axisc=0))
    payload = dict(frequency_hz=frequency, z_mm=c['field_z_mm'], x_mm=xs.tolist(), y_mm=ys.tolist(),
                norm_e_v_m=nullable(real(np.linalg.norm(e, axis=0))),
                norm_h_a_m=nullable(real(np.linalg.norm(h, axis=0))),
                e_real_v_m=nullable(real(e.real)), e_imag_v_m=nullable(real(e.imag)),
                h_real_a_m=nullable(real(h.real)), h_imag_a_m=nullable(real(h.imag)),
                poynting_w_m2=nullable(real(p)), excitation='unit amplitude at port 1 unless scattering')
    if c['advanced']['field_layers'] > 1:
        zs = np.linspace(c['advanced']['field_z_min_mm'], c['field_z_mm'], c['advanced']['field_layers'])
        zv, yv, xv = np.meshgrid(zs, ys, xs, indexing='ij')
        volume = field.interpolate(xv*.001, yv*.001, zv*.001)
        ev, hv = np.asarray(volume.E), np.asarray(volume.H)
        payload['volume'] = dict(x_mm=xs.tolist(), y_mm=ys.tolist(), z_mm=zs.tolist(),
            array_order='z,y,x; vector components x,y,z first',
            norm_e_v_m=nullable(real(np.linalg.norm(ev, axis=0))),
            e_real_v_m=nullable(real(ev.real)), e_imag_v_m=nullable(real(ev.imag)),
            h_real_a_m=nullable(real(hv.real)), h_imag_a_m=nullable(real(hv.imag)))
    return payload


def physics_assumptions(c):
    a = c.get('advanced', ADVANCED_DEFAULTS)
    return [('PEC conductors' if a['conductor'] == 'pec' else 'Finite thin conductor sheets; Hammerstad-Jensen roughness correction'),
            ('Linear frequency-dependent relative permittivity' if a['er_stop'] else 'Nondispersive dielectric')+f"; loss tangent {a['loss_tangent']:g}",
            f"Outer boundary: {a['boundary']}; ABC order {a['abc_order']}",
            'No convergence qualification', 'Template geometry; originating PCB is context only']


def check_mesh_budget(model, c):
    if model.mesh.n_tets > c['max_tets']:
        raise ValueError(f"Mesh has {model.mesh.n_tets:,} tetrahedra, exceeding the reviewed limit {c['max_tets']:,}. Increase mesh size, PML thickness, or explicitly review a higher tetrahedron budget.")


def element_impedance(kind, value, frequency):
    if kind == 'resistor':
        return value
    if kind == 'capacitor':
        return 1/(2j*math.pi*frequency*value*1e-12)
    if kind == 'inductor':
        return 2j*math.pi*frequency*value*1e-9
    raise ValueError('Unknown typed FEM element')
