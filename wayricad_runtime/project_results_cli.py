"""List, inspect and save complete project-local PI/SI/thermal JSON results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import project_results as library

PLUGINS = ('quick-pi', 'quick-si', 'quick-therm', 'quick-emerge')
_EVIDENCE = {'board_path', 'source_sha256', 'tool', 'version', 'source_state',
             'units', 'coordinate_frame', 'z_basis'}
_REQUIRED_EVIDENCE = {'board_path', 'source_sha256', 'tool', 'version', 'source_state'}


def _input(path):
    with Path(path).open('rb') as stream:
        return library._decode(stream.read(library.MAX_BYTES + 1))


def _evidence(path, project):
    value = _input(path)
    if set(value) - _EVIDENCE or not _REQUIRED_EVIDENCE.issubset(value):
        raise ValueError('Evidence must contain only portable-export arguments and the original saved PCB fingerprint.')
    if value['source_state'] != 'saved' or not isinstance(value['board_path'], str):
        raise ValueError('Verified save requires explicit saved-source evidence and a PCB path.')
    board = Path(value['board_path'])
    value['board_path'] = board if board.is_absolute() else Path(project) / board
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True, help='Existing project directory containing the result library.')
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list', help='List verified record receipts in deterministic plugin/content order.')
    listing.add_argument('--plugin', choices=PLUGINS)
    show = commands.add_parser('show', help='Inspect one immutable result and its current source state.')
    show.add_argument('record', type=Path, help='Chosen JSON result file; relative to the project or absolute, including an external folder.')
    show.add_argument('--plugin', choices=PLUGINS)
    show.add_argument('--full', action='store_true', help='Include the complete bundle plus receipt; no arrays are shortened.')
    save = commands.add_parser('save', help='Save a complete JSON bundle; unverified/read-only unless explicit evidence is supplied.')
    save.add_argument('input', type=Path, help='Existing strict JSON producer bundle; never a design file or script.')
    save.add_argument('--plugin', choices=PLUGINS, required=True)
    save.add_argument('--version', help='Actual producer version, otherwise explicitly unknown.')
    save.add_argument('--evidence', type=Path, help='Strict JSON portable-export arguments with the ORIGINAL solve-time PCB SHA-256.')
    save.add_argument('--output', type=Path, help='Named JSON destination, relative to the project or absolute. Omit for the immutable project library.')
    save.add_argument('--overwrite', action='store_true', help='Permit replacing an existing named output; source/input files remain protected.')
    args = parser.parse_args(argv)
    try:
        if args.command == 'list':
            result = library.list_results(args.project, plugin=args.plugin)
        elif args.command == 'show':
            record = args.record if args.record.is_absolute() else args.project / args.record
            loaded = library.load_result(args.project, record, plugin=args.plugin, chosen=True)
            result = loaded if args.full else loaded['receipt']
        else:
            bundle = _input(args.input)
            evidence = _evidence(args.evidence, args.project) if args.evidence else None
            destination = args.output
            if destination is not None:
                destination = destination if destination.is_absolute() else args.project / destination
                if not destination.suffix:destination=destination.with_suffix('.json')
                if destination.exists() and not args.overwrite:
                    raise ValueError('Named output already exists. Choose another filename or explicitly use --overwrite.')
            protected = [args.input] + ([args.evidence] if args.evidence else [])
            result = library.save_result(args.project, args.plugin, bundle, pocket_kivi=evidence, version=args.version,
                                         destination=destination, protected_sources=protected)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(json.dumps(dict(status='error', error=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
