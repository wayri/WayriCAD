"""Immutable local/shared catalog, explicit synchronization and signed reviews.

Catalog payloads are JSON data, never scripts. A shared directory may be hosted
on a user-managed file server; HTTPS catalogs are read-only mirrors. A trusted
key proves control of that key, not a person's legal identity or fab approval.
"""
import base64
import contextlib
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from .engineering import validate_profile, fingerprint
from .workspace import atomic_write

SCHEMA=1
MAX_DOCUMENT_BYTES=4*1024*1024


def canonical(data):
    return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def sha(data):return hashlib.sha256(data).hexdigest()


def _read(path):
    if path.is_symlink(): raise ValueError('Catalog symlinks are not accepted')
    if path.stat().st_size>MAX_DOCUMENT_BYTES: raise ValueError('Catalog document too large')
    return path.read_bytes()


@contextlib.contextmanager
def catalog_lock(root):
    path=root/'.constraint-studio-catalog.lock'
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as e:
        raise RuntimeError('Catalog is locked by another writer. Stale locks require administrator review.') from e
    try:
        os.write(fd,canonical({'pid':os.getpid(),'time':time.time()}));os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


class SharedCatalog:
    def __init__(self,location):
        self.root=Path(location).expanduser().resolve()

    def index(self):
        p=self.root/'index.json'
        if not p.exists():return {'schema':SCHEMA,'entries':{}}
        value=json.loads(_read(p))
        if value.get('schema')!=SCHEMA or not isinstance(value.get('entries'),dict):
            raise ValueError('Unsupported catalog index')
        for key,e in value['entries'].items():
            if not isinstance(e,dict) or not re.fullmatch('[a-f0-9]{64}',e.get('sha256','')):
                raise ValueError('Invalid catalog object digest')
            if key!=e.get('id','')+'@'+e.get('version',''):raise ValueError('Invalid catalog identity')
        return value

    def publish(self,profile):
        profile=copy.deepcopy(validate_profile(profile));data=canonical(profile);digest=sha(data)
        if len(data)>MAX_DOCUMENT_BYTES:raise ValueError('Profile too large')
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'objects').mkdir(exist_ok=True)
        if (self.root/'objects').is_symlink():raise ValueError('Catalog objects directory cannot be a symlink')
        key=profile['id']+'@'+profile['version']
        with catalog_lock(self.root):
            index=self.index();existing=index['entries'].get(key)
            if existing and existing['sha256']!=digest:
                raise ValueError('Published versions are immutable. Increment the profile version.')
            object_path=self.root/'objects'/(digest+'.json')
            if object_path.exists():
                if _read(object_path)!=data:raise ValueError('Catalog object digest collision/corruption')
            else:atomic_write(object_path,data)
            index['entries'][key]={'id':profile['id'],'version':profile['version'],'name':profile.get('name',profile['id']), 'sha256':digest}
            atomic_write(self.root/'index.json',canonical(index))
        return key,digest

    def get(self,key,expected_digest=None):
        entry=self.index()['entries'].get(key)
        if not entry:raise KeyError(key)
        if expected_digest and expected_digest!=entry['sha256']:raise ValueError('Pinned profile digest changed')
        data=_read(self.root/'objects'/(entry['sha256']+'.json'))
        if sha(data)!=entry['sha256']:raise ValueError('Catalog payload checksum mismatch')
        profile=validate_profile(json.loads(data))
        if profile['id']+'@'+profile['version']!=key:raise ValueError('Catalog payload identity mismatch')
        return profile


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Catalog redirects are refused; use the final HTTPS origin')


