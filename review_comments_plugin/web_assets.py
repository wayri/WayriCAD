"""Bounded, read-only audit of the pinned full ESM or legacy viewer closure.

The bundled 0.6.0 MPL-2.0 distribution is unmodified. Optional external roots
are snapshotted, never fetched or imported from another plugin installation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import posixpath
import re
import stat
from typing import Mapping


VIEWER_2D = (
    'web-library/kicad-viewer.mjs',
    'web-library/viewer-host.mjs',
    'web-library/source-loader.mjs',
    'web-library/three-runtime.mjs',
    'extension/design-diff.js',
    'extension/file-compatibility.js',
    'extension/worksheet.js',
    'extension/layer-colors.js',
    'extension/schematic-renderer.js',
    'extension/pcb-renderer.js',
    'extension/owned-canvas.js',
    'extension/touch-canvas.js',
)
VIEWER_3D = ('extension/vendor/spike-board3d.bundle.js',)
LINKED_MODELS = ('extension/repo-models.js', 'extension/embedded-models.js')
CORE_NOTICES = ('LICENSE', 'LICENSING.md', 'THIRD-PARTY-NOTICES.md')
THREE_D_NOTICES = (
    'extension/vendor/SPIKE-ENGINE-NOTICE.md',
    'extension/vendor/THREE-LICENSE',
    'extension/vendor/fzstd/LICENSE',
    'extension/vendor/fzstd/README.md',
)
MODERN_2D = (*tuple(name.replace('extension/', 'engine/', 1) if name.startswith('extension/')
                  else name for name in VIEWER_2D),
             'web-library/viewer-chrome.mjs',
             'web-library/archive/zip.mjs',
             'web-library/manufacturing-input.mjs',
             'web-library/manufacturing-canvas.mjs',
             'web-library/source-types.mjs',
             'web-library/manufacturing/index.mjs',
             'web-library/manufacturing/gerber.mjs',
             'web-library/manufacturing/excellon.mjs',
             'web-library/manufacturing/geometry.mjs',
             'web-library/manufacturing/apertures.mjs',
             'web-library/inspector.mjs')
MODERN_3D = tuple(name.replace('extension/', 'engine/', 1) for name in VIEWER_3D)
MODERN_NOTICES = tuple(name.replace('extension/', 'engine/', 1) for name in THREE_D_NOTICES)
MODERN_LICENSE = ('licenses/Pocket-KiView-Source-Available-1.0.txt',)
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024
PIN_PATH = Path(__file__).parent / 'vendor/kicad-webview/REVIEW-PIN.json'
DIST_ENTRY = 'web-library/kicad-viewer.mjs'


def release_pin() -> dict:
    """Integration-owned expected hashes, not a purported upstream manifest."""
    return json.loads(PIN_PATH.read_text(encoding='utf-8'))


def _distribution_sources() -> dict[str, str]:
    return {DIST_ENTRY if name == 'kivi-viewer.js' else name: name
            for name in release_pin()['files']}

# KiView's ESM imports and import.meta URL references must resolve within the
# exact subset served by Review.  This is checked again on the host's captured
# bytes, since the external source tree can change between reads.
_MODULE_REFERENCE = re.compile(
    r'''\b(?:(?:import|export)\s*(?:\(\s*|(?:[^;]*?\s+from\s*)?)|'''
    r'''new\s+URL\s*\(\s*)['"](?P<path>\.{1,2}/[^'"\s]+)['"]''',
    re.MULTILINE,
)


@dataclass(frozen=True, order=True)
class WebAsset:
    path: str
    bytes: int
    sha256: str


def _checked_root(root: str | Path) -> Path:
    given = Path(root).expanduser()
    if not given.is_dir() or _is_link(given):
        raise ValueError('Choose a real KiView source directory, not a link.')
    return given.resolve()


def _is_link(path: Path) -> bool:
    """Reject Windows junction/reparse assets as well as symbolic links."""
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _checked_file(base: Path, name: str) -> Path:
    path = base
    for part in Path(name).parts:
        if part in ('', '.', '..'):
            raise ValueError('Invalid KiView asset path: ' + name)
        path = path / part
        if _is_link(path):
            raise ValueError('KiView asset path contains a link: ' + name)
    if not path.is_file():
        raise ValueError('Required KiView asset is missing: ' + name)
    return path


def required_paths(*, include_3d: bool = True, linked_models: bool = False,
                   layout: str = 'legacy') -> tuple[str, ...]:
    """The reviewed source closure; STEP needs a separate release gate."""
    if linked_models and not include_3d:
        raise ValueError('Linked models require the 3D viewer.')
    if layout in ('distribution', 'distribution-package'):
        return tuple(sorted(_distribution_sources()))
    if layout not in ('legacy', 'modern'):
        raise ValueError('Unknown KiView source layout.')
    source, models, notices = ((VIEWER_2D, VIEWER_3D, THREE_D_NOTICES) if layout == 'legacy'
                               else (MODERN_2D, MODERN_3D, MODERN_NOTICES))
    return tuple(sorted((*source, *CORE_NOTICES, *(MODERN_LICENSE if layout == 'modern' else ()),
                         *(models + notices if include_3d else ()),
                         *(LINKED_MODELS if linked_models else ()))))


def _layout(base: Path) -> str:
    if (base / 'kivi-viewer.js').is_file():
        return 'distribution'
    if (base / 'dist/kivi-viewer.js').is_file():
        return 'distribution-package'
    if (base / 'web-library/kicad-viewer.mjs').is_file():
        return 'legacy'
    if (base / 'src/kicad-viewer.mjs').is_file():
        return 'modern'
    raise ValueError('Required KiView asset is missing: web-library or src/kicad-viewer.mjs')


def _source_path(name: str, layout: str) -> str:
    if layout in ('distribution', 'distribution-package'):
        return ('dist/' if layout == 'distribution-package' else '') + _distribution_sources().get(name, name)
    if layout == 'modern':
        if name.startswith('web-library/'):
            return 'src/' + name.removeprefix('web-library/')
        if name in LINKED_MODELS:
            return 'engine/' + name.removeprefix('extension/')
    return name


def verify_module_closure(files: Mapping[str, bytes]) -> None:
    """Reject relative ESM and import.meta asset URLs outside captured files."""
    names = set(files)
    for name, data in files.items():
        if not name.endswith(('.mjs', '.js')):
            continue
        try:
            source = data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('KiView module is not UTF-8: ' + name) from exc
        for match in _MODULE_REFERENCE.finditer(source):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), match['path']))
            if target.startswith('../') or target not in names:
                raise ValueError(f'KiView module reference is outside the served subset: {name} -> {target}')


def asset_manifest(root: str | Path, *, include_3d: bool = True,
                   linked_models: bool = False) -> tuple[WebAsset, ...]:
    """Hash exact files without following symlinks or traversing other assets."""
    base = _checked_root(root)
    layout = _layout(base)
    records = []
    captured = {}
    total = 0
    for name in required_paths(include_3d=include_3d, linked_models=linked_models,
                               layout=layout):
        path = _checked_file(base, _source_path(name, layout))
        size = path.stat().st_size
        total += size
        if size > MAX_ASSET_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('KiView asset subset exceeds its reviewed size bound.')
        with path.open('rb') as stream:
            data = stream.read(MAX_ASSET_BYTES + 1)
        if len(data) != size:
            raise ValueError('KiView asset changed while being read: ' + name)
        digest = hashlib.sha256(data).hexdigest()
        if layout in ('distribution', 'distribution-package'):
            expected = release_pin()['files'][_distribution_sources()[name]]
            if size != expected['bytes'] or digest != expected['sha256']:
                raise ValueError('KiCad WebView distribution differs from the pinned 0.6.0 release: ' + name)
        captured[name] = data
        records.append(WebAsset(name, size, digest))
    verify_module_closure(captured)
    return tuple(records)


def discover_assets(root: str | Path, *, include_3d: bool = True,
                    linked_models: bool = True) -> dict[str, Path]:
    """Map only audited relative URLs to immutable on-disk source files.

    The returned paths are for a local read-only host. Recompute the manifest
    before serving a changed source tree; do not treat this as public bundling.
    """
    manifest = asset_manifest(root, include_3d=include_3d, linked_models=linked_models)
    base = _checked_root(root)
    layout = _layout(base)
    return {record.path: _checked_file(base, _source_path(record.path, layout)) for record in manifest}


def verify_assets(root: str | Path, manifest: tuple[WebAsset, ...]) -> None:
    """Check an installed copy against the source audit before loading it."""
    base = _checked_root(root)
    layout = _layout(base)
    if not manifest or tuple(record.path for record in manifest) != tuple(sorted(set(
            record.path for record in manifest))):
        raise ValueError('KiView asset manifest is missing, duplicate or unsorted.')
    for record in manifest:
        if Path(record.path).is_absolute() or '..' in Path(record.path).parts:
            raise ValueError('Invalid KiView asset path: ' + record.path)
        path = _checked_file(base, _source_path(record.path, layout))
        with path.open('rb') as stream:
            data = stream.read(MAX_ASSET_BYTES + 1)
        if (len(data) != record.bytes or len(data) > MAX_ASSET_BYTES or
                hashlib.sha256(data).hexdigest() != record.sha256):
            raise ValueError('KiView asset does not match the approved manifest: ' + record.path)
