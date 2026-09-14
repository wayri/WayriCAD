"""Password-authenticated LOCAL review ledger; not enterprise identity or PKI.

HMACs detect accidental/off-path edits under one OS user's trust boundary. An
administrator controlling the database/key can rewrite it. No nonrepudiation,
manufacturer certification or regulated e-signature compliance is claimed.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import re
import secrets
from .partsdb import digest, encoded, text, catalog_health, record_identity, CRITICAL, normalized
from .engine import now
from .native import BASE
from .footprints import Inspector

ROLES=('admin','engineering','supply')
ITERATIONS=310000


def _password(password,salt):
    if not isinstance(password,str) or not 12<=len(password)<=1024:
        raise ValueError('Reviewer passphrase must contain 12–1024 characters.')
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex()


def authenticate(lib,name,password,roles=None):
    row=lib.db.execute('SELECT * FROM reviewers WHERE name=?',(name,)).fetchone()
    # Equal KDF work for unknown names; passwords are never logged or stored in plans.
    salt=row['salt'] if row else '00'*16
    result=_password(password,salt)
    if not row or not row['active'] or not hmac.compare_digest(result,row['password_hash']):
        raise ValueError('Reviewer authentication failed.')
    if roles and row['role'] not in roles:raise ValueError('Reviewer role does not authorize this decision.')
    return dict(row)


def reviewers(lib):
    return [dict(r) for r in lib.db.execute('SELECT name,role,active FROM reviewers ORDER BY name')]


def register(lib,name,role,password,confirmation,admin='',admin_password=''):
    text(name,'reviewer',128)
    if not name.strip() or role not in ROLES:raise ValueError('Choose a reviewer name and admin, engineering or supply role.')
    if confirmation!='REGISTER':raise ValueError('Type REGISTER to create a local reviewer.')
    with lib.transaction():
        count=lib.db.execute('SELECT count(*) FROM reviewers').fetchone()[0]
        if count:authenticate(lib,admin,admin_password,('admin',))
        elif role!='admin':raise ValueError('The first local reviewer must be an administrator.')
        salt=secrets.token_hex(16);hashed=_password(password,salt)
        if lib.db.execute('SELECT 1 FROM reviewers WHERE name=?',(name,)).fetchone():raise ValueError('Reviewer already exists; names cannot be reassigned.')
        lib.db.execute('INSERT INTO reviewers VALUES (?,?,?,?,1)',(name,role,salt,hashed))
        lib.audit('reviewer-created',{'name':name,'role':role,'admin':admin or 'local-bootstrap'})
    return {'reviewer':name,'role':role,'trust':'Local account, not independently verified identity.'}


def deactivate(lib,name,admin,password,confirmation):
    if confirmation!='DEACTIVATE':raise ValueError('Type DEACTIVATE.')
    with lib.transaction():
        authenticate(lib,admin,password,('admin',))
        row=lib.db.execute('SELECT * FROM reviewers WHERE name=?',(name,)).fetchone()
        if not row:raise ValueError('Unknown reviewer.')
        if row['active'] and row['role']=='admin' and lib.db.execute("SELECT count(*) FROM reviewers WHERE active=1 AND role='admin'").fetchone()[0]<=1:raise ValueError('Cannot deactivate the final administrator.')
        lib.db.execute('UPDATE reviewers SET active=0 WHERE name=?',(name,));lib.audit('reviewer-deactivated',{'name':name,'admin':admin})
    return {'deactivated':name}


def validate_policy(policy=None):
    p={'roles':['engineering'],'check_level':'error','catalog_required':False,'stock_required':False,'qualification_required':False,'market':'IN','freshness_hours':24}
    if policy is not None:
        if not isinstance(policy,dict) or set(policy)-set(p):raise ValueError('Unknown review policy key.')
        p.update(deepcopy(policy))
    if not isinstance(p['roles'],list) or not p['roles'] or len(set(p['roles']))!=len(p['roles']) or any(r not in ('engineering','supply') for r in p['roles']):raise ValueError('Approval roles: unique engineering and/or supply.')
    if p['check_level'] not in ('error','warning'):raise ValueError('Review check_level: error or warning.')
    for k in ('catalog_required','stock_required','qualification_required'):
        if type(p[k]) is not bool:raise ValueError(k+' must be boolean.')
    if not re.fullmatch(r'[A-Z]{2}',p['market']):raise ValueError('Market needs a two-letter uppercase code.')
    if type(p['freshness_hours']) not in (int,float) or not 0<p['freshness_hours']<=8760:raise ValueError('Freshness: >0..8760 hours.')
    return p


def _bound_state(ws):
    # View rearrangements and append-only UI history do not alter engineering approval.
    ignored={'history','view','view_presets','grouping','search_filters','saved_filters','baseline','source_hashes','app_version'}
    return {k:v for k,v in ws.state.items() if k not in ignored}


def context(lib,ws,variant=BASE,policy=None):
    ws.project.check_unchanged();p=validate_policy(policy);rows=ws.rows(variant);inspector=Inspector(ws);geometry={};issues=[];qualification_targets=[];alternate_targets=[];alternate_seen=set()
    def issue(code,severity,message,reference='',detail=None):
        item={'code':code,'severity':severity,'message':message,'reference':reference,'detail':detail}
        item['id']=digest(item);issues.append(item)
    for c in ws.checks(variant):
        if c.get('severity')=='error' or p['check_level']=='warning' and c.get('severity')=='warning':
            issue('BOM_'+str(c.get('code','CHECK')),c.get('severity','error'),str(c.get('message','BOM check')),str(c.get('reference',c.get('ref',''))),c)
    catalog_by_id={}
    for row in rows:
        fp=row['fields'].get('Footprint','')
        if fp and fp not in geometry:
            g=inspector.library(fp);geometry[fp]={'hash':g.get('hash'),'source':g.get('source'),'status':g.get('status')}
        if row['flags'].get('dnp') or not row['flags'].get('in_bom',True):continue
        pid=record_identity(row['fields'])
        if pid not in catalog_by_id:
            try:catalog_by_id[pid]=lib.get(pid)
            except ValueError:catalog_by_id[pid]=None
        part=catalog_by_id[pid]
        if not part:
            if p['catalog_required'] or p['qualification_required']:issue('NO_CATALOG','unknown','No exact catalog identity.',row['ref'])
            if p['stock_required']:issue('NO_STOCK','unknown','No eligible catalog stock evidence.',row['ref'])
            continue
        health=catalog_health(part,p['market'],p['freshness_hours'])
        if part.get('status')=='blocked' or health['metadata_conflicts']:issue('CATALOG_BLOCKED','error','Catalog identity is blocked or has critical conflicts.',row['ref'],part['id'])
        if health['lifecycle']=='AT RISK':issue('LIFECYCLE_RISK','warning','Recorded NRND/EOL/obsolete lifecycle observation.',row['ref'],health['lifecycle_labels'])
        if p['stock_required'] and health['stock']['status']!='observed_covered':issue('STOCK_NOT_OBSERVED','unknown','No eligible numeric stock observation covering one part; use build planning for quantity coverage.',row['ref'])
        for link in part.get('alternates',[]):
            key=(part['id'],link['part_id'],str(link['scope']))
            if key in alternate_seen:continue
            alternate_seen.add(key);conflicts=[]
            candidate=lib.get(link['part_id'])
            if candidate['revision']!=link['revision']:conflicts.append('Linked alternate revision changed; revise the candidate link before review.')
            candidate_health=catalog_health(candidate,p['market'],p['freshness_hours'])
            if candidate_health['state']=='blocked' or candidate_health['lifecycle']=='AT RISK':conflicts.append('Alternate has critical catalog/lifecycle risks.')
            for key in CRITICAL:
                left=part['fields'].get(key,'');right=candidate['fields'].get(key,'')
                if key=='Value':
                    if normalized(part['fields'],row['ref'])!=normalized(candidate['fields'],row['ref']):conflicts.append('Nominal value conflict.')
                elif left and right and left!=right:conflicts.append('Conflicting recorded '+key+'.')
            if not part['fields'].get('Footprint') or part['fields'].get('Footprint')!=candidate['fields'].get('Footprint'):conflicts.append('No exact matching selected footprint.')
            target={'primary_id':part['id'],'primary_revision':part['revision'],'alternate_id':candidate['id'],'alternate_revision':candidate['revision'],'scope':link['scope'],'evidence':link['evidence'],'reason':link['reason'],'conflicts':conflicts,
                    'notice':'Human scoped engineering decision; does not prove electrical interchangeability or authorize automatic substitution.'}
            target['target_hash']=digest(target);alternate_targets.append(target)
        if p['qualification_required']:
            spec=part.get('land_pattern')
            if not spec:issue('NO_QUALIFICATION','unknown','No declared manufacturer land-pattern specification.',row['ref']);continue
            from .qualification import run
            try:report=run(ws,variant,row['id'],spec)
            except (ValueError,OSError) as exc:
                issue('QUALIFICATION_UNAVAILABLE','unknown','Cannot complete declared qualification: '+str(exc),row['ref']);continue
            if report['status']!='MATCHED_DECLARED_CHECKS':issue('QUALIFICATION_INCOMPLETE','error' if report['status']=='MISMATCH' else 'unknown','Declared package/pin checks did not all match.',row['ref'],report['fingerprint'])
            else:qualification_targets.append({'part_id':pid,'revision':part['revision'],'report_hash':report['fingerprint'],'reference':row['ref']})
    bound={'library_id':lib.meta('id'),'catalog_epoch':int(lib.meta('epoch')),'source_hashes':ws.project.hashes,'workspace':_bound_state(ws),'variant':variant,'geometry':geometry,'policy':p,'qualification_targets':qualification_targets,'alternate_targets':alternate_targets,'findings':issues}
    return {'schema':'wayricad-review-context-1','input_hash':digest(bound),'variant':variant,'policy':p,'issues':issues,'qualification_targets':qualification_targets,'alternate_targets':alternate_targets,
            'catalog_epoch':bound['catalog_epoch'],'source_hashes':ws.project.hashes,'geometry':geometry,
            'trust':'Local authenticated review, not PKI, regulated e-signature compliance or manufacturer certification.'}


def _sign(lib,payload):return hmac.new(bytes.fromhex(lib.meta('review_key')),encoded(payload).encode(),hashlib.sha256).hexdigest()


def ledger(lib,clock=None):
    clock=clock or datetime.now(timezone.utc);out=[]
    for row in lib.db.execute('SELECT * FROM decisions ORDER BY rowid'):
        d=json.loads(row['payload']);valid=hmac.compare_digest(_sign(lib,d),row['signature'])
        account=lib.db.execute('SELECT role,active FROM reviewers WHERE name=?',(d.get('reviewer'),)).fetchone()
        expiry=datetime.fromisoformat(d['expires_at'])
        out.append({**d,'signature_valid':valid,'reviewer_active':bool(account and account['active']),
                    'status':'INVALID' if not valid else 'INACTIVE_REVIEWER' if not account or not account['active'] else 'EXPIRED' if expiry<=clock else 'CURRENT'})
    revoked={d['target'] for d in out if d['kind']=='revoke' and d['signature_valid']}
    for d in out:
        if d['id'] in revoked:d['status']='REVOKED'
    return out


def assess(lib,ctx):
    records=ledger(lib);current=[]
    for d in records:
        if d['input_hash']!=ctx['input_hash'] and d['kind']!='revoke':d['status']='STALE' if d['status']=='CURRENT' else d['status']
        if d['status']=='CURRENT' and d['input_hash']==ctx['input_hash']:current.append(d)
    waivers={d['target'] for d in current if d['kind']=='waiver'}
    remaining=[i for i in ctx['issues'] if i['severity']=='error' or i['id'] not in waivers]
    approved={d['role'] for d in current if d['kind']=='release'}
    missing=[r for r in ctx['policy']['roles'] if r not in approved]
    # Qualification approvals bind a computed exact report, not a user-authored status flag.
    unqualified=[q for q in ctx['qualification_targets'] if not any(d['kind']=='qualification' and d['target']==q['report_hash'] for d in current)]
    return {**ctx,'decisions':records,'unwaived_issues':remaining,'missing_roles':missing,'unapproved_qualifications':unqualified,'alternate_assessments':[{**a,'status':'BLOCKED' if a['conflicts'] else 'APPROVED_LOCAL_SCOPE' if any(d['kind']=='alternate' and d['target']==a['target_hash'] for d in current) else 'REQUIRES_ENGINEERING_REVIEW'} for a in ctx.get('alternate_targets',[])],
            'status':'APPROVED_LOCAL' if not remaining and not missing and not unqualified else 'NOT_APPROVED'}


def decide(lib,ws,variant,payload,policy=None):
    if not isinstance(payload,dict):raise ValueError('Decision payload must be an object.')
    if payload.get('confirmation')!='REVIEW':raise ValueError('Type REVIEW after inspecting the current context.')
    reason=text(payload.get('reason',''),'decision reason',4000)
    if len(reason.strip())<10:raise ValueError('A meaningful decision reason (10+ characters) is required.')
    kind=payload.get('kind');role='supply' if kind=='waiver' and payload.get('role')=='supply' else 'engineering'
    if kind=='release':role=payload.get('role','engineering')
    if kind not in ('release','waiver','qualification','alternate','revoke'):raise ValueError('Decision kind: release, waiver, qualification, alternate or revoke.')
    with lib.transaction():
        user=authenticate(lib,payload.get('reviewer',''),payload.get('password',''),('admin',) if kind=='revoke' else (role,))
        ctx=context(lib,ws,variant,policy)
        if payload.get('input_hash')!=ctx['input_hash']:raise ValueError('Review inputs changed. Generate and inspect a new review context.')
        target=text(payload.get('target',''),'target',128)
        source=text(payload.get('evidence',''),'review evidence reference',4000)
        if kind=='waiver':
            finding=next((i for i in ctx['issues'] if i['id']==target),None)
            if not finding:raise ValueError('Waiver must target one exact current finding.')
            if finding['severity']=='error':raise ValueError('Error findings cannot be waived.')
            expected='supply' if finding['code'] in ('LIFECYCLE_RISK','STOCK_NOT_OBSERVED','NO_STOCK') else 'engineering'
            if user['role']!=expected:raise ValueError('This finding requires the '+expected+' role.')
            if not source.strip():raise ValueError('A waiver requires an evidence or change-control reference.')
        if kind=='qualification':
            if not any(q['report_hash']==target for q in ctx['qualification_targets']):raise ValueError('Only a currently computed matched qualification report can be approved.')
            if not source.strip():raise ValueError('Record the manufacturer evidence/document revision.')
        if kind=='alternate':
            target_record=next((a for a in ctx.get('alternate_targets',[]) if a['target_hash']==target),None)
            if not target_record or target_record['conflicts']:raise ValueError('Alternate approval must target a current unblocked, revision-pinned candidate link.')
            if not source.strip():raise ValueError('Record explicit engineering qualification evidence and scope.')
        if kind=='release':
            status=assess(lib,ctx)
            if status['unwaived_issues'] or status['unapproved_qualifications']:raise ValueError('Resolve or validly waive findings and approve declared qualifications before release approval.')
        if kind=='revoke' and not lib.db.execute('SELECT 1 FROM decisions WHERE id=?',(target,)).fetchone():raise ValueError('Unknown decision to revoke.')
        try:expiry=datetime.fromisoformat(payload['expires_at'].replace('Z','+00:00'))
        except (KeyError,TypeError,ValueError) as exc:raise ValueError('Expiry needs a timezone-aware ISO timestamp.') from exc
        clock=datetime.now(timezone.utc)
        if expiry.tzinfo is None or not clock<expiry<=clock+timedelta(days=366):raise ValueError('Expiry must be in the future, at most 366 days.')
        d={'schema':'wayricad-decision-1','id':secrets.token_hex(16),'kind':kind,'role':user['role'],'reviewer':user['name'],'input_hash':ctx['input_hash'],
           'variant':variant,'target':target,'reason':reason,'evidence':source,'created_at':now(),'expires_at':expiry.isoformat()}
        lib.db.execute('INSERT INTO decisions VALUES (?,?,?)',(d['id'],encoded(d),_sign(lib,d)));lib.audit('review-decision',d)
    return d
