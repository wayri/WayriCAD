"""Native schematic symbol cache auditing, archives, extraction and relinking.

Modern KiCad schematics already contain lib_symbols. We never remove that cache
or replace a used symbol with a possibly different library version. New library
IDs are written together with matching cache keys; lib_name overrides are handled
explicitly. Pins, units, fields, UUIDs, wires and hierarchy identity are retained.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import re
from .board_package import PayloadReader, entry_for_bytes, replace_entries, safe_name, slug
from .codec import Codec, sha256
from .core import PREFIX, embedded_entries
from .sexpr import Atom, Node, parse, patch, quote, semantic
from .paths import Resolver
from .portability_io import (Extraction, read_bytes, read_text, load_extraction, checked_relative,
    file_reference, add_table_entry, publish_design, design_sidecars, verify_source, rebase_library_tables, saved_project_variables)
from .unbundle import uri_references
from .portability_io import DesignChange, extraction_data, extraction_hashes, available_nickname

LIB_VERSION = 20251024  # KiCad 10 sch_file_versions.h (symbol-library format)
SCH_ARCHIVE = 'WayriCAD_Embed3D_symbols.json'
SCH_FORMAT = 'embed_3d_plugin-symbol-archive-v1'


@dataclass
class Sheet:
    path: Path
    text: str
    relative: str  # relative source path; may have ../ for an external child
    output: str
    children: list[tuple[str, Path]]
    root: Node | None = None


def property_value(node: Node, text: str, name: str):
    for prop in node.nodes(text, 'property'):
        offset = 2 if prop.arg().value(text) == 'private' else 1
        if prop.arg(offset).value(text) == name:
            return prop.arg(offset+1)
    return None


def load_hierarchy(source: Path, follow=True, variables=None, cancelled=None):
    # Use one filesystem identity for the root and every visited sheet. Windows
    # TEMP and KiCad paths may use DOS 8.3 aliases; mixing those with resolved
    # child paths incorrectly relocates even the root into external-sheets/.
    source = Path(source).resolve()
    values = saved_project_variables(source); values.update(variables or {})
    resolver = Resolver(source.parent, values)
    sheets, stack = {}, set()
    total = [0]
    def visit(path):
        if cancelled and cancelled(): raise InterruptedError('Schematic scan cancelled')
        path = path.resolve()
        if path in stack: raise ValueError('Cyclic sheet hierarchy: '+str(path))
        if path in sheets: return
        if len(sheets) >= 512: raise ValueError('Hierarchy exceeds 512 unique sheets')
        raw = read_bytes(path); total[0] += len(raw)
        if total[0] > 512*1024*1024: raise ValueError('Schematic hierarchy exceeds 512 MiB')
        text = raw.decode('utf-8'); root = parse(text)
        if root.head(text) != 'kicad_sch': raise ValueError('Use modern .kicad_sch files: '+str(path))
        version = root.one(text, 'version')
        if version is None or int(version.arg().value(text)) < 20251028:
            raise ValueError('Open and save this schematic and its child sheets in KiCad 10 before symbol portability operations: '+str(path))
        if int(version.arg().value(text)) > 20260306:
            raise ValueError('Schematic format is newer than the reviewed KiCad 10 format; upgrade the plugin before changing it.')
        relative = os.path.relpath(path, source.parent).replace('\\', '/')
        try:
            output = checked_relative(relative).as_posix()
        except ValueError:
            output = 'external-sheets/'+sha256(str(path).encode())[:16]+'_'+slug(path.stem, 40)+'.kicad_sch'
        children = []
        if follow:
            for child in root.nodes(text, 'sheet'):
                filename = property_value(child, text, 'Sheetfile')
                if filename is None: raise ValueError('Hierarchical sheet has no Sheetfile property')
                link = filename.value(text)
                expanded = resolver.expand(link)
                if '$' in expanded or '://' in expanded:
                    raise ValueError('Unresolved or embedded child sheet path: '+link)
                target = Path(expanded.replace('\\', os.sep))
                if not target.is_absolute(): target = path.parent/target
                children.append((link, target.resolve()))
        sheets[path] = Sheet(path, text, relative, output, children, root)
        stack.add(path)
        for _, target in children: visit(target)
        stack.remove(path)
    visit(source)
    return list(sheets.values())


def cache_symbols(text, root=None):
    root = root or parse(text); block = root.one(text, 'lib_symbols'); result = {}
    if block:
        for node in block.nodes(text, 'symbol'):
            key = node.arg().value(text)
            if key in result: raise ValueError('Duplicate cached symbol key: '+key)
            result[key] = node.raw(text)
    return result


def placed_symbols(text, root=None):
    result, seen = [], set()
    for sym in (root or parse(text)).nodes(text, 'symbol'):
        libid = sym.one(text, 'lib_id'); uid = sym.one(text, 'uuid'); override = sym.one(text, 'lib_name')
        if not libid or not uid: raise ValueError('Placed symbol lacks lib_id/UUID')
        value = uid.arg().value(text)
        if value in seen: raise ValueError('Duplicate placed symbol UUID: '+value)
        seen.add(value)
        result.append({'uuid': value, 'lib_id': libid.arg().value(text),
                       'key': override.arg().value(text) if override else libid.arg().value(text),
                       'node': sym})
    return result


def rename_definition(text, name):
    root = parse(text)
    if root.head(text) != 'symbol': raise ValueError('Not a symbol definition')
    # A schematic's cache is normally flattened by KiCad. Do not implement a
    # subtly different inheritance engine for an unusual nonflattened cache.
    if root.one(text, 'extends'):
        raise ValueError('Unflattened symbol inheritance: '+root.arg().value(text)+'. Open/save the schematic in KiCad, or flatten the supplied symbol before cache repair.')
    edits = [(root.arg().start, root.arg().end, quote(name))]
    leaf = name.rsplit(':', 1)[-1]
    for unit in root.nodes(text, 'symbol'):
        old = unit.arg().value(text)
        suffix = re.search(r'_(\d+)_(\d+)$', old)
        if not suffix: raise ValueError('Unrecognized symbol unit name: '+old)
        edits.append((unit.arg().start, unit.arg().end, quote(leaf+suffix.group())))
    return patch(text, edits)


def relink_definition_footprint(text, mapping):
    """Change only an exactly matched default Footprint property's value."""
    if not mapping:
        return text
    root = parse(text)
    value = property_value(root, text, 'Footprint')
    old_id = value.value(text) if value else ''
    if old_id and old_id in mapping:
        return patch(text, [(value.start, value.end, quote(mapping[old_id]))])
    return text


