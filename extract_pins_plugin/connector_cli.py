"""Read-only connector geometry and native schematic-label CLI commands."""
from __future__ import annotations

import csv
from io import StringIO
import json
from pathlib import Path
import sys

from .core.connector_mating import footprint_pins, physical_grid, grid_text, match_mating

DESIGN_SUFFIXES = {'.kicad_pcb', '.kicad_sch', '.kicad_pro', '.kicad_dru', '.kicad_mod', '.kicad_sym'}


def register_commands(sub):
    """Register boardless labels, physical tables and explicit mating reviews."""
    labels = sub.add_parser('labels', help='Convert one/two-column CSV or TSV into native pasteable schematic labels.')
    labels.add_argument('input', help='CSV/TSV path, or - to read stdin.')
    labels.add_argument('--columns', choices=('auto', 'labels', 'pin-label'), default='auto')
    labels.add_argument('--sequence', choices=('sequential', 'row-major', 'column-major', 'odd-even', 'serpentine'), default='sequential')
    labels.add_argument('--start', type=int, default=1)
    labels.add_argument('--step', type=int, default=1)
    labels.add_argument('--grid-columns', type=int, default=2)
    labels.add_argument('--header', action='store_true', help='Skip the first nonempty record explicitly.')
    labels.add_argument('--select', default='', help='Comma-separated pin IDs to copy; empty selects all.')
    labels.add_argument('--prefix', default='')
    labels.add_argument('--suffix', default='')
    labels.add_argument('--ref', default='')
    _label_options(labels)
    labels.add_argument('-f', '--format', choices=('clipboard', 'csv', 'json'), default='clipboard')
    labels.add_argument('-o', '--output', help='New report/clipboard file; omitted writes stdout.')
    labels.set_defaults(func=cmd_labels)

    grid = sub.add_parser('connector-grid', help='Extract a physical pin/label table from numbered PCB pad positions.')
    grid.add_argument('pcb', help='Saved .kicad_pcb; never modified.')
    grid.add_argument('--ref', required=True, help='Exact connector reference.')
    grid.add_argument('--side', choices=('top', 'bottom'), default='top')
    grid.add_argument('--rotation', type=float, default=0)
    grid.add_argument('--mirror', action='store_true', help='Additional explicit X reflection.')
    grid.add_argument('--tolerance', type=float, default=.02, help='Coordinate clustering tolerance, mm.')
    grid.add_argument('--transpose', action='store_true', help='Exchange output rows and columns.')
    grid.add_argument('-f', '--format', choices=('csv', 'md', 'json'), default='csv')
    grid.add_argument('-o', '--output')
    grid.set_defaults(func=cmd_grid)

    mate = sub.add_parser('connector-mate', help='Review explicitly posed connector pin geometry from JSON.')
    mate.add_argument('input', help='JSON with a/b pin arrays and optional pose_a/pose_b; - reads stdin.')
    mate.add_argument('--tolerance', type=float, default=.1, help='Maximum contact-centre distance, mm.')
    mate.add_argument('--labels-from', choices=('a', 'b'), default='a')
    mate.add_argument('--a-prefix', default='')
    mate.add_argument('--a-suffix', default='')
    mate.add_argument('--b-prefix', default='')
    mate.add_argument('--b-suffix', default='')
    mate.add_argument('--allow-partial', action='store_true', help='Explicitly export only unambiguous matched contacts.')
    _label_options(mate)
    mate.add_argument('-f', '--format', choices=('json', 'csv', 'clipboard-a', 'clipboard-b', 'clipboard-pair'), default='json')
    mate.add_argument('-o', '--output')
    mate.set_defaults(func=cmd_mate)


