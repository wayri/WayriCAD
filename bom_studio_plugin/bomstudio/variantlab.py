"""Independent BOM variants: reviewed creation, inheritance, pinned overrides and locks."""
from __future__ import annotations
from copy import deepcopy
from .native import BASE
from .engine import Workspace, validate_name, now
from .partsdb import digest, text


def validate(ws):
    for name,v in ws.state['variants'].items():
        for key in ('bom_only','locked','pinned'):
            if key in v and type(v[key]) is not bool:raise ValueError('Variant '+key+' must be boolean.')
        if v.get('bom_only') and v.get('native'):raise ValueError('A BOM-only variant cannot also be native.')
        chain=ws.variant_chain(name)
        if not v.get('bom_only') and any(ws.state['variants'][a].get('bom_only') for a in chain):
            raise ValueError('A native-syncable variant cannot inherit from a BOM-only variant.')
        if not isinstance(v.get('tags',[]),list) or len(v.get('tags',[]))>50 or any(not isinstance(t,str) or len(t)>128 for t in v.get('tags',[])):raise ValueError('Invalid variant tags.')


def _mutate(ws,request):
    op=request.get('op');name=request.get('name','');validate_name(name)
    if op=='create':
        parent=request.get('parent',BASE);ws.variant_chain(parent)
        if name.casefold() in {BASE.casefold(),'default',*(v.casefold() for v in ws.state['variants'])}:raise ValueError('Variant name is already used or reserved.')
        mode=request.get('mode','derived')
        if mode not in ('derived','pinned'):raise ValueError('Mode must be derived or pinned.')
        rec={'parent':parent,'description':text(request.get('description',''),'description',4000),'native':False,'bom_only':True,'locked':False,
             'pinned':mode=='pinned','overrides':{},'variables':{},'tags':request.get('tags',[]),'created_at':now()}
        if mode=='pinned':
            # Raw expressions remain raw. Copy variables, not evaluated numeric guesses.
            rec['variables']=ws.variables(parent)
            schemas={}
            for c in ws.project.components:
                f,flags,_=ws.own(c,parent)
                rec['overrides'][c.id]={**deepcopy(f),**deepcopy(flags)}
                schemas[c.id]={'fields':deepcopy(f),'order':list(f),'inherit':[],'reset_base':[]}
            rec['pinned_source_context']=digest({'hashes':ws.project.hashes,'parent':parent,'instances':sorted(ws.project.by_id)})
            ws.state.setdefault('field_schema_edits',{})[name]=schemas
        ws.state['variants'][name]=rec
    else:
        if name not in ws.state['variants'] or not ws.state['variants'][name].get('bom_only'):raise ValueError('This operation is only for independent BOM variants.')
        rec=ws.state['variants'][name]
        if rec.get('locked') and op!='unlock':raise ValueError('Unlock the independent variant deliberately before changing it.')
        if op=='rename':
            new=request.get('new','');validate_name(new)
            if new.casefold() in {BASE.casefold(),'default',*(v.casefold() for v in ws.state['variants'])}:raise ValueError('New name is already used/reserved.')
            ws.state['variants'][new]=ws.state['variants'].pop(name)
            for v in ws.state['variants'].values():
                if v.get('parent')==name:v['parent']=new
            if name in ws.state.get('field_schema_edits',{}):ws.state['field_schema_edits'][new]=ws.state['field_schema_edits'].pop(name)
        elif op=='reparent':ws.variant_chain(request['parent']);rec['parent']=request['parent']
        elif op=='metadata':rec.update(description=text(request.get('description',''),'description',4000),tags=request.get('tags',[]))
        elif op in ('lock','unlock'):rec['locked']=op=='lock'
        elif op=='remove':
            if any(v.get('parent')==name for v in ws.state['variants'].values()):raise ValueError('Reparent or remove children first.')
            del ws.state['variants'][name];ws.state.get('field_schema_edits',{}).pop(name,None)
        else:raise ValueError('Unknown independent variant operation.')
    validate(ws)


def preview(ws,request):
    if not isinstance(request,dict) or set(request)-{'op','name','new','parent','mode','description','tags'}:raise ValueError('Unknown variant operation keys.')
    ws.project.check_unchanged();shadow=Workspace(ws.project,load=False);shadow.state=deepcopy(ws.state);_mutate(shadow,request);shadow._validate_state()
    old=set(ws.state['variants']);new=set(shadow.state['variants']);changes=[]
    for name in sorted(old|new):
        if name in old and name in new:
            before={r['id']:r for r in ws.rows(name)}
            for row in shadow.rows(name):
                a=before[row['id']]
                if a['raw']!=row['raw'] or a['flags']!=row['flags']:changes.append({'variant':name,'reference':row['ref'],'before':{**a['raw'],**a['flags']},'after':{**row['raw'],**row['flags']}})
    return {'schema':'wayricad-bom-variant-plan-1','request':request,'fingerprint':digest([ws._serialize(),ws.project.hashes,request]),'added':sorted(new-old),'removed':sorted(old-new),'changes':changes,
            'notice':'BOM-only variants never synchronize into KiCad. Pinned overrides preserve raw expressions and copied variables, not external sheet/geometry context. Locks are workflow guards, not security boundaries.'}


def apply(ws,plan,confirmation):
    if confirmation!='VARIANT':raise ValueError('Type VARIANT after reviewing the variant plan.')
    fresh=preview(ws,plan['request'])
    if fresh['fingerprint']!=plan.get('fingerprint'):raise ValueError('Variant review is stale.')
    ws.commit('Independent BOM variant: '+plan['request']['op'],lambda:_mutate(ws,plan['request']))
    return {'ok':True,'variants':ws.state['variants'],'native_files_written':False}
