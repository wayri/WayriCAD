"""Pinned, user-local CalculiX provisioning; never modify KiCad or PATH."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

VERSION = '2.23'
URL = 'https://www.dhondt.de/calculix_2.23_4win.zip'
ARCHIVE_SHA256 = '87fc4e1721df37370ec67d0a244bb14f9bf804b0a95df49e2ae7369d30ec72e8'
BINARY_SHA256 = 'e18360eb32a5cd48f91a212c57069212cd8e27d2f798a599a78106bd0b3ecc1f'
MAX_DOWNLOAD = 64 * 1024 * 1024
MEMBER = 'calculix_2.23_4win/ccx_static.exe'


def solver_root():
    from wayricad_runtime.runtime_setup import cache_root
    override = os.environ.get('WAYRICAD_SOLVER_CACHE')
    return Path(override).expanduser().resolve() if override else cache_root().parent / 'solvers'


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def cached_calculix(root=None):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        return None
    path = Path(root or solver_root()) / ('calculix-' + VERSION + '-win64') / 'ccx.exe'
    if path.is_file() and _hash(path) == BINARY_SHA256:
        return str(path)
    return None


def ensure_calculix(*, root=None, archive=None, progress=None):
    """Install the reviewed Windows solver atomically, or give platform guidance."""
    from wayricad_runtime.runtime_setup import _lock
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('Automatic CalculiX setup supports Windows x64. Install ccx with your '
                           'OS package manager, then select it or set WAYRICAD_CCX.')
    root = Path(root or solver_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _lock(root / 'calculix-setup.lock', 300):
        found = cached_calculix(root)
        if found:
            return found
        target = root / ('calculix-' + VERSION + '-win64')
        if target.exists():
            raise RuntimeError('Managed CalculiX cache failed integrity checks. Select a trusted '
                               'solver or a new WAYRICAD_SOLVER_CACHE directory; existing files were preserved.')
        if shutil.disk_usage(root).free < 256 * 1024 * 1024:
            raise RuntimeError('CalculiX setup needs at least 256 MiB free in the solver cache.')
        with tempfile.TemporaryDirectory(prefix='.calculix-setup-', dir=root) as scratch:
            work = Path(scratch)
            payload = Path(archive) if archive else work / 'download.zip'
            if not archive:
                try:
                    if progress:
                        progress(0, 61675985)
                    with urlopen(URL, timeout=60) as response, payload.open('wb') as output:
                        if not response.geturl().startswith('https://www.dhondt.de/'):
                            raise RuntimeError('CalculiX download redirected outside the official host.')
                        size = 0
                        while block := response.read(1024 * 1024):
                            size += len(block)
                            if size > MAX_DOWNLOAD:
                                raise RuntimeError('CalculiX download exceeded its size limit.')
                            output.write(block)
                            if progress:
                                progress(size, 61675985)
                except OSError as exc:
                    raise RuntimeError('CalculiX download failed. Retry online or select an existing '
                                       'ccx executable for offline use.') from exc
            if payload.stat().st_size > MAX_DOWNLOAD or _hash(payload) != ARCHIVE_SHA256:
                raise RuntimeError('CalculiX archive checksum mismatch; nothing was installed.')
            candidate = work / 'candidate'
            candidate.mkdir()
            with zipfile.ZipFile(payload) as bundle:
                # Extract only reviewed files to fixed names, never archive paths.
                for member, filename, limit in ((MEMBER, 'ccx.exe', 48*1024*1024),
                        ('calculix_2.23_4win/README_Install', 'README_Install', 64*1024)):
                    info = bundle.getinfo(member)
                    if info.file_size > limit:
                        raise RuntimeError('CalculiX member exceeded its size limit.')
                    with bundle.open(info) as source, (candidate / filename).open('wb') as output:
                        shutil.copyfileobj(source, output)
            exe = candidate / 'ccx.exe'
            if _hash(exe) != BINARY_SHA256:
                raise RuntimeError('CalculiX binary checksum mismatch; nothing was installed.')
            probe = subprocess.run([str(exe), '-v'], cwd=candidate, capture_output=True,
                                   text=True, timeout=30,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if VERSION not in probe.stdout + probe.stderr:
                raise RuntimeError('CalculiX failed its launch check; no installation was activated.')
            receipt = dict(version=VERSION, url=URL, archive_sha256=ARCHIVE_SHA256,
                           binary_sha256=BINARY_SHA256, license='GPL-2.0-or-later',
                           source_url='https://www.dhondt.de/ccx_2.23.src.tar.bz2')
            (candidate / 'provenance.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            os.replace(candidate, target)
        return str(target / 'ccx.exe')
