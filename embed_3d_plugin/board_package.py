"""Native-format PCB footprint archives and reconstructible local libraries.

This module does NOT pretend that a kicad-embed URI is a library directory.
It makes a NEW PCB package; it never swaps the active BOARD object. Footprint
geometry must be normalized by KiCad's native FootprintSave before composition.
All board edits are span-limited to footprint IDs, model links and payloads.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable
from .codec import Codec, MAX_BYTES, sha256
from .core import Embedded, Plan, PREFIX, MAX_JOB_BYTES, embedded_entries, make_entry
from .sexpr import Node, parse, patch, quote, semantic
from .storage import atomic_write, job_directory, write_json

FORMAT = 'embed_3d_plugin-board-package-v1'
MANIFEST = 'WayriCAD_Embed3D_manifest.json'
MAX_MANIFEST = 8*1024*1024


def safe_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', value):
        raise ValueError('Unsafe or overlong local library/footprint name: '+str(value))
    if value.endswith(('.', ' ')) or value.split('.')[0].upper() in {
        'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1, 10)), *('LPT'+str(i) for i in range(1, 10))}:
        raise ValueError('Reserved filesystem name: '+value)
    return value


def slug(value: str, limit=70):
    result = re.sub(r'[^A-Za-z0-9_.-]+', '_', value).strip('._-')[:limit].rstrip('.') or 'footprint'
    return 'fp_'+result if result.split('.')[0].upper() in ('CON', 'AUX', 'PRN', 'NUL') else result


def uuid_of(text: str, root: Node | None = None):
    root = root or parse(text)
    node = root.one(text, 'uuid') or root.one(text, 'tstamp')
    if not node:
        raise ValueError('A placed footprint has no UUID')
    return node.arg().value(text)


def model_refs(text):
    return [node.arg().value(text) for node in parse(text).nodes(text, 'model')]


def model_settings(text):
    return [semantic(node.raw(text), True) for node in parse(text).nodes(text, 'model')]


def replace_entries(text: str, entries: dict[str, Embedded]):
    root = parse(text)
    old = root.one(text, 'embedded_files')
    raw = '\n(embedded_files\n'+'\n'.join(e.raw for e in entries.values())+'\n)\n' if entries else ''
    return patch(text, [(old.start, old.end, raw)] if old else [(root.end-1, root.end-1, raw)])


def entry_for_bytes(name, data: bytes, codec: Codec, file_type='other'):
    if len(data) > MAX_BYTES:
        raise ValueError('Embedded file exceeds the 256 MiB limit: '+name)
    encoded, digest = codec.encode(data), sha256(data)
    return Embedded(name, digest, encoded, make_entry(name, encoded, digest, file_type=file_type))


class PayloadReader:
    """Bound decompression and reuse decoded data by content, not by path."""
    def __init__(self, codec=None):
        self.codec = codec or Codec()
        self.cache = {}
        self.total = 0

    def read(self, entry: Embedded):
        if not entry.encoded:
            raise ValueError('Missing embedded bytes: '+entry.name)
        key = sha256(entry.encoded.encode('ascii'))
        if key not in self.cache:
            data = self.codec.decode(entry.encoded)
            self.total += len(data)
            if self.total > MAX_JOB_BYTES:
                raise ValueError('Embedded package exceeds the 512 MiB decompression budget')
            self.cache[key] = data
        data = self.cache[key]
        if re.fullmatch(r'[0-9a-fA-F]{64}', entry.checksum or '') and sha256(data) != entry.checksum.lower():
            raise ValueError('Embedded SHA256 mismatch: '+entry.name)
        return data


@dataclass
class Definition:
    key: str
    name: str
    text: str  # Native library-normalized text with localized payloads.
    source_id: str
    origin: str = 'board snapshot'


@dataclass
class Instance:
    uuid: str
    plan: Plan
    definition_key: str
    snapshot_key: str


@dataclass
class Package:
    board_text: str
    library_name: str
    library_files: dict[str, bytes]
    manifest: dict


def _board_fingerprint(text):
    """Mask only allowed changes, not arbitrary board/footprint geometry."""
    root = parse(text)
    edits = []
    for fp in root.nodes(text, 'footprint'):
        edits.append((fp.arg().start, fp.arg().end, '"<LIBRARY-ID>"'))
    return semantic(patch(text, edits), True)


def hydrate(text, pool, reader=None):
    """Make an archived definition standalone for the real .pretty reader."""
    reader = reader or PayloadReader()
    entries = embedded_entries(text)
    for ref in model_refs(text):
        if not ref.startswith(PREFIX):
            raise ValueError('Archived footprint still references an external model: '+ref)
        name = ref[len(PREFIX):]
        entry = entries.get(name) or pool.get(name)
        if not entry:
            raise ValueError('Board is missing model payload: '+name)
        reader.read(entry)
        entries[name] = entry
    return replace_entries(text, entries)


def compose(board_text: str, instances: list[Instance], definitions: list[Definition],
            library_name: str, codec=None) -> Package:
    """Pure composition; safe only after native normalization of definitions."""
    safe_name(library_name)
    root = parse(board_text)
    if root.head(board_text) != 'kicad_pcb':
        raise ValueError('Choose a KiCad PCB')
    codec = codec or Codec()
    reader = PayloadReader(codec)
    pool = embedded_entries(board_text)
    previous_manifest = pool.get(MANIFEST)
    if previous_manifest:
        try:
            previous = json.loads(reader.read(previous_manifest))
        except (ValueError, UnicodeError) as exc:
            raise ValueError('Reserved manifest name belongs to an unreadable attachment') from exc
        if not isinstance(previous, dict) or previous.get('format') != FORMAT:
            raise ValueError('Reserved manifest name belongs to a different attachment')
        del pool[MANIFEST]  # Replace only our active manifest; keep old attachments.
    definitions_by_key = {d.key: d for d in definitions}
    if len(definitions_by_key) != len(definitions) or not definitions:
        raise ValueError('Definitions must have unique keys and cannot be empty')
    if len({d.name.casefold() for d in definitions}) != len(definitions):
        raise ValueError('Definition names collide on a case-insensitive filesystem')
    by_uuid = {item.uuid: item for item in instances}
    fps = root.nodes(board_text, 'footprint')
    if len(by_uuid) != len(instances) or len(fps) != len(instances) or set(by_uuid) != {uuid_of(board_text, f) for f in fps}:
        raise ValueError('Packaging requires exactly one plan for EVERY placed footprint, including those without models')
    canonical = {}
    payload_hashes = {}

    def add(entry):
        existing = pool.get(entry.name)
        data = reader.read(entry)
        if existing and existing.encoded and reader.read(existing) != data:
            raise ValueError('Embedded file-name collision: '+entry.name)
        pool[entry.name] = entry
        payload_hashes[entry.name] = sha256(data)

    def pool_models(text):
        local = embedded_entries(text)
        for entry in local.values():
            if entry.encoded:
                add(entry)
        changes = []
        for model in parse(text).nodes(text, 'model'):
            ref = model.arg().value(text)
            if not ref.startswith(PREFIX):
                raise ValueError('Unresolved model prevents PCB packaging: '+ref)
            name = ref[len(PREFIX):]
            entry = local.get(name) or pool.get(name)
            if not entry or not entry.encoded:
                raise ValueError('Missing model data: '+name)
            data = reader.read(entry)
            suffixes = Path(name).suffixes
            suffix = ''.join(suffixes[-2:]) if suffixes and suffixes[-1].lower() in ('.gz', '.bz2', '.xz', '.zip') else Path(name).suffix
            key = (sha256(data), suffix.lower())
            if key not in canonical:
                # Choose a content-addressed filename independent of source location.
                chosen = 'model__'+key[0]+key[1]
                canon = Embedded(chosen, key[0], entry.encoded,
                                 make_entry(chosen, entry.encoded, key[0]))
                add(canon)
                canonical[key] = chosen
            target = canonical[key]
            changes.append((model.arg().start, model.arg().end, quote(PREFIX+target)))
        text = patch(text, changes)
        # Keep non-model resources local as well; they may be needed by footprint
        # editor fonts/datasheets. Model bytes themselves are moved to board pool.
        remaining = {}
        for name, entry in embedded_entries(text).items():
            token = parse(entry.raw).one(entry.raw, 'type')
            is_model = token and token.arg().value(entry.raw) == 'model'
            if not is_model:
                remaining[name] = entry
        return replace_entries(text, remaining)

    manifests, archived = [], {}
    for definition in definitions:
        safe_name(definition.name)
        text = definition.text
        fp_root = parse(text)
        if fp_root.head(text) != 'footprint' or fp_root.arg().value(text) != definition.name:
            raise ValueError('Definition is not normalized with its assigned library name: '+definition.name)
        pooled = pool_models(text)
        if semantic(text, True) != semantic(pooled, True) or model_settings(text) != model_settings(pooled):
            raise ValueError('A footprint setting changed during pooling')
        data = pooled.encode('utf-8')
        filename = 'WayriCAD_Embed3D_fp__'+sha256(data)+'.kicad_mod'
        entry = entry_for_bytes(filename, data, codec)
        add(entry)
        archived[definition.key] = pooled
        manifests.append({'key': definition.key, 'name': definition.name, 'source_id': definition.source_id,
                          'origin': definition.origin, 'embedded_file': filename, 'sha256': sha256(data),
                          'models': model_refs(pooled)})

    edits, instance_manifest = [], []
    for fp in fps:
        uid = uuid_of(board_text, fp)
        item = by_uuid[uid]
        if item.definition_key not in definitions_by_key or item.snapshot_key not in definitions_by_key:
            raise ValueError('Instance refers to a missing definition')
        plan, original = item.plan, fp.raw(board_text)
        if model_refs(original) != [r.reference for r in plan.rows] or model_settings(original) != model_settings(plan.original):
            raise ValueError('PCB model links or transforms changed since preview: '+plan.name)
        for row in plan.rows:
            if row.status != 'Embedded' and not (row.checked and row.ready):
                raise ValueError('Resolve every model before packaging: '+plan.name+' / '+row.reference)
        built = pool_models(plan.build())
        before_models = parse(original).nodes(original, 'model')
        after_refs = model_refs(built)
        local_edits = []
        for model, ref in zip(before_models, after_refs):
            local_edits.append((model.arg().start, model.arg().end, quote(ref)))
        target = library_name+':'+definitions_by_key[item.definition_key].name
        old_id = parse(original).arg().value(original)
        arg = parse(original).arg()
        local_edits.append((arg.start, arg.end, quote(target)))
        patched = patch(original, local_edits)
        # Gather original local attachments without reintroducing model payloads.
        nonmodels = {}
        for name, entry in embedded_entries(patched).items():
            if entry.encoded:
                add(entry)
            node = parse(entry.raw).one(entry.raw, 'type')
            if not node or node.arg().value(entry.raw) != 'model':
                nonmodels[name] = entry
        patched = replace_entries(patched, nonmodels)
        if model_settings(original) != model_settings(patched):
            raise ValueError('Board model transforms changed')
        # Stronger than semantic equality: every model's suffix is byte-identical.
        for old, new in zip(before_models, parse(patched).nodes(patched, 'model')):
            if original[old.arg().end:old.end] != patched[new.arg().end:new.end]:
                raise ValueError('A board model suffix was changed')
        edits.append((fp.start, fp.end, patched))
        instance_manifest.append({'uuid': uid, 'reference': plan.name, 'original_fpid': old_id,
                                  'new_fpid': target, 'definition_key': item.definition_key,
                                  'as_placed_snapshot_key': item.snapshot_key,
                                  'used_supplied_definition': item.definition_key != item.snapshot_key,
                                  'models': plan.manifest()['models']})
    output = patch(board_text, edits)
    # Drop newly introduced redundant model names (not pre-existing root names).
    # Canonical bytes are shared once even when original basenames differ.
    needed = set()
    for text in [output, *archived.values()]:
        nodes = parse(text).nodes(text, 'footprint') if parse(text).head(text) == 'kicad_pcb' else [parse(text)]
        for n in nodes:
            needed.update(m.arg().value(text)[len(PREFIX):] for m in n.nodes(text, 'model')
                          if m.arg().value(text).startswith(PREFIX))
    old_names = set(embedded_entries(board_text))
    for name, entry in list(pool.items()):
        type_node = parse(entry.raw).one(entry.raw, 'type')
        if type_node and type_node.arg().value(entry.raw) == 'model' and name not in needed and name not in old_names:
            del pool[name]
            payload_hashes.pop(name, None)
    manifest = {'format': FORMAT, 'plugin_version': '0.4.1', 'library_name': library_name,
                'definitions': manifests, 'instances': instance_manifest,
                'payload_sha256': payload_hashes,
                'scope': 'PCB footprints and linked 3D models; schematic fields are not changed',
                'library_requires_directory': True}
    manifest_data = json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8')
    if len(manifest_data) > MAX_MANIFEST:
        raise ValueError('Manifest exceeds 8 MiB; split unusually large boards')
    pool[MANIFEST] = entry_for_bytes(MANIFEST, manifest_data, codec)
    output = replace_entries(output, pool)
    if _board_fingerprint(board_text) != _board_fingerprint(output):
        raise ValueError('Safety check: board geometry, nets, attributes or model transforms changed')
    files = {d.name+'.kicad_mod': hydrate(archived[d.key], pool, reader).encode('utf-8') for d in definitions}
    package = Package(output, library_name, files, manifest)
    # Prove the output PCB alone can reconstruct exactly the same library.
    reconstructed = recover(output, codec)
    if reconstructed.library_files != files:
        raise ValueError('Board-only reconstruction does not match generated library')
    return package


def recover(board_text: str, codec=None) -> Package:
    root = parse(board_text)
    if root.head(board_text) != 'kicad_pcb':
        raise ValueError('Choose a .kicad_pcb file')
    pool = embedded_entries(board_text)
    if MANIFEST not in pool:
        raise ValueError('This PCB has no WayriCAD Embed3D footprint archive. Package it first.')
    reader = PayloadReader(codec)
    raw = reader.read(pool[MANIFEST])
    if len(raw) > MAX_MANIFEST:
        raise ValueError('Embedded manifest exceeds 8 MiB')
    meta = json.loads(raw)
    if not isinstance(meta, dict) or meta.get('format') != FORMAT:
        raise ValueError('Unknown board-package manifest format')
    library = safe_name(meta.get('library_name'))
    definitions = meta.get('definitions')
    hashes = meta.get('payload_sha256')
    if not isinstance(definitions, list) or not 0 < len(definitions) <= 20000 or not isinstance(hashes, dict):
        raise ValueError('Invalid archive definitions/hashes')
    files, names, keys = {}, set(), set()
    for item in definitions:
        if not isinstance(item, dict):
            raise ValueError('Invalid archived definition')
        name = safe_name(item.get('name'))
        key, filename = item.get('key'), item.get('embedded_file')
        if not isinstance(key, str) or key in keys or name.casefold() in names:
            raise ValueError('Duplicate or invalid footprint definition')
        keys.add(key); names.add(name.casefold())
        safe_name(filename)
        if filename not in pool:
            raise ValueError('Missing footprint snapshot: '+filename)
        data = reader.read(pool[filename])
        if sha256(data) != item.get('sha256') or sha256(data) != hashes.get(filename):
            raise ValueError('Snapshot hash mismatch: '+filename)
        text = data.decode('utf-8')
        fp = parse(text)
        if fp.head(text) != 'footprint' or fp.arg().value(text) != name:
            raise ValueError('Archived footprint name mismatch')
        if model_refs(text) != item.get('models'):
            raise ValueError('Archived model mapping mismatch')
        for ref in model_refs(text):
            model = ref[len(PREFIX):] if ref.startswith(PREFIX) else ''
            if model not in pool or sha256(reader.read(pool[model])) != hashes.get(model):
                raise ValueError('Missing or corrupt model payload: '+ref)
        files[name+'.kicad_mod'] = hydrate(text, pool, reader).encode('utf-8')
    return Package(board_text, library, files, meta)


def library_table(library: str, original=''):
    safe_name(library)
    uri = '${KIPRJMOD}/'+library+'.pretty'
    row = '(lib (name '+quote(library)+') (type "KiCad") (uri '+quote(uri)+') (options "") (descr "WayriCAD Embed3D board-embedded footprint snapshots"))'
    if not original.strip():
        return '(fp_lib_table\n  '+row+'\n)\n'
    root = parse(original)
    if root.head(original) != 'fp_lib_table':
        raise ValueError('Existing fp-lib-table is not valid')
    matched = []
    for node in root.nodes(original, 'lib'):
        name = node.one(original, 'name')
        if name and name.arg().value(original) == library:
            matched.append(node)
    if len(matched) > 1:
        raise ValueError('Duplicate library nickname in fp-lib-table')
    if matched:
        old_uri = matched[0].one(original, 'uri')
        old_type = matched[0].one(original, 'type')
        if not old_uri or old_uri.arg().value(original) != uri or not old_type or old_type.arg().value(original) != 'KiCad':
            raise ValueError('Library nickname already maps elsewhere; table was not changed')
        return original
    return patch(original, [(root.end-1, root.end-1, '\n  '+row+'\n')])


def _no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Refusing to write through a symlink: '+str(part))


def write_package(package: Package, destination: Path, board_name: str,
                  sidecars: dict[str, bytes] | None = None, validate: Callable | None = None):
    """Publish a new directory only after all writes and optional native validation."""
    destination = Path(destination).absolute()
    _no_symlinks(destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError('Choose a NEW folder inside an existing parent directory')
    if Path(board_name).name != board_name or '\\' in board_name or not board_name.lower().endswith('.kicad_pcb'):
        raise ValueError('Use a plain .kicad_pcb filename')
    allowed = {str(Path(board_name).with_suffix(s)) for s in ('.kicad_pro', '.kicad_dru')}
    if any(name not in allowed for name in (sidecars or {})):
        raise ValueError('Unexpected design sidecar')
    staging = Path(tempfile.mkdtemp(prefix='.embed_3d_plugin-package-', dir=destination.parent))
    try:
        board_path = staging/board_name
        atomic_write(board_path, package.board_text.encode('utf-8'))
        library = staging/(safe_name(package.library_name)+'.pretty')
        library.mkdir()
        for name, data in package.library_files.items():
            safe_name(name)
            atomic_write(library/name, data)
        atomic_write(staging/'fp-lib-table', library_table(package.library_name).encode('utf-8'))
        for name, data in (sidecars or {}).items():
            atomic_write(staging/name, data)
        write_json(staging/'WayriCAD Embed3D-package.json', package.manifest)
        atomic_write(staging/'README-WayriCAD Embed3D.txt', (
            'Open '+board_name+' in KiCad 10. The original project was not modified.\n'
            'Footprint snapshots and model bytes are embedded INSIDE the PCB.\n'
            'The .pretty directory is the native editable library reconstructed from that archive.\n'
            'Keep this folder together for normal library operations. If only the PCB is moved,\n'
            'use WayriCAD Embed3D > Rebuild embedded library to restore the .pretty and fp-lib-table.\n'
            'The schematic is not copied or edited. Schematic Footprint fields can revert\n'
            'the new library links on Update PCB from Schematic. Use WayriCAD Embed3D-package.json\n'
            'to review original/new IDs before synchronizing a schematic separately.\n'
            'With supplied definitions, board pad geometry remains as placed; a subsequent\n'
            'Update Footprints from Library can change geometry. Review that operation.\n'
            'Copied .kicad_pro/.kicad_dru are saved disk versions, not unsaved settings.\n'
            'External worksheets, resources unrelated to models, and schematic libraries\n'
            'are outside this footprint-and-model package scope.\n').encode('utf-8'))
        if validate:
            validate(board_path, library)
        if board_path.read_bytes() != package.board_text.encode('utf-8'):
            raise ValueError('PCB package changed during native validation')
        for name, data in package.library_files.items():
            if (library/name).read_bytes() != data:
                raise ValueError('Library changed during native validation')
        if destination.exists():
            raise ValueError('Destination was created by another process')
        os.rename(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination/board_name


def _publish_new_file(target: Path, raw: bytes):
    """Atomic exclusive publication on a local filesystem; never a partial target.

    Uses a same-filesystem hard link after fsync. Filesystems without hard-link
    support fail safely instead of falling back to an overwrite-prone operation.
    """
    fd, temp_name = tempfile.mkstemp(prefix='.embed_3d_plugin-new-', dir=target.parent)
    staging = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.link(staging, target)  # Atomic and refuses any already-existing name.
    finally:
        staging.unlink(missing_ok=True)


def rebuild_library(board_path: Path, project: Path | None = None, apply=False, validate=None):
    """Rebuild without overwriting edited library files; preserve other table rows.

    Adds missing files, permits identical files, rejects divergent files. Journal
    and table backup precede writes. Failure rolls back only our new files/table.
    """
    board_path = Path(board_path).absolute()
    data = board_path.read_bytes()
    package = recover(data.decode('utf-8'))
    parent = Path(project).absolute() if project else board_path.parent
    _no_symlinks(parent)
    if not parent.is_dir():
        raise ValueError('Rebuild project directory does not exist')
    library = parent/(package.library_name+'.pretty')
    _no_symlinks(library)
    table = parent/'fp-lib-table'
    _no_symlinks(table)
    old_table = table.read_bytes() if table.exists() else None
    table_text = library_table(package.library_name, old_table.decode('utf-8') if old_table is not None else '')
    new_table = table_text.encode('utf-8')
    missing = []
    for name, raw in package.library_files.items():
        target = library/name
        _no_symlinks(target)
        if target.exists():
            if not target.is_file() or target.read_bytes() != raw:
                raise ValueError('Existing footprint has later/different edits; not overwritten: '+str(target))
        else:
            missing.append((target, raw))
    result = {'library': str(library), 'files': len(package.library_files), 'new_files': len(missing),
              'table_change': old_table != new_table, 'applied': False}
    if not apply:
        return result
    if not missing and old_table == new_table:
        return {**result, 'applied': True, 'unchanged': True}
    # Validate full reconstruction before touching a user library.
    if validate:
        with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-rebuild-') as tmp:
            preview = Path(tmp)/'rebuild.pretty'; preview.mkdir()
            for name, raw in package.library_files.items():
                (preview/name).write_bytes(raw)
            validate(board_path, preview)
    job = job_directory(parent)
    if old_table is not None:
        atomic_write(job/'before-fp-lib-table', old_table)
    write_json(job/'manifest.json', {'format': 'embed_3d_plugin-rebuild-v1', 'status': 'prepared',
                                   'board': str(board_path), 'new_files': [str(t) for t, _ in missing],
                                   'table_existed': old_table is not None})
    created, wrote_table, created_dir = [], False, not library.exists()
    try:
        if board_path.read_bytes() != data or (table.read_bytes() if table.exists() else None) != old_table:
            raise ValueError('PCB or library table changed during preview; rebuild again')
        library.mkdir(exist_ok=True)
        for target, raw in missing:
            if target.exists():
                raise ValueError('A footprint appeared during rebuild: '+str(target))
            _publish_new_file(target, raw)
            created.append((target, raw))
        if (table.read_bytes() if table.exists() else None) != old_table:
            raise ValueError('Library table changed during rebuild')
        if new_table != old_table:
            atomic_write(table, new_table)
            wrote_table = True
        write_json(job/'manifest.json', {'format': 'embed_3d_plugin-rebuild-v1', 'status': 'complete', **result})
    except Exception:
        if wrote_table and table.read_bytes() == new_table:
            if old_table is None:
                table.unlink()
            else:
                atomic_write(table, old_table)
        for path, raw in reversed(created):
            if path.exists() and path.read_bytes() == raw:
                path.unlink()
        if created_dir and library.exists() and not any(library.iterdir()):
            library.rmdir()
        raise
    return {**result, 'applied': True, 'journal': str(job)}
