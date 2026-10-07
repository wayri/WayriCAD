"""Conservative archived-provenance adoption of pre-link insertion batches.

Never establish a link from a matching reference alone. Regenerate an archived
import and prove its complete owned schematic, assets, settings and PCB scope.
"""
from pathlib import Path
import copy
import json
import hashlib
import tempfile
from . import sexpr as sx
from .model import MergeError
from .legacy_sources import restore_source_backup
from .repair import fingerprint, copy_project
from .engine import publish
from .assets import sha256


def _uuid(node):
    return sx.value(node,'uuid') or sx.value(node,'tstamp') or sx.value(node,'id')


def _rewrite(tree, ids, references, new_batch, old_batch,asset_rebases=None):
    from .linked_updates import _rewrite_refs
    sx.remap_identifiers(tree,ids)
    for node in sx.walk(tree):
        for index,value in enumerate(node):
            if isinstance(value,sx.Quoted):
                text=str(value).replace(new_batch,old_batch)
                for before,after in (asset_rebases or {}).items():text=text.replace(before,after)
                if sx.tag(node)=='path' and index==1:
                    text='/'.join(ids.get(part,part) for part in text.split('/'))
                node[index]=sx.q(text)
    _rewrite_refs(tree,references)
    return tree


def _uuid_pairs(expected,actual):
    a=[str(n[1]) for n in sx.walk(expected) if sx.tag(n) in {'uuid','tstamp','id'} and len(n)>1]
    b=[str(n[1]) for n in sx.walk(actual) if sx.tag(n) in {'uuid','tstamp','id'} and len(n)>1]
    if len(a)!=len(b):raise MergeError('Archived import UUID structure differs from destination.')
    mapping={}
    for old,new in zip(a,b):
        if old in mapping and mapping[old]!=new:raise MergeError('Ambiguous archived UUID correspondence.')
        mapping[old]=new
    return mapping


def _sheet_content(tree):
    from .linked_updates import _normal
    value=copy.deepcopy(tree)
    for node in sx.walk(value):
        node[:]=[part for part in node if not (isinstance(part,list) and sx.tag(part)=='page')]
    return _normal(value)


def _proposals(project,manifest):
    root=sx.load(project.with_suffix('.kicad_sch'));known={l['wrapper_uuid'] for l in manifest['links']}
    report_file=project.parent/'insertion-report.json'
    if not report_file.is_file():return []
    report=json.loads(report_file.read_text(encoding='utf-8-sig'));rows=[]
    for source in report.get('sources',[]):
        alias=source.get('alias','')
        wrappers=[s for s in sx.children(root,'sheet') if sx.value(s,'uuid') not in known and
                  sx.prop(s,'Sheetname') and str(sx.prop(s,'Sheetname')[2])==alias]
        if len(wrappers)!=1:continue
        wrapper=wrappers[0];field=sx.prop(wrapper,'Sheetfile')
        if not field:continue
        parts=str(field[2]).replace('\\','/').split('/')
        if len(parts)<4 or parts[0]!='fusion_imports' or parts[2]!='imported':continue
        batch='/'.join(parts[:2]);archive=project.parent/batch/'source-backup.zip'
        rows.append({'id':'legacy:'+sx.value(wrapper,'uuid'),'alias':alias,'batch':batch,
                     'wrapper':wrapper,'source':source,'archive':archive,'include_layout':bool(report.get('include_layout'))})
    return rows


