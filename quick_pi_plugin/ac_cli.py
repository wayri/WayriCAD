"""Strict AC-study intake and read-only command-line workflow."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = 'wayricad.pi-ac/v1'
MAX_STUDY_BYTES = 4 * 1024 * 1024


def parse_study(data):
    """Decode a bounded study, rejecting repeated fields and non-finite values."""
    if len(data) > MAX_STUDY_BYTES:
        raise ValueError('AC study exceeds 4 MiB.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Repeated AC JSON field: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('AC JSON requires finite numbers: ' + value)
    try:
        study = json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs,
                           parse_constant=invalid)
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('AC study must be bounded UTF-8 JSON.') from exc
    if not isinstance(study, dict) or study.get('schema') != SCHEMA:
        raise ValueError('AC study requires schema ' + SCHEMA + '.')
    def visit(value, depth=0):
        if depth > 32:
            raise ValueError('AC study nesting exceeds 32 levels.')
        if isinstance(value, dict):
            for item in value.values(): visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value: visit(item, depth + 1)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('AC JSON requires finite numbers.')
    visit(study)
    return study


def load_study(path):
    """Read a JSON study and retain its exact saved-byte fingerprint."""
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > MAX_STUDY_BYTES:
        raise ValueError('AC study must be a JSON file no larger than 4 MiB.')
    data = path.read_bytes()
    return parse_study(data), hashlib.sha256(data).hexdigest()


def protect_outputs(targets, sources):
    """Reject path aliases that would overwrite a PCB or the model input."""
    for target in targets:
        target = Path(target).resolve()
        for source in sources:
            source = Path(source).resolve()
            if target == source or (target.exists() and source.exists() and os.path.samefile(target, source)):
                raise ValueError('AC output must not overwrite the source PCB or study input.')


def main(args, run_job, forbidden=False):
    """Run an explicit AC cross-section through the isolated Quick PI worker."""
    if forbidden:
        raise ValueError('--ac cannot combine with unrelated PI analysis flags. Put AC geometry and currents in the study.')
    source = args.ac.resolve()
    study, digest = load_study(source)
    protected = [source] + ([args.board.resolve()] if args.board else [])
    targets = []
    if args.output:
        if args.output.suffix.lower() != '.json':
            raise ValueError('AC JSON output needs a .json filename.')
        targets.append(args.output.resolve())
    if args.html:
        html = args.html.resolve().with_suffix('.html')
        targets.extend((html, html.with_suffix('.json')))
        if args.output and args.output.resolve() == html:
            raise ValueError('JSON output and HTML report need different files.')
    protect_outputs(targets, protected)
    request = {'action': 'ac', 'study': study, 'study_input_path': str(source),
               'study_file_sha256': digest}
    if args.board: request['board_path'] = str(args.board.resolve())
    if args.html: request['html_output'] = str(args.html.resolve().with_suffix('.html'))
    result = run_job(request, timeout=args.timeout)
    payload = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        protect_outputs([args.output], protected)
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('AC study changed during analysis. Rerun before exporting.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + '\n', encoding='utf-8')
    print(payload)
    return 0 if result['ac'].get('status') in ('completed', 'CONVERGED', 'converged') else 3
