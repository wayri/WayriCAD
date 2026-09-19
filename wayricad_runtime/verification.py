"""Read-only native KiCad DRC evidence and conservative regression comparison."""
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SECTIONS = ('violations', 'unconnected_items', 'schematic_parity')


class VerificationError(ValueError):
    pass


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def discover_cli(explicit=None):
    selected = explicit or os.environ.get('KICAD_CLI')
    if selected:
        path = Path(selected).expanduser().resolve()
        if not path.is_file():
            raise VerificationError('Specified kicad-cli executable does not exist: ' + str(path))
        return path
    candidates = [Path(sys.executable).with_name('kicad-cli.exe' if os.name == 'nt' else 'kicad-cli')]
    found = shutil.which('kicad-cli')
    if found:
        candidates.append(Path(found))
    candidates.extend(Path(os.environ.get('ProgramFiles', 'C:/Program Files')).glob('KiCad/10.*/bin/kicad-cli.exe'))
    candidates.extend((Path('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'),
                       Path('/Applications/KiCad/kicad-cli')))
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise VerificationError('Install KiCad CLI or supply its executable path with --kicad-cli.')


def parse_report(value):
    """Accept a native DRC JSON path or object, retaining all finding details."""
    try:
        document = value if isinstance(value, dict) else json.loads(Path(value).read_text(encoding='utf-8-sig'))
        if not isinstance(document, dict) or document.get('$schema') != 'https://schemas.kicad.org/drc.v1.json':
            raise ValueError('Expected the native KiCad drc.v1 JSON report.')
        if document.get('coordinate_units') != 'mm':
            raise ValueError('DRC report must use millimetres.')
        if not isinstance(document.get('kicad_version'), str) or not isinstance(document.get('source'), str):
            raise ValueError('DRC report lacks engine/source identity.')
        for section in SECTIONS:
            if not isinstance(document.get(section), list):
                raise ValueError('DRC report lacks the ' + section + ' array.')
            for finding in document[section]:
                if not isinstance(finding, dict) or finding.get('severity') not in ('error', 'warning', 'exclusion'):
                    raise ValueError('Invalid DRC finding severity.')
                if not all(isinstance(finding.get(k), str) for k in ('type', 'description')) or not isinstance(finding.get('items'), list):
                    raise ValueError('Invalid DRC finding details.')
                for item in finding['items']:
                    if not isinstance(item, dict) or not isinstance(item.get('description'), str):
                        raise ValueError('Invalid DRC item.')
                    position = item.get('pos')
                    if not isinstance(position, dict) or any(isinstance(position.get(k), bool) or not isinstance(position.get(k), (int,float)) or not math.isfinite(position[k]) for k in ('x','y')):
                        raise ValueError('Invalid DRC item coordinates.')
        return document
    except (OSError, ValueError, TypeError) as exc:
        raise VerificationError('Invalid DRC report: ' + str(exc)) from exc


def _records(document):
    records = {}
    counts = Counter()
    for section in SECTIONS:
        for finding in document[section]:
            # UUIDs change during imports/copies. All physical and descriptive
            # details remain significant; there is no coordinate rounding.
            record = dict(finding, section=section)
            record['items'] = sorted(({k:v for k,v in item.items() if k != 'uuid'} for item in finding['items']),
                                     key=lambda item: json.dumps(item, sort_keys=True))
            key = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()).hexdigest()
            records[key] = record
            counts[key] += 1
    return records, counts


def summarize(document):
    normal = document['violations'] + document['schematic_parity']
    return {'errors': sum(f['severity']=='error' for f in normal),
            'warnings': sum(f['severity']=='warning' for s in SECTIONS for f in document[s]),
            'unconnected': sum(f['severity']!='exclusion' for f in document['unconnected_items']),
            'schematic_parity': sum(f['severity']!='exclusion' for f in document['schematic_parity'])}


