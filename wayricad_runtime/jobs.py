"""Project-local report sequences and native KiCad jobset integration."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import uuid

SCHEMA = 'wayricad.jobs/v1'
TOKEN = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
RESERVED = {'project', 'project_dir', 'board', 'schematic', 'output', 'step_dir',
            'python', 'native_python', 'kicad_cli'}


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Configuration exceeds 2 MiB.')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+x)))


def atomic_text(path, text):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.wayricad-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Expected a relative report path with forward slashes.')
    path = Path(value)
    if path.is_absolute() or any(p in ('.', '..') for p in value.split('/')):
        raise ValueError('Report paths must stay within their step directory.')
    return path


def validate(config):
    keys = {'schema', 'project', 'name', 'variables', 'steps'}
    if not isinstance(config, dict) or set(config) - keys or config.get('schema') != SCHEMA:
        raise ValueError('Expected '+SCHEMA+' with no unknown configuration keys.')
    if 'name' in config and not isinstance(config['name'], str):
        raise ValueError('Sequence name must be text.')
    variables = config.get('variables', {})
    if not isinstance(variables, dict):
        raise ValueError('variables must be an object.')
    for key, value in variables.items():
        if not IDENTIFIER.fullmatch(key) or key in RESERVED or not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError('Invalid or reserved variable: '+key)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Variables must be finite.')
    steps = config.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 128:
        raise ValueError('Choose 1–128 ordered steps.')
    seen = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) - {'id', 'label', 'argv', 'outputs', 'depends_on', 'timeout_seconds'}:
            raise ValueError('Unknown step keys.')
        name = step.get('id', '')
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or name in seen:
            raise ValueError('Step IDs must be unique simple names.')
        if not isinstance(step.get('label', name), str):
            raise ValueError('Step labels must be text.')
        argv = step.get('argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a and '\x00' not in a for a in argv):
            raise ValueError(name+': argv must be a nonempty list of strings, not a shell command.')
        outputs = step.get('outputs', [])
        if not isinstance(outputs, list):
            raise ValueError(name+': outputs must be a list.')
        for output in outputs:
            safe_relative(output)
        if len(set(outputs)) != len(outputs):
            raise ValueError(name+': duplicate expected outputs.')
        deps = step.get('depends_on', [])
        if not isinstance(deps, list) or not all(isinstance(d, str) and d in seen for d in deps):
            raise ValueError(name+': dependencies must name earlier steps.')
        timeout = step.get('timeout_seconds', 300)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
            raise ValueError(name+': timeout_seconds must be positive and at most 86400.')
        seen.add(name)
    return config


def project_path(value=None, config=None, config_path=None):
    base = Path(config_path).resolve().parent if config_path else Path.cwd()
    value = value or (config or {}).get('project')
    if value:
        path = Path(value).expanduser()
        path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    else:
        candidates = list(base.glob('*.kicad_pro'))
        if len(candidates) != 1:
            raise ValueError('Specify a .kicad_pro project; automatic detection requires exactly one.')
        path = candidates[0].resolve()
    if not path.is_file() or path.suffix.lower() != '.kicad_pro':
        raise ValueError('Choose an existing saved .kicad_pro project.')
    return path


def find_kicad_cli():
    requested = os.environ.get('KICAD_CLI')
    candidates = [requested] if requested else ['kicad-cli']
    if not requested:
        if os.name == 'nt':
            candidates += [str(Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'KiCad'/v/'bin/kicad-cli.exe') for v in ('10.0', '11.0')]
        elif sys.platform == 'darwin':
            candidates += ['/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli']
    for item in candidates:
        found = shutil.which(item)
        if found:
            return found
    raise ValueError('kicad-cli not found. Set KICAD_CLI to its executable.')


def context(config, project, output):
    values = {k: str(v) for k, v in config.get('variables', {}).items()}
    values.update(project=str(project), project_dir=str(project.parent),
                  board=str(project.with_suffix('.kicad_pcb')), schematic=str(project.with_suffix('.kicad_sch')),
                  output=str(output), python=sys.executable)
    tokens = {m for step in config['steps'] for arg in step['argv'] for m in TOKEN.findall(arg)}
    if 'kicad_cli' in tokens:
        values['kicad_cli'] = find_kicad_cli()
    if 'native_python' in tokens:
        from .runtime_setup import native_python
        values['native_python'] = str(native_python())
    missing = tokens - values.keys() - {'step_dir'}
    if missing:
        raise ValueError('Define sequence variables: '+', '.join(sorted(missing)))
    for key in ('board', 'schematic'):
        if key in tokens and not Path(values[key]).is_file():
            raise ValueError('Missing project input: '+Path(values[key]).name)
    return values


def expand(argv, values):
    return [TOKEN.sub(lambda m: values[m[1]], arg) for arg in argv]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def input_hashes(project, config_path):
    # Include hierarchical schematic sheets and project rules, without report outputs.
    paths = {project, project.with_suffix('.kicad_pcb'), project.with_suffix('.kicad_dru'), Path(config_path).resolve()}
    paths.update(project.parent.rglob('*.kicad_sch'))
    return {str(p): digest(p) for p in sorted(paths) if p.is_file()}


def terminate(process):
    if process.poll() is not None:
        return
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=15, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass  # Always reap the direct child even if process-tree termination is unavailable.
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=15)


def execute_step(argv, directory, cwd, timeout, env):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    with (directory/'stdout.log').open('wb') as out, (directory/'stderr.log').open('wb') as err:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, shell=False, creationflags=flags,
                                   start_new_session=os.name != 'nt')
        try:
            return process.wait(timeout=timeout), ''
        except subprocess.TimeoutExpired:
            terminate(process)
            return None, 'TIMEOUT'
        except KeyboardInterrupt:
            terminate(process)
            return None, 'CANCELLED'


def files_in(directory):
    return [p for p in sorted(directory.rglob('*')) if p.is_file() and not p.is_symlink()
            and p.resolve().is_relative_to(directory.resolve())]


def save_reports(run, report):
    atomic_text(run/'summary.json', json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    rows = []
    for step in report['steps']:
        links = ' · '.join('<a href="'+quote(a['path'], safe='/')+'">'+escape(a['path'].split('/', 1)[-1])+'</a>' for a in step.get('artifacts', []))
        rows.append('<tr><td>'+escape(step['label'])+'</td><td>'+escape(step['status'])+'</td><td>'+escape(step.get('message', ''))+'</td><td>'+links+'</td></tr>')
    notes = ''.join('<li>'+escape(n)+'</li>' for n in report.get('errors', []))
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>WayriCAD reports</title><style>body{font:16px system-ui;max-width:1100px;margin:3em auto;padding:0 1em;color:#233042;background:#f8fafc}table{width:100%;border-collapse:collapse}td,th{padding:.8em;text-align:left;border-bottom:1px solid #cbd5e1}a{color:#12619b}h1{margin-bottom:.3em}</style><h1>'+escape(report['name'])+'</h1><p>'+escape(report['project'])+' · '+escape(report['status'])+' · '+escape(report['run_id'])+'</p><p>Execution status is not engineering approval. Review each report’s assumptions, coverage and findings.</p><ul>'+notes+'</ul><table><tr><th>Step</th><th>Status</th><th>Details</th><th>Reports and logs</th></tr>'+''.join(rows)+'</table><p><a href="summary.json">Machine-readable summary and SHA-256 manifest</a></p></html>'
    atomic_text(run/'index.html', html)


def run_sequence(config, project, config_path, output=None, keep_going=False, dry_run=False):
    validate(config)
    root = Path(output).expanduser().resolve() if output else project.parent/'reports'/'wayricad'
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    run = root/run_id
    values = context(config, project, run)
    planned = [dict(id=s['id'], argv=expand(s['argv'], dict(values, step_dir=str(run/s['id'])))) for s in config['steps']]
    if dry_run:
        return {'dry_run': True, 'output': str(run), 'steps': planned}, 0
    before = input_hashes(project, config_path)
    run.mkdir(parents=True, exist_ok=False)
    report = {'schema': SCHEMA, 'name': config.get('name', 'WayriCAD report sequence'),
              'project': project.name, 'run_id': run_id, 'status': 'RUNNING', 'steps': [],
              'inputs_sha256': {os.path.relpath(p, project.parent).replace('\\', '/'): h for p, h in before.items()}, 'errors': []}
    env = os.environ.copy()
    # Native interpreters must find the same installed wheel/source modules.
    module_root = str(Path(__file__).resolve().parent.parent)
    env['PYTHONPATH'] = module_root + (os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    statuses = {}
    stopped = False
    cancelled = False
    try:
        for step, plan in zip(config['steps'], planned):
            row = {'id': step['id'], 'label': step.get('label', step['id']), 'status': 'SKIPPED', 'argv': plan['argv'], 'artifacts': []}
            report['steps'].append(row)
            dependencies = step.get('depends_on', [])
            if stopped or any(statuses[d] != 'PASS' for d in dependencies):
                row['message'] = 'Stopped after failure/cancellation.' if stopped else 'A prerequisite did not pass.'
                statuses[step['id']] = row['status']
                continue
            directory = run/step['id']
            directory.mkdir()
            started = time.monotonic()
            row['status'] = 'FAIL'
            try:
                code, reason = execute_step(plan['argv'], directory, project.parent, step.get('timeout_seconds', 300), env)
                row['exit_code'] = code
                row['status'] = reason or ('PASS' if code == 0 else 'FAIL')
                row['message'] = reason or ('' if code == 0 else 'Command returned nonzero; see logs.')
                if code == 0:
                    missing = [name for name in step.get('outputs', []) if not (directory/name).is_file()
                               or not (directory/name).resolve().is_relative_to(directory.resolve()) or (directory/name).stat().st_size == 0]
                    if missing:
                        row.update(status='FAIL', message='Missing/empty required reports: '+', '.join(missing))
                row['artifacts'] = [{'path': p.relative_to(run).as_posix(), 'bytes': p.stat().st_size,
                                     'sha256': digest(p)} for p in files_in(directory)]
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                row.update(status='FAIL', message=str(exc))
            row['duration_seconds'] = round(time.monotonic()-started, 4)
            statuses[step['id']] = row['status']
            cancelled |= row['status'] == 'CANCELLED'
            stopped = cancelled or (row['status'] != 'PASS' and not keep_going)
            save_reports(run, report)
        try:
            after = input_hashes(project, config_path)
            if before != after:
                report['errors'].append('Project inputs changed during execution; reports do not describe one unchanged design.')
        except OSError as exc:
            report['errors'].append('Could not verify project inputs after execution: '+str(exc))
    except KeyboardInterrupt:
        cancelled = True
        if report['steps'] and report['steps'][-1]['id'] not in statuses:
            report['steps'][-1].update(status='CANCELLED', message='CANCELLED')
            statuses[report['steps'][-1]['id']] = 'CANCELLED'
        existing = {step['id'] for step in report['steps']}
        for step, plan in zip(config['steps'], planned):
            if step['id'] not in existing:
                report['steps'].append({'id': step['id'], 'label': step.get('label', step['id']),
                                        'status': 'SKIPPED', 'argv': plan['argv'], 'artifacts': [],
                                        'message': 'Stopped after cancellation.'})
    try:
        report['status'] = 'CANCELLED' if cancelled else ('PASS' if not report['errors'] and all(s['status'] == 'PASS' for s in report['steps']) else 'FAIL')
        report['completed_utc'] = datetime.now(timezone.utc).isoformat()
        save_reports(run, report)
        work = os.environ.get('JOBSET_OUTPUT_WORK_PATH')
        if work:
            try:
                work_path = Path(work)
                if not work_path.is_absolute() or not work_path.is_dir():
                    raise ValueError('JOBSET_OUTPUT_WORK_PATH must be an existing absolute directory.')
                destination = work_path/'wayricad'/run_id
                if destination.resolve() != run.resolve():
                    if destination.resolve().is_relative_to(run.resolve()):
                        raise ValueError('Jobset collection directory is inside the source report directory.')
                    destination.parent.mkdir(exist_ok=True)
                    shutil.copytree(run, destination)
            except (OSError, ValueError) as exc:
                report['errors'].append('Jobset report collection failed: '+str(exc))
                report['status'] = 'FAIL'
                save_reports(run, report)
        atomic_text(root/'latest.html', '<!doctype html><meta charset="utf-8"><title>Latest WayriCAD report</title><p>'+escape(report['status'])+' · <a href="'+quote(run_id)+'/index.html">Open latest completed report</a></p>')
    except KeyboardInterrupt:
        cancelled = True
        report['status'] = 'CANCELLED'
        report['completed_utc'] = datetime.now(timezone.utc).isoformat()
        save_reports(run, report)
        atomic_text(root/'latest.html', '<!doctype html><meta charset="utf-8"><title>Latest WayriCAD report</title><p>CANCELLED · <a href="'+quote(run_id)+'/index.html">Open latest completed report</a></p>')
    report['report_directory'] = str(run)
    return report, 130 if cancelled else (0 if report['status'] == 'PASS' else 1)


def shell_command(argv, platform=None):
    platform = platform or ('windows' if os.name == 'nt' else 'posix')
    if any(any(c in a for c in '\r\n\x00') for a in argv):
        raise ValueError('Invalid command argument.')
    if platform == 'windows':
        if any(any(c in a for c in '%!"') for a in argv):
            raise ValueError('Windows jobset command paths cannot contain %, ! or double quotes.')
        # CALL avoids cmd /c stripping the first quoted executable path.
        return 'call '+' '.join('"'+a+'"' for a in argv)
    return shlex.join(argv)


def jobset_document(project, config_path, *, existing=None, position=None, runner=None, python=None, platform=None):
    config = validate(load_json(config_path))
    if runner and python:
        raise ValueError('Choose either --runner or --python, not both.')
    command = [runner] if runner else [python or sys.executable, '-m', 'wayricad_runtime.jobs']
    command += ['run', str(project), '--config', str(Path(config_path).resolve()), '--keep-going']
    job = {'id': str(uuid.uuid4()), 'type': 'special_execute', 'description': config.get('name', 'WayriCAD reports'),
           'settings': {'command': shell_command(command, platform), 'ignore_exit_code': False, 'record_output': True}}
    document = copy.deepcopy(existing) if existing is not None else {'meta': {'version': 1}, 'jobs': [], 'outputs': [{'id': str(uuid.uuid4()), 'type': 'folder', 'description': 'WayriCAD reports', 'only': [], 'settings': {'output_path': str(project.parent/'reports'/'jobset')}}]}
    if not isinstance(document, dict) or not isinstance(document.get('jobs'), list) or not isinstance(document.get('outputs'), list):
        raise ValueError('Invalid native jobset: jobs and outputs must be lists.')
    jobs = document['jobs']
    index = len(jobs) if position is None else position
    if not 0 <= index <= len(jobs):
        raise ValueError('Job position is outside the existing sequence.')
    if any(not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] for item in jobs):
        raise ValueError('Native jobset jobs must have nonempty string IDs.')
    old_ids = [item['id'] for item in jobs]
    if len(set(old_ids)) != len(old_ids):
        raise ValueError('Native jobset job IDs must be unique.')
    for output in document['outputs']:
        if not isinstance(output, dict):
            raise ValueError('Native jobset outputs must be objects.')
        only = output.get('only', [])
        if (not isinstance(only, list) or not all(isinstance(i, str) for i in only)
                or len(set(only)) != len(only) or any(i not in old_ids for i in only)):
            raise ValueError('Native jobset output references unknown job IDs.')
        if only:
            insertion = next((n for n, old in enumerate(only) if old_ids.index(old) >= index), len(only))
            only.insert(insertion, job['id'])
    jobs.insert(index, job)
    return document


def write_new(path, data):
    path = Path(path)
    if path.suffix.lower() in ('.kicad_pro', '.kicad_pcb', '.kicad_sch'):
        raise ValueError('Output cannot replace a design file.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    from .job_presets import PRESETS, DESCRIPTIONS, REQUIRED_VARIABLES
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('presets', help='List supplied report sequences and required variables.')
    init = subs.add_parser('init', help='Create a project-local report configuration; never overwrite an existing file.')
    init.add_argument('project', nargs='?');init.add_argument('--preset', choices=sorted(PRESETS), default='fabrication')
    init.add_argument('--output', type=Path);init.add_argument('--set', action='append', default=[], metavar='NAME=VALUE')
    for name in ('run', 'validate', 'jobset'):
        sub = subs.add_parser(name)
        sub.add_argument('project', nargs='?');sub.add_argument('--config', type=Path)
        if name == 'run':
            sub.add_argument('--output', type=Path);sub.add_argument('--keep-going', action='store_true')
            sub.add_argument('--dry-run', action='store_true')
        if name == 'jobset':
            sub.add_argument('--output', required=True, type=Path)
            sub.add_argument('--merge', type=Path, help='Read an existing jobset and write a new copy.')
            sub.add_argument('--position', type=int, help='Zero-based insertion position; default append.')
            sub.add_argument('--runner');sub.add_argument('--python')
            sub.add_argument('--platform', choices=('windows','posix'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'presets':
            print(json.dumps({name: {'description': DESCRIPTIONS[name], 'required_variables': REQUIRED_VARIABLES.get(name, [])} for name in PRESETS}, indent=2));return 0
        if args.command == 'init':
            project = project_path(args.project)
            path = args.output or project.parent/'wayricad-jobs.json'
            variables = {}
            for item in args.set:
                key, sep, value = item.partition('=')
                if not sep or not value:raise ValueError('--set needs NAME=VALUE.')
                variables[key] = value
            missing = set(REQUIRED_VARIABLES.get(args.preset, [])) - variables.keys()
            if missing:raise ValueError('Supply --set for: '+', '.join(sorted(missing)))
            config = {'schema': SCHEMA, 'project': os.path.relpath(project, path.resolve().parent), 'name': 'WayriCAD '+args.preset+' reports', 'variables': variables, 'steps': copy.deepcopy(PRESETS[args.preset])}
            write_new(path, validate(config));print(str(path.resolve()));return 0
        config_path = args.config
        if config_path is None:
            project = project_path(args.project)
            config_path = project.parent/'wayricad-jobs.json'
        config = validate(load_json(config_path))
        # An explicitly supplied project is relative to the invoking directory.
        project = project_path(str(Path(args.project).resolve()) if args.project else None, config, config_path)
        if args.command == 'jobset':
            document = jobset_document(project, config_path, existing=load_json(args.merge) if args.merge else None,
                                      position=args.position, runner=args.runner, python=args.python, platform=args.platform)
            write_new(args.output, document);print(str(args.output.resolve()));return 0
        result, code = run_sequence(config, project, config_path, output=getattr(args, 'output', None),
                                    keep_going=getattr(args, 'keep_going', False), dry_run=args.command == 'validate' or args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False));return code
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'ERROR', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr);return 2


if __name__ == '__main__':
    raise SystemExit(main())
