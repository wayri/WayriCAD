import hashlib
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import validate
from .findings import finish
from .runtime import discover, run_process


def run(board_path, config, progress=lambda value, message: None, cancel=None, project_dir=None, measurement_session=None):
    board_path = Path(board_path).resolve()
    config = validate(config)
    runtime = discover()
    required = [('kicad_python', 'KiCad Python')]
    if config['mode'] == 'exact3d':
        required += [('kicad_cli', 'KiCad CLI'), ('freecad_python', 'FreeCAD Python')]
    for key, description in required:
        if not runtime[key]:
            raise RuntimeError(description + ' was not found. Set WAYRICAD_MECHANICAL_' + key.upper() + ' to its executable; see Help → Setup.')
    started = datetime.now(timezone.utc)
    timer = time.monotonic()
    source_hash = hashlib.sha256(board_path.read_bytes()).hexdigest()
    comparison = config['comparison_board']
    other_path = None
    other_hash = None
    measurement_sources = {str(board_path): source_hash}
    if measurement_session:
        for enclosure in config['enclosures']:
            path = Path(enclosure['path']).resolve()
            if path.is_file():
                measurement_sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if comparison:
        other_path = Path(comparison['path'])
        if not other_path.is_absolute():
            other_path = board_path.parent / other_path
        other_path = other_path.resolve()
        if not other_path.is_file() or other_path.suffix.lower() != '.kicad_pcb':
            raise ValueError('Choose an existing KiCad PCB for the comparison board')
        other_hash = hashlib.sha256(other_path.read_bytes()).hexdigest()
        measurement_sources[str(other_path)] = other_hash
    with tempfile.TemporaryDirectory(prefix='wayricad-mechanical-') as temp:
        work = Path(temp)
        request = dict(board_path=str(board_path), config=config, workdir=str(work), project_dir=str(project_dir or board_path.parent))
        (work / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        progress(8, 'Reading footprints, mounting holes and model coverage…')
        entry = Path(__file__).with_name('worker_entry.py')
        run_process([runtime['kicad_python'], entry, 'snapshot_worker', work / 'request.json'], work / 'extract.log', cancel)
        board = json.loads((work / 'board.json').read_text(encoding='utf-8'))
        other_board = None
        if other_path:
            other_work = work / 'comparison'
            other_work.mkdir()
            other_request = dict(board_path=str(other_path), config=config, workdir=str(other_work), project_dir=str(other_path.parent))
            (other_work / 'request.json').write_text(json.dumps(other_request), encoding='utf-8')
            progress(18, 'Reading comparison-board footprints and model coverage…')
            run_process([runtime['kicad_python'], entry, 'snapshot_worker', other_work / 'request.json'], other_work / 'extract.log', cancel)
            other_board = json.loads((other_work / 'board.json').read_text(encoding='utf-8'))
        if config['mode'] == 'quick2d':
            from .quick import screen
            progress(50, 'Screening same-side footprint envelopes (2D)…')
            result = screen(board, config)
        else:
            progress(25, 'Exporting positioned STEP solids with KiCad…')
            step = work / 'assembly.step'
            args = [runtime['kicad_cli'], 'pcb', 'export', 'step', '--force', '--subst-models', '--user-origin', '0x0mm', '-o', str(step)]
            if not config['include_dnp']:
                args.append('--no-dnp')
            args.append(board['snapshot'])
            run_process(args, work / 'export.log', cancel)
            job = dict(board=board, config=config, step=str(step))
            if measurement_session:
                job['measurement_directory'] = str(work / 'measurement-solids')
            if other_board:
                other_step = work / 'comparison' / 'assembly.step'
                other_args = [runtime['kicad_cli'], 'pcb', 'export', 'step', '--force', '--subst-models', '--user-origin', '0x0mm', '-o', str(other_step)]
                if not config['include_dnp']:
                    other_args.append('--no-dnp')
                other_args.append(other_board['snapshot'])
                progress(38, 'Exporting comparison-board STEP solids…')
                run_process(other_args, work / 'comparison' / 'export.log', cancel)
                job['comparison'] = dict(board=other_board, step=str(other_step), placement=comparison)
            (work / 'job.json').write_text(json.dumps(job), encoding='utf-8')
            progress(48, 'Checking solids, hardware, heights and assembly access…')
            run_process([runtime['freecad_python'], entry, 'solid_worker', work / 'job.json', work / 'result.json'], work / 'solids.log', cancel)
            result = json.loads((work / 'result.json').read_text(encoding='utf-8'))
        reported_rules = dict(config)
        reported_rules['comparison_board'] = None
        result.update(schema_version=1, version=__version__, project_name=config['project_name'] or board_path.stem,
                      project_revision=config['project_revision'], reviewer=config['reviewer'],
                      board_name=board_path.name, board_path=str(board_path), board_sha256=source_hash,
                      started_at=started.isoformat(), completed_at=datetime.now(timezone.utc).isoformat(),
                      local_timestamp=datetime.now().astimezone().isoformat(), duration_seconds=round(time.monotonic()-timer, 3),
                      rules=reported_rules, board=board)
        if other_board:
            result['comparison_board'] = dict(translation_mm=comparison['translation_mm'],
                                             rotation_deg=comparison['rotation_deg'])
            if hashlib.sha256(other_path.read_bytes()).hexdigest() != other_hash:
                result['coverage']['gaps'].append('Comparison board changed on disk during validation; rerun before sign-off')
        if hashlib.sha256(board_path.read_bytes()).hexdigest() != source_hash:
            result['coverage']['gaps'].append('Board changed on disk during validation; rerun before sign-off')
        result['export_log'] = (work / 'export.log').read_text(encoding='utf-8', errors='replace') if (work / 'export.log').exists() else 'Quick 2D screen: STEP export not requested.'
        scope_rules = {k:v for k,v in config.items() if k not in ('waivers', 'project_name', 'project_revision', 'reviewer')}
        model_hashes = sorted(m['sha256'] for c in board['components'] for m in c['models'] if m.get('resolved'))
        if other_board:
            model_hashes.extend(m['sha256'] for c in other_board['components'] for m in c['models'] if m.get('resolved'))
        scope = source_hash + (other_hash or '') + json.dumps(scope_rules,sort_keys=True) + ''.join(sorted(model_hashes))
        for finding in result['findings']:
            finding['id'] = hashlib.sha256((finding['id']+scope).encode()).hexdigest()[:20]
        board.pop('snapshot', None)
        if other_board:
            other_board.pop('snapshot', None)
        if measurement_session:
            for source_board in [board] + ([other_board] if other_board else []):
                for component in source_board['components']:
                    for model in component['models']:
                        if model.get('resolved'):
                            measurement_sources[model['path']] = model['sha256']
            measurement_session.bind(result, work / 'measurement-solids' if config['mode'] == 'exact3d' else None,
                                     runtime, measurement_sources)
        progress(100, 'Validation complete — review findings and model coverage')
        return finish(result, config)
