"""Read-only dependency audit with explicit, reviewable local path suggestions."""
from pathlib import Path
from collections import defaultdict
import copy
import json
import tempfile
import shutil
from dataclasses import asdict

from . import sexpr as sx
from .schematic import discover, new_uuid
from .board import prepare_board
from .assets import prepare_assets
from .repair import project_files,copy_project,fingerprint
from .model import SourceSpec,MergeError,validate_source_aliases


def suggest_paths(source, unresolved):
    files = project_files(source.project_file.parent)
    names = defaultdict(list)
    directories = defaultdict(set)
    for p in files:
        names[p.name.casefold()].append(p)
        if p.suffix.casefold() == '.kicad_mod': directories[p.parent].add(p.stem)
    wanted = defaultdict(set)
    for tree in [source.board, *[s.tree for s in source.sheets], *source.libraries.values()]:
        for node in sx.walk(tree):
            identifier = str(node[1]) if sx.tag(node)=='footprint' and len(node)>1 else sx.propval(node,'Footprint')
            if identifier and ':' in identifier:
                nick,item = identifier.split(':',1); wanted[nick].add(item)
    suggestions = []
    seen = set()
    for item in unresolved:
        raw,kind = item['reference'],item['kind']
        if kind == 'footprint library':
            choices = [p for p, members in directories.items() if wanted.get(raw) and wanted[raw].issubset(members)]
            action = 'register_footprint_library'
        else:
            choices = names.get(Path(raw.replace('\\','/')).name.casefold(), [])
            action = 'path_remap'
        # Hash-identical files may be duplicates; provenance remains explicit.
        choices = sorted(set(choices))
        key = (action,raw)
        if len(choices)==1 and key not in seen:
            seen.add(key)
            suggestions.append({'source':source.alias,'action':action,'reference':raw,'path':str(choices[0])})
    return suggestions


def audit_dependencies(specs, log=lambda message:None):
    sources=[]
    for spec in specs:
        source=discover(spec,new_uuid(),log); prepare_board(source); sources.append(source)
    # Keep unrewritten source trees to inspect registered names and identifiers.
    originals=copy.deepcopy(sources)
    with tempfile.TemporaryDirectory(prefix='fusion-dependency-audit-') as folder:
        prepare_assets(sources,Path(folder),log,strict=False)
    unresolved=[item for source in sources for item in source.asset_manifest if item['status']=='unresolved']
    suggestions=[]
    for source in originals:
        suggestions.extend(suggest_paths(source,[i for i in unresolved if i['source']==source.alias]))
    return {'unresolved':unresolved,'suggestions':suggestions,
            'originals_modified':False,'strict_merge_checks_disabled':False}


def preview_dependencies(specs,log=lambda message:None):
    validate_source_aliases(specs)
    hashes={s.alias:fingerprint(Path(s.project).with_suffix('.kicad_pro').resolve().parent) for s in specs}
    result=audit_dependencies(specs,log)
    if any(hashes[s.alias]!=fingerprint(Path(s.project).with_suffix('.kicad_pro').resolve().parent) for s in specs):
        raise MergeError('A source changed during dependency review. Preview again.')
    return {'specs':[asdict(s) for s in specs],'hashes':hashes,'report':result}


def apply_dependencies(plan,destination):
    from .engine import publish
    specs=[SourceSpec(**s) for s in plan['specs']]
    validate_source_aliases(specs)
    dest=Path(destination).resolve()
    if dest.exists() or not dest.parent.is_dir():
        raise MergeError('Choose a new dependency-copy folder inside an existing parent.')
    for spec in specs:
        root=Path(spec.project).with_suffix('.kicad_pro').resolve().parent
        if root==dest or root in dest.parents:
            raise MergeError('Dependency-copy output must be outside every source project.')
        if fingerprint(root)!=plan['hashes'][spec.alias]:
            raise MergeError('Source changed after dependency preview. Preview again.')
    stage=Path(tempfile.mkdtemp(prefix='.fusion-paths-',dir=dest.parent))
    result=[]
    try:
        for spec in specs:
            root=Path(spec.project).with_suffix('.kicad_pro').resolve().parent
            folder=stage/spec.alias
            copy_project(root,folder)
            if fingerprint(folder)!=plan['hashes'][spec.alias]:raise MergeError('Copied source differs from the dependency review snapshot.')
            data=asdict(spec); data['project']=str(dest/spec.alias/Path(spec.project).with_suffix('.kicad_pro').name)
            tablepath=folder/'fp-lib-table'
            table=sx.load(tablepath) if tablepath.is_file() else ['fp_lib_table',['version','7']]
            for suggestion in plan['report']['suggestions']:
                if suggestion['source']!=spec.alias:continue
                path=Path(suggestion['path']).resolve()
                if root not in path.parents:raise MergeError('Dependency suggestion leaves the reviewed source folder.')
                relative=path.relative_to(root)
                if suggestion['action']=='path_remap':
                    data['path_remaps'][suggestion['reference']]=str(dest/spec.alias/relative)
                elif suggestion['action']=='register_footprint_library':
                    for entry in list(sx.children(table,'lib')):
                        if sx.value(entry,'name')==suggestion['reference']:table.remove(entry)
                    table.append(['lib',['name',sx.q(suggestion['reference'])],['type',sx.q('KiCad')],
                                  ['uri',sx.q('${KIPRJMOD}/'+relative.as_posix())],['options',sx.q('')],['descr',sx.q('Reviewed local dependency registration')]])
                else:raise MergeError('Unsupported dependency suggestion.')
            sx.save(tablepath,table)
            result.append(SourceSpec(**data))
        for spec in specs:
            if fingerprint(Path(spec.project).with_suffix('.kicad_pro').resolve().parent)!=plan['hashes'][spec.alias]:
                raise MergeError('Source changed while dependency copies were staged.')
        (stage/'dependency-review.json').write_text(json.dumps(plan['report'],indent=2)+'\n',encoding='utf-8')
        publish(stage,dest)
        return result
    finally:shutil.rmtree(stage,ignore_errors=True)
