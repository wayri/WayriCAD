"""Check and narrowly repair KiCad's IPC Python interpreter setting.

KiCad creates Python plugin environments before any WayriCAD code runs. This
module only repairs the known malformed ``pythonw/.exe`` setting and preserves
all other KiCad preferences with a timestamped backup.
"""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def settings_path(version='10.0'):
    base = Path(os.environ.get('KICAD_CONFIG_HOME', Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming')) / 'kicad'))
    return base / version / 'kicad_common.json'


def _configured_path(config):
    data = json.loads(Path(config).read_text(encoding='utf-8'))
    value = data['api']['interpreter_path']
    if not isinstance(value, str) or not value.strip():
        raise ValueError('KiCad has no Python interpreter selected')
    return data, Path(value)


def _probe(interpreter):
    console = interpreter.with_name('python.exe') if interpreter.name.lower() == 'pythonw.exe' else interpreter
    if not console.is_file():
        return False, f'KiCad console Python does not exist: {console}'
    try:
        result = subprocess.run([str(console), '-I', '-c', 'import venv'], timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f'KiCad Python cannot start: {exc}'
    if result.returncode:
        return False, f'KiCad Python cannot import venv (exit {result.returncode})'
    return True, f'KiCad Python and venv are available: {interpreter}'


def check(config):
    config = Path(config)
    if not config.is_file():
        return False, f'KiCad settings not found: {config}'
    try:
        _, interpreter = _configured_path(config)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return False, f'KiCad Python setting missing or invalid: {exc}'
    if not interpreter.is_file():
        return False, f'KiCad Python executable does not exist: {interpreter}'
    return _probe(interpreter)


def repair_candidate(config):
    """Return only the candidate implied by the observed malformed suffix."""
    _, broken = _configured_path(config)
    if broken.is_file() or broken.name.lower() != '.exe' or broken.parent.name.lower() != 'pythonw':
        return None
    return broken.parent.parent / 'python.exe'


def kicad_is_running():
    if os.name != 'nt':
        return False
    try:
        result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f'Cannot check whether KiCad is running: {exc}') from exc
    names = {row[0].casefold() for row in csv.reader(result.stdout.splitlines()) if row}
    return bool(names & {'kicad.exe', 'pcbnew.exe', 'eeschema.exe', 'cvpcb.exe', 'fp_editor.exe'})


def repair_malformed(config, *, probe=_probe, running=kicad_is_running):
    """Repair the observed typo, with backup; refuse other or uncertain cases."""
    config = Path(config)
    if not config.is_file():
        raise RuntimeError(f'KiCad settings not found: {config}')
    try:
        data, broken = _configured_path(config)
        candidate = repair_candidate(config)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise RuntimeError(f'Cannot read KiCad Python setting: {exc}') from exc
    if candidate is None:
        raise RuntimeError('Configured path is not the known pythonw/.exe typo; leaving KiCad settings unchanged')
    if not candidate.is_file():
        raise RuntimeError(f'Cannot find matching KiCad Python: {candidate}; leaving settings unchanged')
    okay, message = probe(candidate)
    if not okay:
        raise RuntimeError(message)
    if running():
        raise RuntimeError('Close KiCad Manager and PCB Editor before repairing their settings')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    backup = config.with_name(config.name + '.wayricad-backup-' + stamp)
    shutil.copy2(config, backup)
    data['api']['interpreter_path'] = str(candidate)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=config.parent, prefix=config.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, config)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return f'Repaired KiCad Python: {broken} -> {candidate}; backup: {backup}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='10.0')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--repair', action='store_true', help='Back up and repair only the known pythonw/.exe typo while KiCad is closed')
    args = parser.parse_args(argv)
    config = args.config or settings_path(args.version)
    if args.repair:
        try:
            print(repair_malformed(config))
        except RuntimeError as exc:
            print(f'No repair made: {exc}')
            return 1
        print('Restart KiCad. It will create the missing plugin environments using the corrected interpreter.')
        return 0
    okay, message = check(config)
    print(message)
    if not okay:
        print('Run this tool with --repair for the known pythonw/.exe typo, or select the installed KiCad bin/python.exe in Preferences > Plugins.')
    return 0 if okay else 1


if __name__ == '__main__':
    raise SystemExit(main())
