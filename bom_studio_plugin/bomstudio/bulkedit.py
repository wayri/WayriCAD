"""Reviewed, atomic workspace edits and presentation-only arbitrary grouping.

All edits route through the existing native-aware edit engine. A preview is
bound to the entire workspace and sources; applying commits one undo record.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from .engine import Workspace, COMPUTED, validate_name
from .native import BASE, FLAGS, natural

FLAG_FIELDS = {'InBOM':'in_bom', 'OnBoard':'on_board', 'InPosFiles':'in_pos_files',
               'ExcludeFromSim':'exclude_from_sim', 'DNP':'dnp'}
READ_ONLY = COMPUTED | {'Sheet','Item','InBOM','OnBoard','InPosFiles','ExcludeFromSim'}


def digest(ws, payload):
    data=ws._serialize()+'\n'+json.dumps(payload, sort_keys=True,ensure_ascii=False)+'\n'+json.dumps(ws.project.hashes,sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


def normalize_changes(row, changes):
    if not isinstance(changes, dict) or not changes or len(changes)>200:
        raise ValueError('Provide 1–200 fields per edit.')
    output={}
    for name,value in changes.items():
        validate_name(name)
        if name.startswith('@field:'):
            key=name[7:]
            if key not in row['raw']:raise ValueError('Unknown physical field: '+key)
            if key in ('Reference','UUID') or key in FLAGS:raise ValueError('This identity/reserved native property is read-only.')
        elif name in ('@attribute:exclude_bom','@attribute:exclude_board','@attribute:exclude_pos'):
            if value is not None and type(value) is not bool:raise ValueError('Exclusion attributes require true or false.')
            key={'@attribute:exclude_bom':'in_bom','@attribute:exclude_board':'on_board','@attribute:exclude_pos':'in_pos_files'}[name]
            value=None if value is None else not value
        elif name in FLAG_FIELDS:
            key=FLAG_FIELDS[name]
        elif name=='Assembly':
            if value is not None and value not in ('FIT','DNP','DNI'):raise ValueError('Assembly must be FIT, DNP or DNI.')
            output['dnp']=None if value is None else value!='FIT';key=name
        else:
            if name in READ_ONLY or '${' in name and name not in row['raw']:
                raise ValueError(name+' is a computed/virtual field. Edit its source instead.')
            key=row.get('field_name_sources',{}).get(name,name)
        if key in output and output[key]!=value:raise ValueError('Conflicting edits through field aliases: '+name)
        output[key]=value
    return output


def simulate(ws, variant, entries):
    ws.variant_chain(variant)
    if ws.state['variants'].get(variant,{}).get('locked'):raise ValueError('Independent BOM variant is locked.')
    if not isinstance(entries,list) or not 1<=len(entries)<=20000:raise ValueError('Provide 1–20,000 edit entries.')
    rows={r['id']:r for r in ws.rows(variant)}
    assignments={};shared={}
    for entry in entries:
        ids=entry.get('ids',[])
        if not isinstance(ids,list) or not ids or len(ids)>100000:raise ValueError('Choose components to edit.')
        for cid in ids:
            if cid not in rows:raise ValueError('Unknown component ID; reopen the workspace.')
            changes=normalize_changes(rows[cid],entry.get('changes'))
            dest=assignments.setdefault(cid,{})
            for field,value in changes.items():
                if field in dest and dest[field]!=value:raise ValueError('Conflicting values for '+rows[cid]['ref']+'/'+field)
                dest[field]=value
                if variant==BASE:
                    for member in ws.project.by_id[cid].members:
                        key=(str(member.doc.path),member.uuid,field)
                        if key in shared and shared[key]!=value:raise ValueError('Conflicting edits to repeated-sheet base symbols. Use instance-specific named variants.')
                        shared[key]=value
    shadow=Workspace(ws.project,load=False);shadow.state=deepcopy(ws.state)
    # Coalesce identical assignments to avoid quadratic repeated-sheet expansion.
    groups=defaultdict(list)
    for cid,changes in assignments.items():groups[json.dumps(changes,sort_keys=True)].append(cid)
    for changes,ids in groups.items():shadow.edit(ids,variant,json.loads(changes))
    events=[];warnings=[]
    scopes=([variant]+[v for v in ws.state['variants'] if v!=variant and variant in ws.variant_chain(v)]) if variant!=BASE else [BASE]+list(ws.state['variants'])
    selected=set(assignments);affected=set();losses=0
    for scope in scopes:
        before={r['id']:r for r in ws.rows(scope)}
        for after in shadow.rows(scope):
            old=before[after['id']]
            a=dict(old['raw'],**old['flags']);b=dict(after['raw'],**after['flags'])
            for field in sorted(set(a)|set(b)):
                if a.get(field)!=b.get(field):
                    was=a.get(field);new=b.get(field)
                    loss=isinstance(was,str) and ('${' in was or '@{' in was) and was!=new
                    losses+=int(loss)
                    events.append({'variant':scope,'id':after['id'],'reference':after['ref'],'field':field,
                        'before':was,'after':new,'variable_loss':loss,'expanded':after['id'] not in selected})
                    affected.add(after['id'])
    if any(e['field'] in ('Value','Footprint','MPN','Manufacturer') for e in events):
        warnings.append('Changing Value, MPN or Footprint does not validate the physical part or change the library symbol. Re-run health and review electrical ratings/pinout in KiCad.')
    if affected-selected:warnings.append('Shared base-symbol edits also affect repeated-sheet occurrences not explicitly selected.')
    if len(scopes)>1:warnings.append('Edits can propagate into descendant variants that inherit those fields; the review includes effective changes.')
    if losses:warnings.append('This edit replaces raw variable expressions. Change the underlying variable instead to retain linkage.')
    shadow.state['history']=deepcopy(ws.state['history'])
    return shadow.state,{'events':events,'affected':len(affected),'selected':len(selected),'variable_losses':losses,'warnings':warnings}


def preview(ws,variant,entries):
    ws.project.check_unchanged()
    _,review=simulate(ws,variant,entries)
    return dict(review,fingerprint=digest(ws,{'variant':variant,'entries':entries}))


def apply(ws,variant,entries,fingerprint,confirmation,acknowledge_loss=False):
    if confirmation!='EDIT':raise ValueError('Type EDIT to stage reviewed changes.')
    ws.project.check_unchanged()
    if fingerprint!=digest(ws,{'variant':variant,'entries':entries}):raise ValueError('Preview is stale. Review again before applying.')
    state,review=simulate(ws,variant,entries)
    if review['variable_losses'] and not acknowledge_loss:raise ValueError('Acknowledge loss of variable expressions before applying.')
    ws.commit('Reviewed grid edit: '+str(review['affected'])+' components',lambda:ws.state.update(state))
    return {'affected':review['affected'],'changes':len(review['events'])}


def groups(ws,variant,fields,raw=False,rows=None):
    if not isinstance(fields,list) or len(fields)>30 or any(not isinstance(f,str) for f in fields):raise ValueError('Group by up to 30 fields.')
    if len(fields)!=len(set(fields)):raise ValueError('Duplicate grouping fields.')
    rows=ws.rows(variant) if rows is None else rows;bucket=defaultdict(list)
    for r in rows:
        values=dict(r['fields'])
        if raw:
            for k in values:
                source=r.get('field_name_sources',{}).get(k,k)
                if source in r['raw']:values[k]=r['raw'][source]
        key=tuple(str(values.get(f,'')) for f in fields) if fields else (r['id'],)
        bucket[key].append((r,values))
    result=[]
    for key,items in bucket.items():
        names=set().union(*(v for r,v in items));values={};mixed=[]
        for name in sorted(names):
            choices=list(dict.fromkeys(str(v.get(name,'')) for r,v in items))
            if len(choices)==1:values[name]=items[0][1].get(name,'')
            else:values[name]='<mixed>';mixed.append(name)
        result.append({'id':hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20],
            'keys':dict(zip(fields,key)),'ids':[r['id'] for r,v in items],
            'references':[r['ref'] for r,v in items],'count':len(items),'values':values,'mixed':mixed})
    return {'groups':result,'fields':fields,'raw':raw,'components':len(rows),
            'warning':'Presentation groups may mix purchasing-incompatible parts. Export grouping retains its independent compatibility guards.'}
