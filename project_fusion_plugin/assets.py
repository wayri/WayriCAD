"""Offline dependency collection, local library tables and path rebasing.

Only input/local files are read. No URI is downloaded and no source is modified.
Explicit project libraries are copied in full; installed global libraries are
trimmed to referenced footprints. Cached schematic definitions remain the design
truth, with separate full local-library snapshots for subsequent library edits.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from . import sexpr as sx
from .model import MergeError
from .paths import resolve_asset, config_directories, variable_context, EMBED_SCHEMES, REMOTE

MAX_FILES = 60000
MAX_BYTES = 12 * 1024**3
SKIP_DIRS = {'.git', '.svn', '__pycache__', 'node_modules', '.venv', 'venv'}
PATH_FIELDS = {'datasheet', 'sim.library', 'spice_lib_file', 'spice_library', 'model_file', 'modelpath', '3dmodel', 'worksheet', 'page_layout_descr_file'}
ASSET_SUFFIXES = {'.step','.stp','.wrl','.vrml','.iges','.igs','.idf','.emn','.emp','.pdf','.kicad_wks','.cir','.spice','.mod','.sub','.subckt','.png','.jpg','.jpeg','.svg','.dxf'}


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def nickname(alias,kind,name):
    safe=re.sub(r'[^A-Za-z0-9_]','_',str(name))[:48]
    return f'Fusion_{alias}_{kind}_{safe}_{hashlib.sha256(str(name).encode()).hexdigest()[:8]}'


def table_entry(name,uri,description='Copied dependency'):
    return ['lib',['name',sx.q(name)],['type',sx.q('KiCad')],['uri',sx.q(uri)],['options',sx.q('')],['descr',sx.q(description)]]


def iter_files(root):
    """Bound traversal and follow directory links without recursive link loops."""
    visited=set(); count=0
    def visit(path):
        nonlocal count
        real=path.resolve()
        if real in visited:
            return
        visited.add(real)
        for p in sorted(path.iterdir(),key=lambda p:p.name.casefold()):
            count+=1
            if count>MAX_FILES:
                raise MergeError(f'Asset tree exceeds {MAX_FILES} entries: {root}')
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.endswith('-backups'):
                    yield from visit(p)
            elif p.is_file():
                yield p
    yield from visit(Path(root))


class Collector:
    def __init__(self,source,output,log,strict=True,copy_assets=True):
        self.source=source; self.output=Path(output); self.log=log; self.strict=strict
        self.copy_assets=copy_assets
        self.copies={}; self.directory_copies={}; self.bytes=0; self.count=0
        self.processing=set(); self.destination_owners={}; self.tables={}; self.symbol_jobs=[]; self.fp_jobs=[]

    def record(self,raw,status,**kw):
        item={'source':self.source.alias,'reference':str(raw),'status':status,**kw}
        if item not in self.source.asset_manifest:
            self.source.asset_manifest.append(item)
        return item

    def missing(self,raw,kind):
        self.record(raw,'unresolved',kind=kind)
        message=f'{self.source.alias}: unresolved {kind}: {raw!r}. Define a source path variable/remap or restore the file.'
        if self.strict:
            raise MergeError(message)
        self.log('WARNING: '+message+' Output is NOT self-contained.')
        return str(raw)

    def remember(self,p):
        p=Path(p).resolve(); digest=sha256(p)
        previous=self.source.hashes.get(str(p))
        if previous is not None and previous!=digest:
            raise MergeError(f'Asset changed while being read: {p}')
        self.source.files.add(p); self.source.hashes[str(p)]=digest
        return digest

    def local_ref(self,relative):
        return '${KIPRJMOD}/'+str(relative).replace('\\','/')

    def external_ref(self,path,kind,*,members=None):
        """Retain a resolved source path and pin every consumed file's hash."""
        path=Path(path).resolve()
        if path.is_file():
            digest=self.remember(path)
            self.record(path,'external',kind=kind,external=True,
                        source_path=path.as_posix(),sha256=digest)
        elif path.is_dir():
            files=iter_files(path) if members is None else members
            for member in files:
                if not member.is_file():
                    self.missing(str(member),kind+' member')
                    continue
                digest=self.remember(member)
                self.record(member,'external',kind=kind+' member',external=True,
                            source_path=member.resolve().as_posix(),sha256=digest)
            self.record(path,'external-directory',kind=kind,external=True,
                        source_path=path.as_posix())
        else:
            return self.missing(str(path),kind)
        self.log(f'WARNING: {self.source.alias}: {kind} remains external at {path}; the output depends on this source path.')
        return path.as_posix()

    def destination(self,path,kind='files'):
        # Folder hash, not file hash: .wrl/.step names stay siblings and relative
        # dependency basenames survive. Separate folders also avoid name clashes.
        path=Path(path).resolve()
        folder=hashlib.sha256(str(path.parent).encode()).hexdigest()[:16]
        safe=re.sub(r'[<>:"|?*\\]','_',path.name)
        return Path('assets')/self.source.alias/kind/folder/safe

    def copy_file(self,path,relative=None,kind='file'):
        path=Path(path).resolve()
        if path in self.copies:
            previous=self.copies[path]
            if relative is not None and self.local_ref(relative)!=previous:
                rel=Path(relative)
                if rel.is_absolute() or '..' in rel.parts: raise MergeError('Unsafe duplicate asset destination.')
                target=self.output/rel; target.parent.mkdir(parents=True,exist_ok=True)
                # Copy original, then rebase text references for the new location.
                shutil.copy2(path,target)
                self.record(path,'copied',kind=kind,destination=rel.as_posix(),sha256=self.remember(path))
                if path.suffix.lower() in {'.cir','.spice','.sub','.subckt','.mod','.lib','.wrl','.vrml','.obj','.mtl'}:
                    self.rewrite_secondary(path,target)
                return self.local_ref(rel)
            return previous
        if not path.is_file():
            return self.missing(str(path),kind)
        self.count+=1; self.bytes+=path.stat().st_size
        if self.count>MAX_FILES or self.bytes>MAX_BYTES:
            raise MergeError('Dependency copy exceeds 60,000 files or 12 GiB per source; narrow explicit asset folders.')
        rel=Path(relative) if relative is not None else self.destination(path)
        if rel.is_absolute() or '..' in rel.parts:
            raise MergeError('Unsafe asset destination.')
        dest=self.output/rel
        key=rel.as_posix().casefold()
        owner=self.destination_owners.get(key)
        if owner is not None and owner!=path:
            raise MergeError(f'Case-insensitive output asset collision: {owner} and {path}')
        self.destination_owners[key]=path
        dest.parent.mkdir(parents=True,exist_ok=True)
        digest=self.remember(path)
        self.copies[path]=self.local_ref(rel)
        shutil.copy2(path,dest)
        self.record(path,'copied',kind=kind,destination=rel.as_posix(),sha256=digest)
        # Resolve file-internal secondary references while preserving relative
        # evaluation in formats that do not understand ${KIPRJMOD} themselves.
        if path.suffix.lower() in {'.cir','.spice','.sub','.subckt','.mod','.lib','.wrl','.vrml','.obj','.mtl'}:
            self.rewrite_secondary(path,dest)
        # KiCad's WRL->STEP export substitution depends on SAME basename/folder.
        if path.suffix.lower() in {'.wrl','.vrml','.step','.stp'}:
            for sibling in path.parent.iterdir():
                if sibling.is_file() and sibling.stem.casefold()==path.stem.casefold() and sibling.suffix.lower() in {'.wrl','.vrml','.step','.stp'} and sibling.resolve()!=path:
                    self.copy_file(sibling,rel.parent/sibling.name,'3D companion')
        return self.copies[path]

    def rewrite_secondary(self,path,dest):
        try:
            text=path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            return
        def replace_ref(raw):
            if REMOTE.match(raw):
                self.record(raw,'external-uri',kind='secondary dependency'); return raw
            dependency=resolve_asset(raw,self.source,path.parent)
            if dependency is None or not dependency.is_file():
                self.missing(raw,f'dependency in {path.name}'); return raw
            uri=self.copy_file(dependency,kind='secondary dependency')
            local=self.output/uri.removeprefix('${KIPRJMOD}/')
            return os.path.relpath(local,dest.parent).replace('\\','/')
        if path.suffix.lower() in {'.wrl','.vrml'}:
            pattern=re.compile(r'(\burl\s*(?:\[\s*)?)("[^"\r\n]+")',re.I)
            text=pattern.sub(lambda m:m[1]+'"'+replace_ref(m[2][1:-1])+'"',text)
        elif path.suffix.lower() in {'.obj','.mtl'}:
            text=re.sub(r'(?im)^(\s*(?:mtllib|map_Kd|map_Ka|bump)\s+)([^\r\n]+)',lambda m:m[1]+replace_ref(m[2].strip()),text)
        else:
            pattern=re.compile(r'(?im)^(\s*\.(?:include|inc|lib)\s+)("[^"]+"|\x27[^\x27]+\x27|[^\s;]+)')
            def replace(m):
                token=m[2]; raw=token[1:-1] if token.startswith(('"',"'")) else token
                # A .lib section declaration has a section name, not a filename.
                if m[1].strip().lower()=='.lib' and not any(c in raw for c in './\\${%'):
                    return m[0]
                return m[1]+'"'+replace_ref(raw)+'"'
            text=pattern.sub(replace,text)
        dest.write_text(text,encoding='utf-8')

    def copy_directory(self,path,kind='directory'):
        path=Path(path).resolve()
        if path in self.directory_copies:
            return self.directory_copies[path]
        if path==self.output.resolve() or path in self.output.resolve().parents:
            raise MergeError('An asset folder contains the staged output; choose a separate output parent to avoid copying output back into itself.')
        if not path.is_dir():
            return self.missing(str(path),kind)
        rel=Path('assets')/self.source.alias/'folders'/hashlib.sha256(str(path).encode()).hexdigest()[:16]/path.name
        uri=self.local_ref(rel); self.directory_copies[path]=uri
        for p in iter_files(path):
            self.copy_file(p,rel/p.relative_to(path),kind)
        self.record(path,'copied-directory',kind=kind,destination=rel.as_posix())
        return uri

    def link(self,raw,relative,kind='asset',required=True):
        raw=str(raw)
        if not raw or raw in {'~','-'}:
            return raw
        if raw.startswith(EMBED_SCHEMES):
            self.record(raw,'embedded',kind=kind); return raw
        if REMOTE.match(raw):
            self.record(raw,'external-uri',kind=kind)
            if kind in {'3D model','footprint library','symbol library','simulation model','explicit asset'}:
                return self.missing(raw,kind+' (remote fetching is disabled)')
            return raw
        path=resolve_asset(raw,self.source,relative)
        external_model=(not self.copy_assets and kind.casefold() in
                        {'3d model','field 3dmodel','field modelpath'})
        if path is not None and path.is_file():
            return self.external_ref(path,kind) if external_model else self.copy_file(path,kind=kind)
        if path is not None and path.is_dir():
            return self.external_ref(path,kind) if external_model else self.copy_directory(path,kind)
        if required:
            retained=self.missing(raw,kind)
            return path.as_posix() if path is not None and not self.strict else retained
        return raw

    def rewrite_tree(self,tree,relative):
        for node in sx.walk(tree):
            tag=sx.tag(node)
            if tag=='model' and len(node)>1:
                node[1]=sx.q(self.link(node[1],relative,'3D model'))
            elif tag=='property':
                index=2 if len(node)>1 and node[1]=='private' and not isinstance(node[1],sx.Quoted) else 1
                if len(node)<=index+1: continue
                name,raw=str(node[index]).casefold(),str(node[index+1])
                if name in {'footprint','reference','value','sheetfile','sheet file'}: continue
                candidate=resolve_asset(raw,self.source,relative) if raw and not raw.startswith(EMBED_SCHEMES) and not REMOTE.match(raw) else None
                path_syntax=bool(re.match(r'^(?:[A-Za-z]:[/\\]|/|\.\.?[/\\]|file://|\$\{[^}]+\}[/\\]|%[^%]+%[/\\])',raw))
                # A bare part number in Datasheet is metadata, not a missing file.
                # Explicit paths and document filenames remain required assets.
                explicit=(name in PATH_FIELDS and (name!='datasheet' or path_syntax or Path(raw).suffix.casefold() in ASSET_SUFFIXES)) or path_syntax
                exists=candidate is not None and candidate.is_file()
                if explicit or exists:
                    kind='simulation model' if name in {'sim.library','spice_lib_file','spice_library'} else 'field '+str(node[index])
                    node[index+1]=sx.q(self.link(raw,relative,kind))
            elif tag in {'page_layout_descr_file','worksheet'} and len(node)>1:
                node[1]=sx.q(self.link(node[1],relative,'worksheet'))

    def load_tables(self,kind):
        filename=kind+'-lib-table'; entries={}
        for cfg in reversed(config_directories()):
            p=cfg/filename
            if p.is_file():
                tree=sx.load(p,self.source.hashes); self.source.files.add(p.resolve())
                for e in sx.children(tree,'lib'):
                    entries[sx.value(e,'name')]=(e,p.parent,False)
        p=self.source.project_file.parent/filename
        if p.is_file():
            tree=sx.load(p,self.source.hashes); self.source.files.add(p.resolve())
            seen=set()
            for e in sx.children(tree,'lib'):
                name=sx.value(e,'name')
                if not name or name in seen:
                    raise MergeError(f'{self.source.alias}: duplicate/empty {filename} library name.')
                seen.add(name); entries[name]=(e,p.parent,True)
        self.tables[kind]=entries
        return entries

    def locate_library(self,kind,nick):
        record=self.tables[kind].get(nick)
        if record:
            entry,relative,local=record
            if sx.value(entry,'type')!='KiCad':
                self.missing(sx.value(entry,'uri'),kind+' library type '+sx.value(entry,'type')); return None,local
            return resolve_asset(sx.value(entry,'uri'),self.source,relative),local
        context=variable_context(self.source)
        for version in ('10','9','8'):
            base=context.get(f'KICAD{version}_{"FOOTPRINT" if kind=="fp" else "SYMBOL"}_DIR')
            if base:
                p=resolve_asset(base,self.source,self.source.project_file.parent)
                if p:
                    p=p/(nick+('.pretty' if kind=='fp' else '.kicad_sym'))
                    if p.exists(): return p,False
        return None,False

    def footprint_library(self,nick,path,full,items,table):
        if path is None or not path.is_dir():
            return self.missing(nick,'footprint library')
        new=nickname(self.source.alias,'FP',nick)
        previous=self.source.fp_lib_map.get(nick)
        if previous and previous!=new:
            raise MergeError('Conflicting footprint library mapping.')
        self.source.fp_lib_map[nick]=new
        rel=Path('libraries')/(new+'.pretty')
        files=list(iter_files(path)) if full else [path/(item+'.kicad_mod') for item in sorted(items)]
        # A source library can be referenced in place unless its contents must
        # change for the combined project's layer map or project-relative paths.
        generated=bool(self.source.layer_map)
        if not self.copy_assets:
            for fp in files:
                if not fp.is_file():
                    self.missing(str(fp),'footprint')
                    continue
                if fp.suffix.lower()!='.kicad_mod': continue
                tree=sx.load(fp,self.source.hashes)
                for node in sx.walk(tree):
                    if sx.tag(node)=='model' and len(node)>1:
                        raw=str(node[1])
                        model=resolve_asset(raw,self.source,fp.parent)
                        if model is None or not model.is_file():
                            self.missing(raw,'3D model')
                        elif not Path(raw).is_absolute():
                            generated=True
                        else:
                            self.external_ref(model,'3D model')
            if not generated:
                self.external_ref(path,'footprint library',members=files)
                table.append(table_entry(new,path.resolve().as_posix(),'External source footprint library'))
                for fp in files:
                    if fp.is_file() and fp.suffix.lower()=='.kicad_mod':
                        self.source.fp_id_map[nick+':'+fp.stem]=new+':'+fp.stem
                return
        table.append(table_entry(new,self.local_ref(rel),'Copied full source library' if full else 'Referenced installed footprints'))
        if not self.copy_assets:
            self.record(path,'generated-repair',kind='footprint library',generated=True,
                        reason='layer mapping or model-path rebasing',destination=rel.as_posix())
        for fp in files:
            if not fp.is_file():
                self.missing(str(fp),'footprint'); continue
            target=rel/fp.relative_to(path)
            self.copy_file(fp,target,'footprint library member')
            if fp.suffix.lower()=='.kicad_mod':
                tree=sx.load(fp,self.source.hashes); self.rewrite_tree(tree,fp.parent)
                if fp.stem in items and self.source.layer_map:
                    from .layers import remap_item
                    remap_item(tree,self.source)
                sx.save(self.output/target,tree)
                self.source.fp_id_map[nick+':'+fp.stem]=new+':'+fp.stem
        self.record(path,'copied-directory' if full else 'copied-used-members',kind='footprint library',destination=rel.as_posix())

    def symbol_library(self,nick,path,table):
        if path is None or (not path.is_dir() and (not path.is_file() or path.suffix.lower()!='.kicad_sym')):
            return self.missing(nick,'symbol library')
        new=nickname(self.source.alias,'SYM',nick)
        if not self.copy_assets:
            self.external_ref(path,'symbol library')
            table.append(table_entry(new,path.resolve().as_posix(),'External source symbol library'))
            jobs=[]
            members=iter_files(path) if path.is_dir() else [path]
            for member in members:
                if member.suffix.lower()=='.kicad_sym':
                    tree=sx.load(member,self.source.hashes)
                    self.symbol_jobs.append((tree,member.parent,None))
                    jobs.append(tree)
            return jobs if path.is_dir() else jobs[0]
        if path.is_dir():
            rel=Path('libraries')/(new+'.kicad_symdir')
            table.append(table_entry(new,self.local_ref(rel),'Full unpacked source symbol library'))
            jobs=[]
            for member in iter_files(path):
                target=rel/member.relative_to(path)
                self.copy_file(member,target,'unpacked symbol library member')
                if member.suffix.lower()=='.kicad_sym':
                    tree=sx.load(member,self.source.hashes); self.symbol_jobs.append((tree,member.parent,target)); jobs.append(tree)
            return jobs
        rel=Path('libraries')/(new+'.kicad_sym')
        self.copy_file(path,rel,'full symbol library')
        tree=sx.load(path,self.source.hashes)
        self.symbol_jobs.append((tree,path.parent,rel))
        table.append(table_entry(new,self.local_ref(rel),'Original full local symbol library; active designs use frozen caches'))
        return tree

    def project_paths(self):
        result=copy.deepcopy(self.source.project)
        # Editor-history/output destinations are not source dependencies.
        for k in ('last_paths','recent_files','recent_files_list'):
            result.pop(k,None)
        def walk(value):
            if isinstance(value,dict):
                for key,child in list(value.items()):
                    if isinstance(child,str) and child and key in {'page_layout_descr_file','worksheet','drawing_sheet','spice_lib_file','model_file'}:
                        value[key]=self.link(child,self.source.project_file.parent,'project '+key)
                    else: walk(child)
            elif isinstance(value,list):
                for child in value: walk(child)
        walk(result)
        variables=result.get('text_variables',{})
        for key,raw in list(variables.items()):
            path=resolve_asset(raw,self.source,self.source.project_file.parent)
            if path == self.source.project_file.parent.resolve():
                # References through this root must still resolve to an archived
                # source tree; do not redirect them to a different project root.
                variables[key]=self.copy_directory(path,'project root path variable '+key)
            elif path is not None and path.exists():
                variables[key]=self.link(raw,self.source.project_file.parent,'project path variable '+key)
        self.source.portable_project=result


