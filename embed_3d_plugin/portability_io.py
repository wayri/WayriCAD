"""Bounded reads, portable paths, conservative publication and manifest validation.

Extract is new-files-only. Relink writes a new design copy by default. Existing
files may only be reused when byte-identical; divergent content is never replaced.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Callable
from .codec import sha256
from .core import MAX_JOB_BYTES
from .board_package import safe_name, _no_symlinks
from .sexpr import parse, patch, quote
from .storage import atomic_write, write_json

MANIFEST = 'WayriCAD Embed3D-extraction.json'
FORMAT = 'embed_3d_plugin-extraction-v1'
MAX_TEXT = 384 * 1024 * 1024


@dataclass
class DesignChange:
    """Pure, previewable design output; no writes until a coordinator publishes."""
    files: dict[str, bytes]
    originals: dict[str, bytes]
    report: dict
    extra_files: dict[str, dict[str, bytes]] = field(default_factory=dict)


def extraction_data(folder, source, extraction=None):
    if extraction is None:
        return load_extraction(folder, source)
    extraction.finalize()
    verify_source(extraction.meta, Path(source))
    return extraction.meta, dict(extraction.files)


def extraction_hashes(folder, files, extraction=None):
    if extraction is not None:
        return {}  # Outputs of this same operation, not pre-existing input files.
    folder = Path(folder)
    return {str(folder/MANIFEST): sha256(read_bytes(folder/MANIFEST)),
            **{str(folder/n): sha256(v) for n,v in files.items()}}


def read_bytes(path: Path, limit=MAX_TEXT):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Missing file or size limit exceeded: '+str(path))
    with path.open('rb') as stream:
        data = stream.read(limit+1)
    if len(data) > limit:
        raise ValueError('File grew beyond size limit: '+str(path))
    return data


def read_text(path):
    return read_bytes(Path(path)).decode('utf-8')


def checked_relative(name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('Unsafe archive pathname: '+str(name))
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
        raise ValueError('Unsafe archive pathname: '+name)
    for part in p.parts:
        if len(part) > 240 or any(ord(c) < 32 or c in '<>\"|?*' for c in part) or part.endswith(('.', ' ')):
            raise ValueError('Unsafe filename: '+part)
        if part.split('.')[0].upper() in {'CON', 'AUX', 'PRN', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
            raise ValueError('Reserved filename: '+part)
    return Path(*p.parts)


def file_reference(path: Path, project: Path, mode='relative'):
    path, project = Path(path).absolute(), Path(project).absolute()
    if mode == 'absolute':
        return path.as_posix()
    if mode != 'relative':
        raise ValueError('Path mode must be relative or absolute')
    try:
        relative = os.path.relpath(path, project).replace('\\', '/')
    except ValueError as exc:
        raise ValueError('Relative links cannot cross filesystem drives. Choose absolute paths.') from exc
    return '${KIPRJMOD}/'+relative


def add_table_entry(original: str, kind: str, nickname: str, uri: str):
    safe_name(nickname)
    head = 'fp_lib_table' if kind == 'footprints' else 'sym_lib_table'
    row = '(lib (name '+quote(nickname)+') (type "KiCad") (uri '+quote(uri)+') (options "") (descr "WayriCAD Embed3D extracted design library"))'
    if not original.strip():
        return '('+head+'\n  '+row+'\n)\n'
    root = parse(original)
    if root.head(original) != head:
        raise ValueError('Invalid '+head)
    found = []
    for item in root.nodes(original, 'lib'):
        name = item.one(original, 'name')
        if name and name.arg().value(original) == nickname:
            found.append(item)
    if len(found) > 1:
        raise ValueError('Duplicate library nickname: '+nickname)
    if found:
        row_uri, row_type = found[0].one(original, 'uri'), found[0].one(original, 'type')
        if not row_uri or row_uri.arg().value(original) != uri or not row_type or row_type.arg().value(original) != 'KiCad':
            raise ValueError('Library nickname already maps elsewhere: '+nickname+'. Choose a new nickname before extraction.')
        return original
    return patch(original, [(root.end-1, root.end-1, '\n  '+row+'\n')])



def available_nickname(original, base):
    """Do not repoint an existing library alias during a new-copy relink."""
    safe_name(base)
    names=set()
    if original.strip():
        root=parse(original)
        for row in root.nodes(original,'lib'):
            name=row.one(original,'name')
            if name:names.add(name.arg().value(original))
    if base not in names:return base
    for index in range(2,10002):
        value=base+'_'+str(index)
        if value not in names:return value
    raise ValueError('No unused library nickname available.')


def rebase_library_tables(files: dict[str, bytes], source_project: Path, output_project: Path, mode='relative'):
    """Rebase explicitly project-relative table URIs; do not guess custom variables.

    Other resource references inside .kicad_pro (drawing sheets, sim paths etc.)
    remain out of scope and are reported as such by the workflow.
    """
    result = dict(files)
    for name in ('fp-lib-table', 'sym-lib-table'):
        if name not in result: continue
        text = result[name].decode('utf-8'); root = parse(text); edits=[]
        for row in root.nodes(text, 'lib'):
            uri = row.one(text, 'uri')
            if not uri: continue
            arg = uri.arg(); value = arg.value(text)
            if value.startswith('${KIPRJMOD}/'):
                target = Path(source_project)/value[len('${KIPRJMOD}/'):]
            elif value.startswith('$(KIPRJMOD)/'):
                target = Path(source_project)/value[len('$(KIPRJMOD)/'):]
            elif value and not value.startswith(('/', '\\')) and ':' not in value and '$' not in value:
                target = Path(source_project)/value
            else:
                continue
            edits.append((arg.start, arg.end, quote(file_reference(target, output_project, mode))))
        result[name] = patch(text, edits).encode('utf-8')
    return result


@dataclass
class Extraction:
    files: dict[str, bytes]
    meta: dict
    warnings: list[str] = field(default_factory=list)

    def finalize(self):
        if MANIFEST in self.files:
            raise ValueError('Reserved manifest filename')
        names = set()
        for name in self.files:
            checked_relative(name)
            if name.casefold() in names:
                raise ValueError('Case-insensitive output collision: '+name)
            names.add(name.casefold())
        if sum(map(len, self.files.values())) > MAX_JOB_BYTES:
            raise ValueError('Extraction exceeds 512 MiB output budget')
        self.meta.update(format=FORMAT, plugin_version='0.4.1',
                         files={p: sha256(v) for p, v in self.files.items()}, warnings=self.warnings)
        return self

    def preview(self):
        self.finalize()
        return {'kind': self.meta['kind'], 'files': len(self.files),
                'bytes': sum(map(len, self.files.values())), 'warnings': self.warnings,
                'outputs': list(self.files), 'source': self.meta.get('source')}

    def publish(self, folder: Path, cancelled=None):
        self.finalize()
        if self.meta.get('asset_folder') and Path(folder).absolute() != Path(self.meta['asset_folder']).absolute():
            raise ValueError('Asset folder changed since preview. Preview again to rebase footprint model links.')
        verify_source(self.meta)
        outputs = dict(self.files)
        outputs[MANIFEST] = (json.dumps(self.meta, indent=2, ensure_ascii=False)+'\n').encode('utf-8')
        publish_files(folder, outputs, cancelled=cancelled)
        return Path(folder)/MANIFEST


def publish_files(folder: Path, files: dict[str, bytes], cancelled=None):
    """Exclusive file creation, read-back checks and rollback of new files only.

    This works on normal local filesystems without a hard-link requirement.
    Multi-file publication is not power-loss atomic; the manifest is written last.
    """
    folder = Path(folder).absolute()
    _no_symlinks(folder)
    targets, folded = {}, set()
    for name, data in files.items():
        rel = checked_relative(name)
        if name.casefold() in folded:
            raise ValueError('Case-insensitive output collision: '+name)
        folded.add(name.casefold())
        target = folder/rel
        _no_symlinks(target)
        if target.exists() and (not target.is_file() or read_bytes(target) != data):
            raise ValueError('Existing file differs; nothing overwritten: '+str(target))
        targets[target] = data
    created, dirs = [], []
    try:
        for target, data in targets.items():
            if cancelled and cancelled():
                raise InterruptedError('Publication cancelled; new files rolled back')
            parents = []
            p = target.parent
            while not p.exists():
                parents.append(p); p = p.parent
            for p in reversed(parents):
                try:
                    p.mkdir(); dirs.append(p)
                except FileExistsError:
                    if not p.is_dir(): raise
            _no_symlinks(target)
            if target.exists():
                if read_bytes(target) != data:
                    raise ValueError('Destination changed during publication: '+str(target))
                continue
            # Track partial writes so exception cleanup never deletes another process's file.
            with target.open('xb') as stream:
                created.append((target, data))
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            if read_bytes(target) != data:
                raise OSError('Extraction read-back failed: '+str(target))
    except Exception:
        for path, expected in reversed(created):
            try:
                actual = path.read_bytes()
                if actual == expected or expected.startswith(actual): path.unlink()
            except OSError:
                pass
        for path in reversed(dirs):
            try: path.rmdir()
            except OSError: pass
        raise


def verify_source(meta, override: Path | None = None):
    root = Path(override or meta['source']).absolute()
    hashes = meta.get('source_files', {root.name: meta.get('source_sha256')})
    for relative, digest in hashes.items():
        # Sources may be above root for hierarchical sheets; values are never output paths.
        candidate = root if relative == '.' else root.parent/relative
        if sha256(read_bytes(candidate)) != digest:
            raise ValueError('Source changed since extraction/preview. Extract again: '+str(candidate))
    return root


def load_extraction(folder: Path, source: Path | None = None):
    folder = Path(folder).absolute()
    meta = json.loads(read_bytes(folder/MANIFEST, 8*1024*1024))
    if not isinstance(meta, dict) or meta.get('format') != FORMAT or meta.get('kind') not in ('pcb', 'schematic'):
        raise ValueError('Not a WayriCAD Embed3D extraction folder')
    hashes = meta.get('files')
    if not isinstance(hashes, dict) or len(hashes) > 30000:
        raise ValueError('Invalid extraction file manifest')
    data, total = {}, 0
    for name, digest in hashes.items():
        path = folder/checked_relative(name)
        _no_symlinks(path)
        value = read_bytes(path)
        total += len(value)
        if total > MAX_JOB_BYTES or sha256(value) != digest:
            raise ValueError('Extracted file changed, missing or corrupt: '+str(path)+'. Relink never silently substitutes edited assets.')
        data[name] = value
    if source is not None:
        verify_source(meta, source)
    return meta, data


def saved_project_variables(source: Path):
    """Read only the selected design's saved project variables, not another open project."""
    project = Path(source).with_suffix('.kicad_pro')
    if not project.is_file(): return {}
    raw = json.loads(read_bytes(project, 16*1024*1024))
    values = raw.get('text_variables', {})
    if not isinstance(values, dict): raise ValueError('Invalid project text_variables: '+str(project))
    return {str(k):str(v) for k,v in values.items() if k != 'KIPRJMOD' and isinstance(v,(str,int,float))}


