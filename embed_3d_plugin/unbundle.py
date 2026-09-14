"""PCB extraction and a deliberately separate, manifest-verified relink operation."""
from __future__ import annotations
from pathlib import Path
import re
from .board_package import (PayloadReader, recover, MANIFEST as BOARD_MANIFEST,
    model_settings, model_refs, replace_entries, safe_name, slug, uuid_of, _board_fingerprint)
from .core import PREFIX, embedded_entries, dependency_warning
from .codec import sha256
from .sexpr import Atom, Node, parse, patch, quote
from .paths import Resolver
from .portability_io import DesignChange, extraction_data, extraction_hashes, available_nickname
from .portability_io import (Extraction, read_bytes, read_text, load_extraction,
    file_reference, add_table_entry, design_sidecars, publish_design, publish_files,
    verify_source, checked_relative, rebase_library_tables, saved_project_variables)


def uri_references(text):
    """Read actual S-expression strings, not encoded attachment blobs."""
    result = set()
    def walk(node):
        if isinstance(node, Atom):
            if node.kind == 'string':
                value = node.value(text)
                if value.startswith(PREFIX):
                    result.add(value)  # Quoted native filenames may contain spaces.
                result.update(re.findall(r'kicad-embed://[^\s"<>]+', value))
        elif node.head(text) != 'embedded_files':
            for child in node.children: walk(child)
    walk(parse(text))
    return result


def prune_models(text, candidates, protected=()):
    entries = embedded_entries(text)
    used = uri_references(text) | set(protected)
    return replace_entries(text, {name: entry for name, entry in entries.items()
                                 if name not in candidates or PREFIX+name in used})


def model_filename(name, data):
    name = Path(name.replace('\\', '/')).name
    suffix = Path(name).suffix.lower()
    if suffix in ('.gz', '.bz2', '.xz', '.zip'):
        suffix = ''.join(Path(name).suffixes[-2:]).lower()
    if not re.fullmatch(r'(?:\.[a-z0-9]{1,10}){0,2}', suffix):
        raise ValueError('Unsafe model file extension: '+name)
    stem = re.sub(r'__[0-9a-f]{64}$', '', Path(name).stem)
    return 'models/'+safe_name(slug(stem, 25)+'__'+sha256(data)+suffix)


def _real_entry(name, local, pool):
    entry = local.get(name)
    return entry if entry and entry.encoded else pool.get(name)