def hydrate_symbol(text, shared, reader):
    entries = embedded_entries(text)
    keys = set(entries) | {v[len(PREFIX):] for v in uri_references(text)}
    for key in keys:
        value = entries.get(key)
        if not value or not value.encoded: value = shared.get(key)
        if not value: raise ValueError('Missing embedded symbol resource: '+key)
        reader.read(value); entries[key] = value
    return replace_entries(text, entries) if entries else text


def library_text(definitions):
    return '(kicad_symbol_lib (version %d) (generator "WayriCAD Embed3D") (generator_version "3.1.1")\n%s\n)\n' % (LIB_VERSION, '\n'.join(definitions))


def _source_meta(source, sheets):
    return {'source': str(Path(source).absolute()),
            'source_files': {s.relative: sha256(s.text.encode('utf-8')) for s in sheets},
            'sheets': [{'relative': s.relative, 'output': s.output,
                        'sha256': sha256(s.text.encode('utf-8'))} for s in sheets]}


def extract_symbols(source: Path, *, follow=True, nickname='UnbundledSymbols',
                    include_unused=False, variables=None, cancelled=None, selection=None, sheets=None,
                    footprint_defaults=None):
    """Extract actual as-drawn definitions. Originals and library IDs are unchanged."""
    safe_name(nickname)
    sheets = sheets if sheets is not None else load_hierarchy(source, follow, variables, cancelled)
    shared, reader = {}, PayloadReader()
    for sheet in sheets:
        for name, entry in embedded_entries(sheet.text, sheet.root).items():
            if name in shared and reader.read(shared[name]) != reader.read(entry):
                raise ValueError('Conflicting schematic embedded resource name: '+name)
            shared[name] = entry
    exports, records, warnings, seen_names = {}, [], [], {}
    for sheet in sheets:
        cache = cache_symbols(sheet.text, sheet.root); placed = placed_symbols(sheet.text, sheet.root)
        chosen = placed if selection is None else [p for p in placed if p['uuid'] in selection.get(sheet.relative, set())]
        unknown = set() if selection is None else set(selection.get(sheet.relative, set())) - {p['uuid'] for p in placed}
        if unknown: raise ValueError('Selected symbol UUID no longer exists in '+sheet.relative)
        keys = set(cache) if include_unused and selection is None else {p['key'] for p in chosen}
        missing = {p['key'] for p in placed} - set(cache)
        if missing: raise ValueError('Missing native symbol cache in '+sheet.path.name+': '+', '.join(sorted(missing))+'. Repair in KiCad before extracting.')
        mapping = {}
        for key in sorted(keys):
            if cancelled and cancelled(): raise InterruptedError('Symbol extraction cancelled')
            raw = relink_definition_footprint(hydrate_symbol(cache[key], shared, reader), footprint_defaults)
            canonical = semantic(rename_definition(raw, 'Canonical'))
            digest = sha256(repr(canonical).encode('utf-8'))
            stem = re.sub(r'__[0-9a-f]{20}$', '', key.rsplit(':',1)[-1])
            name = safe_name(slug(stem, 40)+'__'+digest[:20])
            new = rename_definition(raw, name)
            if name in seen_names and seen_names[name] != canonical: raise ValueError('Symbol naming collision')
            seen_names[name] = canonical
            exports[name] = new
            mapping[key] = name
        records.append({'relative': sheet.relative, 'mapping': mapping,
                        'instances': [{k:v for k,v in p.items() if k != 'node'} for p in chosen],
                        'selected_uuids': None if selection is None else [p['uuid'] for p in chosen]})
    files = {nickname+'.kicad_sym': library_text(exports.values()).encode('utf-8')}
    # Export separately attached symbol libraries too. They are not a lookup backend.
    for key, entry in shared.items():
        if selection is None and key.lower().endswith('.kicad_sym'):
            data = reader.read(entry); lib = parse(data.decode('utf-8'))
            if lib.head(data.decode('utf-8')) != 'kicad_symbol_lib': raise ValueError('Invalid embedded symbol library')
            filename = 'archives/'+slug(Path(key).stem, 24)+'__'+sha256(data)+'.kicad_sym'
            files[filename] = data
    meta = dict(_source_meta(source, sheets), kind='schematic', library=nickname,
                follow=follow, variables=variables or {}, records=records,
                symbol_count=len(exports), include_unused=include_unused)
    warnings.append('KiCad keeps lib_symbols inside every schematic. External relinking does not remove the native symbol cache.')
    if not follow and any(parse(s.text).nodes(s.text, 'sheet') for s in sheets):
        warnings.append('Only the selected sheet is included. Child sheets were not extracted.')
    return Extraction(files, meta, warnings).finalize()


