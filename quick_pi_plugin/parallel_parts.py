"""Detect two-terminal parts across the exact saved net pair; models stay reviewed."""
from __future__ import annotations

import re


def stage_pads(inventory,source_label,staged,index):
    """Resolve one primary stage before the final sink/path has been completed."""
    rows=inventory.get('terminals',[])
    source=[row for row in rows if source_label in (row['id'],row.get('label'))]
    if len(source)!=1:raise ValueError('Choose one unambiguous source pad.')
    net=source[0]['net']
    for number,stage in enumerate(staged):
        pads=[row for row in rows if row.get('reference',row.get('label','').rsplit('.',1)[0])==stage['reference']]
        incoming=[row for row in pads if row.get('net')==net]
        if len(pads)!=2 or len(incoming)!=1:raise ValueError('Parallel detection needs an unambiguous two-pad primary path.')
        outgoing=next(row for row in pads if row['id']!=incoming[0]['id'])
        if number==index:return incoming[0]['id'],outgoing['id']
        net=outgoing['net']
    raise ValueError('Select a component stage first.')


def candidates(inventory, from_id, to_id, excluded=()):
    rows=inventory.get('terminals',[]);by_id={row['id']:row for row in rows}
    start,end=by_id[from_id],by_id[to_id]
    if not start.get('net') or not end.get('net') or start['net']==end['net']:return []
    grouped={}
    for row in rows:
        owner=row.get('footprint_uuid')
        if owner:grouped.setdefault(owner,[]).append(row)
    excluded=set(excluded)|{start.get('footprint_uuid'),end.get('footprint_uuid')}
    result=[]
    for owner,pads in grouped.items():
        if owner in excluded or len(pads)!=2 or len({p['id'] for p in pads})!=2:continue
        incoming=[p for p in pads if p.get('net')==start['net']]
        outgoing=[p for p in pads if p.get('net')==end['net']]
        if len(incoming)!=1 or len(outgoing)!=1:continue
        a,b=incoming[0],outgoing[0]
        result.append({'id':a.get('reference',a.get('label','').rsplit('.',1)[0]),
                       'footprint_uuid':owner,'from_pad':a['id'],'to_pad':b['id'],
                       'component_value':a.get('component_value','')})
    return sorted(result,key=lambda row:(row['id'],row['footprint_uuid']))


def suggested_resistance(part):
    """Suggest only a bare resistor value; DCR, capacitors and diodes are not guessed."""
    if not re.fullmatch(r'R\d+',part.get('id',''),re.IGNORECASE):return ''
    text=str(part.get('component_value','')).strip().replace('Ω','ohm')
    embedded=re.fullmatch(r'(\d*)[rR](\d+)',text)
    if embedded:text=(embedded[1] or '0')+'.'+embedded[2]
    text=re.sub(r'[rR]$','',text)
    if not re.fullmatch(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?:Meg|[fpnumkKMGTµμ]?)(?:ohms?)?',text):return ''
    from .console import _model
    try:model=_model(text)
    except ValueError:return ''
    return text if model.get('resistance_ohm',0)>0 and not model.get('inductance_h',0) else ''


def with_parallel(request, staged, inventory):
    """Attach explicitly reviewed parallel components to the parsed primary path."""
    from copy import deepcopy
    from .console import _model
    result=deepcopy(request)
    for spec,configured in zip(result.get('series',[]),staged):
        selected=configured.get('parallel',[])
        if not selected:continue
        available={row['footprint_uuid']:row for row in candidates(inventory,spec['from_pad'],spec['to_pad'])}
        branches=[]
        for part in selected:
            found=available.get(part.get('footprint_uuid'))
            if found is None:raise ValueError('A parallel component no longer spans the selected net pair. Review the path.')
            model=_model(part['model'])
            if 'fixed_drop_v' in model or 'diode' in model:raise ValueError('Parallel DC paths currently support reviewed R/L models, not forward-drop models.')
            branches.append({key:found[key] for key in ('id','from_pad','to_pad')}|model)
        if 'fixed_drop_v' in spec or 'diode' in spec:raise ValueError('A forward-drop component cannot be used as a parallel R/L stage.')
        spec['parallel']=branches
    return result