def extract_pcb(source: Path, folder: Path, *, footprints=True, models=True,
                include_external=False, nickname='UnbundledFootprints',
                normalized=None, normalized_source_hash=None, resolver=None, cancelled=None,
                footprint_uuids=None, model_uuids=None, allow_missing=False, board_snapshot=None):
    """Return a preview plan. No disk writes. Native normalized map: uuid -> (name, text).

    Without a map, footprint extraction requires a valid WayriCAD Embed3D board archive.
    Model-only extraction supports any modern KiCad PCB.
    """
    source, folder = Path(source).absolute(), Path(folder).absolute()
    from .native import board_asset_root
    if board_snapshot is None:
        text = read_text(source); root = board_asset_root(text)
    else:
        _, text, root = board_snapshot
    if normalized_source_hash and sha256(text.encode('utf-8')) != normalized_source_hash:
        raise ValueError('PCB changed after native footprint capture. Preview again.')
    if not footprints and not models: raise ValueError('Select footprints, 3D models, or both')
    safe_name(nickname)
    reader, pool = PayloadReader(), embedded_entries(text, root)
    files, warnings, instances, definitions, def_models = {}, [], [], {}, {}
    resolver = resolver or Resolver(source.parent, saved_project_variables(source))
    library_paths = resolver.footprint_libraries(source.parent)
    archived = None
    if footprints and normalized is None:
        archived = recover(text)
        definitions = {Path(n).stem: b.decode('utf-8') for n, b in archived.library_files.items()}
        archived_defs = {d['key']: d['name'] for d in archived.manifest['definitions']}
        archived_map = {i['uuid']: i for i in archived.manifest['instances']}
    elif footprints:
        definitions = {name: raw for name, raw in normalized.values()}
        if len(definitions) != len(normalized): raise ValueError('Duplicate normalized footprint name')
    all_uids = {uuid_of(text, fp) for fp in root.nodes(text, 'footprint')}
    for chosen in (footprint_uuids, model_uuids):
        if chosen is not None and not set(chosen) <= all_uids:
            raise ValueError('A selected footprint no longer exists')
    selected_names = set()
    definition_model_selection = {}
    definition_contexts = {}
    total_external = [0]
    external_cache = {}

    def extract_models(raw, context, collect=True):
        parsed = parse(raw)
        local = embedded_entries(raw, parsed); mapping, edits = [], []
        for index, model in enumerate(parsed.nodes(raw, 'model')):
            if cancelled and cancelled(): raise InterruptedError('PCB extraction cancelled')
            ref = model.arg().value(raw)
            if not models or not collect: continue
            embedded = ref.startswith(PREFIX)
            if embedded:
                name = ref[len(PREFIX):]; entry = _real_entry(name, local, pool)
                if not entry: raise ValueError('Missing embedded model bytes: '+ref)
                data = reader.read(entry)
            elif include_external:
                try:
                    resolution = resolver.resolve(ref, context)
                except (ValueError, OSError) as exc:
                    if not allow_missing:
                        raise
                    warnings.append('Unresolved model retained: '+ref+'; '+str(exc))
                    continue
                # Resolver returns a Path, or raises a readable resolution error.
                if resolution not in external_cache:
                    external_cache[resolution] = read_bytes(resolution, 256*1024*1024)
                    total_external[0] += len(external_cache[resolution])
                data = external_cache[resolution]; name = resolution.name
                if total_external[0] > 512*1024*1024: raise ValueError('External model read budget exceeded')
            else:
                warnings.append('External model not copied; still depends on original resources: '+ref)
                if ref.startswith('${KIPRJMOD}/'):
                    target_path = source.parent/ref[len('${KIPRJMOD}/'):]
                    edits.append((model.arg().start, model.arg().end, quote(target_path.as_posix())))
                continue
            problem = dependency_warning(Path(name), data)
            if problem: raise ValueError(name+': '+problem)
            target = model_filename(name, data)
            files[target] = data
            mapping.append({'index': index, 'original': ref, 'file': target,
                            'embedded_name': name if embedded else None})
            edits.append((model.arg().start, model.arg().end, quote((folder/target).as_posix())))
        new = patch(raw, edits)
        embedded_names = {m['embedded_name'] for m in mapping if m['embedded_name']}
        if embedded_names:
            new = prune_models(new, embedded_names)
        if new != raw and model_settings(raw) != model_settings(new):
            raise ValueError('Extraction changed 3D settings')
        return new, mapping

    for fp in root.nodes(text, 'footprint'):
        raw, uid = fp.raw(text), uuid_of(text, fp)
        old_id = fp.arg().value(text)
        context = library_paths.get(old_id.split(':', 1)[0]) if ':' in old_id else source.parent
        model_selected = models and (model_uuids is None or uid in model_uuids)
        fp_selected = footprints and (footprint_uuids is None or uid in footprint_uuids)
        _, mapping = extract_models(raw, context, model_selected)
        name = None
        if fp_selected:
            if normalized is not None:
                if uid not in normalized: raise ValueError('Missing normalized footprint: '+uid)
                name = normalized[uid][0]
            else:
                item = archived_map.get(uid)
                if not item or old_id != item['new_fpid']:
                    raise ValueError('Archive does not match current footprint links; use As placed extraction')
                name = archived_defs[item['definition_key']]
            selected_names.add(name)
            definition_contexts.setdefault(name, context)
            definition_model_selection[name] = definition_model_selection.get(name, False) or model_selected
        instances.append({'uuid': uid, 'original_fpid': old_id, 'name': name, 'models': mapping,
                          'footprint_selected': bool(fp_selected), 'models_selected': bool(model_selected)})
    for name, raw in definitions.items():
        if footprint_uuids is not None and name not in selected_names: continue
        safe_name(name)
        collect = definition_model_selection.get(name, models and model_uuids is None)
        context = definition_contexts.get(name, source.parent)
        new, mapping = extract_models(raw, context, collect)
        # A standalone library moves the interpretation of relative model links.
        # Unchecked/external models are not copied, but keep resolving to the
        # original resource rather than accidentally changing their geometry.
        rebased = []
        copied_indices = {m['index'] for m in mapping}
        for index, model in enumerate(parse(new).nodes(new, 'model')):
            ref = model.arg().value(new)
            if index in copied_indices or ref.startswith(PREFIX): continue
            target = None
            if ref.startswith('${KIPRJMOD}/'):
                target = source.parent/ref[len('${KIPRJMOD}/'):]
            elif ref.startswith('$(KIPRJMOD)/'):
                target = source.parent/ref[len('$(KIPRJMOD)/'):]
            elif '$' not in ref and not Path(ref).is_absolute():
                try: target = resolver.resolve(ref, context)
                except (ValueError, OSError):
                    warnings.append('Unresolved external model in extracted footprint '+name+': '+ref)
            if target is not None:
                rebased.append((model.arg().start, model.arg().end, quote(target.as_posix())))
        new = patch(new, rebased)
        if not models or not collect:
            # Keep model payloads available locally when extracting footprints alone.
            own = embedded_entries(new)
            for ref in model_refs(new):
                if ref.startswith(PREFIX):
                    key = ref[len(PREFIX):]; entry = _real_entry(key, own, pool)
                    if not entry: raise ValueError('Missing embedded model bytes: '+ref)
                    reader.read(entry); own[key] = entry
            new = replace_entries(new, own)
        files[nickname+'.pretty/'+name+'.kicad_mod'] = new.encode('utf-8')
        def_models[name] = mapping
    if footprints and models:
        warnings.append('Extracted footprint files use the chosen asset folder paths. Relink creates a project-specific library view with your selected relative/absolute path style.')
    meta = {'kind': 'pcb', 'source': str(source), 'source_sha256': sha256(text.encode('utf-8')),
            'source_files': {'.': sha256(read_bytes(source))}, 'library': nickname,
            'footprints': footprints, 'models': models, 'include_external': include_external,
            'instances': instances, 'definition_models': def_models, 'asset_folder': str(folder),
            'definition_source': 'as placed (native normalized)' if normalized is not None else 'embedded library archive'}
    if not files: warnings.append('No matching files to extract. The input remains unchanged.')
    return Extraction(files, meta, sorted(set(warnings))).finalize()


