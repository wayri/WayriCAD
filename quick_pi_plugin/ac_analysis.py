"""Current-driven magnetoquasistatic losses in straight copper cross-sections.

Cell-centred finite volumes solve the axial magnetic vector potential and one
electric-field unknown per isolated conductor. Every conductor has an explicit
net-current constraint, including passive conductors carrying zero net current.
Currents are RMS phasors; fields are uniform along the specified path length.
"""
from __future__ import annotations

import math


MU0 = 4e-7 * math.pi
REFERENCES = [
    {'title': 'FEMM manual: harmonic conductors and circuit constraints',
     'url': 'https://www.femm.info/Archives/doc/manual34.pdf'},
    {'title': 'Magnetic and electric potential formulation',
     'url': 'https://doc.comsol.com/6.4/doc/com.comsol.help.acdc/acdc_ug_magnetic_fields.08.096.html'},
    {'title': 'Skin depth and conductor mesh resolution',
     'url': 'https://www.comsol.com/support/learning-center/article/81171'},
    {'title': 'NBS copper wire tables',
     'url': 'https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e2.pdf'},
]
LIMITATIONS = [
    'Straight, parallel, constant rectangular copper cross-sections only; no '
    'bends, vias, changing widths, zones or automatic whole-board AC extraction.',
    'Prescribed conductor currents and harmonics, not a nonlinear SMPS circuit '
    'or semiconductor, transformer, inductor-core or switching-loss simulation.',
    'No displacement current, distributed capacitance, dielectric loss, '
    'radiation, magnetic materials or common-mode current returning outside the model.',
    'Voltage is operating-point context only. No HV clearance, creepage, '
    'insulation, arcing, touch-safety or regulatory qualification is performed.',
    'Fixed, uniform copper temperature. Losses do not establish a temperature '
    'rise, cooling capability, ampacity or fuse-opening time.',
    'Mesh and air-box comparisons estimate discretization sensitivity; they '
    'do not establish physical accuracy for unsupported geometry.',
]


def _number(value, name, *, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(name + ' must be a finite number.')
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name + ' must be a finite number.') from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum) or (
            maximum is not None and result > maximum):
        raise ValueError(name + ' is outside its supported range.')
    return result


