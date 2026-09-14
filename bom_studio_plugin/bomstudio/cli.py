"""Stable headless command surface for people, CI, job sets and local agents.

Success reports use a versioned JSON envelope on stdout. Diagnostics go to
stderr. Native writes and workspace mutations are separate reviewed commands.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
from pathlib import Path
import json
import os
import platform
import shutil
import sys
import traceback
from . import __version__
from .native import Project,BASE,sha
from .engine import Workspace
from . import automation,search,actions,configedit,bulkedit,catalog,enforcement,evidence,intelligence,analytics,analytics_exports,measures
from .exporters import export,release,MIME
from .writeback import compile_plan,apply_plan

EXIT={'ok':0,'usage':2,'policy':3,'io':4,'review':5,'unavailable':6,'internal':7,'interrupted':130}
from .engineering_cli import COMMANDS as ENGINEERING_COMMANDS
COMMANDS=('assemblers','vendors','bom-format','library-create','fields','native-bom','doctor','info','list','query','analytics','threshold','check','health','analyze','export','release','compare','bulk','config','native','enforce','evidence','templates','run','jobset','verify','gui','schema')+ENGINEERING_COMMANDS


class StrictParser(argparse.ArgumentParser):
    def __init__(self,*args,**kwargs):
        kwargs["allow_abbrev"]=False;super().__init__(*args,**kwargs)
    def error(self,message):raise ValueError(message)


def parser():
    p=StrictParser(prog='wayricad-bom',description='WayriCAD BOM Studio — offline automation; reads SAVED files and workspace. No unattended native writes.',allow_abbrev=False)
    p.add_argument('--version',action='version',version='WayriCAD BOM Studio '+__version__)
    p.add_argument('--debug',action='store_true',help='Print a traceback for unexpected failures (may include local paths).')
    subs=p.add_subparsers(dest='command',required=True)
    def project(q,variant=True,source=True):
        q.add_argument('project',help='Root .kicad_pro or .kicad_sch')
        if variant:q.add_argument('--variant',default=BASE)
        if source:q.add_argument('--source-only',action='store_true',help='Ignore saved .wayricad-bom.json (read-only commands only).')
    def output(q):q.add_argument('--output',help='New JSON report/plan file; stdout otherwise. Never overwrites an existing file.')
    q=subs.add_parser('vendors',help='Split fitted BOM by supplier and create DigiKey/Mouser/custom upload files. No network requests.');project(q);output(q)
    q.add_argument('--config',help='Vendor mapping/config JSON or - for stdin; saved mappings otherwise.')
    q.add_argument('--vendor-field',help='Exact project property used for routing, e.g. Vendor or Distributor.')
    q.add_argument('--boards',type=int);q.add_argument('--attrition-percent')
    q.add_argument('--quantity-basis',choices=['installed','required','order'])
    q.add_argument('--format',choices=['json','zip','csv','tsv','xlsx'],default='json')
    q.add_argument('--vendor',help='One vendor ID/name for an individual CSV/TSV/XLSX; ZIP includes all vendors.')
    q.add_argument('--allow-partial',action='store_true',help='Explicitly allow incomplete routing; never bypasses source/BOM errors.')
    q.add_argument('--fingerprint',help='Require the exact review fingerprint returned by preview.')
    q.add_argument('--save-settings',action='store_true',help='Deliberately save mappings in the sidecar; no native fields change.')
    q=subs.add_parser('assemblers',help='Per-board JLCPCB, PCBWay, HQPCB, NextPCB, Sierra, PCB Power and custom-mapped BOM exports.')
    q.add_argument('project',nargs='?',help='Saved .kicad_pro/.kicad_sch; omit only with --list-profiles.')
    q.add_argument('--variant',default=BASE);q.add_argument('--source-only',action='store_true');output(q)
    q.add_argument('--list-profiles',action='store_true');q.add_argument('--config',help='Assembler JSON configuration or - for stdin.')
    q.add_argument('--profile',action='append',help='Profile ID; repeat for alternative assembler handoffs, not split orders.')
    q.add_argument('--all-profiles',action='store_true');q.add_argument('--format',choices=['json','zip','csv','xlsx','tsv'],default='json')
    q.add_argument('--acknowledge-profile-review',action='store_true',help='Explicit acknowledgement after reviewing unverified/custom provider layouts.')
    q.add_argument('--require-supplier-code',action='store_true',help='Require an LCSC code for each JLCPCB line.')
    q.add_argument('--fingerprint');q.add_argument('--save-settings',action='store_true')
    for key in ('value','comment','description','footprint','manufacturer','mpn','customer'):q.add_argument('--'+key+'-field')
    q.add_argument('--footprint-mode',choices=['identifier','name'])
    d=subs.add_parser('doctor',help='Dependency/host capability diagnosis without opening a design.');output(d)
    i=subs.add_parser('info',help='Project, saved-workspace and compatibility summary.');project(i);output(i)
    q=subs.add_parser('list',help='Enumerate variants, templates, fields, filters, profiles or variables.');project(q);q.add_argument('--what',choices=['variants','templates','fields','filters','profiles','variables'],default='variants');output(q)
    q=subs.add_parser('query',help='Search with boolean, field, missing-field and numeric predicates.');project(q);q.add_argument('--query',default='');q.add_argument('--unit',action='append',default=[],help='FIELD=UNIT override; repeat for typed numeric fields.');q.add_argument('--filter',help='Saved-filter name (mutually exclusive with --query).');q.add_argument('--case-sensitive',action='store_true');q.add_argument('--rows',action='store_true');q.add_argument('--group-by',action='append',default=[],help='Repeat to group matched rows by any fields.');q.add_argument('--limit',type=int,default=10000);q.add_argument('--offset',type=int,default=0);output(q)
    q=subs.add_parser('analytics',help='Cost, mass, dissipation, budgets, quantity scenarios and numeric statistics. Read-only.');project(q);output(q)
    q.add_argument('--config',help='Analytics configuration JSON, or - for stdin. Otherwise uses saved analytics settings.')
    q.add_argument('--metrics',nargs='+',choices=['pricing','mass','thermal']);q.add_argument('--scenario-name')
    for flag in ('price-field','price-per-field','currency-field','currency-default','moq-field','multiple-field','supplier-field','sku-field','quote-date-field','mass-field','power-field','rating-field','temperature-field','type-field','duty-field'):
        q.add_argument('--'+flag)
    q.add_argument('--price-per');q.add_argument('--mass-unit');q.add_argument('--power-unit');q.add_argument('--temperature-unit')
    q.add_argument('--power-basis',choices=['average','active']);q.add_argument('--duty-percent');q.add_argument('--temperature-requirement-c')
    q.add_argument('--boards',type=int);q.add_argument('--attrition-percent');q.add_argument('--scenario-boards',type=int,nargs='+')
    q.add_argument('--group-by',action='append');q.add_argument('--query');q.add_argument('--stat',action='append',default=[],help='FIELD=UNIT; repeated numeric statistics columns.')
    q.add_argument('--unit',action='append',default=[],help='FIELD=UNIT; repeated typed search/statistics mapping.')
    q.add_argument('--format',choices=list(analytics_exports.MIME)+['asc'],default='json');q.add_argument('--table',choices=analytics_exports.TABLES,default='summary')
    q.add_argument('--fail-on',choices=['none','error','warning','unknown'],default='none')
    q=subs.add_parser('threshold',help='Typed column threshold, e.g. --field Temp_Max --condition "<80" --unit C.');project(q);output(q)
    q.add_argument('--field',required=True);q.add_argument('--condition',required=True);q.add_argument('--unit');q.add_argument('--query',default='');q.add_argument('--rows',action='store_true')
    q.add_argument('--fail-on-match',action='store_true',help='Exit 3 when any part matches, for user-defined CI limits.')
    q.add_argument('--fail-on-unknown',action='store_true',help='Exit 3 when the tested field has missing/invalid data.')
    for name in ('check','health','analyze'):
        q=subs.add_parser(name,help={'check':'BOM data validation with exit gates.','health':'Footprint/evidence/stock health screening.','analyze':'Consolidation assessment and equivalent-value analysis.'}[name]);project(q);output(q)
        if name!='analyze':q.add_argument('--fail-on',choices=['none','error','warning','unknown'],default='error' if name=='check' else 'none')
    q=subs.add_parser('export',help='Export one variant and template to any supported BOM format.');project(q);q.add_argument('--template',help='Explicit custom template. Omit for saved native CSV using --acknowledge-saved-only.');q.add_argument('--acknowledge-saved-only',action='store_true');q.add_argument('--format',choices=[f for f in MIME if f!='zip'],required=True);q.add_argument('--output',required=True);q.add_argument('--draft',action='store_true')
    q=subs.add_parser('release',help='All-variant BOM release ZIP.');project(q,variant=False);q.add_argument('--variants',nargs='+');q.add_argument('--template',required=True,help='Explicit custom release template; no implicit Purchasing format.');q.add_argument('--output',required=True);q.add_argument('--draft',action='store_true')
    q=subs.add_parser('compare',help='Compare two variant populations and fields.');project(q,variant=False);q.add_argument('--left',default=BASE);q.add_argument('--right',required=True);output(q)
    for name in ('bulk','config','native','enforce','evidence'):
        q=subs.add_parser(name,help={'bulk':'Reviewed multi-field bulk recipes.','config':'Reviewed variables, variants, settings and template transactions.','native':'SEPARATE native-file preview/APPLY, with backups.','enforce':'Reviewed all-project field-template enforcement.','evidence':'Reviewed supplier/package evidence import.'}[name])
        ss=q.add_subparsers(dest='operation',required=True)
        for operation in ('preview','apply'):
            x=ss.add_parser(operation);project(x,variant=name=='bulk',source=False);output(x)
            if operation=='preview':
                if name=='bulk':x.add_argument('--recipe',required=True,help='Data-only JSON file, or - for stdin.')
                if name=='config':x.add_argument('--changes',required=True,help='JSON array of explicit configuration operations.')
                if name=='enforce':x.add_argument('--profile',required=True);x.add_argument('--options',help='JSON file of enforcement options.')
                if name=='evidence':x.add_argument('--payload',required=True,help='JSON payload accepted by the supplier-evidence importer.')
            else:
                x.add_argument('--plan',required=True);x.add_argument('--confirm',required=True,help={'bulk':'EDIT','config':'CONFIG','native':'APPLY','enforce':'ENFORCE','evidence':'IMPORT'}[name])
                x.add_argument('--acknowledge-loss',action='store_true',help='Acknowledge variable/configuration/field loss identified in the plan.')
                if name=='native':x.add_argument('--editors-closed',action='store_true')
                if name=='evidence':x.add_argument('--reviewed',action='store_true')
    q=subs.add_parser('templates',help='Export portable template/profile/layout definitions. Import with config.');project(q,variant=False);q.add_argument('--section',choices=['templates','field_profiles','view_presets']);q.add_argument('--name');output(q)
    q=subs.add_parser('run',help='Execute a data-only release pipeline, optionally inside a KiCad job set.');project(q,variant=False);q.add_argument('--config',required=True);dest=q.add_mutually_exclusive_group(required=True);dest.add_argument('--output-dir');dest.add_argument('--jobset-output',action='store_true',help='Use JOBSET_OUTPUT_WORK_PATH/<pipeline name>; refuse if absent.')
    q=subs.add_parser('jobset',help='Generate a NEW native job-set + Python runner/config bundle.');project(q,variant=False);q.add_argument('--directory',required=True,help='New destination directory (or intended extraction path with --zip).');q.add_argument('--python',help='Exact interpreter path.');q.add_argument('--config');q.add_argument('--platform',choices=['posix','windows']);q.add_argument('--zip',help='Write a new ZIP instead of the target directory.');output(q)
    q=subs.add_parser('verify',help='Verify a WayriCAD pipeline manifest and file hashes.');q.add_argument('directory');output(q)
    q=subs.add_parser('gui',help='Launch the local workbench, with browser fallback if the embedded runtime is unavailable.');q.add_argument('project',nargs='?');q.add_argument('--demo',action='store_true');q.add_argument('--analytics-demo',action='store_true');q.add_argument('--engineering-demo',action='store_true');q.add_argument('--no-browser',action='store_true');q.add_argument('--ui',choices=['desktop','browser','none']);q.add_argument('--port',type=int,default=0);q.add_argument('--detach',action='store_true',help='Explicitly start an independent GUI process and return a session receipt.');q.add_argument('--no-auto-link',action='store_true',help='Do not discover/connect the PCB project from inherited KiCad IPC context.')
    q=subs.add_parser('schema',help='Describe CLI JSON contracts, command families, and exit codes.');output(q)
    q=subs.add_parser('fields',help='Audit exact source properties, blanks, labels and native presets.');project(q);output(q)
    q=subs.add_parser('native-bom',help='Export SAVED native data using the installed KiCad CLI, not WayriCAD transformations.');project(q);q.add_argument('--config',help='JSON native options.');q.add_argument('--acknowledge-saved-only',action='store_true');q.add_argument('--output',required=True)
    q=subs.add_parser('bom-format',help='Inspect/inherit KiCad formats; explicit copy, merge and reviewed reverse staging.')
    ss=q.add_subparsers(dest='operation',required=True)
    for op in ('show','follow','configure','customize','merge','use-custom','preview','apply'):
        x=ss.add_parser(op);project(x,variant=False,source=op in ('show','preview'));output(x)
        if op=='configure':x.add_argument('--config',required=True,help='JSON BOM columns and formatting settings for this workspace.')
        if op=='follow':x.add_argument('--preset',default='@current');x.add_argument('--format-preset',default='@current')
        if op in ('customize','merge','use-custom','preview'):x.add_argument('--template',required=True)
        if op=='apply':x.add_argument('--plan',required=True);x.add_argument('--confirm',required=True);x.add_argument('--acknowledge-replacement',action='store_true')
    q=subs.add_parser('library-create',help='Create native KiCad symbol/footprint/3D libraries and a catalogue when needed.');ss=q.add_subparsers(dest='operation',required=True)
    for op in ('preview','apply'):
        x=ss.add_parser(op);output(x)
        if op=='preview':x.add_argument('--request',required=True,help='JSON request; mode empty, projects or catalogue; absolute new destination.')
        else:x.add_argument('--plan',required=True);x.add_argument('--confirm',required=True)
    from .engineering_cli import register
    register(subs)
    return p


def unit_args(items):
    out={}
    for item in items:
        if '=' not in item:raise ValueError('Unit mappings require FIELD=UNIT, for example Temp_Max=C.')
        field,unit=item.rsplit('=',1)
        if not field.strip() or field in out:raise ValueError('Unit mappings need a nonempty unique field name.')
        out[field]=measures.unit_name(unit)
    return out


def read_input(path):
    payload=automation.strict_loads(sys.stdin.read(20*1024*1024+1)) if path=='-' else automation.load_json(path)
    if isinstance(payload,dict) and payload.get('schema')=='wayricad-cli-1':return payload['data']
    return payload


def emit(data,a,ok=True):
    if getattr(a,'output',None):
        raw=automation.json_bytes(data);path=automation.write_new(a.output,raw)
        data={'output':path,'bytes':len(raw),'sha256':sha(raw)}
    print(json.dumps({'schema':'wayricad-cli-1','version':__version__,'command':a.command,'ok':ok,'data':data},ensure_ascii=False,allow_nan=False))


def run_command(a):
    name=a.command
    if name=='assemblers':
        from . import assembler_export as ae
        if a.list_profiles:
            if a.project or a.save_settings or a.format!='json':raise ValueError('--list-profiles is a project-free JSON read.')
            emit(ae.profiles(read_input(a.config) if a.config else None),a);return 0
        if not a.project:raise ValueError('Provide a saved project, or use --list-profiles.')
        if a.all_profiles and a.profile:raise ValueError('Use --profile or --all-profiles, not both.')
        if a.save_settings and (a.source_only or a.output or a.format!='json'):raise ValueError('Save assembler settings separately in JSON/stdout mode, without --source-only or --output.')
        ws=Workspace(Project(a.project),load=not a.source_only)
        config=ae.validate_config(read_input(a.config)) if a.config else ae.configuration(ws)
        if a.profile:config['profiles']=a.profile
        if a.all_profiles:config['profiles']=list(ae.PROFILES)
        if a.acknowledge_profile_review:config['acknowledge_review_required']=True
        if a.require_supplier_code:config['require_supplier_code']=True
        if a.footprint_mode:config['footprint_mode']=a.footprint_mode
        for k in ae.MAPPINGS:
            if getattr(a,k+'_field') is not None:config['fields'][k]=getattr(a,k+'_field')
        report=ae.preview(ws,a.variant,config)
        if a.fingerprint and a.fingerprint!=report['fingerprint']:raise ValueError('Assembly review is stale. Preview again.')
        if a.save_settings:ae.configure(ws,config);ws.save()
        failed=report['status'] in ('BLOCKED','REVIEW_REQUIRED')
        if a.format=='json':emit(report,a,not failed);return 3 if failed else 0
        if not a.output:raise ValueError('Assembly upload outputs require a new --output file.')
        if failed:
            emit({'status':report['status'],'summary':report['summary'],'blocking_checks':report['blocking_checks'],
                  'issues':[i for p in report['profiles'] for i in p['issues']],'output_created':False},argparse.Namespace(command=name),False)
            return 3
        raw,filename,mime=ae.export(ws,a.variant,config,a.format,fingerprint=report['fingerprint'])
        path=automation.write_new(a.output,raw)
        emit({'output':path,'bytes':len(raw),'sha256':sha(raw),'mime':mime,'status':report['status'],
              'quantity_basis':'per_board','summary':report['summary']},argparse.Namespace(command=name));return 0
    if name=='vendors':
        from . import vendor_export as ve
        if a.save_settings and a.source_only:raise ValueError('--save-settings cannot be combined with --source-only.')
        if a.save_settings and (a.format!='json' or a.output):raise ValueError('Save settings separately using JSON/stdout only, then export after review.')
        ws=Workspace(Project(a.project),load=not a.source_only)
        config=ve.validate_config(read_input(a.config)) if a.config else ve.configuration(ws)
        for k in ('vendor_field','boards','attrition_percent','quantity_basis'):
            if getattr(a,k) is not None:config[k]=getattr(a,k)
        config=ve.validate_config(config)
        report=ve.preview(ws,a.variant,config)
        if a.fingerprint and a.fingerprint!=report['fingerprint']:raise ValueError('Vendor review is stale; preview again.')
        if a.save_settings:ve.configure(ws,config);ws.save()
        failed=bool(report['blocking_checks'] or (report['unassigned'] and not a.allow_partial) or (report['summary']['eligible_components'] and not report['vendors']))
        if a.format=='json':emit(report,a,not failed);return 3 if failed else 0
        if not a.output:raise ValueError('Upload outputs require a new --output file.')
        if failed:
            emit({'status':report['status'],'summary':report['summary'],'issues':report['issues'],'blocking_checks':report['blocking_checks'],'output_created':False},argparse.Namespace(command=name),False)
            return 3
        raw,filename,mime=ve.export(ws,a.variant,config,a.format,a.vendor,a.allow_partial,report['fingerprint'])
        output_path=automation.write_new(a.output,raw)
        emit({'output':output_path,'bytes':len(raw),'sha256':sha(raw),'mime':mime,'status':'PARTIAL' if report['unassigned'] else report['status'],'summary':report['summary']},argparse.Namespace(command=name))
        return 0
    if name=='bom-format':
        from . import nativefirst as nf
        ws=Workspace(Project(a.project),load=not getattr(a,'source_only',False))
        op=a.operation
        if op=='show':data=nf.context(ws)
        elif op=='configure':data=nf.configure_export(ws,read_input(a.config))
        elif op=='follow':data=nf.select(ws,'native',a.preset,a.format_preset)
        elif op in ('customize','merge'):data=nf.customize(ws,a.template,op=='merge')
        elif op=='use-custom':data=nf.select(ws,'custom',custom_template=a.template)
        elif op=='preview':data=nf.reverse_preview(ws,a.template)
        else:
            plan=read_input(a.plan)
            if plan.get('schema')!='wayricad-format-plan-1':raise ValueError('Invalid format review plan.')
            data=nf.reverse_apply(ws,plan['template'],plan['fingerprint'],a.confirm,a.acknowledge_replacement)
        if op not in ('show','preview'):ws.save()
        emit(data,a);return 0
    if name=='library-create':
        from . import librarymaker
        data=librarymaker.preview(read_input(a.request)) if a.operation=='preview' else librarymaker.apply(read_input(a.plan),a.confirm)
        emit(data,a);return 0
    if name=='fields':
        from .field_registry import inventory
        ws=Workspace(Project(a.project),load=not a.source_only)
        emit(inventory(ws,a.variant),a);return 0
    if name=='native-bom':
        from . import nativebom
        ws=Workspace(Project(a.project),load=not a.source_only)
        from .nativefirst import inherited_options
        result=nativebom.generate(ws,read_input(a.config) if a.config else inherited_options(ws,a.variant),a.acknowledge_saved_only);raw=result.pop('data');report=result
        output=automation.write_new(a.output,raw)
        print(json.dumps({'schema':'wayricad-cli-1','version':__version__,'command':name,'ok':True,'data':{**report,'output':output,'bytes':len(raw),'sha256':sha(raw)}},ensure_ascii=False));return 0
    if name in ENGINEERING_COMMANDS:
        from .engineering_cli import run
        return run(a)
    if name=='schema':
        emit({'commands':list(COMMANDS),'exit_codes':EXIT,'schemas':['wayricad-assembler-config-1','wayricad-assembler-report-1','wayricad-assembler-package-1','wayricad-vendor-config-1','wayricad-vendor-split-1','wayricad-vendor-package-1','wayricad-cli-1','wayricad-query-1','wayricad-bulk-recipe-1','wayricad-bulk-plan-1','wayricad-config-plan-1','wayricad-native-plan-1','wayricad-enforce-plan-1','wayricad-evidence-plan-1','wayricad-pipeline-1','wayricad-run-1','wayricad-filters-1','wayricad-analytics-config-1','wayricad-analytics-1','wayricad-threshold-1'],
              'mutations':'Reviewed apply operations and explicit BOM-format selection/copy save the workspace; native apply remains separate.',
              'review_tokens':{'bom-format':'FORMAT','bulk':'EDIT','config':'CONFIG','enforce':'ENFORCE','evidence':'IMPORT','native':'APPLY'},
              'default_pipeline':automation.default_pipeline()},a);return 0
    if name=='doctor':
        from .bridge import diagnostic
        from .assetpreview import capabilities as preview_caps
        from .desktop import diagnostic as desktop_diagnostic
        emit({'python':sys.version.split()[0],'platform':platform.platform(),'kicad_cli':shutil.which('kicad-cli'),'live_link':diagnostic(),'asset_preview':preview_caps(),'desktop':desktop_diagnostic(),'host_tested':False,'offline_core':True},a);return 0
    if name=='verify':
        report=automation.verify_run(a.directory);emit(report,a,report['valid']);return 0 if report['valid'] else 3
    if name=='gui':
        from .server import Application,Server
        import webbrowser
        if a.detach:
            from .launch import detached
            emit(detached(a.project,a.demo,a.no_browser,a.port,a.no_auto_link,a.analytics_demo,a.engineering_demo,a.ui),a);return 0
        app=Application(a.project,a.demo,auto_link=not a.no_auto_link,analytics_demo=a.analytics_demo,engineering_demo=a.engineering_demo);server=Server(app,a.port)
        from .desktop import ui_mode,run as desktop_run
        mode=ui_mode(a.no_browser,a.ui);app.ui_mode=mode
        if mode=='desktop':
            desktop_run(server);return 0
        print(server.url,flush=True)
        if mode=='browser':webbrowser.open(server.url,new=2)
        try:server.serve_forever(poll_interval=.2)
        finally:server.server_close()
        return 0
    ws=Workspace(Project(a.project),load=not getattr(a,'source_only',False));variant=getattr(a,'variant',BASE)
    ws.variant_chain(variant)
    if name=='info':
        emit({'project':ws.project.status(),'workspace':str(ws.sidecar),'workspace_loaded':not a.source_only and ws.sidecar.exists(),'variants':[BASE]+list(ws.state['variants']),
              'components':len(ws.project.components),'source_sha256':ws.project.hashes,'workspace_sha256':sha(ws._serialize().encode()),'selected_variant':variant,'native_writes_require_separate_apply':True},a)
    elif name=='list':
        items={'variants':[BASE]+list(ws.state['variants']),'templates':ws.state['templates'],'fields':sorted(set().union(*(set(r['fields'])|set(r['raw']) for r in ws.rows(variant)))),'filters':ws.state.get('saved_filters',{}),'profiles':ws.state['field_profiles'],'variables':{'effective':ws.variables(variant),'project':ws.project.variables,'project_edits':ws.state['project_variables'],'workspace':ws.state['variables']}}[a.what]
        emit({'kind':a.what,'variant':variant,'items':items},a)
    elif name=='query':
        if a.limit<1 or a.limit>100000 or a.offset<0:raise ValueError('Query limit must be 1–100,000; offset must be nonnegative.')
        query=a.query;case=a.case_sensitive
        if a.filter:
            if a.query:raise ValueError('Choose --query or --filter, not both.')
            record=ws.state.get('saved_filters',{}).get(a.filter)
            if record is None:raise ValueError('Unknown saved filter: '+a.filter)
            query=record['query'];case=record.get('case_sensitive',False) or case
        field_units={**analytics.units_for(ws),**unit_args(a.unit)}
        report=search.run(ws,variant,query,case,a.rows,field_units=field_units)
        report['field_units']=field_units
        if a.group_by:
            rows,_=search.select(ws,variant,query,case,field_units=field_units)
            known=set().union(*(set(r['fields'])|set(r['raw']) for r in ws.rows(variant)))
            if any(f not in known for f in a.group_by):raise ValueError('Unknown grouping field.')
            groups=bulkedit.groups(ws,variant,a.group_by,rows=rows)
            report['group_count']=len(groups['groups'])
            report['groups']=groups['groups'][a.offset:a.offset+a.limit]
            report['next_group_offset']=a.offset+a.limit if a.offset+a.limit<report['group_count'] else None
        start=a.offset;end=start+a.limit
        report['ids']=report['ids'][start:end];report['references']=report['references'][start:end]
        if a.rows:report['rows']=report['rows'][start:end]
        report.update(offset=start,returned=len(report['ids']),next_offset=end if end<report['matched'] else None)
        emit(report,a)
    elif name=='threshold':
        report=analytics.threshold(ws,variant,a.field,a.condition,a.unit,a.query,a.rows)
        bad=(a.fail_on_match and report['matched']>0) or (a.fail_on_unknown and bool(report['unknown_or_invalid']))
        emit(report,a,not bad);return 3 if bad else 0
    elif name=='analytics':
        config=analytics.validate_config(read_input(a.config)) if a.config else analytics.defaults(ws)
        for key in analytics.DEFAULT:
            if hasattr(a,key) and getattr(a,key) is not None and key not in ('schema','metrics'):
                config[key]=getattr(a,key)
        if a.metrics is not None:config['metrics']=a.metrics
        config['field_units'].update(unit_args(a.unit));config['statistics'].update(unit_args(a.stat))
        report=analytics.run(ws,variant,config);bad=automation.violations(report['issues'],a.fail_on)
        if a.format=='json':emit(report,a,not bad)
        else:
            if not a.output:raise ValueError('Non-JSON analytics reports require --output. No file was created.')
            raw,filename,mime=analytics_exports.render(report,a.format,a.table)
            path=automation.write_new(a.output,raw)
            emit({'output':path,'bytes':len(raw),'sha256':sha(raw),'mime':mime,'status':'ADVISORY','policy_violations':len(bad)},argparse.Namespace(command=name),not bad)
        return 3 if bad else 0
    elif name in ('check','health','analyze'):
        report={'schema':'wayricad-checks-1','variant':variant,'issues':ws.checks(variant)} if name=='check' else intelligence.run(ws,variant) if name=='health' else intelligence.analyze(ws,variant)
        bad=automation.violations(report['issues'],a.fail_on) if name!='analyze' else []
        emit(report,a,not bad);return 3 if bad else 0
    elif name in ('export','release'):
        if Path(a.output).exists() or Path(a.output).is_symlink():raise FileExistsError('Output already exists; choose a new path.')
        if name=='export' and not a.template:
            if a.format!='csv' or a.draft:
                raise ValueError('Native-first output supports only CSV. Explicitly choose --template NAME for other formats/drafts.')
            from . import nativebom, nativefirst
            result=nativebom.generate(ws,nativefirst.inherited_options(ws,variant),a.acknowledge_saved_only)
            data=result['data'];path=automation.write_new(a.output,data)
            emit({'output':path,'bytes':len(data),'sha256':sha(data),'mime':'text/csv; charset=utf-8','status':'NATIVE_SAVED_ONLY','notice':result['notice']},argparse.Namespace(command=name))
            return 0
        try:data,filename,mime=export(ws,variant,a.template,a.format,a.draft) if name=='export' else release(ws,a.variants,a.template,a.draft)
        except ValueError as e:
            if 'blocking' in str(e):emit({'error':str(e)},argparse.Namespace(command=name),False);return 3
            raise
        path=automation.write_new(a.output,data)
        emit({'output':path,'bytes':len(data),'sha256':sha(data),'mime':mime,'status':'DRAFT' if a.draft else 'CHECKED'},argparse.Namespace(command=name))
    elif name=='compare':emit({'left':a.left,'right':a.right,'changes':ws.compare(a.left,a.right)},a)
    elif name in ('bulk','config','native','enforce','evidence'):
        if a.operation=='preview':
            if name=='bulk':plan=actions.preview(ws,variant,read_input(a.recipe))
            elif name=='config':plan=configedit.preview(ws,read_input(a.changes))
            elif name=='native':plan=dict(compile_plan(ws),schema='wayricad-native-plan-1')
            elif name=='enforce':
                if a.profile not in ws.state['field_profiles']:raise ValueError('Unknown field profile.')
                profile=ws.state['field_profiles'][a.profile];options=read_input(a.options) if a.options else {}
                plan=dict(enforcement.preview(ws,profile,options),schema='wayricad-enforce-plan-1',definition=profile)
            else:
                payload=read_input(a.payload);plan=dict(evidence.preview(ws,payload),schema='wayricad-evidence-plan-1',payload=payload)
            emit(plan,a,not bool(plan.get('errors')));return 3 if plan.get('errors') else 0
        # Validate all planned operations before a saved mutation. Output path precheck prevents
        # making a successful change followed by a misleading report-collision failure.
        if a.output:automation.validate_new_path(a.output)
        plan=read_input(a.plan)
        expected={'bulk':'wayricad-bulk-plan-1','config':'wayricad-config-plan-1','native':'wayricad-native-plan-1','enforce':'wayricad-enforce-plan-1','evidence':'wayricad-evidence-plan-1'}[name]
        if not isinstance(plan,dict) or plan.get('schema')!=expected:raise ValueError('Expected '+expected+' plan.')
        if name=='bulk':
            if plan.get('variant')!=variant:raise ValueError('Plan variant differs; supply the same --variant used for preview.')
            result=actions.apply(ws,variant,plan['recipe'],plan['fingerprint'],a.confirm,a.acknowledge_loss)
        elif name=='config':result=configedit.apply(ws,plan['operations'],plan['fingerprint'],a.confirm,a.acknowledge_loss)
        elif name=='native':
            current=compile_plan(ws)
            if current['fingerprint']!=plan['fingerprint']:raise ValueError('Native plan is stale; preview again.')
            ws,backup=apply_plan(ws,plan['fingerprint'],a.confirm,a.editors_closed);result={'backup':backup,'native_files_written':True}
        elif name=='enforce':
            current=enforcement.preview(ws,plan['definition'],plan['options'])
            if current['fingerprint']!=plan['fingerprint']:raise ValueError('Enforcement plan is stale.')
            enforcement.apply(ws,plan['fingerprint'],a.confirm,a.acknowledge_loss);result={'staged':True,'events':len(current['events'])}
        else:result=evidence.apply(ws,plan['payload'],plan['fingerprint'],a.confirm,a.reviewed)
        if name!='native':result=dict(result or {},workspace=ws.save(),native_files_written=False)
        emit(result,a)
    elif name=='templates':emit(catalog.bundle(ws,a.section,a.name),a)
    elif name=='run':
        config=read_input(a.config);validated=automation.validate_pipeline(config,ws)
        if a.jobset_output:
            env=os.environ.get('JOBSET_OUTPUT_WORK_PATH')
            if not env or not Path(env).is_absolute() or not Path(env).is_dir():raise ValueError('JOBSET_OUTPUT_WORK_PATH must identify an existing absolute directory supplied by KiCad.')
            dest=Path(env)/validated['name']
        else:dest=a.output_dir
        result=automation.pipeline(ws,config,dest);emit(result,a,result['status']=='PASSED');return 0 if result['status']=='PASSED' else 3
    elif name=='jobset':
        config=read_input(a.config) if a.config else None
        kwargs={'python':a.python,'platform':a.platform,'config':config}
        if a.zip:
            data,_,_=automation.jobset_bundle(ws,a.directory,**kwargs);path=automation.write_new(a.zip,data);result={'zip':path,'extract_to':str(Path(a.directory).absolute())}
        else:
            files=automation.jobset_files(ws,a.directory,**kwargs);directory=Path(a.directory).expanduser();directory.mkdir(parents=False,exist_ok=False)
            try:
                for name,data in files.items():automation.write_new(directory/name,data)
            except BaseException:shutil.rmtree(directory,ignore_errors=True);raise
            result={'directory':str(directory.resolve()),'files':list(files)}
        emit(result,a)
    return 0


def legacy(argv):
    """Retain 0.1–0.3 positional export/check invocations, without silent GUI launch."""
    p=argparse.ArgumentParser(description='Legacy WayriCAD CLI (use subcommands for new scripts)',allow_abbrev=False)
    p.add_argument('project');p.add_argument('--variant',default=BASE);p.add_argument('--template',default='Purchasing');p.add_argument('--format',choices=list(MIME));p.add_argument('--output');p.add_argument('--draft',action='store_true')
    a=p.parse_args(argv);print('Legacy CLI syntax: migrate to check/export/release subcommands.',file=sys.stderr)
    ws=Workspace(Project(a.project))
    if not a.format:
        issues=ws.checks(a.variant);print(json.dumps(issues,ensure_ascii=False,indent=2));return 2 if any(i['severity']=='error' for i in issues) else 0
    if not a.output:p.error('--output is required for exports')
    data,_,_=release(ws,template=a.template,draft=a.draft) if a.format=='zip' else export(ws,a.variant,a.template,a.format,a.draft)
    automation.write_new(a.output,data);print(a.output);return 0


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv);a=None
    try:
        if argv and argv[0] not in COMMANDS and Path(argv[0]).suffix.lower() in ('.kicad_pro','.kicad_sch'):return legacy(argv)
        a=parser().parse_args(argv);return run_command(a)
    except KeyboardInterrupt:return 130
    except BrokenPipeError:return 0
    except Exception as e:
        from .bridge import BridgeUnavailable
        from .desktop import DesktopUnavailable
        if isinstance(e,(BridgeUnavailable,DesktopUnavailable)):code=6
        elif isinstance(e,(FileNotFoundError,FileExistsError,PermissionError,OSError)):code=4
        elif isinstance(e,(ValueError,KeyError,TypeError)):
            code=5 if any(w in str(e).lower() for w in ('stale','acknowledge','confirm','type edit','type apply','type config','type enforce','type import','type create')) else 2
        else:code=7
        if a is not None and getattr(a,'debug',False):traceback.print_exc(file=sys.stderr)
        print(json.dumps({'schema':'wayricad-cli-error-1','version':__version__,'exit_code':code,'error':str(e),'type':type(e).__name__},ensure_ascii=False),file=sys.stderr)
        return code

if __name__=='__main__':raise SystemExit(main())