def relink_pcb(source: Path, assets: Path, output: Path, *, link_footprints=True,
               link_models=True, path_mode='relative', prune=False, apply=False,
               validate=None, cancelled=None, footprint_uuids=None, model_uuids=None,
               extraction=None, return_plan=False):
    """Create a detached design copy linked to the explicitly selected extraction.

    The library view lives in the extraction folder. Its model paths are rebased
    for this output project; another project's existing view is not rewritten.
    """
    source, assets, output = map(lambda p: Path(p).absolute(), (source, assets, output))
    meta, extracted = extraction_data(assets, source, extraction)
    if meta['kind'] != 'pcb': raise ValueError('Select a PCB extraction folder')
    if not link_footprints and not link_models: raise ValueError('Choose at least one relink target')
    if link_footprints and not meta['footprints']: raise ValueError('Footprints were not extracted')
    if link_models and not meta['models']: raise ValueError('Models were not extracted')
    text = read_text(source); root = parse(text)
    sidecars = design_sidecars(source)
    target_nickname = available_nickname(sidecars.get('fp-lib-table',b'').decode('utf-8'),meta['library'])
    by_uuid = {i['uuid']: i for i in meta['instances']}
    if len(by_uuid) != len(meta['instances']): raise ValueError('Duplicate UUID in extraction manifest')
    for chosen in (footprint_uuids, model_uuids):
        if chosen is not None and not set(chosen) <= set(by_uuid):
            raise ValueError('Selected footprint was not in this extraction')
    old_pool = embedded_entries(text); edits, extracted_names = [], set()
    linked_fp_names = set(); linked_fp_count = 0; linked_model_count = 0
    for fp in root.nodes(text, 'footprint'):
        raw, uid = fp.raw(text), uuid_of(text, fp)
        item = by_uuid.get(uid)
        if not item or fp.arg().value(text) != item['original_fpid']:
            raise ValueError('Footprint no longer matches extraction: '+uid)
        changes = []
        fp_selected = link_footprints and (footprint_uuids is None or uid in footprint_uuids)
        md_selected = link_models and (model_uuids is None or uid in model_uuids)
        if fp_selected:
            if not item.get('name'): raise ValueError('Footprint was not extracted: '+uid)
            linked_fp_names.add(item['name']); linked_fp_count += 1
            arg = parse(raw).arg(); safe_name(item['name'])
            changes.append((arg.start, arg.end, quote(target_nickname+':'+item['name'])))
        if md_selected:
            if not item.get('models_selected', True): raise ValueError('Models were not extracted for '+uid)
            nodes = parse(raw).nodes(raw, 'model')
            for mapping in item['models']:
                node = nodes[mapping['index']]
                if node.arg().value(raw) != mapping['original']: raise ValueError('Model reference changed since extraction')
                checked_relative(mapping['file'])
                if mapping['file'] not in extracted: raise ValueError('Unverified model target')
                changes.append((node.arg().start, node.arg().end,
                                quote(file_reference(assets/mapping['file'], output, path_mode))))
                if mapping['embedded_name']: extracted_names.add(mapping['embedded_name'])
                linked_model_count += 1
        changed_indices = {m['index'] for m in item['models']} if md_selected else set()
        for idx, node in enumerate(parse(raw).nodes(raw, 'model')):
            ref = node.arg().value(raw)
            if idx not in changed_indices and ref.startswith('${KIPRJMOD}/'):
                target_path = source.parent/ref[len('${KIPRJMOD}/'):]
                changes.append((node.arg().start, node.arg().end, quote(file_reference(target_path, output, path_mode))))
        changed = patch(raw, changes)
        if prune and link_models:
            changed = prune_models(changed, extracted_names)
        if model_settings(raw) != model_settings(changed): raise ValueError('Relink changed model settings')
        edits.append((fp.start, fp.end, changed))
    result = patch(text, edits)
    # Remove ONLY our managed archive when all corresponding targets were relinked.
    pool = embedded_entries(result)
    archive_removed = []
    if prune and link_footprints and link_models and (footprint_uuids is None or set(footprint_uuids)==set(by_uuid)) and (model_uuids is None or set(model_uuids)==set(by_uuid)) and BOARD_MANIFEST in pool:
        original_archive = recover(text)  # validate before removing anything
        archive_removed = [BOARD_MANIFEST]+[d['embedded_file'] for d in original_archive.manifest['definitions']]
        for name in archive_removed: pool.pop(name, None)
        result = replace_entries(result, pool)
    if prune and link_models:
        protected = set()
        # Keep models referenced inside retained footprint archives, even when the
        # corresponding board instance no longer uses the embedded URI.
        reader = PayloadReader()
        for name, entry in pool.items():
            if name.lower().endswith('.kicad_mod'):
                protected |= uri_references(reader.read(entry).decode('utf-8'))
        result = prune_models(result, extracted_names, protected)
    if _board_fingerprint(text) != _board_fingerprint(result): raise ValueError('Board preservation check failed')
    sidecars = design_sidecars(source); outputs = rebase_library_tables(sidecars, source.parent, output, path_mode); views = {}
    if link_footprints:
        key = sha256((str(output)+'|'+path_mode+'|'+str(link_models)).encode())[:20]
        view_dir = 'linked/'+key+'/'+meta['library']+'.pretty'
        for name, mappings in meta['definition_models'].items():
            if name not in linked_fp_names: continue
            raw = extracted[meta['library']+'.pretty/'+name+'.kicad_mod'].decode('utf-8')
            nodes = parse(raw).nodes(raw, 'model'); changes = []
            for m in mappings:
                node = nodes[m['index']]
                changes.append((node.arg().start, node.arg().end,
                                quote(file_reference(assets/m['file'], output, path_mode))))
            view = patch(raw, changes)
            if model_settings(view) != model_settings(raw): raise ValueError('Library-view settings changed')
            views[view_dir+'/'+name+'.kicad_mod'] = view.encode('utf-8')
        uri = file_reference(assets/view_dir, output, path_mode)
        outputs['fp-lib-table'] = add_table_entry(outputs.get('fp-lib-table', b'').decode('utf-8'),
                                                  'footprints', target_nickname, uri).encode('utf-8')
    outputs[source.name] = result.encode('utf-8')
    report = {'operation': 'relink-pcb', 'source': str(source), 'assets': str(assets), 'output': str(output),
              'link_footprints': link_footprints, 'link_models': link_models, 'path_mode': path_mode, 'target_library':target_nickname,
              'remove_redundant_payloads': prune, 'removed_archive_entries': archive_removed,
              'input_sha256': {**extraction_hashes(assets,extracted,extraction), str(source): sha256(text.encode('utf-8')), **{str(source.parent/n): sha256(v) for n,v in sidecars.items()}},
              'footprint_count': linked_fp_count, 'models_relinked': linked_model_count, 'library_view_files': list(views),
              'warnings': list(meta.get('warnings', []))+['Schematic Footprint fields are not changed. Review before Update PCB from Schematic.',
                           'This is a PCB copy, not a complete project dependency pack. External non-model dependencies may remain.']}
    if return_plan: return DesignChange(outputs, {**sidecars, source.name: text.encode('utf-8')}, report, {str(assets): views} if views else {})
    if apply:
        if output.exists() or not output.parent.is_dir(): raise ValueError('Choose a NEW output folder')
        verify_source(meta, source); extraction_data(assets, source, extraction)
        # Library views are explicit new extraction outputs, not edits to original assets.
        publish_files(assets, views, cancelled=cancelled)
        publish_design(output, outputs, {**sidecars, source.name: text.encode('utf-8')}, report,
                       validate=validate, cancelled=cancelled)
    return report
