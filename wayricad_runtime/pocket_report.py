"""Declared saved-source/version evidence for opt-in portable report sidecars."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import re


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200 and not any(ord(c) < 32 for c in value)


def producer_version(module_file=None, package=None, version=None):
    """Use producer metadata, never a hard-coded release or unrelated suite version."""
    if version is not None:
        if not _text(version):
            raise ValueError('Supply the actual producer version.')
        return version
    try:
        module = importlib.import_module(package) if isinstance(package, str) else package
    except ImportError:
        module = None
    if module is not None and _text(getattr(module, '__version__', None)):
        return module.__version__
    location = module_file or getattr(module, '__file__', None)
    if location:
        directory = Path(location).resolve().parent
        # Source metadata is adjacent; PCM metadata is above the plugins folder.
        for path in (directory / 'metadata.json', directory.parent / 'metadata.json'):
            if not path.is_file():
                continue
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('Producer metadata exceeds 1 MiB.')
            try:
                metadata = json.loads(path.read_text(encoding='utf-8-sig'))
                candidate = metadata['versions'][0]['version']
            except (KeyError, IndexError, TypeError, ValueError):
                raise ValueError('Producer metadata does not declare a usable version.') from None
            if _text(candidate):
                return candidate
    return None


def _scopes(bundle):
    if not isinstance(bundle, dict):
        raise ValueError('Portable export requires the complete producer result object.')
    scopes = [bundle]
    for key in ('request', 'geometry', 'report'):
        if isinstance(bundle.get(key), dict):
            scopes.append(bundle[key])
    mesh = bundle.get('mesh')
    if isinstance(mesh, dict) and isinstance(mesh.get('geometry'), dict):
        scopes.append(mesh['geometry'])
    return scopes


def _saved(scopes):
    for scope in scopes:
        for key in ('source_state', 'board_binding', 'geometry_origin', 'source_kind'):
            value = scope.get(key)
            if isinstance(value, str) and re.search(r'(^|[^a-z])(live|unsaved|snapshot|unbound)([^a-z]|$)', value, re.I):
                raise ValueError('Live, unsaved, snapshot or unbound results cannot acquire a saved PCB binding.')
        if any(scope.get(key) is True for key in ('unsaved_changes', 'live_board', 'is_snapshot', 'snapshot')):
            raise ValueError('Live, unsaved or snapshot results cannot acquire a saved PCB binding.')


def evidence_context(bundle, *, tool, module_file=None, package=None, board_path=None,
                     version=None, units=None, coordinate_frame=None, z_basis=None):
    """Build portable-json kwargs from original declared solve-time evidence.

    A caller path hint may recover a known saved path, but no digest is ever
    computed here. The portable serializer subsequently checks current bytes.
    """
    scopes = _scopes(bundle)
    _saved(scopes)
    if bundle.get('evidence_reference') is not None or bundle.get('schema') == 'wayricad.pi-report-reference/v1':
        raise ValueError('A linked child descriptor is not complete standalone numerical evidence.')
    paths = []
    if board_path is not None:
        paths.append(Path(board_path).resolve())
    for scope in scopes:
        for key in ('board_path', 'source_path', 'board'):
            value = scope.get(key)
            if isinstance(value, (str, Path)) and value and Path(value).suffix.lower() == '.kicad_pcb':
                paths.append(Path(value).resolve())
    if not paths or any(path.suffix.lower() != '.kicad_pcb' for path in paths):
        raise ValueError('This result has no declared saved PCB path; keep its original report export.')
    board = paths[0]
    if any(path != board for path in paths):
        raise ValueError('Result source paths conflict; do not rebind an existing analysis.')
    digests = []
    for scope in scopes:
        for key in ('source_sha256', 'board_sha256'):
            value = scope.get(key)
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value):
                    raise ValueError('Original saved PCB fingerprint is invalid.')
                digests.append(value.lower())
        fingerprints = scope.get('source_fingerprints')
        if fingerprints is not None:
            if not isinstance(fingerprints, dict):
                raise ValueError('Original source fingerprints are invalid.')
            for name, digest in fingerprints.items():
                if not isinstance(name, str):
                    raise ValueError('Original source fingerprint paths must be strings.')
                if Path(name).resolve() == board:
                    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
                        raise ValueError('Original saved PCB fingerprint is missing or invalid.')
                    digests.append(digest.lower())
    if not digests:
        raise ValueError('Original solve-time PCB fingerprint is unavailable; rerun from the saved board.')
    if any(digest != digests[0] for digest in digests):
        raise ValueError('Original saved PCB fingerprints conflict; rerun the analysis.')
    actual_version=producer_version(package=package, module_file=module_file, version=version)
    if actual_version is None:
        raise ValueError('Actual producer version is unavailable; portable export cannot label this result.')
    return dict(board_path=board, source_sha256=digests[0], source_state='saved', tool=tool,
                version=actual_version,
                units=units, coordinate_frame=coordinate_frame, z_basis=z_basis)


def prepare_report(bundle, evidence):
    """Prepare one portable payload and reusable custody guard without re-encoding."""
    if not isinstance(evidence, dict):
        raise ValueError('Portable report evidence must be a keyword-argument object.')
    _saved(_scopes(bundle))
    if bundle.get('evidence_reference') is not None or bundle.get('schema') == 'wayricad.pi-report-reference/v1':
        raise ValueError('A linked child descriptor is not complete standalone numerical evidence.')
    from .pocket_kivi_export import _prepare, _checked_inputs
    _, payload, protected, source = _prepare(bundle, **evidence)
    board, expected, root = source

    def guard():
        _checked_inputs(bundle, board, expected, root)

    return payload, protected, guard
