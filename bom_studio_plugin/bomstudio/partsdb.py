"""Versioned local engineering catalog. SQLite + content-addressed native assets.

Harvesting is read-only. A reviewed plan imports observations, not qualifications.
No network requests, installation-directory writes, or implicit source-file edits.
"""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import sqlite3
import zipfile
import io
from .native import Project, BASE, sha
from .engine import Workspace, now
from . import evidence, intelligence
from .sexpr import parse, properties, quote, apply_edits
from .footprints import Inspector

SCHEMA = 'wayricad-parts-library-1'
MAX_PARTS = 100000
MAX_PROJECTS = 500
IGNORED_DIRS = {'.git','.svn','node_modules','.venv','venv','.wayricad-bom-backups','__pycache__'}
PROTECTED = {'Reference','Qty','Required','OrderQty','LineCost','OrderCost','UUID','Source','Sheet','Item','Assembly','InBOM','OnBoard','InPosFiles','ExcludeFromSim'}
CRITICAL = ('Value','Footprint','Voltage','VoltageRating','Voltage_Rating','Power','PowerRating','Tolerance','Dielectric','Temp_Min','Temp_Max','Qualification','Technology')


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':'), allow_nan=False)


def digest(value):
    return sha(encoded(value).encode())


def text(value, name='text', limit=32767):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value:
        raise ValueError('Invalid '+name)
    return value


def number(value, name, low=0, high=10**12):
    if type(value) is not int or not low<=value<=high:raise ValueError(f'{name}: expected integer {low}..{high}.')
    return value


def record_identity(fields, source=''):
    m,p=evidence.identity(fields.get('Manufacturer',''),fields.get('MPN',''))
    if m and p:return 'P-'+digest([m,p])[:24]
    # A generic, unresolved record is not an orderable identity and never pools procurement.
    return 'G-'+digest([source,fields.get('Value',''),fields.get('Footprint',''),fields.get('LibrarySymbol','')])[:24]


def normalized(fields, ref=''):
    v=intelligence.normalized_value(fields.get('Value',''),ref,fields.get('LibrarySymbol',''))
    return encoded(v) if v else encoded(['literal',fields.get('Value','')])


def _validate_part(p):
    if not isinstance(p,dict):raise ValueError('Part must be an object.')
    if p.get('kind') not in ('orderable','generic'):raise ValueError('Part kind: orderable or generic.')
    if not re.fullmatch(r'[PG]-[a-f0-9]{24}',p.get('id','')):raise ValueError('Invalid part ID.')
    fields=p.get('fields')
    if not isinstance(fields,dict) or len(fields)>500:raise ValueError('At most 500 fields per catalog part.')
    for k,v in fields.items():
        text(k,'field name',256);text(v,'field value')
        if k in ('__proto__','constructor','prototype'):raise ValueError('Unsafe field name.')
    if p['kind']=='orderable' and record_identity(fields)!=p['id']:raise ValueError('Exact manufacturer/MPN identity cannot change; create a new part instead.')
    if p.get('status','candidate') not in ('candidate','preferred','deprecated','blocked'):raise ValueError('Catalog preference: candidate, preferred, deprecated or blocked. Preference is not qualification.')
    if not isinstance(p.get('tags',[]),list) or len(p.get('tags',[]))>100:raise ValueError('At most 100 tags.')
    for tag in p.get('tags',[]):text(tag,'tag',128)
    for key in ('sources','assets','conflicts','evidence','asset_sets'):
        if not isinstance(p.get(key,[]),list):raise ValueError('Invalid '+key)
    if len(p.get('sources',[]))>20000:raise ValueError('Too many provenance records for one part.')
    evidence.validate_ledger(p.get('evidence',[]))
    if p.get('land_pattern'):
        from .qualification import validate_spec
        validate_spec(p['land_pattern'])
        if evidence.identity(p['land_pattern']['manufacturer'],p['land_pattern']['mpn'])!=evidence.identity(fields.get('Manufacturer',''),fields.get('MPN','')):raise ValueError('Land-pattern specification identity differs from catalog identity.')
    if 'qualified' in p or 'approved' in p:raise ValueError('Qualifications belong in signed local review records, not an editable part flag.')
    encoded(p)
    return p


