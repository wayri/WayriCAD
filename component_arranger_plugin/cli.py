"""Group, preview and validate/export component placement in a NEW saved project."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('board', type=Path)
    scope = p.add_mutually_exclusive_group()
    scope.add_argument('--refs', help='Comma-separated exact footprint references')
    scope.add_argument('--scope', choices=['sheet', 'native_groups', 'schematic'], help='Infer groups instead of manual --refs')
    p.add_argument('--group', default='A', help='Alphabetical inferred group ID')
    p.add_argument('--list-groups', action='store_true')
    p.add_argument('--wire-mm', type=float, default=25)
    p.add_argument('--include-local-labels', action='store_true', help='Explicitly authorize local-label cluster merging')
    p.add_argument('--include-global-labels', action='store_true', help='Explicitly authorize global-label cluster merging')
    p.add_argument('--anchor', help='Anchor reference; inferred if omitted, reported in JSON')
    p.add_argument('--sides', choices=['top', 'bottom', 'both'], default='top')
    p.add_argument('--angles', default='0,90')
    p.add_argument('--density', type=float, default=.5)
    p.add_argument('--width-mm', type=float, help='Explicit area width; requires --height-mm')
    p.add_argument('--height-mm', type=float)
    p.add_argument('--capacitor', action='append', default=[], help='Override C1=anchor_power_pin; repeat')
    p.add_argument('--validate', action='store_true')
    p.add_argument('--output', type=Path, help='Validate and export a new .kicad_pcb plus matching project/rules')
    p.add_argument('--report', type=Path, help='NEW JSON report file')
    return p


def run_native(options):
    import pcbnew as api
    from . import engine, grouping, native
    source = Path(options['board']).resolve(strict=True)
    if source.suffix != '.kicad_pcb': raise ValueError('Input must be a saved .kicad_pcb.')
    if options.get('output'):
        output = Path(options['output']).resolve()
        if output.suffix != '.kicad_pcb' or not output.parent.is_dir() or any(output.with_suffix(ext).exists() for ext in ('.kicad_pcb','.kicad_pro','.kicad_dru')):
            raise ValueError('Choose a NEW PCB/project/rules basename in an existing directory.')
    paths = [source] + [source.with_suffix(e) for e in ('.kicad_pro', '.kicad_dru', '.kicad_sch')]
    custody = {p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in paths}
    board = api.LoadBoard(str(source))
    manager = api.SETTINGS_MANAGER()
    if source.with_suffix('.kicad_pro').is_file():
        manager.LoadProject(str(source.with_suffix('.kicad_pro')), False)
        board.SetProject(manager.GetProject(str(source.with_suffix('.kicad_pro'))))
    groups = None
    if options.get('scope') == 'schematic':
        groups = grouping.infer_schematic_groups(source.with_suffix('.kicad_sch'), max_wire_mm=options['wire_mm'],
                include_label_links=options['include_local_labels'], include_global_links=options['include_global_labels'])
    elif options.get('scope'):
        groups = grouping.board_groups(board, options['scope'])
    if options.get('list_groups'):
        if groups is None: raise ValueError('--list-groups requires --scope.')
        return dict(status='GROUPS', groups=groups)
    refs = [r.strip() for r in (options.get('refs') or '').split(',') if r.strip()]
    if groups is not None:
        group = next((c for c in groups['clusters'] if c['id'] == options['group']), None)
        if group is None: raise ValueError('Group not found; use --list-groups first.')
        refs = group['references']
    if len(set(refs)) < 2: raise ValueError('Choose two or more --refs, or an inferred group.')
    models = tuple(native.model(fp, api) for fp in board.GetFootprints() if fp.GetReference() in refs)
    anchor = options.get('anchor')
    if anchor:
        selected = next((f for f in models if f.reference == anchor), None)
        if selected is None: raise ValueError('Anchor must be in the chosen group.')
        anchor = selected.key
    else: anchor = engine.infer_anchor(models)
    sides = ('top', 'bottom') if options['sides'] == 'both' else (options['sides'],)
    area = engine.suggested_area(models, anchor, options['density'], sides)
    if bool(options.get('width_mm')) != bool(options.get('height_mm')): raise ValueError('Provide both area dimensions.')
    if options.get('width_mm') is not None:
        w,h = options['width_mm'],options['height_mm']
        if not 0 < w <= 1000 or not 0 < h <= 1000: raise ValueError('Area must be (0,1000] mm.')
        f = next(f for f in models if f.key == anchor)
        area = f.x-w/2,f.y-h/2,f.x+w/2,f.y+h/2
    targets = dict(row.split('=',1) for row in options['capacitor'])
    plan = native.propose(board, api, refs, anchor=anchor, area=area, density=options['density'], allowed_sides=sides,
                          allowed_angles=tuple(float(a) for a in options['angles'].split(',')), capacitor_targets=targets)
    if options['validate'] or options.get('output'): native.validate(board, api, plan)
    def source_check():
        if any((hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) != h for p,h in custody.items()):
            raise ValueError('Source board/project/schematic/rules changed; retry.')
    source_check()
    report = dict(schema='wayricad.component-arranger/v1', status='VALIDATED' if plan.validated_digest else 'PREVIEW',
                  source_sha256=custody[source], anchor=next(f.reference for f in models if f.key==anchor),
                  area_mm=area, result=asdict(plan.result), evidence=plan.evidence, groups=groups,
                  external_pads=[asdict(p) for p in plan.external_pads])
    if options.get('output'):
        output = Path(options['output']).resolve()
        targets = [output, output.with_suffix('.kicad_pro'), output.with_suffix('.kicad_dru')]
        if output.suffix != '.kicad_pcb' or not output.parent.is_dir() or any(p.exists() for p in targets):
            raise ValueError('Choose a NEW PCB/project/rules basename in an existing directory.')
        native.check(board, api, plan)
        created = []
        try:
            native.materialize(board, api, native.placements(plan))
            with output.open('x', encoding='utf-8') as stream:
                created.append(output); stream.write(native.serialize(board, api))
            for ext in ('.kicad_pro', '.kicad_dru'):
                context = source.with_suffix(ext)
                if context.is_file():
                    path = output.with_suffix(ext)
                    with path.open('xb') as stream:
                        created.append(path); stream.write(context.read_bytes())
            source_check()
        except BaseException:
            for p in reversed(created): p.unlink()
            raise
        report['status'] = 'EXPORTED'; report['output'] = output.name
    return report


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.report and (args.report.exists() or not args.report.parent.is_dir()):
            raise ValueError('Choose a NEW report file in an existing directory.')
        if args.report and args.output and args.report.resolve() in {args.output.resolve().with_suffix(ext) for ext in ('.kicad_pcb','.kicad_pro','.kicad_dru')}:
            raise ValueError('Report must be separate from project output.')
        with tempfile.TemporaryDirectory(prefix='wayricad-arranger-cli-') as raw:
            request,response = Path(raw)/'request.json',Path(raw)/'response.json'
            request.write_text(json.dumps({k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}),encoding='utf-8')
            result = subprocess.run([sys.executable,str(Path(__file__).with_name('cli_worker.py')),str(request),str(response)],capture_output=True,text=True,timeout=480)
            if not response.is_file(): raise ValueError('Use matching KiCad native Python with pcbnew. '+result.stderr[-300:])
            payload = json.loads(response.read_text(encoding='utf-8'))
            if result.returncode or payload.get('status')=='ERROR': raise ValueError(payload.get('error','Native child failed.'))
        rendered=json.dumps(payload,indent=2)+'\n'
        if args.report:
            with args.report.open('x',encoding='utf-8') as stream:stream.write(rendered)
        print(rendered,end='');return 0
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        print(json.dumps(dict(status='ERROR',error=str(error))),file=sys.stderr);return 1


if __name__=='__main__': raise SystemExit(main())
