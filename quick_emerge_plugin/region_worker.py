"""Native KiCad Python entry point; all structured results go to --output."""
import argparse
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--board', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--area')
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    source = Path(args.board).resolve()
    if output == source or output.suffix.lower() != '.json':
        print('Output must be a .json file separate from the source PCB.', file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from pcb_regions import collect_regions
        result = collect_regions(args.board, args.area)
        code = 0
    except Exception as exc:
        result = {'error': str(exc)}
        code = 2
    temporary = output.with_name(output.name + '.' + str(os.getpid()) + '.tmp')
    try:
        temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return code


if __name__ == '__main__':
    sys.exit(main())
