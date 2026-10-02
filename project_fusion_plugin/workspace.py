"""Universal workspace orchestration; existing native engines remain authoritative."""
from pathlib import Path
import copy,json,tempfile
from .model import MergeError,MAX_INSTANCES,validate_source_aliases
from .repair import fingerprint
from .schematic import new_uuid

def materialize_sources(specs,include_layout,parent,cli_path=''):
    from .source_selection import materialize_selection
    folder=Path(parent)/('FusionSourceCopies-'+new_uuid()[:8])
    results=[];originals=[]
    for index,spec in enumerate(specs):
        root=Path(spec.project).resolve().parent;originals.append({'root':str(root),'hashes':fingerprint(root)})
        request=copy.deepcopy(spec.selection or {'whole_project':True,'sheet_paths':[],'max_depth':None})
        request['include_layout']=bool(include_layout)
        prepared=materialize_selection(spec,request,folder/f'instance_{index+1:03d}',cli_path)
        if len(prepared)==1:prepared[0].sheet_position_mm=copy.deepcopy(spec.sheet_position_mm)
        results.extend(prepared)
    if not 1<=len(results)<=MAX_INSTANCES:raise MergeError('Selected sheets exceed the 100-instance limit.')
    validate_source_aliases(results)
    for original in originals:
        if fingerprint(Path(original['root']))!=original['hashes']:raise MergeError('Original source changed during selection preparation.')
    return results,originals

def check_originals(plan):
    for record in plan.get('selection_originals',[]):
        if fingerprint(Path(record['root']))!=record['hashes']:raise MergeError('Original source changed since review; preview again.')

def preview_new_schematic(sources,destination,name,cli_path='',gap_mm=10,copy_assets=True):
    from .insertion import preview_import
    blank=Path(destination).parent/('FusionEmptyTarget-'+new_uuid()[:8]);blank.mkdir()
    project=blank/(name+'.kicad_pro');project.write_text(json.dumps({'meta':{'filename':project.name,'version':1}}),encoding='utf-8')
    project.with_suffix('.kicad_sch').write_text('(kicad_sch (version 20250114) (generator "eeschema") (uuid '+new_uuid()+') (paper "A4") (lib_symbols) (sheet_instances (path "/" (page "1"))))',encoding='utf-8')
    plan=preview_import(str(project),sources,False,destination,cli_path,gap_mm,copy_assets=copy_assets)
    plan['new_schematic']=True
    return plan

def publish_new_schematic(plan,destination,name):
    from .engine import publish
    from .repair import copy_project
    from . import sexpr as sx
    check_originals(plan)
    candidate=Path(plan['candidate_directory'])
    if fingerprint(candidate)!=plan['candidate_hashes']:raise MergeError('Review candidate changed; preview again.')
    with tempfile.TemporaryDirectory(prefix='fusion-new-',dir=Path(destination).parent) as temporary:
        stage=Path(temporary)/'project';copy_project(candidate,stage)
        if name!=Path(plan['target_project']).stem:raise MergeError('Output name changed since preview; preview again.')
        if fingerprint(stage)!=plan['candidate_hashes']:raise MergeError('Copied review candidate differs from its verified snapshot.')
        check_originals(plan);publish(stage,Path(destination))
    return {'project':str(Path(destination)/(name+'.kicad_pro')),'schematic_only':True,'native_netlist_verified':True}
