"""Read-only series route discovery beside a saved PCB."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def run(args, argv):
    from wayricad_runtime.report_ui import publish_documents
    from wayricad_runtime.series_topology import infer_series_paths
    from .service import run_job
    options={word.split('=')[0] for word in argv if word.startswith('--')}
    if options-{'--infer-series','--source','--sink','--output','--timeout'}:
        raise ValueError('Path discovery accepts only board, --infer-series, --source, --sink, --output and --timeout; it does not solve.')
    if not args.board or not args.source or not args.sink:
        raise ValueError('Path discovery requires a saved PCB, --source and --sink pads.')
    source=Path(args.board).resolve()
    if not source.is_file() or source.suffix.lower()!='.kicad_pcb':
        raise ValueError('Choose an existing .kicad_pcb file.')
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    inventory=run_job(dict(action='inspect',board_path=str(source)),timeout=args.timeout)
    answer=infer_series_paths(inventory,args.source,args.sink)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=before or inventory.get('source_sha256')!=before:
        raise ValueError('The saved PCB changed during discovery. Reload it and retry.')
    payload=json.dumps(answer,indent=2,allow_nan=False)+'\n'
    if args.output:
        if args.output.suffix.lower()!='.json':
            raise ValueError('Choose a separate .json path discovery output.')
        publish_documents({args.output:payload},sources=[source])
    else:
        print(payload,end='')
    return 0 if answer['routes'] else 3