def validate_study(study):
    """Normalize explicit SI-compatible inputs; coordinates are centres in mm.

    Harmonic current amplitudes are RMS, while dc_current_a is signed mean.
    current_scale fixes each conductor's fraction of that common waveform.
    Positive and negative scales must balance so the magnetic return is modeled.
    """
    keys = {'schema', 'temperature_c', 'length_mm', 'reference_voltage_v',
            'relative_permittivity', 'conductors', 'dc_current_a', 'harmonics',
            'mesh_step_mm', 'air_padding_mm', 'max_cells', 'convergence_tolerance', 'waveform'}
    if not isinstance(study, dict) or set(study) - keys:
        raise ValueError('AC study contains unknown fields or is not an object.')
    if study.get('schema') != 'wayricad.pi-ac/v1':
        raise ValueError('AC study schema must be wayricad.pi-ac/v1.')
    out = {'schema': study['schema']}
    for name, default, low, high in [
            ('temperature_c', 20., -40., 200.), ('length_mm', None, 1e-6, 1e6),
            ('reference_voltage_v', 0., 0., None),
            ('relative_permittivity', 4.2, 1., 100.),
            ('dc_current_a', 0., None, None),
            ('mesh_step_mm', .05, 1e-6, 1000.),
            ('air_padding_mm', 1., 1e-5, 10000.),
            ('convergence_tolerance', .05, .001, .2)]:
        out[name] = _number(study.get(name, default), name, minimum=low, maximum=high)
    budget = study.get('max_cells', 60000)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 100 <= budget <= 100000:
        raise ValueError('max_cells must be an integer from 100 to 100000.')
    out['max_cells'] = budget
    conductors = study.get('conductors')
    if not isinstance(conductors, list) or not 2 <= len(conductors) <= 16:
        raise ValueError('Provide 2–16 explicit copper conductors including the return.')
    out['conductors'] = []; names = set()
    for row in conductors:
        if not isinstance(row, dict) or set(row) != {
                'name', 'x_mm', 'y_mm', 'width_mm', 'thickness_mm', 'current_scale'}:
            raise ValueError('Each conductor needs name, centre x/y, width, thickness and current_scale.')
        name = row['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('Conductor names must be unique, nonempty and at most 80 characters.')
        names.add(name)
        item = {'name': name}
        for key in ('x_mm', 'y_mm', 'width_mm', 'thickness_mm', 'current_scale'):
            item[key] = _number(row[key], key)
        if min(item['width_mm'], item['thickness_mm']) <= 0:
            raise ValueError('Copper width and thickness must be positive.')
        if max(abs(item['x_mm']), abs(item['y_mm'])) > 1e6 or max(
                item['width_mm'], item['thickness_mm']) > 1e4:
            raise ValueError('Cross-section dimensions or coordinates exceed the supported range.')
        out['conductors'].append(item)
    scales = [c['current_scale'] for c in out['conductors']]
    if not any(v > 0 for v in scales) or not any(v < 0 for v in scales) or (
            abs(sum(scales)) > 1e-10 * sum(abs(v) for v in scales)):
        raise ValueError('Explicit outgoing and return current scales must sum to zero.')
    for i, a in enumerate(out['conductors']):
        for b in out['conductors'][i+1:]:
            if (abs(a['x_mm']-b['x_mm']) <= (a['width_mm']+b['width_mm'])/2 and
                    abs(a['y_mm']-b['y_mm']) <= (a['thickness_mm']+b['thickness_mm'])/2):
                raise ValueError('Copper conductors must not touch or overlap.')
    harmonics = study.get('harmonics')
    if not isinstance(harmonics, list) or not 1 <= len(harmonics) <= 32:
        raise ValueError('Provide 1–32 distinct positive-frequency RMS current harmonics.')
    out['harmonics'] = []; frequencies = set()
    span = math.hypot(*[max(c[axis]+c[size]/2 for c in out['conductors'])-
                       min(c[axis]-c[size]/2 for c in out['conductors'])
                       for axis, size in [('x_mm', 'width_mm'), ('y_mm', 'thickness_mm')]])
    for row in harmonics:
        if not isinstance(row, dict) or set(row) != {'frequency_hz', 'current_rms_a'}:
            raise ValueError('Each harmonic needs frequency_hz and current_rms_a.')
        frequency = _number(row['frequency_hz'], 'frequency_hz', minimum=1e-6)
        current = _number(row['current_rms_a'], 'current_rms_a', minimum=0.)
        if current <= 0:
            raise ValueError('Remove zero-current rows; each supplied harmonic needs positive RMS current.')
        if frequency in frequencies:
            raise ValueError('Combine equal-frequency phasors before supplying harmonic RMS currents.')
        frequencies.add(frequency)
        phase = 2*math.pi*frequency*max(out['length_mm'], span)*.001*math.sqrt(out['relative_permittivity'])/299792458.
        if phase > .1:
            raise ValueError('Path or cross-section is electrically too large for this model '
                             '(phase > 0.1 rad). Use a distributed electromagnetic model.')
        out['harmonics'].append({'frequency_hz': frequency, 'current_rms_a': current})
    if not any(h['current_rms_a'] > 0 for h in out['harmonics']):
        raise ValueError('At least one AC harmonic must carry nonzero RMS current.')
    out['harmonics'].sort(key=lambda h: h['frequency_hz'])
    if 'waveform' in study:
        config = study['waveform']
        if not isinstance(config, dict) or set(config) != {
                'kind', 'frequency_hz', 'amplitude_a', 'terms', 'duty', 'dc_current_a'}:
            raise ValueError('Waveform metadata must contain its six original generator inputs.')
        generated = waveform_harmonics(**config)
        if (not math.isclose(out['dc_current_a'], generated['dc_current_a'], rel_tol=1e-10, abs_tol=1e-12) or
                len(out['harmonics']) != len(generated['harmonics']) or any(
                    not math.isclose(a[key], b[key], rel_tol=1e-10, abs_tol=1e-12)
                    for a, b in zip(out['harmonics'], generated['harmonics'])
                    for key in ('frequency_hz', 'current_rms_a'))):
            raise ValueError('Waveform metadata is stale. Regenerate or remove it after editing harmonics.')
        out['waveform'] = generated['waveform']
    return out


def _axis(conductors, coordinate, size, step, skin, padding, refinement):
    """Exact conductor faces plus graded air cells, without snapped copper areas."""
    import numpy as np
    spans = [(c[coordinate]-c[size]/2, c[coordinate]+c[size]/2) for c in conductors]
    anchors = sorted({v for pair in spans for v in pair})
    faces = [anchors[0]]
    for low, high in zip(anchors, anchors[1:]):
        targets = [min(step, (b-a)/4, skin/3)*refinement
                   for a, b in spans if a < (low+high)/2 < b]
        target = min(targets, default=step*refinement)
        count = max(1, math.ceil((high-low)/target))
        # Bound axis construction before allocating a potentially enormous grid.
        if count > 100000 or len(faces)+count > 100000:
            raise ValueError('AC mesh exceeds the cell budget; reduce frequency or simplify the section.')
        faces.extend(np.linspace(low, high, count+1)[1:].tolist())
    for sign in (-1, 1):
        edge = anchors[0] if sign < 0 else anchors[-1]
        walked = 0.; increment = step*refinement; outer = []
        while walked < padding:
            walked = min(padding, walked+increment)
            outer.append(edge+sign*walked); increment *= 1.5
        faces = list(reversed(outer))+faces if sign < 0 else faces+outer
    return np.asarray(faces)*.001


def _mesh(study, rho, refinement, padding_factor):
    import numpy as np
    from scipy import sparse
    conductors = study['conductors']
    skin = math.sqrt(rho/(math.pi*MU0*max(h['frequency_hz'] for h in study['harmonics'])))*1000
    args = (study['mesh_step_mm'], skin, study['air_padding_mm']*padding_factor, refinement)
    xf = _axis(conductors, 'x_mm', 'width_mm', *args)
    yf = _axis(conductors, 'y_mm', 'thickness_mm', *args)
    dx = np.diff(xf); dy = np.diff(yf); nx = len(dx); ny = len(dy); n = nx*ny
    if n > study['max_cells']:
        raise ValueError(f'AC mesh needs {n} cells, above max_cells={study["max_cells"]}. '
                         'Increase the explicit budget or simplify the section; skin resolution was not coarsened.')
    x = (xf[1:]+xf[:-1])/2; y = (yf[1:]+yf[:-1])/2
    xx, yy = np.meshgrid(x, y); area = (dy[:, None]*dx[None, :]).ravel()
    labels = np.full(n, -1, dtype=int)
    for k, c in enumerate(conductors):
        inside = ((abs(xx-c['x_mm']*.001) < c['width_mm']*.0005) &
                  (abs(yy-c['y_mm']*.001) < c['thickness_mm']*.0005)).ravel()
        labels[inside] = k
        expected = c['width_mm']*c['thickness_mm']*1e-6
        if not math.isclose(float(area[inside].sum()), expected, rel_tol=1e-9):
            raise RuntimeError('AC mesh failed to preserve a copper cross-sectional area.')
    ids = np.arange(n).reshape(ny, nx); diagonal = np.zeros(n); rows = []; cols = []; values = []
    for a, b, weight in [
            (ids[:, :-1].ravel(), ids[:, 1:].ravel(),
             np.broadcast_to(dy[:, None]/((dx[:-1]+dx[1:])/2)[None, :], (ny, nx-1)).ravel()),
            (ids[:-1, :].ravel(), ids[1:, :].ravel(),
             np.broadcast_to(dx[None, :]/((dy[:-1]+dy[1:])/2)[:, None], (ny-1, nx)).ravel())]:
        np.add.at(diagonal, a, weight); np.add.at(diagonal, b, weight)
        rows.extend([a, b]); cols.extend([b, a]); values.extend([-weight, -weight])
    diagonal[ids[:, 0]] += 2*dy/dx[0]; diagonal[ids[:, -1]] += 2*dy/dx[-1]
    diagonal[ids[0, :]] += 2*dx/dy[0]; diagonal[ids[-1, :]] += 2*dx/dy[-1]
    rows.append(np.arange(n)); cols.append(np.arange(n)); values.append(diagonal)
    k_matrix = sparse.csc_matrix((np.concatenate(values),
                                  (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    metal = np.flatnonzero(labels >= 0)
    c_matrix = sparse.csc_matrix((area[metal]/rho, (metal, labels[metal])), shape=(n, len(conductors)))
    sigma_area = np.zeros(n); sigma_area[metal] = area[metal]/rho
    return {'k': k_matrix, 'c': c_matrix, 's': sparse.diags(sigma_area, format='csc'),
            'g': sparse.diags(np.asarray(c_matrix.sum(axis=0)).ravel(), format='csc'),
            'area': area, 'labels': labels, 'metal': metal,
            'x': xx.ravel(), 'y': yy.ravel(), 'dx': np.tile(dx, ny), 'dy': np.repeat(dy, nx),
            'cells': n, 'skin_depth_mm': skin}


def _frequency(mesh, study, rho, frequency):
    """Solve (K+jωμS)u−jωμCE=0, −Cᵀu+GE=I, where u=jωA."""
    import numpy as np
    from scipy import sparse
    from scipy.sparse.linalg import splu
    omega = 2*math.pi*frequency; scale = np.asarray([c['current_scale'] for c in study['conductors']])
    matrix = sparse.bmat([[mesh['k']+1j*omega*MU0*mesh['s'], -1j*omega*MU0*mesh['c']],
                          [-mesh['c'].T, mesh['g']]], format='csc')
    rhs = np.concatenate([np.zeros(mesh['cells']), scale]).astype(complex)
    solution = splu(matrix).solve(rhs)
    if not np.isfinite(solution).all():
        raise RuntimeError('AC field solve returned non-finite values.')
    field = solution[mesh['cells']:]; ids = mesh['metal']; labels = mesh['labels'][ids]
    density = (field[labels]-solution[ids])/rho
    currents = np.bincount(labels, weights=density.real*mesh['area'][ids], minlength=len(scale))+1j*np.bincount(
        labels, weights=density.imag*mesh['area'][ids], minlength=len(scale))
    current_error = float(np.max(abs(currents-scale))/float(np.max(abs(scale))))
    length = study['length_mm']*.001
    impedance = complex(np.dot(scale, field)*length)
    loss = rho*abs(density)**2*mesh['area'][ids]*length
    power_error = abs(float(loss.sum())-impedance.real)/max(float(loss.sum()), 1e-300)
    if current_error > 1e-7 or power_error > 1e-7 or impedance.real <= 0 or impedance.imag < -1e-12:
        raise RuntimeError('AC current conservation, passivity or Joule power balance failed.')
    return {'impedance': impedance, 'density': density, 'loss': loss,
            'current_error': current_error, 'power_error': power_error}


def _run_study(study):
    """Solve DC plus prescribed AC harmonics with mesh and air-box checks.

    Returns JSON-compatible RMS densities, copper watts and complex loop
    impedances. UNCONVERGED results remain provisional, never a pass verdict.
    The final field is the finer mesh with the enlarged magnetic boundary.
    """
    import numpy as np
    study = validate_study(study)
    rho = 1.7241e-8*(1+.00393*(study['temperature_c']-20.))
    length = study['length_mm']*.001
    fine = _mesh(study, rho, .5, 1.)
    active_harmonics = [h for h in study['harmonics'] if h['current_rms_a'] > 0]
    fine_solved = [_frequency(fine, study, rho, h['frequency_hz']) for h in active_harmonics]
    def error(left, right):
        return max(abs(left.real-right.real)/right.real, abs(left-right)/abs(right))
    previous = fine_solved; boundary_history = []
    for enlargement in range(1, 5):
        padding_factor = 2.**enlargement
        final = _mesh(study, rho, .5, padding_factor)
        final_solved = [_frequency(final, study, rho, h['frequency_hz']) for h in active_harmonics]
        boundary_errors = [error(a['impedance'], b['impedance']) for a, b in zip(previous, final_solved)]
        boundary_history.append({'padding_mm': study['air_padding_mm']*padding_factor,
                                 'relative_error': max(boundary_errors), 'cells': final['cells']})
        if max(boundary_errors) <= study['convergence_tolerance']:
            break
        previous = final_solved
    # Compare mesh levels at the same final boundary; otherwise moving the
    # magnetic boundary could conceal a discretization error in the copper.
    coarse = _mesh(study, rho, 1., padding_factor)
    coarse_solved = [_frequency(coarse, study, rho, h['frequency_hz']) for h in active_harmonics]
    scales = np.asarray([c['current_scale'] for c in study['conductors']])
    areas = np.asarray([c['width_mm']*c['thickness_mm']*1e-6 for c in study['conductors']])
    dc_by_conductor = rho*length/areas*(scales*study['dc_current_a'])**2
    dc_resistance = float(np.sum(rho*length/areas*scales**2))
    ids = final['metal']; labels = final['labels'][ids]
    density_squared = (scales[labels]*study['dc_current_a']/areas[labels])**2
    ac_by_conductor = np.zeros(len(scales)); harmonics = []; mesh_errors = []
    for index, h in enumerate(active_harmonics):
        solved = [coarse_solved[index], final_solved[index], final_solved[index]]
        a, b, c = [r['impedance'] for r in solved]
        mesh_errors.append(error(a, b))
        current = h['current_rms_a']; row = solved[-1]
        density_squared += abs(row['density'])**2*current**2
        losses = row['loss']*current**2
        ac_by_conductor += np.bincount(labels, weights=losses, minlength=len(scales))
        harmonics.append({**h, 'resistance_ohm': c.real, 'reactance_ohm': c.imag,
                          'impedance_ohm': abs(c), 'voltage_rms_v': abs(c)*current,
                          'loss_w': float(losses.sum()),
                          'skin_depth_mm': math.sqrt(rho/(math.pi*MU0*h['frequency_hz']))*1000,
                          'ac_dc_resistance_ratio': c.real/dc_resistance,
                          'mesh_relative_error': mesh_errors[-1], 'boundary_relative_error': boundary_errors[index],
                          'power_balance_relative_error': row['power_error'],
                          'current_relative_error': row['current_error']})
    checks = {'mesh_relative_error': max(mesh_errors), 'boundary_relative_error': max(boundary_errors),
              'current_relative_error': max(h['current_relative_error'] for h in harmonics),
              'power_relative_error': max(h['power_balance_relative_error'] for h in harmonics),
              'convergence_tolerance': study['convergence_tolerance'],
              'convergence_scope': 'Global loop impedance only; local peak current density is not convergence-qualified.'}
    converged = max(checks['mesh_relative_error'], checks['boundary_relative_error']) <= study['convergence_tolerance']
    dc_loss = float(dc_by_conductor.sum()); ac_loss = float(ac_by_conductor.sum())
    ripple_v = math.sqrt(sum(h['voltage_rms_v']**2 for h in harmonics))
    cells = [{'x_mm': float(final['x'][i]*1000), 'y_mm': float(final['y'][i]*1000),
              'width_mm': float(final['dx'][i]*1000), 'height_mm': float(final['dy'][i]*1000),
              'conductor': study['conductors'][int(final['labels'][i])]['name'],
              'current_density_rms_a_mm2': float(math.sqrt(density_squared[k])*1e-6),
              'loss_density_w_mm3': float(rho*density_squared[k]*1e-9)} for k, i in enumerate(ids)]
    return {'schema': 'wayricad.pi-ac-result/v1', 'status': 'CONVERGED' if converged else 'UNCONVERGED',
            'model': '2D magnetoquasistatic current-constrained finite-volume copper cross-section',
            'study': study, 'temperature_c': study['temperature_c'], 'resistivity_ohm_m': rho,
            'dc_resistance_ohm': dc_resistance, 'dc_loss_w': dc_loss, 'ac_loss_w': ac_loss,
            'total_loss_w': dc_loss+ac_loss, 'ripple_voltage_rms_v': ripple_v,
            'ripple_voltage_ratio': ripple_v/study['reference_voltage_v'] if study['reference_voltage_v'] else None,
            'total_current_rms_a': math.sqrt(study['dc_current_a']**2+sum(h['current_rms_a']**2 for h in harmonics)),
            'waveform_band': waveform_harmonics(**study['waveform']) if 'waveform' in study else {
                'notice': 'Only supplied harmonics are included; omitted frequency content and switching edges are unknown.'},
            'harmonics': harmonics, 'conductors': [
                {'name': c['name'], 'dc_loss_w': float(dc_by_conductor[k]),
                 'ac_loss_w': float(ac_by_conductor[k]),
                 'total_loss_w': float(dc_by_conductor[k]+ac_by_conductor[k])}
                for k, c in enumerate(study['conductors'])],
            'cells': cells, 'checks': checks,
            'mesh': {'coarse_cells': coarse['cells'], 'fine_cells': final['cells'],
                     'final_cells': final['cells'], 'copper_cells': len(cells),
                     'air_padding_mm': study['air_padding_mm']*padding_factor,
                     'boundary_history': boundary_history},
            'assumptions': ['RMS harmonic phasors; powers add across distinct frequencies.',
                            'Explicit balanced real conductor-current scales; copper permeability μ0.',
                            'Uniform prescribed temperature; linear copper resistivity referenced to 20°C.',
                            'Zero axial magnetic potential at the finite air-box boundary, checked by enlargement.',
                            'Reference voltage is context; permittivity is used only for the electrical-length guard.'],
            'limitations': list(LIMITATIONS), 'references': list(REFERENCES)}


def run_study(study):
    """Return finite JSON evidence, rejecting overflow rather than exporting NaN."""
    import numpy as np
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            result = _run_study(study)
        def finite(value):
            if isinstance(value, dict):
                for item in value.values(): finite(item)
            elif isinstance(value, list):
                for item in value: finite(item)
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError('AC inputs exceed the finite numerical range.')
        finite(result)
        return result
    except (OverflowError, FloatingPointError) as exc:
        raise ValueError('AC inputs exceed the finite numerical range; reduce magnitudes.') from exc


def waveform_harmonics(kind, frequency_hz, amplitude_a, terms=8, duty=.5, dc_current_a=0.):
    """Generate RMS Fourier terms for triangular ripple or unipolar PWM current.

    Triangle amplitude is peak-to-peak and its supplied DC mean is retained.
    Pulse amplitude is the on-state current and its mean is amplitude*duty.
    terms is the maximum harmonic order, not a promise that omitted edge
    harmonics are unimportant. The omitted RMS current is reported explicitly.
    """
    frequency = _number(frequency_hz, 'frequency_hz', minimum=1e-6)
    amplitude = _number(amplitude_a, 'amplitude_a', minimum=0.)
    mean = _number(dc_current_a, 'dc_current_a')
    if isinstance(terms, bool) or not isinstance(terms, int) or not 1 <= terms <= 32:
        raise ValueError('Waveform harmonic order must be an integer from 1 to 32.')
    if kind not in ('triangle', 'pulse'):
        raise ValueError('Choose triangle ripple or pulse current.')
    duty = _number(duty, 'duty', minimum=1e-6, maximum=1-1e-6)
    rows = []
    for n in range(1, terms+1):
        sine = abs(math.sin(math.pi*n*duty))
        current = (2*math.sqrt(2)*amplitude/(math.pi*n)**2 if n % 2 else 0.) if kind == 'triangle' else (
            math.sqrt(2)*amplitude*sine/(math.pi*n) if sine > 1e-14 else 0.)
        if current > 0:
            rows.append({'frequency_hz': frequency*n, 'current_rms_a': current})
    # Normalize before squaring so extreme amplitudes fail predictably below.
    retained_ratio = math.sqrt(sum((r['current_rms_a']/amplitude)**2 for r in rows)) if amplitude else 0.
    total_ratio = 1/math.sqrt(12) if kind == 'triangle' else math.sqrt(duty*(1-duty))
    retained = amplitude*retained_ratio
    omitted = amplitude*math.sqrt(max(0., total_ratio**2-retained_ratio**2))
    if not all(math.isfinite(v) for v in (retained, omitted, frequency*terms)):
        raise ValueError('Waveform inputs exceed the finite numerical range.')
    return {'waveform': {'kind': kind, 'frequency_hz': frequency, 'amplitude_a': amplitude,
                         'terms': terms, 'duty': duty, 'dc_current_a': mean},
            'dc_current_a': mean if kind == 'triangle' else amplitude*duty,
            'harmonics': rows, 'retained_rms_a': retained, 'omitted_rms_a': omitted,
            'notice': 'Finite Fourier band only. Omitted current harmonics can have disproportionate AC loss; '
                      'specify measured bandwidth/edge spectra for a real SMPS.'}