def design_sidecars(source: Path):
    source = Path(source)
    files = {}
    for suffix in ('.kicad_pro', '.kicad_dru'):
        path = source.with_suffix(suffix)
        if path.is_file(): files[path.name] = read_bytes(path)
    for name in ('fp-lib-table', 'sym-lib-table'):
        path = source.parent/name
        if path.is_file(): files[name] = read_bytes(path)
    return files


def publish_design(folder: Path, files: dict[str, bytes], originals: dict[str, bytes],
                   details: dict, validate: Callable | None = None, cancelled=None):
    """Publish a NEW folder with untouched input snapshots and a restore report."""
    folder = Path(folder).absolute()
    _no_symlinks(folder)
    if folder.exists() or not folder.parent.is_dir():
        raise ValueError('Choose a NEW output folder under an existing parent')
    seen = set()
    for name in files:
        checked_relative(name)
        if name.casefold() in seen or name.split('/')[0].casefold() in ('wayricad embed3d-originals', 'wayricad embed3d-operation.json'):
            raise ValueError('Reserved or colliding design output: '+name)
        seen.add(name.casefold())
    if sum(map(len, files.values())) > 512*1024*1024:
        raise ValueError('Design output exceeds 512 MiB budget')
    staging = Path(tempfile.mkdtemp(prefix='.embed_3d_plugin-design-', dir=folder.parent))
    try:
        for name, data in files.items():
            path = staging/checked_relative(name); path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, data)
        backup = staging/'WayriCAD Embed3D-originals'; backup.mkdir()
        for name, data in originals.items():
            path = backup/checked_relative(name); path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(path, data)
        details = dict(details, plugin_version='0.4.1',
                       files={p: sha256(v) for p, v in files.items()},
                       original_sha256={p: sha256(v) for p, v in originals.items()})
        write_json(staging/'WayriCAD Embed3D-operation.json', details)
        if cancelled and cancelled(): raise InterruptedError('Cancelled before design publication')
        if validate: validate(staging)
        if folder.exists(): raise ValueError('Output folder appeared during validation; not overwritten')
        staging.rename(folder)
    finally:
        if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
    return folder