def _label_options(parser):
    parser.add_argument('--kind', choices=('global', 'local', 'hierarchical'), default='global')
    parser.add_argument('--template', default='{label}', help='Fields: {label}, {pin}, {ref}.')
    parser.add_argument('--case', choices=('unchanged', 'upper', 'lower'), default='unchanged')
    parser.add_argument('--orientation', type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument('--pitch', type=float, default=2.54, help='Label anchor spacing, mm.')
    parser.add_argument('--text-size', type=float, default=1.27, help='Label text size, mm.')


def _read(source):
    if source == '-':text = sys.stdin.read(2_000_001)
    else:
        with Path(source).open(encoding='utf-8-sig') as stream:text = stream.read(2_000_001)
    if len(text) > 2_000_000 or len(text.encode('utf-8')) > 2_000_000:
        raise ValueError('Input exceeds the 2 MB connector review budget.')
    return text


def _output(text, destination, inputs=()):
    """Write a new export without replacing an input, design or existing file."""
    if not destination:
        sys.stdout.write(text)
        return
    path = Path(destination)
    if path.suffix.casefold() in DESIGN_SUFFIXES:
        raise ValueError('Export to a new .txt, .csv, .md or .json file; native design files are protected.')
    if any(source != '-' and path.resolve() == Path(source).resolve() for source in inputs):
        raise ValueError('The export path is the input file.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='') as output:
        output.write(text)


def _csv(rows):
    stream = StringIO()
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def _failure(exc):
    from .cli import CliError, EXIT_USAGE
    raise CliError(str(exc), EXIT_USAGE) from exc


def _clipboard(rows, args, origin=(0, 0)):
    from .core.connector_labels import schematic_labels
    return schematic_labels(rows, kind=args.kind, orientation=args.orientation,
                            pitch_mm=args.pitch, text_size_mm=args.text_size, origin=origin)


def cmd_labels(args):
    from .core.connector_labels import parse_pin_text, format_labels
    try:
        rows = parse_pin_text(_read(args.input), columns=args.columns, sequence=args.sequence,
                              start=args.start, step=args.step, header=args.header,
                              grid_columns=args.grid_columns)
        if args.select:
            selected = {value.strip() for value in args.select.split(',') if value.strip()}
            missing = selected - {row['pin'] for row in rows}
            if missing:raise ValueError('Selected pin IDs not found: ' + ', '.join(sorted(missing)))
            rows = [row for row in rows if row['pin'] in selected]
        rows = format_labels(rows, prefix=args.prefix, suffix=args.suffix, template=args.template,
                             case=args.case, ref=args.ref)
        text = (_clipboard(rows, args) if args.format == 'clipboard' else
                _csv(rows) if args.format == 'csv' else json.dumps(rows, indent=2, ensure_ascii=False) + '\n')
        _output(text, args.output, (args.input,))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:_failure(exc)


def cmd_grid(args):
    from .cli import load_board
    try:
        board = load_board(args.pcb)
        selected = [fp for fp in board.GetFootprints() if str(fp.GetReference()) == args.ref]
        if len(selected) != 1:raise ValueError('Select one unique connector reference; found ' + str(len(selected)))
        grid = physical_grid(footprint_pins(selected[0]), tolerance_mm=args.tolerance,
                             side=args.side, rotation_deg=args.rotation, mirror=args.mirror)
        if args.transpose:grid = [list(row) for row in zip(*grid)]
        text = json.dumps(grid, indent=2, ensure_ascii=False) + '\n' if args.format == 'json' else grid_text(grid, args.format)
        _output(text, args.output, (args.pcb,))
        return 0
    except (ValueError, OSError, UnicodeError) as exc:_failure(exc)


def cmd_mate(args):
    from .core.connector_labels import format_labels
    try:
        request = json.loads(_read(args.input))
        if not isinstance(request, dict) or not isinstance(request.get('a'), list) or not isinstance(request.get('b'), list):
            raise ValueError('Mating JSON requires a and b pin arrays.')
        result = match_mating(request['a'], request['b'], tolerance_mm=args.tolerance,
                              pose_a=request.get('pose_a'), pose_b=request.get('pose_b'))
        result['pose_a'] = request.get('pose_a') or {}
        result['pose_b'] = {'mirror': True} if request.get('pose_b') is None else request['pose_b']
        a_rows, b_rows, flat = [], [], []
        for pair in result['pairs']:
            label = pair[args.labels_from].get('label', '')
            prepared = []
            for side in ('a', 'b'):
                row = {'pin': pair[side]['pin'], 'label': label}
                if label:
                    row = format_labels([row], prefix=getattr(args, side + '_prefix'), suffix=getattr(args, side + '_suffix'),
                                        template=args.template, case=args.case, ref=side.upper())[0]
                prepared.append(row)
            a_rows.append(prepared[0]);b_rows.append(prepared[1])
            pair.update(a_label=prepared[0]['label'], b_label=prepared[1]['label'])
            flat.append({'A pin': pair['a']['pin'], 'A label': pair['a_label'], 'B pin': pair['b']['pin'],
                         'B label': pair['b_label'], 'Distance mm': pair['distance_mm']})
        partial = bool(result['issues'] or result['unmatched_a'] or result['unmatched_b'])
        if args.format.startswith('clipboard'):
            if partial and not args.allow_partial:raise ValueError('Unmatched or ambiguous contacts remain. Review JSON first, or explicitly choose --allow-partial.')
            text = (_clipboard(a_rows, args) if args.format == 'clipboard-a' else
                    _clipboard(b_rows, args) if args.format == 'clipboard-b' else
                    _clipboard(a_rows, args) + _clipboard(b_rows, args, origin=(60, 0)))
        else:
            text = _csv(flat) if args.format == 'csv' else json.dumps(result, indent=2, ensure_ascii=False) + '\n'
        _output(text, args.output, (args.input,))
        return 3 if partial else 0
    except (ValueError, OSError, UnicodeError, TypeError) as exc:_failure(exc)
