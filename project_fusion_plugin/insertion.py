"""Reviewed offline insertion into a saved existing project.

The target is preserved as the owning root. Incoming designs are electrically
isolated and receive fresh identifiers, references and portable asset namespaces.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import copy
import json
import math
import os
import shutil
import tempfile
import zipfile

from . import sexpr as sx
from .model import MergeError,SourceSpec,validate_source_aliases
from .schematic import discover,new_uuid,natural_ref,transform_schematics,make_parent
from .repair import fingerprint,copy_project,project_files
from .assets import prepare_assets,audit_assets,sha256
from .netlist import KiCadCLI,compare_netlists
from .board import prepare_board,compose,verify_board,geometry_signature,ITEMS,net_name,net_table,board_bounds,fp_reference
from .layers import copper_sequence,plan_layers
from .engine import export_selected_netlist,build_project,publish,_snapshot,_assert_sources_unchanged
from .sections import _geometry_signature
from .variants import effective_board_flags


def _json(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def _normalize(node):
    if isinstance(node,list):return tuple(_normalize(x) for x in node)
    if isinstance(node,sx.Quoted):return str(node)
    try:return round(float(node),7)
    except (ValueError,TypeError):return str(node)


def _reference_maps(target,incoming,include_layout):
    used={r.old_ref for r in target.symbols}
    if target.board:
        used.update(fp_reference(fp) for fp in sx.children(target.board,'footprint'))
    counters={}
    for ref in used:
        try:prefix,number=natural_ref(ref)
        except MergeError:continue
        counters[prefix]=max(counters.get(prefix,0),number)
    target.ref_map={r.old_ref:r.old_ref for r in target.symbols}
    for source in incoming:
        references={r.old_ref for r in source.symbols}
        if include_layout:references.update(source.board_ref_map)
        for ref in sorted(references,key=natural_ref):
            prefix,_=natural_ref(ref);number=counters.get(prefix,0)+1
            candidate=prefix+(f'{number:04d}' if prefix.startswith('#') else str(number))
            while candidate in used:
                number+=1;candidate=prefix+(f'{number:04d}' if prefix.startswith('#') else str(number))
            source.ref_map[ref]=candidate;used.add(candidate);counters[prefix]=number
        for record in source.symbols:record.new_ref=source.ref_map[record.old_ref]


def _prefix_assets(tree,prefix):
    for node in sx.walk(tree):
        for index,value in enumerate(node):
            if isinstance(value,sx.Quoted) and str(value).startswith('${KIPRJMOD}/'):
                if not str(value).startswith('${KIPRJMOD}/'+prefix+'/'):
                    node[index]=sx.q('${KIPRJMOD}/'+prefix+'/'+str(value)[len('${KIPRJMOD}/'):])


def _combine_table(candidate,assets,name,prefix):
    existing=sx.load(candidate/name) if (candidate/name).is_file() else [name.replace('-','_')]
    new=sx.load(assets/name);_prefix_assets(new,prefix)
    names={sx.value(n,'name').casefold() for n in sx.children(existing,'lib')}
    for entry in sx.children(new,'lib'):
        nickname=sx.value(entry,'name').casefold()
        if nickname in names:raise MergeError('Incoming library namespace collides with a target library: '+nickname+'. Choose a different source alias.')
        existing.append(entry);names.add(nickname)
    sx.save(candidate/name,existing)


def _target_integrity(original,updated):
    before={sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id'):n
            for n in sx.children(original) if sx.tag(n) in ITEMS}
    after={sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id'):n
           for n in sx.children(updated) if sx.tag(n) in ITEMS}
    for ident,item in before.items():
        if ident not in after:raise MergeError('Insertion removed an existing target PCB object: '+ident)
        final=after[ident]
        if _geometry_signature(item)!=_geometry_signature(final):
            raise MergeError('Insertion changed existing target PCB geometry: '+ident+' ('+sx.tag(item)+'). Changed fields: '+repr([v for v in _geometry_signature(item) if v not in _geometry_signature(final)])[:1000])
        if sx.tag(item)=='footprint':
            if any(sx.propval(item,key)!=sx.propval(final,key) for key in ('Reference','Value')) or sx.value(item,'path')!=sx.value(final,'path'):
                raise MergeError('Insertion changed an existing target footprint identity.')
            oldpads={str(p[1]):net_name(p,net_table(original)) for p in sx.children(item,'pad')}
            newpads={str(p[1]):net_name(p,net_table(updated)) for p in sx.children(final,'pad')}
            if oldpads!=newpads:raise MergeError('Insertion changed an existing target pad net.')
    for key in ('layers','setup'):
        if _normalize(sx.child(original,key))!=_normalize(sx.child(updated,key)):
            raise MergeError('Insertion changed target PCB '+key+' settings.')


def _append_board(target,incoming_board,merged):
    table=net_table(target);known_names=set(table.values())
    direct=any(sx.tag(n)=='net' and len(n)==2 and isinstance(n[1],sx.Quoted) for n in sx.walk(target))
    codes={name:code for code,name in table.items()}
    next_code=max([int(c) for c in table if str(c).isdigit()]+[0])+1
    for name in sorted(merged.nets):
        if name in known_names:continue
        codes[name]=str(next_code);next_code+=1
        if not direct:target.append(['net',codes[name],sx.q(name)])
    incoming_table=net_table(incoming_board)
    from .board import merge_embedded
    merge_embedded(target,incoming_board)
    for item in sx.children(incoming_board):
        if sx.tag(item) not in ITEMS:continue
        item=copy.deepcopy(item)
        for node in sx.walk(item):
            net=sx.child(node,'net')
            if net is not None:
                name=net_name(node,incoming_table)
                if direct:net[:]=['net',sx.q(name)]
                elif len(net)>2:net[:]=['net',codes.get(name,'0'),sx.q(name)]
                else:net[:]=['net',codes.get(name,'0')]
            if sx.tag(node)=='layer' and len(node)>1 and str(node[1])=='Edge.Cuts':node[1]=sx.q('Dwgs.User')
        target.append(item)
    identifiers=sx.declared_uuids(target)
    if len(set(identifiers))!=len(identifiers):raise MergeError('PCB identifier collision; nothing published.')
    return target


def _saved_project(path,require_board):
    path=Path(path).expanduser().resolve()
    if path.suffix.lower() not in {'.kicad_pro','.kicad_sch','.kicad_pcb'}:raise MergeError('Select an existing KiCad project or root schematic.')
    project=path.with_suffix('.kicad_pro')
    for suffix in ('.kicad_pro','.kicad_sch')+(('.kicad_pcb',) if require_board else ()):
        if not path.with_suffix(suffix).is_file():raise MergeError('Missing saved target project member: '+str(path.with_suffix(suffix)))
    return project


def preview_import(target_path,sources,include_layout,candidate_directory,cli_path='',gap_mm=10.0,copy_assets=True):
    if not isinstance(include_layout,bool):raise MergeError('Choose schematic-only or schematic plus PCB explicitly.')
    if not 1<=len(sources)<=100:raise MergeError('Insert between 1 and 100 incoming design instances.')
    validate_source_aliases(sources)
    if not math.isfinite(float(gap_mm)) or not 0<=float(gap_mm)<=1000:raise MergeError('Placement gap must be 0–1000 mm.')
    target_project=_saved_project(target_path,include_layout);target_root=target_project.parent
    destination=Path(candidate_directory).expanduser().resolve()
    roots=[target_root,*[Path(spec.project).resolve().parent for spec in sources]]
    if destination.exists() or any(destination==root or root in destination.parents for root in roots):
        raise MergeError('Choose a new candidate folder outside every original project.')
    target_hashes=fingerprint(target_root)
    source_hashes=[{'root':str(root),'hashes':fingerprint(root)} for root in roots[1:]]
    cli=KiCadCLI(cli_path);destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-insert-',dir=destination.parent) as folder:
        work=Path(folder);candidate=work/'candidate';copy_project(target_root,candidate)
        if fingerprint(candidate)!=target_hashes:raise MergeError('Target changed while copying; preview again.')
        target_alias='Target_'+new_uuid().replace('-','')[:12]
        while target_alias.casefold() in {s.alias.casefold() for s in sources}:target_alias='Target_'+new_uuid().replace('-','')[:12]
        target=discover(SourceSpec(str(target_project),target_alias,variant='<Default>'),new_uuid(),require_board=include_layout)
        if any(target_root!=sheet.source_path.parent and target_root not in sheet.source_path.parents for sheet in target.sheets):
            raise MergeError('External target schematic sheets must be placed inside the project before insertion.')
        root_uuid=target.old_root_uuid
        target.board=sx.load(target.pcb_file) if target.pcb_file.is_file() else None
        incoming=[]
        for spec in sources:
            source=discover(spec,root_uuid,require_board=include_layout)
            if include_layout:prepare_board(source)
            else:source.board=['kicad_pcb']
            source.class_map={c['name']:source.alias+'__'+c['name'] for c in source.project.get('net_settings',{}).get('classes',[]) if 'name' in c}
            incoming.append(source)
        _reference_maps(target,incoming,include_layout)
        from .bom_fields import inventory,grouped_bom,export_csv
        bom_input=inventory([target,*incoming])
        # Use the copied target for the native base-state authority.
        target.xml=cli.export_netlist(candidate/target.schematic_file.name,work/'target.xml')
        for source in incoming:source.xml=export_selected_netlist(source,cli,work/(source.alias+'.xml'))
        batch='fusion_imports/'+new_uuid();assets=candidate/batch;assets.mkdir(parents=True)
        prepare_assets(incoming,assets,lambda _:None,strict=True,copy_assets=copy_assets)
        page=max([int(sx.value(n,'page','1')) for sheet in target.sheets for n in sx.walk(sheet.tree) if sx.tag(n)=='path' and sx.child(n,'page') is not None]+[1])+1
        for source in incoming:page=transform_schematics(source,assets,target_project.stem,page)
        # All generated local references resolve against the owning target root.
        for path in assets.rglob('*'):
            if path.is_file() and (path.suffix in {'.kicad_sch','.kicad_sym','.kicad_mod'} or path.name in {'fp-lib-table','sym-lib-table'}):
                tree=sx.load(path);_prefix_assets(tree,batch);sx.save(path,tree)
        for source in incoming:_prefix_assets(source.board,batch)
        _combine_table(candidate,assets,'fp-lib-table',batch);_combine_table(candidate,assets,'sym-lib-table',batch)
        parent=make_parent(incoming,target_project.stem,root_uuid)
        target_tree=sx.load(candidate/target.schematic_file.name)
        existing_max_x=max([float(n[1]) for node in sx.walk(target_tree) for n in sx.children(node,'at') if len(n)>2]+[0])+25.4
        for sheet in sx.children(parent,'sheet'):
            alias=sx.propval(sheet,'Sheetname')
            explicit=next((bool(getattr(s.spec,'sheet_position_mm',[])) for s in incoming if s.alias==alias),False)
            for node in sx.walk(sheet):
                if not explicit and sx.tag(node)=='at' and len(node)>2:node[1]=str(float(node[1])+existing_max_x)
            field=sx.prop(sheet,'Sheetfile');field[2]=sx.q(batch+'/'+str(field[2]))
            target_tree.append(sheet)
        sx.save(candidate/target.schematic_file.name,target_tree)
        project=copy.deepcopy(target.project)
        temporary=build_project(incoming,target_project.stem)
        for key,value in temporary.get('text_variables',{}).items():
            if key in project.get('text_variables',{}):raise MergeError('Incoming project variable collides with target: '+key)
            if isinstance(value,str):value=value.replace('${KIPRJMOD}/','${KIPRJMOD}/'+batch+'/')
            project.setdefault('text_variables',{})[key]=value
        _json(candidate/target_project.name,project)
        merged=cli.export_netlist(candidate/target.schematic_file.name,work/'combined.xml')
        connectivity=compare_netlists([target,*incoming],merged)
        unplaced=sum(len({r.old_ref for r in source.symbols if r.old_ref in source.xml.components
                          and effective_board_flags(r)['on_board']=='yes' and sx.propval(r.node,'Footprint')})
                     for source in incoming) if not include_layout else 0
        drc=None
        imported=None
        if include_layout:
            target_layers=copper_sequence(target.board)
            if any(copper_sequence(source.board)!=target_layers for source in incoming):
                raise MergeError('Insertion preserves the target stackup. Incoming routed boards must have the same copper-layer count; use a separately reviewed layer conversion first.')
            plan_layers(incoming,False)
            target_box=board_bounds(target.board);next_x=target_box[2]+float(gap_mm)
            for source in incoming:
                if (source.spec.x_mm is None)!=(source.spec.y_mm is None):raise MergeError('Specify both X and Y placement coordinates or neither.')
                x=next_x if source.spec.x_mm is None else float(source.spec.x_mm)
                y=target_box[1] if source.spec.y_mm is None else float(source.spec.y_mm)
                if not all(math.isfinite(v) and abs(v)<=10000 for v in (x,y)):raise MergeError('Placement must be finite and within ±10000 mm.')
                # KiCad serializes positions on its 1 nm grid. Quantize the rigid
                # translation before composing every item, as ordinary merge does.
                source.translation=(round(x-source.bbox[0],6),round(y-source.bbox[1],6));next_x=x+(source.bbox[2]-source.bbox[0])+float(gap_mm)
            imported=compose(incoming,merged,'preserve',0)
            verify_board(imported,incoming,merged)
            result=_append_board(copy.deepcopy(target.board),imported,merged)
            geometry_before=geometry_signature(result)
            other_before={sx.value(n,'uuid') or sx.value(n,'tstamp'):_geometry_signature(n) for n in sx.children(result)
                          if sx.tag(n) in ITEMS-{'group','footprint','segment','arc','via'}}
            groups_before={sx.value(g,'uuid') or sx.value(g,'id'):set(map(str,sx.child(g,'members',[])[1:])) for g in sx.children(result,'group')}
            sx.save(candidate/target.pcb_file.name,result)
        # Incoming net classes are appended; all existing target rules/settings stay.
        imported_settings=build_project(incoming,target_project.stem).get('net_settings',{})
        settings=project.setdefault('net_settings',{})
        existing_classes={c.get('name') for c in (settings.get('classes') or [])}
        for cls in imported_settings.get('classes',[]):
            if cls.get('name')=='Default':continue
            if cls.get('name') in existing_classes:raise MergeError('Incoming net-class collision: '+cls['name'])
            if settings.get('classes') is None:settings['classes']=[]
            settings['classes'].append(cls)
        for key in ('netclass_patterns',):
            if imported_settings.get(key):
                if settings.get(key) is None:settings[key]=[]
                settings[key].extend(imported_settings[key])
        for key in ('netclass_assignments','net_colors'):
            for name,value in imported_settings.get(key,{}).items():
                if name in (settings.get(key) or {}):raise MergeError('Incoming net-class assignment collides with target: '+name)
                if settings.get(key) is None:settings[key]={}
                settings[key][name]=value
        _json(candidate/target_project.name,project)
        # Check portable dependencies against the final target project root.
        for source in incoming:
            for entry in source.asset_manifest:
                if entry.get('destination'):entry['destination']=batch+'/'+entry['destination']
        asset_audit=audit_assets(incoming,candidate)
        if include_layout:
            drc=cli.drc(candidate/target.pcb_file.name,candidate/'insertion-drc.json')
            native_board=sx.load(candidate/target.pcb_file.name)
            _target_integrity(target.board,native_board)
            if geometry_signature(native_board)!=geometry_before:raise MergeError('Native validation changed imported footprint, track or via geometry.')
            other_after={sx.value(n,'uuid') or sx.value(n,'tstamp'):_geometry_signature(n) for n in sx.children(native_board)
                         if sx.tag(n) in ITEMS-{'group','footprint','segment','arc','via'}}
            if other_before!=other_after:raise MergeError('Native validation changed zone, keepout or supporting drawing geometry.')
            groups_after={sx.value(g,'uuid') or sx.value(g,'id'):set(map(str,sx.child(g,'members',[])[1:])) for g in sx.children(native_board,'group')}
            if groups_before!=groups_after:raise MergeError('Native validation changed PCB group membership.')
        cli.run(['sch','erc','--format','json','--output',candidate/'insertion-erc.json',candidate/target.schematic_file.name],cwd=candidate)
        erc=json.loads((candidate/'insertion-erc.json').read_text(encoding='utf-8-sig'))
        mapping={(s.alias,r.sheet.old_path,r.old_ref):s.ref_map[r.old_ref] for s in [target,*incoming] for r in s.symbols}
        export_csv(candidate/'insertion-bom.csv',grouped_bom(bom_input,reference_map=mapping),bom=True)
        field_rows=inventory([target,*incoming])
        for row in field_rows:row['merged_reference']=mapping.get((row['source'],row['sheet_path'],row['reference']),row['reference'])
        export_csv(candidate/'insertion-fields.csv',field_rows)
        source_file_hashes=_snapshot(incoming,assets)
        from .linked_updates import record_import
        record_import(candidate,target_project,incoming,parent,batch,imported,merged,include_layout,cli_path)
        report={'plugin_version':'0.9.2','target_project':str(target_project),'include_layout':include_layout,
                'copy_assets':bool(copy_assets),'assets':asset_audit,
                'incoming_designs':len(incoming),'incoming_sheets':sum(len(s.sheets) for s in incoming),
                'incoming_symbols':sum(len(s.symbols) for s in incoming),
                'incoming_footprints':sum(len(sx.children(s.board,'footprint')) for s in incoming) if include_layout else 0,
                'expected_new_unplaced_components':unplaced,'target_root_uuid':root_uuid,'connectivity':connectivity,
                'target_existing_geometry_preserved':True,'incoming_geometry_native_verified':include_layout,'target_settings_preserved':True,
                'target_outline_preserved':True,'drc_findings':len(drc.get('violations',[])) if drc else None,
                'unconnected_findings':len(drc.get('unconnected_items',[])) if drc else None,
                'erc_findings':sum(len(sheet.get('violations',[])) for sheet in erc.get('sheets',[])),
                'manufacturing_approved':False,'sources':[{'alias':s.alias,'reference_map':s.ref_map,'variant':s.selected_variant,
                'section_origin':copy.deepcopy(s.spec.section_origin),'translation_mm':list(s.translation)} for s in incoming],
                'limitations':['Incoming custom rules are archived for manual migration.',
                'Existing target board outline is retained; imported layout may require extending the outline after review.']}
        _json(candidate/'insertion-report.json',report)
        _assert_sources_unchanged(incoming)
        if fingerprint(target_root)!=target_hashes or any(fingerprint(Path(entry['root']))!=entry['hashes'] for entry in source_hashes):
            raise MergeError('A source or target changed during preview; nothing published.')
        publish(candidate,destination)
    return {'target_project':str(target_project),'target_hashes':target_hashes,'source_hashes':source_hashes,'gap_mm':float(gap_mm),
            'source_file_hashes':source_file_hashes,'candidate_directory':str(destination),'candidate_hashes':fingerprint(destination),'report':report}


def apply_import(plan):
    target=Path(plan['target_project']).resolve();root=target.parent;candidate=Path(plan['candidate_directory']).resolve()
    if not candidate.is_dir() or fingerprint(candidate)!=plan['candidate_hashes']:raise MergeError('Review candidate changed; preview again.')
    if fingerprint(root)!=plan['target_hashes']:raise MergeError('Target changed since preview; preview again.')
    for entry in plan['source_hashes']:
        if fingerprint(Path(entry['root']))!=entry['hashes']:raise MergeError('Incoming source changed since preview; preview again.')
    for entry in plan.get('source_file_hashes',[]):
        path=Path(entry['original_path'])
        if not path.is_file() or sha256(path)!=entry['sha256']:raise MergeError('Incoming dependency changed since preview; preview again: '+str(path))
    if any(root.glob('*.lck')):raise MergeError('The target has editor lock files. Save and close its KiCad editors before offline apply.')
    removed=list(plan.get('remove_files',[]))
    if removed:
        receipt_directory=Path(plan.get('undo_backup','')).resolve()
        receipt=json.loads((receipt_directory/'transaction.json').read_text(encoding='utf-8-sig'))
        if receipt.get('target_project')!=str(target) or receipt.get('applied_hashes')!=plan['target_hashes']:
            raise MergeError('Undo receipt does not match the current destination.')
        if fingerprint(receipt_directory/'project')!=receipt['target_hashes'] or plan['candidate_hashes']!=receipt['target_hashes']:
            raise MergeError('Undo backup or review candidate changed.')
        if set(removed)!=set(plan['target_hashes'])-set(plan['candidate_hashes']):raise MergeError('Undo removal list does not match verified transaction files.')
        if any(Path(relative).is_absolute() or '..' in Path(relative).parts for relative in removed):raise MergeError('Unsafe undo file path.')
    backup=root.parent/(root.name+'-FusionBackup-'+new_uuid());backup.mkdir()
    copy_project(root,backup/'project')
    if fingerprint(backup/'project')!=plan['target_hashes']:raise MergeError('Backup verification failed; nothing applied.')
    _json(backup/'transaction.json',{'target_project':str(target),'target_hashes':plan['target_hashes'],'report':plan['report']})
    originals=plan['target_hashes'];changed=[];created=[];created_directories=[]
    try:
        if fingerprint(root)!=originals:raise MergeError('Target changed while backing up; nothing applied.')
        for path in project_files(candidate):
            relative=str(path.relative_to(candidate));out=root/relative
            if relative in originals and plan['candidate_hashes'][relative]==originals[relative]:continue
            if relative not in originals and out.exists():raise MergeError('New insertion file collides with existing target data: '+relative)
            missing=[];parent=out.parent
            while parent!=root and not parent.exists():missing.append(parent);parent=parent.parent
            out.parent.mkdir(parents=True,exist_ok=True)
            created_directories.extend(reversed(missing))
            temp=out.with_name(out.name+'.fusion-'+new_uuid())
            try:
                shutil.copy2(path,temp);os.replace(temp,out)
            finally:
                if temp.exists():temp.unlink()
            (changed if relative in originals else created).append(relative)
        for relative in removed:
            (root/relative).unlink();changed.append(relative)
        if fingerprint(root)!=plan['candidate_hashes']:raise MergeError('Applied project does not match the validated candidate.')
        from datetime import datetime,timezone
        _json(backup/'transaction.json',{'target_project':str(target),'target_hashes':plan['target_hashes'],
              'applied_hashes':plan['candidate_hashes'],'created_at':datetime.now(timezone.utc).isoformat(),
              'report':plan['report'],'completed':True})
    except Exception as failure:
        recovery_errors=[]
        for relative in reversed(changed):
            try:
                (root/relative).parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(backup/'project'/relative,root/relative)
            except Exception as error:recovery_errors.append(str(error))
        for relative in reversed(created):
            path=root/relative
            try:
                if path.exists():path.unlink()
            except Exception as error:recovery_errors.append(str(error))
        for folder in sorted(set(created_directories),key=lambda p:len(p.parts),reverse=True):
            try:folder.rmdir()
            except OSError:pass
        try:restored=fingerprint(root)==originals
        except Exception as error:restored=False;recovery_errors.append(str(error))
        if not restored or recovery_errors:raise MergeError('Offline apply failed and rollback could not restore every file; recover from '+str(backup)+'\n'+'\n'.join(recovery_errors[-3:])) from failure
        raise
    return {'target_project':str(target),'backup_directory':str(backup),'report':plan['report']}
