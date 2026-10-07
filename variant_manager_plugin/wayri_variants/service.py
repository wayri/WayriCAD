"""Reviewed operations, immutable backups, and guarded source-file transactions.

All mutation entry points require an explicit editors_closed acknowledgement.
A multi-file transaction is NOT power-failure atomic; its verified ZIP is the
recovery source if the process or machine dies midway through a commit.
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import datetime as dt
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from typing import Callable, Iterable

from . import engine as E

Error = E.VariantPromoterError
DEFAULT = E.DEFAULT_VARIANT
FORMAT = 'org.wayri.variant-backup/v1'
MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_ENTRIES = 10000
IDENTITY_FIELDS = {'Reference', 'Sheetfile', 'Sheet file', 'Sheetname', 'Sheet name'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')


def _safe_rel(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise Error(f'Unsafe archive path: {name!r}')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('..', '.') for x in name.split('/')) or '' in name.split('/'):
        raise Error(f'Unsafe archive path: {name!r}')
    if any(ord(c) < 32 for c in name):
        raise Error('Control character in archive path')
    return p


def _inside(path: Path, home: Path) -> str:
    # Do not follow symlinked design files into another project.
    lexical = path.absolute()
    try:
        lexical.relative_to(home)
        relative = path.resolve().relative_to(home)
    except ValueError as exc:
        raise Error(f'External hierarchy/file is not writable by this manager: {path}') from exc
    cursor = lexical
    while cursor != home:
        if cursor.is_symlink():
            raise Error(f'Symlinked project paths are not supported for writes: {cursor}')
        cursor = cursor.parent
    return relative.as_posix()


def resolve_root(selected: str | Path) -> Path:
    p = Path(selected).expanduser().absolute()
    if not p.is_file():
        raise Error(f'File does not exist: {p}')
    if p.suffix.lower() == '.kicad_sch':
        return p
    if p.suffix.lower() == '.kicad_pcb':
        p = p.with_suffix('.kicad_pro')
    if p.suffix.lower() != '.kicad_pro' or not p.exists():
        raise Error('Choose a .kicad_pro or root .kicad_sch file.')
    data = json.loads(p.read_text(encoding='utf-8'))
    roots = E.project_top_level_sheets(p, data)
    if roots:
        return roots[0]
    root = p.with_suffix('.kicad_sch')
    if not root.is_file():
        raise Error('No matching root schematic found; select the root .kicad_sch explicitly.')
    return root


@dataclasses.dataclass
class Context:
    root: Path
    home: Path
    project: Path | None
    entries: dict
    data: dict | None
    schematics: list
    names: list[str]
    sources: dict[str, bytes]

    @property
    def hashes(self) -> dict[str, str | None]:
        hashes = {n: sha(b) for n, b in self.sources.items()}
        if self.project:
            # Creation of a new board after preview must not go unnoticed.
            pcb = _inside(self.project.with_suffix('.kicad_pcb'), self.home)
            hashes.setdefault(pcb, None)
        return hashes

    @property
    def root_rel(self) -> str:
        return _inside(self.root, self.home)

    @property
    def root_uuid(self) -> str:
        return E._uuid(next(s for s in self.schematics if s.path == self.root).root)


def load(selected: str | Path, *, writable: bool = False) -> Context:
    initial = resolve_root(selected)
    if initial.is_symlink():
        raise Error('Select the original schematic, not a symlink.')
    root, project, entries, data, project_hash, schematics, names = E._project_context(initial)
    home = (project.parent if project else root.parent).resolve()
    sources = {}
    for s in schematics:
        rel = _inside(s.path, home)
        raw = s.path.read_bytes()
        if sha(raw) != s.sha256:
            raise Error('Schematic changed while loading; reload the project.')
        sources[rel] = raw
    if project:
        raw = project.read_bytes()
        if sha(raw) != project_hash:
            raise Error('Project metadata changed while loading; reload.')
        sources[_inside(project, home)] = raw
        pcb = project.with_suffix('.kicad_pcb')
        if pcb.exists():
            sources[_inside(pcb, home)] = pcb.read_bytes()
    if sum(map(len, sources.values())) > MAX_TOTAL or any(len(b) > MAX_FILE for b in sources.values()):
        raise Error('Project exceeds the 128 MiB/file or 512 MiB snapshot safety limit.')
    ctx = Context(root, home, project, entries, data, schematics, names, sources)
    if writable:
        if project is None:
            raise Error('A .kicad_pro is required for durable native variant names. Save the project in KiCad first.')
        for s in schematics:
            gen = s.root.child_node('generator_version')
            major = (gen.scalar(0) or '').split('.')[0] if gen else ''
            if major and major != '10':
                raise Error(f'{s.path.name}: this build writes KiCad 10 files only (generator {gen.scalar(0)}).')
            if len(E._project_names_in_sch(s)) > 1:
                raise Error(f'{s.path.name}: shared multi-project instance data is read-only.')
        for name in names:
            if E._is_default_name(name) or name != name.strip():
                raise Error(f'Reserved or whitespace-ambiguous native variant name: {name!r}')
    check_fresh(ctx.home, ctx.hashes)
    return ctx


def check_fresh(home: Path, expected: dict[str, str | None]) -> None:
    for rel, expected_hash in expected.items():
        path = home / _safe_rel(rel)
        _inside(path, home)
        if expected_hash is None:
            if path.exists():
                raise Error(f'Preview is stale: {rel} was created. Preview again.')
        elif not path.is_file() or sha(path.read_bytes()) != expected_hash:
            raise Error(f'Preview is stale: {rel} changed or disappeared. Reload and preview again.')


def lock_files(ctx: Context) -> list[Path]:
    result = set()
    for rel in ctx.hashes:
        p = ctx.home / rel
        for candidate in (p.with_name('~' + p.name + '.lck'), p.with_name(p.name + '.lck')):
            if candidate.exists():
                result.add(candidate)
    return sorted(result)


def ensure_closed(ctx: Context, acknowledged: bool) -> None:
    if not acknowledged:
        raise Error('Save and close this project in KiCad, then confirm that its editors and project manager are closed.')
    found = lock_files(ctx)
    if found:
        raise Error('KiCad lock file(s) remain; nothing written:\n' + '\n'.join(str(p) for p in found) +
                    '\nClose the project, including its manager. Do not delete a live lock.')


@contextlib.contextmanager
def manager_lock(ctx: Context):
    p = ctx.home / '.wayri-variants.lock'
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise Error('Another variant transaction is active, or a previous run left .wayri-variants.lock. '
                    'Verify no manager is running before manually removing a stale lock.') from exc
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'created_utc': stamp(), 'root': ctx.root_rel}, f)
            f.flush()
            os.fsync(f.fileno())
        yield
    finally:
        p.unlink(missing_ok=True)


def object_key(s, obj, inst, home: Path) -> str:
    # UUID/path identity, not reference designation, survives reannotation.
    return json.dumps([_inside(s.path, home), obj.kind, obj.uuid,
                       inst.project_name if inst else '', inst.path_id if inst else ''], separators=(',', ':'))


def snapshot(ctx: Context) -> dict:
    objects = []
    seen = set()
    for s in ctx.schematics:
        for obj in s.objects:
            for inst in obj.instances or [None]:
                key = object_key(s, obj, inst, ctx.home)
                if key in seen:
                    raise Error('Duplicate symbol/sheet instance identity; refusing ambiguous snapshot.')
                seen.add(key)
                states = {DEFAULT: dataclasses.asdict(obj.base)}
                for name in ctx.names:
                    state = E._effective_state(obj.base, inst.variants.get(name) if inst else None, s.version)
                    states[name] = dataclasses.asdict(state)
                objects.append({'key': key, 'label': inst.reference if inst and inst.reference else obj.label,
                                'states': states, 'kind': obj.kind, 'file': _inside(s.path, ctx.home),
                                'uuid': obj.uuid, 'project_name': inst.project_name if inst else '',
                                'instance_path': inst.path_id if inst else '',
                                'identity': 'UUID plus project and hierarchy instance path'})
    # Native overrides are local. Report parent-sheet flags separately so a
    # child with no override is never mislabeled as the complete assembly state.
    for row in objects:
        ancestors = [parent for parent in objects if parent['kind'] == 'sheet'
                     and parent['project_name'] == row['project_name']
                     and row['instance_path'].startswith(parent['instance_path'].rstrip('/') + '/' + parent['uuid'])]
        row['parent_sheet_flags'] = {name: [
            {'key': parent['key'], 'label': parent['label'],
             'flags': {flag: parent['states'][name][flag] for flag in
                       ('dnp', 'exclude_from_sim', 'excluded_from_bom', 'excluded_from_board')}}
            for parent in ancestors] for name in [DEFAULT] + ctx.names}
        row['state_scope'] = 'local instance; parent sheet flags reported separately'
    return {'format': FORMAT, 'root_uuid': ctx.root_uuid, 'root': ctx.root_rel,
            'names': ctx.names, 'metadata': copy.deepcopy(ctx.entries), 'objects': objects}


def _state(raw: dict) -> E.State:
    keys = {f.name for f in dataclasses.fields(E.State)}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise Error('Malformed state in backup.')
    for name in keys - {'fields'}:
        if type(raw[name]) is not bool:
            raise Error('Non-boolean assembly flag in backup.')
    if not isinstance(raw['fields'], dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                 for k, v in raw['fields'].items()):
        raise Error('Malformed field values in backup.')
    return E.State(**copy.deepcopy(raw))


def _snapshot_map(data: dict) -> dict[str, dict[str, E.State]]:
    try:
        if data['format'] != FORMAT or not isinstance(data['names'], list) or not isinstance(data['objects'], list):
            raise Error('Unrecognized variant snapshot.')
        names = data['names']
        if any(not isinstance(n, str) or E._is_default_name(n) for n in names):
            raise Error('Invalid backup variant names.')
        if len({n.casefold() for n in names}) != len(names):
            raise Error('Duplicate backup variant names.')
        result = {}
        for obj in data['objects']:
            key = obj['key']
            if not isinstance(key, str) or key in result:
                raise Error('Duplicate/malformed backup object identity.')
            if set(obj['states']) != set(names) | {DEFAULT}:
                raise Error('Incomplete backup states.')
            result[key] = {n: _state(v) for n, v in obj['states'].items()}
        return result
    except (KeyError, TypeError) as exc:
        raise Error(f'Malformed variant snapshot: {exc}') from exc


@dataclasses.dataclass
class Plan:
    context: Context
    title: str
    operation: str
    writes: dict[str, bytes]
    expected: dict[str, str | None]
    summary: list[str]
    names_after: list[str]
    diff: str
    # Optional semantic contracts to verify on the rendered files.
    contract: dict | None = None

    @property
    def count(self) -> int:
        return len(self.writes)


def _diff(ctx: Context, writes: dict[str, bytes]) -> str:
    parts = []
    for rel, raw in writes.items():
        before = ctx.sources.get(rel, b'').decode('utf-8').splitlines(keepends=True)
        after = raw.decode('utf-8').splitlines(keepends=True)
        parts.extend(difflib.unified_diff(before, after, fromfile='before/' + rel, tofile='after/' + rel))
    return ''.join(parts)


def _validate_plan(plan: Plan) -> None:
    """Parse the exact after-files and check every named/default effective state."""
    with tempfile.TemporaryDirectory(prefix='wayri-variant-validation-') as tmp:
        home = Path(tmp)
        all_files = dict(plan.context.sources)
        all_files.update(plan.writes)
        for rel, raw in all_files.items():
            p = home / _safe_rel(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        after = load(home / plan.context.root_rel)
        if set(after.names) != set(plan.names_after):
            raise Error('Internal validation: variant inventory differs from requested result.')
        if plan.contract is not None:
            actual = _snapshot_map(snapshot(after))
            if set(actual) != set(plan.contract):
                raise Error('Internal validation: instance topology changed.')
            for key, desired_states in plan.contract.items():
                for name, desired in desired_states.items():
                    if name not in actual[key] or actual[key][name].signature() != desired.signature():
                        raise Error(f'Internal validation: effective state changed unexpectedly for {name}, {key}.')
    check_fresh(plan.context.home, plan.expected)


def _finish(ctx: Context, title: str, operation: str, writes: dict[str, bytes],
            summary: list[str], names_after: list[str], contract: dict | None) -> Plan:
    writes = {n: b for n, b in writes.items() if b != ctx.sources.get(n)}
    plan = Plan(ctx, title, operation, writes, dict(ctx.hashes), summary, names_after, _diff(ctx, writes), contract)
    plan.rows = _rows(_snapshot_map(snapshot(ctx)), contract) if contract is not None else []
    _validate_plan(plan)
    plan.seal = sha(json.dumps({'writes': {n: sha(b) for n, b in writes.items()},
                                'expected': plan.expected, 'names': plan.names_after}, sort_keys=True).encode('utf-8'))
    return plan


def plan_default(selected: str | Path, variant: str, *, keep_source: bool = True,
                 preserve_old: str | None = None) -> Plan:
    ctx = load(selected, writable=True)
    name = E._resolve_variant(variant, ctx.names, allow_default=False)
    sources = [(n, n) for n in ctx.names if n != name or keep_source]
    if preserve_old:
        preserve_old = E._validate_new_variant_name(preserve_old)
        if preserve_old.casefold() in {n.casefold() for n in ctx.names}:
            raise Error('The preserved old Default must have a new, unused variant name.')
        sources.append((preserve_old, DEFAULT))
    raw = E._plan_transform(ctx.root, operation='set-default', title=f'Set {name} as Default',
                           new_default_source=name, variant_sources=sources,
                           summary_head=f'{name} becomes Default; surviving variants retain their effective configurations.')
    writes = {_inside(p.path, ctx.home): p.new_text.encode('utf-8') for p in raw.schematic_files}
    if raw.project_new_text is not None:
        writes[_inside(ctx.project, ctx.home)] = raw.project_new_text.encode('utf-8')
    before = _snapshot_map(snapshot(ctx))
    contract = {}
    for key, states in before.items():
        chosen = states[name]
        for field in IDENTITY_FIELDS:
            if chosen.fields.get(field) != states[DEFAULT].fields.get(field):
                raise Error(f'Promotion changes identity/hierarchy field {field!r}; this operation is not supported.')
        contract[key] = {DEFAULT: chosen, **{new: states[source] for new, source in sources}}
    summary = [f'New Default: {name}', 'Other variants: effective values and flags preserved.',
               f'Source name: {"kept" if keep_source else "removed"}.',
               f'Old Default: {preserve_old or "saved in automatic backup only"}.',
               'PCB file is not edited. Reopen KiCad and run Update PCB from Schematic before outputs.']
    return _finish(ctx, raw.title, 'set-default', writes, summary, [n for n, _ in sources], contract)


def plan_delete(selected: str | Path, variants: Iterable[str]) -> Plan:
    ctx = load(selected, writable=True)
    chosen = list(dict.fromkeys(E._resolve_variant(n, ctx.names, allow_default=False) for n in variants))
    if not chosen:
        raise Error('Select at least one named variant. Default cannot be deleted.')
    dead = set(chosen)
    writes = {}
    for s in ctx.schematics:
        edits = []
        for obj in s.objects:
            for inst in obj.instances:
                for name, node in inst.variants.items():
                    if name in dead:
                        edits.append(E.Edit(node.start, node.end, '', f'delete {name}'))
        if edits:
            writes[_inside(s.path, ctx.home)] = E._apply_edits(s.text, edits).encode('utf-8')
    names_after = [n for n in ctx.names if n not in dead]
    text, _ = E._build_project_variant_text(ctx.project, ctx.data, ctx.entries,
                                           [(n, n) for n in names_after])
    if text is not None:
        writes[_inside(ctx.project, ctx.home)] = text.encode('utf-8')
    before = _snapshot_map(snapshot(ctx))
    contract = {k: {n: st for n, st in states.items() if n not in dead} for k, states in before.items()}
    summary = [f'Delete {len(chosen)} named variant(s): ' + ', '.join(chosen),
               'Default and all unselected schematic variants remain unchanged.',
               'A verified source snapshot is mandatory before deletion.',
               'PCB file is not edited. Update PCB from Schematic after reopening KiCad.']
    return _finish(ctx, f'Delete {len(chosen)} variants', 'bulk-delete', writes, summary, names_after, contract)


def backup_folder(ctx: Context) -> Path:
    return ctx.home / '.wayri-variant-backups'


def _write_backup(ctx: Context, *, reason: str, destination: Path | None = None,
                  absent_after_restore: Iterable[str] = ()) -> Path:
    check_fresh(ctx.home, ctx.hashes)
    semantic = snapshot(ctx)
    payload = {'files/' + rel: data for rel, data in ctx.sources.items()}
    payload['variants.json'] = (json.dumps(semantic, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    identifier = stamp() + '-' + uuid.uuid4().hex[:10]
    manifest = {'format': FORMAT, 'tool_version': E.APP_VERSION, 'id': identifier,
                'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'reason': reason,
                'root': ctx.root_rel, 'root_uuid': ctx.root_uuid,
                'project': _inside(ctx.project, ctx.home) if ctx.project else None,
                'variants': ctx.names, 'files': [], 'absent_paths': list(absent_after_restore),
                'variants_sha256': sha(payload['variants.json']),
                'scope': 'Schematic hierarchy, project settings, matching PCB if present. Not external libraries or 3D assets.'}
    for rel, raw in ctx.sources.items():
        manifest['files'].append({'path': rel, 'size': len(raw), 'sha256': sha(raw)})
    payload['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    if destination is None:
        folder = backup_folder(ctx)
        folder.mkdir(parents=True, exist_ok=True)
        if folder.is_symlink():
            raise Error('Backup directory may not be a symlink.')
        destination = folder / f'{identifier}.wvariants.zip'
    else:
        destination = Path(destination).expanduser().absolute()
        destination.parent.mkdir(parents=True, exist_ok=True)
    if destination in [ctx.home / n for n in ctx.sources]:
        raise Error('A backup cannot replace a project source file.')
    created = False
    try:
        with destination.open('xb') as stream:
            created = True
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for name, raw in payload.items():
                    z.writestr(name, raw)
            stream.flush()
            os.fsync(stream.fileno())
        check_fresh(ctx.home, ctx.hashes)
        read_backup(destination)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def create_backup(selected: str | Path, *, destination: Path | None = None,
                  editors_closed: bool = False) -> Path:
    ctx = load(selected)
    ensure_closed(ctx, editors_closed)
    with manager_lock(ctx):
        return _write_backup(ctx, reason='Manual backup', destination=destination)


def read_backup(path: str | Path) -> tuple[dict, dict, dict[str, bytes]]:
    """Validate without extracting. Paths, sizes, duplicates, and hashes are checked."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise Error('Backup is too large.')
            seen = set()
            for i in infos:
                _safe_rel(i.filename)
                cf = i.filename.casefold()
                if cf in seen or i.file_size > MAX_FILE or i.flag_bits & 1:
                    raise Error('Duplicate, encrypted, or oversized backup entry.')
                seen.add(cf)
                if stat.S_ISLNK(i.external_attr >> 16):
                    raise Error('Symlinks are not permitted in backups.')
            manifest = json.loads(z.read('manifest.json').decode('utf-8'))
            if manifest.get('format') != FORMAT:
                raise Error('Not a supported Wayri variant backup.')
            _safe_rel(manifest['root'])
            raw_variants = z.read('variants.json')
            if sha(raw_variants) != manifest['variants_sha256']:
                raise Error('Variant data checksum mismatch.')
            semantic = json.loads(raw_variants.decode('utf-8'))
            _snapshot_map(semantic)
            if semantic['root_uuid'] != manifest['root_uuid'] or semantic['names'] != manifest['variants']:
                raise Error('Backup manifest and semantic snapshot disagree.')
            payload = {}
            allowed = {'manifest.json', 'variants.json'}
            for entry in manifest['files']:
                name = entry['path']
                _safe_rel(name)
                if name.casefold() in {n.casefold() for n in payload}:
                    raise Error('Duplicate source path in manifest.')
                if Path(name).suffix not in {'.kicad_sch', '.kicad_pro', '.kicad_pcb'}:
                    raise Error('Unexpected source file type in backup.')
                raw = z.read('files/' + name)
                if len(raw) != entry['size'] or sha(raw) != entry['sha256']:
                    raise Error(f'Source checksum mismatch: {name}')
                payload[name] = raw
                allowed.add('files/' + name)
            if {i.filename for i in infos} != allowed or manifest['root'] not in payload:
                raise Error('Backup has unexpected or missing files.')
            for name in manifest.get('absent_paths', []):
                _safe_rel(name)
            return manifest, semantic, payload
    except Error:
        raise
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        raise Error(f'Cannot read or verify backup: {exc}') from exc


