import argparse
import json
import sys
from pathlib import Path

from .config import load, save
from .runtime import discover


def main(argv=None):
    parser = argparse.ArgumentParser(prog='WayriCAD Mechanical Check')
    parser.add_argument('board', nargs='?')
    parser.add_argument('--rules')
    parser.add_argument('--output', default='artifacts/reports')
    parser.add_argument('--gui', action='store_true')
    parser.add_argument('--review', help='Open a saved JSON report in the native conflict viewer')
    parser.add_argument('--snapshot-of', help=argparse.SUPPRESS)
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--init-rules', metavar='PATH')
    args = parser.parse_args(argv)
    if args.doctor:
        print(json.dumps(discover(), indent=2))
        return 0
    if args.init_rules:
        save(args.init_rules, load())
        return 0
    if args.gui or args.review:
        from .ui import launch
        launch(args.board, args.rules, args.snapshot_of, args.review)
        return 0
    if not args.board:
        parser.error('Provide a .kicad_pcb board, or use --gui / --doctor')
    from .runner import run
    from .report import export
    try:
        result = run(args.board, load(args.rules), lambda n, text: print(f'{n:3}% {text}', flush=True))
        paths = export(result, Path(args.output))
        print(json.dumps(dict(status=result['status'], findings=len(result['findings']), reports=paths), indent=2))
        return 3 if result['status'] == 'incomplete' else 2 if result['status'] == 'review_required' else 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
