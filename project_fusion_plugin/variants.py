"""KiCad 10 native per-instance assembly variants.

A selected configuration becomes the base state of the *new* imported copy.
Source files and other source variants are never modified. Differential overrides
live under instances/project/path/variant, not under displayed references.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from . import sexpr as sx
from .model import MergeError, SourceSpec
from .paths import resolve_asset

DEFAULT = '<Default>'
BOM_LOGIC_FIX_VERSION = 20260306
MIN_VARIANT_VERSION = 20250922
FLAGS = {'dnp': 'no', 'exclude_from_sim': 'no', 'in_bom': 'yes', 'on_board': 'yes', 'in_pos_files': 'yes'}


def project_names(project):
    entries = project.get('schematic', {}).get('variants', []) or []
    if not isinstance(entries, list):
        raise MergeError('Native schematic.variants metadata must be an array.')
    names=[]
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('name'),str) or not entry['name']:
            raise MergeError('Malformed native variant metadata; expected objects with a nonempty name.')
        name=entry['name']
        if name in names or name == DEFAULT:
            raise MergeError(f'Duplicate/reserved variant name: {name!r}')
        names.append(name)
    return names


def object_paths(node, path, project_name):
    exact=[]; fallback=[]
    inst=sx.child(node,'instances',['instances'])
    for p in sx.children(inst,'project'):
        for entry in sx.children(p,'path'):
            if str(entry[1]).rstrip('/') == path.rstrip('/'):
                fallback.append(entry)
                if str(p[1]) == project_name:
                    exact.append(entry)
    choices=exact or fallback
    if len(choices)>1:
        texts={sx.dumps(p) for p in choices}
        if len(texts)>1:
            raise MergeError(f'Ambiguous variant instance at {path}; save the source in its owning project.')
    return choices[:1]


def named_blocks(node):
    result={}
    for v in sx.children(node,'variant'):
        name=sx.value(v,'name')
        if not name or name in result or name == DEFAULT:
            raise MergeError('A native variant has a missing, duplicate or reserved name.')
        result[name]=v
    return result


def names_in_tree(tree, project_name, path):
    names=[]
    for obj in sx.children(tree):
        if sx.tag(obj) not in {'symbol','sheet'}:
            continue
        for instance in object_paths(obj,path,project_name):
            for name in named_blocks(instance):
                if name not in names:
                    names.append(name)
    return names


def detect_variants(spec):
    """Read-only UI discovery, including external and nested subsheets."""
    from types import SimpleNamespace
    from .source_detection import read_schematic
    if isinstance(spec,(str,Path)):
        spec=SourceSpec(str(spec),'Source')
    project_file=Path(spec.project).expanduser().resolve().with_suffix('.kicad_pro')
    if not project_file.is_file() and Path(spec.project).suffix.lower()!='.kicad_sch':
        raise MergeError('Variant discovery needs an owning project or a standalone schematic.')
    project=json.loads(project_file.read_text(encoding='utf-8-sig')) if project_file.is_file() else {}
    source=SimpleNamespace(spec=spec,project_file=project_file,project=project)
    names=project_names(project)
    root=project_file.with_suffix('.kicad_sch')
    top=read_schematic(root)
    parsed={root:top}
    count=0
    def visit(p,tree,path,ancestors):
        nonlocal count
        count+=1
        if count>512 or len(ancestors)>32 or p in ancestors:
            raise MergeError('Cyclic or excessively large schematic hierarchy during variant discovery.')
        for name in names_in_tree(tree,project_file.stem,path):
            if name not in names:
                names.append(name)
        for sheet in sx.children(tree,'sheet'):
            raw=sx.propval(sheet,'Sheetfile') or sx.propval(sheet,'Sheet file')
            child=resolve_asset(raw,source,p.parent)
            if child is None or not child.is_file():
                raise MergeError(f'Cannot resolve child schematic {raw!r} in {p}. Configure source path overrides.')
            if child not in parsed:parsed[child]=read_schematic(child)
            visit(child,parsed[child],path+'/'+sx.value(sheet,'uuid'),ancestors+[p])
    visit(root,top,'/'+sx.value(top,'uuid'),[])
    return [DEFAULT,*names]


def select_variant(source):
    names=project_names(source.project)
    for sheet in source.sheets:
        for name in names_in_tree(sheet.tree,source.project_file.stem,sheet.old_path):
            if name not in names:
                names.append(name)
    source.variant_names=names
    selected=source.spec.variant
    if selected is None:
        if names:
            raise MergeError(f'{source.alias}: choose a variant explicitly; detected {", ".join(names)} and {DEFAULT}. Default is not assumed current.')
        selected=DEFAULT
    if selected != DEFAULT and selected not in names:
        raise MergeError(f'{source.alias}: variant {selected!r} was not found. Detected: {", ".join([DEFAULT,*names])}.')
    source.selected_variant=selected
    if hasattr(source,'_path_context'): del source._path_context


def state(node):
    fields={}
    for p in sx.children(node,'property'):
        # Private properties are valid KiCad syntax; retain their original nodes.
        offset=2 if len(p)>1 and p[1]=='private' and not isinstance(p[1],sx.Quoted) else 1
        if len(p)<=offset+1:
            raise MergeError('Malformed symbol/sheet field.')
        name,value=str(p[offset]),str(p[offset+1])
        if name in fields:
            raise MergeError(f'Duplicate field {name!r}')
        fields[name]=value
    flags={k:sx.value(node,k,default) for k,default in FLAGS.items()}
    if any(v not in {'yes','no'} for v in flags.values()):
        raise MergeError('Variant flags must be serialized as yes/no.')
    return {'fields':fields, 'flags':flags}


def effective(node, instance, selected, version):
    result=state(node)
    block=named_blocks(instance).get(selected) if instance is not None and selected != DEFAULT else None
    if block is None:
        return result
    if version<MIN_VARIANT_VERSION:
        raise MergeError('Variant data appears in a pre-variant schematic file format.')
    seen=set()
    for c in sx.children(block):
        tag=sx.tag(c)
        if tag not in set(FLAGS)|{'name','field'}:
            raise MergeError(f'Unsupported native variant token {tag!r}; refusing to drop configuration data.')
        if tag=='field':
            name=sx.value(c,'name'); value=sx.value(c,'value',None)
            if not name or value is None or ('field',name) in seen:
                raise MergeError('Variant field has missing/duplicate name/value.')
            if name in {'Reference','Sheetfile','Sheet file'}:
                if result['fields'].get(name) != value:
                    raise MergeError(f'Variant changes structural field {name!r}; use a synchronized standalone source for that configuration.')
            result['fields'][name]=value
            seen.add(('field',name))
        elif tag in FLAGS:
            if tag in seen or len(c)!=2 or str(c[1]) not in {'yes','no'}:
                raise MergeError(f'Invalid/duplicate variant flag {tag!r}')
            value=str(c[1])
            # KiCad's old writer serialized the exclusion bit as in_bom.
            if tag=='in_bom' and version<BOM_LOGIC_FIX_VERSION:
                value='no' if value=='yes' else 'yes'
            if sx.tag(node)=='sheet' and tag in {'on_board','in_pos_files'}:
                raise MergeError(f'Named sheet variant {tag} is not supported by the KiCad 10 sheet writer.')
            result['flags'][tag]=value
            seen.add(tag)
    return result


def set_field(node,name,value,board=False):
    p=sx.prop(node,name)
    if p is not None:
        offset=3 if len(p)>1 and p[1]=='private' and not isinstance(p[1],sx.Quoted) else 2
        p[offset]=sx.q(value)
        return
    at=sx.child(node,'at',['at','0','0','0'])
    # New custom fields are hidden; existing field placement is not changed.
    p=['property',sx.q(name),sx.q(value),['at','0' if board else str(at[1]),'0' if board else str(at[2]),'0']]
    if board:
        p.append(['layer',sx.q('F.Fab')])
    p.append(['effects',['font',['size','1','1']],['hide','yes']])
    node.append(p)


def apply_selected(source):
    select_variant(source)
    source.destination_states={}
    named=source.spec.variant_mode!='base' and source.spec.destination_variant!=DEFAULT
    report=[]
    for sheet in source.sheets:
        version=int(sx.value(sheet.tree,'version'))
        for obj in sx.children(sheet.tree):
            if sx.tag(obj) not in {'symbol','sheet'}:
                continue
            paths=object_paths(obj,sheet.old_path,source.project_file.stem)
            before=state(obj)
            after=effective(obj, paths[0] if paths else None, source.selected_variant, version)
            if named:
                source.destination_states[(sheet.old_path,sx.value(obj,'uuid'))]=copy.deepcopy(after)
                # The saved PCB represents Default. Named configurations cannot
                # replace its footprint topology during a geometry-preserving import.
                if after['fields'].get('Footprint')!=before['fields'].get('Footprint'):
                    raise MergeError(f'{source.alias}: named variant changes Footprint; synchronize a separate source copy before importing this footprint configuration.')
                library=getattr(source,'libraries',{}).get(sx.value(obj,'lib_id'))
                if library is not None and sx.child(library,'power') is not None and after['fields'].get('Value')!=before['fields'].get('Value'):
                    raise MergeError('Named variants cannot change power-symbol net identities during an isolated import.')
                if before!=after:
                    report.append({'sheet':str(sheet.source_path),'instance':sheet.old_path,
                                   'uuid':sx.value(obj,'uuid'),'before':before,'after':after})
                after=before
            for name,value in after['fields'].items():
                if before['fields'].get(name) != value:
                    set_field(obj,name,value)
            for k,v in after['flags'].items():
                if sx.tag(obj)=='sheet' and k=='in_pos_files':
                    continue
                if before['flags'][k] != v or sx.child(obj,k) is not None:
                    sx.put(obj,k,v)
            if before!=after:
                report.append({'sheet':str(sheet.source_path),'instance':sheet.old_path,
                               'uuid':sx.value(obj,'uuid'),'before':before,'after':after})
            # The imported sheet occurrence is independent. Keep only its owning
            # instance; stale other-project/other-occurrence overrides cannot leak.
            for entry in sx.walk(obj):
                sx.remove(entry,'variant')
                sx.remove(entry,'variants')
    source.variant_changes=report
    if named:
        for sheet in source.sheets:
            for node in sx.walk(sheet.tree):
                for index,value in enumerate(node):
                    if isinstance(value,sx.Quoted):
                        node[index]=sx.q(str(value).replace('${VARIANT}',DEFAULT))
    # Board flags need the effective sheet ancestors, even though the schematic
    # keeps the sheet-level flags (KiCad propagates those itself).
    def inherit(sheet,parent):
        sheet.assembly_parent_flags=dict(parent)
        for obj,child in sheet.sub_sheets:
            combined=dict(parent)
            for k in ('dnp','exclude_from_sim'):
                combined[k]='yes' if parent.get(k)=='yes' or sx.value(obj,k,FLAGS[k])=='yes' else 'no'
            for k in ('in_bom','on_board'):
                combined[k]='no' if parent.get(k)=='no' or sx.value(obj,k,FLAGS[k])=='no' else 'yes'
            inherit(child,combined)
    inherit(source.sheets[0],{})
    source.destination_parent_flags={}
    def inherit_selected(sheet,parent):
        source.destination_parent_flags[sheet.old_path]=dict(parent)
        for obj,child in sheet.sub_sheets:
            selected=source.destination_states.get((sheet.old_path,sx.value(obj,'uuid')),state(obj))
            combined=dict(parent)
            for k in ('dnp','exclude_from_sim'):
                combined[k]='yes' if parent.get(k)=='yes' or selected['flags'][k]=='yes' else 'no'
            for k in ('in_bom','on_board'):
                combined[k]='no' if parent.get(k)=='no' or selected['flags'][k]=='no' else 'yes'
            inherit_selected(child,combined)
    inherit_selected(source.sheets[0],{})


def destination_metadata(project,sources,existing=False):
    """Resolve destination names without modifying existing definitions."""
    result=copy.deepcopy(project)
    names=project_names(result)
    for source in sources:
        if not hasattr(source,'spec'):continue
        from .model import validate_section_origin
        validate_section_origin(source.spec)
        if source.spec.variant_mode=='separate':
            name=source.spec.destination_variant
            if name in names:
                raise MergeError(f'{source.alias}: destination variant {name!r} already exists; use merge or a new name.')
            names.append(name)
            schematic=result.setdefault('schematic',{})
            if schematic.get('variants') is None:schematic['variants']=[]
            schematic.setdefault('variants',[]).append({'name':name})
    for source in sources:
        if not hasattr(source,'spec'):continue
        if source.spec.variant_mode=='merge' and source.spec.destination_variant!=DEFAULT and source.spec.destination_variant not in names:
            raise MergeError(f'{source.alias}: destination variant {source.spec.destination_variant!r} does not exist. Create it with separate variant handling first.')
    return result


def attach_destination(source,output,project_name):
    """Write chosen states under fresh imported instance paths after rebasing.

    Default fields remain authoritative for geometry and native connectivity.
    Only imported occurrences receive overrides; target symbols are untouched.
    """
    if source.spec.variant_mode=='base' or source.spec.destination_variant==DEFAULT:
        return
    from .schematic import namespace_text
    for sheet in source.sheets:
        tree=sx.load(Path(output)/sheet.relative_file)
        sx.put(tree,'version',str(max(int(sx.value(tree,'version')),BOM_LOGIC_FIX_VERSION)))
        reverse={new:old for old,new in sheet.ids.items()}
        power_ids={sx.value(r.node,'uuid') for r in getattr(sheet,'symbols',[])
                   if sx.child(source.libraries[r.lib_id],'power') is not None}
        for node in sx.children(tree):
            if sx.tag(node) not in {'symbol','sheet'}:continue
            selected=source.destination_states.get((sheet.old_path,reverse.get(sx.value(node,'uuid'))))
            if selected is None:raise MergeError('Missing selected variant state after hierarchy rebasing.')
            entries=object_paths(node,sheet.new_path,project_name)
            if len(entries)!=1:raise MergeError('Missing imported native variant instance path.')
            variant=['variant',['name',sx.q(source.spec.destination_variant)]]
            base=state(node)
            for name,value in selected['fields'].items():
                if name in {'Reference','Sheetfile','Sheet file','Footprint'}:continue
                temporary=['symbol',['property',sx.q(name),sx.q(value)]]
                namespace_text(temporary,source)
                value=sx.propval(temporary,name)
                if name=='Value' and sx.value(node,'uuid') in power_ids:
                    from .schematic import isolated
                    value=isolated(value,source)
                if value!=base['fields'].get(name):
                    variant.append(['field',['name',sx.q(name)],['value',sx.q(value)]])
            for name,value in selected['flags'].items():
                if sx.tag(node)=='sheet' and name in {'on_board','in_pos_files'}:continue
                if value!=base['flags'][name]:variant.append([name,value])
            entries[0].append(variant)
        sx.save(Path(output)/sheet.relative_file,tree)


def disposition(source):
    return {'mode':source.spec.variant_mode,'destination':source.spec.destination_variant,
            'source_selected':source.selected_variant,
            'native_validation_state':DEFAULT if source.destination_states else source.selected_variant}


def validate_destination_layout(source):
    for (path,ident),selected in source.destination_states.items():
        sheet=next(s for s in source.sheets if s.old_path==path)
        node=next(n for n in sx.children(sheet.tree) if sx.value(n,'uuid')==ident)
        if selected['flags']['on_board']!=state(node)['flags']['on_board']:
            raise MergeError(f'{source.alias}: named variant changes on_board; choose schematic-only import or synchronize a separate layout first.')


def selection_block(node,selected,name):
    """Build a native override from explicit selected fields and assembly flags."""
    base=state(node);block=['variant',['name',sx.q(name)]]
    for key,value in selected['fields'].items():
        if key not in {'Reference','Sheetfile','Sheet file'} and value!=base['fields'].get(key):
            block.append(['field',['name',sx.q(key)],['value',sx.q(value)]])
    for key,value in selected['flags'].items():
        if sx.tag(node)=='sheet' and key in {'on_board','in_pos_files'}:continue
        if value!=base['flags'][key]:block.append([key,value])
    return block


def transform_destination(source,output,project_name,page):
    from .schematic import transform_schematics
    selected=source.selected_variant
    try:
        if source.destination_states:source.selected_variant=DEFAULT
        return transform_schematics(source,output,project_name,page)
    finally:source.selected_variant=selected


def extracted_variant_name(source):
    return source.selected_variant if source.selected_variant!=DEFAULT else 'FusionSelectedDefault'


def effective_board_flags(record):
    result=state(record.node)['flags']
    parents=getattr(record.sheet,'assembly_parent_flags',{})
    for k in ('dnp','exclude_from_sim'):
        if parents.get(k)=='yes': result[k]='yes'
    for k in ('in_bom','on_board'):
        if parents.get(k)=='no': result[k]='no'
    return result


def synchronize_footprint(fp,record,source):
    flags=effective_board_flags(record)
    if flags['on_board']=='no':
        raise MergeError(f'{source.alias}: {record.old_ref} is excluded from PCB in the selected variant but has a placed footprint. Removing it would alter preserved layout/connectivity; synchronize a source copy first.')
    desired=sx.propval(record.node,'Footprint')
    existing=str(fp[1])
    if desired != existing:
        raise MergeError(f'{source.alias}: selected variant {source.selected_variant!r} assigns {record.old_ref} to {desired!r}, but the placed footprint is {existing!r}. The merger will not silently resize/replace a routed footprint. Update PCB from the chosen variant in a source copy first.')
    for name,value in state(record.node)['fields'].items():
        if name in {'Reference','Footprint'}:
            continue
        set_field(fp,name,value,board=True)
    from .embedded import transfer_symbol_fields
    transfer_symbol_fields(fp,record,source)
    for text in sx.children(fp,'fp_text'):
        if len(text)>2 and text[1]=='value':
            text[2]=sx.q(sx.propval(record.node,'Value'))
    attr=sx.child(fp,'attr')
    if attr is None:
        attr=sx.put(fp,'attr')
    for token,enabled in [('dnp',flags['dnp']=='yes'),('exclude_from_bom',flags['in_bom']=='no'),('exclude_from_pos_files',flags['in_pos_files']=='no')]:
        attr[:]=[v for v in attr if not (isinstance(v,str) and v==token)]
        if enabled:
            attr.append(token)
    # The schematic is authoritative. Remove PCB-side cached variant tables;
    # copying them would re-introduce unselected variants on the merged PCB.
    sx.remove(fp,'variant'); sx.remove(fp,'variants')
