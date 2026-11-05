"""Bounded, read-only field table from saved KiCad PCB or schematic sources.

Rows preserve physical symbol/footprint identity and explicit variant deltas.
This module does not evaluate KiCad expressions, infer variant inheritance, or
write design files. Provider scope and publication remain with ReviewSession.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from wayricad_runtime.schematic_sexpr import Node, parse, properties


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 64
MAX_ROWS = 5000
MAX_DEPTH = 32
_FLAGS = ('dnp', 'in_bom', 'on_board', 'in_pos_files', 'exclude_from_sim')
_DEFAULT_FLAGS = dict(dnp=False, in_bom=True, on_board=True,
                      in_pos_files=True, exclude_from_sim=False)


def _safe(path: Path, base: Path) -> Path:
    """Reject in-project links and escapes before reading exact saved bytes."""
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise ValueError('BOM source is outside the selected project directory.') from exc
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('BOM source contains a linked file or directory.')
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError('Saved BOM source is missing.') from exc
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError('BOM source must be a saved regular file in the selected project.')
    return resolved


def _flag(node: Node, name: str, default: bool) -> bool:
    item = node.one(name)
    if item is None:
        return default
    if item.val() not in ('yes', 'no'):
        raise ValueError(f'Unsupported saved {name} flag.')
    return item.val() == 'yes'


def _flags(node: Node) -> dict[str, bool]:
    return {name: _flag(node, name, value) for name, value in _DEFAULT_FLAGS.items()}


def _instance(node: Node, path: str, project: str) -> Node | None:
    instances = node.one('instances')
    if instances is None:
        return None
    matched = []
    projects = instances.nodes('project')
    preferred = [item for item in projects if item.val() == project]
    for item in preferred or projects:
        for candidate in item.nodes('path'):
            if '/' + '/'.join(candidate.val().split('/')).strip('/') == path:
                matched.append(candidate)
    if len(matched) > 1:
        raise ValueError('Ambiguous saved schematic instance path.')
    if not matched:
        raise ValueError('Schematic symbol or sheet has no matching saved instance path.')
    return matched[0]


def _variant_deltas(instance: Node | None, version: int) -> dict[str, dict]:
    result = {}
    if instance is None:
        return result
    for item in instance.nodes('variant'):
        name = item.get('name')
        if not name or name.casefold() in {key.casefold() for key in result}:
            raise ValueError('Saved variant names must be nonempty and unique.')
        if any(child.tag not in ('name', 'field', *_FLAGS) for child in item.children):
            raise ValueError('Unsupported saved variant attribute.')
        fields = {}
        for field in item.nodes('field'):
            if any(child.tag not in ('name', 'value') for child in field.children):
                raise ValueError('Unsupported saved variant field attribute.')
            key = field.get('name')
            if not key or key in fields:
                raise ValueError('Duplicate or unnamed saved variant field.')
            fields[key] = field.get('value')
        flags = {}
        for key in _FLAGS:
            if item.one(key):
                flags[key] = _flag(item, key, _DEFAULT_FLAGS[key])
                # KiCad 10's old differential representation inverted this bit.
                if key == 'in_bom' and version < 20260306:
                    flags[key] = not flags[key]
        result[name] = {'fields': fields, 'flags': flags}
    return result


def load_bom(path: str | Path, root: str | Path | None = None) -> dict:
    """Return an exact saved-field snapshot; ``root`` sets repository-relative IDs."""
    given = Path(path).expanduser().absolute()
    if given.is_symlink() or given.parent.is_symlink():
        raise ValueError('Choose a saved KiCad file, not a linked file or directory.')
    selected = given.resolve(strict=True)
    if selected.suffix.lower() not in ('.kicad_sch', '.kicad_pcb'):
        raise ValueError('Choose a saved .kicad_sch or .kicad_pcb file.')
    project_dir = selected.parent
    base = Path(root).expanduser().absolute() if root is not None else project_dir
    if base.is_symlink():
        raise ValueError('BOM repository root cannot be a linked directory.')
    base = base.resolve(strict=True)
    _safe(selected, base)
    origin = selected.relative_to(base).as_posix()
    hashes: dict[str, str] = {}
    total = 0
    trees: dict[Path, Node] = {}

    def read(source: Path, limit: int = MAX_FILE_BYTES) -> bytes:
        nonlocal total
        source = _safe(source, base)
        name = source.relative_to(base).as_posix()
        if name in hashes:
            return source.read_bytes()
        if len(hashes) >= MAX_FILES or source.stat().st_size > limit:
            raise ValueError('Saved BOM source exceeds its file or catalog limit.')
        data = source.read_bytes()
        total += len(data)
        if len(data) > limit or total > MAX_TOTAL_BYTES:
            raise ValueError('Saved BOM source exceeds its bounded read limit.')
        digest = hashlib.sha256(data).hexdigest()
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Saved BOM source changed during read.')
        hashes[name] = digest
        return data

    project = selected.with_suffix('.kicad_pro')
    project_data = {}
    if project.exists() or project.is_symlink():
        try:
            project_data = json.loads(read(project, 1024 * 1024).decode('utf-8-sig'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Saved KiCad project settings are invalid.') from exc
        if not isinstance(project_data, dict):
            raise ValueError('Saved KiCad project settings must be an object.')
    schematic_settings = project_data.get('schematic', {})
    if not isinstance(schematic_settings, dict):
        raise ValueError('Saved project schematic settings are invalid.')
    declared = schematic_settings.get('variants', [])
    if not isinstance(declared, list):
        raise ValueError('Saved project variant list is invalid.')
    descriptions = {}
    for item in declared:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name']:
            raise ValueError('Saved project variant definition is invalid.')
        name = item['name']
        if name.casefold() in {key.casefold() for key in descriptions}:
            raise ValueError('Duplicate saved project variant name.')
        descriptions[name] = item.get('description', '') if isinstance(item.get('description', ''), str) else ''
    rows = []
    native_names = set()

    def tree(source: Path) -> Node:
        source = _safe(source, base)
        if source not in trees:
            try:
                parsed = parse(read(source).decode('utf-8-sig'))
            except UnicodeError as exc:
                raise ValueError('Saved KiCad source is not UTF-8.') from exc
            if parsed.tag != 'kicad_sch':
                raise ValueError('A saved schematic child has an unsupported format.')
            trees[source] = parsed
        return trees[source]

    if selected.suffix.lower() == '.kicad_pcb':
        try:
            board = parse(read(selected).decode('utf-8-sig'))
        except UnicodeError as exc:
            raise ValueError('Saved KiCad board is not UTF-8.') from exc
        if board.tag != 'kicad_pcb':
            raise ValueError('Selected file is not a saved KiCad PCB.')
        for footprint in board.nodes('footprint'):
            props = {key: value[0] for key, value in properties(footprint).items()}
            ref = props.get('Reference', '')
            uid = footprint.get('uuid')
            if not uid or not ref:
                raise ValueError('Saved PCB footprint needs UUID and Reference.')
            props.setdefault('Footprint', footprint.val())
            attributes = footprint.one('attr')
            attr = {atom.value for atom in attributes.atoms[1:]} if attributes else set()
            flags = dict(_DEFAULT_FLAGS, dnp='dnp' in attr,
                         in_bom='exclude_from_bom' not in attr,
                         in_pos_files='exclude_from_pos_files' not in attr)
            rows.append(dict(id='bom:' + hashlib.sha256(('pcb:' + uid).encode()).hexdigest(),
                             reference=ref, fields=props, flags=flags,
                             sheet_path='', source_file=origin, origin_file=origin,
                             member_uuids=[uid], variant_overrides={}, variant_context=[]))
            if len(rows) > MAX_ROWS:
                raise ValueError('Saved BOM exceeds its row limit.')
    else:
        source_root = selected.parent
        project_name = selected.stem
        root_tree = tree(selected)
        root_uuid = root_tree.get('uuid')
        if not root_uuid:
            raise ValueError('Saved root schematic has no UUID.')

        def walk(source: Path, instance_path: str, human_path: str,
                 ancestors: list[dict], chain: tuple[Path, ...]):
            source = _safe(source, base)
            if source in chain or len(chain) >= MAX_DEPTH:
                raise ValueError('Schematic hierarchy is circular or too deep.')
            document = tree(source)
            try:
                version = int(document.get('version', '0'))
            except ValueError as exc:
                raise ValueError('Saved schematic version is invalid.') from exc
            local = {}
            for symbol in document.nodes('symbol'):
                if not symbol.one('lib_id'):
                    continue
                props = {key: value[0] for key, value in properties(symbol).items()}
                instance = _instance(symbol, instance_path, project_name)
                ref = instance.get('reference') if instance else props.get('Reference', '')
                if ref.startswith('#'):
                    continue
                uid = symbol.get('uuid')
                if not ref or not uid:
                    raise ValueError('Saved schematic symbol needs UUID and Reference.')
                props['Reference'] = ref
                flags = _flags(symbol)
                overrides = _variant_deltas(instance, version)
                native_names.update(overrides)
                unit_text = instance.get('unit', symbol.get('unit', '1')) if instance else symbol.get('unit', '1')
                try:
                    unit = int(unit_text)
                except ValueError as exc:
                    raise ValueError('Saved schematic symbol unit is invalid.') from exc
                key = ref
                if key in local:
                    row, units, lib_id = local[key]
                    if (unit in units or lib_id != symbol.get('lib_id') or
                            row['fields'] != props or row['flags'] != flags or
                            row['variant_overrides'] != overrides):
                        raise ValueError('Duplicate reference or conflicting multi-unit fields in saved schematic.')
                    units.add(unit)
                    row['member_uuids'].append(uid)
                    row['member_uuids'].sort()
                    row['id'] = 'bom:' + hashlib.sha256(
                        ('sch:' + instance_path + ':' + row['member_uuids'][0]).encode()).hexdigest()
                else:
                    row = dict(id='bom:' + hashlib.sha256(
                        ('sch:' + instance_path + ':' + uid).encode()).hexdigest(), reference=ref,
                               fields=props, flags=flags, sheet_path=human_path,
                               source_file=source.relative_to(base).as_posix(),
                               origin_file=origin, member_uuids=[uid],
                               variant_overrides=overrides, variant_context=list(ancestors))
                    local[key] = row, {unit}, symbol.get('lib_id')
                    rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise ValueError('Saved BOM exceeds its row limit.')
            for sheet in document.nodes('sheet'):
                props = {key: value[0] for key, value in properties(sheet).items()}
                filename = props.get('Sheetfile', props.get('Sheet file', ''))
                name = props.get('Sheetname', props.get('Sheet name', ''))
                uid = sheet.get('uuid')
                if not filename or not uid or '${' in filename or filename.startswith('kicad-embed:'):
                    raise ValueError('Saved schematic sheet path is unresolved or unsupported.')
                relative = Path(filename.replace('\\', '/'))
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Saved schematic child path cannot traverse the project.')
                child = source.parent / relative
                if not child.resolve().is_relative_to(source_root):
                    raise ValueError('Saved schematic child is outside the selected project directory.')
                _safe(child, base)
                instance = _instance(sheet, instance_path, project_name)
                overrides = _variant_deltas(instance, version)
                native_names.update(overrides)
                context = dict(sheet=name, path=instance_path + '/' + uid,
                               fields=props, flags=_flags(sheet), variant_overrides=overrides)
                walk(child, instance_path + '/' + uid, human_path + name + '/',
                     ancestors + [context], chain + (source,))

        walk(selected, '/' + root_uuid, '/', [], ())
    # Exact source hashes remain useful only while every file still has its read bytes.
    for name, expected in hashes.items():
        if hashlib.sha256(_safe(base / name, base).read_bytes()).hexdigest() != expected:
            raise ValueError('Saved BOM source changed during extraction.')
    seen = defaultdict(list)
    for row in rows:
        seen[row['reference']].append(row)
    for members in seen.values():
        for row in members:
            row['duplicate_reference'] = len(members) > 1
    rows.sort(key=lambda row: (row['reference'].casefold(), row['sheet_path'], row['id']))
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Saved BOM object identities are ambiguous.')
    keys = {key for row in rows for key in row['fields']}
    columns = [name for name in ('Reference', 'Value', 'Footprint') if name in keys]
    columns += sorted(keys - set(columns), key=str.casefold)
    names = list(descriptions)
    names += sorted((name for name in native_names if name.casefold() not in
                     {item.casefold() for item in names}), key=str.casefold)
    variants = ['<Default>', *names]
    for row in rows:
        row['available_variants'] = variants
    inventory = {row['id']: dict(reference=row['reference'],
                                  fields=sorted(row['fields'], key=str.casefold),
                                  source_file=row['source_file']) for row in rows}
    return dict(kind='pcb' if selected.suffix.lower() == '.kicad_pcb' else 'schematic',
                origin_file=origin, columns=columns, rows=rows, variants=variants,
                variant_descriptions=descriptions, source_hashes=dict(sorted(hashes.items())),
                inventory=inventory)


def bom_anchor(scope: dict, row: dict, source_hashes: dict[str, str], *, field: str | None = None,
               variant: str | None = None) -> dict:
    """Create location context only for the originating design file's scope."""
    if scope.get('file') != row.get('origin_file'):
        raise ValueError('BOM row belongs to another saved design file.')
    if not isinstance(row.get('id'), str) or not re.fullmatch(r'bom:[0-9a-f]{64}', row['id']) or not isinstance(row.get('reference'), str):
        raise ValueError('BOM row has no stable object identity.')
    if not isinstance(source_hashes, dict) or not 1 <= len(source_hashes) <= MAX_FILES or any(
            not isinstance(name, str) or not name or Path(name).is_absolute() or '\\' in name or
            '..' in Path(name).parts or
            not isinstance(digest, str) or len(digest) != 64 or
            any(char not in '0123456789abcdef' for char in digest)
            for name, digest in source_hashes.items()):
        raise ValueError('BOM source hashes are missing or invalid.')
    if row['origin_file'] not in source_hashes or row['source_file'] not in source_hashes:
        raise ValueError('BOM row source is absent from the saved source inventory.')
    context = dict(type='bom', rowId=row['id'], sourceFiles=dict(sorted(source_hashes.items())))
    result = dict(scope, kind='bom', objectId=row['id'], reference=row['reference'], context=context)
    if field is not None:
        if field not in row.get('fields', {}):
            raise ValueError('BOM field is absent from this saved row.')
        result['kind'] = 'bom-field'
        context['field'] = field
    if variant is not None:
        if variant != '*' and variant not in row.get('available_variants', []):
            raise ValueError('BOM variant is not explicitly available for this project.')
        result['variant'] = variant
    return result