@lru_cache(maxsize=256)
def _symbol_geometry(text):
    return semantic(rename_definition(text, 'Canonical'), ignore_embedding=True)


def verify_symbol_preservation(before, after, before_root=None, after_root=None, footprint_defaults=None):
    before_root, after_root = before_root or parse(before), after_root or parse(after)
    old_cache, new_cache = cache_symbols(before, before_root), cache_symbols(after, after_root)
    old, new = placed_symbols(before, before_root), placed_symbols(after, after_root)
    if [p['uuid'] for p in old] != [p['uuid'] for p in new]: raise ValueError('Placed symbol identity changed')
    def instance_content(raw):
        root = parse(raw)
        removals = [(n.start,n.end,'') for key in ('lib_id','lib_name') for n in root.nodes(raw,key)]
        return semantic(patch(raw,removals))
    expected_geometry, received_geometry = {}, {}
    for a,b in zip(old,new):
        if instance_content(a['node'].raw(before)) != instance_content(b['node'].raw(after)):
            raise ValueError('A symbol field, pin, unit, location or attribute changed: '+a['uuid'])
        if a['key'] not in expected_geometry:
            expected = relink_definition_footprint(old_cache[a['key']], footprint_defaults)
            expected_geometry[a['key']] = _symbol_geometry(expected)
        if b['key'] not in received_geometry:
            received_geometry[b['key']] = _symbol_geometry(new_cache[b['key']])
        if expected_geometry[a['key']] != received_geometry[b['key']]:
            raise ValueError('Symbol geometry changed: '+a['uuid'])
    # Every non-symbol/non-cache/non-embedding span is structurally identical.
    def remainder(text, root):
        edits = [(n.start,n.end,'') for kind in ('lib_symbols','symbol','embedded_files') for n in root.nodes(text,kind)]
        return semantic(patch(text,edits))
    if remainder(before, before_root) != remainder(after, after_root): raise ValueError('Non-symbol schematic content changed')


