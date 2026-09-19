"""Transactional project-local libraries, using the saved design as authority.

Definitions come from native-normalized placed footprints and schematic caches.
Only linked bytes are copied; unavailable models are never substituted by shape.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from . import symbols as sy
from . import board_package as bp
from .codec import sha256
from .paths import Resolver
from .sexpr import parse, patch, quote
from .unbundle import extract_pcb
from .unbundle import model_filename
from .core import PREFIX, embedded_entries, dependency_warning
from .workspace import scan_design
from .portability_io import checked_relative, add_table_entry, available_nickname, saved_project_variables
from .portability_io import read_bytes

CONFIG = '.wayricad-library.json'
MANIFEST = 'wayricad-library-manifest.json'


def folder_name(value):
    relative = checked_relative(str(value).replace('\\', '/'))
    if relative.parts[0].startswith('.'):
        raise ValueError('Choose a visible relative folder inside the project, such as local.')
    return relative.as_posix()


def settings(project):
    path = Path(project) / CONFIG
    if not path.exists():
        return {'folder': 'local', 'model_roots': [], 'variables': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    data['folder'] = folder_name(data.get('folder', 'local'))
    return data


def portable_definition(source, uri, resolver, allow_missing=False):
    """Copy a library footprint without changing its coordinate system."""
    raw = Path(source).read_text(encoding='utf-8')
    root = parse(raw)
    if root.head(raw) != 'footprint':
        raise ValueError('Invalid footprint library file: '+str(source))
    name = bp.safe_name('L_'+bp.slug(Path(source).stem, 40))
    files, warnings = {}, []
    changes = [(root.arg().start, root.arg().end, quote(name))]
    pool, reader = embedded_entries(raw), bp.PayloadReader()
    for model in root.nodes(raw, 'model'):
        reference = model.arg().value(raw)
        if reference.startswith(PREFIX):
            key = reference[len(PREFIX):]
            if key not in pool: raise ValueError('Missing embedded model: '+key)
            data = reader.read(pool[key]); filename = key
        else:
            try:
                path = resolver.resolve(reference, Path(source).parent)
                data = path.read_bytes(); filename = path.name
            except (ValueError, OSError) as exc:
                if not allow_missing: raise
                warnings.append('Unresolved model retained: '+reference+'; '+str(exc))
                continue
        problem = dependency_warning(Path(filename), data)
        if problem: raise ValueError(filename+': '+problem)
        target = model_filename(filename, data); files[target] = data
        changes.append((model.arg().start, model.arg().end, quote(uri+'/'+target)))
    return name, patch(raw, changes), files, warnings


class ProjectResolver(Resolver):
    """Explicit additional roots; ambiguity is an error, never a guess."""
    def __init__(self, project, variables=None, model_roots=()):
        super().__init__(project, variables)
        self.search_roots = [Path(p).resolve() for p in model_roots]
        self.source_files = {}
        self._resolution_cache = {}
        self._library_cache = {}

    def begin_plan(self):
        self.source_files.clear()
        self._resolution_cache.clear()
        self._library_cache.clear()

    def model_roots(self):
        return list(dict.fromkeys([*self.search_roots, *super().model_roots()]))

    def resolve(self, reference, source_dir=None):
        key = (str(reference), str(source_dir or ''))
        if key not in self._resolution_cache:
            try:
                self._resolution_cache[key] = (super().resolve(reference, source_dir), None)
            except (ValueError, OSError) as exc:
                self._resolution_cache[key] = (None, (type(exc), str(exc)))
        path, error = self._resolution_cache[key]
        if error is not None:
            raise error[0](error[1])
        if path not in self.source_files:
            self.source_files[path] = sha256(path.read_bytes())
        return path

    def footprint_libraries(self, project_dir=None):
        key = str(project_dir or '')
        if key not in self._library_cache:
            self._library_cache[key] = super().footprint_libraries(project_dir)
        return dict(self._library_cache[key])


def _relink_fingerprint(text, root=None):
    """Byte-exact geometry invariant, masking only permitted link strings."""
    from .native import board_asset_root
    root = root or board_asset_root(text)
    changes = []
    for footprint in root.nodes(text, 'footprint'):
        arg = footprint.arg()
        changes.append((arg.start, arg.end, '"<LIBRARY-ID>"'))
        for model in footprint.nodes(text, 'model'):
            arg = model.arg()
            changes.append((arg.start, arg.end, '"<MODEL-PATH>"'))
    return patch(text, changes)


@dataclass
class LocalPlan:
    project: Path
    folder: str
    files: dict[str, bytes]
    expected: dict[str, str | None]
    inputs: dict[str, str]
    counts: dict
    warnings: list[str] = field(default_factory=list)
    applied: bool = False

    def summary(self):
        return {'operation': 'localize-project', 'project': str(self.project),
                'library_folder': self.folder, 'counts': self.counts,
                'files_to_write': len(self.files), 'warnings': self.warnings,
                'source_changes': sorted(n for n in self.files if not n.startswith(self.folder+'/')),
                'backup_required': True, 'models_complete': not any('Unresolved model retained:' in w for w in self.warnings),
                'assets_complete': not any(w.startswith(('Unresolved model retained:', 'Unresolved footprint retained:',
                                                        'Unresolved symbol footprint default retained:')) for w in self.warnings)}

    def assert_fresh(self):
        for path, digest in self.inputs.items():
            if sha256(Path(path).read_bytes()) != digest:
                raise ValueError('Input changed after preview: '+path)
        for name, digest in self.expected.items():
            target = self.project / name
            bp._no_symlinks(target)
            current = sha256(target.read_bytes()) if target.is_file() else None
            if current != digest or (target.exists() and not target.is_file()):
                raise ValueError('Output changed after preview: '+name)

    def apply(self, *, validate=None, cancelled=None):
        if self.applied:
            raise ValueError('Preview this operation again before applying.')
        self.assert_fresh()
        backup = self.project / '.wayricad-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        bp._no_symlinks(backup)
        written = []
        with tempfile.TemporaryDirectory(prefix='.wayricad-stage-', dir=self.project) as temporary:
            stage = Path(temporary)
            for name, data in self.files.items():
                if cancelled and cancelled():
                    raise InterruptedError('Localization cancelled before publication.')
                target = stage / checked_relative(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if validate:
                validate(stage)
            self.assert_fresh()
            backup.mkdir(parents=True)
            journal = {'format': 'wayricad-library-restore/v1', 'project': str(self.project),
                       'previous': self.expected, 'published': {n:sha256(v) for n,v in self.files.items()},
                       'written': [], 'state': 'publishing'}
            for name, digest in self.expected.items():
                if digest is not None:
                    old = backup / name
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.project / name, old)
            record = backup / 'restore.json'
            record.write_text(json.dumps(journal, indent=2), encoding='utf-8')
            try:
                # Libraries first; references last. Every target has a journaled backup.
                ordered = sorted(self.files, key=lambda n: (not n.startswith(self.folder+'/'), n))
                for name in ordered:
                    if cancelled and cancelled():
                        raise InterruptedError('Localization cancelled; changes rolled back.')
                    target = self.project / name
                    bp._no_symlinks(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    written.append(name)
                    journal['written'] = written
                    record.write_text(json.dumps(journal, indent=2), encoding='utf-8')
                    os.replace(stage / name, target)
            except BaseException:
                for name in reversed(written):
                    if self.expected[name] is None:
                        (self.project/name).unlink(missing_ok=True)
                    else:
                        shutil.copy2(backup/name, self.project/name)
                journal['state'] = 'rolled-back'
                record.write_text(json.dumps(journal, indent=2), encoding='utf-8')
                raise
            journal['state'] = 'complete'
            record.write_text(json.dumps(journal, indent=2), encoding='utf-8')
        self.applied = True
        return {**self.summary(), 'backup': str(backup), 'reopen_required': True}


def restore(backup):
    """Restore a completed publication only while its outputs are unchanged."""
    backup = Path(backup).resolve(); record = backup/'restore.json'
    journal = json.loads(record.read_text(encoding='utf-8'))
    if journal.get('format') != 'wayricad-library-restore/v1' or journal.get('state') != 'complete':
        raise ValueError('Choose a completed Embed3D backup.')
    project = Path(journal['project']).resolve()
    if backup.parent != project/'.wayricad-backups':
        raise ValueError('Backup must remain inside its original project.')
    for name in journal['written']:
        name = checked_relative(name).as_posix(); target = project/name
        bp._no_symlinks(target); bp._no_symlinks(backup/name)
        if not target.is_file() or sha256(target.read_bytes()) != journal['published'][name]:
            raise ValueError('File changed since localization; preserve your edits before restoring: '+name)
        old_hash = journal['previous'][name]
        if old_hash is not None and sha256((backup/name).read_bytes()) != old_hash:
            raise ValueError('Backup checksum failed: '+name)
    for name in reversed(journal['written']):
        if journal['previous'][name] is None:
            (project/name).unlink()
        else:
            shutil.copy2(backup/name,project/name)
    journal['state'] = 'restored'; record.write_text(json.dumps(journal,indent=2),encoding='utf-8')
    return {'restored_files':len(journal['written']), 'project':str(project), 'reopen_required':True}


def prepare(pcb=None, schematic=None, *, folder='local', normalized=None,
            normalized_hash=None, resolver=None, allow_missing=False, cancelled=None):
    pcb = Path(pcb).resolve() if pcb else None
    schematic = Path(schematic).resolve() if schematic else None
    if not pcb and not schematic:
        raise ValueError('Choose a saved PCB or schematic.')
    if pcb and schematic and pcb.parent!=schematic.parent:
        raise ValueError('PCB and root schematic must be saved in the same project folder. Create a project copy first.')
    project = (pcb or schematic).parent
    folder = folder_name(folder)
    bp._no_symlinks(project/folder)
    # Capture sidecars before resolving/extracting. A later hash of an edited
    # table must never authorize publishing a plan built from its old contents.
    sidecars={}
    for name in (CONFIG,'fp-lib-table','sym-lib-table',(pcb or schematic).with_suffix('.kicad_pro').name,folder+'/'+MANIFEST):
        path=project/name;bp._no_symlinks(path)
        sidecars[name]=sha256(path.read_bytes()) if path.is_file() else None
    resolver = resolver or ProjectResolver(project, saved_project_variables(pcb or schematic))
    if isinstance(resolver, ProjectResolver):
        resolver.begin_plan()
    sheets = sy.load_hierarchy(schematic, cancelled=cancelled) if schematic else None
    board_snapshot = None
    if pcb:
        from .native import board_asset_root
        data = read_bytes(pcb); text = data.decode('utf-8')
        board_snapshot = (data, text, board_asset_root(text))
    inventory = scan_design(pcb, schematic, resolver=resolver, cancelled=cancelled,
                            sheets=sheets, board_snapshot=board_snapshot)
    files, warnings, inputs = {}, list(inventory.warnings), dict(inventory.hashes)
    config = settings(project)
    fp_table = (project/'fp-lib-table').read_text(encoding='utf-8') if (project/'fp-lib-table').exists() else ''
    sym_table = (project/'sym-lib-table').read_text(encoding='utf-8') if (project/'sym-lib-table').exists() else ''
    same = config.get('folder') == folder
    fp_nick = config.get('footprint_library') if same else None
    sym_nick = config.get('symbol_library') if same else None
    fp_nick = fp_nick or available_nickname(fp_table, 'WayriCAD_Project')
    sym_nick = sym_nick or available_nickname(sym_table, 'WayriCAD_Project')
    uri = '${KIPRJMOD}/'+folder
    footprint_ids, symbol_extraction, assignments = {}, None, {}
    footprint_defaults = {}
    counts = {'components': len(inventory.rows), 'footprints': 0, 'symbols': 0, 'models': 0, 'schematic_assignments': 0}
    if pcb:
        if normalized is None:
            raise ValueError('Native footprint normalization is required; use the KiCad launcher or native CLI.')
        extraction = extract_pcb(pcb, project/folder, normalized=normalized,
            normalized_source_hash=normalized_hash, include_external=True, resolver=resolver,
            nickname=fp_nick, allow_missing=allow_missing, cancelled=cancelled,
            board_snapshot=board_snapshot)
        warnings.extend(extraction.warnings)
        for name, data in extraction.files.items():
            if name.endswith('.kicad_mod'):
                text = data.decode('utf-8')
                text = text.replace((project/folder).as_posix()+'/', uri+'/')
                data = text.encode('utf-8')
            files[folder+'/'+name] = data
        _, text, root = board_snapshot; edits = []
        nodes = {bp.uuid_of(text, fp): fp for fp in root.nodes(text, 'footprint')}
        for item in extraction.meta['instances']:
            node = nodes[item['uuid']]; raw = node.raw(text); local = parse(raw)
            target_id = fp_nick+':'+item['name']; footprint_ids[item['uuid']] = target_id
            if item['original_fpid']:
                footprint_defaults.setdefault(item['original_fpid'], target_id)
            changes = [(local.arg().start, local.arg().end, quote(target_id))]
            models = local.nodes(raw, 'model')
            for model in item['models']:
                arg = models[model['index']].arg()
                changes.append((arg.start, arg.end, quote(uri+'/'+model['file'])))
            updated = patch(raw, changes)
            if bp.model_settings(raw) != bp.model_settings(updated):
                raise ValueError('Model transforms changed during relinking.')
            edits.append((node.start, node.end, updated))
        changed = patch(text, edits)
        if _relink_fingerprint(text, root) != _relink_fingerprint(changed):
            raise ValueError('Board geometry changed during relinking.')
        files[pcb.name] = changed.encode('utf-8')
        files['fp-lib-table'] = add_table_entry(fp_table, 'footprints', fp_nick, uri+'/'+fp_nick+'.pretty').encode('utf-8')
        counts['footprints'] = len(footprint_ids)
        counts['models'] = len([n for n in extraction.files if n.startswith('models/')])
    if schematic:
        for component in inventory.rows:
            if component.board_uuid in footprint_ids:
                for sheet, uid in component.symbol_instances:
                    assignments[(sheet, uid)] = footprint_ids[component.board_uuid]
        # Schematic-only and not-yet-placed components still need their assigned
        # footprint definitions. Resolve exact project/global library IDs.
        libraries = resolver.footprint_libraries(project)
        captured = {}
        def capture(old_id, default=False):
            if old_id in footprint_defaults:
                return footprint_defaults[old_id]
            if old_id not in captured:
                nick, separator, leaf = old_id.partition(':')
                library = libraries.get(nick)
                source = Path(library)/(leaf+'.kicad_mod') if library and separator and '/' not in leaf and '\\' not in leaf else None
                if source is None or not source.is_file():
                    captured[old_id] = None
                else:
                    inputs[str(source)] = sha256(source.read_bytes())
                    name, raw, assets, notes = portable_definition(source,uri,resolver,allow_missing)
                    name = leaf if nick == fp_nick else bp.safe_name('L_'+bp.slug(nick,20)+'_'+bp.slug(leaf,40)+'_'+sha256(old_id.encode())[:10])
                    node = parse(raw); raw = patch(raw,[(node.arg().start,node.arg().end,quote(name))])
                    files[folder+'/'+fp_nick+'.pretty/'+name+'.kicad_mod'] = raw.encode('utf-8')
                    for filename,data in assets.items(): files[folder+'/'+filename] = data
                    warnings.extend(notes); captured[old_id] = fp_nick+':'+name
                    footprint_defaults[old_id] = captured[old_id]
                    counts['footprints'] += 1
            if captured[old_id] is None:
                category = 'symbol footprint default' if default else 'footprint'
                if not allow_missing:
                    raise ValueError('Assigned '+category+' library is unavailable: '+old_id)
                warnings.append('Unresolved '+category+' retained: '+old_id)
            return captured[old_id]

        for sheet in sheets:
            for item in sy.placed_symbols(sheet.text, sheet.root):
                key = (sheet.relative, item['uuid'])
                if key in assignments: continue
                value = sy.property_value(item['node'], sheet.text, 'Footprint')
                old_id = value.value(sheet.text) if value else ''
                if not old_id: continue
                target = capture(old_id)
                if target is not None:
                    assignments[key] = target
            for definition in sy.cache_symbols(sheet.text, sheet.root).values():
                node = parse(definition)
                value = sy.property_value(node, definition, 'Footprint')
                old_id = value.value(definition) if value else ''
                if old_id:
                    capture(old_id, default=True)

        symbol_extraction = sy.extract_symbols(schematic, nickname=sym_nick, cancelled=cancelled,
                                                sheets=sheets, footprint_defaults=footprint_defaults)
        warnings.extend(symbol_extraction.warnings)
        for name, data in symbol_extraction.files.items():
            files[folder+'/symbols/'+name] = data
        by_sheet = {row['relative']: row for row in symbol_extraction.meta['records']}
        for sheet in sheets:
            if Path(sheet.output).as_posix() != Path(sheet.relative).as_posix():
                raise ValueError('A child sheet is outside the project; first create a self-contained project copy.')
            text = sy.relink_sheet(sheet.text, by_sheet[sheet.relative]['mapping'], sym_nick,
                                  root=sheet.root, footprint_defaults=footprint_defaults)
            edits = []
            for item in sy.placed_symbols(text):
                target = assignments.get((sheet.relative, item['uuid']))
                if not target:
                    continue
                value = sy.property_value(item['node'], text, 'Footprint')
                if value is None:
                    raise ValueError('Matched symbol has no Footprint property: '+item['uuid'])
                edits.append((value.start, value.end, quote(target)))
                counts['schematic_assignments'] += 1
            files[sheet.relative] = patch(text, edits).encode('utf-8')
        files['sym-lib-table'] = add_table_entry(sym_table, 'symbols', sym_nick, uri+'/symbols/'+sym_nick+'.kicad_sym').encode('utf-8')
        counts['symbols'] = symbol_extraction.meta['symbol_count']
    if counts['footprints']:
        files['fp-lib-table'] = add_table_entry(fp_table, 'footprints', fp_nick, uri+'/'+fp_nick+'.pretty').encode('utf-8')
    counts['models'] = len([n for n in files if n.startswith(folder+'/models/')])
    # Keep the project settings beside the libraries and stage the native project
    # file too, so CLI validation sees the same stackup and text variables.
    project_file = (pcb or schematic).with_suffix('.kicad_pro')
    if project_file.is_file():
        files[project_file.name] = project_file.read_bytes()
    config.update(folder=folder, footprint_library=fp_nick, symbol_library=sym_nick,
                  model_roots=[str(p) for p in getattr(resolver, 'search_roots', [])],
                  variables=resolver.explicit)
    files[CONFIG] = (json.dumps(config, indent=2)+'\n').encode('utf-8')
    for path, digest in getattr(resolver, 'source_files', {}).items():
        inputs[str(path)] = digest
    managed_path = project/folder/MANIFEST
    previous = json.loads(managed_path.read_text(encoding='utf-8')) if managed_path.exists() else {}
    old_assets = previous.get('files', {})
    expected = {}
    for name, data in files.items():
        target = project/checked_relative(name)
        bp._no_symlinks(target)
        expected[name] = sha256(target.read_bytes()) if target.is_file() else None
        if name.startswith(folder+'/') and target.exists() and target.read_bytes() != data:
            if old_assets.get(name) != expected[name]:
                raise ValueError('Existing library file is not an unchanged managed asset: '+name)
    manifest = {'format': 'wayricad-project-library/v1', 'counts': counts,
                'files': {n: sha256(v) for n,v in files.items() if n.startswith(folder+'/')},
                'warnings': sorted(set(warnings))}
    files[folder+'/'+MANIFEST] = (json.dumps(manifest, indent=2)+'\n').encode('utf-8')
    expected[folder+'/'+MANIFEST] = sha256(managed_path.read_bytes()) if managed_path.exists() else None
    for name,digest in sidecars.items():
        path=project/name
        current=sha256(path.read_bytes()) if path.is_file() else None
        if current!=digest:
            raise ValueError('Project sidecar changed during preview: '+name)
        if name in expected:expected[name]=digest
    return LocalPlan(project, folder, files, expected, inputs, counts, sorted(set(warnings)))
