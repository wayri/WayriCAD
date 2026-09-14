"""Reviewed, create-only native KiCad libraries, with an optional new parts catalog.

Never overwrites a library/table or fabricates a missing symbol, pad or model.
Preview assembles into a private temporary directory; apply reassembles, checks
source/part revisions and native bytes, and publishes into a NEW directory.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import time
import zipfile
from . import partsdb, assetbundle
from .sexpr import parse, quote

SCHEMA='wayricad-library-create-1'
MAX_FILES=30000
MAX_BYTES=512*1024*1024


def validate_request(request):
    allowed={'mode','destination','name','library','ids','all_parts','projects','recursive',
             'all_variants','require_complete','allow_partial_projects','choices','asset_options','actor'}
    if not isinstance(request,dict) or set(request)-allowed:raise ValueError('Unknown library-creation option.')
    r={'mode':'projects','name':'WayriCADParts','require_complete':True,'recursive':False,'all_variants':False,
       'all_parts':False,'allow_partial_projects':False,'actor':'Local user',**request}
    if r['mode'] not in ('empty','projects','catalogue'):raise ValueError('Choose empty, projects or catalogue source.')
    if not isinstance(r['name'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',r['name']):raise ValueError('Library name: letter first, then letters, numbers, underscore or hyphen; maximum 64 characters.')
    if r['name'].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:raise ValueError('Reserved operating-system filename.')
    for k in ('require_complete','recursive','all_variants','all_parts','allow_partial_projects'):
        if type(r[k]) is not bool:raise ValueError(k+' must be boolean.')
    partsdb.text(r['actor'],'actor',200)
    if not r['actor'].strip():raise ValueError('An actor/reason identity is required for catalogue provenance.')
    raw=partsdb.text(r.get('destination',''),'destination',4096)
    d=Path(raw).expanduser()
    if not d.is_absolute() or d.name in ('','.','..'):raise ValueError('Choose an absolute NEW destination directory.')
    if '..' in d.parts:raise ValueError('Parent traversal is not allowed in the destination.')
    if d.is_symlink() or d.exists():raise FileExistsError('Destination already exists. Select a NEW folder; nothing is overwritten.')
    if not d.parent.is_dir():raise ValueError('Destination parent must already exist. Choose a new subfolder within it.')
    # Do not hide persistent user data inside a replaceable plugin package.
    package=Path(__file__).resolve().parent.parent
    resolved=d.resolve()
    if resolved==package or package in resolved.parents:raise ValueError('Choose a data directory outside the plugin installation.')
    r['destination']=str(d)
    if r['mode']=='projects':
        paths=r.get('projects',[])
        if not isinstance(paths,list) or not paths or len(paths)>500:raise ValueError('Choose at least one saved KiCad project or source directory.')
        r['projects']=[str(Path(partsdb.text(x,'project path',4096)).expanduser().absolute()) for x in paths]
    if r['mode']=='catalogue':
        r['library']=str(Path(partsdb.text(r.get('library',''),'catalogue path',4096)).expanduser().absolute())
        ids=r.get('ids',[])
        if not r['all_parts'] and (not isinstance(ids,list) or not ids or len(ids)>10000 or len(set(ids))!=len(ids)):raise ValueError('Select catalogue parts, or explicitly select all parts.')
        if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):raise ValueError('Invalid selected catalogue identities.')
    if not isinstance(r.get('choices',{}),dict):raise ValueError('Asset-set choices must map part IDs to source-set IDs.')
    return r


def _sha(data):return hashlib.sha256(data).hexdigest()
def _json(data):return (json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()


def _table(name,kind,uri):
    root='sym_lib_table' if kind=='symbol' else 'fp_lib_table'
    return f'({root}\n  (version 7)\n  (lib (name {quote(name)}) (type "KiCad") (uri {quote(uri)}) (options "") (descr "Created by WayriCAD BOM Studio"))\n)\n'


def _unpack(raw,stage):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist()
        if len(infos)>MAX_FILES or sum(i.file_size for i in infos)>MAX_BYTES:raise ValueError('Library bundle exceeds creation limits.')
        names=set()
        for info in infos:
            p=Path(info.filename)
            if info.is_dir():continue
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or info.filename in names:raise ValueError('Unsafe or duplicate generated bundle path.')
            names.add(info.filename);out=stage/p;out.parent.mkdir(parents=True,exist_ok=True)
            with out.open('xb') as f:f.write(z.read(info))


@contextmanager
def assemble(request,progress=None,cancel=None):
    r=validate_request(request);dest=Path(r['destination']);name=r['name'];fingerprint={};warnings=[];mapping=[]
    def check():
        if cancel and cancel():raise InterruptedError('Library preparation canceled; destination was not created.')
    with tempfile.TemporaryDirectory(prefix='wayricad-library-review-') as temporary:
        stage=Path(temporary)/'library';stage.mkdir();check()
        if progress:progress(0,3,'Reading source assets; no destination changes.')
        if r['mode'] in ('projects','empty'):
            with partsdb.Library(stage/'catalogue',create=True) as lib:
                if r['mode']=='projects':
                    plan=partsdb.harvest(r['projects'],recursive=r['recursive'],include_variants=r['all_variants'],
                         capture_assets=True,asset_options=r.get('asset_options'),progress=progress,cancel=cancel)
                    if plan['failures'] and not r['allow_partial_projects']:raise ValueError('One or more project scans failed. Review the harvest separately or explicitly permit partial projects. '+str(plan['failures'][:3]))
                    if not plan['parts']:raise ValueError('No usable parts were harvested; choose Empty library to create a blank library explicitly.')
                    partsdb.import_harvest(lib,plan,'IMPORT',r['actor'],r['allow_partial_projects'])
                    ids=[p['id'] for p in plan['parts']];fingerprint={'harvest':plan['fingerprint'],'sources':plan['sources']}
                    warnings.extend({'project_scan':f} for f in plan['failures'])
                    check()
                    bundle=assetbundle.export_library(lib,ids,r.get('choices'),r['require_complete'],
                           (dest/(name+'.3dshapes')).as_posix(),library_name=name)[0]
                    _unpack(bundle,stage)
                info=lib.info();info.pop('path',None)
            # Closed SQLite connection checkpoints its WAL. Backup/copy the whole directory.
            catalog_relative='catalogue'
        else:
            with partsdb.Library(r['library']) as lib:
                ids=[row[0] for row in lib.db.execute('SELECT id FROM parts ORDER BY id')] if r['all_parts'] else r['ids']
                if len(ids)>10000:raise ValueError('Select at most 10,000 parts per native library.')
                fingerprint={'catalogue_id':lib.meta('id'),'epoch':lib.meta('epoch'),
                  'revisions':{i:lib.get(i)['revision'] for i in ids},'path':str(lib.root)}
                bundle=assetbundle.export_library(lib,ids,r.get('choices'),r['require_complete'],
                       (dest/(name+'.3dshapes')).as_posix(),library_name=name)[0]
                _unpack(bundle,stage);info=lib.info()
            catalog_relative=None
        check()
        if r['mode']=='empty':
            (stage/(name+'.kicad_sym')).write_text('(kicad_symbol_lib (version 20241209) (generator "wayricad_bom_studio"))\n',encoding='utf-8')
        (stage/(name+'.pretty')).mkdir(exist_ok=True)
        (stage/(name+'.3dshapes')).mkdir(exist_ok=True)
        if (stage/'catalog-data.json').exists():
            data=json.loads((stage/'catalog-data.json').read_bytes());mapping=data.get('mapping',[]);warnings.extend(data.get('warnings',[]))
        snippets=stage/'table-snippets';snippets.mkdir()
        (snippets/'sym-lib-table').write_text(_table(name,'symbol',(dest/(name+'.kicad_sym')).as_posix()),encoding='utf-8')
        (snippets/'fp-lib-table').write_text(_table(name,'footprint',(dest/(name+'.pretty')).as_posix()),encoding='utf-8')
        # Validate generated definitions through our native reader, not KiCad-host certification.
        parse((stage/(name+'.kicad_sym')).read_text(encoding='utf-8'))
        for p in (stage/(name+'.pretty')).glob('*.kicad_mod'):parse(p.read_text(encoding='utf-8'))
        readme=(f'{name} — WayriCAD native KiCad parts library\n\n'
          f'Symbol library: {dest/(name+".kicad_sym")}\nFootprint library: {dest/(name+".pretty")}\n'
          f'3D originals: {dest/(name+".3dshapes")}\n'
          'Add the symbol and footprint libraries in KiCad Preferences → Manage Symbol/Footprint Libraries, using the SAME nickname: '+name+'.\n'
          'Choose project-local or global scope in KiCad. Existing tables were NOT edited. table-snippets contains entries to merge, not files to replace existing tables with.\n\n'
          'Model paths point to this chosen absolute directory. Moving it requires relinking models or re-creating the library at the new location.\n'
          'Symbols/footprints/models are captured originals or supported normalized definitions, not automatically qualified parts. Missing geometry is never invented. '
          'Empty mode creates valid library containers with no fabricated components. Add symbols/footprints using KiCad editors or harvest real saved projects.\n'
          'This is a create-only snapshot. Later catalogue edits do not silently rewrite this native library. Re-create into a NEW folder to publish a revised snapshot.\n'
          'Back up the complete directory while WayriCAD is closed. The catalogue includes revision/history data; do not put it inside the plugin installation. '
          'Review source redistribution rights before sharing. No native KiCad host loading is claimed by the built-in syntax check.\n')
        (stage/'README.txt').write_text(readme,encoding='utf-8')
        # Exclude timestamps/random catalog IDs from deterministic native-byte review.
        stable={p.relative_to(stage).as_posix():_sha(p.read_bytes()) for p in stage.rglob('*') if p.is_file() and
               ('catalogue' not in p.relative_to(stage).parts) and p.name not in ('catalog-data.json','manifest.json')}
        decision={'request':r,'source':fingerprint,'native_files':stable,'warnings':warnings}
        summary={'schema':SCHEMA,'request':r,'fingerprint':partsdb.digest(decision),'source':fingerprint,
           'native_files':stable,'warnings':warnings,'mapping':mapping,
           'counts':{'symbols':len(mapping),'footprints':len(list((stage/(name+'.pretty')).glob('*.kicad_mod'))),
                     'models':len(list((stage/(name+'.3dshapes')).iterdir())),'catalogue_parts':info['parts']},
           'catalogue_path':str(dest/'catalogue') if catalog_relative else r.get('library'),
           'new_catalogue':bool(catalog_relative),'destination_written':False,
           'notice':'Creates a NEW directory only. Source projects/catalogue and existing KiCad tables stay unchanged. Native geometry hashes are reviewed; audit timestamps/catalogue identifiers are regenerated on apply. No missing asset is fabricated.'}
        manifest={'schema':'wayricad-created-library-1','request':r,'review_fingerprint':summary['fingerprint'],
                  'mapping':mapping,'warnings':warnings,'files':{p.relative_to(stage).as_posix():_sha(p.read_bytes()) for p in stage.rglob('*') if p.is_file() and p.name!='manifest.json'}}
        (stage/'manifest.json').write_bytes(_json(manifest))
        if progress:progress(3,3,'Library preview ready; no destination changes.')
        yield r,stage,summary


def preview(request,progress=None,cancel=None):
    with assemble(request,progress,cancel) as (_,__,plan):return plan


def apply(plan,confirmation):
    if confirmation!='CREATE':raise ValueError('Type CREATE after reviewing the library plan.')
    if not isinstance(plan,dict) or plan.get('schema')!=SCHEMA:raise ValueError('Invalid library review plan.')
    with assemble(plan['request']) as (r,stage,fresh):
        if fresh['fingerprint']!=plan.get('fingerprint'):raise ValueError('Library source, catalogue revision, request or geometry changed. Preview again.')
        dest=Path(r['destination']);created=False
        try:
            dest.mkdir(mode=0o700);created=True  # exclusive reservation; never replace another directory
            for item in stage.iterdir():
                target=dest/item.name
                if item.is_dir():shutil.copytree(item,target)
                else:
                    with item.open('rb') as src,target.open('xb') as out:shutil.copyfileobj(src,out)
            # Verify copied bytes against the final manifest before declaring success.
            manifest=json.loads((dest/'manifest.json').read_bytes())
            for path,h in manifest['files'].items():
                if _sha((dest/path).read_bytes())!=h:raise IOError('Published library verification failed: '+path)
        except BaseException:
            if created:shutil.rmtree(dest,ignore_errors=True)
            raise
        return {**fresh,'destination_written':True,'created_directory':str(dest),'manifest_sha256':_sha((dest/'manifest.json').read_bytes()),
                'symbol_library':str(dest/(r['name']+'.kicad_sym')),'footprint_library':str(dest/(r['name']+'.pretty')),
                'model_directory':str(dest/(r['name']+'.3dshapes')),'registration':'Not performed: add both libraries with the same nickname in KiCad.'}


def dispatch(app,path,p):
    if path=='preview-start':
        from .engineering import Tasks
        if not hasattr(app,'engineering_tasks'):app.engineering_tasks=Tasks()
        request=dict(p.get('request',{}))
        if request.get('mode','projects')=='projects' and not request.get('projects') and app.workspace:
            request['projects']=[str(app.workspace.project.pro_path)]
        validate_request(request)
        return app.engineering_tasks.start(lambda progress,cancel:preview(request,progress,cancel))
    if path in ('task-status','task-cancel'):
        if not hasattr(app,'engineering_tasks'):raise ValueError('Unknown library preparation task.')
        if path=='task-cancel':return app.engineering_tasks.cancel(p['id'])
        result=app.engineering_tasks.get(p['id'],True)
        if result['state']=='ready':
            plan=result['result']
            if plan.get('schema')!=SCHEMA:raise ValueError('This task is not a library creation preview.')
            if not hasattr(app,'library_plans'):app.library_plans={}
            while len(app.library_plans)>=4:app.library_plans.pop(next(iter(app.library_plans)))
            token=secrets.token_hex(16);app.library_plans[token]=(time.time(),plan)
            result['result']={'review_id':token,**plan}
        return result
    if path=='preview':
        request=p.get('request',{})
        if request.get('mode','projects')=='projects' and not request.get('projects') and app.workspace:
            request={**request,'projects':[str(app.workspace.project.pro_path)]}
        plan=preview(request)
        if not hasattr(app,'library_plans'):app.library_plans={}
        app.library_plans={k:v for k,v in app.library_plans.items() if time.time()-v[0]<1800}
        if len(app.library_plans)>=4:app.library_plans.pop(next(iter(app.library_plans)))
        token=secrets.token_hex(16);app.library_plans[token]=(time.time(),plan)
        return {'review_id':token,**plan}
    if path=='apply':
        entry=getattr(app,'library_plans',{}).get(p.get('review_id'))
        if not entry or time.time()-entry[0]>1800:raise ValueError('Library review expired; preview again.')
        result=apply(entry[1],p.get('confirmation'))
        app.library_plans.pop(p['review_id'],None)
        if p.get('attach'):
            app.library_path=result['catalogue_path']
            if app.workspace:app.workspace.commit('Attach created native library catalogue',lambda:app.workspace.state.setdefault('engineering',{}).update(library=app.library_path))
            if p.get('remember'):
                from .engineering import remember_library
                remember_library(app.library_path)
        return result
    raise ValueError('Unknown library creation operation.')