def relink_sheet(text, mapping, nickname, selected_uuids=None, root=None, footprint_defaults=None):
    root = root or parse(text); block = root.one(text, 'lib_symbols')
    cache = cache_symbols(text, root); edits = []; generated = {}; used = set(); retained = set()
    converted = {}
    for item in placed_symbols(text, root):
        key = item['key']
        if key not in mapping or (selected_uuids is not None and item['uuid'] not in selected_uuids):
            retained.add(key); continue
        name = safe_name(mapping[key]); new_id = nickname+':'+name
        conversion = (key, new_id)
        if conversion not in converted:
            converted[conversion] = rename_definition(relink_definition_footprint(cache[key], footprint_defaults), new_id)
        raw = converted[conversion]
        if new_id in generated and generated[new_id] != raw and semantic(generated[new_id]) != semantic(raw):
            raise ValueError('Conflicting schematic definitions map to one library ID')
        generated[new_id] = raw; used.add(key)
        sym = item['node']; libid = sym.one(text,'lib_id'); arg = libid.arg()
        edits.append((arg.start,arg.end,quote(new_id)))
        override = sym.one(text,'lib_name')
        if override: edits.append((override.start,override.end,''))
    if block:
        # Keep unselected/unused cache entries unchanged unless a generated ID
        # would collide with a different existing definition.
        remaining = {k:relink_definition_footprint(v, footprint_defaults)
                     for k,v in cache.items() if k not in used or k in retained}
        for k,v in generated.items():
            if k in remaining and semantic(remaining[k]) != semantic(v): raise ValueError('Cache-key collision: '+k)
            remaining[k] = v
        new_block = '(lib_symbols\n'+'\n'.join(remaining.values())+'\n)'
        edits.append((block.start,block.end,new_block))
    result = patch(text,edits)
    verify_symbol_preservation(text,result,before_root=root,footprint_defaults=footprint_defaults)
    return result


def _remap_sheets(sheet, text, sheets):
    lookup = {s.path: s.output for s in sheets}
    paths = dict(sheet.children); changes = []
    for child in parse(text).nodes(text,'sheet'):
        arg = property_value(child,text,'Sheetfile')
        if arg is None or arg.value(text) not in paths: continue
        target = paths[arg.value(text)]
        relative = os.path.relpath(lookup[target], str(Path(sheet.output).parent)).replace('\\','/')
        if relative != arg.value(text): changes.append((arg.start,arg.end,quote(relative)))
    return patch(text,changes)


def _prune_symbol_archive(text):
    pool = embedded_entries(text)
    if SCH_ARCHIVE not in pool: return text
    reader = PayloadReader(); meta = json.loads(reader.read(pool[SCH_ARCHIVE]))
    if not isinstance(meta,dict) or meta.get('format') != SCH_FORMAT: raise ValueError('Reserved symbol archive name belongs to another attachment')
    names = [d['embedded_file'] for d in meta['libraries']]
    for item in meta['libraries']:
        entry = pool.get(item['embedded_file'])
        if not entry or sha256(reader.read(entry)) != item['sha256']: raise ValueError('Corrupt symbol archive')
    referenced = uri_references(text)
    for name in names+[SCH_ARCHIVE]:
        if PREFIX+name not in referenced: pool.pop(name,None)
    return replace_entries(text,pool)