def _prove(project,manifest,row,work,cli_path):
    from . import linked_updates as lu
    from .insertion import preview_import
    from .schematic import discover,new_uuid
    from .board import ITEMS,net_table,net_name,board_bounds
    from .netlist import KiCadCLI
    if row['source'].get('section_origin'):
        raise MergeError('Older partial imports require re-extraction to prove original section provenance.')
    restored=restore_source_backup(row['archive'],row['alias'],work/'archive')
    asset_rebases={hashlib.sha256(str(Path(restored_path).parent).encode()).hexdigest()[:16]:hashlib.sha256(str(Path(original).parent).encode()).hexdigest()[:16]
                   for original,restored_path in restored['restored_paths'].items()}
    def rebase_name(name):
        name=name.replace('\\','/').replace(fresh['batch'],batch)
        for before,after in asset_rebases.items():name=name.replace(before,after)
        return name
    spec=restored['spec'];spec.variant=row['source'].get('variant','<Default>')
    wrapper=row['wrapper'];batch=row['batch'];alias=row['alias'];refs=row['source'].get('reference_map',{})
    if not refs:raise MergeError('Older import lacks its original reference map.')
    cli=KiCadCLI(cli_path)
    xml=cli.export_netlist(project.with_suffix('.kicad_sch'),work/'actual.xml')
    board=sx.load(project.with_suffix('.kicad_pcb')) if project.with_suffix('.kicad_pcb').is_file() else ['kicad_pcb']
    groups=[g for g in sx.children(board,'group') if len(g)>1 and str(g[1])=='Fusion_'+alias] if row['include_layout'] else []
    if row['include_layout'] and len(groups)!=1:raise MergeError('Older routed import lacks one unambiguous ownership group.')
    owned=set()
    if groups:
        byid={_uuid(n):n for n in sx.children(board) if sx.tag(n) in ITEMS}
        def add(ident):
            if ident in owned:return
            if ident not in byid:raise MergeError('Legacy group has a missing member.')
            owned.add(ident)
            if sx.tag(byid[ident])=='group':
                for member in sx.child(byid[ident],'members',[])[1:]:add(str(member))
        add(_uuid(groups[0]))
    libraries={}
    for table in ('fp-lib-table','sym-lib-table'):
        tree=sx.load(project.parent/table) if (project.parent/table).is_file() else []
        libraries[table]=[sx.value(n,'name') for n in sx.children(tree,'lib')
                          if sx.value(n,'uri').startswith('${KIPRJMOD}/'+batch+'/') and sx.value(n,'name').startswith('Fusion_'+alias)]
    data=json.loads(project.read_text(encoding='utf-8-sig'))
    skeleton={'id':row['id'],'alias':alias,'wrapper_uuid':sx.value(wrapper,'uuid'),'pcb_item_ids':list(owned),
              'library_names':libraries,'class_names':[c['name'] for c in data.get('net_settings',{}).get('classes',[]) if c.get('name','').startswith(alias+'__')],
              'net_names':sorted({net_name(n,net_table(board)) for ident,n in ((_uuid(n),n) for n in sx.children(board)) if ident in owned and net_name(n,net_table(board))}
                                 |{net_name(p,net_table(board)) for n in sx.children(board,'footprint') if _uuid(n) in owned for p in sx.children(n,'pad') if net_name(p,net_table(board))})}
    skeleton['net_names']=sorted(set(skeleton['net_names'])|{name for name,pins in xml.nets.items() if any(ref in set(refs.values()) for ref,pin in pins)})
    stripped=lu._strip_links(project,[skeleton],work/'stripped')
    if row['include_layout']:
        source=discover(spec,new_uuid());source.board=sx.load(source.pcb_file)
        bounds=board_bounds(source.board);translation=row['source'].get('translation_mm')
        if not translation or len(translation)!=2:raise MergeError('Legacy layout translation is missing.')
        spec.x_mm=bounds[0]+translation[0];spec.y_mm=bounds[1]+translation[1]
    preview_import(str(stripped),[spec],row['include_layout'],work/'expected',cli_path)
    fresh_project=work/'expected'/project.name
    _,fresh_manifest=lu._load(fresh_project)
    fresh=next(l for l in fresh_manifest['links'] if l['alias']==alias)
    fresh_wrapper=next(s for s in sx.children(sx.load(fresh_project.with_suffix('.kicad_sch')),'sheet') if sx.value(s,'uuid')==fresh['wrapper_uuid'])
    refs_map={value:refs[key] for key,value in fresh['reference_map'].items() if key in refs}
    if set(refs)!=set(fresh['reference_map']):raise MergeError('Archived symbol reference inventory differs.')
    expected_xml=KiCadCLI(cli_path).export_netlist(fresh_project.with_suffix('.kicad_sch'),work/'expected.xml')
    net_names={}
    for name,pins in expected_xml.nets.items():
        if not any(ref in refs_map for ref,pin in pins):continue
        transformed={(refs_map.get(ref,ref),pin) for ref,pin in pins}
        matches=[actual_name for actual_name,endpoints in xml.nets.items() if endpoints==transformed]
        if len(matches)!=1:raise MergeError('Legacy electrical pin partitions differ from archived source.')
        net_names[name]=matches[0]
    ids={fresh['wrapper_uuid']:skeleton['wrapper_uuid']}
    ids.update(_uuid_pairs(fresh_wrapper,wrapper))
    old_files=[];pairs=[]
    for name in fresh['sheet_files']:
        old_name=name.replace(fresh['batch'],batch)
        if not (project.parent/old_name).is_file():raise MergeError('Legacy imported schematic file is missing.')
        expected=sx.load(work/'expected'/name);actual=sx.load(project.parent/old_name)
        for old,new in _uuid_pairs(expected,actual).items():
            if old in ids and ids[old]!=new:raise MergeError('Ambiguous cross-sheet UUID mapping.')
            ids[old]=new
        pairs.append((expected,actual));old_files.append(old_name)
    for expected,actual in pairs:
        _rewrite(expected,ids,refs_map,fresh['batch'],batch,asset_rebases)
        if _sheet_content(expected)!=_sheet_content(actual):raise MergeError('Imported schematic differs from verified archived source.')
    expected_wrapper=_rewrite(copy.deepcopy(fresh_wrapper),ids,refs_map,fresh['batch'],batch)
    actual_wrapper=copy.deepcopy(wrapper)
    # Normalize the rigid wrapper translation, retaining relative pin/text
    # placement. Page allocation belongs to the destination.
    expected_at=sx.child(expected_wrapper,'at');actual_at=sx.child(actual_wrapper,'at')
    dx=float(actual_at[1])-float(expected_at[1]);dy=float(actual_at[2])-float(expected_at[2])
    for node in sx.walk(expected_wrapper):
        if sx.tag(node)=='at' and len(node)>2:node[1]=str(float(node[1])+dx);node[2]=str(float(node[2])+dy)
    def wrapper_interface(tree):
        tree=copy.deepcopy(tree)
        for node in sx.walk(tree):
            node[:]=[part for part in node if not (isinstance(part,list) and sx.tag(part)=='page')]
        return lu._normal(tree)
    if wrapper_interface(expected_wrapper)!=wrapper_interface(actual_wrapper):raise MergeError('Legacy wrapper interface changed.')
    # Owned PCB nodes must match after UUID, reference, and numeric-net rebasing.
    if row['include_layout']:
        fresh_board=sx.load(fresh_project.with_suffix('.kicad_pcb'));fresh_table=net_table(fresh_board);old_table=net_table(board)
        actual_nodes=[n for n in sx.children(board) if _uuid(n) in owned];available=list(actual_nodes)
        def clean(node,table,transform=False):
            value=copy.deepcopy(node)
            if transform:value=_rewrite(value,ids,refs_map,fresh['batch'],batch,asset_rebases)
            for part in sx.walk(value):
                if sx.child(part,'net') is not None:
                    name=net_name(part,table);sx.put(part,'net',sx.q(net_names.get(name,name) if transform else name))
                part[:]=[n for n in part if not (isinstance(n,list) and sx.tag(n) in {'uuid','tstamp','id','members'})]
            return lu._normal(value)
        for expected in [n for n in sx.children(fresh_board) if _uuid(n) in set(fresh['pcb_item_ids'])]:
            matches=[n for n in available if clean(expected,fresh_table,True)==clean(n,old_table)]
            if len(matches)!=1:raise MergeError('Legacy '+sx.tag(expected)+' has changed or has ambiguous item correspondence.')
            if len([n for n in sx.children(board) if sx.tag(n) in ITEMS and clean(expected,fresh_table,True)==clean(n,old_table)])!=1:
                raise MergeError('Legacy layout matches an unrelated destination item; ownership is ambiguous.')
            actual=matches[0];available.remove(actual);ids.update(_uuid_pairs(expected,actual))
        if available:raise MergeError('Legacy layout contains unproven extra owned items.')
        old_nodes={_uuid(n):n for n in actual_nodes}
        for group in sx.children(fresh_board,'group'):
            if _uuid(group) not in fresh['pcb_item_ids']:continue
            actual=old_nodes[ids[_uuid(group)]]
            expected_members={ids.get(str(v),str(v)) for v in sx.child(group,'members',[])[1:]}
            if expected_members!=set(map(str,sx.child(actual,'members',[])[1:])):
                raise MergeError('Legacy group membership differs from archived import.')
    link=copy.deepcopy(fresh);link['id']=row['id'];link['wrapper_uuid']=skeleton['wrapper_uuid'];link['wrapper_node']=copy.deepcopy(wrapper)
    link['batch']=batch;link['sheet_files']=old_files;link['reference_map']=dict(refs)
    link['symbol_refs']={key:refs_map.get(value,value) for key,value in fresh['symbol_refs'].items()}
    link['schematic_ids']={path:{key:ids.get(value,value) for key,value in mapping.items()} for path,mapping in fresh['schematic_ids'].items()}
    link['pcb_uuid_map']={key:ids.get(value,value) for key,value in fresh['pcb_uuid_map'].items()}
    link['pcb_item_ids']=list(owned);link['outer_group_uuid']=_uuid(groups[0]) if groups else None
    link['net_names']=[net_names.get(name,name) for name in fresh['net_names']]
    link['asset_files']=[rebase_name(name) for name in fresh['asset_files']]
    link['source_spec']['project']=restored['original_project'];link['source_spec']['path_remaps']={};link['source_spec']['x_mm']=link['source_spec']['y_mm']=None
    link['source_baseline']['hashes']=restored['original_filehashes'];link['source_baseline']['spec']=copy.deepcopy(link['source_spec'])
    # Compare the complete expected scope, allowing only known remapping and the
    # legacy wrapper's placement. Native connectivity must also match exactly.
    linked_refs=set(refs.values())
    expected_partitions={frozenset((refs_map.get(ref,ref),pin) for ref,pin in pins) for pins in expected_xml.nets.values()
                         if any(ref in set(fresh['reference_map'].values()) for ref,pin in pins)}
    actual_partitions={frozenset(pins) for pins in xml.nets.values() if any(ref in linked_refs for ref,pin in pins)}
    if expected_partitions!=actual_partitions:raise MergeError('Legacy electrical pin partitions differ from archived source.')
    link['target_baseline']=lu._scope(project,link,xml)
    expected_scope=lu._scope(fresh_project,fresh,expected_xml)
    for name in ('assets','tables','settings'):
        a=expected_scope[name];b=link['target_baseline'][name]
        if name=='assets':
            for asset in fresh['asset_files']:
                expected_file=fresh_project.parent/asset;actual_file=project.parent/rebase_name(asset)
                if not actual_file.is_file():raise MergeError('Legacy dependency is missing: '+rebase_name(asset))
                if expected_file.suffix in {'.kicad_mod','.kicad_sym'}:
                    expected_asset=sx.load(expected_file);actual_asset=sx.load(actual_file)
                    expected_asset=_rewrite(expected_asset,{}, {},fresh['batch'],batch,asset_rebases)
                    if lu._normal(expected_asset)!=lu._normal(actual_asset):raise MergeError('Legacy library content differs from archived import.')
                elif sha256(expected_file)!=sha256(actual_file):raise MergeError('Legacy dependency bytes differ from archived import.')
            continue
        elif name=='tables':
            # Table URI changes are proved separately, without opaque hashes.
            for table,names in libraries.items():
                expected_tree=sx.load(fresh_project.parent/table);actual_tree=sx.load(project.parent/table)
                for nickname in names:
                    e=next(n for n in sx.children(expected_tree,'lib') if sx.value(n,'name')==nickname)
                    actual=next(n for n in sx.children(actual_tree,'lib') if sx.value(n,'name')==nickname)
                    if lu._normal(_rewrite(copy.deepcopy(e),{}, {},fresh['batch'],batch))!=lu._normal(actual):raise MergeError('Legacy library table was edited.')
            continue
        elif name=='settings':
            encoded=json.dumps(a)
            for old,new in net_names.items():encoded=encoded.replace(json.dumps(old),json.dumps(new))
            a=json.loads(encoded)
        if a!=b:raise MergeError('Legacy '+name+' differs from archived import.')
    # Scoped endpoints cannot attach outside the imported design.
    if lu._conflicts(project,link,xml):raise MergeError('Legacy block has destination boundary connections.')
    return link,restored


