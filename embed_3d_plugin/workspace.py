"""One component matrix and one preview/apply pipeline for all three asset types.

No wx or pcbnew imports. Saved designs are never overwritten. The native bridge
supplies normalized library footprints; all selection/merge/IO is testable here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from . import __version__
from .codec import Codec, sha256
from .core import PREFIX, Planner, embedded_entries, MAX_JOB_BYTES
from .paths import Resolver
from .sexpr import parse, patch, quote, semantic
from . import board_package as bp
from . import symbols as sy
from .unbundle import extract_pcb, relink_pcb, uri_references, prune_models
from .portability_io import (DesignChange, Extraction, read_bytes, read_text,
    file_reference, add_table_entry, design_sidecars, rebase_library_tables,
    publish_design, publish_files, load_extraction, verify_source, checked_relative,
    saved_project_variables, MANIFEST as EXTRACTION_MANIFEST)

TYPES = ('symbols', 'footprints', 'models')
ARCHIVE = 'WayriCAD_Embed3D_components.json'
ARCHIVE_FORMAT = 'embed_3d_plugin-component-archive-v1'
WORKSPACE_MANIFEST = 'WayriCAD Embed3D-workspace.json'
WORKSPACE_FORMAT = 'embed_3d_plugin-workspace-extraction-v1'


def _prop(node, text, name, default=''):
    value = sy.property_value(node, text, name)
    if value is not None: return value.value(text)
    # Footprint properties saved by older KiCad may still use fp_text.
    for item in node.nodes(text, 'fp_text'):
        if item.arg().value(text).lower() == name.lower(): return item.arg(2).value(text)
    return default


def natural(value):
    return tuple((1, int(s)) if s.isdigit() else (0, s.casefold()) for s in re.split(r'(\d+)', value))


@dataclass
class Component:
    key: str
    reference: str
    value: str
    board_uuid: str | None = None
    symbol_instances: list[tuple[str, str]] = field(default_factory=list)
    footprint_id: str = ''
    symbol_ids: list[str] = field(default_factory=list)
    models: list[dict] = field(default_factory=list)
    status: str = ''
    notes: list[str] = field(default_factory=list)
    checked: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(TYPES, False))

    def available(self, kind):
        if kind == 'symbols': return bool(self.symbol_instances)
        if kind == 'footprints': return self.board_uuid is not None
        if kind == 'models': return bool(self.models)
        raise ValueError('Unknown asset type: '+kind)

    def detail(self):
        out = [self.reference+'  ·  '+self.value,
               'Footprint: '+(self.footprint_id or 'Not placed on this PCB'),
               'Symbol: '+(', '.join(self.symbol_ids) or 'No matching saved schematic symbol')]
        for sheet, uid in self.symbol_instances: out.append('Schematic: '+sheet+'  /  '+uid)
        out.extend(self.notes)
        for m in self.models:
            out += ['', '3D: '+m['reference'], m['status']+': '+m['detail'], m.get('settings', '')]
        return '\n'.join(out)


@dataclass
class Inventory:
    pcb: Path | None
    schematic: Path | None
    rows: list[Component]
    hashes: dict[str, str]
    warnings: list[str]
    follow: bool = True

    def select_all(self, kind=None, value=True):
        kinds = TYPES if kind is None else (kind,)
        for row in self.rows:
            for k in kinds: row.checked[k] = bool(value and row.available(k))

    def state(self, kind=None):
        kinds = TYPES if kind is None else (kind,)
        values = [r.checked[k] for r in self.rows for k in kinds if r.available(k)]
        return 'none' if not values or not any(values) else 'all' if all(values) else 'mixed'

    def selection(self, all_assets=False):
        result = Selection()
        for row in self.rows:
            for k in TYPES:
                if not row.available(k) or not (all_assets or row.checked[k]): continue
                if k == 'symbols':
                    for sheet, uid in row.symbol_instances: result.symbols.setdefault(sheet, set()).add(uid)
                elif k == 'footprints': result.footprints.add(row.board_uuid)
                elif k == 'models': result.models.add(row.board_uuid)
        return result

    def assert_fresh(self):
        for filename, digest in self.hashes.items():
            if sha256(read_bytes(Path(filename))) != digest:
                raise ValueError('Saved design changed after Scan. Scan again: '+filename)


@dataclass
class Selection:
    footprints: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    symbols: dict[str, set[str]] = field(default_factory=dict)

    def counts(self):
        return {'symbols': sum(len(v) for v in self.symbols.values()),
                'footprints': len(self.footprints), 'models': len(self.models)}

    def any(self): return any(self.counts().values())

    def serial(self):
        return {'footprints': sorted(self.footprints), 'models': sorted(self.models),
                'symbols': {k: sorted(v) for k, v in sorted(self.symbols.items())}}


def _model_inventory(raw, pool, resolver, context):
    result = []; local = embedded_entries(raw)
    for node in parse(raw).nodes(raw, 'model'):
        ref = node.arg().value(raw)
        if ref.startswith(PREFIX):
            entry = local.get(ref[len(PREFIX):])
            if not entry or not entry.encoded: entry = pool.get(ref[len(PREFIX):])
            status = 'Embedded' if entry and entry.encoded else 'Missing payload'
            detail = 'Stored in the design; byte integrity is checked during the operation.' if status == 'Embedded' else 'The linked payload is not present in the design.'
        else:
            try:
                path = resolver.resolve(ref, context)
                status, detail = 'External', str(path)
            except (ValueError, OSError) as exc:
                status, detail = 'Needs attention', str(exc)
        result.append({'reference': ref, 'status': status, 'detail': detail,
                       'settings': raw[node.arg().end:node.end-1].strip()})
    return result


def scan_design(pcb=None, schematic=None, *, follow=True, resolver=None, cancelled=None):
    """Match by native symbol UUID first; ambiguous/ref-only matches stay separate.

    A multi-unit component in one sheet gets one checkbox controlling its units.
    Shared sheet files have one row set: editing a shared file affects all its uses.
    """
    pcb = Path(pcb).absolute() if pcb else None
    schematic = Path(schematic).absolute() if schematic else None
    if not pcb and not schematic: raise ValueError('Select a saved PCB, a root schematic, or both.')
    if pcb and schematic and pcb.parent != schematic.parent:
        raise ValueError('The PCB and root schematic must be in the same project folder. They can also be processed separately.')
    project = (pcb or schematic).parent
    resolver = resolver or Resolver(project, saved_project_variables(pcb or schematic))
    hashes, warnings, groups = {}, [], {}
    if schematic:
        sheets = sy.load_hierarchy(schematic, follow, cancelled=cancelled)
        child_counts = {}
        for sheet in sheets:
            hashes[str(sheet.path)] = sha256(sheet.text.encode('utf-8'))
            for _, target in sheet.children: child_counts[target] = child_counts.get(target, 0)+1
            cache = sy.cache_symbols(sheet.text)
            for item in sy.placed_symbols(sheet.text):
                n = item['node']; ref = _prop(n, sheet.text, 'Reference', item['uuid'][:8])
                value = _prop(n, sheet.text, 'Value')
                unit = n.one(sheet.text, 'unit')
                group_key = (sheet.relative, ref if ref and '?' not in ref else item['uuid'])
                group = groups.setdefault(group_key, {'ref': ref, 'value': value, 'instances': [], 'ids': set(), 'notes': [], 'units': [], 'parts': []})
                group['instances'].append((sheet.relative, item['uuid'])); group['ids'].add(item['lib_id'])
                group['units'].append(unit.arg().value(sheet.text) if unit else '1')
                group['parts'].append((item['uuid'], item['lib_id'], value, group['units'][-1]))
                if item['key'] not in cache: group['notes'].append('Missing native symbol cache; repair this symbol in KiCad before embedding/relinking.')
        # Duplicate references or conflicting definitions must not collapse
        # physically distinct components into one checkbox. Split by UUID.
        expanded = {}
        for key, group in groups.items():
            ambiguous = len(set(group['units'])) != len(group['units']) or len(group['ids']) > 1
            if ambiguous:
                for uid, libid, value, unit in group['parts']:
                    expanded[(key[0], key[1]+'@'+uid)] = {
                        'ref':group['ref'], 'value':value, 'instances':[(key[0],uid)],
                        'ids':{libid}, 'notes':group['notes']+['Duplicate reference/definition: kept as a separate UUID-selected component.'],
                        'units':[unit], 'ambiguous':False}
            else:
                group['ambiguous'] = False; expanded[key] = group
        groups = expanded
        if any(v > 1 for v in child_counts.values()):
            warnings.append('A child sheet file is reused. Its symbol checkboxes apply to that saved file and therefore to every use of that file.')
    by_uid, by_ref = {}, {}
    for key, g in groups.items():
        for _, uid in g['instances']: by_uid.setdefault(uid, []).append(key)
        by_ref.setdefault(g['ref'], []).append(key)
    board_rows, used_groups = [], set()
    if pcb:
        raw = read_bytes(pcb); text = raw.decode('utf-8'); root = parse(text)
        if root.head(text) != 'kicad_pcb': raise ValueError('Choose a .kicad_pcb file.')
        hashes[str(pcb)] = sha256(raw)
        pool = embedded_entries(text); libraries = resolver.footprint_libraries(project)
        fps = root.nodes(text, 'footprint'); counts = {}; seen_uuids = set()
        for fp in fps:
            ref = _prop(fp, text, 'Reference'); counts[ref] = counts.get(ref, 0)+1
        for fp in fps:
            if cancelled and cancelled(): raise InterruptedError('Scan cancelled')
            uid = bp.uuid_of(text, fp)
            if uid in seen_uuids: raise ValueError('Duplicate PCB footprint UUID: '+uid)
            seen_uuids.add(uid)
            ref = _prop(fp, text, 'Reference', uid[:8]); fpid = fp.arg().value(text)
            row = Component('pcb:'+uid, ref, _prop(fp, text, 'Value'), uid, footprint_id=fpid)
            path = fp.one(text, 'path'); path_id = path.arg().value(text).rstrip('/').rsplit('/', 1)[-1] if path else ''
            candidates = by_uid.get(path_id, []) if path_id else (by_ref.get(ref, []) if counts.get(ref) == 1 else [])
            candidates = [k for k in set(candidates) if not groups[k]['ambiguous']]
            if len(candidates) == 1 and candidates[0] not in used_groups:
                k = candidates[0]; g = groups[k]; used_groups.add(k)
                row.symbol_instances = list(g['instances']); row.symbol_ids = sorted(g['ids']); row.notes += g['notes']
                if not path_id: row.notes.append('Matched by a unique reference; this board footprint has no schematic UUID path.')
            elif schematic:
                row.notes.append('No unambiguous saved schematic match. Its symbol, when present, has a separate row below.')
            context = libraries.get(fpid.split(':', 1)[0]) if ':' in fpid else project
            row.models = _model_inventory(fp.raw(text), pool, resolver, context)
            blocked = sum(m['status'] in ('Needs attention', 'Missing payload') for m in row.models)
            embedded = sum(m['status'] == 'Embedded' for m in row.models)
            row.status = f'{blocked} model link(s) need attention' if blocked else (f'{embedded}/{len(row.models)} models embedded' if row.models else 'No 3D model')
            board_rows.append(row)
    for key, group in groups.items():
        if key in used_groups: continue
        row = Component('sch:'+key[0]+':'+group['instances'][0][1], group['ref'], group['value'],
                        symbol_instances=list(group['instances']), symbol_ids=sorted(group['ids']),
                        status='Schematic only · native symbol cache', notes=list(group['notes']))
        board_rows.append(row)
    board_rows.sort(key=lambda r: (natural(r.reference), r.key))
    result = Inventory(pcb, schematic, board_rows, hashes, warnings, follow)
    result.select_all()
    if schematic:
        warnings.append('Native lib_symbols caches stay inside schematics. Embedding adds reusable symbol-library archives.')
        if not follow: warnings.append('Child sheets are not included; this output is not a complete hierarchy.')
    return result


def _rebase_models(raw, source, output, mode, resolver, context=None):
    changes = []
    for model in parse(raw).nodes(raw, 'model'):
        value = model.arg().value(raw)
        if value.startswith(PREFIX): continue
        target = None
        if value.startswith('${KIPRJMOD}/'): target = source.parent/value[len('${KIPRJMOD}/'):]
        elif value.startswith('$(KIPRJMOD)/'): target = source.parent/value[len('$(KIPRJMOD)/'):]
        elif '$' not in value and not Path(value).is_absolute():
            try: target = resolver.resolve(value, context)
            except (ValueError, OSError): pass
        if target:
            changes.append((model.arg().start, model.arg().end, quote(file_reference(target, output, mode))))
    return patch(raw, changes)


def read_component_archive(text):
    pool = embedded_entries(text)
    if ARCHIVE not in pool: return {}
    reader = bp.PayloadReader(); meta = json.loads(reader.read(pool[ARCHIVE]))
    if not isinstance(meta, dict) or meta.get('format') != ARCHIVE_FORMAT:
        raise ValueError('Reserved component archive name belongs to another attachment.')
    records = meta.get('footprints', {})
    if not isinstance(records, dict): raise ValueError('Invalid component archive')
    for uid, record in records.items():
        name = record['embedded_file']; bp.safe_name(record['name'])
        if name not in pool: raise ValueError('Missing archived footprint: '+name)
        if sha256(reader.read(pool[name])) != record['sha256']: raise ValueError('Corrupt footprint archive: '+name)
    return records


def archived_normalized(source, selected):
    """Recover our selective archive first, or the earlier all-board package."""
    text = read_text(source); pool = embedded_entries(text); reader = bp.PayloadReader(); result = {}
    records = read_component_archive(text)
    for uid in selected:
        record = records.get(uid)
        if record:
            raw = reader.read(pool[record['embedded_file']]).decode('utf-8')
            local = embedded_entries(raw)
            for ref in bp.model_refs(raw):
                if ref.startswith(PREFIX):
                    name = ref[len(PREFIX):]
                    entry = local.get(name)
                    if not entry or not entry.encoded: entry = pool.get(name)
                    if not entry: raise ValueError('Missing archived model: '+name)
                    reader.read(entry); local[name] = entry
            result[uid] = (record['name'], bp.replace_entries(raw, local))
    missing = set(selected)-set(result)
    if missing and bp.MANIFEST in pool:
        package = bp.recover(text)
        defs = {d['key']: d['name'] for d in package.manifest['definitions']}
        for item in package.manifest['instances']:
            if item['uuid'] in missing:
                name = defs[item['definition_key']]
                # Per-instance names avoid collisions when a supplied definition was shared.
                newname = bp.safe_name('F_'+item['uuid'].replace('-', '')+'_'+bp.slug(name, 20))
                raw = package.library_files[name+'.kicad_mod'].decode('utf-8')
                arg = parse(raw).arg(); raw = patch(raw, [(arg.start,arg.end,quote(newname))])
                result[item['uuid']] = (newname,raw)
    missing = set(selected)-set(result)
    if missing: raise ValueError('No archived definition for '+', '.join(sorted(missing)[:3])+'. Choose As placed to normalize it with KiCad.')
    return result, sha256(text.encode('utf-8'))


def _fresh_nickname(base, table, uri, kind):
    bp.safe_name(base)
    for i in range(1, 1001):
        candidate = base if i == 1 else base+'_'+str(i)
        try: return candidate, add_table_entry(table, kind, candidate, uri.replace('{nickname}', candidate))
        except ValueError as exc:
            if 'nickname already maps' not in str(exc): raise
    raise ValueError('Cannot allocate a project library nickname.')


def embed_board(source, output, selection, *, normalized=None, normalized_hash=None,
                resolver=None, local_links=True, nickname='WayriCAD_Embed3D_Footprints',
                path_mode='relative', cancelled=None):
    source, output = Path(source).absolute(), Path(output).absolute()
    text = read_text(source); root = parse(text); pool = embedded_entries(text); codec = Codec(); reader = bp.PayloadReader(codec)
    if normalized_hash and sha256(text.encode('utf-8')) != normalized_hash: raise ValueError('PCB changed after native normalization.')
    resolver = resolver or Resolver(source.parent, saved_project_variables(source))
    libraries = resolver.footprint_libraries(source.parent); planner = Planner(resolver)
    nodes = root.nodes(text, 'footprint')
    fps = {bp.uuid_of(text, fp): fp for fp in nodes}
    if len(fps) != len(nodes): raise ValueError('Duplicate PCB footprint UUID')
    if not selection.footprints | selection.models <= set(fps): raise ValueError('Selected PCB UUID is missing.')
    if selection.footprints and normalized is None: raise ValueError('As-placed footprint normalization requires KiCad. Use the plugin in the PCB Editor.')
    sidecars = design_sidecars(source); outputs = rebase_library_tables(sidecars, source.parent, output, path_mode)
    inputs = {str(source): sha256(text.encode('utf-8')), **{str(source.parent/n): sha256(v) for n,v in sidecars.items()}}
    archive = read_component_archive(text); entries = dict(archive); edits = []; newdefs = {}; model_count = 0
    if selection.footprints and local_links:
        table = outputs.get('fp-lib-table', b'').decode('utf-8')
        nickname, table = _fresh_nickname(nickname, table, '${KIPRJMOD}/{nickname}.pretty', 'footprints')
        outputs['fp-lib-table'] = table.encode('utf-8')

    def add(entry):
        old = pool.get(entry.name)
        if old and old.encoded and reader.read(old) != reader.read(entry): raise ValueError('Embedded payload name collision: '+entry.name)
        pool[entry.name] = entry

    for uid, fp in fps.items():
        if cancelled and cancelled(): raise InterruptedError('Embedding cancelled')
        raw = fp.raw(text); original = raw; fpid = fp.arg().value(text)
        context = libraries.get(fpid.split(':',1)[0]) if ':' in fpid else source.parent
        if uid in selection.models:
            plan = planner.scan(raw, name=_prop(fp,text,'Reference',uid), source_dir=context, pool=pool)
            bad = [r for r in plan.rows if r.status != 'Embedded' and not r.ready]
            if bad: raise ValueError(plan.name+': '+bad[0].reference+'\n'+bad[0].detail)
            for row in plan.rows:
                row.checked = row.ready
                if row.resolved and row.digest: inputs[str(row.resolved)] = row.digest
            raw = plan.build(); local = embedded_entries(raw)
            # Pool actual model payloads at PCB level, leaving non-model resources local.
            for ref in bp.model_refs(raw):
                if not ref.startswith(PREFIX): raise ValueError('Selected model stayed external: '+ref)
                name = ref[len(PREFIX):]; entry = local.get(name)
                if not entry or not entry.encoded: entry = pool.get(name)
                if not entry: raise ValueError('Embedded payload is missing: '+ref)
                reader.read(entry); add(entry); local.pop(name, None); model_count += 1
            raw = bp.replace_entries(raw, local)
        raw = _rebase_models(raw, source, output, path_mode, resolver, context)
        if uid in selection.footprints:
            if uid not in normalized: raise ValueError('Missing normalized footprint: '+uid)
            name, definition = normalized[uid]; bp.safe_name(name)
            if name in newdefs: raise ValueError('Normalized footprint names collide.')
            # Normalization occurs on the saved source; substitute only the final model paths.
            models = parse(definition).nodes(definition, 'model'); refs = bp.model_refs(raw)
            if len(models) != len(refs) or bp.model_settings(definition) != bp.model_settings(original):
                raise ValueError('Normalized definition differs from saved PCB model settings: '+name)
            changes = [(n.arg().start,n.arg().end,quote(ref)) for n, ref in zip(models, refs)]
            definition = patch(definition, changes); own = embedded_entries(definition)
            for ref in refs:
                if ref.startswith(PREFIX):
                    key = ref[len(PREFIX):]; entry = pool.get(key) or own.get(key)
                    if not entry or not entry.encoded: raise ValueError('Missing model bytes for library footprint '+name)
                    reader.read(entry); add(entry); own.pop(key, None)
            definition = bp.replace_entries(definition, own)
            data = definition.encode('utf-8'); filename = 'WayriCAD_Embed3D_fp__'+sha256(data)+'.kicad_mod'
            add(bp.entry_for_bytes(filename, data, codec))
            target = nickname+':'+name if local_links else fpid
            entries[uid] = {'name':name, 'original_fpid':fpid, 'new_fpid':target,
                            'embedded_file':filename, 'sha256':sha256(data)}
            if local_links:
                arg = parse(raw).arg(); raw = patch(raw, [(arg.start,arg.end,quote(target))])
                # The on-disk library is self-contained even without the board pool.
                hydrated = embedded_entries(definition)
                for ref in refs:
                    if ref.startswith(PREFIX): hydrated[ref[len(PREFIX):]] = pool[ref[len(PREFIX):]]
                newdefs[name] = bp.replace_entries(definition, hydrated).encode('utf-8')
        if bp.model_settings(original) != bp.model_settings(raw): raise ValueError('Model transforms changed')
        edits.append((fp.start,fp.end,raw))
    result = patch(text, edits)
    if selection.footprints:
        meta = {'format':ARCHIVE_FORMAT, 'plugin_version':__version__, 'footprints':entries}
        pool[ARCHIVE] = bp.entry_for_bytes(ARCHIVE,json.dumps(meta,ensure_ascii=False,sort_keys=True).encode('utf-8'),codec)
    result = bp.replace_entries(result,pool)
    if bp._board_fingerprint(text) != bp._board_fingerprint(result): raise ValueError('PCB geometry preservation check failed.')
    outputs[source.name] = result.encode('utf-8')
    for name, data in newdefs.items(): outputs[nickname+'.pretty/'+name+'.kicad_mod'] = data
    report = {'operation':'embed-components','input_sha256':inputs,'footprints_archived':len(selection.footprints),
              'model_entries_embedded':model_count,'local_library_links':bool(selection.footprints and local_links),
              'library':nickname,'warnings':[]}
    if selection.footprints and local_links:
        report['warnings'].append('PCB footprint library IDs change; schematic Footprint assignment fields do not. Review those assignments before updating PCB from schematic.')
    return DesignChange(outputs,{**sidecars,source.name:text.encode('utf-8')},report)



def _prune_component_archives(change, source, selection, assets, extraction=None):
    """Remove only verified checked archives; keep models needed by any survivor."""
    before=read_text(source); after=change.files[Path(source).name].decode('utf-8')
    pool=embedded_entries(after); records=read_component_archive(before)
    if not records: return change
    remaining={u:r for u,r in records.items() if u not in selection.footprints}
    keep={r['embedded_file'] for r in remaining.values()}
    direct=uri_references(after); removed=[]
    for uid,r in records.items():
        name=r['embedded_file']
        if uid in selection.footprints and name not in keep and PREFIX+name not in direct:
            pool.pop(name,None);removed.append(name)
    if selection.footprints:
        if remaining:
            meta={'format':ARCHIVE_FORMAT,'plugin_version':__version__,'footprints':remaining}
            pool[ARCHIVE]=bp.entry_for_bytes(ARCHIVE,json.dumps(meta,ensure_ascii=False,sort_keys=True).encode('utf-8'),Codec())
        elif PREFIX+ARCHIVE not in direct:
            pool.pop(ARCHIVE,None);removed.append(ARCHIVE)
    after=bp.replace_entries(after,pool)
    if selection.models:
        meta=extraction.meta if extraction else load_extraction(assets,source)[0]
        names={m['embedded_name'] for i in meta['instances'] if i['uuid'] in selection.models for m in i['models'] if m['embedded_name']}
        reader=bp.PayloadReader();protected=set()
        for name,entry in pool.items():
            if name.lower().endswith('.kicad_mod'):
                protected |= uri_references(reader.read(entry).decode('utf-8'))
        after=prune_models(after,names,protected)
    if bp._board_fingerprint(before)!=bp._board_fingerprint(after): raise ValueError('Pruning changed PCB geometry')
    change.files[Path(source).name]=after.encode('utf-8')
    change.report['removed_component_archives']=removed
    return change

def _merge_tables(a,b):
    if a == b: return a
    x,y = a.decode('utf-8'),b.decode('utf-8'); rx,ry = parse(x),parse(y)
    if rx.head(x) != ry.head(y): raise ValueError('Library table type conflict')
    existing = {n.one(x,'name').arg().value(x): n.raw(x) for n in rx.nodes(x,'lib')}
    append = []
    for n in ry.nodes(y,'lib'):
        name = n.one(y,'name').arg().value(y)
        if name in existing:
            if semantic(existing[name]) != semantic(n.raw(y)):
                raise ValueError('Combined operations disagree on library nickname '+name+'. Choose distinct nicknames.')
        else: append.append(n.raw(y))
    return patch(x, [(rx.end-1,rx.end-1,'\n'+'\n'.join(append)+'\n')]).encode('utf-8')


def merge_changes(changes):
    files, originals, extras, reports = {}, {}, {}, []
    for change in changes:
        for name, data in change.files.items():
            if name in files and files[name] != data:
                if name in ('fp-lib-table','sym-lib-table'): data = _merge_tables(files[name],data)
                else: raise ValueError('Conflicting combined design output: '+name)
            files[name] = data
        for name,data in change.originals.items():
            if name in originals and originals[name] != data: raise ValueError('Original design paths collide: '+name)
            originals[name] = data
        for folder, content in change.extra_files.items():
            d=extras.setdefault(folder,{})
            for name,data in content.items():
                if name in d and d[name] != data: raise ValueError('External library view conflict: '+name)
                d[name]=data
        reports.append(change.report)
    return DesignChange(files,originals,{'operations':reports},extras)


@dataclass
class Options:
    assets: Path
    output: Path
    path_mode: str = 'relative'
    follow: bool = True
    include_external: bool = False
    local_links: bool = True
    prune: bool = False
    footprint_nickname: str = 'WayriCAD_Embed3D_Footprints'
    symbol_nickname: str = 'WayriCAD_Embed3D_Symbols'
    supplied_symbols: tuple[Path,...] = ()


@dataclass
class WorkspacePlan:
    operation: str
    inventory: Inventory
    selection: Selection
    options: Options
    extractions: dict[str, Extraction] = field(default_factory=dict)
    change: DesignChange | None = None
    manifest: dict | None = None
    warnings: list[str] = field(default_factory=list)
    applied: bool = False
    input_hashes: dict[str,str] = field(default_factory=dict)
    absent_inputs: list[str] = field(default_factory=list)

    def summary(self):
        return {'operation':self.operation, 'selection':self.selection.serial(), 'counts':self.selection.counts(),
                'source_pcb':str(self.inventory.pcb or ''), 'source_schematic':str(self.inventory.schematic or ''),
                'assets':str(self.options.assets), 'output':str(self.options.output) if self.change else None,
                'files_to_extract':sum(len(p.files) for p in self.extractions.values()),
                'design_files':list(self.change.files) if self.change else [], 'warnings':sorted(set(self.warnings))}

    def apply(self, *, validate=None, cancelled=None):
        if self.applied: raise ValueError('This plan has already run. Preview a new operation.')
        self.inventory.assert_fresh()
        for name in self.absent_inputs:
            if Path(name).exists(): raise ValueError('A new project sidecar appeared after preview: '+name+'. Preview again.')
        for name,digest in self.input_hashes.items():
            if sha256(read_bytes(Path(name))) != digest: raise ValueError('Input changed after preview: '+name)
        if self.change:
            if Path(self.options.output).exists() or not Path(self.options.output).parent.is_dir():
                raise ValueError('Select a NEW design folder under an existing parent.')
        # Every extraction uses exclusive publication. The assets can remain if a
        # later native validation fails; source designs are never overwritten.
        for folder, plan in self.extractions.items(): plan.publish(Path(folder),cancelled)
        if self.manifest:
            publish_files(self.options.assets,{WORKSPACE_MANIFEST:(json.dumps(self.manifest,indent=2,ensure_ascii=False)+'\n').encode('utf-8')},cancelled)
        if self.change:
            for folder, files in self.change.extra_files.items(): publish_files(Path(folder),files,cancelled)
            report = self.summary(); report['operations'] = self.change.report['operations']
            # Recheck after extraction but before final staging.
            self.inventory.assert_fresh()
            publish_design(self.options.output,self.change.files,self.change.originals,report,validate,cancelled)
        self.applied = True
        return self.summary()


def _base_schematic(source, output, follow, path_mode):
    sheets = sy.load_hierarchy(source,follow)
    sidecars=design_sidecars(source); files=rebase_library_tables(sidecars,source.parent,output,path_mode); originals=dict(sidecars)
    hashes={str(source.parent/n):sha256(v) for n,v in sidecars.items()}
    for sheet in sheets:
        files[sheet.output]=sy._remap_sheets(sheet,sheet.text,sheets).encode('utf-8')
        originals[sheet.output]=sheet.text.encode('utf-8');hashes[str(sheet.path)]=sha256(originals[sheet.output])
    return DesignChange(files,originals,{'operation':'copy-schematic','input_sha256':hashes,'warnings':[]})


def _roots_for_relink(assets):
    assets=Path(assets)
    path=assets/WORKSPACE_MANIFEST
    if path.is_file():
        meta=json.loads(read_bytes(path,8*1024*1024))
        if meta.get('format')!=WORKSPACE_FORMAT: raise ValueError('Not a WayriCAD Embed3D workspace extraction folder.')
        roots={}
        for kind,record in meta['extractions'].items():
            rel=checked_relative(record['folder']); folder=assets/rel
            if sha256(read_bytes(folder/EXTRACTION_MANIFEST))!=record['manifest_sha256']:
                raise ValueError('Extraction manifest changed: '+str(folder))
            roots[kind]=folder
        return roots
    # Existing 0.3.0 one-domain extractions remain usable through the single button.
    if (assets/EXTRACTION_MANIFEST).is_file():
        meta,_=load_extraction(assets)
        return {meta['kind']:assets}
    raise ValueError('Choose an Unbundle output folder containing a WayriCAD Embed3D extraction manifest. Relink cannot guess arbitrary library matches.')


def prepare_operation(inventory, selection, operation, options, *, normalized=None,
                      normalized_hash=None, resolver=None, cancelled=None):
    if operation not in ('embed','unbundle','relink','unbundle-relink'): raise ValueError('Unknown operation')
    if not selection.any(): raise ValueError('Check at least one component asset.')
    inventory.assert_fresh()
    # Validate independent selections against the scanned identities.
    available=inventory.selection(True)
    if not selection.footprints<=available.footprints or not selection.models<=available.models:
        raise ValueError('Selection contains an unavailable PCB asset.')
    for sheet,uids in selection.symbols.items():
        if not set(uids)<=available.symbols.get(sheet,set()): raise ValueError('Selection contains an unavailable schematic symbol.')
    options.assets=Path(options.assets).absolute(); options.output=Path(options.output).absolute()
    if options.follow != inventory.follow: raise ValueError('Hierarchy option changed. Scan again.')
    if operation!='unbundle':
        if options.output.exists() or not options.output.parent.is_dir(): raise ValueError('Choose a NEW design output folder under an existing parent.')
    if operation in ('unbundle','unbundle-relink'):
        if options.output==options.assets and operation=='unbundle-relink': raise ValueError('Assets and new design must use separate folders.')
        # Keep assets outside the staged design directory for simple, correct references.
        if operation=='unbundle-relink' and options.output in options.assets.parents:
            raise ValueError('Choose an asset folder outside the new design folder (for example, a sibling folder).')
    plan=WorkspacePlan(operation,inventory,selection,options,warnings=list(inventory.warnings))
    changes=[]; roots={}; extracted={}
    if operation in ('unbundle','unbundle-relink'):
        if selection.footprints or selection.models:
            root=options.assets/'pcb'; roots['pcb']=root
            item=extract_pcb(inventory.pcb,root,footprints=bool(selection.footprints),models=bool(selection.models),
                footprint_uuids=selection.footprints,model_uuids=selection.models,
                normalized=normalized,normalized_source_hash=normalized_hash,resolver=resolver,
                include_external=options.include_external,nickname=options.footprint_nickname,cancelled=cancelled)
            plan.extractions[str(root)]=item;extracted['pcb']=item;plan.warnings+=item.warnings
        if selection.symbols:
            root=options.assets/'symbols';roots['schematic']=root
            item=sy.extract_symbols(inventory.schematic,follow=options.follow,nickname=options.symbol_nickname,
                                    selection=selection.symbols,cancelled=cancelled)
            plan.extractions[str(root)]=item;extracted['schematic']=item;plan.warnings+=item.warnings
        records={}
        for kind,item in extracted.items():
            item.finalize(); data=(json.dumps(item.meta,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
            records[kind]={'folder':roots[kind].relative_to(options.assets).as_posix(),'manifest_sha256':sha256(data)}
        plan.manifest={'format':WORKSPACE_FORMAT,'plugin_version':__version__,'extractions':records,'selection':selection.serial()}
    elif operation=='relink':
        roots=_roots_for_relink(options.assets)
        if (options.assets/WORKSPACE_MANIFEST).is_file():
            plan.input_hashes[str(options.assets/WORKSPACE_MANIFEST)]=sha256(read_bytes(options.assets/WORKSPACE_MANIFEST))
    if operation=='embed':
        if inventory.pcb:
            changes.append(embed_board(inventory.pcb,options.output,selection,normalized=normalized,
                normalized_hash=normalized_hash,resolver=resolver,local_links=options.local_links,
                nickname=options.footprint_nickname,path_mode=options.path_mode,cancelled=cancelled))
        if inventory.schematic:
            if selection.symbols:
                # A fresh nickname avoids repointing a user's existing library table row.
                sidecars=rebase_library_tables(design_sidecars(inventory.schematic),inventory.schematic.parent,options.output,options.path_mode)
                nick=options.symbol_nickname
                if options.local_links:
                    nick,_=_fresh_nickname(nick,sidecars.get('sym-lib-table',b'').decode('utf-8'),'${KIPRJMOD}/{nickname}.kicad_sym','symbols')
                changes.append(sy.embed_symbols(inventory.schematic,options.output,follow=options.follow,nickname=nick,
                    local_links=options.local_links,selection=selection.symbols,supplied=options.supplied_symbols,
                    return_plan=True,cancelled=cancelled,path_mode=options.path_mode))
            else: changes.append(_base_schematic(inventory.schematic,options.output,options.follow,options.path_mode))
    if operation in ('relink','unbundle-relink'):
        if inventory.pcb:
            if selection.footprints or selection.models:
                if 'pcb' not in roots: raise ValueError('This asset folder has no PCB extraction. Unbundle the checked PCB assets first.')
                change=relink_pcb(inventory.pcb,roots['pcb'],options.output,link_footprints=bool(selection.footprints),
                    link_models=bool(selection.models),footprint_uuids=selection.footprints,model_uuids=selection.models,
                    path_mode=options.path_mode,prune=options.prune,extraction=extracted.get('pcb'),return_plan=True,cancelled=cancelled)
                if options.prune: change=_prune_component_archives(change,inventory.pcb,selection,roots['pcb'],extracted.get('pcb'))
                changes.append(change)
            else:
                changes.append(embed_board(inventory.pcb,options.output,Selection(),resolver=resolver,path_mode=options.path_mode))
        if inventory.schematic:
            if selection.symbols:
                if 'schematic' not in roots: raise ValueError('This asset folder has no symbol extraction. Unbundle the checked symbols first.')
                changes.append(sy.relink_symbols(inventory.schematic,roots['schematic'],options.output,path_mode=options.path_mode,
                    prune=options.prune,selection=selection.symbols,extraction=extracted.get('schematic'),return_plan=True,cancelled=cancelled))
            else: changes.append(_base_schematic(inventory.schematic,options.output,options.follow,options.path_mode))
    if changes:
        plan.change=merge_changes(changes)
        for report in plan.change.report['operations']:
            plan.input_hashes.update(report.get('input_sha256',{}));plan.warnings+=report.get('warnings',[])
    plan.input_hashes.update(inventory.hashes)
    for source in (inventory.pcb, inventory.schematic):
        if source:
            candidates=[source.with_suffix(ext) for ext in ('.kicad_pro','.kicad_dru')]+[source.parent/n for n in ('fp-lib-table','sym-lib-table')]
            plan.absent_inputs.extend(str(p) for p in candidates if not p.exists())
    if operation=='unbundle-relink':
        plan.warnings.append('Combined operation: assets are extracted, then a new design copy is relinked. If validation fails, extracted assets may remain; original designs are never overwritten.')
    if operation!='unbundle':
        plan.warnings.append('This creates a new saved-design copy, not an in-place edit of open buffers. Save in KiCad before scanning. Unselected external dependencies can remain.')
    return plan