def list_backups(selected: str | Path) -> list[dict]:
    ctx = load(selected)
    result = []
    for path in sorted(backup_folder(ctx).glob('*.wvariants.zip'), reverse=True):
        try:
            manifest, _, _ = read_backup(path)
            if manifest['root_uuid'] == ctx.root_uuid:
                result.append({'path': str(path), **manifest, 'valid': True})
        except Error as exc:
            result.append({'path': str(path), 'id': path.name, 'created_utc': '',
                           'reason': str(exc), 'variants': [], 'valid': False})
    return result


def plan_restore_variants(selected: str | Path, backup: str | Path,
                          variants: Iterable[str], *, overwrite: bool = False) -> Plan:
    ctx = load(selected, writable=True)
    manifest, saved, _ = read_backup(backup)
    if saved['root_uuid'] != ctx.root_uuid:
        raise Error('Backup belongs to a different root schematic UUID.')
    saved_map = _snapshot_map(saved)
    current_map = _snapshot_map(snapshot(ctx))
    if set(saved_map) != set(current_map):
        raise Error('Symbol/sheet-instance topology differs from the backup. Variant-only restore is refused; '
                    'use a source snapshot on a copy or reconcile the hierarchy first.')
    chosen = list(dict.fromkeys(E._resolve_variant(n, saved['names'], allow_default=False) for n in variants))
    if not chosen:
        raise Error('Select at least one named variant to restore.')
    for n in chosen:
        collisions = [x for x in ctx.names if x.casefold() == n.casefold()]
        if collisions and (not overwrite or collisions[0] != n):
            raise Error(f'Variant {n!r} already exists (or differs only by case). Explicit replacement is required.')
    names_after = ctx.names + [n for n in chosen if n not in ctx.names]
    desired_map = copy.deepcopy(current_map)
    for key in current_map:
        for name in chosen:
            desired = saved_map[key][name].clone()
            current_base = current_map[key][DEFAULT]
            if set(desired.fields) != set(current_base.fields):
                raise Error('Field schema changed since backup. Variant-only restore refuses to add/remove field geometry.')
            # Do not undo reannotation or current sheet names/filenames.
            for field in IDENTITY_FIELDS:
                if field in current_base.fields:
                    desired.fields[field] = current_base.fields[field]
            desired_map[key][name] = desired
    writes = {}
    for s in ctx.schematics:
        edits = []
        for obj in s.objects:
            for inst in obj.instances:
                key = object_key(s, obj, inst, ctx.home)
                blocks = []
                for name in chosen:
                    old = inst.variants.get(name)
                    if old:
                        edits.append(E.Edit(old.start, old.end, '', f'replace variant {name}'))
                    desired = desired_map[key][name]
                    flags, fields = E._state_diff(obj.base, desired, obj.kind)
                    if flags or fields:
                        blocks.append(E._render_variant(name, obj.base, desired, obj.kind, s.version,
                                                        E._child_indent(s.text, inst.path_node), E._eol(s.text)))
                if blocks:
                    pos = E._closing_line_start(s.text, inst.path_node)
                    edits.append(E.Edit(pos, pos, ''.join(b + E._eol(s.text) for b in blocks), 'restore overrides'))
        if edits:
            writes[_inside(s.path, ctx.home)] = E._apply_edits(s.text, edits).encode('utf-8')
    metadata = {n: saved['metadata'].get(n, {'name': n}) for n in chosen}
    text, _ = E._build_project_variant_text(ctx.project, ctx.data, ctx.entries,
                                           [(n, n) for n in names_after], metadata)
    if text is not None:
        writes[_inside(ctx.project, ctx.home)] = text.encode('utf-8')
    return _finish(ctx, f'Restore {len(chosen)} named variant(s)', 'restore-variants', writes,
                   ['Restore: ' + ', '.join(chosen), 'Current Default, drawing geometry, and unselected variants stay unchanged.',
                    'Saved effective fields/flags are rebased against the current Default.',
                    'Update PCB from Schematic afterward.'], names_after, desired_map)


