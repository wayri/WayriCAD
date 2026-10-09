"""Bounded intake and path-safe electrothermal CLI workflow."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

MAX_STUDY_BYTES = 4 * 1024 * 1024


def load_study(path):
    source = Path(path).resolve()
    if not source.is_file() or source.stat().st_size > MAX_STUDY_BYTES:
        raise ValueError('Electrothermal study must be a JSON file no larger than 4 MiB.')
    data = source.read_bytes()
    return parse_envelope(data), hashlib.sha256(data).hexdigest()


def parse_envelope(data):
    if len(data) > MAX_STUDY_BYTES:
        raise ValueError('Electrothermal study exceeds 4 MiB.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Repeated electrothermal JSON field: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Electrothermal JSON requires finite numbers: ' + value)
    envelope = json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(envelope, dict) or set(envelope) != {'mode', 'study'}:
        raise ValueError('Study JSON must contain exactly mode and study.')
    if envelope['mode'] not in ('steady', 'transient') or not isinstance(envelope['study'], dict):
        raise ValueError('Choose mode steady or transient and an explicit study object.')
    def depth(value, level=0):
        if level > 32: raise ValueError('Electrothermal study nesting exceeds 32 levels.')
        if isinstance(value, dict):
            for item in value.values(): depth(item, level+1)
        elif isinstance(value, list):
            for item in value: depth(item, level+1)
        elif isinstance(value, float):
            import math
            if not math.isfinite(value): raise ValueError('Electrothermal JSON requires finite numbers.')
    depth(envelope)
    return envelope


def main(args, run_job, forbidden=False):
    if forbidden:
        raise ValueError('--electrothermal cannot combine with unrelated PI analysis flags. Put electrical selections in the study.')
    source = args.electrothermal.resolve()
    envelope, sha = load_study(source)
    protected = [source] + ([args.board.resolve()] if args.board else [])
    targets = []
    if args.output:
        if args.output.suffix.lower() != '.json': raise ValueError('JSON output needs a .json filename.')
        targets.append(args.output.resolve())
    if args.html:
        html = args.html.resolve().with_suffix('.html')
        targets.extend((html, html.with_suffix('.json')))
        if args.output and args.output.resolve() == html:
            raise ValueError('JSON output and HTML report need different files.')
    for target in targets:
        for item in protected:
            if target == item or (target.exists() and os.path.samefile(target, item)):
                raise ValueError('Output must not overwrite the source PCB or study input.')
    request = {'action': 'electrothermal', **envelope, 'study_input_path': str(source),
               'study_file_sha256': sha}
    if args.board: request['board_path'] = str(args.board.resolve())
    if args.html: request['html_output'] = str(args.html.resolve().with_suffix('.html'))
    result = run_job(request, timeout=args.timeout)
    payload = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload+'\n', encoding='utf-8')
    print(payload)
    coupled = result['electrothermal']
    if (args_mode := envelope['mode']) == 'steady' and not coupled.get('converged'):
        return 3
    if args_mode == 'transient' and coupled.get('status') != 'completed': return 3
    from .electrothermal_report import valid_operating_point
    return 0 if valid_operating_point(result) else 4
