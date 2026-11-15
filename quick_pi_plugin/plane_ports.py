"""Explicit triangular parallel-plate PDN cavity, not MQS board extraction."""
from __future__ import annotations

import math
from concurrent.futures import CancelledError

SCHEMA = 'wayricad.pi-plane-ports/v1'
MU0 = 4e-7 * math.pi
EPS0 = 8.8541878128e-12
REFERENCES = [
    {'title': 'COMSOL: TEM/quasi-TEM lines, magnetic walls and conductor losses',
     'url': 'https://www.comsol.com/support/learning-center/article/modeling-tem-and-quasi-tem-transmission-lines-21971'},
    {'title': 'MIT Electromagnetics and Applications: waveguides and cavity resonators',
     'url': 'https://ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/MIT6_013S09_chap09.pdf'},
    {'title': 'SciPy SuperLU: multiple right-hand sides',
     'url': 'https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.SuperLU.solve.html'},
]
LIMITATIONS = [
    'Explicit homogeneous parallel-plate quasi-TEM cavity, not inferred PCB geometry or a Palace integration.',
    'Magnetic walls are perfectly reflecting Neumann edges; no fringing, edge radiation or boundary sinks.',
    'One resistive copper sheet and one ideal equipotential reference plane; real return-plane losses are omitted.',
    'Real sheet resistance max(rho/t, sqrt(pi*f*mu0*rho)) is an approximate DC/skin envelope with a kink; '
    'no internal conductor inductance, roughness or exact finite-thickness surface impedance.',
    'No vias, launches, plane-stack coupling, discrete components, dielectric dispersion, or higher transverse modes.',
    'Explicit conforming triangle mesh required; no automatic refinement, mesh convergence or physical validation claim.',
    'Topology and local element checks do not certify absence of global self-intersections in a supplied mesh.',
    'Point-node ports can be mesh-sensitive; finite port weights must be preserved physically during refinement.',
    'A sampled frequency sweep can miss narrow resonances. No measured or Palace performance comparison is supplied.',
]


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + ' must be a finite number.')
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(name + ' must be finite.') from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(name + ' is outside its supported range.')
    return value


def _index(value, count):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
        raise ValueError('Mesh and port indices must be zero-based integers in the vertex range.')
    return value


