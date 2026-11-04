"""Read-only, saved-revision SVG snapshots for the review canvas.

This is a plot of files on disk, not a capture of unsaved editor state or its
viewport.  The caller must label it accordingly and keep review annotations
separate from the KiCad document.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from wayricad_runtime.schematic_sexpr import parse, properties

_SVG = '{http://www.w3.org/2000/svg}svg'
_MAX_SVG_BYTES = 16 * 1024 * 1024
_MAX_SHEETS = 64


@dataclass(frozen=True)
class CanvasSnapshot:
    svg: bytes
    view_box: tuple[float, float, float, float]
    source_path: str
    source_sha256: str
    kind: str
    sheet: str | None
    layers: tuple[str, ...]
    cli_path: str
    root_path: str = ''
    # With the fixed full-page, unscaled CLI flags below, plot positions are
    # KiCad document millimetres. Native KiCad 10/11 fixtures check this mapping.
    coordinate_system: str = 'kicad-document-mm'


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sources(path: Path, kind: str) -> dict[Path, str | None]:
    """Fingerprint the saved input and its project/schematic dependencies."""
    paths = {path}
    project = path.with_suffix('.kicad_pro')
    paths.add(project)
    if kind == 'pcb':
        paths.add(path.with_suffix('.kicad_dru'))
    if kind == 'schematic':
        pending = [path]
        while pending:
            current = pending.pop()
            tree = parse(current.read_text(encoding='utf-8-sig'))
            for sheet in tree.nodes('sheet'):
                props = properties(sheet)
                filename = props.get('Sheetfile', props.get('Sheet file', ('',)))[0]
                if not filename or '${' in filename or filename.startswith('kicad-embed:'):
                    raise ValueError('Resolve embedded or variable child sheet paths in KiCad before rendering.')
                child = (current.parent / filename).resolve()
                if not child.is_relative_to(path.parent):
                    raise ValueError('Child sheets outside the saved project directory cannot be safely rendered.')
                if child.suffix.lower() != '.kicad_sch' or not child.is_file():
                    raise ValueError('A child schematic sheet is missing or unsupported: ' + filename)
                if child not in paths:
                    paths.add(child)
                    pending.append(child)
                if len(paths) > _MAX_SHEETS + 1:
                    raise ValueError('The schematic exceeds the bounded review snapshot.')
    return {item: _sha(item) if item.is_file() else None for item in sorted(paths)}


def _copy_inputs(root: Path, source: Path, fingerprints: dict[Path, str | None]) -> Path:
    """Create the exact known CLI input set inside scratch, never beside source."""
    input_root = root / 'input'
    input_root.mkdir()
    for original, digest in fingerprints.items():
        if digest is None:
            continue
        try:
            relative = original.relative_to(source.parent)
        except ValueError as exc:
            raise ValueError('An input outside the saved project directory cannot be safely rendered.') from exc
        target = input_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        if _sha(target) != digest:
            raise ValueError('Saved design changed while making its private rendering copy.')
    return input_root / source.name


def _sheet_file_for_page(root: Path, sources: dict[Path, str | None], page: str) -> tuple[Path, str]:
    if page == '1':
        return root, root.stem
    matches = set()
    for document in sources:
        if document.suffix.lower() != '.kicad_sch':
            continue
        tree = parse(document.read_text(encoding='utf-8-sig'))
        for item in tree.nodes('sheet'):
            props = properties(item)
            filename = props.get('Sheetfile', props.get('Sheet file', ('',)))[0]
            sheet_name = props.get('Sheetname', props.get('Sheet name', ('',)))[0]
            child = (document.parent / filename).resolve()
            for instance in item.nodes('instances'):
                for project in instance.nodes('project'):
                    if project.val() != root.stem:
                        continue
                    for path in project.nodes('path'):
                        if path.get('page') == page:
                            matches.add((child, root.stem + '-' + sheet_name))
    if len(matches) != 1:
        raise ValueError('Requested page has no unique saved schematic file identity.')
    return matches.pop()


def _resolve_cli(cli: str | os.PathLike[str] | None) -> Path:
    selected = str(cli) if cli is not None else None
    if selected is None and (os.environ.get('KICAD_API_SOCKET') or os.environ.get('KICAD_API_TOKEN')):
        # An editor launch has a stronger identity than inherited PATH/CLI
        # overrides. Do not silently render a newer board with another host.
        from wayricad_runtime.context import connect
        client = connect()
        try:
            selected = client.get_kicad_binary_path('kicad-cli')
        finally:
            client.close()
        if not selected:
            raise ValueError('The originating KiCad editor did not supply its SVG export CLI.')
    if selected is None:
        selected = os.environ.get('WAYRICAD_ANALYSIS_CLI') or os.environ.get('KICAD_CLI')
    if selected:
        candidate = shutil.which(selected) or selected
        path = Path(candidate).expanduser().resolve()
        if not path.is_file():
            raise ValueError('The selected KiCad CLI does not exist: ' + selected)
        return path
    candidates = [Path(shutil.which('kicad-cli') or '')]
    if os.name == 'nt':
        base = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'KiCad'
        candidates.extend(base / version / 'bin' / 'kicad-cli.exe' for version in ('11.0', '10.0'))
    elif os.sys.platform == 'darwin':
        candidates.append(Path('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError('Install KiCad CLI or pass the originating editor\'s kicad-cli path.')


def _read_svg(path: Path) -> tuple[bytes, tuple[float, float, float, float]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_SVG_BYTES:
        raise ValueError('KiCad did not produce a bounded regular SVG file.')
    data = path.read_bytes()
    if b'<!ENTITY' in data.upper():
        raise ValueError('KiCad SVG contains an unsupported XML entity.')
    # KiCad emits a public SVG 1.1 DTD URL. It is unnecessary for rendering a
    # review preview, and must not cause a web view to fetch external content.
    data = re.sub(rb'<!DOCTYPE\s+svg\s+PUBLIC\s+"[^"]+"\s+"[^"]+"\s*>', b'', data,
                  count=1, flags=re.IGNORECASE)
    if b'<!DOCTYPE' in data.upper():
        raise ValueError('KiCad SVG contains an unsupported document type.')
    root = ET.fromstring(data)
    if root.tag != _SVG:
        raise ValueError('KiCad export is not SVG.')
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1].lower() in ('script', 'foreignobject'):
            raise ValueError('KiCad SVG contains unsupported active content.')
        for key, value in element.attrib.items():
            name = key.rsplit('}', 1)[-1].lower()
            if name.startswith('on') or name == 'base':
                raise ValueError('KiCad SVG contains unsupported active content.')
            if name == 'href' and not value.startswith(('#', 'data:')):
                raise ValueError('KiCad SVG contains an external resource reference.')
    raw = root.attrib.get('viewBox', '')
    values = [float(value) for value in re.split(r'[\s,]+', raw.strip()) if value]
    if len(values) != 4 or not all(math.isfinite(v) for v in values) or values[2] <= 0 or values[3] <= 0:
        raise ValueError('KiCad SVG has no finite positive viewBox.')
    return data, tuple(values)


def _run(command: list[str], timeout: float, cancelled) -> None:
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancelled is not None and cancelled():
                raise InterruptedError('Review canvas rendering cancelled.')
            if time.monotonic() >= deadline:
                raise TimeoutError('KiCad SVG rendering exceeded its time limit.')
            try:
                stdout, stderr = process.communicate(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            detail = (stderr or stdout).decode('utf-8', errors='replace')[-1500:]
            raise ValueError('KiCad could not render this saved document. ' + detail)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            process.communicate()


def render_saved_canvas(path: str | os.PathLike[str], *, cli: str | os.PathLike[str] | None = None,
                        sheet: str | None = None, layers: tuple[str, ...] | list[str] | None = None,
                        expected_sha256: str | None = None, timeout: float = 30,
                        cancelled=None) -> CanvasSnapshot:
    """Plot a saved PCB or schematic into private scratch, then return its SVG bytes.

    ``sheet`` is a schematic *page number* as accepted by ``kicad-cli --pages``.
    If omitted, an exact SVG filename match selects the chosen saved source
    file from a multi-page export. ``layers`` names PCB plot layers; they are
    not inferred from editor state. Neither this function nor its result
    changes a KiCad source document.
    """
    source = Path(path).expanduser().resolve()
    kind = {'.kicad_pcb': 'pcb', '.kicad_sch': 'schematic'}.get(source.suffix.lower())
    if kind is None or not source.is_file():
        raise ValueError('Choose a saved .kicad_pcb or .kicad_sch document.')
    if timeout <= 0:
        raise ValueError('Rendering timeout must be positive.')
    if cancelled is not None and cancelled():
        raise InterruptedError('Review canvas rendering cancelled.')
    if kind == 'pcb' and sheet is not None:
        raise ValueError('A PCB canvas has no schematic page number.')
    if kind == 'schematic' and layers is not None:
        raise ValueError('Schematic pages do not accept PCB layer names.')
    if sheet is not None and (not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', sheet) or sheet in ('.', '..')):
        raise ValueError('Choose one explicit schematic page number.')
    layer_names = tuple(layers) if layers is not None else ('F.Cu',)
    if kind == 'pcb' and (not layer_names or len(layer_names) > 64 or any(
            not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,31}', name)
            for name in layer_names)):
        raise ValueError('Choose valid PCB plot layer names.')
    before = _sources(source, kind)
    primary_sha = before[source]
    if expected_sha256 is not None and expected_sha256 != primary_sha:
        raise ValueError('Saved document changed. Reload review comments before rendering.')
    converter = _resolve_cli(cli)
    actual_source, expected_stem = (_sheet_file_for_page(source, before, sheet)
                                    if kind == 'schematic' and sheet is not None
                                    else (source, source.stem))
    with tempfile.TemporaryDirectory(prefix='wayricad-review-canvas-') as directory:
        scratch = Path(directory)
        private_source = _copy_inputs(scratch, source, before)
        output = scratch / 'output'
        output.mkdir()
        if kind == 'pcb':
            target = output / 'board.svg'
            command = [str(converter), 'pcb', 'export', 'svg', '--mode-single',
                       '--output', str(target), '--layers', ','.join(layer_names),
                       '--page-size-mode', '1', '--exclude-drawing-sheet', str(private_source)]
        else:
            command = [str(converter), 'sch', 'export', 'svg', '--output', str(output),
                       '--exclude-drawing-sheet']
            if sheet is not None:
                command.extend(['--pages', sheet])
            command.append(str(private_source))
        _run(command, timeout, cancelled)
        if _sources(source, kind) != before:
            raise ValueError('Saved document or project changed during rendering. Reload and retry.')
        if kind == 'schematic':
            candidates = sorted(output.glob('*.svg'))
            matches = [candidate for candidate in candidates if candidate.stem == expected_stem]
            if len(matches) != 1:
                raise ValueError('KiCad did not identify the requested saved schematic page uniquely. '
                                 'Choose its saved sheet file directly.')
            if sheet is not None and len(candidates) != 1:
                raise ValueError('KiCad exported more than the requested schematic page.')
            target = matches[0]
        svg, view_box = _read_svg(target)
        if _sources(source, kind) != before:
            raise ValueError('Saved document or project changed during rendering. Reload and retry.')
    return CanvasSnapshot(svg=svg, view_box=view_box, source_path=str(actual_source),
                          source_sha256=before[actual_source], kind=kind, sheet=sheet,
                          layers=layer_names if kind == 'pcb' else (), cli_path=str(converter),
                          root_path=str(source))
