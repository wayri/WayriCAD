"""Catalogue-only structured searches; all filters are data, never executable code."""
from __future__ import annotations
from collections import Counter
from . import assetbundle, measures, partsdb


def rules(value):
    if value is None:return []
    if not isinstance(value,list) or len(value)>20:raise ValueError('Use up to 20 catalogue field filters.')
    result=[]
    for x in value:
        if not isinstance(x,dict) or set(x)-{'field','op','value','unit'}:raise ValueError('Invalid catalogue field rule.')
        field=partsdb.text(x.get('field',''),'field',256);op=x.get('op');val=partsdb.text(x.get('value',''),'value',4096)
        if not field.strip() or op not in ('contains','equals','not_equals','missing','present','<','<=','>','>=','numeric_equals'):raise ValueError('Choose a field and supported catalogue operator.')
        q=None;u=x.get('unit','number') or 'number'
        if op in ('<','<=','>','>=','numeric_equals'):
            q=measures.literal(val,u)
            if q.status!='known':raise ValueError('Invalid numeric catalogue threshold: '+q.reason)
            u=q.input_unit or u
        result.append((field,op,val,u,q))
    return result


def search(lib,query='',offset=0,limit=50,status='',kind='',footprint='',filters=None,has_asset=''):
    if status and status not in ('candidate','preferred','deprecated','blocked'):raise ValueError('Unknown catalogue preference.')
    if kind and kind not in ('generic','orderable'):raise ValueError('Unknown catalogue identity type.')
    if has_asset not in ('','symbol','footprint','model','all3','incomplete'):raise ValueError('Unknown asset filter.')
    partsdb.number(offset,'offset',0,10000000);partsdb.number(limit,'limit',1,500)
    compiled=rules(filters);items=[];matched=0;numeric_unknown=Counter();fields=set();facets={k:Counter() for k in ('Manufacturer','Footprint','status','model_state')}
    # Ordinary text remains indexed. Typed predicates apply BEFORE pagination, not
    # only to the visible first page; bounded to the catalogue's 100k-part limit.
    cursor=0;scanned=0
    while True:
        page=lib.search(query,cursor,500,status,kind,footprint)
        for p in page['items']:
            scanned+=1;fields.update(p['fields']);a=assetbundle.summary(p);match=True
            for field,op,val,u,q in compiled:
                v=str(p.get('internal_pn','') if field=='@internal_pn' else p.get('status','') if field=='@status' else p['fields'].get(field,''))
                if op=='contains':ok=val.casefold() in v.casefold()
                elif op=='equals':ok=val.casefold()==v.casefold()
                elif op=='not_equals':ok=val.casefold()!=v.casefold()
                elif op=='missing':ok=not v.strip()
                elif op=='present':ok=bool(v.strip())
                else:
                    n=measures.parse(v,u,dimension=q.dimension)
                    if n.status!='known':numeric_unknown[field]+=1;ok=False
                    else:ok={'<':n.value<q.value,'<=':n.value<=q.value,'>':n.value>q.value,'>=':n.value>=q.value,'numeric_equals':n.value==q.value}[op]
                match=match and ok
            if has_asset in ('symbol','footprint','model'):match=match and a[has_asset]>0
            elif has_asset=='all3':match=match and any(s.get('symbol_hash') and s.get('footprint_hash') and s.get('models') and all(m.get('status')=='stored' for m in s['models']) and not s.get('issues') for s in assetbundle.asset_sets(p))
            elif has_asset=='incomplete':match=match and not a['complete_references']
            if not match:continue
            for k in facets:facets[k][a['model_state'] if k=='model_state' else p.get(k) if k=='status' else p['fields'].get(k,'')]+=1
            if offset<=matched<offset+limit:
                p['asset_summary']=a;p['health']=partsdb.catalog_health(p);items.append(p)
            matched+=1
        if page['next_offset'] is None:break
        cursor=page['next_offset']
    return {'schema':'wayricad-catalog-search-2','items':items,'total':matched,'offset':offset,'limit':limit,'next_offset':offset+limit if offset+limit<matched else None,
            'fields':sorted(fields),'facets':{k:[{'value':v,'count':n} for v,n in c.most_common(80)] for k,c in facets.items()},
            'numeric_unknown':dict(numeric_unknown),'examined':scanned,'notice':'Filters intersect (AND). Missing/invalid numeric data does not match numeric rules. Stored assets are not qualification.'}