def validate_study(study):
    """Validate bounded explicit inputs; return normalized JSON-compatible study."""
    import numpy as np
    required = {'schema', 'vertices_mm', 'triangles', 'ports', 'reference_plane',
                'dielectric_height_mm', 'epsr', 'tandelta', 'copper_thickness_mm',
                'resistivity_ohm_m', 'frequencies_hz'}
    if not isinstance(study, dict) or not required <= set(study) or set(study) - required - {'temperature_c'}:
        raise ValueError('Plane study has missing or unknown fields.')
    if study['schema'] != SCHEMA or study['reference_plane'] != 'ideal':
        raise ValueError('Use schema ' + SCHEMA + ' and reference_plane="ideal".')
    out = {'schema': SCHEMA, 'reference_plane': 'ideal'}
    for key, low, high in [('dielectric_height_mm', 1e-6, 100.), ('epsr', 1., 100.),
                           ('tandelta', 0., 1.), ('copper_thickness_mm', 1e-6, 10.),
                           ('resistivity_ohm_m', 1e-12, 1e-4), ('temperature_c', -40., 200.)]:
        out[key] = _number(study.get(key, 20.), key, low, high)
    vertices = study['vertices_mm']
    if not isinstance(vertices, list) or not 3 <= len(vertices) <= 50000:
        raise ValueError('Provide 3-50000 explicit vertices_mm.')
    out['vertices_mm'] = []
    for vertex in vertices:
        if not isinstance(vertex, list) or len(vertex) != 2:
            raise ValueError('Each vertex must be [x_mm, y_mm].')
        out['vertices_mm'].append([_number(v, 'vertex coordinate (mm)', -1e6, 1e6) for v in vertex])
    if len({tuple(v) for v in out['vertices_mm']}) != len(vertices):
        raise ValueError('Duplicate vertex coordinates are not a conforming mesh.')
    triangles = study['triangles']
    if not isinstance(triangles, list) or not 1 <= len(triangles) <= 100000:
        raise ValueError('Provide 1-100000 explicit triangles.')
    out['triangles'] = []
    seen = set()
    for triangle in triangles:
        if not isinstance(triangle, list) or len(triangle) != 3:
            raise ValueError('Each triangle must have three vertex indices.')
        row = [_index(i, len(vertices)) for i in triangle]
        canonical = tuple(sorted(row))
        if len(set(row)) != 3 or canonical in seen:
            raise ValueError('Repeated-node or duplicate triangle.')
        seen.add(canonical)
        out['triangles'].append(row)
    xy = np.asarray(out['vertices_mm']) * .001
    tri = np.asarray(out['triangles'])
    _topology(xy, tri)
    ports = study['ports']
    if not isinstance(ports, list) or len(ports) != 2:
        raise ValueError('Exactly two distinct positive-node port groups are required.')
    out['ports'] = []
    used = set()
    names = set()
    for port in ports:
        if not isinstance(port, dict) or set(port) != {'name', 'nodes', 'weights'}:
            raise ValueError('Each port needs exactly name, nodes and weights.')
        name = port['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('Port names must be distinct nonempty strings of at most 80 characters.')
        names.add(name)
        nodes, weights = port['nodes'], port['weights']
        if (not isinstance(nodes, list) or not nodes or len(nodes) > len(vertices) or
                not isinstance(weights, list) or len(weights) != len(nodes)):
            raise ValueError('Each port needs equal nonempty node and positive-weight lists.')
        nodes = [_index(i, len(vertices)) for i in nodes]
        if len(set(nodes)) != len(nodes) or used.intersection(nodes):
            raise ValueError('Port node groups must be distinct and disjoint, with no duplicate nodes.')
        used.update(nodes)
        weights = [_number(w, 'port weight', 1e-300, 1.) for w in weights]
        total = math.fsum(weights)
        if not math.isclose(total, 1., rel_tol=0., abs_tol=1e-12):
            raise ValueError('Positive port weights must sum to one.')
        out['ports'].append({'name': name, 'nodes': nodes, 'weights': [w/total for w in weights]})
    frequencies = study['frequencies_hz']
    if not isinstance(frequencies, list) or not 1 <= len(frequencies) <= 512:
        raise ValueError('Provide 1-512 distinct finite frequencies_hz; DC is not supported.')
    frequencies = [_number(f, 'frequency_hz', 1e4, 1e10) for f in frequencies]
    if len(set(frequencies)) != len(frequencies):
        raise ValueError('Frequencies must be distinct.')
    out['frequencies_hz'] = sorted(frequencies)
    ratio = out['dielectric_height_mm'] * .001 * max(frequencies) * math.sqrt(MU0 * EPS0 * out['epsr'])
    if ratio >= .1:
        raise ValueError('Dielectric height / in-medium wavelength must be < 0.1 for the quasi-TEM model.')
    return out


def _topology(xy, tri):
    """Reject unused vertices, degenerate elements, nonmanifold edges and islands."""
    import numpy as np
    p = xy[tri]
    e1, e2 = p[:, 1]-p[:, 0], p[:, 2]-p[:, 0]
    cross = e1[:, 0]*e2[:, 1]-e1[:, 1]*e2[:, 0]
    edge_squared = np.maximum.reduce([np.sum(e1**2, axis=1), np.sum(e2**2, axis=1),
                                     np.sum((p[:, 2]-p[:, 1])**2, axis=1)])
    if np.any(abs(cross) <= 1e-12 * edge_squared) or np.any(abs(cross) < 2e-24):
        raise ValueError('Triangles must have positive area and nondegenerate shape (either orientation).')
    if len(np.unique(tri)) != len(xy):
        raise ValueError('All vertices must belong to the triangle mesh.')
    # Edge-connected triangles reject even islands touching at just one vertex.
    parent = list(range(len(tri)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = {}
    for i, row in enumerate(tri):
        for a, b, opposite in ((row[0], row[1], row[2]), (row[1], row[2], row[0]),
                                (row[2], row[0], row[1])):
            key = (min(a, b), max(a, b))
            if key not in edges:
                edges[key] = (i, opposite, False)
            else:
                previous, other, paired = edges[key]
                if paired:
                    raise ValueError('Nonmanifold mesh edge belongs to more than two triangles.')
                direction = xy[b]-xy[a]
                u, v = xy[opposite]-xy[a], xy[other]-xy[a]
                if (direction[0]*u[1]-direction[1]*u[0]) * (direction[0]*v[1]-direction[1]*v[0]) >= 0:
                    raise ValueError('Adjacent triangles overlap on the same side of a shared edge.')
                parent[root(i)] = root(previous)
                edges[key] = (previous, other, True)
    if len({root(i) for i in range(len(tri))}) != 1:
        raise ValueError('Mesh must be one edge-connected plane; separate islands are unsupported.')


def _assemble(study):
    import numpy as np
    from scipy import sparse
    xy = np.asarray(study['vertices_mm']) * .001
    tri = np.asarray(study['triangles'])
    p = xy[tri]
    d1, d2 = p[:, 1]-p[:, 0], p[:, 2]-p[:, 0]
    twice_area = abs(d1[:, 0]*d2[:, 1]-d1[:, 1]*d2[:, 0])
    # Each numerator is 2*signed_area*grad(Ni); the sign cancels in K.
    gradients = np.stack((p[:, [1, 2, 0], 1]-p[:, [2, 0, 1], 1],
                          p[:, [2, 0, 1], 0]-p[:, [1, 2, 0], 0]), axis=2)
    local = np.einsum('tik,tjk->tij', gradients, gradients) / (2*twice_area[:, None, None])
    n = len(xy)
    rows = np.broadcast_to(tri[:, :, None], local.shape).ravel()
    cols = np.broadcast_to(tri[:, None, :], local.shape).ravel()
    k = sparse.coo_matrix((local.ravel(), (rows, cols)), shape=(n, n)).tocsc()
    area = np.zeros(n)
    np.add.at(area, tri.ravel(), np.repeat(twice_area/6, 3))
    capacitance = area * EPS0 * study['epsr'] / (study['dielectric_height_mm']*.001)
    b = np.zeros((n, 2))
    for j, port in enumerate(study['ports']):
        b[port['nodes'], j] = port['weights']
    return k, capacitance, b, float(twice_area.sum()/2)


def _checkpoint(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('Plane-port solve cancelled.')


def _frequency(k, capacitance, b, study, rho, frequency):
    import numpy as np
    from scipy import sparse
    from scipy.sparse.linalg import splu
    omega = 2*math.pi*frequency
    sheet_r = max(rho/(study['copper_thickness_mm']*.001), math.sqrt(math.pi*frequency*MU0*rho))
    sheet_z = sheet_r + 1j*omega*MU0*study['dielectric_height_mm']*.001
    shunt = omega*(study['tandelta']+1j)*capacitance
    y = k/sheet_z + sparse.diags(shunt, format='csc')
    # Separate the exact uniform-capacitor mode. Direct Y solves at low f lose
    # digits by subtracting enormous nearly equal nodal voltages in K @ V.
    total_c = float(capacitance.sum())
    c_column = sparse.csc_matrix(capacitance[:, None])
    augmented = sparse.bmat([[y, c_column], [c_column.T, None]], format='csc')
    centered_b = b-capacitance[:, None]/total_c
    rhs = np.vstack((centered_b, np.zeros((1, 2)))).astype(complex)
    solution = splu(augmented).solve(rhs)
    fluctuation = solution[:-1]
    uniform_v = 1/(omega*(study['tandelta']+1j)*total_c)
    v = fluctuation+uniform_v
    if not np.isfinite(solution).all() or not np.isfinite(v).all():
        raise RuntimeError('Nonfinite plane voltage solution.')
    z = b.T @ v
    norm = max(float(np.linalg.norm(z)), 1e-300)
    residual = float(np.linalg.norm(y @ fluctuation-centered_b)/max(float(np.linalg.norm(b)), 1e-300))
    plane_return = -np.sum(shunt[:, None]*v, axis=0)
    # This checks arbitrary complex superpositions, not just diagonal power.
    loss = (1/sheet_z).real * (fluctuation.conj().T @ (k @ fluctuation)) + (
        v.conj().T @ ((omega*study['tandelta']*capacitance)[:, None]*v))
    hermitian = (z+z.conj().T)/2
    checks = {'residual_relative_error': residual,
              'current_relative_error': float(np.max(abs(plane_return+1))),
              'net_current_error_a': float(np.max(abs(plane_return+np.sum(b, axis=0)))),
              'reciprocity_relative_error': float(np.linalg.norm(z-z.T)/norm),
              'hermitian_min_eigenvalue_ohm': float(np.linalg.eigvalsh(hermitian).min()),
              'power_relative_error': float(np.linalg.norm(hermitian-loss)/
                                            max(float(np.linalg.norm(loss)), 1e-300))}
    if (max(checks[name] for name in ('residual_relative_error', 'current_relative_error',
                                    'net_current_error_a', 'reciprocity_relative_error',
                                    'power_relative_error')) > 1e-7 or
            checks['hermitian_min_eigenvalue_ohm'] < -1e-9*norm):
        raise RuntimeError('Plane residual, current conservation, reciprocity or passivity check failed: '
                           + repr(checks))
    return {'frequency_hz': frequency,
            'z_ohm': [[{'real': float(x.real), 'imag': float(x.imag)} for x in row] for row in z],
            'checks': checks, 'sheet_resistance_ohm_per_square': sheet_r,
            'reference_plane_current_a': [{'real': float(x.real), 'imag': float(x.imag)} for x in plane_return]}


def run_study(study, *, cancel=None):
    """Return finite MODELLED evidence, with one LU/two-RHS solve per frequency."""
    import json
    import numpy as np
    try:
        _checkpoint(cancel)
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            study = validate_study(study)
            _checkpoint(cancel)
            k, capacitance, b, area = _assemble(study)
            rho = study['resistivity_ohm_m']*(1+.00393*(study['temperature_c']-20))
            rows = []
            for frequency in study['frequencies_hz']:
                _checkpoint(cancel)
                rows.append(_frequency(k, capacitance, b, study, rho, frequency))
            _checkpoint(cancel)
            result = {'schema': SCHEMA, 'kind': 'result', 'status': 'MODELLED', 'study': study,
                      'model': '2D P1 triangular parallel-plate quasi-TEM cavity with lumped capacitance',
                      'boundary': 'magnetic-walls-neumann', 'reference_plane': 'ideal',
                      'phasor_convention': 'RMS exp(+j omega t); V = Z I; rows observe, columns excite ports',
                      'units': {'frequency': 'Hz', 'impedance': 'ohm', 'input_geometry': 'mm',
                                'capacitance': 'F', 'area': 'm2', 'temperature': 'degC',
                                'current': 'A', 'resistivity': 'ohm m'},
                      'area_m2': area, 'total_capacitance_f': float(capacitance.sum()),
                      'resistivity_at_temperature_ohm_m': rho, 'frequencies': rows,
                      'mesh': {'nodes': len(capacitance), 'triangles': len(study['triangles'])},
                      'work': {'assemblies': 1, 'factorizations': len(rows),
                               'multi_rhs_solves': len(rows), 'rhs_columns_per_solve': 2},
                      'convergence': {'status': 'NOT_EVALUATED',
                                      'scope': 'Explicit supplied mesh; user must refine mesh and frequency sweep.'},
                      'limitations': list(LIMITATIONS), 'references': list(REFERENCES)}
        json.dumps(result, allow_nan=False)
        return result
    except (OverflowError, FloatingPointError) as exc:
        raise ValueError('Plane study exceeds finite numerical limits.') from exc
