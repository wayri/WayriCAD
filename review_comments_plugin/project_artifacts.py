"""Bounded project-local manufacturing files; generation is an explicit action."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .review_targets import GERBER_SUFFIXES, relative_path

MAX_FILES = 128
MAX_BYTES = 64 * 1024 * 1024


def local_file(root, path):
    root = Path(root).resolve(strict=True)
    raw = Path(path).absolute()
    if not raw.is_relative_to(root):
        raise ValueError('Choose a file inside this project directory.')
    current = root
    for part in raw.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Project artifacts cannot use linked paths.')
    if not raw.is_file() or raw.resolve() != raw:
        raise ValueError('The project artifact is missing or moved.')
    if raw.stat().st_size > MAX_BYTES:
        raise ValueError('Project artifact exceeds 64 MiB.')
    return raw


def read_artifact(root, path):
    path = local_file(root, path)
    if path.suffix.lower() not in GERBER_SUFFIXES:
        raise ValueError('Choose a local Gerber or drill drawing.')
    data = path.read_bytes()
    if len(data) > MAX_BYTES or path.read_bytes() != data:
        raise ValueError('Manufacturing file changed during read.')
    source = data.decode('utf-8-sig')
    if '\x00' in source or not source.strip():
        raise ValueError('Manufacturing source must be nonempty text.')
    return dict(path=path.relative_to(Path(root).resolve()).as_posix(), source=source,
                source_sha256=hashlib.sha256(data).hexdigest(), view='manufacturing')


def discover_gerbers(root):
    root = Path(root).resolve(strict=True)
    found, total, inspected = [], 0, 0
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories
            if name not in ('.git', '.venv', 'node_modules', '__pycache__')
            and not (Path(directory) / name).is_symlink())
        for name in sorted(names):
            inspected += 1
            if inspected > 10000:
                raise ValueError('Project scan exceeds 10,000 entries; load a specific Gerber file.')
            path = Path(directory) / name
            if path.suffix.lower() not in GERBER_SUFFIXES or path.is_symlink():
                continue
            path = local_file(root, path)
            total += path.stat().st_size
            if len(found) >= MAX_FILES or total > MAX_BYTES:
                raise ValueError('Project Gerbers exceed 128 files or 64 MiB; choose individual files.')
            found.append(path)
    return found


def gerber_anchor(target_scope, project_root, path, *, variant='*', position=None, area=None):
    from .model import anchor
    payload = read_artifact(project_root, path)
    context = dict(type='gerber', file=payload['path'], sha256=payload['source_sha256'])
    if position is not None:
        context['position'] = position
    if area is not None:
        context['area'] = area
    return anchor(dict(target_scope, kind='gerber',
        objectId='gerber:' + hashlib.sha256(payload['path'].encode()).hexdigest(),
        reference=Path(path).name[:100], variant=variant, context=context))


def find_cli():
    if not os.environ.get('KICAD_CLI') and os.environ.get('KICAD_API_SOCKET') and os.environ.get('KICAD_API_TOKEN'):
        from wayricad_runtime.context import connect
        executable = Path(connect().get_kicad_binary_path('kicad-cli'))
        if not executable.is_file():
            raise ValueError('The originating KiCad editor has no matching CLI. Configure KICAD_CLI explicitly.')
        return str(executable)
    from wayricad_runtime.jobs import find_kicad_cli
    return find_kicad_cli()


def generate_gerbers(board, *, cli=None):
    """Create a unique project-local output folder, never overwrite existing CAM."""
    board = Path(board).absolute()
    board = local_file(board.parent, board)
    if board.suffix.lower() != '.kicad_pcb':
        raise ValueError('Gerber generation needs a saved PCB.')
    root = board.parent
    if shutil.disk_usage(root).free < 2 * MAX_BYTES:
        raise ValueError('Not enough disk space for manufacturing output. Load existing project Gerbers instead.')
    sources = {}
    for candidate in (board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru')):
        if candidate.exists():
            data = local_file(root, candidate).read_bytes()
            if len(data) > MAX_BYTES:
                raise ValueError('Export source exceeds the input size limit.')
            sources[candidate.name] = data
    if sum(map(len, sources.values())) > 2 * MAX_BYTES:
        raise ValueError('Export project inputs exceed 128 MiB.')
    output = Path(tempfile.mkdtemp(prefix='review-gerbers-', dir=root))
    try:
        # KiCad may write adjacent project-local preferences. Export a bounded
        # disposable snapshot so no original project or preference is touched.
        with tempfile.TemporaryDirectory(prefix='.input-', dir=output) as temporary:
            temporary = Path(temporary)
            for name, data in sources.items(): (temporary/name).write_bytes(data)
            command = [str(cli or find_cli()), 'pcb', 'export', 'gerbers', '--output', str(output), str(temporary/board.name)]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, cwd=temporary,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            from wayricad_runtime.context import redact_error
            detail = redact_error((result.stderr or result.stdout).decode('utf-8', errors='replace'))[:1000]
            if not detail.strip():
                detail = f'Native CLI exited with code 0x{result.returncode & 0xffffffff:08X} before reporting an error. Check the matching KiCad CLI installation.'
            raise ValueError('KiCad Gerber export failed: ' + detail + ' Output directory retained: ' + output.name)
        if any(local_file(root, root/name).read_bytes() != data for name, data in sources.items()):
            raise ValueError('Saved project changed during generation. Output was retained but cannot be treated as current.')
        files = discover_gerbers(output)
        if not files:
            raise ValueError('KiCad produced no supported Gerber drawings. Output was retained.')
        return output, files
    except subprocess.TimeoutExpired:
        raise ValueError('KiCad Gerber export timed out. Partial output was retained; no export was confirmed.') from None
    except Exception:
        # Preserve partial results; no broad cleanup or silent overwrite.
        raise
