"""Real coarse adapter smoke solves, not numerical/convergence qualification."""
from datetime import datetime, timezone
import importlib.metadata
import math
from pathlib import Path

from . import backend
from .compatibility import CERTIFICATE_ISSUER, adapter_signature
from .model import validate_config


def _finite(value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('qualification requires numeric samples')
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError('qualification found invalid numeric samples')


def _axis(values, *, positive=False):
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError('qualification requires sampled axes')
    for value in values:
        _finite(value, positive=positive)
    if any(b <= a for a, b in zip(values, values[1:])):
        raise ValueError('qualification requires strictly ordered axes')


def _grid(values, rows, columns, *, allow_none=False):
    if not isinstance(values, list) or len(values) != rows:
        raise ValueError('qualification grid row count mismatch')
    known = []
    for row in values:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError('qualification grid column count mismatch')
        for value in row:
            if value is None and allow_none:
                continue
            _finite(value, nonnegative=True)
            known.append(value)
    if not known:
        raise ValueError('qualification grid has no finite samples')
    return known


def check_result(result, config):
    """Reject incomplete adapter output before issuing any certificate."""
    try:
        study = config.get('advanced', {}).get('study', 'driven')
        if study == 'thermal':
            t = result['thermal']
            _axis(t['x_mm']); _axis(t['y_mm'])
            values = _grid(t['temperature_k'], len(t['y_mm']), len(t['x_mm']), allow_none=True)
            _finite(t['reference_peak_k'], positive=True)
            if result['port_count'] != 0 or result['s_parameters']:
                raise ValueError('Thermal results must not invent a network')
            if config['advanced']['thermal_time_s']:
                reference = t['reference_transient_peak_k']
                if not math.isclose(t['transient']['time_s'][-1], config['advanced']['thermal_time_s'], rel_tol=0., abs_tol=1e-9) or abs(t['peak_k']-reference) > .5:
                    raise ValueError('Transient time/reference compatibility check failed')
                return
            if abs(max(values)-t['reference_peak_k']) > .02*max(1., t['reference_peak_k']-config['advanced']['ambient_k']):
                raise ValueError('Thermal slab disagrees with the independent analytical reference')
            return
        frequencies = result['frequencies_hz']
        _axis(frequencies, positive=True)
        if config['sweep'] == 'linear' and len(frequencies) != config['points']:
            raise ValueError('qualification frequency count mismatch')
        count = 0 if study == 'scattering' else (config['advanced']['array_count_x']*config['advanced']['array_count_y'] if study == 'array' else (2 if study in ('periodic','waveguide') else (1 if config['mode'] == 'patch' else 2)))
        expected = {f'S{i}{j}' for i in range(1, count + 1) for j in range(1, count + 1)}
        if set(result['s_parameters']) != expected:
            raise ValueError('qualification missing full port matrix')
        for samples in result['s_parameters'].values():
            if len(samples) != len(frequencies):
                raise ValueError('qualification S-parameter alignment mismatch')
            for pair in samples:
                if len(pair) != 2:
                    raise ValueError('qualification complex pair mismatch')
                for value in pair:
                    _finite(value)
        field = result['field']
        for axis in ('x_mm', 'y_mm'):
            _axis(field[axis])
            if len(field[axis]) != config['field_grid']:
                raise ValueError('qualification field axis count mismatch')
        _grid(field['norm_e_v_m'], len(field['y_mm']), len(field['x_mm']), allow_none=True)
        if study == 'array' and result['array']['superposition_relative_error'] > 1e-10:
            raise ValueError('Array fields disagree with the independent per-port coherent sum')
        if study == 'waveguide' and result['waveguide']['maximum_s21_complex_error'] > .02:
            raise ValueError('Waveguide TE10 propagation differs from the analytic reference')
        if config['advanced']['coupled_thermal']:
            _finite(result['thermal']['peak_k'], positive=True)
            if result['thermal']['peak_k'] < config['advanced']['ambient_k']-1e-6 or not result['thermal'].get('coupling'):
                raise ValueError('Coupled thermal heating is missing or physically invalid')
        if study == 'scattering':
            rcs = result['scattering']
            _grid(rcs['rcs_m2'], len(rcs['theta_rad']), len(rcs['phi_rad']))
        if config['mode'] == 'patch' and study in ('driven', 'optimization', 'array'):
            radiation = result['radiation']
            _axis(radiation['theta_rad'])
            _axis(radiation['phi_rad'])
            values = _grid(radiation['norm_e'], len(radiation['theta_rad']), len(radiation['phi_rad']))
            if max(values) <= 0:
                raise ValueError('qualification radiation peak must be positive')
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('qualification result is incomplete or malformed') from error


def smoke_configs():
    common = dict(thickness_mm=1, points=3, field_grid=5, field_z_mm=1)
    line = validate_config(dict(common, mode='pcb_line', substrate_x_mm=20, substrate_y_mm=10,
                                line_length_mm=10, line_width_mm=2, air_margin_mm=5,
                                f_start_hz=1e9, f_stop_hz=2e9, resolution=.5, mesh_edge_mm=2))
    patch = validate_config(dict(common, mode='patch', substrate_x_mm=40, substrate_y_mm=40,
                                 patch_width_mm=20, patch_length_mm=20, feed_width_mm=2,
                                 inset_width_mm=3, inset_length_mm=5, air_margin_mm=10,
                                 f_start_hz=4e9, f_stop_hz=5e9, resolution=.4, mesh_edge_mm=3))
    return [('pcb_line_linear', line), ('patch_linear', patch),
            ('pcb_line_adaptive', dict(line, sweep='adaptive', points=5, adaptive_steps=1))]


def qualify(output):
    """Write only the explicitly requested certificate after all real solves pass."""
    from packaging.version import Version
    version = importlib.metadata.version('emerge')
    if Version(version).major < 3:
        raise RuntimeError('Quick EMerge qualification requires EMerge 3 or newer.')
    initial_signature = adapter_signature()
    checks = []
    for name, config in smoke_configs():
        result = backend.solve(config, qualifying=True)
        check_result(result, config)
        checks.append(name)
    from .region_backend import qualification_region
    config = validate_config(dict(smoke_configs()[0][1], mode='pcb_region', rule_area_id='qualification-coupon',
                                  signal_net='SIGNAL', reference_net='GND', region_er_reviewed=True))
    result = backend.solve(config, qualifying=True, region=qualification_region())
    check_result(result, config)
    checks.append('polygon_region_linear')
    for name, config in advanced_smoke_configs():
        result = backend.solve(config, qualifying=True)
        check_result(result, config)
        checks.append(name)
    checks.extend(qualify_extended_apis(Path(output).parent))
    packages = {}
    for name in ('emerge', 'numpy', 'scipy', 'matplotlib', 'gmsh', 'packaging', 'emcad', 'ezdxf', 'optycal', 'msgpack', 'msgpack-numpy'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    if adapter_signature() != initial_signature:
        raise RuntimeError('Adapter source changed during qualification; repeat checks on the final source.')
    certificate = dict(schema=1, issuer=CERTIFICATE_ISSUER, version=version,
                       adapter_signature=initial_signature,
                       qualified_at=datetime.now(timezone.utc).isoformat(), checks=checks,
                       packages=packages,
                       scope='API compatibility smoke solves; not numerical accuracy or convergence')
    backend.atomic_json(Path(output), certificate)
    return certificate


def advanced_smoke_configs():
    base = dict(smoke_configs()[0][1], points=2)
    return [(name, validate_config(dict(base, **extra, advanced=advanced))) for name, extra, advanced in (
        ('lossy_dispersive_line', {}, dict(conductor='finite', loss_tangent=.02, roughness_um=.5, er_stop=3.1, field_layers=3)),
        ('periodic_floquet', dict(patch_width_mm=5, patch_length_mm=4), dict(study='periodic')),
        ('scattered_sphere', {}, dict(study='scattering', scatter_radius_mm=3)),
        ('steady_thermal_slab', {}, dict(study='thermal')),
        ('bounded_optimization', {}, dict(study='optimization', optimize_min_mm=1, optimize_max_mm=3, optimize_evaluations=3)),
        ('transient_thermal_slab', {}, dict(study='thermal', thermal_time_s=2.1, thermal_step_s=.25)),
        ('dielectric_rf_heating', {}, dict(loss_tangent=.02, coupled_thermal=True)),
        ('waveguide_te10', dict(f_start_hz=8e9,f_stop_hz=10e9,mesh_edge_mm=3), dict(study='waveguide')),
        ('internal_via_line', {}, dict(line_geometry='stripline_via')),
        ('shunt_resistor_line', {}, dict(shunt_component='resistor',shunt_value=50)),
        ('finite_three_patch_array', dict(mode='patch',substrate_x_mm=30,patch_width_mm=5,patch_length_mm=4,feed_width_mm=1,inset_width_mm=.5,inset_length_mm=1), dict(study='array',array_count_x=3,array_count_y=1,array_pitch_x_mm=8,array_pitch_y_mm=8,array_phase_x_deg=30)),
        ('pml_line', {}, dict(boundary='pml', pml_thickness_mm=5)),
    )]


def qualify_extended_apis(directory):
    """Qualify installed import, fitting and live export APIs on tiny owned fixtures."""
    import json
    import tempfile
    from .qualification_data import import_smoke_configs, qualification_source_board, qualify_network_api
    from .model import config_digest
    checks = []
    with tempfile.TemporaryDirectory(prefix='advanced-api-qualification-', dir=directory) as temporary:
        folder = Path(temporary)
        base = smoke_configs()[0][1]
        for name, config in import_smoke_configs(folder, base):
            result = backend.solve(config, qualifying=True)
            check_result(result, config)
            if result.get('import_source', {}).get('sha256') != config['advanced']['import_sha256']:
                raise ValueError('Imported geometry did not preserve the reviewed source manifest')
            checks.append(name)
        checks.append(qualify_network_api())
        source = qualification_source_board(folder)
        c = validate_config(dict(smoke_configs()[1][1], points=2, advanced=dict(export_dxf=True,export_optycal=True)))
        request = dict(config=c,config_sha256=config_digest(c),source=source)
        request_path = folder/'request.json'
        request_path.write_text(json.dumps(request),encoding='utf-8')
        result = backend.run_request(request_path,qualifying=True)
        check_result(result,c)
        exports = result.get('exports',{})
        if exports.get('state') != 'published' or len(exports.get('artifacts',[])) < 2:
            raise ValueError('Live DXF/Optycal qualification did not publish both reviewed exports')
        checks.append('live_dxf_optycal_consumer_readback')
    return checks
