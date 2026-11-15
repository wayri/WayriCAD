"""Source-bound two-port study CLI; no KiCad or GUI dependency."""
import hashlib
import json
import math
import threading
from concurrent.futures import CancelledError
from pathlib import Path


def run(args, words):
    from .ac_cli import MAX_STUDY_BYTES, parse_study, protect_outputs
    from .ac_ports import SCHEMA, run_study
    from wayricad_runtime.report_ui import publish_documents
    plane=bool(args.plane_ports)
    if plane:
        from .plane_ports import SCHEMA,run_study
    allowed = {'--plane-ports' if plane else '--ac-ports', '--output', '--timeout'}
    if args.board or any(word.split('=')[0] not in allowed for word in words if word.startswith('--')):
        raise ValueError('Two-port extraction accepts only --ac-ports, --output and --timeout.')
    source = (args.plane_ports if plane else args.ac_ports).resolve()
    if not source.is_file() or source.stat().st_size > MAX_STUDY_BYTES:
        raise ValueError('Provide a saved two-port JSON study no larger than 4 MiB.')
    raw = source.read_bytes()
    study = parse_study(raw, schema=SCHEMA)
    digest = hashlib.sha256(raw).hexdigest()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('Timeout must be positive finite seconds.')
    target = args.output.resolve() if args.output else None
    if target:
        if target.suffix.lower() != '.json':
            raise ValueError('Two-port output must use .json.')
        protect_outputs([target], [source])
    cancel = threading.Event()
    timer = threading.Timer(args.timeout, cancel.set)
    timer.daemon = True
    timer.start()
    try:
        result = run_study(study, cancel=cancel)
        if cancel.is_set():
            raise CancelledError('Two-port solve exceeded its cooperative time budget.')
    finally:
        timer.cancel()
    result.update(study_input_path=str(source), study_file_sha256=digest)

    def guard():
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Study input changed during extraction; rerun before export.')

    guard()
    text = json.dumps(result, indent=2, allow_nan=False)
    if target:
        publish_documents({target: text}, sources=[source], source_guard=guard)
    else:
        print(text)
    return 0 if result['status'] == 'CONVERGED' else 3