class HTTPSCatalog:
    """Read-only static catalog. No cookies, credentials, downloads of code or telemetry."""
    def __init__(self,base_url):
        p=urllib.parse.urlsplit(base_url)
        if p.scheme!='https' or not p.netloc or p.username or p.password or p.query or p.fragment:
            raise ValueError('Use an HTTPS catalog root without credentials, query or fragment')
        self.base=base_url.rstrip('/')+'/'
        self.opener=urllib.request.build_opener(_NoRedirect())

    def _get(self,path):
        if path!='index.json' and not re.fullmatch(r'objects/[a-f0-9]{64}\.json',path):raise ValueError('Invalid catalog resource')
        with self.opener.open(self.base+path,timeout=20) as r:
            b=r.read(MAX_DOCUMENT_BYTES+1)
        if len(b)>MAX_DOCUMENT_BYTES:raise ValueError('Remote catalog document too large')
        return b

    def index(self):
        data=json.loads(self._get('index.json'))
        if data.get('schema')!=SCHEMA or not isinstance(data.get('entries'),dict):raise ValueError('Unsupported remote catalog')
        for key,e in data['entries'].items():
            if not isinstance(e,dict) or not re.fullmatch('[a-f0-9]{64}',e.get('sha256','')):raise ValueError('Invalid remote object digest')
            if key!=e.get('id','')+'@'+e.get('version',''):raise ValueError('Remote identity mismatch')
        return data

    def get(self,key,expected_digest=None):
        e=self.index()['entries'][key]
        if expected_digest and expected_digest!=e['sha256']:raise ValueError('Pinned remote profile digest changed')
        data=self._get('objects/'+e['sha256']+'.json')
        if sha(data)!=e['sha256']:raise ValueError('Remote object digest mismatch')
        p=validate_profile(json.loads(data))
        if p['id']+'@'+p['version']!=key:raise ValueError('Remote object identity mismatch')
        return p


def synchronization_plan(workspace,catalog):
    known=workspace.metadata.get('catalog_pins',{})
    rows=[]
    for key,entry in sorted(catalog.index()['entries'].items()):
        old=known.get(key)
        status='new' if not old else 'current' if old['sha256']==entry['sha256'] else 'CHANGED IMMUTABLE VERSION'
        rows.append(dict(entry,key=key,status=status))
    return rows


def pin_profile(workspace,catalog,key,digest):
    # Fetch and validate before changing any staged metadata.
    p=catalog.get(key,expected_digest=digest)
    old=workspace.metadata.get('catalog_pins',{}).get(key)
    if old and old['sha256']!=digest:raise ValueError('Existing pin differs. Publish a new version; no forced replacement.')
    profiles=workspace.metadata.setdefault('profiles',{})
    if key in profiles and canonical(profiles[key])!=canonical(p):raise ValueError('Local profile with this identity differs; preserve it under a new version first')
    profiles[key]=copy.deepcopy(p)
    workspace.metadata.setdefault('catalog_pins',{})[key]={'sha256':digest,'source':str(getattr(catalog,'root',getattr(catalog,'base','')))}
    return p


def review_payload(workspace):
    """Content, including tool bindings, but excluding signatures about that content."""
    metadata={k:v for k,v in workspace.metadata.items() if k not in ('signed_reviews','reviews')}
    return {'rules_sha256':sha(workspace.document.emit().encode()),'board_sha256':sha(workspace.board_text.encode()),
            'project_sha256':sha(canonical(workspace.project)),'bindings_sha256':sha(canonical({'guards':workspace.guards,'metadata':metadata}))}


def crypto_available():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return True
    except ImportError:return False


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as e:raise RuntimeError('Signed reviews require the optional cryptography package in the KiCad Python environment. Unsigned editing does not.') from e
    return serialization,Ed25519PrivateKey,Ed25519PublicKey


def generate_identity(passphrase):
    """Return encrypted private PEM and public PEM. Caller chooses secure locations."""
    if not isinstance(passphrase,str) or len(passphrase)<12:raise ValueError('Use a passphrase of at least 12 characters')
    s,Private,_=_crypto();key=Private.generate()
    private=key.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.BestAvailableEncryption(passphrase.encode()))
    public=key.public_key().public_bytes(s.Encoding.PEM,s.PublicFormat.SubjectPublicKeyInfo)
    return private,public


def key_id(public_pem):
    s,_,Public=_crypto();key=s.load_pem_public_key(public_pem)
    if not isinstance(key,Public):raise ValueError('Only Ed25519 review keys are accepted')
    return sha(key.public_bytes(s.Encoding.Raw,s.PublicFormat.Raw))


def sign_review(workspace,private_pem,passphrase,principal,rationale,status='approved'):
    if not principal.strip() or not rationale.strip():raise ValueError('Signer and rationale are required')
    if status not in ('reviewed','approved','rejected'):raise ValueError('Invalid signed review status')
    if status=='approved' and any(i.severity=='error' for i in workspace.issues()):raise ValueError('Cannot approve local validation errors')
    s,Private,_=_crypto();key=s.load_pem_private_key(private_pem,password=passphrase.encode())
    if not isinstance(key,Private):raise ValueError('Only Ed25519 review keys are accepted')
    public=key.public_key().public_bytes(s.Encoding.PEM,s.PublicFormat.SubjectPublicKeyInfo)
    reviews=workspace.metadata.get('signed_reviews',[])
    body={'schema':1,'principal':principal.strip(),'rationale':rationale.strip(),'status':status,'key_id':key_id(public),
          'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'payload':review_payload(workspace),
          'previous':sha(canonical(reviews[-1])) if reviews else None}
    record={'body':body,'signature':base64.b64encode(key.sign(canonical(body))).decode(),'public_key':public.decode()}
    workspace.metadata.setdefault('signed_reviews',[]).append(record)
    return record