def relink_symbols(source: Path, assets: Path, output: Path, *, path_mode='relative',
                   prune=False, apply=False, validate=None, cancelled=None, selection=None,
                   extraction=None, return_plan=False):
    source, assets, output = map(lambda p:Path(p).absolute(),(source,assets,output))
    meta, files = extraction_data(assets,source,extraction)
    if meta['kind'] != 'schematic': raise ValueError('Choose a schematic extraction folder')
    sheets = load_hierarchy(source, meta['follow'], meta.get('variables'), cancelled)
    records = {r['relative']:r for r in meta['records']}
    complete_selection = all(
        {p['uuid'] for p in placed_symbols(s.text)} <=
        (set(selection.get(s.relative, set())) if selection is not None else
         ({p['uuid'] for p in records.get(s.relative, {}).get('instances', [])}))
        for s in sheets)
    sidecars = design_sidecars(source); outputs, originals = rebase_library_tables(sidecars, source.parent, output, path_mode), dict(sidecars)
    target_nickname=available_nickname(sidecars.get('sym-lib-table',b'').decode('utf-8'),meta['library'])
    for sheet in sheets:
        record = records.get(sheet.relative)
        if record is None: raise ValueError('Hierarchy differs from extraction')
        allowed = record.get('selected_uuids')
        if selection is not None:
            wanted = set(selection.get(sheet.relative, set()))
            available = {p['uuid'] for p in record['instances']}
            if not wanted <= available: raise ValueError('Selected symbols were not extracted in '+sheet.relative)
            allowed = wanted
        text = relink_sheet(sheet.text,record['mapping'],target_nickname,allowed)
        if prune and complete_selection: text = _prune_symbol_archive(text)
        outputs[sheet.output] = _remap_sheets(sheet,text,sheets).encode('utf-8')
        originals[sheet.output] = sheet.text.encode('utf-8')
    uri = file_reference(assets/(meta['library']+'.kicad_sym'),output,path_mode)
    outputs['sym-lib-table'] = add_table_entry(outputs.get('sym-lib-table',b'').decode('utf-8'),
                'symbols',target_nickname,uri).encode('utf-8')
    report = {'operation':'relink-symbols','source':str(source),'assets':str(assets),'output':str(output),
              'path_mode':path_mode,'target_library':target_nickname,'remove_archive_attachments':prune,'native_symbol_cache_retained':True,
              'sheets':len(sheets),'symbols':meta['symbol_count'],
              'input_sha256': {**extraction_hashes(assets,files,extraction), **{str(s.path):sha256(s.text.encode('utf-8')) for s in sheets}, **{str(source.parent/n):sha256(v) for n,v in sidecars.items()}},
              'warnings':list(meta.get('warnings',[]))+['No pin/geometry update from library is performed. Native lib_symbols caches are retained.',
                          'PCB footprint IDs and schematic Footprint fields are not rewritten.',
                          'This copies selected schematic sheets and saved sidecars, not every external project dependency.']}
    if prune and not complete_selection:
        report['warnings'].append('Partial symbol selection: shared symbol-library archives were retained for unchecked components.')
    if return_plan: return DesignChange(outputs, originals, report)
    if apply:
        verify_source(meta,source); extraction_data(assets,source,extraction)
        publish_design(output,outputs,originals,report,validate=validate,cancelled=cancelled)
    return report


