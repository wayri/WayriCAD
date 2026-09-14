"""Indexed catalogue finder with lightweight derived cache and paged records.

The disposable index never changes curated part revisions, assets, review keys,
stock evidence or catalogue epoch. Revisions rebuild only their derived entry.
No supplier requests are made. Health is freshly assessed for returned rows.
"""
from __future__ import annotations
from collections import Counter
import json
import time
from . import assetbundle, measures, partsdb
from .classification import classify, VERSION
from .catalogbrowse_legacy import rules

TABLE='wayricad_finder_index_v1'
SORTS={'mpn':'mpn','manufacturer':'manufacturer','value':'value','category':'category',
       'internal_pn':'internal_pn','updated':'updated','status':'status','revision':'revision'}


def ensure_index(lib, rebuild=False):
    start=time.perf_counter();db=lib.db
    db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
        id TEXT PRIMARY KEY, revision INTEGER NOT NULL, classifier TEXT NOT NULL,
        category TEXT NOT NULL, basis TEXT NOT NULL, manufacturer TEXT NOT NULL,
        mpn TEXT NOT NULL, value TEXT NOT NULL, footprint TEXT NOT NULL,
        internal_pn TEXT NOT NULL, status TEXT NOT NULL, kind TEXT NOT NULL,
        lifecycle TEXT NOT NULL, updated TEXT NOT NULL,
        symbol_count INTEGER NOT NULL, footprint_count INTEGER NOT NULL,
        model_count INTEGER NOT NULL, all3 INTEGER NOT NULL, incomplete INTEGER NOT NULL,
        fields TEXT NOT NULL, classification TEXT NOT NULL, assets TEXT NOT NULL)''')
    for name,columns in [('category','category,manufacturer,mpn,id'),('manufacturer','manufacturer,mpn,id'),
                         ('footprint','footprint'),('status','status'),('lifecycle','lifecycle')]:
        db.execute(f'CREATE INDEX IF NOT EXISTS kw_finder_{name}_v1 ON {TABLE}({columns})')
    if rebuild:db.execute(f'DELETE FROM {TABLE}')
    count=0
    while True:
        rows=db.execute(f'''SELECT p.payload FROM parts p LEFT JOIN {TABLE} b ON p.id=b.id
            WHERE b.id IS NULL OR b.revision!=p.revision OR b.classifier!=? LIMIT 500''',(VERSION,)).fetchall()
        if not rows:break
        records=[]
        for row in rows:
            p=json.loads(row[0]);f=p['fields'];c=classify(p);a=assetbundle.summary(p)
            complete3=any(s.get('symbol_hash') and s.get('footprint_hash') and s.get('models')
                          and all(m.get('status')=='stored' for m in s['models']) and not s.get('issues')
                          for s in assetbundle.asset_sets(p))
            # Date-sensitive stock remains a read-time assessment, not a green
            # flag frozen into this index. Lifecycle captures recorded labels.
            labels=[str(e.get('lifecycle','')).upper() for e in p.get('evidence',[]) if e.get('lifecycle')]
            labels.extend([str(f.get('Lifecycle','')).upper()])
            life='RISK' if any(any(x in v for x in ('NRND','EOL','OBSOLETE','DISCONTINUED','NOT RECOMMENDED')) for v in labels) else ('RECORDED' if any(labels) else 'UNKNOWN')
            records.append((p['id'],p['revision'],VERSION,c['category'],c['basis'],f.get('Manufacturer',''),
                            f.get('MPN',''),f.get('Value',''),f.get('Footprint',''),p.get('internal_pn',''),
                            p.get('status','candidate'),p.get('kind','generic'),life,p.get('updated_at',''),
                            a['symbol'],a['footprint'],a['model'],int(bool(complete3)),int(not a['complete_references']),
                            partsdb.encoded(f),partsdb.encoded(c),partsdb.encoded(a)))
        with lib.transaction():
            db.executemany(f'INSERT OR REPLACE INTO {TABLE} VALUES ({",".join("?" for _ in range(22))})',records)
        count+=len(records)
    db.execute(f'DELETE FROM {TABLE} WHERE id NOT IN (SELECT id FROM parts)')
    return {'schema':'wayricad-finder-index-1','updated_records':count,'milliseconds':round((time.perf_counter()-start)*1000,3),
            'classifier':VERSION,'authoritative_data_changed':False,'notice':'Disposable derived search index; original parts, revisions and approvals are unchanged.'}


def _scope(lib,query,status,kind,footprint,category,manufacturer,lifecycle,has_asset):
    where=[];args=[]
    partsdb.text(query,'query',4096)
    if query.strip():
        terms=query.split()[:32]
        if lib.meta('fts')=='1':
            q=' AND '.join('"'+t.replace('"','""')+'"*' for t in terms)
            where.append('id IN (SELECT id FROM parts_search WHERE parts_search MATCH ?)');args.append(q)
        else:
            # Metadata fallback is literal, not an executable regex/SQL query.
            for term in terms:
                where.append('id IN (SELECT id FROM parts WHERE instr(lower(payload),?)>0)');args.append(term.lower())
    for col,val in [('status',status),('kind',kind),('footprint',footprint),('manufacturer',manufacturer),('lifecycle',lifecycle)]:
        if val:where.append(col+'=?');args.append(val)
    if category:
        partsdb.text(category,'category',256)
        where.append('(category=? OR substr(category,1,?)=?)');args.extend([category,len(category)+1,category+'/'])
    if has_asset in ('symbol','footprint','model'):where.append(has_asset+'_count>0')
    elif has_asset=='all3':where.append('all3=1')
    elif has_asset=='incomplete':where.append('incomplete=1')
    return ' WHERE '+' AND '.join(where) if where else '',args


def _matches(f,record,compiled,unknown):
    matched=True
    for field,op,val,u,q in compiled:
        v=str(record['internal_pn'] if field=='@internal_pn' else record['status'] if field=='@status'
              else record['category'] if field in ('@category','@Category') else f.get(field,''))
        if op=='contains':ok=val.casefold() in v.casefold()
        elif op=='equals':ok=val.casefold()==v.casefold()
        elif op=='not_equals':ok=val.casefold()!=v.casefold()
        elif op=='missing':ok=not v.strip()
        elif op=='present':ok=bool(v.strip())
        else:
            n=measures.parse(v,u,dimension=q.dimension)
            if n.status!='known':unknown[field]+=1;ok=False
            else:ok={'<':n.value<q.value,'<=':n.value<=q.value,'>':n.value>q.value,'>=':n.value>=q.value,'numeric_equals':n.value==q.value}[op]
        matched=matched and ok
    return matched


def search(lib,query='',offset=0,limit=50,status='',kind='',footprint='',filters=None,has_asset='',
           category='',manufacturer='',lifecycle='',sort='mpn',descending=False,summary=False):
    start=time.perf_counter()
    if status and status not in ('candidate','preferred','deprecated','blocked'):raise ValueError('Unknown catalogue preference.')
    if kind and kind not in ('generic','orderable'):raise ValueError('Unknown catalogue identity type.')
    if has_asset not in ('','symbol','footprint','model','all3','incomplete'):raise ValueError('Unknown asset filter.')
    if lifecycle not in ('','RISK','RECORDED','UNKNOWN'):raise ValueError('Choose lifecycle RISK, RECORDED or UNKNOWN.')
    if sort not in SORTS:raise ValueError('Unknown catalogue sort field.')
    if type(descending) is not bool or type(summary) is not bool:raise ValueError('Boolean sort/summary flags required.')
    partsdb.number(offset,'offset',0,10000000);partsdb.number(limit,'limit',1,500)
    for v in (manufacturer,footprint):partsdb.text(v,'filter',4096)
    compiled=rules(filters);idx=ensure_index(lib);db=lib.db
    clause,args=_scope(lib,query,status,kind,footprint,category,manufacturer,lifecycle,has_asset)
    examined=db.execute(f'SELECT count(*) FROM {TABLE}'+clause,args).fetchone()[0]
    fields=set();unknown=Counter()
    source=TABLE
    if compiled:
        db.execute('DROP TABLE IF EXISTS temp.kw_finder_matches');db.execute('CREATE TEMP TABLE kw_finder_matches(id TEXT PRIMARY KEY)')
        matches=[]
        for r in db.execute(f'SELECT id,fields,internal_pn,status,category FROM {TABLE}'+clause,args):
            f=json.loads(r['fields']);fields.update(f)
            if _matches(f,r,compiled,unknown):matches.append((r['id'],))
        db.executemany('INSERT INTO kw_finder_matches VALUES (?)',matches)
        source=f'(SELECT * FROM {TABLE} WHERE id IN (SELECT id FROM kw_finder_matches))'
        clause='';args=[]
    total=db.execute(f'SELECT count(*) FROM {source}'+clause,args).fetchone()[0]
    facets={}
    for col,name in [('manufacturer','Manufacturer'),('footprint','Footprint'),('status','status'),('category','Category'),('lifecycle','lifecycle')]:
        facets[name]=[{'value':r[0],'count':r[1]} for r in db.execute(f'SELECT {col},count(*) FROM {source}'+clause+f' GROUP BY {col} ORDER BY count(*) DESC,{col} LIMIT 80',args)]
    # Full-library tree is labelled separately from filtered facets. Its counts
    # are not represented as counts for the current narrower result set.
    tree=Counter()
    leafs=db.execute(f'SELECT category,count(*) FROM {TABLE} GROUP BY category ORDER BY count(*) DESC LIMIT 1000').fetchall()
    for cat,n in leafs:
        split=cat.split('/')
        for i in range(1,len(split)+1):tree['/'.join(split[:i])]+=n
    ordered=SORTS[sort]+' COLLATE NOCASE '+('DESC' if descending else 'ASC')+',id ASC'
    records=db.execute(f'SELECT * FROM {source}'+clause+' ORDER BY '+ordered+' LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    items=[]
    for record in records:
        f=json.loads(record['fields']);fields.update(f)
        p=lib.get(record['id']);original=p
        if summary:
            p={k:p.get(k) for k in ('id','revision','kind','internal_pn','status','updated_at','content_hash')}
            p['fields']=f
        p['classification']=json.loads(record['classification']);p['asset_summary']=json.loads(record['assets'])
        # Read current evidence only for one page, not every text-matched record.
        # original retained above; do not load a full record twice.
        p['health']=partsdb.catalog_health(original);items.append(p)
    return {'schema':'wayricad-catalog-search-3','items':items,'total':total,'offset':offset,'limit':limit,
            'next_offset':offset+limit if offset+limit<total else None,'fields':sorted(fields),'facets':facets,
            'category_tree':[{'value':k,'count':v,'depth':k.count('/')} for k,v in sorted(tree.items())],
            'category_tree_scope':'entire catalogue; at most 1000 most frequent leaf categories',
            'numeric_unknown':dict(unknown),'examined':examined,'records_loaded':len(items),
            'index':idx,'elapsed_ms':round((time.perf_counter()-start)*1000,3),
            'field_list_scope':'matched rows for typed searches; returned page for ordinary searches. Arbitrary names may be typed.',
            'notice':'Categories are declared or explainable suggestions, never qualification. Availability is recorded evidence, not live stock. Filters apply before pagination.'}
