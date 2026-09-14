"""Headless engineering-library workflows. Secrets are prompted or read from env, never flags."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import getpass
import os
import sys
from . import engineering as eng, partsdb, governance, buildplan, variantlab, masslib, qualification, automation
from .native import Project,BASE
from .engine import Workspace

COMMANDS=('catalog','recommend','qualify','review','inventory','buildplan','bomvariant','mass','hosttest','benchmark')

def register(subs):
    def out(p):p.add_argument('--output',help='NEW JSON report or plan path. stdout otherwise; never overwrites.')
    def lib(p,required=True):p.add_argument('--library',required=required,help='Local parts-library DIRECTORY, not a .kicad_sym file.')
    def project(p):p.add_argument('project');p.add_argument('--variant',default=BASE)
    def input_(p,label='payload'):p.add_argument('--'+label,required=True,help='JSON file or - for stdin.')
    def apply_(p,token):input_(p,'plan');p.add_argument('--confirm',required=True,help=token);p.add_argument('--actor',default='');p.add_argument('--reason',default='Reviewed command-line change');p.add_argument('--acknowledge-loss',action='store_true')
    p=subs.add_parser('catalog',help='Versioned local parts, local project harvesting, health and native library export.')
    sub=p.add_subparsers(dest='operation',required=True)
    for op in ('create','info','search','health','get','verify','harvest','import','edit-preview','edit-apply','evidence-preview','evidence-apply','export','native-export','assets','preview','asset-export'):
        q=sub.add_parser(op);out(q)
        if op!='harvest':lib(q)
        if op=='create':q.add_argument('--confirm',required=True,help='CREATE')
        if op in ('search','health'):q.add_argument('--query',default='');q.add_argument('--offset',type=int,default=0);q.add_argument('--limit',type=int,default=100)
        if op=='health':q.add_argument('--market',default='IN');q.add_argument('--freshness-hours',type=int,default=24);q.add_argument('--low-stock',type=int,default=100);q.add_argument('--all',action='store_true',help='Assess all matching identities, not just a page.')
        if op in ('get','assets','preview','asset-export'):q.add_argument('--id',required=True);q.add_argument('--revision',type=int)
        if op in ('assets','preview'):q.add_argument('--set-id')
        if op=='preview':
            q.add_argument('--kind',choices=['symbol','footprint','model'],required=True);q.add_argument('--model-index',type=int,default=0);q.add_argument('--unit',type=int,default=1);q.add_argument('--style',type=int,choices=[1,2],default=1);q.add_argument('--format',choices=['json','svg'],default='json')
        if op=='asset-export':q.add_argument('--hash',required=True)
        if op=='search':q.add_argument('--filters',help='JSON array of AND field rules.');q.add_argument('--has-asset',choices=['symbol','footprint','model','all3','incomplete'],default='');q.add_argument('--status',default='');q.add_argument('--kind',default='');q.add_argument('--footprint',default='');q.add_argument('--category',default='');q.add_argument('--manufacturer',default='');q.add_argument('--lifecycle',choices=['RISK','RECORDED','UNKNOWN'],default='');q.add_argument('--sort',choices=['mpn','manufacturer','value','footprint','category','internal_pn','revision'],default='mpn');q.add_argument('--descending',action='store_true');q.add_argument('--summary',action='store_true')
        if op=='harvest':q.add_argument('paths',nargs='+');q.add_argument('--recursive',action='store_true');q.add_argument('--source-only',action='store_true');q.add_argument('--metadata-only',action='store_true');q.add_argument('--asset-config',help='JSON local library/model roots, path variables and source precedence.')
        if op=='import':apply_(q,'IMPORT');q.add_argument('--allow-partial',action='store_true')
        if op=='edit-preview':input_(q,'request')
        if op=='edit-apply':apply_(q,'CATALOG')
        if op=='evidence-preview':q.add_argument('--id',required=True);input_(q,'record')
        if op=='evidence-apply':apply_(q,'IMPORT')
        if op=='native-export':q.add_argument('--ids',nargs='+',required=True);q.add_argument('--choices',help='JSON mapping part IDs to observed asset-set IDs.');q.add_argument('--require-complete',action='store_true');q.add_argument('--model-prefix',default='${KIPRJMOD}/WayriCAD.3dshapes')
    for command in ('recommend','bomvariant','mass','inventory'):
        p=subs.add_parser(command,help={'recommend':'Explain/review exact-footprint and normalized-value catalog candidates.','bomvariant':'Independent BOM-only variants: derived/pinned copies, metadata, locks and inheritance.','mass':'Source-linked mass suggestions; estimates require explicit acceptance.','inventory':'Reviewed stock-lot observations; simulation never reserves inventory.'}[command]);sub=p.add_subparsers(dest='operation',required=True)
        ops={'recommend':('list','preview','apply'),'bomvariant':('list','preview','apply'),'mass':('suggest','preview','apply'),'inventory':('list','preview','apply')}[command]
        for op in ops:
            q=sub.add_parser(op);out(q)
            if command!='inventory':project(q)
            if command!='bomvariant':lib(q,command in ('recommend','inventory'))
            if command=='recommend' and op!='apply':q.add_argument('--component',required=True)
            if command=='recommend' and op=='preview':q.add_argument('--part-id',required=True);q.add_argument('--fields',nargs='+')
            if command=='mass' and op!='apply':q.add_argument('--field');q.add_argument('--unit')
            if op=='preview' and command!='recommend':input_(q,'request' if command=='bomvariant' else 'choices' if command=='mass' else 'records')
            if op=='apply':apply_(q,'VARIANT' if command=='bomvariant' else 'INVENTORY' if command=='inventory' else 'EDIT')
            if command=='recommend' and op=='apply':q.add_argument('--engineering-reviewed',action='store_true')
            if command=='mass' and op=='apply':q.add_argument('--accept-estimate',action='store_true')
    q=subs.add_parser('qualify',help='Compare source-linked declared pad geometry and explicit pin functions, read-only.');project(q);q.add_argument('--component',required=True);input_(q,'spec');out(q);q.add_argument('--require-match',action='store_true')
    q=subs.add_parser('buildplan',help='Read-only multi-project/variant purchasing and inventory allocation.');project(q);lib(q);input_(q,'config');out(q);q.add_argument('--require-covered',action='store_true')
    p=subs.add_parser('review',help='Local authenticated reviewers, evidence-linked waivers, qualification and release decisions.');sub=p.add_subparsers(dest='operation',required=True)
    for op in ('accounts','register','deactivate','ledger','context','decide'):
        q=sub.add_parser(op);lib(q);out(q)
        if op in ('context','decide'):project(q);q.add_argument('--policy')
        if op in ('register','deactivate'):q.add_argument('--name',required=True);q.add_argument('--confirm',required=True)
        if op=='register':q.add_argument('--role',choices=['admin','engineering','supply'],required=True);q.add_argument('--admin');q.add_argument('--admin-password-env')
        if op=='deactivate':q.add_argument('--admin',required=True)
        if op in ('register','deactivate','decide'):q.add_argument('--password-env',help='Environment variable name holding a passphrase. Omit for a hidden terminal prompt. Never the passphrase itself.')
        if op=='decide':input_(q,'decision')
        if op=='context':q.add_argument('--require-approved',action='store_true')
    q=subs.add_parser('hosttest',help='Run bounded REAL installed KiCad CLI checks; unavailable/manual checks stay SKIPPED.');q.add_argument('--project');q.add_argument('--kicad-cli');q.add_argument('--directory',required=True,help='New output directory; tests work on a copy.');out(q)
    q=subs.add_parser('benchmark',help='Reproducible temporary SQLite catalog benchmark; not a native KiCad or full-project benchmark.');q.add_argument('--parts',type=int,default=10000);q.add_argument('--queries',type=int,default=100);out(q)

def secret(env,prompt):
    if env:
        if env not in os.environ:raise ValueError('Required passphrase environment variable is absent.')
        return os.environ[env]
    if not sys.stdin.isatty():raise ValueError('Use --password-env for noninteractive review. Never put a password in a JSON plan.')
    return getpass.getpass(prompt)

def run(a):
    from .cli import emit,read_input
    name=a.command;op=getattr(a,'operation','');result=None;ws=None
    if hasattr(a,'project') and a.project and name!='hosttest':ws=Workspace(Project(a.project));ws.variant_chain(a.variant)
    v=getattr(a,'variant',BASE);write_ws=False;exitcode=0
    if name=='hosttest':
        from .host_acceptance import run as run_host
        result=run_host(a.directory,a.project,a.kicad_cli);exitcode=0 if result['status']=='PASSED_EXECUTED_CHECKS' else 6 if result['status']=='UNAVAILABLE' else 3
    elif name=='benchmark':
        from .host_acceptance import benchmark
        result=benchmark(a.parts,a.queries)
    elif name=='catalog' and op=='harvest':
        result=partsdb.harvest(a.paths,recursive=a.recursive,load_workspace=not a.source_only,capture_assets=not a.metadata_only,asset_options=read_input(a.asset_config) if a.asset_config else None)
    elif name=='bomvariant':
        if op=='list':result={'variants':[{'name':k,**x} for k,x in ws.state['variants'].items() if x.get('bom_only')],'native_sync':'BOM-only variants are never written to KiCad.'}
        elif op=='preview':result=variantlab.preview(ws,read_input(a.request))
        else:result=variantlab.apply(ws,read_input(a.plan),a.confirm);write_ws=True
    elif name=='qualify':
        result=qualification.run(ws,v,eng.resolve_id(ws,v,a.component),read_input(a.spec));exitcode=3 if a.require_match and result['status']!='MATCHED_DECLARED_CHECKS' else 0
    else:
        from contextlib import nullcontext
        path=None
        if name=='mass':
            try:path=eng.library_path(ws,getattr(a,'library',''))
            except ValueError:pass
        else:path=eng.library_path(ws,getattr(a,'library',''))
        if name=='catalog' and op=='create' and a.confirm!='CREATE':raise ValueError('Type CREATE to create a new library.')
        with partsdb.Library(path,create=name=='catalog' and op=='create') if path else nullcontext(None) as lib:
            if name=='catalog':
                if op in ('create','info'):result=lib.info()
                elif op=='search':
                    from .catalogbrowse import search
                    result=search(lib,a.query,a.offset,a.limit,a.status,a.kind,a.footprint,read_input(a.filters) if a.filters else None,a.has_asset,category=a.category,manufacturer=a.manufacturer,lifecycle=a.lifecycle,sort=a.sort,descending=a.descending,summary=a.summary)
                elif op=='health':result=eng.health_report(lib,a.query,a.market,a.freshness_hours,a.offset,a.limit,a.low_stock,a.all)
                elif op=='get':result={'part':lib.get(a.id,a.revision),'history':lib.history(a.id)}
                elif op=='assets':
                    from .assetbundle import describe
                    result=describe(lib,a.id,a.revision,a.set_id)
                elif op=='preview':
                    from .assetpreview import preview
                    result=preview(lib,a.id,a.kind,a.revision,a.set_id,a.model_index,a.unit,a.style)
                    if a.format=='svg':
                        if a.kind=='model' or not a.output:raise ValueError('SVG needs symbol/footprint and a new --output path.')
                        raw=result['svg'].encode();path=automation.write_new(a.output,raw);a.output=None;result={'output':str(path),'bytes':len(raw),'asset_hash':result['asset_hash'],'warnings':result['warnings']}
                elif op=='asset-export':
                    from .assetbundle import download_asset
                    if not a.output:raise ValueError('Asset export requires a new --output path.')
                    raw,filename,_=download_asset(lib,a.id,a.hash,a.revision);from .assetbundle import write_asset_new;path=write_asset_new(a.output,raw,filename);a.output=None;result={'output':str(path),'bytes':len(raw),'suggested_name':filename,'sha256':__import__('hashlib').sha256(raw).hexdigest()}
                elif op=='verify':result=lib.verify();exitcode=0 if result['ok'] else 3
                elif op=='import':
                    from .assetbundle import read_harvest_plan
                    result=partsdb.import_harvest(lib,read_harvest_plan(a.plan),a.confirm,a.actor,a.allow_partial)
                elif op=='edit-preview':result=eng.part_preview(lib,read_input(a.request))
                elif op=='edit-apply':result=eng.part_apply(lib,read_input(a.plan),a.confirm,a.actor,a.reason)
                elif op=='evidence-preview':result=eng.evidence_preview(lib,a.id,read_input(a.record))
                elif op=='evidence-apply':result=eng.evidence_apply(lib,read_input(a.plan),a.confirm,a.actor)
                elif op=='export':result=lib.snapshot()
                elif op=='native-export':
                    if not a.output:raise ValueError('Native library ZIP requires --output.')
                    raw,_,_=partsdb.export_native_library(lib,a.ids,read_input(a.choices) if a.choices else None,a.require_complete,a.model_prefix);path=automation.write_new(a.output,raw);a.output=None;result={'output':str(path),'bytes':len(raw),'sha256':__import__('hashlib').sha256(raw).hexdigest()}
            elif name=='inventory':
                if op=='list':result={'lots':[__import__('json').loads(r[0]) for r in lib.db.execute('SELECT payload FROM inventory ORDER BY id')]}
                elif op=='preview':result=buildplan.inventory_preview(lib,read_input(a.records))
                else:result=buildplan.inventory_apply(lib,read_input(a.plan),a.confirm,a.actor)
            elif name=='recommend':
                if op=='list':result=partsdb.recommendations(lib,ws,v,eng.resolve_id(ws,v,a.component))
                elif op=='preview':result=eng.recommend_preview(lib,ws,v,eng.resolve_id(ws,v,a.component),a.part_id,a.fields)
                else:result=eng.recommend_apply(lib,ws,v,read_input(a.plan),a.confirm,a.acknowledge_loss,a.engineering_reviewed);write_ws=True
            elif name=='mass':
                if op=='suggest':result=masslib.suggest(ws,v,lib,a.field,a.unit)
                elif op=='preview':result=masslib.preview(ws,v,read_input(a.choices),lib,a.field,a.unit)
                else:result=masslib.apply(ws,v,read_input(a.plan),a.confirm,a.accept_estimate,lib);write_ws=True
            elif name=='buildplan':
                result=buildplan.run(ws,lib,read_input(a.config));exitcode=3 if a.require_covered and result['status']!='OBSERVED_PLAN' else 0
            elif name=='review':
                if op=='accounts':result={'reviewers':governance.reviewers(lib)}
                elif op=='register':result=governance.register(lib,a.name,a.role,secret(a.password_env,'New passphrase: '),a.confirm,a.admin or '',secret(a.admin_password_env,'Admin passphrase: ') if a.admin else '')
                elif op=='deactivate':result=governance.deactivate(lib,a.name,a.admin,secret(a.password_env,'Admin passphrase: '),a.confirm)
                elif op=='ledger':result={'decisions':governance.ledger(lib)}
                elif op=='context':
                    result=governance.assess(lib,governance.context(lib,ws,v,read_input(a.policy) if a.policy else None));exitcode=3 if a.require_approved and result['status']!='APPROVED_LOCAL' else 0
                else:
                    payload=read_input(a.decision)
                    if 'password' in payload:raise ValueError('Remove password from the decision file. Use hidden prompt or --password-env.')
                    payload={**payload,'password':secret(a.password_env,'Reviewer passphrase: ')};result=governance.decide(lib,ws,v,payload,read_input(a.policy) if a.policy else None)
    if write_ws:ws.save()
    if result is None:raise ValueError('Unknown engineering command/operation.')
    emit(result,a,exitcode==0);return exitcode
