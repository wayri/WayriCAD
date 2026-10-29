"""Transactional, per-user solver environments. Never upgrade an active venv."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

from packaging.version import InvalidVersion, Version

from .backend import atomic_json, SUPPORTED_VERSION
from .compatibility import CERTIFICATE_NAME, adapter_signature, read_certificate, runtime_certificate


CHECK_INTERVAL = 24 * 60 * 60
MIN_FREE_BYTES = 3 * 1024**3
# The complete compatibility matrix includes a PML solve and CAD/export readback.
# Keep an active runtime untouched while a slower candidate finishes this gate.
QUALIFICATION_TIMEOUT = 1200
SOLVER_EXTRAS = ('ezdxf>=1.4,<2', 'msgpack>=1.1,<2', 'msgpack-numpy>=0.4.8,<0.5')
ENTRY = Path(__file__).with_name('__main__.py')


class SetupCancelled(RuntimeError):
    pass


def default_home():
    override = os.environ.get('WAYRICAD_QUICK_EMERGE_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))
    elif sys.platform == 'darwin':
        base = Path.home()/'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
    return base/'WayriCAD/quick-emerge/runtimes'


def environment_python(folder):
    return Path(folder)/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


@contextmanager
def setup_lock(home):
    """OS-owned lock releases automatically after a crash; never delete it."""
    home.mkdir(parents=True, exist_ok=True)
    with (home/'setup.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another Quick EMerge window is setting up dependencies. Retry when it finishes.') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def latest_release():
    """Include 3.x prereleases while upstream's stable release is still 2.x."""
    request = urllib.request.Request('https://pypi.org/pypi/emerge/json',
                                     headers={'User-Agent': 'WayriCAD-Quick-EMerge/0.1'})
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read(8*1024*1024+1)
    if len(content) > 8*1024*1024:
        raise RuntimeError('EMerge package metadata exceeds the supported size.')
    return select_release(json.loads(content))


def select_release(metadata):
    candidates = []
    for version, files in metadata.get('releases', {}).items():
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        if parsed.major >= 3 and not parsed.is_devrelease and any(not f.get('yanked', False) for f in files):
            candidates.append(parsed)
    if not candidates:
        raise RuntimeError('No non-yanked EMerge 3+ release is available.')
    return str(max(candidates))


def run_command(argv, *, log, cancel, timeout=1200, progress=lambda value: None):
    env = os.environ.copy()
    # Keep proxy/certificate settings, but prevent inherited Python path injection.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
        env.pop(key, None)
    started = time.monotonic()
    with Path(log).open('ab') as stream:
        process = subprocess.Popen([str(v) for v in argv], stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                   env=env, cwd=Path(log).parent,
                                   start_new_session=os.name != 'nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                if cancel.wait(.25):
                    raise SetupCancelled('Dependency setup cancelled; the previous runtime is unchanged.')
                if time.monotonic()-started > timeout:
                    raise RuntimeError('Dependency setup timed out. See '+str(log))
                if shutil.disk_usage(Path(log).parent).free < 512*1024**2:
                    raise RuntimeError('Dependency setup stopped before disk space was exhausted. See '+str(log))
                with Path(log).open('rb') as reader:
                    reader.seek(0, 2); reader.seek(max(0, reader.tell()-3000))
                    progress(reader.read().decode('utf-8', errors='replace'))
            if process.returncode:
                raise RuntimeError(f'Dependency command failed (exit {process.returncode}). See {log}')
        finally:
            if process.poll() is None:
                # Stop installer subprocesses as well as their Python parent.
                if os.name == 'nt':
                    try:
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=15)
                    except (OSError, subprocess.TimeoutExpired):
                        process.terminate()
                else:
                    import signal
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.kill(); process.wait(timeout=5)