def prepare_assets(sources,output,log,strict=True,copy_assets=True):
    fp_table=['fp_lib_table',['version','7']]; sym_table=['sym_lib_table',['version','7']]
    for s in sources:
        from .embedded import attach_symbol_resources, namespace_board
        attach_symbol_resources(s)
        c=Collector(s,output,log,strict,copy_assets)
        c.load_tables('fp'); c.load_tables('sym')
        sym_table.append(table_entry('Fusion_'+s.alias,'${KIPRJMOD}/libraries/Fusion_'+s.alias+'.kicad_sym','Frozen source symbol definitions'))
        c.record('cached schematic definitions','generated',kind='frozen active symbol library',
                 generated=True,destination='libraries/Fusion_'+s.alias+'.kicad_sym')
        # Discover local libraries even when not currently registered. Do not
        # copy unrelated documents/build trees or the whole KiCad installation.
        local_fp={}; local_sym={}
        for root,dirs,files in os.walk(s.project_file.parent,followlinks=False):
            dirs[:]=[d for d in dirs if d not in SKIP_DIRS and not d.endswith('-backups')]
            for directory in list(dirs):
                if directory.lower().endswith('.pretty'):
                    p=Path(root)/directory; local_fp[str(p.resolve())]=p; dirs.remove(directory)
                elif directory.lower().endswith('.kicad_symdir'):
                    p=Path(root)/directory; local_sym[str(p.resolve())]=p; dirs.remove(directory)
            for name in files:
                if name.lower().endswith('.kicad_sym'):
                    p=Path(root)/name; local_sym[str(p.resolve())]=p
            if len(local_fp)+len(local_sym)>MAX_FILES:
                raise MergeError('Too many local libraries.')
        # Registered project libraries, including ones outside KIPRJMOD.
        sym_paths={}
        for nick,(entry,relative,local) in c.tables['sym'].items():
            if local:
                path,_=c.locate_library('sym',nick)
                tree=c.symbol_library(nick,path,sym_table)
                if path: sym_paths[str(path.resolve())]=nick
        for path in local_sym.values():
            if str(path.resolve()) not in sym_paths:
                nick='local_'+path.stem+'_'+hashlib.sha256(str(path).encode()).hexdigest()[:8]
                c.symbol_library(nick,path,sym_table)
        # Used footprint IDs include cached defaults and all members of copied
        # local symbol libraries, not only the selected population's symbols.
        wanted={}
        nodes=[s.board,*[sheet.tree for sheet in s.sheets],*[lib for lib in s.libraries.values()],*[job[0] for job in c.symbol_jobs]]
        for tree in nodes:
            for node in sx.walk(tree):
                identifier=str(node[1]) if sx.tag(node)=='footprint' and len(node)>1 else sx.propval(node,'Footprint')
                if identifier and ':' in identifier:
                    nick,item=identifier.split(':',1)
                    if any(x in item for x in ('/','\\','..')):
                        raise MergeError('Unsafe footprint library item name.')
                    wanted.setdefault(nick,set()).add(item)
        fp_paths={}
        for nick,(entry,relative,local) in c.tables['fp'].items():
            if local or nick in wanted:
                path,is_local=c.locate_library('fp',nick)
                c.footprint_library(nick,path,is_local,wanted.pop(nick,set()),fp_table)
                if path: fp_paths[str(path.resolve())]=nick
        for nick,items in wanted.items():
            path,local=c.locate_library('fp',nick)
            c.footprint_library(nick,path,local,items,fp_table)
            if path: fp_paths[str(path.resolve())]=nick
        for path in local_fp.values():
            if str(path.resolve()) not in fp_paths:
                nick='local_'+path.stem+'_'+hashlib.sha256(str(path).encode()).hexdigest()[:8]
                c.footprint_library(nick,path,True,set(),fp_table)
        from .schematic import remap_footprint_id
        for tree,relative,rel in c.symbol_jobs:
            if rel is None: continue  # Source-owned external library is read only.
            c.rewrite_tree(tree,relative)
            for node in sx.walk(tree):
                field=sx.prop(node,'Footprint')
                if field is not None: field[2]=sx.q(remap_footprint_id(str(field[2]),s))
            sx.save(Path(output)/rel,tree)
        for sheet in s.sheets: c.rewrite_tree(sheet.tree,sheet.source_path.parent)
        for lib in s.libraries.values(): c.rewrite_tree(lib,s.project_file.parent)
        c.rewrite_tree(s.board,s.project_file.parent)
        # Keep ordinary library IDs (not per-reference snapshots) as the update
        # targets. Placed geometry is already retained verbatim in the board;
        # per-reference library IDs would change the source XML comparison.
        for raw in s.spec.extra_asset_paths:
            c.link(raw,s.project_file.parent,'explicit asset')
        namespace_board(s)
        for old,new in s.board_embedded_map.items():
            c.record('kicad-embed://'+old,'embedded',kind='board attachment',destination_reference='kicad-embed://'+new)
        c.project_paths()
        # The PCB worksheet is project-owned but refers to a board attachment.
        pcb_settings=s.portable_project.get('pcbnew',{})
        raw=pcb_settings.get('page_layout_descr_file','')
        from .embedded import reference_name
        if reference_name(raw) in s.board_embedded_map:
            pcb_settings['page_layout_descr_file']='kicad-embed://'+s.board_embedded_map[reference_name(raw)]
        external=sum(x.get('external',False) for x in s.asset_manifest)
        log(f'{s.alias}: copied {c.count} dependency files; {external} external dependency records; {sum(x["status"]=="unresolved" for x in s.asset_manifest)} unresolved references.')
    for table in (fp_table,sym_table):
        names=[sx.value(e,'name').casefold() for e in sx.children(table,'lib')]
        if len(names)!=len(set(names)): raise MergeError('Output library nickname collision; nothing was published.')
    sx.save(Path(output)/'fp-lib-table',fp_table); sx.save(Path(output)/'sym-lib-table',sym_table)