def compare_reports(baseline, current):
    before, after = parse_report(baseline), parse_report(current)
    for key in ('coordinate_units', 'kicad_version', 'included_severities', 'ignored_checks'):
        normalize = lambda value: sorted((json.dumps(v, sort_keys=True) for v in value)) if isinstance(value,list) else value
        if normalize(before.get(key)) != normalize(after.get(key)):
            raise VerificationError('Baseline and current DRC check configuration differs: ' + key)
    old_records, old = _records(before)
    new_records, new = _records(after)
    added = [dict(new_records[k], identity=k, count=n) for k,n in sorted((new-old).items())]
    resolved = [dict(old_records[k], identity=k, count=n) for k,n in sorted((old-new).items())]
    blockers = [r for r in added if r['severity']!='exclusion' and (r['severity']=='error' or r['section']=='unconnected_items')]
    return {'accepted': not blockers, 'new': added, 'resolved': resolved,
            'new_errors': sum(r['count'] for r in added if r['severity']=='error' and r['section']!='unconnected_items'),
            'new_unconnected': sum(r['count'] for r in added if r['section']=='unconnected_items' and r['severity']!='exclusion')}


def verify_board(board_path, report_path, *, baseline=None, kicad_cli=None, timeout=120):
    """Run DRC without saving the PCB; publish fresh evidence only on valid output.

    ``accepted`` means no errors/unconnected items, or no new blockers relative
    to the supplied baseline. ``clean`` independently describes the current PCB.
    Engine failure always raises VerificationError, never a successful verdict.
    """
    board, destination = Path(board_path).resolve(), Path(report_path).resolve()
    if not board.is_file() or board.suffix.lower() != '.kicad_pcb':
        raise VerificationError('Provide an existing saved .kicad_pcb.')
    if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not math.isfinite(timeout) or timeout<=0:
        raise VerificationError('DRC timeout must be finite and positive.')
    protected = [board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru')]
    if destination in protected or destination.suffix.lower() != '.json':
        raise VerificationError('DRC report must be a separate .json file.')
    if baseline is not None and not isinstance(baseline, dict) and Path(baseline).resolve()==destination:
        raise VerificationError('Current report must not overwrite its baseline.')
    prior = parse_report(baseline) if baseline is not None else None
    signatures = {p: _digest(p) if p.is_file() else None for p in protected}
    executable = discover_cli(kicad_cli)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.wayricad-drc-', dir=destination.parent) as temporary:
        fresh = Path(temporary)/'drc.json'
        command = [str(executable),'pcb','drc','--format','json','--units','mm',
                   '--severity-error','--severity-warning','--exit-code-violations',
                   '--refill-zones','--output',str(fresh),str(board)]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VerificationError('KiCad DRC could not complete: ' + str(exc)) from exc
        if any((_digest(p) if p.is_file() else None)!=digest for p,digest in signatures.items()):
            raise VerificationError('Board or design-rule input changed during DRC; report not accepted.')
        if process.returncode not in (0,5):
            raise VerificationError(f'KiCad DRC engine failed (exit {process.returncode}): '+process.stderr[-2000:])
        document = parse_report(fresh)
        if Path(document['source']).name != board.name:
            raise VerificationError('DRC report identifies a different PCB.')
        counts = summarize(document)
        findings = sum(len(document[s]) for s in SECTIONS)
        if (process.returncode==5 and not findings) or (process.returncode==0 and findings):
            raise VerificationError('DRC exit code contradicts its reported findings.')
        comparison = compare_reports(prior, document) if prior is not None else None
        clean = not counts['errors'] and not counts['unconnected']
        result = {'schema':'wayricad.routing-verification.v1','status':'completed',
                  'accepted':comparison['accepted'] if comparison is not None else clean,
                  'clean':clean,'counts':counts,'input_sha256':signatures[board],
                  'input_files_sha256':{str(path):digest for path,digest in signatures.items()},
                  'board_path':str(board),'report_path':str(destination),'report_sha256':_digest(fresh),
                  'engine_exit_code':process.returncode,'kicad_cli':str(executable),'kicad_version':document['kicad_version'],
                  'comparison':comparison,'scope':'Native PCB DRC; schematic parity is not requested.'}
        os.replace(fresh,destination)
        return result
