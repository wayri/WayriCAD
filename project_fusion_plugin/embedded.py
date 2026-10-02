"""Preserve embedded payloads and isolate board-level attachment names.

Payload bytes/compression/checksums are retained verbatim. No model conversion or
font extraction is performed. Native KiCad still validates the saved files.
"""
from __future__ import annotations
import copy
import hashlib
from pathlib import PurePosixPath
from . import sexpr as sx
from .model import MergeError
from .paths import EMBED_SCHEMES


def filename(entry):
    name=sx.value(entry,'name')
    if not name and len(entry)>1 and isinstance(entry[1],str): name=str(entry[1])
    return name


def entries(node):
    result={}
    for entry in sx.children(sx.child(node,'embedded_files',['embedded_files'])):
        name=filename(entry)
        if not name or name in result:
            raise MergeError('Missing or duplicate embedded attachment name.')
        result[name]=entry
    return result


def reference_name(raw):
    for scheme in EMBED_SCHEMES:
        if str(raw).startswith(scheme): return str(raw)[len(scheme):]
    return None


def attach_symbol_resources(source):
    """A frozen library symbol must bring its schematic-owned files with it."""
    for lib_id,lib in source.libraries.items():
        local=entries(lib)
        references={reference_name(v) for n in sx.walk(lib) for v in n if isinstance(v,sx.Quoted)}-{None}
        for name in references-set(local):
            candidates=[]
            for sheet in source.sheets:
                if any(r.lib_id==lib_id for r in sheet.symbols):
                    found=entries(sheet.tree).get(name)
                    if found is not None: candidates.append(found)
            if not candidates:
                raise MergeError(f'{source.alias}: frozen symbol {lib_id} refers to missing embedded file {name!r}.')
            if len({sx.dumps(n) for n in candidates})!=1:
                raise MergeError(f'{source.alias}: {lib_id} sees different payloads for embedded {name!r} in different sheets; disambiguate this source library first.')
            target=sx.child(lib,'embedded_files')
            if target is None: target=sx.put(lib,'embedded_files')
            target.append(copy.deepcopy(candidates[0]))


def namespace_board(source):
    """Promote footprint payloads to native board scope and rename references."""
    mapping={}
    for old,entry in entries(source.board).items():
        # Embedded font families are discovered by native KiCad. Keep their
        # original filenames; existing conflict checking rejects unlike fonts.
        if sx.value(entry,'type').casefold()=='font': continue
        safe=PurePosixPath(old.replace('\\','/')).name
        new=source.alias+'__'+hashlib.sha256(str(PurePosixPath(old).with_suffix('')).encode()).hexdigest()[:8]+'__'+safe
        mapping[old]=new
        name=sx.child(entry,'name')
        if name is not None: name[1]=sx.q(new)
        else: entry[1]=sx.q(new)
    def visit(node,active,isroot=False):
        active=dict(active)
        if not isroot and sx.tag(node)=='footprint':
            local=entries(node)
            for old,entry in local.items():
                # Native placed footprints may carry checksum-only manifests.
                # These inherit the board payload and must not shadow its rename.
                if sx.child(entry,'data') is None:
                    inherited=entries(source.board).get(active.get(old,old))
                    if inherited is None or sx.value(inherited,'checksum')!=sx.value(entry,'checksum'):
                        raise MergeError(f'{source.alias}: footprint embedded manifest has no matching board payload: {old}')
                    continue
                safe=PurePosixPath(old.replace('\\','/')).name
                new=source.alias+'__FP__'+hashlib.sha256(sx.dumps(entry).encode()).hexdigest()[:8]+'__'+safe
                promoted=copy.deepcopy(entry)
                name=sx.child(promoted,'name')
                if name is not None:name[1]=sx.q(new)
                else:promoted[1]=sx.q(new)
                target=sx.child(source.board,'embedded_files')
                if target is None:target=sx.put(source.board,'embedded_files')
                existing=entries(source.board).get(new)
                if existing is not None and sx.dumps(existing)!=sx.dumps(promoted):
                    raise MergeError('Embedded payload promotion name collision.')
                if existing is None:target.append(promoted)
                active[old]=new
            # Board-native save does not retain footprint-local payloads.
            sx.remove(node,'embedded_files')
        for i,value in enumerate(node):
            if isinstance(value,list):
                if sx.tag(value)!='embedded_files': visit(value,active)
            elif isinstance(value,sx.Quoted):
                old=reference_name(value)
                if old in active:
                    scheme=next(s for s in EMBED_SCHEMES if str(value).startswith(s))
                    node[i]=sx.q(scheme+active[old])
    visit(source.board,mapping,True)
    source.board_embedded_map=mapping


def validate_scopes(tree,context='document'):
    """Check direct embedded references; derived symbols may inherit assets."""
    def visit(node,scope):
        scope={**scope,**{name:entry for name,entry in entries(node).items() if sx.child(entry,'data') is not None}}
        derived=sx.tag(node)=='symbol' and sx.child(node,'extends') is not None
        for value in node:
            if isinstance(value,list):
                if sx.tag(value)!='embedded_files': visit(value,scope)
            elif isinstance(value,sx.Quoted):
                name=reference_name(value)
                if name is not None and name not in scope and not derived:
                    raise MergeError(f'{context}: unresolved embedded reference {value!r}.')
    visit(tree,{})


def transfer_symbol_fields(fp,record,source):
    """Bring embedded datasheets/SPICE fields copied from a symbol to its PCB part."""
    scope=entries(record.sheet.tree)
    scope.update(entries(source.libraries.get(record.lib_id,['symbol'])))
    scope.update(entries(record.node))
    target_entries=entries(fp)
    for field in sx.children(record.node,'property'):
        offset=2 if len(field)>1 and field[1]=='private' and not isinstance(field[1],sx.Quoted) else 1
        if len(field)<=offset+1: continue
        name=reference_name(field[offset+1])
        if name is None: continue
        payload=scope.get(name)
        if payload is None:
            raise MergeError(f'{source.alias}: {record.old_ref} field {field[offset]} refers to missing embedded file {name!r}.')
        if name in target_entries and sx.dumps(target_entries[name])!=sx.dumps(payload):
            raise MergeError(f'{source.alias}: schematic and footprint have unlike embedded {name!r}; rename one resource in a source copy first.')
        if name not in target_entries:
            target=sx.child(fp,'embedded_files')
            if target is None: target=sx.put(fp,'embedded_files')
            target.append(copy.deepcopy(payload)); target_entries[name]=payload
