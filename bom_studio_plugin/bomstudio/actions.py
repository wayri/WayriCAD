"""Non-executable bulk recipes, explicit scopes and stale-proof reviewed plans."""
from __future__ import annotations
from copy import deepcopy
from . import bulkedit, search
from .native import BASE

OPS={'set','fill_empty','clear','trim','upper','lower','prefix','suffix','replace','copy','reset_to_base'}

def validate_recipe(recipe):
    if not isinstance(recipe,dict) or set(recipe)-{'schema','query','ids','case_sensitive','allow_all','operations','variant'}:raise ValueError('Unknown bulk recipe options.')
    if recipe.get('schema','wayricad-bulk-recipe-1')!='wayricad-bulk-recipe-1':raise ValueError('Unsupported bulk recipe schema.')
    if ('ids' in recipe)==('query' in recipe):raise ValueError('Supply either exact IDs or an explicit query, never both.')
    for flag in ('allow_all','case_sensitive'):
        if flag in recipe and not isinstance(recipe[flag],bool):raise ValueError(flag+' must be true or false.')
    ops=recipe.get('operations')
    if not isinstance(ops,list) or not 1<=len(ops)<=30:raise ValueError('Provide 1–30 bulk operations.')
    for op in ops:
        if not isinstance(op,dict) or set(op)-{'op','field','value','find','source'}:raise ValueError('Invalid bulk operation options.')
        if op.get('op') not in OPS:raise ValueError('Unsupported bulk operation: '+str(op.get('op')))
        if not isinstance(op.get('field'),str) or not op['field'].strip():raise ValueError('Every operation needs a target field.')
        for key in ('find','source'):
            if key in op and (not isinstance(op[key],str) or len(op[key])>10000):raise ValueError('Invalid '+key+' text.')
        if 'value' in op and not isinstance(op['value'],(str,bool)):raise ValueError('Value must be text or a boolean.')
        if len(str(op.get('value','')))>10000:raise ValueError('Bulk value exceeds 10,000 characters.')
        if op['op'] in ('set','fill_empty','prefix','suffix','replace') and 'value' not in op:raise ValueError(op['op']+' needs value.')
        if op['op']=='replace' and not op.get('find'):raise ValueError('Literal replace requires nonempty find text.')
        if op['op']=='copy' and not op.get('source'):raise ValueError('Copy requires a source field.')

def entries(ws,variant,recipe):
    validate_recipe(recipe)
    if recipe.get('variant',variant)!=variant:raise ValueError('Recipe variant differs from the selected variant.')
    rows=ws.rows(variant);known={r['id']:r for r in rows}
    if 'ids' in recipe:
        ids=recipe['ids']
        if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):raise ValueError('IDs must be a list of strings.')
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate component IDs in selector.')
        if any(i not in known for i in ids):raise ValueError('Unknown component in selector.')
        targets=[known[i] for i in ids]
    else:
        q=recipe['query']
        if not isinstance(q,str):raise ValueError('Query must be text.')
        if not q.strip() and recipe.get('allow_all') is not True:raise ValueError('An empty query requires allow_all=true to edit the entire variant.')
        targets,_=search.select(ws,variant,q,recipe.get('case_sensitive',False),rows)
    if not targets:raise ValueError('Bulk scope contains no components; nothing will be changed.')
    if len(targets)>20000:raise ValueError('Bulk review is limited to 20,000 targets per transaction; split the selection.')
    fields=set().union(*(set(r['fields'])|set(r['raw']) for r in rows))
    output=[]
    for row in targets:
        virtual=deepcopy(row);changes={}
        for op in recipe['operations']:
            name=op['field'];kind=op['op'];rawname=row.get('field_name_sources',{}).get(name,name)
            targetkey=bulkedit.FLAG_FIELDS.get(name,rawname)
            if targetkey in changes and changes[targetkey] is None and kind not in ('set','reset_to_base'):
                raise ValueError('Reset must be the last transformation for '+name+'; use a subsequent explicit Set rather than transforming an unresolved reset.')
            before=virtual['raw'].get(rawname,'')
            if name in bulkedit.FLAG_FIELDS:before=virtual['flags'][bulkedit.FLAG_FIELDS[name]]
            if name=='Assembly':before=changes.get('Assembly',row['fields']['Assembly'])
            value=op.get('value','')
            if kind=='fill_empty' and str(before).strip():continue
            if kind=='clear':value=''
            elif kind=='reset_to_base':value=None
            elif kind=='trim':value=str(before).strip()
            elif kind=='upper':value=str(before).upper()
            elif kind=='lower':value=str(before).lower()
            elif kind=='prefix':value=str(value)+str(before)
            elif kind=='suffix':value=str(before)+str(value)
            elif kind=='replace':value=str(before).replace(op['find'],str(value))
            elif kind=='copy':
                source=op['source']
                if source not in fields:raise ValueError('Unknown copy-source field: '+source)
                source_raw=row.get('field_name_sources',{}).get(source,source)
                source_key=bulkedit.FLAG_FIELDS.get(source,source_raw)
                if source_key in changes and changes[source_key] is None:raise ValueError('Cannot copy a field immediately after resetting its override; split the recipe.')
                value=virtual['flags'][source_key] if source_key in virtual['flags'] else virtual['raw'].get(source_raw,virtual['fields'].get(source,''))
            if name in bulkedit.FLAG_FIELDS and isinstance(value,str):
                if kind not in ('set','fill_empty','copy') or value.strip().lower() not in ('true','false','yes','no','1','0'):
                    raise ValueError('Population/inclusion flags require true/false or Reset, not text transforms.')
                value=value.strip().lower() in ('true','yes','1')
            for key,v in bulkedit.normalize_changes(row,{name:value}).items():
                changes[key]=v
                if key in virtual['flags']:virtual['flags'][key]=v
                else:virtual['raw'][key]=v
        if changes:output.append({'ids':[row['id']],'changes':changes})
    if not output:raise ValueError('All operations are no-ops for this scope.')
    return output,len(targets)

def preview(ws,variant,recipe):
    edit_entries,count=entries(ws,variant,recipe)
    review=bulkedit.preview(ws,variant,edit_entries)
    return dict(review,schema='wayricad-bulk-plan-1',variant=variant,recipe=deepcopy(recipe),matched=count,
                fingerprint=bulkedit.digest(ws,{'variant':variant,'recipe':recipe}),entries=edit_entries,
                grid_fingerprint=review['fingerprint'])

def apply(ws,variant,recipe,fingerprint,confirmation,acknowledge_loss=False):
    if fingerprint!=bulkedit.digest(ws,{'variant':variant,'recipe':recipe}):raise ValueError('Bulk plan is stale; review it again.')
    plan=preview(ws,variant,recipe)
    return bulkedit.apply(ws,variant,plan['entries'],plan['grid_fingerprint'],confirmation,acknowledge_loss)
