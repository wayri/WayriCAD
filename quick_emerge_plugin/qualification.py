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
        frequencies = result['frequencies_hz']
        _axis(frequencies, positive=True)
        if config['sweep'] == 'linear' and len(frequencies) != config['points']:
            raise ValueError('qualification frequency count mismatch')
        count = 1 if config['mode'] == 'patch' else 2
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
        if config['mode'] == 'patch':
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
    packages = {}
    for name in ('emerge', 'numpy', 'scipy', 'matplotlib', 'gmsh', 'packaging'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    certificate = dict(schema=1, issuer=CERTIFICATE_ISSUER, version=version,
                       adapter_signature=adapter_signature(),
                       qualified_at=datetime.now(timezone.utc).isoformat(), checks=checks,
                       packages=packages,
                       scope='API compatibility smoke solves; not numerical accuracy or convergence')
    backend.atomic_json(Path(output), certificate)
    return certificate