def verify_reviews(workspace,trusted_keys,required_approvals=1,expected_head=None):
    """Trust is external to the project. Never trust a key merely embedded in a record.
    trusted_keys maps key fingerprints to {public_key, principal, roles:[...]}."""
    if isinstance(required_approvals,bool) or not isinstance(required_approvals,int) or required_approvals<1:raise ValueError('At least one independent approval is required')
    s,_,Public=_crypto();current=review_payload(workspace);results=[];previous=None;latest={};chain_ok=True
    for record in workspace.metadata.get('signed_reviews',[]):
        state='invalid';b=record.get('body',{})
        try:
            if b.get('previous')!=previous:chain_ok=False;raise ValueError('Review chain altered')
            trust=trusted_keys.get(b.get('key_id'))
            if not trust:raise ValueError('Untrusted signing key')
            if trust.get('principal')!=b.get('principal'):raise ValueError('Key principal mismatch')
            public=trust['public_key'].encode() if isinstance(trust['public_key'],str) else trust['public_key']
            if key_id(public)!=b.get('key_id'):raise ValueError('Trusted key fingerprint mismatch')
            key=s.load_pem_public_key(public)
            key.verify(base64.b64decode(record['signature'],validate=True),canonical(b))
            if b.get('payload')!=current:state='stale'
            else:
                state=b.get('status','invalid')
                if state=='approved' and 'approver' not in trust.get('roles',[]):state='reviewer-not-approver'
                # Each principal counts at most once; the latest current decision wins.
                latest[b['principal']]=state
            reason='Verified trusted key signature; identity depends on your trust registry'
        except Exception as e:
            reason=str(e) or type(e).__name__
            chain_ok=False
        results.append({'principal':b.get('principal',''),'status':state,'reason':reason})
        previous=sha(canonical(record))
    if expected_head is not None and previous!=expected_head:chain_ok=False
    approvers=[p for p,state in latest.items() if state=='approved']
    rejection=any(v=='rejected' for v in latest.values())
    return {'approved':chain_ok and not rejection and len(approvers)>=required_approvals,
            'required':required_approvals,'approvers':approvers,'chain_valid':chain_ok,'records':results,
            'head':previous,'anti_rollback_anchor_checked':expected_head is not None,
            'warning':'Signature approval is not native DRC, fabrication accreditation or authenticated employment identity. A separately protected expected-head anchor is needed to detect review-history truncation.'}


def apply_with_policy(directory,policy_path,project_closed=False):
    """Offline apply gated by an EXTERNAL administrator-managed policy file.
    Policy must not come from the untrusted review bundle. Existing source/export
    hash, lint, lock and backup guards are still enforced by apply_bundle().
    """
    from .workspace import Workspace,apply_bundle
    directory=Path(directory).resolve();policy_path=Path(policy_path).expanduser().resolve()
    if directory==policy_path.parent or directory in policy_path.parents:
        raise ValueError('Trust policy must be stored outside the review bundle')
    policy=json.loads(_read(policy_path))
    if policy.get('schema')!=1 or not isinstance(policy.get('trusted_keys'),dict):raise ValueError('Unsupported external review policy')
    manifest=json.loads(_read(directory/'constraint-studio-manifest.json'))
    boards=[n for n in manifest['files'] if Path(n).suffix=='.kicad_pcb' and Path(n).name==n]
    if len(boards)!=1:raise ValueError('Expected exactly one review board')
    w=Workspace.load(directory/boards[0])
    report=verify_reviews(w,policy['trusted_keys'],policy.get('required_approvals',1),policy.get('expected_review_head'))
    if not report['approved']:raise ValueError('External approval policy did not pass: '+json.dumps(report))
    if policy.get('require_anti_rollback_anchor',False) and not report['anti_rollback_anchor_checked']:
        raise ValueError('External policy requires an expected review-head anchor')
    backup=apply_bundle(directory,project_closed=project_closed)
    return backup,report
