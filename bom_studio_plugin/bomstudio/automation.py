"""Read-only release pipelines and native KiCad Execute-Command job sets.

Pipeline recipes are data, not shell scripts. Headless runs never save native
KiCad files or workspace edits. Every run publishes a manifest and reports;
failed policy gates publish no BOM files.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import uuid
import zipfile
from . import __version__,intelligence,analytics,analytics_exports
from .native import BASE,sha
from .exporters import export,MIME


def strict_loads(text,max_bytes=20*1024*1024):
    if not isinstance(text,str) or len(text)>max_bytes:raise ValueError(f'JSON input exceeds {max_bytes//(1024*1024)} MiB.')
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise ValueError('Duplicate JSON key: '+k)
            if k in ('__proto__','constructor','prototype'):raise ValueError('Unsafe JSON key: '+k)
            out[k]=v
        return out
    try:return json.loads(text,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON value: '+x)))
    except RecursionError as e:raise ValueError('JSON nesting is too deep.') from e


def load_json(path):
    path=Path(path).expanduser()
    if path.stat().st_size>20*1024*1024:raise ValueError('JSON input exceeds 20 MiB.')
    return strict_loads(path.read_text(encoding='utf-8-sig'))


def json_bytes(data):return (json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def validate_new_path(path):
    path=Path(path).expanduser()
    if path.suffix.lower() in ('.kicad_sch','.kicad_pcb','.kicad_pro','.kicad_mod','.kicad_sym') or path.name.lower().endswith('.wayricad-bom.json'):
        raise ValueError('Automation output must not be a native design file or workspace sidecar.')
    if path.exists() or path.is_symlink():raise FileExistsError('Output already exists; choose a new path.')
    if not path.parent.is_dir():raise FileNotFoundError('Output parent directory does not exist.')
    if not os.access(path.parent,os.W_OK):raise PermissionError('Output directory is not writable.')
    return path


def write_new(path,data):
    """Exclusive creation: no existing destination, source or sidecar is overwritten."""
    path=validate_new_path(path)
    with open(path,'xb') as f:
        try:f.write(data);f.flush();os.fsync(f.fileno())
        except BaseException:
            f.close()
            try:path.unlink()
            except OSError:pass
            raise
    return str(path.resolve())


def default_pipeline():
    return {'schema':'wayricad-pipeline-1','name':'WayriCAD_BOM','variants':'all','template':'Purchasing',
            'formats':['csv','xlsx','json','txt'],'reports':['checks','health','analysis'],
            'analytics':None,'analytics_formats':['json'],
            'policy':{'checks':'error','health':'none','require_stock':False,'analytics':'none'}}


def validate_pipeline(config,ws):
    if not isinstance(config,dict) or set(config)-{'schema','name','variants','template','formats','reports','policy','analytics','analytics_formats','release_control','vendor_exports','assembler_exports'}:raise ValueError('Unknown pipeline keys.')
    if config.get('schema')!='wayricad-pipeline-1':raise ValueError('Expected wayricad-pipeline-1 configuration.')
    c=default_pipeline();c.update(config)
    if not isinstance(c['name'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,59}',c['name']):raise ValueError('Pipeline name needs 1–60 ASCII letters/digits/_/-, beginning with a letter.')
    variants=[BASE]+list(ws.state['variants']) if c['variants']=='all' else c['variants']
    if not isinstance(variants,list) or not variants or len(variants)>100 or len(set(variants))!=len(variants):raise ValueError('Choose 1–100 unique variants or all.')
    for v in variants:ws.variant_chain(v)
    c['variants']=variants
    if c['template'] not in ws.state['templates']:raise ValueError('Unknown BOM template: '+str(c['template']))
    formats=c['formats'];reports=c['reports']
    if not isinstance(formats,list) or not formats or len(formats)>11 or len(set(formats))!=len(formats) or any(f not in MIME or f=='zip' for f in formats):raise ValueError('Choose unique BOM formats other than ZIP; pipeline creates a directory.')
    if not isinstance(reports,list) or len(set(reports))!=len(reports) or any(r not in ('checks','health','analysis','analytics') for r in reports):raise ValueError('Reports: checks, health, analysis, analytics.')
    if c['analytics'] is not None:c['analytics']=analytics.validate_config(c['analytics'])
    af=c['analytics_formats']
    if not isinstance(af,list) or not af or len(set(af))!=len(af) or any(f not in ('json','csv','xlsx','html') for f in af):raise ValueError('Pipeline analytics_formats: unique json, csv, xlsx, html.')
    policy=c['policy']
    if not isinstance(policy,dict) or set(policy)-{'checks','health','require_stock','analytics'}:raise ValueError('Unknown policy key.')
    p={'checks':'error','health':'none','require_stock':False,'analytics':'none'};p.update(policy)
    if p['analytics'] not in ('none','error','warning','unknown'):raise ValueError('Analytics gate: none, error, warning or unknown.')
    if p['checks'] not in ('error','warning'):raise ValueError('Checks gate must be error or warning; it cannot be disabled.')
    if p['health'] not in ('none','error','warning','unknown'):raise ValueError('Health gate: none, error, warning or unknown.')
    if not isinstance(p['require_stock'],bool):raise ValueError('require_stock must be a boolean.')
    c['policy']=p
    ve=c.get('vendor_exports')
    if ve is not None:
        from .vendor_export import validate_config
        c['vendor_exports']=validate_config(ve)
    ae=c.get('assembler_exports')
    if ae is not None:
        from .assembler_export import validate_config as validate_assembler
        c['assembler_exports']=validate_assembler(ae)
    rc=c.get('release_control')
    if rc is not None:
        from .governance import validate_policy
        if not isinstance(rc,dict) or set(rc)-{'library','policy'} or not isinstance(rc.get('library'),str) or not rc['library']:
            raise ValueError('release_control requires a library directory and optional review policy.')
        c['release_control']={'library':rc['library'],'policy':validate_policy(rc.get('policy'))}
    return c


def violations(issues,threshold):
    levels={'none':set(),'error':{'error'},'warning':{'error','warning'},'unknown':{'error','warning','unknown'}}
    if threshold not in levels:raise ValueError('Unknown policy severity.')
    return [i for i in issues if i['severity'] in levels[threshold]]


def pipeline(ws,config,output_dir):
    c=validate_pipeline(config,ws);ws.project.check_unchanged()
    out=Path(output_dir).expanduser().absolute()
    if out.exists() or out.is_symlink():raise FileExistsError('Run output must be a new directory: '+str(out))
    if not out.parent.is_dir():raise ValueError('The output parent directory must already exist.')
    stage=Path(tempfile.mkdtemp(prefix='.wayricad-run-',dir=out.parent));entries={};gates=[];variant_summary={};vendor_reports={};assembler_reports={}
    manifest={'schema':'wayricad-run-1','app_version':__version__,'started_at':datetime.now(timezone.utc).isoformat(),
              'config':c,'project':ws.project.name,'source_sha256':dict(ws.project.hashes),
              'workspace_sha256':sha(ws._serialize().encode()),'status':'FAILED','files':entries,
              'limits':['BOM-data policy only; not ERC/DRC, electrical qualification or manufacturing approval.',
                        'Source hashes and manifests provide integrity, not digital signatures.',
                        'Reads saved workspace and saved native files, never unsaved editor memory.']}
    def put(name,data):
        p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        entries[name]={'sha256':sha(data),'bytes':len(data)}
    try:
        put('workspace_snapshot.json',ws._serialize().encode('utf-8'))
        for index,v in enumerate(c['variants'],1):
            prefix=f'{index:03d}';checks=ws.checks(v);bad=violations(checks,c['policy']['checks'])
            if bad:gates.append({'variant':v,'kind':'checks','count':len(bad)})
            put(prefix+'/checks.json',json_bytes(checks))
            if c.get('vendor_exports') is not None:
                from . import vendor_export
                vr=vendor_export.preview(ws,v,c['vendor_exports']);vendor_reports[v]=vr
                put(prefix+'/vendor-routing.json',json_bytes(vr))
                if vr['blocking_checks'] or vr['unassigned'] or (vr['summary']['eligible_components'] and not vr['vendors']):
                    gates.append({'variant':v,'kind':'vendor_routing','count':len(vr['unassigned'])+len(vr['blocking_checks'])+(not vr['vendors'])})
            if c.get('assembler_exports') is not None:
                from . import assembler_export
                ar=assembler_export.preview(ws,v,c['assembler_exports']);assembler_reports[v]=ar
                put(prefix+'/assembler-review.json',json_bytes(ar))
                if ar['status'] in ('BLOCKED','REVIEW_REQUIRED'):
                    gates.append({'variant':v,'kind':'assembler_handoff','count':sum(len(p['issues']) for p in ar['profiles'])+len(ar['blocking_checks'])})
            health=None
            if 'health' in c['reports'] or c['policy']['health']!='none' or c['policy']['require_stock']:
                health=intelligence.run(ws,v);put(prefix+'/health.json',json_bytes(health))
                bad=violations(health['issues'],c['policy']['health'])
                if bad:gates.append({'variant':v,'kind':'health','count':len(bad)})
                uncovered=[d for d in health['demand'] if d['stock']['status']!='observed_covered']
                if c['policy']['require_stock'] and uncovered:gates.append({'variant':v,'kind':'stock_not_observed_covered','count':len(uncovered)})
            if 'analysis' in c['reports']:put(prefix+'/analysis.json',json_bytes(intelligence.analyze(ws,v)))
            if 'analytics' in c['reports'] or c['policy']['analytics']!='none':
                quantitative=analytics.run(ws,v,c['analytics']);put(prefix+'/analytics.json',json_bytes(quantitative))
                for fmt in c['analytics_formats']:
                    if fmt=='json':continue
                    for table_name in (analytics_exports.TABLES if fmt=='csv' else ('summary',)):
                        raw,_,_=analytics_exports.render(quantitative,fmt,table_name)
                        put(prefix+'/analytics'+('_'+table_name if fmt=='csv' else '')+'.'+fmt,raw)
                bad=violations(quantitative['issues'],c['policy']['analytics'])
                if bad:gates.append({'variant':v,'kind':'analytics','count':len(bad)})
            if c.get('release_control'):
                from .partsdb import Library
                from .governance import context,assess
                rc=c['release_control']
                with Library(rc['library']) as lib:controlled=assess(lib,context(lib,ws,v,rc['policy']))
                put(prefix+'/controlled-review.json',json_bytes(controlled))
                if controlled['status']!='APPROVED_LOCAL':gates.append({'variant':v,'kind':'controlled_review','count':len(controlled['unwaived_issues'])+len(controlled['missing_roles'])+len(controlled['unapproved_qualifications'])})
            variant_summary[prefix]={'variant':v,'checks':len(checks),'health':health['summary'] if health else None}
        if not gates:
            for index,v in enumerate(c['variants'],1):
                if v in vendor_reports:
                    from .vendor_export import package_files
                    for path,data in package_files(vendor_reports[v]).items():put(f'{index:03d}/vendors/'+path,data)
                if v in assembler_reports:
                    from .assembler_export import package_files as assembly_files
                    for path,data in assembly_files(assembler_reports[v]).items():put(f'{index:03d}/assemblers/'+path,data)
                for fmt in c['formats']:
                    data,name,_=export(ws,v,c['template'],fmt)
                    # Numbered variant folders avoid sanitized-name collisions.
                    put(f'{index:03d}/'+name,data)
            manifest['status']='PASSED'
        ws.project.check_unchanged()
        if c.get('release_control'):
            from .partsdb import Library
            from .governance import context,assess
            with Library(c['release_control']['library']) as lib:
                for index,v in enumerate(c['variants'],1):
                    before=json.loads((stage/f'{index:03d}'/'controlled-review.json').read_text())
                    current=assess(lib,context(lib,ws,v,c['release_control']['policy']))
                    if before['input_hash']!=current['input_hash'] or before['status']!=current['status']:raise ValueError('Release approval/catalog changed during pipeline; rerun.')
        manifest.update(variants=variant_summary,gates=gates,completed_at=datetime.now(timezone.utc).isoformat())
        (stage/'manifest.json').write_bytes(json_bytes(manifest))
        # Directory rename is atomic within a filesystem; existing runs are never replaced.
        if out.exists():raise FileExistsError('Another process created the output directory.')
        stage.rename(out)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise
    return {'schema':'wayricad-run-result-1','status':manifest['status'],'output':str(out),'manifest':str(out/'manifest.json'),'gates':gates,'files':len(entries)}


def verify_run(directory):
    root=Path(directory).expanduser().resolve(strict=True);m=load_json(root/'manifest.json')
    if m.get('schema')!='wayricad-run-1' or not isinstance(m.get('files'),dict):raise ValueError('Not a WayriCAD pipeline manifest.')
    failures=[]
    for name,info in m['files'].items():
        p=root/name
        if Path(name).is_absolute() or '\\' in name or '..' in Path(name).parts or not p.resolve().is_relative_to(root):raise ValueError('Unsafe manifest file path.')
        if p.is_symlink() or not p.is_file() or p.stat().st_size!=info['bytes'] or sha(p.read_bytes())!=info['sha256']:failures.append(name)
    extras=[p.relative_to(root).as_posix() for p in root.rglob('*') if (p.is_file() or p.is_symlink()) and p!=root/'manifest.json' and p.relative_to(root).as_posix() not in m['files']]
    return {'valid':not failures and not extras,'changed_or_missing':failures,'unlisted':extras,'release_status':m.get('status'),'files':len(m['files']),
            'note':'Hash verification is not an authenticated signature or engineering approval.'}


def shell_command(argv,platform=None):
    platform=platform or ('windows' if os.name=='nt' else 'posix')
    if any(not isinstance(a,str) or '\n' in a or '\r' in a or '\x00' in a for a in argv):raise ValueError('Unsafe command path.')
    if platform=='windows':
        # cmd.exe expands %, ! even inside quotes. Refuse instead of guessing escaping.
        if any(any(c in a for c in '%!\"') for a in argv):raise ValueError('Windows job paths cannot contain %, ! or double quotes. Move the automation folder to a simple path.')
        return ' '.join('"'+a+'"' for a in argv)
    if platform!='posix':raise ValueError('Platform must be windows or posix.')
    return shlex.join(argv)


def jobset_files(ws,directory,python=None,plugin_root=None,config=None,platform=None):
    """Return self-contained config/bootstrap/native jobset; no writes performed."""
    if not isinstance(directory,(str,Path)) or not str(directory).strip() or not Path(directory).expanduser().is_absolute():raise ValueError('Job-set extraction directory must be an absolute path on this machine.')
    directory=Path(directory).expanduser().absolute();python=str(Path(python or sys.executable).expanduser().absolute())
    plugin_root=str(Path(plugin_root or Path(__file__).resolve().parent.parent).expanduser().absolute())
    config=config or default_pipeline();validate_pipeline(config,ws)
    project=str(ws.project.pro_path if ws.project.pro_path.exists() else ws.project.root)
    runner=directory/'run_wayricad_job.py'
    command=shell_command([python,str(runner)],platform)
    jid=str(uuid.uuid4());oid=str(uuid.uuid4())
    native={'meta':{'version':1},'jobs':[{'id':jid,'type':'special_execute','description':'WayriCAD checked BOM pipeline',
              'settings':{'command':command,'ignore_exit_code':False,'record_output':True}}],
            'outputs':[{'id':oid,'type':'folder','description':'WayriCAD BOM release','only':[jid],
                        'settings':{'output_path':str(directory/'releases')}}]}
    bootstrap='''#!/usr/bin/env python3
"""Generated WayriCAD job runner. Review config before executing; no native writes."""
from pathlib import Path
import json, os, sys
HERE=Path(__file__).resolve().parent
setup=json.loads((HERE/'job-bootstrap.json').read_text(encoding='utf-8'))
sys.path.insert(0, setup['plugin_root'])
from bomstudio.cli import main
args=['run',setup['project'],'--config',str(HERE/'pipeline.json')]
if os.environ.get('JOBSET_OUTPUT_WORK_PATH'):
    args+=['--jobset-output']
else:
    # Outside a job set, give each manual run a fresh destination.
    from datetime import datetime, timezone
    from uuid import uuid4
    dest=HERE/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    args+=['--output-dir',str(dest)]
raise SystemExit(main(args))
'''
    readme=("WayriCAD BOM job-set bundle\n\nExtract ALL files into the exact folder selected at generation:\n"+str(directory)+
        "\n\nOpen WayriCAD_BOM.kicad_jobset in this project's KiCad Job Sets tab and run.\n"
        "The job uses Special: Execute Command; Ignore exit code is false.\n"
        "run_wayricad_job.py reads KiCad's JOBSET_OUTPUT_WORK_PATH and publishes its\n"
        "WayriCAD_BOM subdirectory there so KiCad can collect it into the configured output.\n"
        "A failed policy returns nonzero and creates reports/FAILED manifest, not BOM files.\n"
        "KiCad may omit copying failed-job output: consult the recorded command output\n"
        "or reproduce the pipeline from CLI to preserve failure diagnostics.\n"
        "To add to an EXISTING job set, add Special: Execute Command and paste:\n"+command+
        "\nDo not replace your existing job set. Add other manufacturing jobs independently.\n"
        "This bundle uses machine-specific interpreter/plugin/project paths. Regenerate after moving.\n"
        "Review pipeline.json policy/template/variants and all paths before running.\n"
        "No GUI opens in a pipeline. Use the separate GUI launcher for an interactive session.\n"
        "The native job-set host and Windows shell execution require target-system validation.\n")
    return {'WayriCAD_BOM.kicad_jobset':json_bytes(native),'run_wayricad_job.py':bootstrap.encode(),
            'pipeline.json':json_bytes(config),'job-bootstrap.json':json_bytes({'plugin_root':plugin_root,'project':project}),
            'README_JOBSET.txt':readme.encode()}


def jobset_bundle(ws,directory,**kwargs):
    files=jobset_files(ws,directory,**kwargs);stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    return stream.getvalue(),'WayriCAD_Jobset_Bundle.zip','application/zip'
