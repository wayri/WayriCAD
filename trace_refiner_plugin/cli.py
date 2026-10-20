"""Preview saved routing or export a separately validated project from the CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('board', type=Path, help='Saved PCB with matching .kicad_pro')
    scope = result.add_mutually_exclusive_group()
    scope.add_argument('--net', action='append', default=[], help='Exact net name; repeat for several nets')
    scope.add_argument('--netclass', action='append', default=[], help='Native net class; repeat as needed')
    scope.add_argument('--track', action='append', default=[], help='Straight track UUID; repeat as needed')
    result.add_argument('--layer', action='append', default=[], help='Copper layer name; default all copper')
    result.add_argument('--max-deviation', type=float, default=.1, help='Maximum displacement in mm (0, 1]')
    result.add_argument('--max-shortening', type=float, default=.1, help='Maximum shortening per chain in mm (0, 1]')
    result.add_argument('--protected', help='Replace default comma-separated protected net wildcards')
    result.add_argument('--validate', action='store_true', help='Run native connectivity and before/after DRC')
    result.add_argument('--output', type=Path, help='Validate and export a NEW PCB/project; never overwrite')
    result.add_argument('--report', type=Path, help='Write JSON report to a NEW file, in addition to stdout')
    return result


def run_native(options):
    """Run in an owned native child; retain source custody through validated export."""
    import pcbnew as api
    from .refiner import DEFAULTS, materialize, native_rules, propose, snapshot, validate_detached, change_metrics

    source = Path(options['board']).resolve(strict=True)
    if source.suffix != '.kicad_pcb':
        raise ValueError('Input must be a .kicad_pcb file.')
    contexts = [source.with_suffix(ext) for ext in ('.kicad_pro', '.kicad_dru')]
    if not contexts[0].is_file():
        raise ValueError('Save the matching .kicad_pro before using the CLI.')
    inputs = [source] + [p for p in contexts if p.is_file()]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    output = Path(options['output']).resolve() if options.get('output') else None
    targets = ([output, output.with_suffix('.kicad_pro'), output.with_suffix('.kicad_dru')]
               if output else [])
    if output and (output.suffix != '.kicad_pcb' or not output.parent.is_dir()):
        raise ValueError('Output must be a .kicad_pcb in an existing directory.')
    if any(p.exists() for p in targets):
        raise ValueError('Output PCB/project/rules already exist; choose a new basename.')
    board = api.LoadBoard(str(source))
    manager = api.SETTINGS_MANAGER()
    manager.LoadProject(str(contexts[0]), False)
    board.SetProject(manager.GetProject(str(contexts[0])))
    settings = dict(DEFAULTS, scope='whole board', layers=options['layer'])
    names = {t.GetNetname() for t in board.GetTracks()}
    names.update(p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads())
    if options['net']:
        missing = set(options['net']) - names
        if missing:
            raise ValueError('Unknown exact net names: ' + ', '.join(sorted(missing)))
        settings.update(scope='net filters', nets=options['net'])
    if options['netclass']:
        classes = {dict(values)['GetName'] for _, values in native_rules(board)['netclasses']}
        missing = set(options['netclass']) - classes
        if missing:
            raise ValueError('Unknown net classes: ' + ', '.join(sorted(missing)))
        settings.update(scope='groups', groups=options['netclass'])
    if options['track']:
        tracks = {t.m_Uuid.AsString(): t for t in board.GetTracks() if type(t) is api.PCB_TRACK}
        if set(options['track']) - tracks.keys():
            raise ValueError('Unknown straight track UUID in --track.')
        for identity in options['track']:
            tracks[identity].SetSelected()
        settings['scope'] = 'selected tracks'
    layers = {board.GetLayerName(i) for i in board.GetEnabledLayers().CuStack()}
    if set(options['layer']) - layers:
        raise ValueError('Unknown or disabled copper layer in --layer.')
    settings.update(max_deviation=options['max_deviation'], max_shortening=options['max_shortening'])
    if options.get('protected') is not None:
        settings['protected'] = options['protected']
    plan = propose(board, api, settings)
    if options['validate'] or output:
        validate_detached(board, api, plan)
    def check_sources():
        if any(not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest
               for p, digest in hashes.items()):
            raise ValueError('Source PCB or project changed during the operation; retry.')
        if any(p.exists() != (p in hashes) for p in contexts):
            raise ValueError('Source context files changed during the operation; retry.')
    check_sources()
    report = dict(schema='wayricad.trace-refiner/v1', status='VALIDATED' if plan.validated else 'PREVIEW',
                  source_sha256=hashes[source], settings=settings, evidence=plan.evidence,
                  changes=[dict(net=c.net, layer=board.GetLayerName(c.layer), width_mm=api.ToMM(c.width),
                                track_ids=[t.m_Uuid.AsString() for t in c.originals],metrics=change_metrics(c,api),
                                before_mm=[[api.ToMM(x), api.ToMM(y)] for x, y in c.before],
                                after_mm=[[api.ToMM(x), api.ToMM(y)] for x, y in c.after])
                           for c in plan.changes], skipped=plan.skipped)
    if output:
        if snapshot(board, api) != plan.fingerprint:
            raise ValueError('Board changed after validation.')
        with tempfile.TemporaryDirectory(prefix='wayricad-refiner-export-') as raw:
            stage = Path(raw) / output.name
            materialize(board, api, plan.changes)
            if not api.SaveBoard(str(stage), board, True):
                raise RuntimeError('Could not save the refined candidate.')
            prepared = [(stage, output)] + [(p, output.with_suffix(p.suffix)) for p in contexts if p.is_file()]
            check_sources()
            created = []
            try:
                for origin, target in prepared:
                    with target.open('xb') as stream:
                        created.append(target)
                        stream.write(origin.read_bytes())
                check_sources()
            except BaseException:
                for target in reversed(created):
                    target.unlink()
                raise
        report['status'] = 'EXPORTED'
        report['output'] = output.name
    return report


def main(argv=None):
    """Keep parsing and JSON output outside KiCad's native project lifetime."""
    args = parser().parse_args(argv)
    options = vars(args)
    options = {key: str(value) if isinstance(value, Path) else value for key, value in options.items()}
    report_path = args.report
    try:
        if report_path and report_path.exists():
            raise ValueError('Report already exists; choose a new file.')
        if report_path and not report_path.parent.is_dir():
            raise ValueError('Report directory must already exist.')
        if report_path and args.output and report_path.resolve() in {
                args.output.resolve().with_suffix(ext) for ext in ('.kicad_pcb', '.kicad_pro', '.kicad_dru')}:
            raise ValueError('Report must be separate from output project files.')
        with tempfile.TemporaryDirectory(prefix='wayricad-refiner-cli-') as raw:
            request, result = Path(raw) / 'request.json', Path(raw) / 'result.json'
            request.write_text(json.dumps(options), encoding='utf-8')
            process = subprocess.run([sys.executable, str(Path(__file__).with_name('cli_worker.py')),
                                      str(request), str(result)], capture_output=True, text=True)
            if not result.is_file():
                raise RuntimeError('Native CLI worker did not complete. Use KiCad 10 Python with pcbnew. ' + process.stderr[-300:])
            payload = json.loads(result.read_text(encoding='utf-8'))
            if process.returncode or payload.get('status') == 'ERROR':
                raise ValueError(payload.get('error', 'Native CLI worker failed.'))
        rendered = json.dumps(payload, indent=2) + '\n'
        if report_path:
            with report_path.open('x', encoding='utf-8') as stream:
                stream.write(rendered)
        print(rendered, end='')
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps(dict(status='ERROR', error=str(exc))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
