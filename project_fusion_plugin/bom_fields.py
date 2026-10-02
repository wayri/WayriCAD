"""Selected-configuration inventory, BOM grouping and detached field edits.

Identity is source alias plus instance path, never a displayed reference. Candidate
copies materialize the selected configuration as Default; originals are read-only.
"""
from __future__ import annotations
import copy
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from dataclasses import asdict
from . import sexpr as sx
from .model import MergeError, SourceSpec,validate_source_aliases
from .variants import state, effective_board_flags, set_field, DEFAULT, FLAGS

PROTECTED = {'Reference', 'Footprint', 'Sheetfile', 'Sheet file', *FLAGS}
PROTECTED_KEYS = {name.casefold() for name in PROTECTED}

def _field_names(fields):
    names = list(fields)
    if any(not isinstance(k, str) or not k.strip() for k in names):
        raise MergeError('Field names must be nonempty strings.')
    if len({k.casefold() for k in names}) != len(names):
        raise MergeError('Conflicting field names differ only by case.')

def inventory(sources):
    rows = []
    seen = set()
    for source in sources:
        for record in source.symbols:
            identity = (source.alias, record.old_path, record.old_uuid)
            if identity in seen:
                raise MergeError('Duplicate field inventory identity.')
            seen.add(identity)
            fields = dict(state(record.node)['fields'])
            _field_names(fields)
            rows.append({'identity': identity, 'source': source.alias,
                         'variant': source.selected_variant, 'reference': record.old_ref,
                         'unit': record.unit, 'sheet_path': record.sheet.old_path,
                         'fields': fields,
                         'flags': effective_board_flags(record)})
    return sorted(rows, key=lambda r: r['identity'])

def grouped_bom(rows, include_excluded=False, reference_map=None):
    """One quantity per physical multi-unit reference; every field must agree.

    References are used only to combine units within the same sheet occurrence,
    with identities retained. Conflicting units fail instead of losing metadata.
    """
    parts = {}
    for row in rows:
        _field_names(row['fields'])
        if row['reference'].startswith('#'):
            continue
        fields = {k: v for k, v in row['fields'].items() if k != 'Reference'}
        signature = json.dumps([fields, row['flags']], sort_keys=True, ensure_ascii=False)
        part_key = (row['source'], row['sheet_path'], row['reference'])
        if part_key in parts and parts[part_key]['signature'] != signature:
            raise MergeError(f'Conflicting multi-unit fields: {part_key}')
        part = parts.setdefault(part_key, {'signature': signature, 'fields': fields,
                               'flags': dict(row['flags']), 'identities': []})
        part['identities'].append(row['identity'])
    groups = {}
    for key, part in sorted(parts.items()):
        if not include_excluded and part['flags']['in_bom'] == 'no':
            continue
        group = groups.setdefault(part['signature'], {'fields': part['fields'],
                    'flags': part['flags'], 'quantity': 0, 'references': [], 'identities': []})
        group['quantity'] += 1
        reference = (reference_map or {}).get((key[0], key[1], key[2]), key[2])
        group['references'].append({'source': key[0], 'sheet_path': key[1], 'reference': reference,
                                    'original_reference': key[2]})
        group['identities'].extend(part['identities'])
    return [groups[k] for k in sorted(groups)]

def export_csv(path, rows, bom=False):
    """UTF-8, fully quoted metadata with provenance serialized without ambiguity."""
    names = sorted({k for r in rows for k in r['fields']})
    prefix = ['quantity', 'references', 'identities'] if bom else ['source', 'variant', 'reference', 'unit', 'identity']
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream, quoting=csv.QUOTE_ALL)
        writer.writerow(prefix + list(FLAGS) + names)
        for row in rows:
            writer.writerow([json.dumps(row[k], ensure_ascii=False) if isinstance(row[k], (list, tuple, dict)) else row[k]
                             for k in prefix] + [row['flags'][k] for k in FLAGS] + [row['fields'].get(k, '') for k in names])

def preview_fields(rows, identities, edits=None, renames=None):
    """Return an explicit before/after plan; rename collisions are always errors."""
    edits, renames = edits or {}, renames or {}
    _field_names(edits); _field_names(renames); _field_names(renames.values())
    names = set(edits) | set(renames) | set(renames.values())
    _field_names(names)
    if any(k.casefold() in PROTECTED_KEYS for k in names):
        raise MergeError('Generic field edits cannot change structural fields or assembly flags.')
    if {k.casefold() for k in edits} & {k.casefold() for k in renames.values()}:
        raise MergeError('An edited field conflicts with a rename target.')
    if any(not isinstance(v, str) for v in edits.values()):
        raise MergeError('Field values must be strings.')
    wanted = {tuple(i) for i in identities}
    found = set()
    plan = []
    for row in rows:
        ident = tuple(row['identity'])
        if ident not in wanted:
            continue
        found.add(ident)
        before = dict(row['fields']); after = dict(before)
        _field_names(before)
        existing = {k.casefold(): k for k in before}
        for name in set(edits) | set(renames):
            if name.casefold() in existing and existing[name.casefold()] != name:
                raise MergeError('Use the existing field spelling: ' + existing[name.casefold()])
        for old, new in renames.items():
            if old == new or old not in before:
                continue
            if new.casefold() in existing or new.casefold() in {k.casefold() for k in edits}:
                raise MergeError(f'Field rename conflict at {ident}: {old} -> {new}')
            after[new] = after.pop(old)
        after.update(edits)
        _field_names(after)
        plan.append({'identity': ident, 'before': before, 'after': after})
    if found != wanted:
        raise MergeError('A selected field identity is missing or stale.')
    return plan

