"""Shared GUI/CLI service for the local engineering library and review workflows."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from datetime import datetime,timezone
import json
import os
import secrets
import threading
import tempfile
from . import partsdb,qualification,governance,variantlab,masslib,buildplan,bulkedit,automation,evidence
from .native import BASE
from .partsdb import Library,digest,text


def preference_file():
    if os.name=='nt':base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))
    elif __import__('sys').platform=='darwin':base=Path.home()/'Library'/'Application Support'
    else:base=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))
    return base/'WayriCADBOMStudio'/'preferences.json'


def default_library():
    try:
        p=preference_file()
        if p.is_symlink() or p.stat().st_size>16384:return ''
        return str(automation.load_json(p).get('library',''))
    except (OSError,ValueError,TypeError):return ''


def remember_library(path):
    p=preference_file();p.parent.mkdir(parents=True,exist_ok=True)
    if p.is_symlink():raise ValueError('Refuse a symlink preferences file.')
    fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.preferences-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump({'schema':'wayricad-preferences-1','library':str(path)},f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,p)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()


class Tasks:
    """Bounded in-process, cancelable read-only tasks. No persistent scheduler."""
    def __init__(self):self.lock=threading.RLock();self.items={}
    def start(self,fn):
        with self.lock:
            if sum(t['state']=='running' for t in self.items.values())>=2:raise ValueError('Two read tasks are already running; wait or cancel one.')
            while len(self.items)>=4:
                old=next((k for k,v in self.items.items() if v['state']!='running'),None)
                if old is None:raise ValueError('Task limit reached.')
                del self.items[old]
            tid=secrets.token_hex(12);ev=threading.Event();item={'id':tid,'state':'running','current':0,'total':None,'message':'Starting…','cancel':ev,'result':None};self.items[tid]=item
        def progress(current,total,message):
            with self.lock:item.update(current=current,total=total,message=message)
        def work():
            try:
                result=fn(progress,ev.is_set)
                with self.lock:
                    if ev.is_set():item.update(state='canceled',message='Canceled; no catalog write.')
                    else:item.update(state='ready',result=result,message='Ready for review; no writes.')
            except InterruptedError:
                with self.lock:item.update(state='canceled',message='Canceled; no catalog write.')
            except Exception as exc:
                with self.lock:item.update(state='failed',message=str(exc))
        threading.Thread(target=work,daemon=True,name='WayriCAD-read-'+tid).start()
        return {'id':tid,'state':'running'}
    def get(self,tid,include_result=False):
        with self.lock:
            if tid not in self.items:raise ValueError('Task expired or belongs to another session.')
            item=self.items[tid];out={k:v for k,v in item.items() if k not in ('cancel','result')}
            if include_result:out['result']=item['result']
            if item['state']=='ready' and item['result'] is not None:
                r=item['result'];out['summary']={'parts':len(r.get('parts',[])),'projects':r.get('projects'),'failures':r.get('failures',[]),'fingerprint':r.get('fingerprint')}
                if r.get('schema')=='wayricad-harvest-1':
                    summaries=r.get('asset_summary',{})
                    out['summary']['captured_assets']={'parts_with_symbol':sum(bool(x['symbol']) for x in summaries.values()),'parts_with_footprint':sum(bool(x['footprint']) for x in summaries.values()),'parts_with_models':sum(bool(x['model']) for x in summaries.values()),'parts_with_incomplete_references':sum(not x['complete_references'] for x in summaries.values())}
                    out['summary']['asset_issues']=[{'internal_pn':p.get('internal_pn'),'reference':s.get('reference'),'issues':s.get('issues')} for p in r.get('parts',[]) for s in p.get('asset_sets',[]) if s.get('issues')][:80]
            return out
    def cancel(self,tid):
        with self.lock:
            if tid not in self.items:raise ValueError('Unknown task.')
            self.items[tid]['cancel'].set()
            if self.items[tid]['state']=='ready':self.items[tid].update(state='canceled',result=None,message='Result discarded; no writes.')
        return self.get(tid)
    def stop(self):
        with self.lock:
            for item in self.items.values():item['cancel'].set()


def library_path(ws=None,explicit='',app=None):
    path=explicit or (ws.state.get('engineering',{}).get('library','') if ws else '') or (getattr(app,'library_path','') if app else '') or default_library()
    if not path:raise ValueError('Create or attach a local parts library first.')
    return Path(text(str(path),'library path',4096)).expanduser().absolute()


def resolve_id(ws,variant,ref):
    rows=ws.rows(variant);found=[r for r in rows if r['id']==ref or r['ref']==ref]
    if len(found)!=1:raise ValueError('Select one unambiguous component reference/instance ID.')
    return found[0]['id']


def part_preview(lib,request):
    allowed={'id','expected_revision','new','fields','status','tags','internal_pn','reference_hint','land_pattern','notes','resolve_conflicts','alternates'}
    if not isinstance(request,dict) or set(request)-allowed:raise ValueError('Unknown catalog change keys.')
    if request.get('new'):
        fields=request.get('fields',{});pid=partsdb.record_identity(fields)
        if not pid.startswith('P-'):raise ValueError('Manual catalog creation requires Manufacturer and full MPN; harvest for unresolved generic records.')
        try:lib.get(pid)
        except ValueError:pass
        else:raise ValueError('Exact identity already exists; edit its revision instead.')
        old=None;p={'id':pid,'kind':'orderable','fields':{},'sources':[],'assets':[],'evidence':[],'conflicts':[],'status':'candidate','tags':[],
                    'internal_pn':'KW-'+pid[2:14].upper(),'reference_hint':request.get('reference_hint','')};rev=0
    else:
        old=lib.get(request['id']);p=deepcopy(old);rev=old['revision']
        if request.get('expected_revision')!=rev:raise ValueError('Stale catalog revision; reload before editing.')
    if 'fields' in request:p['fields'].update(request['fields'])
    for k in ('status','tags','internal_pn','reference_hint','land_pattern','notes','alternates'):
        if k in request:p[k]=deepcopy(request[k])
    for key in ('internal_pn','notes','reference_hint'):
        if key in p:text(p[key],key,4000)
    if not p.get('internal_pn','').strip():raise ValueError('Internal part number is required.')
    duplicate=lib.db.execute("SELECT id FROM parts WHERE json_extract(payload,'$.internal_pn')=? AND id<>?",(p['internal_pn'],p['id'])).fetchone()
    if duplicate:raise ValueError('Internal part number already belongs to another catalog identity.')
    if 'resolve_conflicts' in request:
        resolved=request['resolve_conflicts']
        if not isinstance(resolved,list) or any(type(i) is not int or not 0<=i<len(p['conflicts']) for i in resolved):raise ValueError('Conflict resolutions must identify current conflict indexes.')
        p.setdefault('resolved_conflicts',[]).extend(p['conflicts'][i] for i in sorted(set(resolved)))
        p['conflicts']=[x for i,x in enumerate(p['conflicts']) if i not in set(resolved)]
    alts=p.get('alternates',[])
    if not isinstance(alts,list) or len(alts)>100:raise ValueError('At most 100 candidate alternate links.')
    for alt in alts:
        if not isinstance(alt,dict) or set(alt)-{'part_id','revision','scope','evidence','reason'}:raise ValueError('Alternate link keys: part_id, revision, scope, evidence, reason. No editable approval flag.')
        target=lib.get(alt.get('part_id',''),alt.get('revision'))
        if target['id']==p['id']:raise ValueError('A part cannot be its own alternate.')
        if not alt.get('scope') or not alt.get('evidence') or not alt.get('reason'):raise ValueError('Candidate alternate requires explicit scope, evidence and reason.')
        alt['revision']=target['revision']
    partsdb._validate_part(p)
    return {'schema':'wayricad-part-plan-1','request':request,'part':p,'before':old,'expected_revision':rev,'fingerprint':digest([lib.meta('id'),lib.meta('epoch'),request,p]),
            'notice':'Catalog preferences/candidate links are not qualifications. Existing revisions are retained. Exact orderable identities cannot be renamed.'}


def part_apply(lib,plan,confirmation,actor,reason):
    if confirmation!='CATALOG':raise ValueError('Type CATALOG after reviewing the revision.')
    with lib.transaction():
        fresh=part_preview(lib,plan['request'])
        if fresh['fingerprint']!=plan.get('fingerprint'):raise ValueError('Catalog review changed; preview again.')
        result=lib.put(fresh['part'],actor,reason,fresh['expected_revision'])
    return {'part':result,'native_files_written':False}


def recommend_preview(lib,ws,variant,cid,pid,fields=None):
    report=partsdb.recommendations(lib,ws,variant,cid,100)
    candidate=next((p for p in report['items'] if p['part']['id']==pid),None)
    if not candidate:raise ValueError('Candidate no longer matches the value/footprint screen.')
    if candidate['state']=='blocked':raise ValueError('This candidate has conflicts, a blocked state or an at-risk lifecycle. Resolve the catalog assessment first.')
    part=candidate['part'];fields=fields or ['Manufacturer','MPN','Datasheet']
    if not isinstance(fields,list) or not fields or len(fields)>100 or any(k in partsdb.PROTECTED or k in ('CatalogID','CatalogRevision','InternalPN') for k in fields):raise ValueError('Choose ordinary source fields; protected identity/provenance columns are set separately.')
    changes={k:part['fields'][k] for k in fields if k in part['fields']}
    changes.update({'InternalPN':part['internal_pn'],'CatalogID':pid,'CatalogRevision':str(part['revision'])})
    entries=[{'ids':[cid],'changes':changes}];edit=bulkedit.preview(ws,variant,entries)
    return {'schema':'wayricad-recommendation-plan-1','component':cid,'part_id':pid,'fields':fields,'epoch':lib.meta('epoch'),'candidate':candidate,'entries':entries,'edit':edit,
            'notice':'This edits properties only, not library symbols, pins or pad geometry. Explicit engineering review is still required.'}


def recommend_apply(lib,ws,variant,plan,confirmation,acknowledge_loss=False,engineering_ack=False):
    if engineering_ack is not True:raise ValueError('Acknowledge that recommendation screening is not electrical qualification.')
    fresh=recommend_preview(lib,ws,variant,plan['component'],plan['part_id'],plan['fields'])
    if fresh['epoch']!=plan.get('epoch') or fresh['edit']['fingerprint']!=plan['edit']['fingerprint']:raise ValueError('Recommendation review is stale.')
    return bulkedit.apply(ws,variant,fresh['entries'],fresh['edit']['fingerprint'],confirmation,acknowledge_loss)


def evidence_preview(lib,pid,record):
    part=lib.get(pid);r=evidence.validate_record(record)
    if r['reviewed'] is not True:raise ValueError('Acknowledge reviewing the supplier/manufacturer observation.')
    if evidence.identity(r['manufacturer'],r['mpn'])!=evidence.identity(part['fields'].get('Manufacturer'),part['fields'].get('MPN')):raise ValueError('Observation exact identity differs from this catalog record.')
    return {'schema':'wayricad-catalog-evidence-plan-1','part_id':pid,'record':r,'revision':part['revision'],'fingerprint':digest([lib.meta('epoch'),pid,part['revision'],{k:v for k,v in r.items() if k!='imported_at'}]),'notice':'Historical evidence is retained; a newer observation is not an automatic lifecycle or purchasing approval.'}


def evidence_apply(lib,plan,confirmation,actor):
    if confirmation!='IMPORT':raise ValueError('Type IMPORT after reviewing the exact-part observation.')
    with lib.transaction():
        fresh=evidence_preview(lib,plan['part_id'],plan['record'])
        if fresh['fingerprint']!=plan.get('fingerprint'):raise ValueError('Catalog/evidence changed; review again.')
        part=lib.get(plan['part_id'])
        if any(e['id']==fresh['record']['id'] for e in part['evidence']):return {'duplicate':True}
        part['evidence'].append(fresh['record']);part=lib.put(part,actor,'Reviewed exact-part evidence',fresh['revision'])
    return {'part':part}


def health_report(lib,query='',market='IN',freshness_hours=24,offset=0,limit=100,low_stock_threshold=100,all_parts=False,progress=None,cancel=None):
    if not __import__('re').fullmatch(r'[A-Z]{2}',market):raise ValueError('Market must be two uppercase letters.')
    partsdb.number(freshness_hours,'freshness hours',1,8760)
    partsdb.number(low_stock_threshold,'low stock threshold',0,10**12)
    epoch=lib.meta('epoch');clock=datetime.now(timezone.utc);items=[];counts={};cursor=0 if all_parts else offset
    while True:
        if cancel and cancel():raise InterruptedError('Catalog health scan canceled; no writes.')
        page=lib.search(query,cursor,100 if all_parts else limit)
        for p in page['items']:
            if cancel and cancel():raise InterruptedError('Catalog health scan canceled; no writes.')
            h=partsdb.catalog_health(p,market,freshness_hours,clock,low_stock_threshold)
            counts[h['state']]=counts.get(h['state'],0)+1
            items.append({'id':p['id'],'internal_pn':p.get('internal_pn'),'manufacturer':p['fields'].get('Manufacturer'),'mpn':p['fields'].get('MPN'),'health':h})
        if progress:progress(len(items),page['total'],'Assessing dated catalog observations')
        if not all_parts or page['next_offset'] is None:break
        cursor=page['next_offset']
    if epoch!=lib.meta('epoch'):raise ValueError('Catalog changed while health was assessed; rerun.')
    return {'schema':'wayricad-catalog-health-1','total':page['total'],'assessed':len(items),'all_matches':all_parts,'counts':counts,'offset':0 if all_parts else offset,'next_offset':None if all_parts else page['next_offset'],
            'generated_at':clock.isoformat(),'market':market,'freshness_hours':freshness_hours,'low_stock_threshold':low_stock_threshold,'items':items,
            'notice':'Dated observation assessment. No live supplier/PCN monitoring or network requests. Unknown evidence is not healthy stock.'}


def dispatch(app,op,b):
    ws=app.workspace;variant=b.get('variant',BASE)
    if not hasattr(app,'engineering_tasks'):app.engineering_tasks=Tasks()
    if op=='task-status':return app.engineering_tasks.get(b['id'],b.get('include_result') is True)
    if op=='task-cancel':return app.engineering_tasks.cancel(b['id'])
    if op=='preview-capabilities':
        from .assetpreview import capabilities
        return capabilities()
    if op=='preview-start':
        from .assetpreview import preview
        path=library_path(ws,b.get('library',''),app)
        args={k:b[k] for k in ('revision','set_id','model_index','unit','style','layers','show_labels') if k in b}
        def make_preview(progress,cancel):
            progress(0,1,'Reading captured geometry…')
            with Library(path) as lib:result=preview(lib,b['id'],b['kind'],cancel=cancel,**args)
            progress(1,1,'Inspection ready; original files unchanged.')
            return result
        return app.engineering_tasks.start(make_preview)
    if op=='health-start':
        path=library_path(ws,b.get('library',''),app)
        options={k:b[k] for k in ('query','market','freshness_hours','low_stock_threshold') if k in b}
        def run_health(progress,cancel):
            with Library(path) as lib:return health_report(lib,all_parts=True,progress=progress,cancel=cancel,**options)
        return app.engineering_tasks.start(run_health)
    if op=='harvest-start':
        paths=deepcopy(b['paths']);recursive=b.get('recursive') is True;variants=b.get('include_variants',True) is True;assets=b.get('capture_assets',True) is True
        return app.engineering_tasks.start(lambda progress,cancel:partsdb.harvest(paths,recursive,variants,assets,progress,cancel,asset_options=b.get('asset_options')))
    if op in ('create','attach'):
        if op=='create' and b.get('confirmation')!='CREATE':raise ValueError('Type CREATE to create a new library directory.')
        path=Path(text(b.get('path',''),'path',4096)).expanduser().absolute()
        with Library(path,create=op=='create') as lib:info=lib.info()
        app.library_path=str(path)
        if ws:ws.commit('Attach engineering library',lambda:ws.state.setdefault('engineering',{}).update(library=str(path)))
        if b.get('remember') is True:remember_library(path)
        return info
    if op.startswith('variant-'):
        if not ws:raise ValueError('Open a project first.')
        return variantlab.preview(ws,b['request']) if op=='variant-preview' else variantlab.apply(ws,b['plan'],b.get('confirmation'))
    if op.startswith('mass-'):
        if not ws:raise ValueError('Open a project first.')
        try:path=library_path(ws,b.get('library',''),app)
        except ValueError:path=None
        def call(lib):
            if op=='mass-suggest':return masslib.suggest(ws,variant,lib,b.get('field'),b.get('default_unit'))
            if op=='mass-preview':return masslib.preview(ws,variant,b['choices'],lib,b.get('field'),b.get('default_unit'))
            if op=='mass-apply':return masslib.apply(ws,variant,b['plan'],b.get('confirmation'),b.get('acknowledge') is True,lib)
            raise ValueError('Unknown mass operation.')
        if path:
            with Library(path) as lib:return call(lib)
        return call(None)
    if op=='qualification':
        if not ws:raise ValueError('Open a project first.')
        return qualification.run(ws,variant,resolve_id(ws,variant,b['component']),b['spec'])
    if op=='info':
        try:path=library_path(ws,b.get('library',''),app)
        except ValueError:return {'attached':False,'default_library':default_library()}
    else:path=library_path(ws,b.get('library',''),app)
    with Library(path) as lib:
        if op=='info':return {'attached':True,**lib.info(),'reviewers':governance.reviewers(lib)}
        if op=='search':
            from .catalogbrowse import search
            return search(lib,**{k:b[k] for k in ('query','offset','limit','status','kind','footprint','filters','has_asset','category','manufacturer','lifecycle','sort','descending','summary') if k in b})
        if op=='assets':
            from .assetbundle import describe
            return describe(lib,b['id'],b.get('revision'),b.get('set_id'))
        if op=='asset-download':
            from .assetbundle import download_asset
            return download_asset(lib,b['id'],b['hash'],b.get('revision'))
        if op=='preview':
            from .assetpreview import preview
            return preview(lib,b['id'],b['kind'],**{k:b[k] for k in ('revision','set_id','model_index','unit','style','layers','show_labels') if k in b})
        if op=='classification':
            from .classification import classify
            return classify(lib.get(b['id']))
        if op=='get':return {'part':lib.get(b['id'],b.get('revision')),'history':lib.history(b['id'])}
        if op=='health':return health_report(lib,b.get('query',''),b.get('market','IN'),b.get('freshness_hours',24),b.get('offset',0),b.get('limit',100),b.get('low_stock_threshold',100),b.get('all_parts') is True)
        if op=='verify':return lib.verify()
        if op=='snapshot':return automation.json_bytes(lib.snapshot()),'WayriCAD_Catalog_Data.json','application/json'
        if op=='native-export':return partsdb.export_native_library(lib,b['ids'],b.get('choices'),b.get('require_complete',False),b.get('model_prefix','${KIPRJMOD}/WayriCAD.3dshapes'))
        if op=='harvest-import':
            plan=b.get('plan')
            if not plan:
                t=app.engineering_tasks.get(b['task_id'],True)
                if t['state']!='ready':raise ValueError('Harvest is not ready or was canceled.')
                plan=t['result']
            return partsdb.import_harvest(lib,plan,b.get('confirmation'),b.get('actor',''),b.get('allow_partial') is True)
        if op=='part-preview':return part_preview(lib,b['request'])
        if op=='part-apply':return part_apply(lib,b['plan'],b.get('confirmation'),b.get('actor',''),b.get('reason',''))
        if op=='evidence-preview':return evidence_preview(lib,b['part_id'],b['record'])
        if op=='evidence-apply':return evidence_apply(lib,b['plan'],b.get('confirmation'),b.get('actor',''))
        if op=='inventory-list':return {'lots':[json.loads(r[0]) for r in lib.db.execute('SELECT payload FROM inventory ORDER BY id')]}
        if op=='inventory-preview':return buildplan.inventory_preview(lib,b['records'])
        if op=='inventory-apply':return buildplan.inventory_apply(lib,b['plan'],b.get('confirmation'),b.get('actor',''))
        if op=='catalog-offers':return {'offers':buildplan.catalog_offers(lib,b.get('market','IN'))}
        if op=='reviewer-register':return governance.register(lib,b['name'],b['role'],b['password'],b.get('confirmation'),b.get('admin',''),b.get('admin_password',''))
        if op=='reviewer-deactivate':return governance.deactivate(lib,b['name'],b['admin'],b['password'],b.get('confirmation'))
        if op=='ledger':return {'decisions':governance.ledger(lib)}
        if not ws:raise ValueError('Open a project for this operation.')
        if op=='recommend':return partsdb.recommendations(lib,ws,variant,resolve_id(ws,variant,b['component']),b.get('limit',20))
        if op=='recommend-preview':return recommend_preview(lib,ws,variant,resolve_id(ws,variant,b['component']),b['part_id'],b.get('fields'))
        if op=='recommend-apply':return recommend_apply(lib,ws,variant,b['plan'],b.get('confirmation'),b.get('acknowledge_loss') is True,b.get('engineering_ack') is True)
        if op=='review-context':return governance.assess(lib,governance.context(lib,ws,variant,b.get('policy')))
        if op=='review-decision':return governance.decide(lib,ws,variant,b['decision'],b.get('policy'))
        if op=='buildplan':return buildplan.run(ws,lib,b['config'])
    raise ValueError('Unknown engineering operation: '+op)
