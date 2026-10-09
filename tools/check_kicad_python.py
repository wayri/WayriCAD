"""Diagnose Windows KiCad's IPC host interpreter; preview repairs by default."""
import argparse
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid


CONFIG_NAME = 'kicad_common.json'
HOSTS = {'kicad.exe', 'pcbnew.exe', 'eeschema.exe', 'gerbview.exe',
         'bitmap2component.exe', 'pcb_calculator.exe', 'pl_editor.exe'}
PROBE = (
    'import json,sys,venv,ensurepip; '
    'print(json.dumps({"version":list(sys.version_info[:3]),'
    '"executable":sys.executable,"base_prefix":sys.base_prefix,'
    '"venv":True,"ensurepip":True}))'
)


def config_path(version='10.0', *, environ=None):
    """KICAD_CONFIG_HOME replaces the base; KiCad still appends its version."""
    if not re.fullmatch(r'\d+\.\d+', version):
        raise ValueError('KiCad version must be major.minor, such as 10.0.')
    env = os.environ if environ is None else environ
    if env.get('KICAD_CONFIG_HOME'):
        base = Path(env['KICAD_CONFIG_HOME']).expanduser()
    elif env.get('APPDATA'):
        base = Path(env['APPDATA']) / 'kicad'
    else:
        raise ValueError('Cannot locate Windows settings; supply --config-file.')
    if not base.is_absolute():
        raise ValueError('KiCad configuration base must be absolute; supply --config-file.')
    return base / version / CONFIG_NAME


def read_config(path):
    path = Path(path)
    if path.name != CONFIG_NAME or path.is_symlink():
        raise ValueError('Select a regular ' + CONFIG_NAME + ' file.')
    if not path.is_file():
        raise ValueError('KiCad settings do not exist. Open KiCad once, or supply --config-file.')
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('KiCad settings exceed the 2 MiB diagnostic limit.')
    original = path.read_bytes()

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate settings key: ' + key)
            result[key] = value
        return result

    def reject_nonfinite(value):
        raise ValueError('Nonfinite JSON: ' + value)

    try:
        settings = json.loads(original.decode('utf-8-sig'), object_pairs_hook=unique,
                              parse_constant=reject_nonfinite)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid KiCad settings JSON; preserve the file and repair it in KiCad: ' + str(exc)) from exc
    if not isinstance(settings, dict) or not isinstance(settings.get('api', {}), dict):
        raise ValueError('KiCad settings and their api section must be JSON objects; no repair was made.')
    return original, settings


def interpreter_path(value):
    """A setting is one absolute executable, never a shell command or quoted text."""
    if not isinstance(value, str) or not value or value != value.strip() or '"' in value or '\x00' in value:
        raise ValueError('Interpreter must be an unquoted absolute executable path without arguments.')
    path = Path(value).expanduser()
    if not path.is_absolute() or path.name.lower() not in {'python.exe', 'pythonw.exe'}:
        raise ValueError('Interpreter must name an absolute python.exe or pythonw.exe path.')
    if not path.is_file():
        raise ValueError('Configured Python executable does not exist: ' + str(path))
    return path.resolve()


def discover_interpreters(version='10.0', *, environ=None, kicad_root=None, configured=None):
    """Find installed KiCad runtimes, without assuming an installation/user name."""
    env = os.environ if environ is None else environ
    roots = []
    if kicad_root is not None:
        roots.append(Path(kicad_root).expanduser().resolve())
    elif isinstance(configured, str) and configured:
        possible = Path(configured.strip().strip('"'))
        if possible.is_absolute() and possible.parent.name.lower() == 'bin':
            roots.append(possible.parent.parent)
    if kicad_root is None:
        if env.get('LOCALAPPDATA'):
            roots.append(Path(env['LOCALAPPDATA']) / 'Programs' / 'KiCad' / version)
        for key in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
            if env.get(key):
                roots.append(Path(env[key]) / 'KiCad' / version)
        found = shutil.which('pcbnew.exe', path=env.get('PATH', ''))
        if found and Path(found).parent.parent.name == version:
            roots.append(Path(found).parent.parent)
    candidates, seen = [], set()
    for root in roots:
        bin_path = root / 'bin'
        if not (bin_path / 'pcbnew.exe').is_file() and not (bin_path / 'kicad-cli.exe').is_file():
            continue
        console = bin_path / 'python.exe'
        if not console.is_file():
            continue
        windowless = bin_path / 'pythonw.exe'
        chosen = (windowless if windowless.is_file() else console).resolve()
        identity = str(chosen).casefold()
        if identity not in seen:
            seen.add(identity)
            candidates.append(chosen)
    return candidates