class Library:
    def __init__(self, directory, create=False):
        self.root=Path(directory).expanduser().absolute()
        if self.root.is_symlink():raise ValueError('Library root must not be a symbolic link.')
        if create:
            if self.root.exists() and (not self.root.is_dir() or any(self.root.iterdir())):
                raise FileExistsError('Create requires a NEW or empty library directory.')
            self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.file=self.root/'catalog.sqlite3'
        if not create and not self.file.is_file():raise FileNotFoundError('No WayriCAD library at '+str(self.root))
        if self.file.is_symlink():raise ValueError('Catalog database must not be a symbolic link.')
        self.db=sqlite3.connect(str(self.file),timeout=10,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA busy_timeout=10000')
        if create:self._create()
        row=self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if not row or row[0]!=SCHEMA:self.close();raise ValueError('Unsupported catalog schema.')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
    def _create(self):
        self.db.executescript('''
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE parts(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, manufacturer TEXT, mpn TEXT, value_key TEXT, footprint TEXT, payload TEXT NOT NULL);
        CREATE INDEX parts_identity ON parts(manufacturer,mpn);
        CREATE INDEX parts_match ON parts(footprint,value_key);
        CREATE TABLE revisions(part_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, time TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(part_id,revision));
        CREATE TABLE assets(hash TEXT PRIMARY KEY, media TEXT NOT NULL, body BLOB NOT NULL);
        CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TABLE reviewers(name TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE decisions(id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL);
        CREATE TABLE inventory(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')
        self.db.executemany('INSERT INTO meta VALUES (?,?)',[('schema',SCHEMA),('epoch','0'),('created',now()),('id',os.urandom(16).hex()),('review_key',os.urandom(32).hex())])
        try:
            self.db.execute('CREATE VIRTUAL TABLE parts_search USING fts5(id UNINDEXED, content)')
            self.db.execute("INSERT INTO meta VALUES ('fts','1')")
        except sqlite3.OperationalError:self.db.execute("INSERT INTO meta VALUES ('fts','0')")
        try:os.chmod(self.file,0o600)
        except OSError:pass
    def close(self):self.db.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def meta(self,key):return self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()[0]
    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:yield;self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
    def touch(self):self.db.execute("UPDATE meta SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='epoch'")
    def audit(self,kind,payload):
        prev=self.db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        prev=prev[0] if prev else '';t=now();s=encoded(payload);h=digest([t,kind,s,prev])
        self.db.execute('INSERT INTO audit(time,kind,payload,prev,hash) VALUES (?,?,?,?,?)',(t,kind,s,prev,h))
    def info(self):
        return {'schema':SCHEMA,'path':str(self.root),'library_id':self.meta('id'),'epoch':int(self.meta('epoch')),
                'parts':self.db.execute('SELECT COUNT(*) FROM parts').fetchone()[0],
                'revisions':self.db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0],
                'assets':self.db.execute('SELECT COUNT(*) FROM assets').fetchone()[0],
                'search':'SQLite FTS5' if self.meta('fts')=='1' else 'bounded literal search',
                'trust':'Local single-user trust domain. Scraped fields are observations, never automatic qualifications.'}
    def get(self,pid,revision=None):
        r=self.db.execute('SELECT payload FROM parts WHERE id=?',(pid,)).fetchone() if revision is None else self.db.execute('SELECT payload FROM revisions WHERE part_id=? AND revision=?',(pid,revision)).fetchone()
        if not r:raise ValueError('Unknown catalog part/revision: '+pid)
        return json.loads(r[0])
    def search(self,query='',offset=0,limit=50,status='',kind='',footprint=''):
        text(query,'query',4096);number(offset,'offset',0,10000000);number(limit,'limit',1,500)
        args=[];where=[]
        if query.strip():
            if self.meta('fts')=='1':
                terms=re.findall(r'\S+',query)[:32];q=' AND '.join('"'+s.replace('"','""')+'"*' for s in terms)
                where.append('id IN (SELECT id FROM parts_search WHERE parts_search MATCH ?)');args.append(q)
            else:
                for term in query.split()[:32]:where.append('instr(lower(payload),?)>0');args.append(term.lower())
        if status:where.append("json_extract(payload,'$.status')=?");args.append(status)
        if kind:where.append("json_extract(payload,'$.kind')=?");args.append(kind)
        if footprint:where.append('footprint=?');args.append(footprint)
        clause=' WHERE '+' AND '.join(where) if where else ''
        total=self.db.execute('SELECT count(*) FROM parts'+clause,args).fetchone()[0]
        rows=self.db.execute('SELECT payload FROM parts'+clause+' ORDER BY manufacturer,mpn,id LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
        return {'schema':'wayricad-catalog-search-1','total':total,'offset':offset,'limit':limit,'items':[json.loads(r[0]) for r in rows], 'next_offset':offset+limit if offset+limit<total else None}
    def put(self,p,actor,reason,expected=None):
        _validate_part(p);text(actor,'actor',128);text(reason,'reason',2000)
        if not actor.strip() or not reason.strip():raise ValueError('Actor and change reason required.')
        old=self.db.execute('SELECT revision FROM parts WHERE id=?',(p['id'],)).fetchone()
        current=old[0] if old else 0
        if expected is not None and expected!=current:raise ValueError('Catalog revision is stale; reload before editing.')
        if not old and self.db.execute('SELECT count(*) FROM parts').fetchone()[0]>=MAX_PARTS:raise ValueError('Catalog size exceeds this release\'s 100,000 part limit.')
        p=deepcopy(p);p['revision']=current+1;p['updated_at']=now();p['actor']=actor
        p['content_hash']=digest({k:v for k,v in p.items() if k not in ('content_hash','updated_at','actor','revision')})
        fields=p['fields'];m,mpn=evidence.identity(fields.get('Manufacturer',''),fields.get('MPN',''))
        payload=encoded(p);value_key=normalized(fields,p.get('reference_hint',''))
        self.db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,manufacturer=excluded.manufacturer,mpn=excluded.mpn,value_key=excluded.value_key,footprint=excluded.footprint,payload=excluded.payload',
                        (p['id'],p['revision'],m,mpn,value_key,fields.get('Footprint',''),payload))
        self.db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?)',(p['id'],p['revision'],payload,actor,reason,now(),sha(payload.encode())))
        if self.meta('fts')=='1':
            self.db.execute('DELETE FROM parts_search WHERE id=?',(p['id'],))
            self.db.execute('INSERT INTO parts_search VALUES (?,?)',(p['id'],encoded(fields)+' '+encoded(p.get('tags',[]))+' '+str(p.get('notes',''))+' '+p['id']+' '+p.get('internal_pn','')+' '+encoded([{'project':x.get('project'),'reference':x.get('reference'),'variant':x.get('variant')} for x in p.get('sources',[])])+' '+encoded([{'lifecycle':x.get('lifecycle'),'supplier':x.get('supplier'),'sku':x.get('sku')} for x in p.get('evidence',[])])))
        self.touch();self.audit('part-revision',{'id':p['id'],'revision':p['revision'],'hash':p['content_hash'],'actor':actor,'reason':reason})
        return p
    def history(self,pid):
        return [dict(r) for r in self.db.execute('SELECT revision,actor,reason,time,hash FROM revisions WHERE part_id=? ORDER BY revision DESC',(pid,))]
    def snapshot(self):
        parts=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM parts ORDER BY id')]
        return {'schema':SCHEMA,'library_id':self.meta('id'),'parts':parts,'inventory':[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM inventory ORDER BY id')],
                'notice':'Portable data only. Local reviewer credentials/keys/approvals are intentionally excluded.'}
    def verify(self):
        errors=[];prev=''
        if self.db.execute('PRAGMA quick_check').fetchone()[0]!='ok':errors.append('SQLite quick_check failed.')
        for r in self.db.execute('SELECT * FROM audit ORDER BY seq'):
            if r['prev']!=prev or r['hash']!=digest([r['time'],r['kind'],r['payload'],r['prev']]):errors.append('Audit chain mismatch at '+str(r['seq']))
            prev=r['hash']
        for r in self.db.execute('SELECT * FROM assets'):
            if sha(r['body'])!=r['hash']:errors.append('Asset hash mismatch: '+r['hash'])
        for r in self.db.execute('SELECT * FROM revisions'):
            if sha(r['payload'].encode())!=r['hash']:errors.append('Revision hash mismatch: '+r['part_id'])
        for r in self.db.execute('SELECT * FROM parts'):
            h=self.db.execute('SELECT payload FROM revisions WHERE part_id=? AND revision=?',(r['id'],r['revision'])).fetchone()
            if not h or h[0]!=r['payload']:errors.append('Current part differs from revision: '+r['id'])
        from .assetbundle import validate_sets
        for r in self.db.execute('SELECT payload FROM revisions'):
            try:
                part=json.loads(r[0]);validate_sets(part)
                for a in part.get('assets',[]):
                    if not self.db.execute('SELECT 1 FROM assets WHERE hash=?',(a['hash'],)).fetchone():errors.append('Missing referenced asset: '+a['hash'])
            except (ValueError,KeyError) as exc:errors.append(str(exc))
        return {'ok':not errors,'errors':errors,'notice':'Integrity check, not external authorship proof or a defense against a library administrator rewriting the entire store.'}


def _assets(ws,row,inspector):
    out=[];c=ws.project.by_id[row['id']];m=c.members[0]
    libs=m.doc.tree.one('lib_symbols');sym=next((s for s in libs.nodes('symbol') if s.val()==c.lib_id),None) if libs else None
    if sym and not sym.one('extends'):
        raw=m.doc.text[sym.start:sym.end].encode()
        out.append({'kind':'symbol','name':c.lib_id,'hash':sha(raw),'text':raw.decode(),'source':str(m.doc.path)})
    fp=inspector.library(row['fields'].get('Footprint',''))
    if fp.get('status')=='read':
        path=Path(fp['source']);raw=path.read_bytes()
        if sha(raw)!=fp['hash']:raise ValueError('Footprint changed during harvesting.')
        content=raw.decode('utf-8-sig')
        out.append({'kind':'footprint','name':row['fields']['Footprint'],'hash':sha(content.encode()),'source_hash':sha(raw),'text':content,'source':str(path)})
    return out


def discover(paths,recursive=False,progress=None,cancel=None):
    if not isinstance(paths,list) or not paths or len(paths)>MAX_PROJECTS:raise ValueError('Choose 1..500 explicit project paths/directories.')
    found=set();visited=0
    for item in paths:
        p=Path(text(item,'path',4096)).expanduser().absolute()
        if p.is_symlink():raise ValueError('Top-level symlink not scanned: '+str(p))
        if p.is_file():
            if p.suffix not in ('.kicad_pro','.kicad_sch'):raise ValueError('Select a root .kicad_pro or .kicad_sch.')
            found.add(p.resolve())
        elif p.is_dir():
            for root,dirs,files in os.walk(p,followlinks=False):
                if cancel and cancel():raise InterruptedError('Project discovery canceled; catalog unchanged.')
                visited+=1
                if visited>100000:raise ValueError('Directory scan limit reached; choose narrower roots.')
                dirs[:]=[d for d in sorted(dirs) if d not in IGNORED_DIRS and not d.endswith('-backups') and not (Path(root)/d).is_symlink()] if recursive else []
                for f in files:
                    candidate=Path(root)/f
                    if f.endswith('.kicad_pro') and not candidate.is_symlink():found.add(candidate.resolve())
                if len(found)>MAX_PROJECTS:raise ValueError('More than 500 projects found; split the harvest.')
        else:raise FileNotFoundError('Project/root does not exist: '+str(p))
    # Prefer project files when both forms were explicitly given.
    return sorted(p for p in found if p.suffix!='.kicad_sch' or p.with_suffix('.kicad_pro') not in found)


def harvest(paths,recursive=False,include_variants=True,capture_assets=True,progress=None,cancel=None,load_workspace=True,asset_options=None):
    from . import assetbundle
    asset_options=assetbundle.options(asset_options)
    files=discover(paths,recursive,progress,cancel);parts={};sources={};failures=[]
    if not files:raise ValueError('No projects found. Directory scanning selects .kicad_pro files; supply root schematics explicitly.')
    for index,path in enumerate(files):
        if cancel and cancel():raise InterruptedError('Harvest canceled; catalog unchanged.')
        if progress:progress(index,len(files),'Reading '+path.name)
        prior=deepcopy(parts);prior_sources=dict(sources)
        try:
            ws=Workspace(Project(path),load=load_workspace);resolver=assetbundle.Resolver(ws,asset_options) if capture_assets else None
            if ws.project.blockers:raise ValueError('Project adapter errors; resolve them before harvesting.')
            scopes=[BASE]+list(ws.state['variants']) if include_variants else [BASE]
            asset_cache={}
            for variant in scopes:
                for row in ws.rows(variant):
                    if cancel and cancel():raise InterruptedError('Harvest canceled; catalog unchanged.')
                    if row.get('errors'):raise ValueError('Unresolved expressions must be repaired before harvesting resolved parts.')
                    fields={k:str(v) for k,v in row['fields'].items() if k not in PROTECTED and not k.startswith('@')}
                    fields['LibrarySymbol']=ws.project.by_id[row['id']].lib_id
                    # Canonical fields are retained alongside additional searchable metadata.
                    pid=record_identity(fields,str(ws.project.root));kind='orderable' if pid.startswith('P-') else 'generic'
                    source={'project':str(path),'variant':variant,'reference':row['ref'],'instance':row['id'],'source_hashes':ws.project.hashes,'raw_fields':row['raw']}
                    source['id']=digest(source)
                    if pid not in parts:
                        parts[pid]={'id':pid,'kind':kind,'fields':fields,'status':'candidate','tags':[],'sources':[],'assets':[],'asset_sets':[],'conflicts':[],'evidence':[],
                                    'reference_hint':row['ref'],'internal_pn':fields.get('InternalPN') or 'KW-'+pid[2:14].upper()}
                    p=parts[pid];p['sources'].append(source)
                    for k,v in fields.items():
                        old=p['fields'].get(k,'')
                        if old and v and old!=v:
                            conflict={'field':k,'retained':old,'observed':v,'source':source['id']}
                            if conflict not in p['conflicts']:p['conflicts'].append(conflict)
                        elif not old and v:p['fields'][k]=v
                    if capture_assets:
                        key=(row['id'],fields.get('Footprint',''),variant)
                        if key not in asset_cache:asset_cache[key]=assetbundle.capture(resolver,row,variant)
                        captured,aset=asset_cache[key]
                        for a in captured:
                            if not any(x['hash']==a['hash'] and x['kind']==a['kind'] for x in p['assets']):p['assets'].append(a)
                        if aset not in p['asset_sets']:p['asset_sets'].append(aset)
                    identity=evidence.identity(fields.get('Manufacturer',''),fields.get('MPN',''))
                    for e in ws.state.get('evidence',[]):
                        if evidence.identity(e['manufacturer'],e['mpn'])==identity and e not in p['evidence']:p['evidence'].append(deepcopy(e))
            ws.project.check_unchanged();sources.update(ws.project.hashes)
            if resolver:
                for name,h in resolver.sources.items():
                    if not Path(name).is_file() or sha(Path(name).read_bytes())!=h:raise ValueError('Asset source changed during scan: '+name)
                sources.update(resolver.sources)
                blobs={a['hash']:a.get('size',0) for x in parts.values() for a in x['assets']}
                if sum(blobs.values())>assetbundle.MAX_CAPTURE:raise ValueError('Capture exceeds 256 MiB of unique assets; split the project scan.')
            if load_workspace and ws.sidecar.exists():
                if sha(ws.sidecar.read_bytes())!=ws.sidecar_hash:raise ValueError('Workspace sidecar changed during harvesting.')
                sources[str(ws.sidecar)]=ws.sidecar_hash
        except InterruptedError:raise
        except (ValueError,OSError,KeyError) as exc:
            parts=prior;sources=prior_sources;failures.append({'project':str(path),'error':str(exc)})
        if len(parts)>MAX_PARTS:raise ValueError('Harvest exceeds 100,000 unique parts.')
    plan={'schema':'wayricad-harvest-1','sources':sources,'parts':list(parts.values()),'failures':failures,'projects':len(files),
          'asset_options':asset_options,'asset_summary':{p['id']:assetbundle.summary(p) for p in parts.values()},
          'warning':'Assets and models are retained where resolvable; missing references remain explicit. Resolved values are catalog observations. Existing curated values win conflicts. No qualification, live stock or redistribution permission is inferred.'}
    plan['fingerprint']=digest(plan)
    if progress:progress(len(files),len(files),'Harvest ready for review; no library writes.')
    return plan


def import_harvest(lib,plan,confirmation,actor,allow_partial=False):
    if confirmation!='IMPORT':raise ValueError('Type IMPORT after reviewing the harvest.')
    if plan.get('schema')!='wayricad-harvest-1' or plan.get('fingerprint')!=digest({k:v for k,v in plan.items() if k!='fingerprint'}):raise ValueError('Harvest fingerprint does not match.')
    if plan.get('failures') and not allow_partial:raise ValueError('Some projects failed. Review and explicitly acknowledge partial import.')
    if len(plan.get('parts',[]))>MAX_PARTS:raise ValueError('Too many harvested parts.')
    for path,h in plan['sources'].items():
        if not Path(path).is_file() or sha(Path(path).read_bytes())!=h:raise ValueError('Harvest source changed; scan again: '+path)
    from . import assetbundle
    changed=[];imported_bytes={}
    with lib.transaction():
        for candidate in plan['parts']:
            p=deepcopy(candidate);_validate_part(p)
            for asset in p['assets']:
                raw=assetbundle.payload(asset)
                asset.pop('text',None);asset.pop('data_b64',None)
                imported_bytes[asset['hash']]=len(raw)
                if sum(imported_bytes.values())>assetbundle.MAX_CAPTURE:raise ValueError('Imported capture exceeds 256 MiB.')
                lib.db.execute('INSERT OR IGNORE INTO assets VALUES (?,?,?)',(asset['hash'],asset['kind'],raw))
            assetbundle.validate_sets(p)
            existing=lib.db.execute('SELECT payload FROM parts WHERE id=?',(p['id'],)).fetchone()
            if existing:
                old=json.loads(existing[0]);merged=deepcopy(old)
                for k,v in p['fields'].items():
                    if not merged['fields'].get(k):merged['fields'][k]=v
                    elif v and merged['fields'][k]!=v:
                        conflict={'field':k,'retained':merged['fields'][k],'observed':v,'source':'new-harvest'}
                        if conflict not in merged['conflicts']:merged['conflicts'].append(conflict)
                for key in ('sources','assets','conflicts','evidence','asset_sets'):
                    for entry in p.get(key,[]):
                        if entry not in merged.setdefault(key,[]):merged[key].append(entry)
                if merged==old:continue
                p=merged
            changed.append({'id':p['id'],'revision':lib.put(p,actor,'Reviewed project harvest')['revision']})
    return {'changed':changed,'count':len(changed),'failures':plan.get('failures',[]),'native_files_written':False}


def catalog_health(p,market='IN',freshness_hours=24,clock=None,low_stock_threshold=100):
    number(low_stock_threshold,'low stock threshold',0,10**12)
    clock=clock or datetime.now(timezone.utc);records=p.get('evidence',[]);states=[]
    for r in records:
        age=intelligence.age_hours(r,clock)
        if r.get('reviewed') and r.get('source_url') and age is not None and 0<=age<=freshness_hours:
            label=str(r.get('lifecycle','')).strip().upper()
            if label:states.append(label)
    # Preserve negative historical lifecycle observations rather than silently green them on expiry.
    historical=[str(r.get('lifecycle','')).upper() for r in records]+[p['fields'].get('Lifecycle','').upper()]
    risky=[s for s in historical if s.strip()=='EOL' or any(x in s for x in ('NRND','NOT RECOMMENDED','OBSOLETE','END OF LIFE','DISCONTINUED'))]
    lifecycle='AT RISK' if risky else 'RECENT OBSERVATION' if states else 'UNKNOWN'
    req={'required':1}
    st=intelligence.stock_status(req,records,{'region':market,'stock_age_hours':freshness_hours},clock)
    usable=[o['stock'] for o in st['offers'] if o['eligible']]
    low_stock=bool(usable and max(usable)<low_stock_threshold)
    conflicts=[c for c in p.get('conflicts',[]) if c.get('field') in CRITICAL or c.get('field') in ('MPN','Manufacturer')]
    return {'lifecycle':lifecycle,'lifecycle_labels':sorted(set(risky or states)),'stock':st,'metadata_conflicts':len(conflicts),'low_stock':low_stock,'low_stock_threshold':low_stock_threshold,
            'state':'blocked' if p.get('status')=='blocked' or conflicts else 'warning' if risky or low_stock or p.get('status')=='deprecated' else 'unknown' if lifecycle=='UNKNOWN' or st.get('status')=='unknown' else 'observed',
            'tooltip':'Lifecycle/stock are dated entered/imported observations; not a live query. Preference is separate from qualification.'}


def recommendations(lib,ws,variant,cid,limit=20):
    row=next((r for r in ws.rows(variant) if r['id']==cid),None)
    if not row:raise ValueError('Unknown component.')
    fields=row['fields'];fp=fields.get('Footprint','');value=normalized(fields,row['ref'])
    if not fp:return {'component':row['ref'],'items':[],'reason':'No footprint; no package-based recommendation can be made.'}
    results=lib.db.execute('SELECT payload FROM parts WHERE footprint=? AND value_key=? LIMIT 1000',(fp,value)).fetchall()
    items=[]
    for r in results:
        p=json.loads(r[0]);issues=[];missing=[]
        if p['kind']!='orderable':continue
        for k in CRITICAL:
            if k in ('Value','Footprint'):continue
            needed=str(fields.get(k,'')).strip();offered=str(p['fields'].get(k,'')).strip()
            if needed and not offered:missing.append(k)
            elif needed and offered and needed!=offered:issues.append(k+': '+needed+' vs '+offered)
        # For nonpassives, matching a marketing Value label is never sufficient electrical equivalence.
        passive=bool(re.fullmatch(r'[RCL]\d+.*',row['ref'],re.I))
        if not passive:missing.append('electrical/pin-function equivalence (active device)')
        else:
            essentials={'R':('Tolerance','Power','Voltage'),'C':('Tolerance','Voltage','Dielectric'),'L':('Tolerance','Current')}[row['ref'][0].upper()]
            for key in essentials:
                if not str(fields.get(key,'')).strip() or not str(p['fields'].get(key,'')).strip():
                    if key not in missing:missing.append(key)
        missing.append('application suitability and manufacturer land-pattern qualification')
        health=catalog_health(p);blocked=bool(issues or health['state']=='blocked' or health['lifecycle']=='AT RISK')
        score=40+(20 if p.get('status')=='preferred' else 0)+(10 if not missing else 0)+(5 if p['fields'].get('MPN')==fields.get('MPN') else 0)
        items.append({'part':p,'health':health,'score':score,'state':'blocked' if blocked else 'review',
                      'reasons':['Exact selected footprint','Equivalent supported value notation' if passive else 'Exact value label (not equivalence)'],
                      'conflicts':issues,'missing_evidence':missing,'automatic_substitution':False})
    items.sort(key=lambda x:(x['state']=='blocked',-x['score'],x['part']['internal_pn']))
    return {'schema':'wayricad-recommendations-1','component':row['ref'],'id':cid,'variant':variant,'items':items[:number(limit,'limit',1,100)],
            'matched':len(items),'notice':'Recommendation ranking is screening, not approval. Candidate edits never replace the symbol, connect pins or place a part.'}


def export_native_library(lib,ids,choices=None,require_complete=False,model_prefix='${KIPRJMOD}/WayriCAD.3dshapes'):
    from .assetbundle import export_library
    return export_library(lib,ids,choices,require_complete,model_prefix)