def candidates(project,manifest,cli_path=''):
    rows=[]
    for row in _proposals(Path(project),manifest):
        result={'id':row['id'],'alias':row['alias'],'verified':False,'automatic':False,'method':'Archived regeneration and owned-scope proof'}
        try:
            with tempfile.TemporaryDirectory(prefix='fusion-legacy-proof-') as folder:
                link,restored=_prove(Path(project),manifest,row,Path(folder),cli_path)
            result.update(verified=True,source_project=restored['original_project'])
        except Exception as error:result['reason']=str(error)
        rows.append(result)
    return rows


def preview_adopt(target,link_ids,candidate_directory,cli_path=''):
    from . import linked_updates as lu
    project,manifest=lu._load(target);destination=Path(candidate_directory).resolve()
    if destination.exists() or destination==project.parent or project.parent in destination.parents:
        raise MergeError('Choose a new candidate folder outside the target project.')
    proposals={row['id']:row for row in _proposals(project,manifest)}
    if not link_ids or len(set(link_ids))!=len(link_ids) or any(ident not in proposals for ident in link_ids):raise MergeError('Select existing, unique legacy proposals.')
    if len(manifest['links'])+len(link_ids)>100:raise MergeError('A maximum of 100 linked design instances is supported.')
    target_hashes=fingerprint(project.parent);dependencies=[]
    with tempfile.TemporaryDirectory(prefix='fusion-adopt-') as folder:
        work=Path(folder)
        for index,ident in enumerate(link_ids):
            proof=work/str(index);proof.mkdir()
            link,restored=_prove(project,manifest,proposals[ident],proof,cli_path)
            manifest['links'].append(link)
            dependencies.append({'original_path':str(proposals[ident]['archive']),'sha256':sha256(proposals[ident]['archive'])})
        candidate=work/'candidate';copy_project(project.parent,candidate)
        manifest['target_root_uuid']=sx.value(sx.load(project.with_suffix('.kicad_sch')),'uuid');lu._write(candidate,manifest)
        report={'plugin_version':'0.9.5','linked_adoption':True,'adopted_links':link_ids,'geometry_unchanged':True,'major_changes':0,'manufacturing_approved':False}
        (candidate/'linked-adoption-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if fingerprint(project.parent)!=target_hashes:raise MergeError('Destination changed during legacy proof.')
        publish(candidate,destination)
    return {'target_project':str(project),'target_hashes':target_hashes,'source_hashes':[],'source_file_hashes':dependencies,
            'candidate_directory':str(destination),'candidate_hashes':fingerprint(destination),'report':report}
