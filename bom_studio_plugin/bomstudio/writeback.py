"""Explicit, reviewed native handoff. No editor-memory or PCB writes.

A file transaction is not power-loss atomic across multiple files. Backups and a
manifest are durable before the first replace. Ordinary exceptions roll back.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import difflib
import json
import os
import re
import tempfile
from .engine import Workspace, now
from .native import BASE, FLAGS, SAFE_VERSION, Project, read_flags, variants, variant_lookup, sha, is_generated_field
from .enforcement import schema_symbol_edits
from .sexpr import apply_edits, properties, quote, parse


def _variant_text(name,fields,flags):
    if not fields and not flags:return ''
    parts=['(variant (name '+quote(name)+')']
    parts += ['('+k+' '+('yes' if v else 'no')+')' for k,v in flags.items()]
    parts += ['(field (name '+quote(k)+') (value '+quote(v)+'))' for k,v in sorted(fields.items())]
    return ' '.join(parts)+')'


def _update_variant(edits,doc,instance,name,fields,flags):
    existing=next((n for n in instance.nodes('variant') if n.get('name').casefold()==name.casefold()),None)
    if existing:
        old,unknown=variants(instance,doc.version)
        value=variant_lookup(old,name,{})
        if value.get('fields',{})==fields and value.get('flags',{})==flags:return
    text=_variant_text(name,fields,flags)
    if existing:edits.append((existing.start,existing.end,text))
    elif text:edits.append((instance.end-1,instance.end-1,'\n        '+text+'\n      '))


def compile_plan(ws: Workspace):
    p=ws.project;p.check_unchanged()
    syncable={name:v for name,v in ws.state['variants'].items() if not v.get('bom_only')}
    if not p.status()['native_write_supported']:
        raise ValueError('Native sync requires supported KiCad 10 format 20260306, complete instance paths, and no adapter blockers. See Checks.')
    if ws.state.get('source_hashes') and ws.state['source_hashes']!=p.hashes:
        raise ValueError('Workspace/source baseline differs. Review and acknowledge the reopened source files before native sync.')
    if ws.state['variables'] or any(v.get('variables') for v in syncable.values()):
        raise ValueError('Workspace/variant-scoped variables are export-only in this preview. Move them to Project variables or clear them before native sync; expressions are never silently baked into schematic fields.')
    if not p.pro_path.exists():
        raise ValueError('Save a .kicad_pro alongside the root schematic in KiCad before native sync.')
    for name in [BASE]+list(syncable):
        for component in p.components:
            fields,_,_=ws.own(component,name)
            if any(is_generated_field(k) and v!=k for k,v in fields.items()):
                raise ValueError('Generated KiCad fields require value == name expression. Repair conflicting values explicitly before native sync.')
            if any(re.search(r'\$\{(?:PROJECT|FIELD):',str(value)) for value in [*fields,*fields.values()]):
                raise ValueError('WayriCAD-only PROJECT:/FIELD: expressions in schematic fields cannot be synced natively. Use native-compatible expressions or keep the values in export templates.')
    edits=defaultdict(list);seen=set()
    for c in p.components:
        bf,bflags,_=ws.own(c,BASE)
        for m in c.members:
            key=(str(m.doc.path),m.symbol.start)
            if key not in seen:
                seen.add(key);props=properties(m.symbol)
                schema=ws.state.get('field_schema_edits',{}).get(BASE,{}).get(c.id)
                if schema:
                    schema=deepcopy(schema);schema['fields']=bf
                    edits[m.doc.path].extend(schema_symbol_edits(m,schema))
                for field,value in ws.state['base'].get(c.id,{}).items():
                    if field in FLAGS:
                        old=m.symbol.one(field)
                        if old and read_flags(m.symbol)[field]==value:continue
                        text='('+field+' '+('yes' if value else 'no')+')'
                        edits[m.doc.path].append((old.start,old.end,text) if old else (m.symbol.end-1,m.symbol.end-1,'\n    '+text))
                    elif schema:
                        continue
                    elif field in props:
                        original,_,atom=props[field]
                        if original!=value:edits[m.doc.path].append((atom.start,atom.end,quote(value)))
                    else:
                        at=m.symbol.one('at');x=at.val(1,'0') if at else '0';y=at.val(2,'0') if at else '0'
                        prop=f'\n    (property {quote(field)} {quote(value)} (at {x} {y} 0) (hide yes))\n  '
                        edits[m.doc.path].append((m.symbol.end-1,m.symbol.end-1,prop))
            for name in syncable:
                f,flags,_=ws.own(c,name)
                fields={k:v for k,v in f.items() if k!='Reference' and v!=bf.get(k,'')}
                diff={k:v for k,v in flags.items() if v!=bflags[k]}
                _update_variant(edits[m.doc.path],m.doc,m.instance,name,fields,diff)
    # Inherited variants also inherit ancestor-sheet exclusions. Flatten those
    # differentials natively, rather than trying to override them at symbol level.
    for doc,sheet,inst,path in p.sheet_records:
        if inst is None:raise ValueError('Missing hierarchical sheet instance; native sync blocked.')
        native,_=variants(inst,doc.version);base_flags=read_flags(sheet)
        base_fields={k:v[0] for k,v in properties(sheet).items()}
        for name in syncable:
            flags=dict(base_flags);fields=dict(base_fields)
            for v in ws.variant_chain(name):
                delta=variant_lookup(native,v,{})
                flags.update(delta.get('flags',{}));fields.update(delta.get('fields',{}))
            _update_variant(edits[doc.path],doc,inst,name,
                            {k:v for k,v in fields.items() if v!=base_fields.get(k,'')},
                            {k:v for k,v in flags.items() if v!=base_flags[k]})
    candidate={};changes=[]
    for path,changeset in edits.items():
        doc=p.documents[path];text=apply_edits(doc.text,changeset)
        if text==doc.text:continue
        tree=parse(text)
        if tree.get('uuid')!=doc.tree.get('uuid') or int(tree.get('version'))!=SAFE_VERSION:
            raise ValueError('Candidate file UUID/version failed validation.')
        data=text.encode('utf-8')
        if doc.data.startswith(b'\xef\xbb\xbf'):data=b'\xef\xbb\xbf'+data
        candidate[path]=data
    pro=deepcopy(p.pro)
    variables=dict(pro.get('text_variables',{}))
    for k,v in ws.state['project_variables'].items():
        if v is None:variables.pop(k,None)
        else:variables[k]=v
    if variables!=pro.get('text_variables',{}):pro['text_variables']=variables
    if ws.state.get('native_field_templates') is not None:
        pro.setdefault('schematic',{}).setdefault('drawing',{})['field_names']=deepcopy(ws.state['native_field_templates'])
    if ws.state.get('native_bom_presets'):
        presets=pro.setdefault('schematic',{}).setdefault('bom_presets',[])
        for preset in ws.state['native_bom_presets'].values():
            presets[:]=[x for x in presets if x.get('name')!=preset['name']]
            presets.append(deepcopy(preset))
    if ws.state.get('native_bom_settings') is not None:
        from .nativefirst import validate_native
        pro.setdefault('schematic',{}).update(validate_native(ws.state['native_bom_settings']))
    catalogue=pro.setdefault('schematic',{}).setdefault('variants',[])
    for name,v in syncable.items():
        existing=next((i for i in catalogue if i['name'].casefold()==name.casefold()),None)
        if existing is not None:existing['description']=v.get('description','')
        else:catalogue.append({'name':name,'description':v.get('description','')})
    if pro!=p.pro:candidate[p.pro_path]=(json.dumps(pro,ensure_ascii=False,indent=2)+'\n').encode()
    for path,data in candidate.items():
        before=path.read_text(encoding='utf-8-sig')
        diff=''.join(difflib.unified_diff(before.splitlines(True),data.decode('utf-8-sig').splitlines(True),fromfile=path.name+' (current)',tofile=path.name+' (proposed)'))
        changes.append({'path':str(path),'before_sha256':sha(path.read_bytes()),'after_sha256':sha(data),'diff':diff})
    fingerprint=sha((ws._serialize()+json.dumps(p.hashes,sort_keys=True)).encode())
    ws.preview_cache={'fingerprint':fingerprint,'candidate':candidate,'revision':ws.revision}
    return {'fingerprint':fingerprint,'files':changes,'count':len(changes),
            'warning':'Close ALL KiCad editors before applying. Reopen the project and run Update PCB from Schematic afterward. No PCB is modified. Native sync does not certify ERC/DRC or package compatibility.'}


def _transaction(candidates: dict[Path,bytes], expected: dict[Path,str|None], backup_dir: Path, validator=None):
    """Recoverable transaction with rollback on ordinary errors; never delete backups."""
    if not candidates:return None
    backup_dir.mkdir(parents=True,exist_ok=False)
    originals={p:(p.read_bytes() if p.exists() else None) for p in candidates}
    for p,data in originals.items():
        if (sha(data) if data is not None else None)!=expected[p]:
            raise ValueError('File changed before transaction: '+str(p))
    manifest=[];temps={};replaced=[]
    try:
        for i,(p,data) in enumerate(candidates.items()):
            name=f'{i:03d}_{p.name}.bak'
            if originals[p] is not None:
                with open(backup_dir/name,'xb') as f:f.write(originals[p]);f.flush();os.fsync(f.fileno())
            manifest.append({'original':str(p),'backup':name if originals[p] is not None else None,
                             'before_sha256':expected[p],'after_sha256':sha(data)})
            fd,temp=tempfile.mkstemp(prefix='.'+p.name+'.wayricad-',dir=p.parent)
            temps[p]=Path(temp)
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        with open(backup_dir/'manifest.json','x',encoding='utf-8') as f:
            json.dump({'time':now(),'files':manifest},f,indent=2);f.flush();os.fsync(f.fileno())
        for p,temp in temps.items():
            current=sha(p.read_bytes()) if p.exists() else None
            if current!=expected[p]:raise ValueError('Concurrent file modification: '+str(p))
            os.replace(temp,p);replaced.append(p)
        if validator:validator()
        (backup_dir/'COMPLETED.txt').write_text(now(),encoding='utf-8')
    except Exception as exc:
        failures=[]
        for p in reversed(replaced):
            try:
                # Refuse to erase a third-party write occurring after our replacement.
                if not p.exists() or sha(p.read_bytes())!=sha(candidates[p]):
                    raise ValueError('File changed again; restore manually from backup.')
                if originals[p] is None:p.unlink()
                else:
                    fd,temp=tempfile.mkstemp(prefix='.'+p.name+'.rollback-',dir=p.parent)
                    with os.fdopen(fd,'wb') as f:f.write(originals[p]);f.flush();os.fsync(f.fileno())
                    os.replace(temp,p)
            except Exception as rollback:failures.append(str(p)+': '+str(rollback))
        (backup_dir/'FAILED.txt').write_text(str(exc)+'\n'+'\n'.join(failures),encoding='utf-8')
        if failures:raise RuntimeError('Transaction failed; manual recovery required. Backup: '+str(backup_dir)+'\n'+'\n'.join(failures)) from exc
        raise
    finally:
        for temp in temps.values():
            if temp.exists():temp.unlink()
    return str(backup_dir)


def apply_plan(ws,fingerprint,confirmation,editors_closed):
    if confirmation!='APPLY' or editors_closed is not True:
        raise ValueError('Confirm that all KiCad editors are closed, and type APPLY.')
    cached=ws.preview_cache
    if not cached or cached['fingerprint']!=fingerprint or cached['revision']!=ws.revision:
        raise ValueError('Review is missing or stale. Generate a fresh native-change preview.')
    if fingerprint!=sha((ws._serialize()+json.dumps(ws.project.hashes,sort_keys=True)).encode()):
        raise ValueError('Workspace changed after preview. Review again.')
    ws.project.check_unchanged()
    for directory in {p.parent for p in ws.project.documents}|{ws.project.pro_path.parent}:
        locks=[p for p in directory.glob('*.lck') if 'kicad' in p.name.casefold()]
        if locks:raise ValueError('KiCad lock files are present. Close the editors; do not bypass active locks: '+', '.join(p.name for p in locks))
    candidate=dict(cached['candidate']);expected={p:sha(p.read_bytes()) for p in candidate}
    old_state=deepcopy(ws.state)
    state=deepcopy(ws.state);state['base']={};state['project_variables']={};state['field_schema_edits']={k:v for k,v in state['field_schema_edits'].items() if state['variants'].get(k,{}).get('bom_only')};state['native_field_templates']=None;state['native_bom_presets']={};state['native_bom_settings']=None
    for v in state['variants'].values():
        if not v.get('bom_only'):v.update(parent=BASE,overrides={},native=True)
    state['history'].append({'time':now(),'action':'Apply reviewed native sync'})
    state['source_hashes']={str(p):sha(candidate.get(p,d.data)) for p,d in ws.project.documents.items()}
    state['source_hashes'][str(ws.project.pro_path)]=sha(candidate.get(ws.project.pro_path,ws.project.pro_data))
    candidate[ws.sidecar]=(json.dumps(state,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    expected[ws.sidecar]=ws.sidecar_hash
    desired={v:{c.id:ws.own(c,v)[:2] for c in ws.project.components} for v in [BASE]+list(ws.state['variants'])}
    def verify():
        fresh=Workspace(Project(ws.project.pro_path if ws.project.pro_path.exists() else ws.project.root),load=False)
        local=Workspace(fresh.project) if any(v.get('bom_only') for v in state['variants'].values()) else fresh
        if old_state.get('native_bom_settings'):
            for key,value in old_state['native_bom_settings'].items():
                if fresh.project.pro.get('schematic',{}).get(key)!=value:
                    raise ValueError('Native BOM settings round-trip failed: '+key)
        for v,components in desired.items():
            for cid,(fields,flags) in components.items():
                reader=local if state['variants'].get(v,{}).get('bom_only') else fresh
                got_fields,got_flags,_=reader.own(reader.project.by_id[cid],v)
                if v==BASE and cid in ws.state.get('field_schema_edits',{}).get(BASE,{}) and set(fields)!=set(got_fields):
                    raise ValueError(f'Native field membership verification failed for {cid}.')
                # Variant differential empty/absent fields have equivalent BOM semantics.
                if any(fields.get(k,'')!=got_fields.get(k,'') for k in set(fields)|set(got_fields)) or flags!=got_flags:
                    raise ValueError(f'Native round-trip semantic verification failed for {v}, {cid}.')
    backup_dir=ws.project.root.parent/'.wayricad-bom-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=_transaction(candidate,expected,backup_dir,verify)
    refreshed=Workspace(Project(ws.project.pro_path if ws.project.pro_path.exists() else ws.project.root))
    return refreshed,backup
