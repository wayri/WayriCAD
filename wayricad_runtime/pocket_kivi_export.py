"""Portable saved-result evidence for Pocket KiView; no solving or geometry edits.

Keep producer payload shapes intact. Only recognized filesystem metadata is
relocated, and a board binding always requires the producer's solve-time hash.
"""
from __future__ import annotations

import hashlib
import json
import math
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import posixpath
import re
from urllib.parse import unquote, urlsplit

from .report_ui import checked_sources, publish_documents

SCHEMA = 'wayricad.pocket-kivi-export/v1'
MAX_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 64
_PATH_FIELDS = {'path', 'paths', 'file', 'files', 'filename', 'directory', 'directories',
                'root', 'cwd', 'board'}
_INPUT_FIELDS = {'board', 'board_path', 'pcb_path', 'source_path', 'source_file',
                 'input_path', 'input_file', 'study_input_path', 'settings_path',
                 'project_path', 'rules_path', 'model_path'}


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', value):
        raise ValueError('Supply the original solve-time saved PCB SHA-256, not a study or model hash.')
    return value.lower()


def _strict_json(value):
    """Bound encoded UTF-8 incrementally, including the final newline."""
    output = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    try:
        for chunk in encoder.iterencode(value):
            if len(chunk) > MAX_BYTES - len(output) - 1:
                raise ValueError('Pocket KiView export exceeds 64 MiB; split the saved result.')
            encoded = chunk.encode('utf-8')
            if len(encoded) > MAX_BYTES - len(output) - 1:
                raise ValueError('Pocket KiView export exceeds 64 MiB; split the saved result.')
            output.extend(encoded)
    except (TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError('Pocket KiView export requires finite, bounded JSON data.') from exc
    output.extend(b'\n')
    return bytes(output)


def _path_field(key):
    return key in _PATH_FIELDS or key.endswith(('_path', '_paths', '_file', '_files', '_filename', '_directory', '_dir'))


def _local_path(value):
    """Normalize local metadata lexically; never follow a UNC share to scrub it."""
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError('Filesystem metadata must contain path strings.')
    value = os.fspath(value)
    if not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('Filesystem metadata contains an invalid path.')
    if value.lower().startswith('file:'):
        parsed = urlsplit(value)
        value = unquote(parsed.path)
        if parsed.netloc:
            value = '//' + parsed.netloc + value
        elif re.match(r'^/[A-Za-z]:/', value):
            value = value[1:]
    return value


class _Paths:
    def __init__(self, source_root):
        self.root = str(source_root)
        self.names = {}

    def portable(self, value):
        value = _local_path(value)
        # Public provenance URLs are not local paths. file: URLs were decoded.
        if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', value):
            return value
        windows = bool(PureWindowsPath(value).drive or '\\' in value or
                       (not value.startswith('/') and PureWindowsPath(self.root).drive))
        pure = PureWindowsPath if windows else PurePosixPath
        normalized = ntpath.normpath(value) if windows else posixpath.normpath(value)
        path = pure(normalized)
        if not path.is_absolute() and not path.drive and not path.root:
            if all(part not in ('.', '..') for part in path.parts) and ':' not in normalized:
                return path.as_posix()
            normalized = (ntpath.normpath(ntpath.join(self.root, normalized)) if windows
                          else posixpath.normpath(posixpath.join(self.root, normalized)))
            path = pure(normalized)
        root = pure(self.root)
        try:
            relative = path.relative_to(root)
            if all(part not in ('.', '..') for part in relative.parts):
                return relative.as_posix()
        except ValueError:
            pass
        canonical = normalized.casefold() if windows else normalized
        # External files retain only their filename and a stable collision-safe alias.
        name = path.name
        if not name or name in ('.', '..') or ':' in name:
            name = 'source'
        alias = '_external/' + hashlib.sha256(canonical.encode()).hexdigest()[:16] + '/' + name
        previous = self.names.setdefault(alias, canonical)
        if previous != canonical:
            raise ValueError('Portable source paths collide; choose a different source root.')
        return alias


def _clone(value, paths, *, field='', depth=0, active=None, budget=None):
    """Copy only JSON data, preserving arrays, null gaps, names and identities."""
    if depth > MAX_DEPTH:
        raise ValueError('Pocket KiView export exceeds 64 nesting levels.')
    active = set() if active is None else active
    budget = [0] if budget is None else budget
    if isinstance(value, os.PathLike):
        if not _path_field(field):
            raise ValueError('Path objects are only supported in filesystem metadata fields.')
        value = os.fspath(value)
    if value is None or type(value) in (bool, int, float, str):
        if type(value) is float and not math.isfinite(value):
            raise ValueError('Pocket KiView export rejects NaN and infinity; retain unknown samples as null.')
        if isinstance(value, str):
            if len(value) > MAX_BYTES:
                raise ValueError('Pocket KiView export exceeds 64 MiB.')
            if _path_field(field) and value:
                value = paths.portable(value)
            budget[0] += len(value) + 2
        else:
            budget[0] += len(str(value)) + 1
        if budget[0] > MAX_BYTES:
            raise ValueError('Pocket KiView export exceeds 64 MiB.')
        return value
    if not isinstance(value, (dict, list, tuple)):
        raise ValueError('Pocket KiView export accepts JSON records and arrays only.')
    if id(value) in active:
        raise ValueError('Pocket KiView export cannot contain circular data.')
    active.add(id(value))
    budget[0] += 2
    try:
        if isinstance(value, dict):
            result = {}
            fingerprints = field == 'source_fingerprints'
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError('Pocket KiView JSON object keys must be strings; IDs are never coerced.')
                portable_key = paths.portable(key) if fingerprints else key
                if portable_key in result:
                    raise ValueError('Portable source paths collide.')
                budget[0] += len(portable_key) + 3
                result[portable_key] = _clone(item, paths, field='' if fingerprints else key,
                    depth=depth + 1, active=active, budget=budget)
            return result
        return [_clone(item, paths, field=field, depth=depth + 1, active=active, budget=budget) for item in value]
    finally:
        active.remove(id(value))


def _input_path(value, root):
    path = Path(_local_path(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _checked_inputs(bundle, board, expected, source_root):
    """Reuse report source checks before relocation, including nested SI custody."""
    if _digest(board) != expected:
        raise ValueError('Saved PCB changed; rerun the analysis before exporting.')
    protected = [board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru'),
                 board.with_suffix('.kicad_sch'), board.with_suffix('.kicad_prl')]
    pending, seen = [(bundle, 0)], set()
    while pending:
        record, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise ValueError('Pocket KiView export exceeds 64 nesting levels.')
        if not isinstance(record, (dict, list, tuple)) or id(record) in seen:
            continue
        seen.add(id(record))
        if isinstance(record, (list, tuple)):
            pending.extend((item, depth + 1) for item in record if isinstance(item, (dict, list, tuple)))
            continue
        if record.get('source_state') in ('live', 'unsaved', 'live-unsaved') or record.get('unsaved_changes') is True:
            raise ValueError('Live or unsaved analysis cannot be bound to a saved PCB export.')
        scope = dict(record)
        scope.pop('request', None)  # Each nested request is checked with its own source context.
        for key in _INPUT_FIELDS:
            value = record.get(key)
            if isinstance(value, (str, os.PathLike)) and value:
                path = _input_path(value, source_root)
                scope[key] = str(path)
                protected.append(path)
                if key in ('board', 'board_path', 'pcb_path', 'source_path') and path.suffix.lower() == '.kicad_pcb':
                    if path != board:
                        raise ValueError('Saved result declares a different PCB; do not rebind an existing analysis.')
                    for digest in ('source_sha256', 'board_sha256'):
                        if record.get(digest) is not None and _sha256(record[digest]) != expected:
                            raise ValueError('Saved result PCB fingerprint conflicts with the original solve-time fingerprint.')
        for digest in ('source_sha256', 'board_sha256', 'study_file_sha256'):
            if isinstance(scope.get(digest), str) and re.fullmatch(r'[a-fA-F0-9]{64}', scope[digest]):
                scope[digest] = scope[digest].lower()
        protected.extend(checked_sources(scope))
        fingerprints = record.get('source_fingerprints')
        if fingerprints is not None:
            if not isinstance(fingerprints, dict):
                raise ValueError('Invalid saved-source fingerprint mapping.')
            for value, digest in fingerprints.items():
                path = _input_path(value, source_root)
                protected.append(path)
                if digest is None:
                    if path.exists():
                        raise ValueError('Previously absent source file appeared; rerun before exporting.')
                elif _digest(path) != _sha256(digest):
                    raise ValueError('Saved source or project settings changed; rerun before exporting.')
                if path.suffix.lower() == '.kicad_pcb' and (path != board or digest is None or _sha256(digest) != expected):
                    raise ValueError('Saved PCB fingerprint mapping conflicts with the selected source.')
        pending.extend((item, depth + 1) for item in record.values() if isinstance(item, (dict, list, tuple)))
    return protected


def _prepare(bundle, *, board_path, source_sha256, tool, version, source_state,
             source_root=None, units=None, coordinate_frame=None, z_basis=None):
    if not isinstance(bundle, dict):
        raise ValueError('Export an existing JSON result object without wrapping its payload.')
    if source_state != 'saved':
        raise ValueError('Only results from an explicitly verified saved PCB can be exported with a source binding.')
    board = Path(board_path).resolve()
    if board.suffix.lower() != '.kicad_pcb' or not board.is_file():
        raise ValueError('Choose the saved .kicad_pcb used by the completed analysis.')
    expected = _sha256(source_sha256)
    if bundle.get('source_sha256') is not None and _sha256(bundle['source_sha256']) != expected:
        raise ValueError('Saved result source_sha256 conflicts with the original solve-time PCB fingerprint.')
    if bundle.get('board_sha256') is not None and _sha256(bundle['board_sha256']) != expected:
        raise ValueError('Saved result board_sha256 conflicts with the original solve-time PCB fingerprint.')
    for label, value in (('tool', tool), ('version', version)):
        if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
            raise ValueError('Supply the actual producer ' + label + '.')
    if units is not None and (not isinstance(units, dict) or any(not isinstance(k, str) or
            not isinstance(v, str) or not v.strip() for k, v in units.items())):
        raise ValueError('Declare only evidenced field-to-unit strings, or leave units unknown.')
    for label, value in (('coordinate_frame', coordinate_frame), ('z_basis', z_basis)):
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 1000):
            raise ValueError('Supply an evidenced ' + label + ' string, or leave it unknown.')
    root = Path(source_root).resolve() if source_root is not None else board.parent
    protected = _checked_inputs(bundle, board, expected, root)
    paths = _Paths(root)
    portable = _clone(bundle, paths)
    if 'pocket_kivi_export' in portable:
        raise ValueError('Result already carries portable export metadata; export the original producer bundle.')
    portable['source_path'] = paths.portable(str(board))
    portable['source_sha256'] = expected
    portable['pocket_kivi_export'] = {
        'schema': SCHEMA, 'tool': tool, 'version': version, 'source_state': 'saved',
        'units': _clone(units, paths), 'coordinate_frame': coordinate_frame, 'zBasis': z_basis,
    }
    payload = _strict_json(portable)
    _checked_inputs(bundle, board, expected, root)
    return portable, payload, protected, (board, expected, root)


def portable_bundle(bundle, *, board_path, source_sha256, tool, version, source_state,
                    source_root=None, units=None, coordinate_frame=None, z_basis=None):
    """Return an independent portable copy after verifying saved-source custody.

    ``source_sha256`` must be captured by the analysis at solve time. Supplying a
    fresh disk hash for an old or live result does not satisfy this contract.
    Unknown units/frame/elevation convention remain explicit null metadata.
    """
    return _prepare(bundle, board_path=board_path, source_sha256=source_sha256,
        tool=tool, version=version, source_state=source_state, source_root=source_root,
        units=units, coordinate_frame=coordinate_frame, z_basis=z_basis)[0]


def portable_json(bundle, **evidence):
    """Return strict UTF-8 JSON bytes, at most 64 MiB including its newline."""
    return _prepare(bundle, **evidence)[1]


def export_bundle(bundle, destination, **evidence):
    """Publish a new JSON export using shared source protection and staging.

    Existing files are never replaced, including settings and old exports.
    """
    target = Path(destination)
    if target.suffix.lower() != '.json' or target.exists() or target.is_symlink():
        raise ValueError('Choose a new .json export file; existing source/settings files are protected.')
    _, payload, protected, source = _prepare(bundle, **evidence)
    board, expected, root = source
    # Recheck immediately before and after publication, preserving the source guard.
    protected.extend(_checked_inputs(bundle, board, expected, root))
    if target.exists() or target.is_symlink():
        raise ValueError('Export destination appeared during preparation; choose a new .json file.')
    publish_documents({target: payload}, sources=protected)
    try:
        _checked_inputs(bundle, board, expected, root)
    except BaseException:
        target.unlink(missing_ok=True)  # Only this call's newly created output.
        raise
    return {'json': str(target), 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
            'source_sha256': expected, 'schema': SCHEMA}