def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _check(hashes):
    for path, digest in hashes.items():
        if not Path(path).is_file() or _digest(path) != digest:
            raise MergeError(f'Source changed; no candidate published: {path}')

def apply_to_copies(sources, plan, destination):
    """Publish a new folder atomically, with each selected hierarchy cloned per occurrence.

    Board geometry is copied untouched. Merge preflight subsequently synchronizes
    permitted PCB metadata. Candidate assets still require normal Fusion auditing.
    """
    from .engine import publish
    from .repair import copy_project, project_files
    validate_source_aliases([s.spec for s in sources])
    dest = Path(destination).resolve()
    if dest.exists():
        raise MergeError('Candidate destination already exists.')
    for source in sources:
        if dest == source.project_file.parent or source.project_file.parent in dest.parents:
            raise MergeError('Candidate destination must be outside source projects.')
        if any(source.project_file.parent not in sheet.source_path.parents for sheet in source.sheets):
            raise MergeError(source.alias + ': external child-sheet resources cannot be safely rebased for field copies. Bring child sheets and their resources into a self-contained project copy first.')
    work = copy.deepcopy(sources)
    rows = {tuple(r['identity']): r for r in inventory(work)}
    changes = {}
    for item in plan:
        ident = tuple(item['identity'])
        if ident in changes or ident not in rows or rows[ident]['fields'] != item['before']:
            raise MergeError('Field plan identity/state is stale or duplicated.')
        changed = set(item['before']) | set(item['after'])
        _field_names(item['before']); _field_names(item['after'])
        if any(k.casefold() in PROTECTED_KEYS and item['before'].get(k) != item['after'].get(k) for k in changed):
            raise MergeError('Structural edits are forbidden in a field plan.')
        if any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in item['after'].items()):
            raise MergeError('Malformed field plan.')
        changes[ident] = item
    hashes = {}; copied_files = {}
    for source in work:
        hashes.update(source.hashes)
        copied_files[source.alias] = set(project_files(source.project_file.parent))
        for path in set(source.files) | copied_files[source.alias]:
            hashes.setdefault(str(path), _digest(path))
    _check(hashes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.fusion-fields-', dir=dest.parent))
    try:
        specs = []
        for source in work:
            folder = stage / source.alias
            copy_project(source.project_file.parent, folder)
            for original in copied_files[source.alias]:
                if _digest(folder / original.relative_to(source.project_file.parent)) != hashes[str(original)]:
                    raise MergeError('A copied source asset changed during staging: ' + str(original))
            targets = {sheet.old_path: (folder / source.schematic_file.name if index == 0 else
                       folder / sheet.source_path.parent.relative_to(source.project_file.parent) / f'fields_sheet_{index:03}.kicad_sch')
                       for index, sheet in enumerate(source.sheets)}
            for sheet in source.sheets:
                for record in sheet.symbols:
                    patch = changes.get((source.alias, record.old_path, record.old_uuid))
                    if patch:
                        for prop in list(sx.children(record.node, 'property')):
                            offset = 2 if len(prop)>1 and prop[1]=='private' and not isinstance(prop[1], sx.Quoted) else 1
                            if str(prop[offset]) not in patch['after']:
                                record.node.remove(prop)
                        for name, value in patch['after'].items():
                            set_field(record.node, name, value)
                for node, child in sheet.sub_sheets:
                    name = 'Sheetfile' if sx.prop(node, 'Sheetfile') is not None else 'Sheet file'
                    import os
                    relative = os.path.relpath(targets[child.old_path], targets[sheet.old_path].parent).replace('\\', '/')
                    set_field(node, name, relative)
                sx.save(targets[sheet.old_path], sheet.tree)
            project = copy.deepcopy(source.project)
            project.setdefault('schematic', {})['variants'] = []
            for key in ('variant', 'current_variant'):
                project['schematic'].pop(key, None)
            (folder / source.project_file.name).write_text(json.dumps(project, indent=2), encoding='utf-8')
            data = asdict(source.spec)
            data.update(project=str(dest / source.alias / source.project_file.name), variant=DEFAULT)
            specs.append(SourceSpec(**data))
        (stage / 'field-changes.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
        (stage / 'source-hashes.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
        (stage / 'candidate-status.json').write_text(json.dumps({
            'selected_variants_materialized_as_default': True,
            'pcb_geometry_modified': False,
            'pcb_field_parity': 'pending Fusion merge preflight synchronization',
            'assets': 'local project assets copied; external assets require normal Fusion audit; source overrides retained',
            'original_files_modified': False}, indent=2), encoding='utf-8')
        _check(hashes)
        for source in work:
            if set(project_files(source.project_file.parent)) != copied_files[source.alias]:
                raise MergeError('Source file inventory changed during staging: ' + source.alias)
        publish(stage, dest)
        return specs
    finally:
        if stage.exists():
            shutil.rmtree(stage)
