"""Preview-first project-wide custom-field normalization.

Enforcement is staged in the sidecar, never an implicit native write. Standard
fields, simulation metadata and population flags are protected. An exact schema
is enforced across default + every variant, not just the visible assembly.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
import json
from .catalog import validate_profile, protected, name
from .engine import Resolver
from .native import BASE, sha, is_generated_field
from .sexpr import properties, apply_edits, quote

WARNING=('Enforce can rename or remove custom fields and overwrite their values. '
         'Variable expressions in deleted, reset or baked names/values will be lost from those fields. '
         'Project variable definitions are never deleted by enforcement. Make a project/Git backup first. '
         'Preserve expressions is the default; exact mode can still remove expression-bearing extra fields. '
         'Changes are staged in this workspace; native synchronization is a separate reviewed step.')


def validate_options(options):
    defaults={'mode':'merge','values':'preserve','names':'preserve','value_variables':'preserve','apply_visibility':False,'register_native':True}
    if not isinstance(options,dict) or set(options)-set(defaults):raise ValueError('Unknown enforcement option.')
    o=dict(defaults,**options)
    for k,allowed in {'mode':('merge','exact'),'values':('preserve','fill','reset'),'names':('preserve','resolve'),'value_variables':('preserve','bake')}.items():
        if o[k] not in allowed:raise ValueError('Invalid enforcement '+k+'.')
    for key in ('apply_visibility','register_native'):
        if type(o[key]) is not bool:raise ValueError(key+' must be boolean.')
    return o


def _transform(row,profile,options):
    raw=dict(row['raw']);resolver=Resolver(row['variables']);out={};sources={};visibility={}
    # Physical generated names lock their value; compound variable-bearing names
    # remain ordinary properties. Export virtual columns are a separate layer.
    used=set();events=[];errors=[]
    for f in profile['fields']:
        target=resolver.text(f['name']) if options['names']=='resolve' else f['name']
        try:name(target)
        except ValueError as e:errors.append(str(e));continue
        if protected(target):errors.append('Template resolves to protected field: '+target);continue
        if target in out:errors.append('Multiple template fields resolve to '+target);continue
        wanted=[f['name'],target,*f.get('aliases',[])]
        # Normalize ordinary field-name case, but never case-fold variable tokens.
        folded={k.casefold() for k in wanted if '${' not in k}
        candidates=list(dict.fromkeys([k for k in wanted if k in raw]+[k for k in raw if '${' not in k and k.casefold() in folded]))
        # Preserve an existing expression-bearing name that resolves to the target
        # only when explicitly listed as an alias or when names are being baked.
        if options['names']=='resolve':
            candidates+= [k for k in raw if '${' in k and resolver.text(k)==target and k not in candidates]
        nonempty=[k for k in candidates if raw[k]!='']
        if len({raw[k] for k in nonempty})>1:
            errors.append('Conflicting field/alias values for '+target+': '+', '.join(nonempty));continue
        source=(target if target in nonempty else nonempty[0] if nonempty else candidates[0] if candidates else None)
        value=raw.get(source,'') if source else f.get('default','')
        if options['values']=='reset' or (options['values']=='fill' and value==''):value=f.get('default','')
        if is_generated_field(target):
            # KiCad sets and locks this value to the field-name expression.
            # Do not pretend that an independent default or baked value survives
            # a real KiCad reload. Conflicting aliases/defaults require review.
            requested=f.get('default','')
            if requested not in ('',target):
                errors.append('Generated field '+target+' cannot have an independent default. Leave it blank/use the same expression, or bake the field name first.');continue
            if source and raw[source] not in ('',target) and options['values']!='reset':
                errors.append('Generated field '+target+' conflicts with its source value. Use an ordinary field name, or explicitly Reset after reviewing data loss.');continue
            if options['value_variables']=='bake':
                errors.append('Cannot bake a generated field value while preserving its variable name: '+target+'. Bake the name too, or preserve the value expression.');continue
            value=target
        elif options['value_variables']=='bake':value=resolver.text(value)
        out[target]=value;sources[target]=source
        if options['apply_visibility'] or source is None:visibility[target]=f.get('visible',False)
        used.update(candidates)
        if source is None:events.append({'action':'add','field':target,'before':None,'after':value})
        elif source!=target:events.append({'action':'rename','field':source,'target':target,'before':raw[source],'after':value})
        if source is not None and raw[source]!=value:events.append({'action':'overwrite','field':target,'before':raw[source],'after':value})
        for alias in candidates:
            if alias!=source:events.append({'action':'remove_alias','field':alias,'before':raw[alias],'after':None})
    # Keep KiCad's mandatory and reserved properties, regardless of exact mode.
    for key,value in raw.items():
        if key in used:continue
        if protected(key) or options['mode']=='merge':
            if key in out and out[key]!=value:errors.append('Target field collides with retained field: '+key)
            else:out[key]=value;sources[key]=key
        else:events.append({'action':'remove','field':key,'before':value,'after':None})
    # Standard fields first, schema order second, extras last.
    order=[k for k in raw if protected(k)]+[resolver.text(f['name']) if options['names']=='resolve' else f['name'] for f in profile['fields']]
    out={k:out[k] for k in dict.fromkeys([*order,*out]) if k in out}
    if resolver.errors:errors.extend(resolver.errors)
    # Full proposed-context validation is performed after all symbols and variants
    # have been transformed, so cross-references to removed fields are also caught.
    if list(raw)!=list(out) and not any(e['action'] in ('add','remove','rename','remove_alias') for e in events):
        events.append({'action':'reorder','field':'Custom field order','before':list(raw),'after':list(out)})
    for e in events:
        e['variable_loss']=('${' in e['field'] and e['action'] in ('rename','remove','remove_alias')) or ('${' in str(e.get('before') or '') and e.get('before')!=e.get('after'))
    return {'fields':out,'order':list(out),'sources':sources,'visibility':visibility},events,list(dict.fromkeys(errors))


def preview(ws,profile,options=None):
    if any(v.get('bom_only') and v.get('locked') for v in ws.state['variants'].values()):
        raise ValueError('Unlock independent BOM variants before project-wide field enforcement.')
    ws.project.check_unchanged();validate_profile(profile);options=validate_options(options or {})
    variants=[BASE]+list(ws.state['variants']);plans={};events=[];errors=[]
    if ws.state.get('source_hashes')!=ws.project.hashes:errors.append({'reference':'Project','variant':BASE,'message':'Source baseline has changed; reopen/review/rebase before enforcement.'})
    shared={};native_names=None
    for variant in variants:
        plans[variant]={}
        for row in ws.rows(variant):
            proposal,changes,problems=_transform(row,profile,options)
            plans[variant][row['id']]=proposal
            for event in changes:events.append(dict(event,reference=row['ref'],variant=variant))
            for error in problems:errors.append({'reference':row['ref'],'variant':variant,'message':error})
            if variant==BASE:
                for m in ws.project.by_id[row['id']].members:
                    key=(str(m.doc.path),m.uuid)
                    fields={k:v for k,v in proposal['fields'].items() if k!='Reference'}
                    if key in shared and shared[key]!=fields:errors.append({'reference':row['ref'],'variant':variant,'message':'Shared-sheet instances resolve to different base field schemas. Keep raw variables or change the source in KiCad.'})
                    shared[key]=fields
            # Field names for native project defaults must be context-independent.
            resolver=Resolver(row['variables'])
            names=[resolver.text(f['name']) if options['names']=='resolve' else f['name'] for f in profile['fields']]
            if native_names is None:native_names=names
            elif options['register_native'] and native_names!=names:errors.append({'reference':row['ref'],'variant':variant,'message':'Native project field templates cannot have different resolved names per component/variant. Preserve names or disable native registration.'})
    # Store only equal-to-parent fields as inherited. Subsequent base/parent edits
    # still flow through variants while the reviewed schema is staged.
    for variant in variants[1:]:
        parent=ws.state['variants'][variant].get('parent',BASE)
        for cid,record in plans[variant].items():
            parent_fields=plans[parent][cid]['fields']
            record['inherit']=[k for k,v in record['fields'].items() if k!='Reference' and k in parent_fields and v==parent_fields[k]]
    previous=ws.state.get('field_schema_edits',{})
    try:
        ws.state['field_schema_edits']=plans
        for variant in variants:
            for row in ws.rows(variant):
                for message in row['errors']:
                    errors.append({'reference':row['ref'],'variant':variant,'message':message})
    finally:ws.state['field_schema_edits']=previous
    native=[{'name':n,'visible':f.get('visible',False),'url':f.get('url',False)} for n,f in zip(native_names or [f['name'] for f in profile['fields']],profile['fields'])]
    if options['register_native'] and options['mode']=='merge':
        existing=ws.state.get('native_field_templates')
        if existing is None:existing=ws.project.pro.get('schematic',{}).get('drawing',{}).get('field_names',[])
        used={e['name'].casefold() for e in native}
        native += [deepcopy(e) for e in existing if e.get('name','').casefold() not in used]
    if any(record['visibility'] for record in plans[BASE].values()):
        for cid,record in plans[BASE].items():
            c=ws.project.by_id[cid]
            for member in c.members:
                existing=properties(member.symbol)
                for field,wanted in record['visibility'].items():
                    source=record['sources'].get(field) or field
                    before=None
                    if source in existing:
                        node=existing[source][1];hide=node.one('hide');effects=node.one('effects')
                        legacy=effects.one('hide') if effects else None
                        hidden=(hide is not None and hide.val(1,'yes')!='no') or (legacy is not None and legacy.val(1,'yes')!='no') or (effects is not None and any(a.value=='hide' for a in effects.atoms[1:]))
                        before=not hidden
                    if before!=wanted:events.append({'reference':c.ref,'variant':BASE,'action':'visibility','field':field,'before':before,'after':wanted,'variable_loss':False})
    existing_defaults=ws.state.get('native_field_templates')
    if existing_defaults is None:existing_defaults=ws.project.pro.get('schematic',{}).get('drawing',{}).get('field_names',[])
    removed_defaults=[e for e in existing_defaults if e.get('name') not in {n['name'] for n in native}]
    if options['register_native'] and existing_defaults!=native:
        events.append({'reference':'Project','variant':BASE,'action':'native_defaults','field':'KiCad project field-name defaults','before':existing_defaults,'after':native,'variable_loss':any('${' in e.get('name','') for e in removed_defaults)})
    destructive=sum(e['action'] in ('remove','remove_alias','rename','overwrite') for e in events)+(len(removed_defaults) if options['register_native'] else 0)
    fingerprint=sha((ws._serialize()+json.dumps(ws.project.hashes,sort_keys=True)+json.dumps(profile,sort_keys=True)+json.dumps(options,sort_keys=True)).encode())
    ws.enforce_cache={'fingerprint':fingerprint,'revision':ws.revision,'profile':deepcopy(profile),'options':options,'plans':plans,'native':native,'events':events,'errors':errors,'state_hash':sha(ws._serialize().encode()),'destructive':destructive}
    return {'fingerprint':fingerprint,'profile':profile['name'],'options':options,'components':len(ws.project.components),
            'variants':len(variants),'events':events,'counts':dict(Counter(e['action'] for e in events)),
            'variable_losses':sum(bool(e['variable_loss']) for e in events),'destructive':destructive,
            'errors':errors,'native_templates':native,'warning':WARNING}


def apply(ws,fingerprint,confirmation,acknowledge_loss=False):
    cache=getattr(ws,'enforce_cache',None)
    if confirmation!='ENFORCE':raise ValueError('Type ENFORCE after reviewing the field changes.')
    if not cache or cache['fingerprint']!=fingerprint or cache['revision']!=ws.revision or cache['state_hash']!=sha(ws._serialize().encode()):raise ValueError('Field-schema preview is missing or stale; review again.')
    ws.project.check_unchanged()
    if cache['errors']:raise ValueError('Resolve field/variable conflicts before enforcement. No fields were changed.')
    if cache['destructive'] and acknowledge_loss is not True:raise ValueError('Acknowledge possible loss of fields, values and variable expressions.')
    # One commit = one Undo, even with thousands of symbols and variants.
    def change():
        ws.state['field_schema_edits']=deepcopy(cache['plans'])
        ws.state['field_profiles'][cache['profile']['name']]=deepcopy(cache['profile'])
        if cache['options']['register_native']:ws.state['native_field_templates']=cache['native']
        ws.state['field_enforcement']={'profile':cache['profile']['name'],'options':cache['options'],'counts':dict(Counter(e['action'] for e in cache['events'])),'required':[n['name'] for n,f in zip(cache['native'],cache['profile']['fields']) if f.get('required')]}
    ws.commit('Enforce field name template '+cache['profile']['name']+' across default + all variants (staged)',change)
    ws.enforce_cache=None
    return {'affected':sum(len(p) for p in cache['plans'].values()),'message':'Field schema staged. Undo is available. Save workspace, then Review & native sync to modify KiCad files.'}


def schema_symbol_edits(member,record):
    """Reorder/rename/remove property spans; retain per-field positions/styles."""
    doc=member.doc;symbol=member.symbol;existing=properties(symbol);nodes=symbol.nodes('property')
    fields=record['fields'];sources=record.get('sources',{});visibility=record.get('visibility',{})
    texts=[]
    for field in dict.fromkeys([*record.get('order',[]),*fields]):
        if field not in fields:continue
        value=fields[field]
        source=sources.get(field) or field
        if source in existing:
            original,node,atom=existing[source];local=[]
            nameatom=node.atoms[-2] if len(node.atoms)==4 and node.atoms[1].value=='private' else node.atoms[1]
            if source!=field:local.append((nameatom.start-node.start,nameatom.end-node.start,quote(field)))
            if field!='Reference' and value!=original:local.append((atom.start-node.start,atom.end-node.start,quote(value)))
            if field in visibility:
                hide=node.one('hide');effects=node.one('effects')
                legacy=effects.one('hide') if effects else None
                if legacy:local.append((legacy.start-node.start,legacy.end-node.start,''))
                token='(hide '+('no' if visibility[field] else 'yes')+')'
                if hide:local.append((hide.start-node.start,hide.end-node.start,token))
                else:local.append((node.end-node.start-1,node.end-node.start-1,' '+token))
            texts.append(apply_edits(doc.text[node.start:node.end],local))
        else:
            at=symbol.one('at');x=at.val(1,'0') if at else '0';y=at.val(2,'0') if at else '0'
            texts.append(f'(property {quote(field)} {quote(value)} (at {x} {y} 0) (effects (font (size 1.27 1.27))) (hide '+('no' if visibility.get(field,False) else 'yes')+'))')
    edits=[]
    for i,node in enumerate(nodes):
        text=texts[i] if i<len(texts) else ''
        if doc.text[node.start:node.end]!=text:edits.append((node.start,node.end,text))
    if len(texts)>len(nodes):
        offset=nodes[-1].end if nodes else symbol.end-1
        edits.append((offset,offset,'\n    '+'\n    '.join(texts[len(nodes):])))
    return edits