def probe_interpreter(path, *, timeout=15):
    """Import only stdlib prerequisites. No venv, pip install or plugin is created."""
    chosen = interpreter_path(str(path))
    console = chosen.with_name('python.exe') if chosen.name.lower() == 'pythonw.exe' else chosen
    if not console.is_file():
        raise ValueError('Cannot inspect pythonw.exe without its adjacent python.exe; repair the KiCad installation.')
    try:
        if chosen.name.lower() == 'pythonw.exe':
            windowless = subprocess.run([str(chosen), '-I', '-B', '-c', 'import venv,ensurepip'],
                                       capture_output=True, text=True, timeout=timeout, check=False,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if windowless.returncode:
                raise ValueError('pythonw.exe cannot load venv/ensurepip; inspect the KiCad installation.')
        result = subprocess.run([str(console), '-I', '-B', '-c', PROBE], capture_output=True,
                                text=True, timeout=timeout, check=False,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Python prerequisite probe failed: ' + str(exc)) from exc
    if result.returncode:
        raise ValueError('Python cannot import venv/ensurepip: ' + result.stderr.strip()[-1200:])
    try:
        details = json.loads(result.stdout)
        version = details['version']
        if not isinstance(version, list) or len(version) != 3 or any(type(n) is not int for n in version):
            raise ValueError('Malformed Python version')
        if tuple(version) < (3, 10, 0) or details.get('venv') is not True or details.get('ensurepip') is not True:
            raise ValueError('WayriCAD needs Python 3.10 or newer with venv and ensurepip')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Python prerequisite probe returned invalid output: ' + str(exc)) from exc
    return details


def running_kicad():
    result = subprocess.run(['tasklist.exe', '/FO', 'CSV', '/NH'], capture_output=True,
                            text=True, timeout=15, check=False,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Cannot verify KiCad is closed; use the Plugins preferences to change the interpreter.')
    return sorted({row[0] for row in csv.reader(io.StringIO(result.stdout))
                   if row and row[0].lower() in HOSTS})


def require_kicad_closed():
    hosts = running_kicad()
    if hosts:
        raise ValueError('Close KiCad Manager and all editors before --apply: ' + ', '.join(hosts))


def apply_repair(path, original, settings, chosen):
    """Replace one setting atomically, preserving an exact-byte recovery backup."""
    path = Path(path)
    chosen = interpreter_path(str(chosen))
    probe_interpreter(chosen)
    require_kicad_closed()
    current, _ = read_config(path)
    if current != original:
        raise ValueError('KiCad settings changed after inspection. Run the preview again.')
    if settings.get('api', {}).get('interpreter_path') == str(chosen):
        return None
    updated = dict(settings)
    updated['api'] = {**settings.get('api', {}), 'interpreter_path': str(chosen)}
    payload = (json.dumps(updated, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    backup = path.with_name(path.name + '.wayricad-backup-' + stamp + '-' + uuid.uuid4().hex[:8])
    temporary = None
    try:
        with backup.open('xb') as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        with tempfile.NamedTemporaryFile(prefix='.wayricad-kicad-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, temporary, follow_symlinks=False)
        # KiCad may have opened while the backup/staging files were prepared.
        require_kicad_closed()
        if read_config(path)[0] != original:
            raise ValueError('KiCad settings changed while preparing repair. Original settings were retained.')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return backup


def diagnose(path, *, version='10.0', environ=None, kicad_root=None, interpreter=None):
    original, settings = read_config(path)
    configured = settings.get('api', {}).get('interpreter_path', '')
    report = {'config_file': str(path), 'configured_interpreter': configured,
              'api_enabled': settings.get('api', {}).get('enable_server', False),
              'stage': 'KiCad creates IPC plugin environments before running WayriCAD code',
              'configured_status': 'automatic_selection_unverified', 'issues': [], 'candidates': []}
    if not isinstance(configured, str):
        report['configured_status'] = 'malformed'
        report['issues'].append('api.interpreter_path must be a string.')
    elif configured:
        try:
            report['configured_probe'] = probe_interpreter(configured)
            report['configured_status'] = 'prerequisites_available'
        except ValueError as exc:
            report['configured_status'] = 'unavailable'
            report['issues'].append(str(exc))
    candidates = discover_interpreters(version, environ=environ, kicad_root=kicad_root, configured=configured)
    report['candidates'] = [str(candidate) for candidate in candidates]
    selected = interpreter
    if selected is None:
        if configured and report['configured_status'] == 'prerequisites_available' and kicad_root is None:
            selected = configured
        elif len(candidates) == 1:
            selected = candidates[0]
    if selected is not None:
        selected = interpreter_path(str(selected))
        report['proposed_interpreter'] = str(selected)
        report['proposed_probe'] = probe_interpreter(selected)
        report['change_required'] = configured != str(selected)
    else:
        report['issues'].append('Select the intended installation with --kicad-root or supply --interpreter; no unique runtime was selected.')
    env = os.environ if environ is None else environ
    report['python_environment_overrides'] = [key for key in ('PYTHONHOME', 'PYTHONPATH') if env.get(key)]
    report['limits'] = 'Stdlib imports do not prove venv creation, dependency installation, toolbar discovery or plugin launch. The report does not create or remove environments.'
    return report, original, settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='10.0', help='KiCad settings version (default: 10.0).')
    parser.add_argument('--config-file', type=Path, help='Exact existing kicad_common.json; honors KICAD_CONFIG_HOME otherwise.')
    parser.add_argument('--kicad-root', type=Path, help='Installation containing bin/; resolves multiple or custom installs.')
    parser.add_argument('--interpreter', type=Path, help='Exact python.exe or pythonw.exe to preview in api.interpreter_path.')
    parser.add_argument('--apply', action='store_true', help='With all KiCad processes closed, save the proposed interpreter with an exact-byte backup.')
    parser.add_argument('--json', action='store_true', help='Print the bounded diagnostic as JSON.')
    args = parser.parse_args(argv)
    if sys.platform != 'win32':
        parser.error('This helper targets Windows KiCad. Use Plugins preferences on other platforms.')
    try:
        path = (args.config_file or config_path(args.version)).expanduser().absolute()
        report, original, settings = diagnose(path, version=args.version, kicad_root=args.kicad_root, interpreter=args.interpreter)
        if args.apply:
            if 'proposed_interpreter' not in report:
                raise ValueError('No unambiguous repair was proposed. Supply --interpreter or --kicad-root.')
            backup = apply_repair(path, original, settings, report['proposed_interpreter'])
            report['backup_file'] = str(backup) if backup else None
            report['applied'] = bool(backup)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print('KiCad Python diagnostic: ' + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print('Settings: ' + report['config_file'])
        print('Configured Python: ' + str(report['configured_interpreter'] or '(KiCad automatic selection)'))
        print('Host interpreter status: ' + report['configured_status'])
        for issue in report['issues']:
            print('Issue: ' + issue)
        for candidate in report['candidates']:
            print('Installed candidate: ' + candidate)
        if report.get('proposed_interpreter'):
            print('Proposed api.interpreter_path: ' + report['proposed_interpreter'])
        if report.get('backup_file'):
            print('Saved. Original settings backup: ' + report['backup_file'])
        elif args.apply:
            print('The selected interpreter is already configured; no file changed.')
        else:
            print('Preview only. Add --apply after closing KiCad to save the proposed interpreter.')
        if report['python_environment_overrides']:
            print('Review inherited Python overrides: ' + ', '.join(report['python_environment_overrides']))
        print(report['limits'])
        print('After a repair, restart KiCad and recreate failed plugin environments from its warning panel.')
    return 0 if args.apply or report['configured_status'] == 'prerequisites_available' else 1


if __name__ == '__main__':
    raise SystemExit(main())
