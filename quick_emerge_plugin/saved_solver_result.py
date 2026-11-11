"""Bounded read-only intake for explicitly selected raw solver JSON/gzip."""
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path


def load_solver_json(path):
    from wayricad_runtime.project_results import MAX_BYTES
    from .reporting import validate_report_result
    with Path(path).open('rb') as stream: raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise ValueError('Solver result exceeds the saved-result size budget.')
    decoded=raw
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=BytesIO(raw)) as stream: decoded=stream.read(MAX_BYTES+1)
        if len(decoded)>MAX_BYTES: raise ValueError('Expanded solver result exceeds the saved-result size budget.')
    def invalid_constant(value): raise ValueError('Non-finite JSON constant: '+value)
    result=json.loads(decoded,parse_constant=invalid_constant)
    validate_report_result(result,verify_source=False)
    return {'bundle':result,'receipt':{'source_state':'unverified',
            'source_binding':'unverified','raw_solver_sha256':hashlib.sha256(raw).hexdigest()}}