def embed_symbols(source: Path, output: Path, *, follow=True, nickname='EmbeddedSymbols',
                  supplied=(), local_links=False, variables=None, apply=False,
                  validate=None, cancelled=None, selection=None, return_plan=False, path_mode='relative'):
    """Archive used symbol-library bytes in the ROOT schematic. Native caches remain.

    Supplied libraries are archived verbatim (including valid inheritance) but
    never substituted for as-drawn definitions. Missing used caches fail closed.
    """
    source, output = Path(source).absolute(), Path(output).absolute()
    extraction = extract_symbols(source,follow=follow,nickname=nickname,variables=variables,cancelled=cancelled,selection=selection)
    sheets = load_hierarchy(source,follow,variables,cancelled)
    sidecars = design_sidecars(source); outputs, originals = rebase_library_tables(sidecars, source.parent, output, path_mode), dict(sidecars)
    root_sheet = sheets[0]
    version = parse(root_sheet.text).one(root_sheet.text, 'version')
    if version is None or int(version.arg().value(root_sheet.text)) < 20250114:
        raise ValueError('Open and save this schematic in KiCad 10 before adding embedded archive data.')
    pool = embedded_entries(root_sheet.text); reader=PayloadReader(); codec=Codec()
    if SCH_ARCHIVE in pool:
        old = json.loads(reader.read(pool[SCH_ARCHIVE]))
        if old.get('format') != SCH_FORMAT: raise ValueError('Reserved symbol archive name collision')
    archives=[('As-drawn symbol snapshots',extraction.files[nickname+'.kicad_sym'])]
    source_hashes={}
    for path in supplied:
        path=Path(path).absolute(); data=read_bytes(path,256*1024*1024); text=data.decode('utf-8')
        if parse(text).head(text) != 'kicad_symbol_lib': raise ValueError('Choose modern .kicad_sym libraries: '+str(path))
        archives.append((path.name,data)); source_hashes[str(path)] = sha256(data)
    if sum(len(data) for _,data in archives) > 512*1024*1024:
        raise ValueError('Symbol archive data exceeds 512 MiB')
    library_items=[]
    for label,data in archives:
        name='WayriCAD_Embed3D_symbols__'+sha256(data)+'.kicad_sym'
        if name in pool and reader.read(pool[name]) != data: raise ValueError('Embedded symbol-library filename collision')
        pool[name]=entry_for_bytes(name,data,codec)
        library_items.append({'label':label,'embedded_file':name,'sha256':sha256(data)})
    archive_meta={'format':SCH_FORMAT,'plugin_version':'0.4.1','libraries':library_items,
                  'mapping':extraction.meta['records'],'native_cache_retained':True}
    pool[SCH_ARCHIVE]=entry_for_bytes(SCH_ARCHIVE,json.dumps(archive_meta,ensure_ascii=False).encode('utf-8'),codec)
    records={r['relative']:r for r in extraction.meta['records']}
    for sheet in sheets:
        text=sheet.text
        if local_links: text=relink_sheet(text,records[sheet.relative]['mapping'],nickname,records[sheet.relative].get('selected_uuids'))
        if sheet.path == root_sheet.path: text=replace_entries(text,pool)
        verify_symbol_preservation(sheet.text,text)
        outputs[sheet.output]=_remap_sheets(sheet,text,sheets).encode('utf-8')
        originals[sheet.output]=sheet.text.encode('utf-8')
    if local_links:
        outputs[nickname+'.kicad_sym']=extraction.files[nickname+'.kicad_sym']
        outputs['sym-lib-table']=add_table_entry(outputs.get('sym-lib-table',b'').decode('utf-8'),
                    'symbols',nickname,'${KIPRJMOD}/'+nickname+'.kicad_sym').encode('utf-8')
    report={'operation':'embed-symbols','source':str(source),'output':str(output),'sheets':len(sheets),
            'symbols':extraction.meta['symbol_count'],'libraries_archived':len(archives),
            'local_library_links':local_links,'native_symbol_cache_retained':True,
            'input_sha256': {**{str(s.path):sha256(s.text.encode('utf-8')) for s in sheets}, **{str(source.parent/n):sha256(v) for n,v in sidecars.items()}, **source_hashes},
            'warnings':['Used symbol definitions already exist in lib_symbols. This adds a reusable library archive; it does not replace that cache.',
                        'Supplied libraries are archived, not substituted for existing pins/geometry.',
                        'External datasheets/SPICE resources are not automatically collected. Existing embedded resources are preserved.']}
    if return_plan: return DesignChange(outputs, originals, report)
    if apply:
        verify_source(extraction.meta,source)
        for path,digest in source_hashes.items():
            if sha256(read_bytes(Path(path))) != digest: raise ValueError('Supplied library changed: '+path)
        publish_design(output,outputs,originals,report,validate=validate,cancelled=cancelled)
    return report
