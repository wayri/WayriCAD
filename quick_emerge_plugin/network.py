"""Sampled RF networks using real-reference power waves, S[receiver, source].

No interpolation, vector fit, causality correction or inverse regularization is
performed. Frequency is Hz, Z is ohms and Y is siemens. Zero Hz, complex or
frequency-dependent reference impedances require another qualified contract.
Formula references: scikit-rf network.s2z/s2y and Network.se2gmm documentation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import numpy as np


def _numeric(values, dtype, name):
    """Reject booleans rather than quietly treating them as measured numbers."""
    try:
        raw = np.asarray(values)
        if dtype is float and np.iscomplexobj(raw):
            raise ValueError(name + ' must be real')
        if raw.dtype.kind == 'b' or any(isinstance(v, (bool, np.bool_)) for v in np.asarray(values, dtype=object).flat):
            raise ValueError(name + ' cannot contain booleans')
        out = np.array(values, dtype=dtype, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name + ' must be numeric') from exc
    if not np.isfinite(out).all():
        raise ValueError(name + ' must be finite')
    return out


def _references(z0, count):
    z = _numeric(z0, float, 'reference impedance')
    if z.ndim == 0:
        z = np.full(count, float(z))
    if z.shape != (count,) or np.any(z <= 0):
        raise ValueError('reference impedance must be positive real ohms, scalar or one value per port')
    return z


def _solve(a, b, operation):
    """Reject a singular/ill-conditioned representation; never perturb data."""
    try:
        if np.any(np.linalg.cond(a) > 1e12):
            raise ValueError(operation + ' is singular or ill-conditioned (condition > 1e12)')
        out = np.linalg.solve(a, b)
    except np.linalg.LinAlgError as exc:
        raise ValueError(operation + ' is singular') from exc
    if not np.isfinite(out).all():
        raise ValueError(operation + ' produced nonfinite values')
    return out


def _right_solve(b, a, operation):
    return _solve(a.swapaxes(-1, -2), b.swapaxes(-1, -2), operation).swapaxes(-1, -2)


class SampledNetwork:
    """Validated network, immutable arrays and explicit transformation history.

    ``s`` has shape (frequency, receiver, source). Reference impedances are
    constant positive real values, allowing unequal references between ports.
    Port selectors are zero-based indices or unique names. Derived networks
    preserve the original identity and record ordered ports and loads.
    """
    def __init__(self, frequencies_hz, s, z0_ohm=50, port_names=None, provenance=None):
        f = _numeric(frequencies_hz, float, 'frequencies_hz')
        s = _numeric(s, complex, 'S matrix')
        if f.ndim != 1 or not len(f) or np.any(f <= 0) or np.any(np.diff(f) <= 0):
            raise ValueError('frequencies_hz must be positive, nonempty and strictly increasing')
        if s.ndim != 3 or s.shape[0] != len(f) or s.shape[1] < 1 or s.shape[1] != s.shape[2]:
            raise ValueError('S matrix must have shape (frequency, port, port) matching the sweep')
        if isinstance(port_names, str):
            raise ValueError('port_names must be an ordered sequence, not a string')
        names = tuple(f'P{i+1}' for i in range(s.shape[1])) if port_names is None else tuple(port_names)
        if (len(names) != s.shape[1] or any(not isinstance(n, str) or not n.strip() for n in names)
                or len(set(names)) != len(names)):
            raise ValueError('port names must be nonempty, unique and match the port count')
        self.frequencies_hz, self.s = f, s
        self.z0_ohm = _references(z0_ohm, len(names))
        self.port_names = names
        self.provenance = deepcopy(provenance or {})
        for array in (self.frequencies_hz, self.s, self.z0_ohm):
            array.setflags(write=False)

    @property
    def port_count(self):
        return len(self.port_names)

    def digest(self):
        """Canonical numerical identity including port order and references."""
        payload = {'frequencies_hz': self.frequencies_hz.tolist(),
                   's_ri': np.stack((self.s.real, self.s.imag), axis=-1).tolist(),
                   'z0_ohm': self.z0_ohm.tolist(), 'port_names': self.port_names,
                   'wave_convention': 'real-reference-power'}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    def _derived(self, s, z0, names, transformation):
        history = deepcopy(self.provenance)
        history.setdefault('origin_network_sha256', self.digest())
        history.setdefault('transformations', []).append(transformation)
        return SampledNetwork(self.frequencies_hz, s, z0, names, history)

    def to_z(self):
        """Z = sqrt(R) (I+S) (I-S)^-1 sqrt(R); ideal opens can be singular."""
        eye = np.eye(self.port_count)
        d = np.sqrt(self.z0_ohm)
        normalized = _right_solve(eye + self.s, eye - self.s, 'S to Z')
        return d[None, :, None] * normalized * d[None, None, :]

    def to_y(self):
        """Direct Y conversion also supports networks whose Z is singular."""
        eye = np.eye(self.port_count)
        d = 1 / np.sqrt(self.z0_ohm)
        normalized = _right_solve(eye - self.s, eye + self.s, 'S to Y')
        return d[None, :, None] * normalized * d[None, None, :]

    @classmethod
    def from_z(cls, frequencies_hz, z_ohm, z0_ohm=50, port_names=None, provenance=None):
        z = _numeric(z_ohm, complex, 'Z matrix')
        if z.ndim != 3 or z.shape[1] != z.shape[2] or not z.shape[1]:
            raise ValueError('Z matrix must have shape (frequency, port, port)')
        refs = _references(z0_ohm, z.shape[1])
        d = 1 / np.sqrt(refs)
        zn = d[None, :, None] * z * d[None, None, :]
        eye = np.eye(z.shape[1])
        return cls(frequencies_hz, _right_solve(zn-eye, zn+eye, 'Z to S'), refs, port_names, provenance)

    @classmethod
    def from_y(cls, frequencies_hz, y_siemens, z0_ohm=50, port_names=None, provenance=None):
        y = _numeric(y_siemens, complex, 'Y matrix')
        if y.ndim != 3 or y.shape[1] != y.shape[2] or not y.shape[1]:
            raise ValueError('Y matrix must have shape (frequency, port, port)')
        refs = _references(z0_ohm, y.shape[1])
        d = np.sqrt(refs)
        yn = d[None, :, None] * y * d[None, None, :]
        eye = np.eye(y.shape[1])
        return cls(frequencies_hz, _right_solve(eye-yn, eye+yn, 'Y to S'), refs, port_names, provenance)

    def renormalize(self, z0_ohm):
        """Transform waves directly; avoids requiring a finite Z for a thru."""
        refs = _references(z0_ohm, self.port_count)
        ratio = np.sqrt(refs / self.z0_ohm)
        a = np.diag((ratio + 1/ratio)/2)
        b = np.diag((ratio - 1/ratio)/2)
        out = _solve(a-self.s@b, self.s@a-b, 'reference renormalization')
        return self._derived(out, refs, self.port_names, {'operation': 'renormalize', 'from_ohm': self.z0_ohm.tolist(), 'to_ohm': refs.tolist()})

    def _index(self, selector):
        if isinstance(selector, str):
            try:
                return self.port_names.index(selector)
            except ValueError as exc:
                raise ValueError('unknown port: ' + selector) from exc
        if isinstance(selector, (bool, np.bool_)) or not isinstance(selector, (int, np.integer)) or not 0 <= selector < self.port_count:
            raise ValueError('port must be a zero-based index or a known name')
        return int(selector)

    def terminate(self, keep, loads_ohm):
        """Eliminate ports using explicit uncoupled R>0, 'open' or 'short' loads.

        Sred=Saa+Sab Gamma (I-Sbb Gamma)^-1 Sba. Complex, active,
        frequency-dependent and coupled loads are deliberately unsupported.
        """
        a = [self._index(p) for p in keep]
        if not a or len(set(a)) != len(a):
            raise ValueError('keep must contain unique ports and cannot be empty')
        b = [p for p in range(self.port_count) if p not in a]
        if not isinstance(loads_ohm, dict):
            raise ValueError('loads must explicitly map every eliminated port to its load')
        mapped = {}
        for key, value in loads_ohm.items():
            index = self._index(key)
            if index in mapped:
                raise ValueError('duplicate load port')
            mapped[index] = value
        if set(mapped) != set(b):
            raise ValueError('provide exactly one explicit load for every eliminated port')
        gammas, recorded = [], {}
        for index in b:
            value = mapped[index]
            if isinstance(value, str) and value in ('open', 'short'):
                gamma = 1.0 if value == 'open' else -1.0
                recorded[self.port_names[index]] = value
            else:
                r = _numeric(value, float, 'load resistance')
                if r.ndim or r <= 0:
                    raise ValueError('load resistance must be finite positive ohms or open/short')
                gamma = (float(r)-self.z0_ohm[index])/(float(r)+self.z0_ohm[index])
                recorded[self.port_names[index]] = float(r)
            gammas.append(gamma)
        saa = self.s[:, a, :][:, :, a]
        if b:
            sab = self.s[:, a, :][:, :, b]
            sba = self.s[:, b, :][:, :, a]
            sbb = self.s[:, b, :][:, :, b]
            gamma = np.diag(gammas)
            saa = saa + sab@gamma@_solve(np.eye(len(b))-sbb@gamma, sba, 'loaded port reduction')
        return self._derived(saa, self.z0_ohm[a], [self.port_names[i] for i in a],
                             {'operation': 'terminate', 'kept_ports': [self.port_names[i] for i in a], 'loads_ohm': recorded})

    def mixed_mode(self, pairs):
        """Real power transform, ordered [d(pairs), c(pairs), unpaired].

        Pair=(positive,negative). Pair members must have equal real references;
        differential reference=2R and common reference=R/2. Polarity is retained.
        """
        parsed, used = [], set()
        for pair in pairs:
            if len(pair) != 2:
                raise ValueError('each mixed-mode pair requires positive and negative ports')
            p, n = (self._index(v) for v in pair)
            if p == n or p in used or n in used:
                raise ValueError('mixed-mode pairs must be disjoint distinct ports')
            if self.z0_ohm[p] != self.z0_ohm[n]:
                raise ValueError('pair reference impedances must match; explicitly renormalize first')
            used.update((p, n))
            parsed.append((p, n))
        if not parsed:
            raise ValueError('at least one pair is required')
        rows, names, refs = [], [], []
        for mode, sign, multiplier in [('d', -1, 2), ('c', 1, .5)]:
            for p, n in parsed:
                row = np.zeros(self.port_count)
                row[p], row[n] = 1/np.sqrt(2), sign/np.sqrt(2)
                rows.append(row)
                names.append(f'{mode}({self.port_names[p]},{self.port_names[n]})')
                refs.append(self.z0_ohm[p]*multiplier)
        for i in range(self.port_count):
            if i not in used:
                rows.append(np.eye(self.port_count)[i])
                names.append(self.port_names[i])
                refs.append(self.z0_ohm[i])
        transform = np.array(rows)
        return self._derived(transform@self.s@transform.T, refs, names,
                             {'operation': 'mixed_mode', 'pairs_positive_negative': [[self.port_names[p], self.port_names[n]] for p,n in parsed], 'ordering': 'differential,common,unpaired'})

    def analyze(self, *, phase_floor=1e-12, tolerance=1e-9):
        """Sample diagnostics, not certification of passivity or causality.

        Group delay=-d(unwrapped phase)/d(2 pi f), seconds; unavailable at
        magnitude <= phase_floor. Derivatives use measured adjacent samples,
        one-sided endpoints and nonuniform central differences. Sparse sweeps
        can alias phase; no delay estimate can repair an undersampled sweep.
        """
        if not np.isfinite(phase_floor) or phase_floor <= 0 or not np.isfinite(tolerance) or tolerance < 0:
            raise ValueError('invalid diagnostic tolerance or phase floor')
        mag = np.abs(self.s)
        with np.errstate(divide='ignore'):
            db = 20*np.log10(mag)
        phase = np.full(self.s.shape, np.nan)
        delay = np.full(self.s.shape, np.nan)
        for i in range(self.port_count):
            for j in range(self.port_count):
                indices = np.flatnonzero(mag[:, i, j] > phase_floor)
                for group in np.split(indices, np.flatnonzero(np.diff(indices) > 1)+1):
                    if not len(group):
                        continue
                    values = np.unwrap(np.angle(self.s[group, i, j]))
                    phase[group, i, j] = values
                    if len(group) >= 2:
                        delay[group, i, j] = -np.gradient(values, 2*np.pi*self.frequencies_hz[group], edge_order=1)
        sigma = np.linalg.svd(self.s, compute_uv=False)[:, 0]
        reciprocity = np.max(np.abs(self.s-self.s.swapaxes(1,2)), axis=(1,2))
        diag = np.diagonal(mag, axis1=1, axis2=2)
        gamma = np.diagonal(self.s, axis1=1, axis2=2)
        with np.errstate(divide='ignore', invalid='ignore'):
            input_impedance=self.z0_ohm*(1+gamma)/(1-gamma)
            input_impedance=np.where(np.isfinite(input_impedance),input_impedance,np.nan+1j*np.nan)
            vswr = np.where(diag < 1, (1+diag)/(1-diag), np.nan)
        return {'magnitude': mag, 'magnitude_db': db, 'phase_rad': phase,
                'group_delay_s': delay, 'vswr': vswr,
                'return_loss_db': -np.diagonal(db,axis1=1,axis2=2),
                'insertion_loss_db': -db,
                'input_impedance_ohm': input_impedance,
                'largest_singular_value': sigma,
                'passivity_excess': np.maximum(0, sigma-1),
                'sampled_passive': bool(np.all(sigma <= 1+tolerance)),
                'reciprocity_error': reciprocity,
                'sampled_reciprocal': bool(np.all(reciprocity <= tolerance)),
                'tolerance': tolerance, 'phase_floor': phase_floor,
                'limits': ['Sample diagnostics do not establish causality, broadband passivity or mesh convergence.',
                           'Delay is a finite-difference estimate; phase increments can alias between samples.',
                           'Passivity and reciprocity expectations depend on the modeled device.']}


def from_result(result):
    """Read Quick EMerge RI samples; every ordered S entry must be present."""
    if not isinstance(result, dict) or result.get('schema') not in (1, 2):
        raise ValueError('unsupported Quick EMerge result schema')
    count = result.get('port_count')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 9:
        raise ValueError('result port_count must be an integer from 1 to 9 (unambiguous Sij keys)')
    try:
        f = result['frequencies_hz']
        entries = result['s_parameters']
        keys = {f'S{i+1}{j+1}' for i in range(count) for j in range(count)}
        if set(entries) != keys:
            raise ValueError('result must contain every Sij entry without extra entries')
        matrix = np.empty((len(f), count, count), dtype=complex)
        for i in range(count):
            for j in range(count):
                pairs = _numeric(entries[f'S{i+1}{j+1}'], float, 'Sij RI samples')
                if pairs.shape != (len(f), 2):
                    raise ValueError('Sij values must be aligned [real,imaginary] pairs')
                # Preserve signed-zero RI samples exactly for numerical identity.
                matrix.real[:, i, j] = pairs[:, 0]
                matrix.imag[:, i, j] = pairs[:, 1]
        return SampledNetwork(f, matrix, result.get('reference_impedance_ohm',result['config']['z0_ohm']), result.get('port_names'),
                              {'source': result.get('source'), 'config_sha256': result.get('config_sha256'), 'region_sha256': result.get('region_sha256')})
    except (KeyError, TypeError) as exc:
        raise ValueError('incomplete sampled network result') from exc
