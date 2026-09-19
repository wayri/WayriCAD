"""Private, recoverable runtimes built on KiCad's native Python installation.

Never install packages into KiCad itself. System site packages are intentional:
they provide KiCad's ABI-matched pcbnew and wx bindings, including Linux distro
packages for which PyPI wheels do not exist.
"""
from contextlib import contextmanager
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def _pip_source_options(python):
    """Honor access/offline settings without honoring installation destinations."""
    allowed = ('index-url', 'extra-index-url', 'find-links', 'no-index',
               'proxy', 'cert', 'client-cert', 'cache-dir', 'trusted-host')
    config = {}
    result = _run([str(python), '-I', '-m', 'pip', 'config', 'list'])
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            key, separator, value = line.partition('=')
            if separator:
                try:
                    config[key.strip()] = str(ast.literal_eval(value))
                except (ValueError, SyntaxError):
                    continue
    options = []
    for name in allowed:
        value = config.get(':env:.' + name, config.get('install.' + name, config.get('global.' + name)))
        if value is None:
            continue
        if name == 'no-index':
            if value.lower() in ('1', 'true', 'yes', 'on'):
                options.append('--no-index')
        elif name in ('extra-index-url', 'find-links', 'trusted-host'):
            # pip itself treats repeatable environment/config options as whitespace lists.
            for item in value.split():
                options.extend(['--' + name, item])
        else:
            options.extend(['--' + name, value])
    return options

REQUIREMENTS_IPC = {'kipy': 'kicad-python>=0.8.0,<0.9',
                    'networkx': 'networkx>=2.8,<4', 'zstandard': 'zstandard>=0.25,<1'}
REQUIREMENTS_QUICK_PI = {
    'numpy': 'numpy>=1.24,<3', 'scipy': 'scipy>=1.10,<2',
    'matplotlib': 'matplotlib>=3.7,<4', 'vtk': 'vtk>=9.3,<10',
    'kipy': 'kicad-python>=0.8.0,<0.9',
}


def child_environment():
    env = os.environ.copy()
    foreign_roots = [env.get(name) for name in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'PYTHONHOME')]
    def foreign(entry):
        candidate = os.path.normcase(os.path.abspath(entry))
        for root in foreign_roots:
            if root:
                base = os.path.normcase(os.path.abspath(root))
                if candidate == base or candidate.startswith(base + os.sep):
                    return True
        return False
    if 'PATH' in env:
        env['PATH'] = os.pathsep.join(part for part in env['PATH'].split(os.pathsep)
                                    if part and not foreign(part))
    for name in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX',
                 'CONDA_DEFAULT_ENV', 'PYTHONUSERBASE', '__PYVENV_LAUNCHER__'):
        env.pop(name, None)
    env['PYTHONNOUSERSITE'] = '1'
    env['WAYRICAD_EMBED3D_NO_REGISTER'] = '1'
    # Keep IPC socket/token verbatim: they identify the invoking KiCad instance.
    return env


def _run(command, timeout=30, log=None):
    return subprocess.run(command, env=child_environment(), timeout=timeout,
                          stdout=log or subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _probe(python, requirements=()):
    modules = ['pcbnew', 'wx', *requirements]
    code = ('import importlib,json,sys; '
            'mods=[importlib.import_module(n) for n in ' + repr(modules) + ']; '
            'assert str(mods[0].Version()).startswith("10."), "KiCad 10 required"; '
            'assert hasattr(mods[0], "LoadBoard"); '
            + ('import importlib.metadata; assert importlib.metadata.version("kicad-python").startswith("0.8."), "kicad-python 0.8.x required"; '
               if 'kipy' in modules else '') +
            'print(json.dumps([sys.version,sys.base_prefix]))')
    try:
        result = _run([str(python), '-I', '-c', code])
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def native_python():
    override = os.environ.get('WAYRICAD_KICAD_PYTHON')
    candidates = [override] if override else [sys.executable]
    if not override:
        for root in (os.environ.get('ProgramFiles', 'C:/Program Files'),
                     os.environ.get('ProgramW6432', 'C:/Program Files')):
            candidates.extend(sorted((Path(root) / 'KiCad').glob('10.*/bin/python.exe'), reverse=True))
        candidates.extend([
            '/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3',
            '/Applications/KiCad/KiCad.app/Contents/MacOS/python3',
            '/usr/bin/python3', '/usr/local/bin/python3',
        ])
    for candidate in dict.fromkeys(str(p) for p in candidates if p):
        if Path(candidate).is_file() and _probe(candidate):
            # Resolving a POSIX venv executable symlink loses its site-packages.
            return Path(os.path.abspath(candidate))
    raise RuntimeError('KiCad 10 Python with pcbnew and wx could not be loaded. '
                       'Install the complete KiCad 10 desktop package (including Python bindings), '
                       'or set WAYRICAD_KICAD_PYTHON to its Python executable. '
                       'On Linux install your distribution\'s KiCad and python3-wxgtk4.0 packages.')


def cache_root():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Caches'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    return base / 'WayriCAD' / 'runtimes'


@contextmanager
def _lock(path, timeout):
    """OS advisory locks are released on process exit; never delete lock files."""
    with open(path, 'a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Another WayriCAD window is preparing dependencies. '
                                       'Wait for setup to finish and try again.')
                time.sleep(.2)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def ensure_runtime(requirements=(), *, cache_dir=None, timeout=300):
    """Return a tested executable; lazily install declared imports in a private venv.

    ``requirements`` maps import names to trusted pip requirement specifications.
    Native-only callers pass nothing and never create an environment or use pip.
    """
    requirements = dict(requirements)
    native = native_python()
    identity = _probe(native)
    if _probe(native, requirements):
        return native
    root = Path(cache_dir) if cache_dir is not None else cache_root()
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps([str(native), identity, sorted(requirements.items())]).encode()).hexdigest()[:20]
    folder = root / key
    executable = folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    log_path = root / (key + '.log')
    with _lock(root / (key + '.lock'), timeout):
        if executable.is_file() and _probe(executable, requirements):
            return executable
        try:
            with log_path.open('w', encoding='utf-8') as log:
                if not executable.is_file() or not _probe(executable):
                    # Only this deterministic cache subdirectory is rebuilt under its lock.
                    if folder.exists():
                        if folder.is_symlink():
                            raise RuntimeError('Runtime cache must not be a symbolic link.')
                        if folder.resolve().parent != root.resolve():
                            raise RuntimeError('Runtime cache target escaped its cache directory.')
                        shutil.rmtree(folder)
                    result = _run([str(native), '-I', '-m', 'venv', '--system-site-packages', str(folder)], timeout, log)
                    if result.returncode:
                        raise RuntimeError('Could not create a private environment; on Linux install python3-venv.')
                missing = [spec for module, spec in requirements.items() if not _probe(executable, [module])]
                if missing:
                    result = _run([str(executable), '-I', '-m', 'pip', '--isolated', 'install',
                                   '--disable-pip-version-check', '--only-binary=:all:',
                                   '--retries', '1', '--timeout', '30',
                                   *_pip_source_options(executable), *missing], timeout, log)
                    if result.returncode:
                        raise RuntimeError('Dependency download failed or no compatible binary wheel is available.')
                if not _probe(executable, requirements):
                    raise RuntimeError('Installed dependencies could not be imported with KiCad bindings.')
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f'{exc}\nSetup log: {log_path}\n'
                               'Check network/proxy access and available disk space, then retry. '
                               'KiCad itself was not modified.') from exc
    return executable
