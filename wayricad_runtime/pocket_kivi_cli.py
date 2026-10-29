"""Export a complete saved analysis without changing its numerical payload."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .pocket_kivi_export import MAX_BYTES, export_bundle


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field: ' + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Nonfinite JSON number: ' + value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path, help='Original complete producer JSON')
    parser.add_argument('output', type=Path, help='New portable .json destination')
    parser.add_argument('--board', type=Path, required=True, help='Original saved PCB')
    parser.add_argument('--source-sha256', required=True, help='PCB hash recorded by the solver, never a newly calculated substitute')
    parser.add_argument('--tool', required=True, help='Producer tool name')
    parser.add_argument('--version', required=True, help='Producer version recorded with the result')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--saved-source', action='store_true', required=True,
                        help='Confirm that this result was solved from the specified saved PCB bytes')
    args = parser.parse_args(argv)
    try:
        if args.result.resolve() == args.output.resolve():
            raise ValueError('Output must not overwrite the original analysis.')
        with args.result.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Input exceeds 64 MiB; export separate complete cases.')
        bundle = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_object,
                            parse_constant=_constant)
        if not isinstance(bundle, dict):
            raise ValueError('Input must be one complete producer result object.')
        receipt = export_bundle(bundle, args.output, board_path=args.board,
                                source_sha256=args.source_sha256, source_state='saved',
                                tool=args.tool, version=args.version, source_root=args.source_root)
        print(json.dumps(receipt, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RecursionError) as error:
        print('Saved analysis export: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
