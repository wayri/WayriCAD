"""Bounded two-port MQS extraction; no GUI imports or board inference."""
from __future__ import annotations

import math
import threading
from concurrent.futures import CancelledError

from . import ac_analysis as ac

SCHEMA = 'wayricad.pi-ac-ports/v1'
LIMITATIONS = list(ac.LIMITATIONS) + [
    'Open circuit means zero net current in the unexcited port, not zero local eddy current.',
    'Explicit straight cross-section only; not a Palace integration or full-board extraction.',
    'Convergence is numerical sensitivity of the impedance matrix, not measurement validation.',
]


def validate_study(study):
    """Translate explicit port loops into the existing AC validator's contract."""
    import numpy as np
    if not isinstance(study, dict) or set(study) != {
            'schema', 'cross_section', 'ports', 'frequencies_hz'} or study['schema'] != SCHEMA:
        raise ValueError('Expected schema, cross_section, ports and frequencies_hz for ' + SCHEMA)
    section = study['cross_section']
    allowed = {'temperature_c', 'length_mm', 'relative_permittivity', 'conductors',
               'mesh_step_mm', 'air_padding_mm', 'max_cells', 'convergence_tolerance'}
    if not isinstance(section, dict) or set(section) - allowed:
        raise ValueError('cross_section contains unknown fields; currents are defined only by ports.')
    conductors = section.get('conductors')
    if not isinstance(conductors, list) or not 2 <= len(conductors) <= 16:
        raise ValueError('Provide 2-16 rectangular conductors.')
    names = []
    for conductor in conductors:
        if not isinstance(conductor, dict) or set(conductor) != {
                'name', 'x_mm', 'y_mm', 'width_mm', 'thickness_mm'}:
            raise ValueError('Each conductor needs name, x_mm, y_mm, width_mm, thickness_mm.')
        name = conductor['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('Conductor names must be unique nonempty strings of at most 80 characters.')
        names.append(name)
    ports = study['ports']
    if not isinstance(ports, list) or len(ports) != 2:
        raise ValueError('Exactly two explicit independent ports are required.')
    b = np.zeros((len(names), 2))
    port_names = set()
    for j, port in enumerate(ports):
        if not isinstance(port, dict) or set(port) != {'name', 'positive', 'negative'}:
            raise ValueError('Each port needs name, positive and negative conductor names.')
        name = port['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in port_names:
            raise ValueError('Port names must be distinct nonempty strings of at most 80 characters.')
        port_names.add(name)
        positive, negative = port['positive'], port['negative']
        if (not isinstance(positive, str) or not isinstance(negative, str) or
                positive not in names or negative not in names or positive == negative):
            raise ValueError('Port terminals must name two distinct existing conductors.')
        b[names.index(positive), j] = 1.
        b[names.index(negative), j] = -1.
    if np.linalg.matrix_rank(b) != 2:
        raise ValueError('Port current loops must be linearly independent; reversal is not a second port.')
    frequencies = study['frequencies_hz']
    if not isinstance(frequencies, list) or not 1 <= len(frequencies) <= 32:
        raise ValueError('Provide 1-32 distinct positive finite frequencies_hz.')
    backend = {**section, 'schema': 'wayricad.pi-ac/v1',
               'conductors': [{**c, 'current_scale': float(b[i, 0])}
                              for i, c in enumerate(conductors)],
               'harmonics': [{'frequency_hz': f, 'current_rms_a': 1.} for f in frequencies]}
    backend = ac.validate_study(backend)
    normalized = {'schema': SCHEMA, 'cross_section': {
        k: backend[k] for k in allowed if k != 'conductors'},
        'ports': [dict(p) for p in ports],
        'frequencies_hz': [h['frequency_hz'] for h in backend['harmonics']]}
    normalized['cross_section']['conductors'] = [
        {k: v for k, v in c.items() if k != 'current_scale'} for c in backend['conductors']]
    return normalized, backend, b


def _checkpoint(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('Two-port solve cancelled.')


def _frequency(mesh, study, rho, frequency, b):
    """The ac_analysis equations with two simultaneous unit-current RHS columns."""
    import numpy as np
    from scipy import sparse
    from scipy.sparse.linalg import splu
    omega = 2 * math.pi * frequency
    matrix = sparse.bmat([
        [mesh['k'] + 1j * omega * ac.MU0 * mesh['s'], -1j * omega * ac.MU0 * mesh['c']],
        [-mesh['c'].T, mesh['g']]], format='csc')
    rhs = np.vstack((np.zeros((mesh['cells'], 2)), b)).astype(complex)
    solution = splu(matrix).solve(rhs)
    if not np.isfinite(solution).all():
        raise RuntimeError('Non-finite two-port field solution.')
    field = solution[mesh['cells']:]
    ids = mesh['metal']
    labels = mesh['labels'][ids]
    density = (field[labels] - solution[ids]) / rho
    currents = np.column_stack([
        np.bincount(labels, weights=density[:, j].real * mesh['area'][ids], minlength=len(b)) +
        1j * np.bincount(labels, weights=density[:, j].imag * mesh['area'][ids], minlength=len(b))
        for j in range(2)])
    z = b.T @ field * (study['length_mm'] * .001)
    hermitian = (z + z.conj().T) / 2
    joule = density.conj().T @ (density * mesh['area'][ids, None]) * rho * study['length_mm'] * .001
    norm = max(float(np.linalg.norm(z)), 1e-300)
    power_norm = max(float(np.linalg.norm(joule)), 1e-300)
    checks = {'current_relative_error': float(np.max(abs(currents - b))),
              'net_current_error_a': float(np.max(abs(currents.sum(axis=0)))),
              'reciprocity_relative_error': float(np.linalg.norm(z - z.T) / norm),
              'power_relative_error': float(np.linalg.norm(hermitian - joule) / power_norm),
              'hermitian_min_eigenvalue_ohm': float(np.linalg.eigvalsh(hermitian).min())}
    if (max(checks[k] for k in ('current_relative_error', 'net_current_error_a',
                               'reciprocity_relative_error', 'power_relative_error')) > 1e-7 or
            checks['hermitian_min_eigenvalue_ohm'] < -1e-10 * norm):
        raise RuntimeError('Two-port conservation, reciprocity, passivity or Joule balance failed.')
    return z, checks


def _difference(left, right):
    """Entrywise port-scaled complex error plus dissipative-matrix error."""
    import numpy as np
    scale = np.sqrt(abs(np.diag(right))[:, None] * abs(np.diag(right))[None, :])
    return max(float(np.max(abs(left-right) / np.maximum(scale, 1e-300))),
               float(np.linalg.norm(left.real-right.real) /
                     max(float(np.linalg.norm(right.real)), 1e-300)))


def _complex_matrix(matrix):
    return [[{'real': float(v.real), 'imag': float(v.imag)} for v in row] for row in matrix]


def _run(study, cancel):
    import numpy as np
    normalized, section, b = validate_study(study)
    rho = 1.7241e-8 * (1 + .00393 * (section['temperature_c'] - 20.))
    frequencies = normalized['frequencies_hz']
    counts = {'factorizations': 0, 'multi_rhs_solves': 0, 'rhs_columns_per_solve': 2,
              'meshes': 0}

    def solve(refinement, padding):
        _checkpoint(cancel)
        mesh = ac._mesh(section, rho, refinement, padding)
        counts['meshes'] += 1
        results = []
        for frequency in frequencies:
            _checkpoint(cancel)
            results.append(_frequency(mesh, section, rho, frequency, b))
            counts['factorizations'] += 1
            counts['multi_rhs_solves'] += 1
        _checkpoint(cancel)
        return mesh['cells'], results

    _, previous = solve(.5, 1.)
    history = []
    for enlargement in range(1, 5):
        padding = 2. ** enlargement
        fine_cells, final = solve(.5, padding)
        boundary_errors = [_difference(a[0], c[0]) for a, c in zip(previous, final)]
        history.append({'air_padding_mm': section['air_padding_mm'] * padding,
                        'relative_error': max(boundary_errors), 'cells': fine_cells})
        if max(boundary_errors) <= section['convergence_tolerance']:
            break
        previous = final
    coarse_cells, coarse = solve(1., padding)
    rows = []
    for frequency, (z, checks), comparison, boundary in zip(frequencies, final, coarse, boundary_errors):
        mesh_error = _difference(comparison[0], z)
        rows.append({'frequency_hz': frequency, 'z_ohm': _complex_matrix(z), 'checks': {
            **checks, 'mesh_relative_error': mesh_error, 'boundary_relative_error': boundary}})
    converged = all(max(row['checks']['mesh_relative_error'], row['checks']['boundary_relative_error'])
                    <= section['convergence_tolerance'] for row in rows)
    areas = np.asarray([c['width_mm'] * c['thickness_mm'] * 1e-6 for c in section['conductors']])
    dc = b.T @ np.diag(rho * section['length_mm'] * .001 / areas) @ b
    return {'schema': SCHEMA, 'kind': 'result', 'study': normalized,
            'status': 'CONVERGED' if converged else 'PROVISIONAL',
            'model': '2D MQS current-constrained rectangular copper cross-section',
            'units': {'frequency': 'Hz', 'impedance': 'ohm', 'input_geometry': 'mm',
                      'temperature': 'degC', 'resistivity': 'ohm m'},
            'phasor_convention': 'RMS, exp(+j omega t); V = Z I; rows are observed ports',
            'resistivity_ohm_m': rho, 'dc_resistance_ohm': dc.tolist(), 'frequencies': rows,
            'mesh': {'fine_cells': fine_cells, 'coarse_cells': coarse_cells,
                     'final_air_padding_mm': section['air_padding_mm'] * padding,
                     'boundary_history': history}, 'work': counts,
            'convergence': {'tolerance': section['convergence_tolerance'],
                            'scope': 'Matrix entries scaled by diagonal port impedances plus real-matrix norm; '
                                     'no local-field or physical qualification.'},
            'limitations': list(LIMITATIONS), 'references': list(ac.REFERENCES)}


def run_study(study, *, cancel=None):
    """Return finite JSON envelope. Cancellation is cooperative between sparse solves."""
    import json
    import numpy as np
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            result = _run(study, cancel)
        json.dumps(result, allow_nan=False)
        return result
    except (OverflowError, FloatingPointError) as exc:
        raise ValueError('Two-port inputs exceed the finite numerical range.') from exc


class LatestRun:
    """One bounded worker, one replaceable pending request; callbacks recheck lifetime."""

    def __init__(self, dispatch, receive, solver=run_study):
        self.dispatch, self.receive, self.solver = dispatch, receive, solver
        self.lock = threading.Lock()
        self.generation = 0
        self.closed = False
        self.pending = None
        self.active_cancel = None
        self.worker = None

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.pending = None
            if self.active_cancel is not None:
                self.active_cancel.set()

    def close(self):
        self.invalidate()
        with self.lock:
            self.closed = True

    def submit(self, study):
        import copy
        with self.lock:
            if self.closed:
                return
            self.generation += 1
            if self.active_cancel is not None:
                self.active_cancel.set()
            self.pending = (self.generation, copy.deepcopy(study))
            if self.worker is None:
                self.worker = threading.Thread(target=self._work, daemon=True)
                self.worker.start()

    def _deliver(self, ticket, result, error):
        with self.lock:
            valid = not self.closed and ticket == self.generation
        if valid:
            self.receive(result, error)

    def _work(self):
        while True:
            with self.lock:
                if self.closed or self.pending is None:
                    self.worker = None
                    return
                ticket, study = self.pending
                self.pending = None
                cancel = self.active_cancel = threading.Event()
            result = error = None
            try:
                result = self.solver(study, cancel=cancel)
            except Exception as exc:
                error = exc
            self.dispatch(self._deliver, ticket, result, error)
