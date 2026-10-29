"""Immutable, project-local full simulation records with explicit source custody."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

MAX_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 64
MAX_RECORDS = 1000
SCHEMA = 'wayricad.project-result/v1'
KEY = 'wayricad_saved_result'
_PLUGINS = {'pi': 'quick-pi', 'quick-pi': 'quick-pi', 'quick_pi_plugin': 'quick-pi',
            'si': 'quick-si', 'quick-si': 'quick-si', 'signal_integrity_advisor_plugin': 'quick-si',
            'therm': 'quick-therm', 'thermal': 'quick-therm', 'quick-therm': 'quick-therm',
            'quick_therm_plugin': 'quick-therm'}
_HASH = re.compile(r'[a-f0-9]{64}')


def _plugin(value):
    if not isinstance(value, str) or value not in _PLUGINS:
        raise ValueError('Choose the quick-pi, quick-si or quick-therm result library.')
    return _PLUGINS[value]


def _validate(value, depth=0, active=None):
    if depth > MAX_DEPTH:
        raise ValueError('Saved result exceeds 64 nesting levels.')
    if value is None or type(value) in (str, int, float, bool):
        if isinstance(value, str) and len(value) > MAX_BYTES:
            raise ValueError('Saved result exceeds 64 MiB.')
        if type(value) is float and not math.isfinite(value):
            raise ValueError('Saved results require finite numbers; unknown samples must remain null.')
        return
    if not isinstance(value, (dict, list, tuple)):
        raise ValueError('Saved results accept JSON records and arrays only.')
    active = set() if active is None else active
    if id(value) in active:
        raise ValueError('Saved result contains circular data.')
    active.add(id(value))
    try:
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError('Saved result object keys must be strings; identities are not coerced.')
            children = value.values()
        else:
            children = value
        for child in children:
            _validate(child, depth + 1, active)
    finally:
        active.remove(id(value))


def _canonical(value):
    _validate(value)
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    result = bytearray()
    try:
        for part in encoder.iterencode(value):
            if len(part) > MAX_BYTES - len(result) - 1:
                raise ValueError('Saved result exceeds 64 MiB including metadata.')
            encoded = part.encode('utf-8')
            if len(encoded) > MAX_BYTES - len(result) - 1:
                raise ValueError('Saved result exceeds 64 MiB including metadata.')
            result.extend(encoded)
    except (TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError('Saved result is not bounded strict JSON.') from error
    result.extend(b'\n')
    return bytes(result)


def _decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Saved result exceeds 64 MiB.')
    def mapping(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Saved result contains duplicate JSON keys.')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Saved result contains a nonfinite JSON constant: ' + value)
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=mapping, parse_constant=reject)
        _validate(result)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('Saved result is not bounded strict UTF-8 JSON.') from error
    if not isinstance(result, dict):
        raise ValueError('Saved simulation payload must be a JSON object.')
    return result


def _linked(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def _root(value):
    path = Path(value).absolute()
    if _linked(path) or not path.is_dir():
        raise ValueError('Choose an existing project directory without a symbolic-link root.')
    return path.resolve()


def _relative(value):
    if (not isinstance(value, str) or not value or len(value) > 4096 or '\\' in value or ':' in value
            or any(ord(c) < 32 for c in value) or value.startswith('/')
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('Saved result paths must remain relative to the project.')
    return PurePosixPath(value)


def _inside(root, relative, *, create=False):
    relative = _relative(relative)
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        if _linked(current):
            raise ValueError('Saved result paths must not traverse symbolic links or directory junctions.')
        if index < len(relative.parts) - 1:
            if create:
                current.mkdir(exist_ok=True)
            if current.exists() and not current.is_dir():
                raise ValueError('Saved result parent is not a directory.')
    if not current.resolve().is_relative_to(root):
        raise ValueError('Saved result path escaped the project.')
    return current


def _hash_file(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def _same_bytes(path, raw):
    try:
        with path.open('rb') as stream:
            return stream.read(len(raw) + 1) == raw
    except OSError:
        return False


def _sources(bundle):
    """Collect declared portable fingerprints, never compute replacement evidence."""
    result = {}
    pending = [bundle]
    while pending:
        record = pending.pop()
        if isinstance(record, (list, tuple)):
            pending.extend(value for value in record if isinstance(value, (dict, list, tuple)))
            continue
        if not isinstance(record, dict):
            continue
        for key, hashes in (('source_path', ('source_sha256',)), ('board_path', ('source_sha256', 'board_sha256')),
                            ('board', ('board_sha256',)), ('study_input_path', ('study_file_sha256',))):
            path = record.get(key)
            digest = next((record.get(name) for name in hashes if record.get(name)), None)
            if path and digest:
                _add_source(result, path, digest)
        fingerprints = record.get('source_fingerprints')
        if fingerprints is not None:
            if not isinstance(fingerprints, dict):
                raise ValueError('Invalid original source fingerprint mapping.')
            for path, digest in fingerprints.items():
                _add_source(result, path, digest)
        pending.extend(value for value in record.values() if isinstance(value, (dict, list, tuple)))
    return [dict(path=path, sha256=result[path]) for path in sorted(result)]


def _add_source(result, path, digest):
    _relative(path)
    if digest is not None and (not isinstance(digest, str) or not _HASH.fullmatch(digest.lower())):
        raise ValueError('Invalid original saved-source SHA-256.')
    digest = digest.lower() if digest is not None else None
    if path in result and result[path] != digest:
        raise ValueError('Original source fingerprints conflict.')
    result[path] = digest
    if len(result) > 1024:
        raise ValueError('Saved result exceeds 1,024 source fingerprints.')


def _source_state(root, metadata):
    if metadata['source_binding'] != 'verified-saved':
        return 'unverified', ['No verified saved-board export evidence was supplied.']
    issues = []
    for source in metadata['sources']:
        name, expected = source['path'], source['sha256']
        try:
            path = _inside(root, name)
            if expected is None:
                if path.exists():issues.append(name + ': previously absent source appeared')
            elif not path.is_file():issues.append(name + ': source is missing')
            elif _hash_file(path) != expected:issues.append(name + ': source bytes changed')
        except (ValueError, OSError):
            issues.append(name + ': source is unavailable or uses a symbolic link')
    return ('stale' if issues else 'current'), issues


def _identity(bundle):
    metadata = dict(bundle[KEY])
    metadata.pop('identity', None)
    value = dict(bundle)
    value[KEY] = metadata
    return hashlib.sha256(_canonical(value)).hexdigest()


def _receipt(root, path, record, raw):
    metadata = record[KEY]
    state, issues = _source_state(root, metadata)
    return dict(path=str(path), relative_path=path.relative_to(root).as_posix(), plugin=metadata['plugin'],
                identity=metadata['identity'], producer_version=metadata['producer_version'],
                bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), source_state=state,
                can_restore=state == 'current', source_path=record.get('source_path') if metadata['source_binding'] == 'verified-saved' else None,
                source_sha256=record.get('source_sha256') if metadata['source_binding'] == 'verified-saved' else None,
                source_issues=issues)


def save_result(project_root, plugin, bundle, *, pocket_kivi=None, version=None):
    """Save immutable full JSON; verified evidence is explicit, never freshly invented."""
    root, plugin = _root(project_root), _plugin(plugin)
    if not isinstance(bundle, dict) or KEY in bundle:
        raise ValueError('Save the complete producer bundle, without library metadata.')
    protected = []
    guard = None
    if pocket_kivi is not None:
        if not isinstance(pocket_kivi, dict):
            raise ValueError('Supply verified portable-export keyword arguments.')
        from .pocket_kivi_export import _prepare, _checked_inputs
        from .pocket_report import _saved, _scopes
        _saved(_scopes(bundle))
        arguments = dict(pocket_kivi, source_root=root)
        board = Path(arguments.get('board_path', '')).resolve()
        if not board.is_relative_to(root):
            raise ValueError('The saved PCB must belong to this project directory.')
        if version is not None and version != arguments.get('version'):
            raise ValueError('Producer version conflicts with verified export evidence.')
        version = arguments.get('version')
        original = dict(bundle)
        previous = original.pop('pocket_kivi_export', None)
        portable, _, protected, source = _prepare(original, **arguments)
        if previous is not None and previous != portable['pocket_kivi_export']:
            raise ValueError('Existing portable metadata conflicts with this export evidence.')
        board, expected, source_root = source
        def guard():
            _checked_inputs(original, board, expected, source_root)
        binding = 'verified-saved'
        sources = _sources(portable)
    else:
        # Relocate only recognized filesystem metadata. This operation is not
        # source verification and must never grant a saved-board certificate.
        from .pocket_kivi_export import _clone, _Paths
        portable = _decode(_canonical(_clone(bundle, _Paths(root))))
        binding, sources = 'unverified', []
    if version is not None and (not isinstance(version, str) or not version.strip() or len(version) > 200
            or any(ord(c) < 32 for c in version)):
        raise ValueError('Supply the actual producer version or leave it unknown.')
    portable[KEY] = dict(schema=SCHEMA, version=1, plugin=plugin, producer_version=version,
                         source_binding=binding, sources=sources)
    identity = _identity(portable)
    portable[KEY]['identity'] = identity
    raw = _canonical(portable)
    relative = '.wayricad/results/' + plugin + '/' + identity + '.json'
    target = _inside(root, relative, create=True)
    for path in protected:
        source = Path(path)
        if source.resolve() == target.resolve() or (target.exists() and source.exists() and os.path.samefile(target, source)):
            raise ValueError('Saved results must not overwrite original sources or settings.')
    if target.exists():
        if not _same_bytes(target, raw):
            raise ValueError('Existing result identity collides with mutated content; it was not overwritten.')
        if guard:guard()
        return dict(_receipt(root, target, portable, raw), created=False)
    descriptor, staging = tempfile.mkstemp(prefix='.result-', suffix='.tmp', dir=target.parent)
    staging = Path(staging)
    created = False
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if guard:guard()
        _inside(root, relative)
        try:
            if os.name == 'nt':
                os.rename(staging, target)  # Windows rename fails if target exists.
            else:
                os.link(staging, target)  # Atomic, exclusive publication on POSIX.
            created = True
        except FileExistsError:
            _inside(root, relative)
            if not _same_bytes(target, raw):
                raise ValueError('Existing result identity collides with mutated content; it was not overwritten.') from None
        if guard:guard()
    except BaseException:
        if created and not _linked(target) and _same_bytes(target, raw):
            target.unlink()
        raise
    finally:
        staging.unlink(missing_ok=True)
    return dict(_receipt(root, target, portable, raw), created=created)


def load_result(project_root, path, *, plugin=None):
    """Inspect verified historical data; stale sources never authorize reattachment."""
    root = _root(project_root)
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            raise ValueError('Choose a saved result inside this project library.') from None
    else:
        relative = candidate.as_posix()
    parsed = _relative(relative)
    if (len(parsed.parts) != 4 or parsed.parts[:2] != ('.wayricad', 'results')
            or parsed.suffix != '.json' or not _HASH.fullmatch(parsed.stem)):
        raise ValueError('Choose a canonical .wayricad/results/<plugin>/<identity>.json record.')
    expected_plugin = _plugin(parsed.parts[2])
    if parsed.parts[2] != expected_plugin or (plugin is not None and _plugin(plugin) != expected_plugin):
        raise ValueError('Saved result belongs to another plugin.')
    target = _inside(root, relative)
    with target.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    record = _decode(raw)
    metadata = record.get(KEY)
    required = {'schema', 'version', 'plugin', 'producer_version', 'source_binding', 'sources', 'identity'}
    if (not isinstance(metadata, dict) or set(metadata) != required or metadata.get('schema') != SCHEMA
            or type(metadata.get('version')) is not int or metadata['version'] != 1
            or metadata.get('plugin') != expected_plugin or metadata.get('identity') != parsed.stem
            or metadata.get('source_binding') not in ('verified-saved', 'unverified')
            or not isinstance(metadata.get('sources'), list) or len(metadata['sources']) > 1024):
        raise ValueError('Saved result metadata is missing, incompatible or belongs to another identity.')
    version = metadata['producer_version']
    if version is not None and (not isinstance(version, str) or not version.strip() or len(version) > 200
            or any(ord(c) < 32 for c in version)):
        raise ValueError('Invalid producer version in saved result metadata.')
    sources = {}
    for source in metadata['sources']:
        if not isinstance(source, dict) or set(source) != {'path', 'sha256'}:
            raise ValueError('Invalid saved-source metadata.')
        _add_source(sources, source['path'], source['sha256'])
    if len(sources) != len(metadata['sources']):
        raise ValueError('Duplicate saved-source metadata.')
    if metadata['source_binding'] == 'verified-saved':
        primary = record.get('source_path')
        if (not isinstance(primary, str) or PurePosixPath(primary).suffix.lower() != '.kicad_pcb'
                or not isinstance(record.get('source_sha256'), str) or not _HASH.fullmatch(record['source_sha256'])
                or sources.get(primary) != record['source_sha256']):
            raise ValueError('Verified saved PCB binding is missing or inconsistent.')
        if _sources(record) != metadata['sources']:
            raise ValueError('Saved source metadata does not match the complete payload fingerprints.')
    elif metadata['sources']:
        raise ValueError('Unverified records cannot claim verified source fingerprints.')
    if _identity(record) != metadata['identity']:
        raise ValueError('Saved result content hash does not match its identity.')
    if _canonical(record) != raw:
        raise ValueError('Saved result bytes are not the canonical immutable record.')
    receipt = _receipt(root, target, record, raw)
    bundle = dict(record)
    bundle.pop(KEY)
    return dict(bundle=bundle, receipt=receipt)


def list_results(project_root, *, plugin=None):
    """List checked records by canonical plugin/identity; never invent dates/order."""
    root = _root(project_root)
    plugins = [_plugin(plugin)] if plugin is not None else sorted(set(_PLUGINS.values()))
    result = []
    for selected in plugins:
        folder = _inside(root, '.wayricad/results/' + selected)
        if not folder.exists():continue
        if not folder.is_dir():raise ValueError('Result library is not a directory.')
        for path in sorted(folder.glob('*.json'), key=lambda value: value.name):
            if len(result) >= MAX_RECORDS:
                raise ValueError('Result library exceeds 1,000 records; select a smaller plugin library.')
            result.append(load_result(root, path, plugin=selected)['receipt'])
    return result
