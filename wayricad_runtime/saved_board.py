"""Read-only native analysis of saved boards from a newer KiCad host.

Never use this adapter for editing, DRC acceptance or writing back to an editor.
The native analysis board retains its original filename for source binding; all
loads at these analysis boundaries must consequently go through this module.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

NATIVE_FORMAT = 20260206  # KiCad 10.0 saved PCB format
CLI_ENV = 'WAYRICAD_ANALYSIS_CLI'
HOST_ENV = 'WAYRICAD_ANALYSIS_HOST_VERSION'
_INPUT_SUFFIXES = ('.kicad_pcb', '.kicad_pro', '.kicad_dru')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _inputs(path):
    return {str(item): _sha(item) if item.is_file() else None
            for item in (path.with_suffix(suffix) for suffix in _INPUT_SUFFIXES)}


def _format(path):
    try:
        with Path(path).open('rb') as stream:
            header = stream.read(4096)
    except OSError:
        return None  # Keep native missing/invalid-file diagnostics on direct loads.
    match = re.match(rb'\s*\(kicad_pcb\s+\(version\s+(\d+)\)', header)
    return int(match[1]) if match else None


def origin_environment(client, environment):
    """Bind the converter to the authenticated launching editor, not PATH."""
    environment = dict(environment)
    # Never inherit a converter belonging to a different editor instance.
    environment.pop(CLI_ENV, None)
    environment.pop(HOST_ENV, None)
    environment.pop('KICAD_CLI', None)
    version = client.get_version()
    major, minor = version.major, version.minor
    if major >= 11 or (major == 10 and minor >= 99):
        executable = Path(client.get_kicad_binary_path('kicad-cli')).expanduser()
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError('The originating KiCad editor did not supply its analysis CLI. '
                             'Install its matching kicad-cli and reopen the action.')
        environment[CLI_ENV] = str(executable.resolve())
        environment[HOST_ENV] = f'{major}.{minor}.{version.patch}'
    return environment


def _converter():
    # Standalone callers can explicitly select KICAD_CLI; never silently find
    # the helper-adjacent KiCad 10 CLI or another running editor.
    value = os.environ.get(CLI_ENV) or os.environ.get('KICAD_CLI')
    if not value:
        raise ValueError('This PCB was saved by a newer KiCad. Launch analysis from '
                         'that editor, or set KICAD_CLI to its matching kicad-cli. '
                         'The saved PCB will not be modified.')
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError('The selected newer-KiCad analysis CLI does not exist: ' + str(path))
    return path


def cache_identity(path):
    """Include project/rules and converter bytes in native/result cache keys."""
    path = Path(path).resolve()
    inputs = _inputs(path)
    if (_format(path) or 0) <= NATIVE_FORMAT:
        return (tuple(inputs.items()), None)
    converter = _converter()
    return (tuple(inputs.items()), (str(converter), _sha(converter), os.environ.get(HOST_ENV)))


def _run(command, timeout=60):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Newer-KiCad read-only conversion could not complete: ' + str(exc)) from exc
    if result.returncode:
        raise ValueError('This saved PCB cannot be analysed by the KiCad 10 backend '
                         'without unsupported conversion. No source files were changed. '
                         + (result.stderr or result.stdout)[-2000:])
    return result


class _Snapshot:
    def __init__(self, path):
        self.path = path
        self.inputs = _inputs(path)
        self.converter = _converter()
        self.converter_sha = _sha(self.converter)
        self.temporary = tempfile.TemporaryDirectory(prefix='wayricad-saved-board-',
            dir=os.environ.get('WAYRICAD_ANALYSIS_SCRATCH') or None)
        self.root = Path(self.temporary.name)
        self.input = self.root / 'input' / path.name
        self.output = self.root / 'analysis' / path.name
        self.input.parent.mkdir()
        self.output.parent.mkdir()
        try:
            for name, digest in self.inputs.items():
                if digest is not None:
                    source = Path(name)
                    target = self.input.with_suffix(source.suffix)
                    target.write_bytes(source.read_bytes())
                    if _sha(target) != digest:
                        raise ValueError('PCB/project/rules changed while capturing the analysis snapshot.')
            self.assert_current()
        except BaseException:
            self.temporary.cleanup()
            raise

    def assert_current(self):
        if _inputs(self.path) != self.inputs or _sha(self.converter) != self.converter_sha:
            raise ValueError('PCB, project rules or analysis CLI changed. Reload and run again.')
        for name, digest in self.inputs.items():
            copied = self.input.with_suffix(Path(name).suffix)
            if (_sha(copied) if copied.is_file() else None) != digest:
                raise ValueError('The private analysis input snapshot changed. Reload and run again.')

    def convert(self):
        project = self.input.with_suffix('.kicad_pro')
        if project.is_file():
            data = json.loads(project.read_text(encoding='utf-8-sig'))
            variables = data.get('text_variables', {})
            # The CLI's initial classifier lacks project context. Nested text
            # expressions can introduce new-format variables only during its
            # second classification, whose loss gate is weaker. Fail closed.
            if not isinstance(variables, dict) or any(
                    '${' in str(value) or '@{' in str(value) for value in variables.values()):
                raise ValueError('This newer PCB uses project text-variable expressions. '
                                 'Their strict conversion is not supported by this analysis backend.')
        from .analysis_process import contain_converters
        contain_converters()
        version = _run([str(self.converter), '--version'], timeout=15).stdout.strip()
        match = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
        if not match or tuple(map(int, match.groups())) < (10, 99, 0):
            raise ValueError('Choose the originating KiCad 11 development or newer CLI; '
                             'KiCad 10 CLI cannot convert this saved board.')
        host = os.environ.get(HOST_ENV)
        if host and '.'.join(match.groups()) != host:
            raise ValueError('The analysis CLI version does not match the originating editor.')
        # Actual export is the gate. Dry-run exit 0 does NOT imply compatibility.
        _run([str(self.converter), 'pcb', 'downgrade', '--target', '10.0',
              '--output', str(self.output), str(self.input)])
        if (not self.output.is_file() or self.output.is_symlink() or
                (_format(self.output) or NATIVE_FORMAT + 1) > NATIVE_FORMAT):
            raise ValueError('KiCad did not produce a readable native analysis snapshot.')
        for suffix in _INPUT_SUFFIXES[1:]:
            source = self.input.with_suffix(suffix)
            if source.is_file():
                self.output.with_suffix(suffix).write_bytes(source.read_bytes())
        self.assert_current()
        self.record = dict(schema='wayricad.saved-board-analysis/v1',
            policy='strict read-only downgrade; not DRC or editing equivalence',
            source_path=str(self.path), source_sha256=self.inputs[str(self.path)],
            source_fingerprints=dict(self.inputs), source_format=_format(self.input),
            analysis_sha256=_sha(self.output), analysis_format=_format(self.output),
            converter_path=str(self.converter), converter_sha256=self.converter_sha,
            converter_version=version, host_version=host, target='10.0')


def load_board(path, *, pcbnew=None):
    """Return a native analysis board; preserve KiCad 10's direct load path."""
    if pcbnew is None:
        import pcbnew
    path = Path(path).expanduser().resolve()
    if (_format(path) or 0) <= NATIVE_FORMAT:
        return pcbnew.LoadBoard(str(path))
    snapshot = _Snapshot(path)
    try:
        snapshot.convert()
        board = pcbnew.LoadBoard(str(snapshot.output))
        if board is None:
            raise ValueError('KiCad could not load the converted analysis snapshot.')
        snapshot.assert_current()
        # Audited read-only consumers use the original path for fingerprints,
        # reports, stackup parsing and subsequent loads through this adapter.
        board.SetFileName(str(path))
        board._wayricad_saved_board = snapshot  # Keep lazy native consumers alive.
        return board
    except BaseException:
        snapshot.temporary.cleanup()
        raise


def _snapshot(board):
    # Only an explicitly attached lease counts; proxy/fake objects can invent
    # arbitrary attributes through __getattr__ on an ordinary direct load.
    return getattr(board, '__dict__', {}).get('_wayricad_saved_board')


def assert_current(board):
    snapshot = _snapshot(board)
    if snapshot is not None:
        snapshot.assert_current()


def provenance(board):
    from copy import deepcopy
    snapshot = _snapshot(board)
    return deepcopy(snapshot.record) if snapshot is not None else None


def assert_record_current(record):
    """Guard an extracted model after its native board lease is released."""
    if record is None:
        return
    path = Path(record['source_path'])
    if (_inputs(path) != record['source_fingerprints'] or
            _sha(record['converter_path']) != record['converter_sha256']):
        raise ValueError('PCB, project rules or analysis CLI changed. Reload and run again.')