def audit_assets(sources,output):
    """Verify every emitted local reference recorded by collection resolves."""
    output=Path(output)
    records=[r for s in sources for r in s.asset_manifest]
    for r in records:
        if r['status'] in {'copied','copied-directory','copied-used-members','generated','generated-repair'}:
            p=output/r['destination']
            if not p.exists(): raise MergeError(f'Generated or copied dependency is missing: {p}')
            if p.is_file(): r['output_sha256']=sha256(p)
        elif r['status']=='external':
            p=Path(r['source_path'])
            if not p.is_file() or sha256(p)!=r['sha256']:
                raise MergeError(f'External dependency changed or disappeared: {p}')
        elif r['status']=='external-directory':
            p=Path(r['source_path'])
            if not p.is_dir():
                raise MergeError(f'External dependency directory disappeared: {p}')
    # Every explicit KIPRJMOD asset/library URI in emitted KiCad files is checked
    # after all libraries and schematics have been written, not only when copied.
    for path in output.rglob('*'):
        if path.relative_to(output).parts[0]=='assets': continue  # archived auxiliary trees are not active projects
        if path.is_file() and (path.suffix in {'.kicad_sch','.kicad_pcb','.kicad_sym','.kicad_mod'} or path.name in {'fp-lib-table','sym-lib-table'}):
            tree=sx.load(path)
            if path.suffix in {'.kicad_pcb','.kicad_sch','.kicad_mod'} or path.name.startswith('Fusion_') and path.suffix=='.kicad_sym' and not any(sx.child(n,'extends') is not None for n in sx.children(tree,'symbol')):
                from .embedded import validate_scopes
                validate_scopes(tree,path.name)
            for node in sx.walk(tree):
                for atom in node:
                    if isinstance(atom,sx.Quoted) and str(atom).startswith('${KIPRJMOD}/'):
                        rel=str(atom)[len('${KIPRJMOD}/'):]
                        if '${' not in rel and not (output/rel).exists():
                            raise MergeError(f'Output local dependency does not exist: {atom} in {path.name}')
    external_count=sum(r.get('external',False) for r in records)
    return {'records':records,'unresolved_count':sum(r['status']=='unresolved' for r in records),
            'external_uri_count':sum(r['status']=='external-uri' for r in records),
            'external_count':external_count,
            'generated_count':sum(r.get('generated',False) for r in records),
            'self_contained':not external_count and not any(r['status']=='unresolved' for r in records),
            'resolved_recorded_local_assets':not any(r['status']=='unresolved' for r in records)}