def plan_restore_sources(selected: str | Path, backup: str | Path) -> Plan:
    ctx = load(selected, writable=True)
    manifest, saved, payload = read_backup(backup)
    if manifest['root_uuid'] != ctx.root_uuid or manifest['root'] != ctx.root_rel:
        raise Error('Source restore requires the same root UUID and relative filename.')
    if manifest.get('absent_paths'):
        raise Error('This recovery backup records formerly absent files. Restore on a copy and review the manifest; '
                    'automatic file deletion during rollback is deliberately not supported.')
    for rel, raw in payload.items():
        _inside(ctx.home / _safe_rel(rel), ctx.home)
        if Path(rel).suffix == '.kicad_pro':
            json.loads(raw.decode('utf-8'))
        else:
            parsed = E.SExprParser(raw.decode('utf-8')).parse()
            expected = 'kicad_sch' if Path(rel).suffix == '.kicad_sch' else 'kicad_pcb'
            if parsed.head != expected:
                raise Error(f'Wrong source format in archive: {rel}')
    writes = {n: b for n, b in payload.items() if b != ctx.sources.get(n)}
    expected = dict(ctx.hashes)
    for rel in writes:
        p = ctx.home / rel
        expected[rel] = sha(p.read_bytes()) if p.is_file() else None
    plan = Plan(ctx, 'Restore source-file snapshot', 'restore-sources', writes, expected,
                ['WARNING: rewinds complete saved schematics/project settings and the PCB if present.',
                 'This can undo later drawing and layout edits, not just variant edits.',
                 'Unrelated files are left alone. Libraries, 3D assets, and jobsets are not restored.',
                 'A fresh pre-restore backup is created before any replacement.'], saved['names'], _diff(ctx, writes), None)
    _validate_plan(plan)
    plan.seal = sha(json.dumps({'writes': {n: sha(b) for n, b in writes.items()},
                                'expected': plan.expected, 'names': plan.names_after}, sort_keys=True).encode('utf-8'))
    return plan


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.wayri-tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def apply(plan: Plan, *, editors_closed: bool = False) -> Path | None:
    """Apply exactly the previewed bytes, never recompute an operation after approval."""
    ctx = plan.context
    seal = sha(json.dumps({'writes': {n: sha(b) for n, b in plan.writes.items()},
                           'expected': plan.expected, 'names': plan.names_after}, sort_keys=True).encode('utf-8'))
    if getattr(plan, 'seal', None) != seal:
        raise Error('Reviewed candidate changed in memory. Preview the operation again.')
    ensure_closed(ctx, editors_closed)
    if not plan.writes:
        check_fresh(ctx.home, plan.expected)
        return None
    with manager_lock(ctx):
        ensure_closed(ctx, editors_closed)
        check_fresh(ctx.home, plan.expected)
        before = {rel: (ctx.home / rel).read_bytes() if (ctx.home / rel).is_file() else None for rel in plan.writes}
        # Include an existing source destination even when it isn't in the current hierarchy.
        recovery_sources = dict(ctx.sources)
        recovery_sources.update({n: b for n, b in before.items() if b is not None})
        recovery_ctx = dataclasses.replace(ctx, sources=recovery_sources)
        backup = _write_backup(recovery_ctx, reason=plan.title,
                               absent_after_restore=[n for n, b in before.items() if b is None])
        check_fresh(ctx.home, plan.expected)
        ensure_closed(ctx, editors_closed)
        changed = []
        try:
            for rel, raw in plan.writes.items():
                # Abort rather than overwrite a change made between staged replacements.
                remaining = {n: h for n, h in plan.expected.items() if n not in changed}
                check_fresh(ctx.home, remaining)
                _atomic_bytes(ctx.home / rel, raw)
                changed.append(rel)
            for rel, raw in plan.writes.items():
                if sha((ctx.home / rel).read_bytes()) != sha(raw):
                    raise Error(f'Post-write verification failed: {rel}')
        except Exception as exc:
            rollback_errors = []
            for rel in reversed(changed):
                try:
                    # Avoid overwriting an external edit made after our write.
                    if sha((ctx.home / rel).read_bytes()) != sha(plan.writes[rel]):
                        raise Error('Another process changed the file; not overwritten during rollback')
                    if before[rel] is None:
                        (ctx.home / rel).unlink(missing_ok=True)
                    else:
                        _atomic_bytes(ctx.home / rel, before[rel])
                except Exception as rb:
                    rollback_errors.append(f'{rel}: {rb}')
            detail = '\nRollback needs attention: ' + '; '.join(rollback_errors) if rollback_errors else '\nWritten files were rolled back.'
            raise Error(f'Apply failed: {exc}{detail}\nVerified recovery backup: {backup}') from exc
        # A receipt is informational; failure to write it must not undo a successful transaction.
        try:
            receipt = backup.with_suffix('.receipt.json')
            _atomic_bytes(receipt, (json.dumps({'operation': plan.operation, 'title': plan.title,
                          'applied_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                          'backup': backup.name, 'after_sha256': {n: sha(b) for n, b in plan.writes.items()}},
                          indent=2) + '\n').encode('utf-8'))
        except OSError:
            pass
        return backup


def inventory(selected: str | Path) -> dict:
    """Return exact effective native states by stable hierarchy instance key."""
    ctx = load(selected)
    result = snapshot(ctx)
    result.update(source_hashes=ctx.hashes, project=str(ctx.root),
                  flags=['dnp', 'exclude_from_sim', 'excluded_from_bom',
                         'excluded_from_board', 'excluded_from_pos'])
    return result


def _rows(before: dict, after: dict) -> list[dict]:
    result = []
    for key in sorted(set(before) | set(after)):
        for variant in sorted(set(before.get(key, {})) | set(after.get(key, {}))):
            left = before.get(key, {}).get(variant)
            right = after.get(key, {}).get(variant)
            if left is None or right is None or left.signature() != right.signature():
                result.append({'key': key, 'variant': variant,
                               'before': dataclasses.asdict(left) if left else None,
                               'after': dataclasses.asdict(right) if right else None})
    return result


def preview(selected: str | Path, operations: list[dict]) -> Plan:
    """Stage a batch of variant operations without writing the source project.

    Operations use exact native names and instance keys from inventory(). Merge
    policies are error, source or target. Edits accept fields and boolean flags;
    deleting a field override uses null and restores the Default field value.
    Identity and hierarchy fields cannot be edited. Default promotion rejects
    diverging reused-sheet instances because their serialized base is shared.
    """
    if not isinstance(operations, list) or not operations:
        raise Error('Provide a nonempty list of operations.')
    ctx = load(selected, writable=True)
    before = _snapshot_map(snapshot(ctx))
    states = copy.deepcopy(before)
    names = list(ctx.names)
    metadata = copy.deepcopy(ctx.entries)
    summary = []
    flags = {f.name for f in dataclasses.fields(E.State)} - {'fields'}

    def resolve(name, default=False):
        return E._resolve_variant(name, names, allow_default=default)

    def unused(name):
        name = E._validate_new_variant_name(name)
        if name.casefold() in {n.casefold() for n in names}:
            raise Error(f'Variant already exists: {name}')
        return name

    for operation in operations:
        if not isinstance(operation, dict):
            raise Error('Each operation must be an object.')
        op = operation.get('op')
        schemas = {
            'create': ({'name'}, {'source'}), 'duplicate': ({'name', 'source'}, set()),
            'rename': ({'name', 'source'}, set()), 'delete': ({'variants'}, set()),
            'swap': ({'left', 'right'}, set()), 'edit': ({'variant', 'keys'}, {'fields', 'flags'}),
            'merge': ({'source', 'target'}, {'policy'}),
            'promote': ({'source'}, {'preserve_old', 'keep_source'}),
            'set-default': ({'source'}, {'preserve_old', 'keep_source'}), 'clean': (set(), set())}
        if op not in schemas:
            raise Error(f'Unsupported operation: {op!r}')
        required, optional = schemas[op]
        if required - operation.keys() or operation.keys() - required - optional - {'op'}:
            raise Error(f'{op}: missing required keys or unsupported operation arguments.')
        if 'keep_source' in operation and type(operation['keep_source']) is not bool:
            raise Error('keep_source must be boolean.')
        for argument in ('name', 'source', 'left', 'right', 'variant', 'target', 'preserve_old', 'policy'):
            if argument in operation and not isinstance(operation[argument], str):
                raise Error(f'{argument} must be a string.')
        for argument in ('keys', 'variants'):
            if argument in operation and (not isinstance(operation[argument], list) or
                    any(not isinstance(value, str) for value in operation[argument])):
                raise Error(f'{argument} must be a list of strings.')
        if op in ('create', 'duplicate'):
            name = unused(operation['name'])
            source = resolve(operation.get('source', DEFAULT), True)
            for item in states.values():
                item[name] = item[source].clone()
            names.append(name)
            metadata[name] = copy.deepcopy(metadata.get(source, {}))
        elif op == 'rename':
            source = resolve(operation['source'])
            name = unused(operation['name'])
            names[names.index(source)] = name
            for item in states.values():
                item[name] = item.pop(source)
            metadata[name] = metadata.pop(source, {})
        elif op == 'delete':
            chosen = operation.get('variants', [])
            if not chosen:
                raise Error('Select at least one variant to delete.')
            for name in dict.fromkeys(resolve(n) for n in chosen):
                names.remove(name)
                metadata.pop(name, None)
                for item in states.values():
                    del item[name]
        elif op == 'swap':
            left, right = resolve(operation['left']), resolve(operation['right'])
            if left == right:
                raise Error('Choose two different named variants to swap.')
            for item in states.values():
                item[left], item[right] = item[right], item[left]
            metadata[left], metadata[right] = metadata.get(right, {}), metadata.get(left, {})
        elif op == 'edit':
            variant = resolve(operation['variant'])
            keys = operation.get('keys', [])
            if not keys or any(k not in states for k in keys):
                raise Error('Edit requires existing exact instance keys from inventory.')
            fields = operation.get('fields', {})
            changes = operation.get('flags', {})
            if not isinstance(fields, dict) or not isinstance(changes, dict):
                raise Error('Fields and flags must be objects.')
            if set(fields) & IDENTITY_FIELDS or any(not isinstance(k, str) for k in fields):
                raise Error('Identity and hierarchy fields cannot be edited.')
            if set(changes) - flags or any(type(v) is not bool for v in changes.values()):
                raise Error('Unsupported flag or non-boolean flag value.')
            for key in dict.fromkeys(keys):
                state = states[key][variant]
                for field, value in fields.items():
                    if value is None:
                        if field in states[key][DEFAULT].fields:
                            state.fields[field] = states[key][DEFAULT].fields[field]
                        else:
                            state.fields.pop(field, None)
                    elif isinstance(value, str):
                        state.fields[field] = value
                    else:
                        raise Error('Field values must be strings or null to inherit Default.')
                for flag, value in changes.items():
                    setattr(state, flag, value)
        elif op == 'merge':
            source, target = resolve(operation['source']), resolve(operation['target'])
            policy = operation.get('policy', 'error')
            if source == target or policy not in ('error', 'source', 'target'):
                raise Error('Merge requires different variants and policy error/source/target.')
            conflicts = []
            missing = object()
            for key, item in states.items():
                base, src, dst = item[DEFAULT], item[source], item[target]
                for field in set(base.fields) | set(src.fields) | set(dst.fields):
                    b, s, d = (st.fields.get(field, missing) for st in (base, src, dst))
                    if s == b or s == d:
                        continue
                    if d != b and policy == 'error':
                        conflicts.append(f'{key}: field {field}')
                        continue
                    if d == b or policy == 'source':
                        if s is missing:
                            dst.fields.pop(field, None)
                        else:
                            dst.fields[field] = s
                for flag in flags:
                    b, s, d = (getattr(st, flag) for st in (base, src, dst))
                    if s != b and s != d:
                        if d != b and policy == 'error':
                            conflicts.append(f'{key}: {flag}')
                        elif d == b or policy == 'source':
                            setattr(dst, flag, s)
            if conflicts:
                raise Error('Merge conflicts require an explicit source/target policy:\n' + '\n'.join(conflicts))
        elif op in ('promote', 'set-default'):
            source = resolve(operation['source'])
            preserve = operation.get('preserve_old')
            if preserve:
                preserve = unused(preserve)
                names.append(preserve)
                metadata[preserve] = {}
            for key, item in states.items():
                if preserve:
                    item[preserve] = item[DEFAULT].clone()
                item[DEFAULT] = item[source].clone()
                for field in IDENTITY_FIELDS:
                    if item[DEFAULT].fields.get(field) != before[key][DEFAULT].fields.get(field):
                        raise Error(f'Promotion changes identity field {field}.')
            if not operation.get('keep_source', True):
                names.remove(source)
                metadata.pop(source, None)
                for item in states.values():
                    del item[source]
        elif op == 'clean':
            pass
        else:
            raise Error(f'Unsupported operation: {op!r}')
        summary.append(f'{op}: ' + ', '.join(str(v) for k, v in operation.items() if k not in ('op', 'keys')))

    writes = {}
    for sch in ctx.schematics:
        edits = []
        for obj in sch.objects:
            if not obj.instances:
                continue
            desired_bases = [states[object_key(sch, obj, inst, ctx.home)][DEFAULT] for inst in obj.instances]
            if len({s.signature() for s in desired_bases}) != 1:
                raise Error(f'{sch.path.name}: reused hierarchical instances have different Default states; cannot promote.')
            base = desired_bases[0]
            E._desired_base_edits(sch, obj, base, edits, [])
            for inst in obj.instances:
                for name, node in inst.variants.items():
                    edits.append(E.Edit(node.start, node.end, '', 'replace native variant'))
                key = object_key(sch, obj, inst, ctx.home)
                indent, eol = E._child_indent(sch.text, inst.path_node), E._eol(sch.text)
                blocks = []
                for name in names:
                    desired = states[key][name]
                    changed_flags, fields = E._state_diff(base, desired, obj.kind)
                    if changed_flags or fields:
                        blocks.append(E._render_variant(name, base, desired, obj.kind, sch.version, indent, eol))
                if blocks:
                    pos = E._closing_line_start(sch.text, inst.path_node)
                    edits.append(E.Edit(pos, pos, ''.join(b + eol for b in blocks), 'insert native variants'))
        if edits:
            writes[_inside(sch.path, ctx.home)] = E._apply_edits(sch.text, edits).encode('utf-8')
    text, _ = E._build_project_variant_text(ctx.project, ctx.data, ctx.entries,
                                           [(n, n if n in ctx.names else DEFAULT) for n in names], metadata)
    if text is not None:
        writes[_inside(ctx.project, ctx.home)] = text.encode('utf-8')
    plan = _finish(ctx, f'{len(operations)} reviewed variant operation(s)', 'batch', writes, summary, names, states)
    plan.rows = _rows(before, states)
    return plan


def review(plan: Plan) -> dict:
    """Serializable review evidence; apply uses the immutable in-memory Plan."""
    return {'title': plan.title, 'operation': plan.operation, 'summary': plan.summary,
            'variants_before': plan.context.names, 'variants_after': plan.names_after,
            'source_hashes': plan.expected, 'candidate_hashes': {n: sha(b) for n, b in plan.writes.items()},
            'rows': getattr(plan, 'rows', []),
            'states_after': {key: {name: dataclasses.asdict(state) for name, state in values.items()}
                             for key, values in (plan.contract or {}).items()}, 'diff': plan.diff,
            'files': list(plan.writes), 'requires_closed_editors': True}
