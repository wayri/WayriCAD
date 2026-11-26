"""Standard-library-only identity and qualification certificate checks."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys


CERTIFICATE_NAME = 'quick-emerge-qualified.json'
CERTIFICATE_ISSUER = 'quick-emerge-runtime-qualifier'
ACCELERATED_SOLVERS = {'CORVID': 'corvid-solver', 'SPARTA': 'sparta-solver'}
SOLVER_PARITY_TOLERANCE = 1e-4
ACCELERATED_EMERGE_VERSION = '3.0.10'


def adapter_signature():
    """Bind a certificate to the exact adapter and qualification implementation."""
    digest = hashlib.sha256()
    for name in ('backend.py', 'model.py', 'fem_array.py', 'network_keys.py', 'refinement.py', 'qualification.py', 'compatibility.py',
                 'pcb_regions.py', 'region_ports.py', 'region_backend.py', 'advanced.py', 'advanced_studies.py', 'advanced_imports.py', 'advanced_thermal.py', 'advanced_exports.py', 'qualification_data.py', 'network.py', 'network_extensions.py'):
        digest.update(name.encode('ascii') + b'\0')
        digest.update(Path(__file__).with_name(name).read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def read_certificate(path, *, allow_stale=False):
    """Return a current certificate, or None for missing/stale/malformed evidence.

    The caller must additionally compare ``version`` to installed metadata.
    This local certificate records compatibility checks; it is not a security
    signature or evidence of numerical accuracy.
    """
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or type(value.get('schema')) is not int
                or value['schema'] != 1 or value.get('issuer') != CERTIFICATE_ISSUER
                or not isinstance(value.get('version'), str) or not value['version'].strip()
                or ('packages' in value and not isinstance(value['packages'],dict))
                or ('solver_backends' in value and not isinstance(value['solver_backends'],dict))
                or not isinstance(value.get('adapter_signature'), str)
                or (not allow_stale and value['adapter_signature'] != adapter_signature())):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def runtime_certificate(prefix):
    return read_certificate(Path(prefix) / CERTIFICATE_NAME)


def solver_disabled(solver):
    return os.environ.get(f'EMERGE_DISABLE_{solver}') == '1'


def solver_certificate(solver, prefix=None):
    certificate = runtime_certificate(prefix if prefix is not None else sys.prefix) or {}
    return matching_solver_record(certificate, solver, importlib.metadata.version)


def matching_solver_record(certificate, solver, read_version):
    # A passed CPU smoke test belongs to the exact adapter and solver packages.
    distribution = ACCELERATED_SOLVERS.get(solver)
    if not distribution or solver_disabled(solver):
        return None
    record = certificate.get('solver_backends', {}).get(solver)
    if not isinstance(record, dict) or record.get('status') != 'passed' or record.get('mode') != 'CPU':
        return None
    delta = record.get('max_s_parameter_delta')
    if (record.get('distribution') != distribution
            or record.get('tolerance') != SOLVER_PARITY_TOLERANCE
            or type(delta) not in (float, int) or not math.isfinite(delta)
            or not 0 <= delta <= SOLVER_PARITY_TOLERANCE):
        return None
    packages = certificate.get('packages', {})
    if packages.get(distribution) != record.get('version'):
        return None
    try:
        expected = {'emerge': certificate['version'], 'emsutil': packages['emsutil'],
                    distribution: packages[distribution]}
        if not all(version and read_version(name) == version for name, version in expected.items()):
            return None
    except (KeyError, importlib.metadata.PackageNotFoundError):
        return None
    return record
