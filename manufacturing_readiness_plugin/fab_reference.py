"""Read-only native IPC-D-356 reference export; never a CAM copper extraction."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

from .verification import find_cli
from wayricad_runtime.report_ui import publish_documents

MAX_SOURCE_BYTES = 64 * 1024 * 1024


def check_reference_receipt(reference_path, board_path=None):
    """Check our optional sidecar; absent receipts never imply board binding."""
    reference = Path(reference_path).resolve(strict=True)
    sidecar = reference.with_suffix(reference.suffix + '.receipt.json')
    if not sidecar.exists():
        return dict(status='UNVERIFIED', notice='No native reference receipt; active-board correspondence is not verified.')
    if not sidecar.is_file() or sidecar.stat().st_size > 65536:
        raise ValueError('Native reference receipt is not a bounded JSON file.')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('Duplicate native reference receipt field.')
            value[key] = item
        return value
    data = sidecar.read_bytes()
    if len(data) > 65536:
        raise ValueError('Native reference receipt exceeds 64 KiB.')
    def invalid(value):
        raise ValueError('Non-finite native reference receipt value: ' + value)
    try:
        receipt = json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('Native reference receipt must be bounded UTF-8 JSON.') from exc
    if not isinstance(receipt, dict) or receipt.get('schema') != 'wayricad.fab-reference/v1' or receipt.get('basis') != 'design-netlist':
        raise ValueError('Unrecognized native reference receipt.')
    if reference.stat().st_size > MAX_SOURCE_BYTES or hashlib.sha256(reference.read_bytes()).hexdigest() != receipt.get('output_sha256'):
        raise ValueError('Reference bytes differ from the native export receipt; regenerate the reference.')
    bound = False
    if board_path:
        board = Path(board_path).resolve(strict=True)
        if board.stat().st_size > MAX_SOURCE_BYTES or hashlib.sha256(board.read_bytes()).hexdigest() != receipt.get('source_sha256'):
            raise ValueError('Reference receipt belongs to different saved PCB bytes; export a new reference.')
        bound = True
    return dict(status='BOUND_TO_SAVED_BOARD' if bound else 'REFERENCE_HASH_CHECKED',
                receipt_path=str(sidecar), receipt_sha256=hashlib.sha256(data).hexdigest(),
                board_sha256=receipt.get('source_sha256'),
                notice='Local hash correspondence only, not authenticated CAM or fabrication evidence.')


def _cancelled(cancel):
    return bool(cancel and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()))


def _command(cli, arguments, folder, timeout_s, cancel):
    log = Path(folder) / 'native.log'
    with log.open('wb') as output:
        process = subprocess.Popen([str(cli), *map(str, arguments)], stdout=output,
            stderr=subprocess.STDOUT, cwd=folder,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + timeout_s
        try:
            while process.poll() is None:
                if _cancelled(cancel):
                    raise InterruptedError('Reference export cancelled; no output accepted.')
                if time.monotonic() > deadline:
                    raise TimeoutError('Native reference export exceeded its time budget.')
                if log.stat().st_size > 1024 * 1024:
                    raise ValueError('Native reference diagnostics exceeded 1 MiB.')
                time.sleep(.05)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
    if _cancelled(cancel):
        raise InterruptedError('Reference export cancelled; no output accepted.')
    if log.stat().st_size > 1024 * 1024:
        raise ValueError('Native reference diagnostics exceeded 1 MiB.')
    diagnostics = log.read_text(encoding='utf-8', errors='replace').strip()
    if process.returncode:
        raise ValueError(f'KiCad reference export failed ({process.returncode}): {diagnostics[:2000]}')
    return diagnostics


def export_reference(board_path, destination, *, cli=None, timeout_s=120, cancel=None):
    """Export saved PCB assignments on a private copy, retaining a hash receipt.

    Destinations must be new. The original board is never passed to a writer.
    The receipt distinguishes design net assignments from independent CAM data.
    """
    board = Path(board_path).resolve(strict=True)
    destination = Path(destination).resolve()
    receipt_path = destination.with_suffix(destination.suffix + '.receipt.json')
    if board.suffix.lower() != '.kicad_pcb' or not board.is_file():
        raise ValueError('Choose a saved .kicad_pcb file.')
    if destination.suffix.lower() not in ('.d356', '.ipc', '.356', '.ipc356'):
        raise ValueError('Choose a new IPC-D-356 output filename (.d356 or .ipc).')
    if not isinstance(timeout_s, (float, int)) or isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 3600:
        raise ValueError('Timeout must be finite and between 0 and 3600 seconds.')
    for target in (destination, receipt_path):
        if target == board or (target.exists() and os.path.samefile(target, board)):
            raise ValueError('Reference output cannot overwrite or alias the source board.')
        if target.exists():
            raise ValueError('Reference export requires new output and receipt paths.')
    if board.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('Source board exceeds 64 MiB.')
    data = board.read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError('Source board exceeds 64 MiB.')
    digest = hashlib.sha256(data).hexdigest()
    selected = Path(cli).expanduser().resolve(strict=True) if cli else find_cli()
    if selected is None or not selected.is_file():
        raise ValueError('KiCad CLI is unavailable; specify the originating KiCad installation with --cli.')
    if _cancelled(cancel):
        raise InterruptedError('Reference export cancelled; no output accepted.')
    with tempfile.TemporaryDirectory(prefix='wayricad-fab-reference-') as folder:
        snapshot = Path(folder) / board.name
        snapshot.write_bytes(data)
        output = Path(folder) / 'reference.d356'
        version = _command(selected, ['--version'], folder, min(timeout_s, 10), cancel)
        diagnostics = _command(selected, ['pcb', 'export', 'ipcd356', '--output', output, snapshot], folder, timeout_s, cancel)
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
            raise ValueError('Native exporter changed the saved input copy; no output accepted.')
        if not output.is_file() or output.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('Native exporter produced no bounded IPC-D-356 reference.')
        exported = output.read_bytes()
        if not exported:
            raise ValueError('Native exporter returned an empty IPC-D-356 reference.')
    receipt = dict(schema='wayricad.fab-reference/v1', created_utc=datetime.now(timezone.utc).isoformat(),
        source_file=board.name, source_sha256=digest, output_file=destination.name,
        output_sha256=hashlib.sha256(exported).hexdigest(), kicad_version=version[:200],
        producer='kicad-cli pcb export ipcd356', basis='design-netlist',
        diagnostics=diagnostics[:2000],
        notice='Saved design net assignments only. This is not Gerber/drill copper extraction or fabricated-board electrical evidence.')

    receipt_text = json.dumps(receipt, indent=2) + '\n'
    documents = {destination: exported, receipt_path: receipt_text}
    expected = {path: hashlib.sha256(content.encode('utf-8') if isinstance(content, str) else content).hexdigest()
                for path, content in documents.items()}

    def guard():
        if _cancelled(cancel):
            raise InterruptedError('Reference export cancelled; no output accepted.')
        if hashlib.sha256(board.read_bytes()).hexdigest() != digest:
            raise ValueError('Saved PCB changed during export; regenerate the reference.')
        for path, expected_hash in expected.items():
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise ValueError('Reference output changed during export; choose a new path.')

    publish_documents(documents, sources=[board], source_guard=guard)
    return receipt
