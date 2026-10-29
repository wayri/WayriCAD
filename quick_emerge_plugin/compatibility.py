"""Standard-library-only identity and qualification certificate checks."""
import hashlib
import json
from pathlib import Path


CERTIFICATE_NAME = 'quick-emerge-qualified.json'
CERTIFICATE_ISSUER = 'quick-emerge-runtime-qualifier'


def adapter_signature():
    """Bind a certificate to the exact adapter and qualification implementation."""
    digest = hashlib.sha256()
    for name in ('backend.py', 'model.py', 'refinement.py', 'qualification.py', 'compatibility.py',
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
                or not isinstance(value.get('adapter_signature'), str)
                or (not allow_stale and value['adapter_signature'] != adapter_signature())):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def runtime_certificate(prefix):
    return read_certificate(Path(prefix) / CERTIFICATE_NAME)