def discover_python():
    override = os.environ.get('WAYRICAD_QUICK_EMERGE_PYTHON')
    candidates = [[override]] if override else [[sys.executable]]
    if not override:
        if os.name == 'nt':
            launcher = shutil.which('py')
            if launcher:
                candidates.extend([[launcher, f'-3.{minor}'] for minor in (13, 12, 11, 10)])
            installed = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'KiCad'
            if installed.is_dir():
                candidates.extend([str(p)] for p in sorted(installed.glob('*/bin/python.exe'), reverse=True))
        else:
            candidates.extend([[p]] for minor in (13, 12, 11, 10)
                              if (p := shutil.which(f'python3.{minor}')))
    for command in candidates:
        try:
            probe = subprocess.run([*command, '-I', '-c',
                                    'import sys; print(sys.executable if (3,10)<=sys.version_info[:2]<(3,14) else "")'],
                                   capture_output=True, text=True, timeout=10,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            executable = probe.stdout.strip()
            if probe.returncode == 0 and executable and Path(executable).is_file():
                return Path(executable)
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError('Install Python 3.10–3.13, or set WAYRICAD_QUICK_EMERGE_PYTHON to its executable. EMerge currently excludes Python 3.14.')


class DependencyManager:
    def __init__(self, home=None):
        self.home = Path(home or default_home()).resolve()

    def _read_state(self):
        try:
            state = json.loads((self.home/'active.json').read_text(encoding='utf-8'))
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _runtime(self, name):
        if not isinstance(name, str) or Path(name).name != name:
            return None
        folder = (self.home/name).resolve()
        if folder.parent != self.home:
            return None
        cert = runtime_certificate(folder)
        python = environment_python(folder)
        if cert and python.is_file():
            try:
                probe = subprocess.run([str(python), '-I', '-c',
                                        'import importlib.metadata as m; print(m.version("emerge"))'],
                                       capture_output=True, text=True, timeout=10,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if probe.returncode == 0 and probe.stdout.strip() == cert['version']:
                    return {'python': str(python), 'version': cert['version'], 'environment': name}
            except (OSError, subprocess.TimeoutExpired):
                pass
        return None

    def active(self):
        return self._runtime(self._read_state().get('active'))

    def _requalify(self, name, cancel, progress):
        """Refresh adapter evidence without installing or modifying any packages."""
        if not isinstance(name, str) or Path(name).name != name:
            return None
        folder = (self.home/name).resolve()
        if folder.parent != self.home or (self.home/name).is_symlink():
            return None
        try:
            ownership = json.loads((folder/'managed.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        certificate = read_certificate(folder/CERTIFICATE_NAME, allow_stale=True)
        if (not isinstance(ownership, dict) or ownership.get('schema') != 1
                or ownership.get('owner') != 'quick-emerge' or not certificate
                or ownership.get('version') != certificate['version']):
            return None
        python = environment_python(folder)
        if not python.is_file():
            return None
        probe = subprocess.run([str(python), '-I', '-c',
                                'import importlib.metadata as m; print(m.version("emerge"))'],
                               capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if probe.returncode or probe.stdout.strip() != certificate['version']:
            return None
        pending = folder/('qualification-pending-'+uuid.uuid4().hex+'.json')
        log = self.home/(name+'-requalification.log')
        try:
            if cancel.is_set():
                raise SetupCancelled('Runtime requalification cancelled.')
            progress('Requalifying the existing managed runtime for this adapter; packages stay unchanged…')
            run_command([python, '-I', '-m', 'pip', '--isolated', 'check'], log=log,
                        cancel=cancel, timeout=60, progress=progress)
            run_command([python, '-I', ENTRY, '--qualify-runtime', pending], log=log,
                        cancel=cancel, timeout=QUALIFICATION_TIMEOUT, progress=progress)
            refreshed = read_certificate(pending)
            if not refreshed or refreshed['version'] != certificate['version']:
                raise RuntimeError('Existing runtime did not produce matching current compatibility evidence.')
            if cancel.is_set():
                raise SetupCancelled('Runtime requalification cancelled before certificate replacement.')
            os.replace(pending, folder/CERTIFICATE_NAME)
            return self._runtime(name)
        finally:
            pending.unlink(missing_ok=True)

    def ensure(self, *, force=False, cancel=None, progress=lambda value: None):
        cancel = cancel or threading.Event()
        with setup_lock(self.home):
            state = self._read_state()
            active = self._runtime(state.get('active'))
            requalification_error = None
            if active is None:
                try:
                    active = self._requalify(state.get('active'), cancel, progress)
                except SetupCancelled:
                    raise
                except Exception as exc:
                    requalification_error = str(exc)
                    progress('Existing runtime requalification failed; its previous certificate was retained. '+str(exc))
            checked = state.get('checked_at', 0)
            checked = checked if isinstance(checked, (int, float)) and not isinstance(checked, bool) else 0
            if active and not force and 0 <= time.time()-checked < CHECK_INTERVAL:
                return {**active, 'message': 'Compatible managed runtime ready.'}
            try:
                progress('Checking the latest EMerge 3+ release…')
                version = latest_release()
                if active and Version(version) <= Version(active['version']):
                    state['checked_at'] = time.time()
                    atomic_json(self.home/'active.json', state)
                    return {**active, 'message': 'Managed runtime is up to date.'}
                if (not force and active and state.get('rejected') == [version, adapter_signature()]):
                    return {**active, 'message': 'Latest release did not pass compatibility checks; retaining the working runtime.'}
            except Exception as exc:
                if active:
                    state['checked_at'] = time.time()
                    atomic_json(self.home/'active.json', state)
                    return {**active, 'message': f'Update check unavailable; retained {active["version"]}. {exc}'}
                # Try the tested baseline after a transient metadata lookup failure.
                version = SUPPORTED_VERSION
                progress(f'Latest-release lookup failed ({exc}); trying the tested baseline {version}.')
            if cancel.is_set():
                raise SetupCancelled('Dependency setup cancelled.')
            if shutil.disk_usage(self.home).free < MIN_FREE_BYTES:
                if active:
                    return {**active, 'message': 'Update deferred: at least 3 GiB free is required for a candidate environment.'}
                detail = (' Existing runtime requalification failed: '+requalification_error) if requalification_error else ''
                raise RuntimeError('Solver setup requires at least 3 GiB free for a new environment. Retry requalification or set WAYRICAD_QUICK_EMERGE_HOME to a drive with enough space.'+detail)
            try:
                candidate = self._install(version, cancel, progress)
            except Exception as exc:
                if isinstance(exc, SetupCancelled):
                    raise
                if active:
                    state.update(checked_at=time.time(), rejected=[version, adapter_signature()])
                    atomic_json(self.home/'active.json', state)
                    return {**active, 'message': f'Update rejected; kept EMerge {active["version"]}. {exc}'}
                if version == SUPPORTED_VERSION:
                    raise RuntimeError(f'First-open solver setup failed. Retry setup or select a solver Python manually. {exc}') from exc
                progress(f'Latest release failed checks ({exc}); installing tested baseline {SUPPORTED_VERSION} instead.')
                candidate = self._install(SUPPORTED_VERSION, cancel, progress)
            if cancel.is_set():
                raise SetupCancelled('Dependency setup cancelled before activation.')
            state = {'schema': 1, 'active': candidate['environment'], 'previous': state.get('active') if active else None,
                     'checked_at': time.time()}
            atomic_json(self.home/'active.json', state)
            return {**candidate, 'message': f'EMerge {candidate["version"]} installed and compatibility checks passed.'}

    def _install(self, version, cancel, progress):
        if cancel.is_set():
            raise SetupCancelled('Dependency setup cancelled.')
        if shutil.disk_usage(self.home).free < MIN_FREE_BYTES:
            raise RuntimeError('Candidate installation requires at least 3 GiB free.')
        identifier = 'emerge-'+version+'-'+uuid.uuid4().hex[:10]
        folder = self.home/identifier
        folder.mkdir()
        log = self.home/(identifier+'.log')
        atomic_json(folder/'managed.json', {'schema': 1, 'owner': 'quick-emerge', 'version': version})
        try:
            base = discover_python()
            progress(f'Creating an isolated Python environment for EMerge {version}…')
            run_command([base, '-I', '-m', 'venv', folder], log=log, cancel=cancel, timeout=120, progress=progress)
            python = environment_python(folder)
            progress(f'Installing EMerge {version} and its dependencies…')
            run_command([python, '-I', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                         '--no-cache-dir', '--only-binary=:all:', '--index-url', 'https://pypi.org/simple',
                         f'emerge[cad]=={version}', *SOLVER_EXTRAS], log=log, cancel=cancel, progress=progress)
            run_command([python, '-I', '-m', 'pip', '--isolated', 'check'], log=log, cancel=cancel,
                        timeout=60, progress=progress)
            progress('Qualifying geometry, solves, fields, radiation and adaptive APIs…')
            run_command([python, '-I', ENTRY, '--qualify-runtime', folder/'quick-emerge-qualified.json'],
                        log=log, cancel=cancel, timeout=QUALIFICATION_TIMEOUT, progress=progress)
            candidate = self._runtime(identifier)
            if candidate is None or candidate['version'] != version:
                raise RuntimeError('Candidate did not produce a matching compatibility certificate.')
            if cancel.is_set():
                raise SetupCancelled('Dependency setup cancelled before activation.')
            return candidate
        except Exception:
            # Only this call's unactivated environment is disposable. Preserve
            # previous versions, unrelated content and diagnostic logs.
            resolved = folder.resolve()
            try:
                owned = json.loads((folder/'managed.json').read_text()).get('owner') == 'quick-emerge'
                if resolved.parent == self.home and resolved == folder.absolute() and not folder.is_symlink() and owned:
                    shutil.rmtree(resolved)
            except (OSError, ValueError, TypeError):
                progress('Candidate cleanup incomplete; inspect '+str(folder))
            raise

    def rollback(self):
        with setup_lock(self.home):
            state = self._read_state()
            previous = self._runtime(state.get('previous'))
            if previous is None:
                raise RuntimeError('No compatible previous managed runtime is available.')
            state['active'], state['previous'] = state['previous'], state['active']
            state['checked_at'] = time.time()
            atomic_json(self.home/'active.json', state)
            return {**previous, 'message': 'Previous compatible runtime restored.'}
