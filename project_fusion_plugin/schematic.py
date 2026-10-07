"""Hierarchy-aware schematic import and stable symbol identity mapping."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
import copy
import hashlib
import json
import os
import re
import uuid

from . import sexpr as sx
from .model import MergeError, SourceSpec


def new_uuid():
    return str(uuid.uuid4())


def canonical_path(path):
    return '/' + '/'.join(p for p in str(path).split('/') if p)


def pcb_association_path(symbol_path, root_uuid):
    """Convert a schematic instance path to KiCad's root-free PCB path."""
    path = canonical_path(symbol_path)
    prefix = '/' + str(root_uuid).strip('/') + '/'
    if not sx.UUID_RE.fullmatch(str(root_uuid)) or not path.startswith(prefix) or path == prefix:
        raise MergeError('Schematic symbol path does not belong to the expected root UUID: ' + path)
    return canonical_path(path[len(prefix):])


def expand_path(text, project_dir, relative_dir):
    text = str(text).replace('${KIPRJMOD}', str(project_dir))
    text = os.path.expandvars(text).replace('\\', '/')
    if '${' in text or text.startswith('embedded://'):
        raise MergeError(f'Cannot resolve schematic path: {text}. Extract embedded sheets / define the environment variable first.')
    p = Path(text).expanduser()
    return (p if p.is_absolute() else Path(relative_dir)/p).resolve()


@dataclass
class SymbolRecord:
    sheet: 'SheetInstance'
    node: list
    old_uuid: str
    old_ref: str
    unit: int
    lib_id: str
    new_uuid: str = ''
    new_ref: str = ''
    old_path: str = ''
    new_path: str = ''

@dataclass
class SheetInstance:
    source_path: Path
    tree: list
    old_path: str
    new_path: str
    relative_file: str
    ids: dict
    symbols: list = field(default_factory=list)
    sub_sheets: list = field(default_factory=list)
    display_path: str = ''
    page: int = 0

@dataclass
class Source:
    spec: SourceSpec
    project_file: Path
    schematic_file: Path
    pcb_file: Path
    project: dict
    sheets: list[SheetInstance]
    wrapper_uuid: str
    old_root_uuid: str
    ref_map: dict = field(default_factory=dict)
    link_map: dict = field(default_factory=dict)
    power_names: set = field(default_factory=set)
    libraries: dict = field(default_factory=dict)
    lib_map: dict = field(default_factory=dict)
    board: list | None = None
    board_ref_map: dict = field(default_factory=dict)
    footprint_links: dict = field(default_factory=dict)
    bbox: tuple | None = None
    translation: tuple = (0.0,0.0)
    xml: object = None
    net_map: dict = field(default_factory=dict)
    files: set = field(default_factory=set)
    hashes: dict = field(default_factory=dict)
    class_map: dict = field(default_factory=dict)
    fp_lib_map: dict = field(default_factory=dict)
    fp_id_map: dict = field(default_factory=dict)
    variant_names: list = field(default_factory=list)
    selected_variant: str = '<Default>'
    variant_changes: list = field(default_factory=list)
    layer_map: dict = field(default_factory=dict)
    copper_layers: list = field(default_factory=list)
    target_copper_layers: list = field(default_factory=list)
    layer_notes: list = field(default_factory=list)
    asset_manifest: list = field(default_factory=list)
    portable_project: dict | None = None
    pcb_uuid_map: dict = field(default_factory=dict)
    fusion_group_uuid: str = ''

    @property
    def alias(self):
        return self.spec.alias

    @property
    def symbols(self):
        return [r for s in self.sheets for r in s.symbols]


def _has_variants(data):
    if isinstance(data, dict):
        for k,v in data.items():
            if 'variant' in k.lower() and v not in (None, '', [], {}, False, 0):
                return True
            if _has_variants(v):
                return True
    elif isinstance(data,list):
        return any(_has_variants(v) for v in data)
    return False


def instance_reference(symbol, old_path, project_name):
    inst = sx.child(symbol, 'instances')
    if inst is None:
        raise MergeError(f'Symbol {sx.propval(symbol,"Reference")}: no modern instance table. Open and save this project in KiCad 10 first.')
    exact, fallback = [], []
    for project in sx.children(inst,'project'):
        for path in sx.children(project,'path'):
            if len(path)>1 and canonical_path(path[1]) == canonical_path(old_path):
                item = (sx.value(path,'reference'), sx.value(path,'unit',sx.value(symbol,'unit','1')))
                fallback.append(item)
                if str(project[1]) == project_name:
                    exact.append(item)
    choices = set(exact or fallback)
    if len(choices) != 1:
        raise MergeError(f'Cannot unambiguously resolve symbol {sx.propval(symbol,"Reference")} at {old_path}; save/annotate the source hierarchy first.')
    ref, unit = next(iter(choices))
    if not ref or '?' in ref:
        raise MergeError(f'Unannotated symbol {ref!r}. Annotate the original source before merging.')
    try:
        return ref,int(unit)
    except ValueError as e:
        raise MergeError('Invalid symbol unit in source instance table.') from e


def discover(spec: SourceSpec, new_root_uuid: str, log=lambda msg: None, *, require_board=True) -> Source:
    from .source_detection import read_schematic
    path = Path(spec.project).expanduser().resolve()
    if path.suffix.lower() not in {'.kicad_pro','.kicad_sch','.kicad_pcb'}:
        raise MergeError(f'{spec.alias}: select a .kicad_pro, root .kicad_sch or .kicad_pcb.')
    pro, sch, pcb = (path.with_suffix(ext) for ext in ('.kicad_pro','.kicad_sch','.kicad_pcb'))
    for p in ((pro,sch,pcb) if require_board else (pro,sch)):
        if not p.is_file():
            raise MergeError(f'Missing project member: {p}. Project, root schematic and PCB must share a basename.')
    project_bytes = pro.read_bytes()
    project = json.loads(project_bytes.decode('utf-8-sig'))
    hashes = {str(pro): hashlib.sha256(project_bytes).hexdigest()}
    tree = read_schematic(sch, hashes)
    if sx.tag(tree) != 'kicad_sch':
        raise MergeError(f'{sch} is not a modern KiCad schematic.')
    old_root = sx.value(tree,'uuid')
    if not sx.UUID_RE.fullmatch(old_root):
        raise MergeError(f'{spec.alias}: missing root schematic UUID.')
    wrapper = new_uuid()
    s = Source(spec, pro, sch, pcb, project, [], wrapper, old_root)
    s.hashes.update(hashes)
    s.files.update(p for p in (pro,sch,pcb) if p.is_file())
    for extra in ('sym-lib-table','fp-lib-table',pro.stem+'.kicad_dru'):
        if (pro.parent/extra).is_file():
            s.files.add(pro.parent/extra)

    # Repeated sheet instances share file bytes, but must have independent trees
    # because variant application and import rewrites mutate each occurrence.
    parsed = {sch: tree}
    def visit(p, old_path, new_path, display_path, ancestors):
        if p in ancestors:
            raise MergeError(f'{spec.alias}: cyclic schematic hierarchy at {p}.')
        if len(s.sheets) >= 512 or len(ancestors) >= 32:
            raise MergeError('Hierarchy exceeds 512 sheet instances or 32 nesting levels.')
        if p not in parsed:
            parsed[p] = read_schematic(p, s.hashes)
        root = copy.deepcopy(parsed[p])
        if sx.tag(root) != 'kicad_sch':
            raise MergeError(f'Invalid schematic: {p}')
        identifiers = sx.declared_uuids(root)
        if len(set(identifiers)) != len(identifiers):
            raise MergeError(f'Duplicate declared UUIDs inside {p}. Repair/save the source first.')
        ids = {x:new_uuid() for x in identifiers}
        sheet = SheetInstance(p,root,old_path,new_path,
                              f'imported/{spec.alias}/sheet_{len(s.sheets):03d}.kicad_sch', ids,
                              display_path=display_path)
        s.sheets.append(sheet)
        s.files.add(p)
        for symbol in sx.children(root,'symbol'):
            old_id = sx.value(symbol,'uuid')
            if old_id not in ids:
                raise MergeError(f'Missing symbol UUID in {p}')
            ref, unit = instance_reference(symbol, old_path, pro.stem)
            r = SymbolRecord(sheet,symbol,old_id,ref,unit,sx.value(symbol,'lib_id'),
                             ids[old_id], old_path=old_path+'/'+old_id,
                             new_path=new_path+'/'+ids[old_id])
            sheet.symbols.append(r)
            s.link_map[canonical_path(r.old_path)] = r
            # KiCad legacy footprints sometimes omit only the root UUID.
            s.link_map[canonical_path('/'.join(r.old_path.split('/')[2:]))] = r
        for node in sx.children(root,'sheet'):
            old_id = sx.value(node,'uuid')
            if old_id not in ids:
                raise MergeError(f'Missing child-sheet UUID in {p}')
            filename = sx.propval(node,'Sheetfile') or sx.propval(node,'Sheet file')
            if not filename:
                raise MergeError(f'Child sheet without a filename in {p}')
            from .paths import resolve_asset
            subfile = resolve_asset(filename,s,p.parent)
            if subfile is None or not subfile.is_file():
                raise MergeError(f'Missing child schematic: {subfile}')
            name = sx.propval(node,'Sheetname') or sx.propval(node,'Sheet name') or subfile.stem
            sub = visit(subfile,old_path+'/'+old_id,new_path+'/'+ids[old_id], display_path+name+'/',ancestors+[p])
            sheet.sub_sheets.append((node,sub))
        return sheet
    visit(sch,'/'+old_root,'/'+new_root_uuid+'/'+wrapper,'/'+spec.alias+'/',[])
    records = defaultdict(list)
    for r in s.symbols:
        records[r.old_ref].append(r)
    for ref, rr in records.items():
        if len({r.unit for r in rr}) != len(rr) or len({r.lib_id for r in rr}) != 1:
            raise MergeError(f'{spec.alias}: reference {ref} is duplicated outside a valid multi-unit component. Fix source annotation first.')
    from .variants import apply_selected
    apply_selected(s)
    gather_libraries(s)
    log(f'{s.alias}: {len(s.sheets)} sheet instances, {len(records)} schematic references.')
    return s


def hidden_power_pin(pin):
    return (len(pin)>1 and str(pin[1]) == 'power_in' and
            ('hide' in [x for x in pin if isinstance(x,str)] or sx.value(pin,'hide') == 'yes'))


def gather_libraries(s):
    for sheet in s.sheets:
        for lib in sx.children(sx.child(sheet.tree,'lib_symbols',[]),'symbol'):
            old = str(lib[1])
            if sx.child(lib,'extends') is not None:
                raise MergeError(f'{s.alias}: cached symbol {old} still uses library inheritance. Save a fully resolved source first.')
            serialized = sx.dumps(lib)
            if old in s.libraries and sx.dumps(s.libraries[old]) != serialized:
                raise MergeError(f'{s.alias}: different embedded definitions share library ID {old}. Resolve the source library conflict first.')
            s.libraries[old] = copy.deepcopy(lib)
    for r in s.symbols:
        # lib_name selects an instance-specific embedded definition in KiCad.
        # Freeze that actual definition rather than falling back to lib_id.
        selector = sx.value(r.node, 'lib_name')
        if selector:
            if selector not in s.libraries:
                raise MergeError(f'{s.alias}: selected embedded symbol definition missing: {selector}')
            r.lib_id = selector
        if r.lib_id not in s.libraries:
            raise MergeError(f'{s.alias}: embedded symbol definition missing: {r.lib_id}')
    for old,lib in s.libraries.items():
        item = re.sub(r'[^A-Za-z0-9_]', '_', old.split(':')[-1])[:40] + '_' + hashlib.sha256(old.encode()).hexdigest()[:8]
        s.lib_map[old] = f'Fusion_{s.alias}:{item}'
        for pin in sx.walk(lib):
            if sx.tag(pin)=='pin' and hidden_power_pin(pin):
                s.power_names.add(sx.value(pin,'name'))
    for sheet in s.sheets:
        for n in sx.children(sheet.tree,'global_label'):
            label = str(n[1])
            undecorated = re.sub(r'~\{[^{}]*\}', '', label)
            if any(ch in undecorated for ch in '[]{} \t'):
                raise MergeError(f'{s.alias}: global bus/decorated/group label {label!r} needs explicit handling; this release supports scalar global labels. Local/hierarchical buses remain supported and are netlist-checked.')
            s.power_names.add(label)
        for r in sheet.symbols:
            lib = s.libraries[r.lib_id]
            if sx.child(lib,'power') is not None and any(sx.tag(p)=='pin' and len(p)>1 and p[1]=='power_in' for p in sx.walk(lib)):
                s.power_names.add(sx.propval(r.node,'Value'))
    s.power_names.discard('')


REF = re.compile(r'^(#?[A-Za-z_][A-Za-z0-9_]*?)(\d+)$')


def natural_ref(ref):
    m = REF.fullmatch(ref)
    if not m:
        raise MergeError(f'Unsupported reference {ref!r}; references must end in a numeric designator.')
    return m[1],int(m[2])


def annotate(sources, policy='sequential', block_size=1000):
    counters = defaultdict(int)
    for index,s in enumerate(sources):
        local = defaultdict(int)
        refs = set(r.old_ref for r in s.symbols) | set(s.board_ref_map)
        for old in sorted(refs,key=natural_ref):
            prefix,_ = natural_ref(old)
            if policy == 'blocks':
                local[prefix] += 1
                if local[prefix] >= block_size:
                    raise MergeError(f'{s.alias}: {prefix} references exceed the selected block size.')
                number = (index+1)*block_size + local[prefix]
            else:
                counters[prefix] += 1
                number = counters[prefix]
            new = prefix + (f'{number:04d}' if prefix.startswith('#') else str(number))
            s.ref_map[old] = new
        for r in s.symbols:
            r.new_ref = s.ref_map[r.old_ref]


def namespace_text(node, s):
    variables = s.project.get('text_variables',{})
    for n in sx.walk(node):
        for i,v in enumerate(n):
            if not isinstance(v,sx.Quoted):
                continue
            text = str(v)
            # Preserve ordinary prose; only structured ${...} references change.
            def replace(m):
                key = m[1]
                if key == 'VARIANT' and s.selected_variant != '<Default>':
                    return s.selected_variant
                if ':' in key:
                    ref,field = key.split(':',1)
                    return '${'+s.ref_map.get(ref,ref)+':'+field+'}'
                return '${'+(s.alias+'__'+key if key in variables else key)+'}'
            if '${' in text:
                text = re.sub(r'\$\{([^}]+)\}',replace,text)
            n[i] = sx.q(text)


def isolated(name,s):
    return s.alias+'__'+name if name in s.power_names else name


def rewrite_library(lib, old_id, s):
    n = copy.deepcopy(lib)
    old_item = old_id.split(':')[-1]
    full_new = s.lib_map[old_id]
    new_item = full_new.split(':')[-1]
    n[1] = sx.q(full_new)
    for sub in sx.children(n,'symbol'):
        if str(sub[1]).startswith(old_item+'_'):
            sub[1] = sx.q(new_item+str(sub[1])[len(old_item):])
    for pin in sx.walk(n):
        if sx.tag(pin)=='pin' and len(pin)>1 and pin[1]=='power_in':
            if hidden_power_pin(pin) or sx.child(n,'power') is not None:
                name = sx.child(pin,'name')
                if name is not None:
                    name[1] = sx.q(isolated(str(name[1]),s))
    if sx.child(n,'power') is not None:
        val = sx.prop(n,'Value')
        if val is not None:
            val[2] = sx.q(isolated(str(val[2]),s))
    # Persist correct footprint library nicknames in frozen symbol libraries too.
    f = sx.prop(n,'Footprint')
    if f is not None:
        f[2] = sx.q(remap_footprint_id(str(f[2]),s))
    namespace_text(n,s)
    return n


def remap_footprint_id(text,s):
    if text in s.fp_id_map:
        return s.fp_id_map[text]
    if ':' in text:
        nick,item=text.split(':',1)
        return s.fp_lib_map.get(nick,nick)+':'+item
    return text


def transform_schematics(s: Source, output: Path, project_name: str, page_counter: int):
    transformed_libs = {old:rewrite_library(lib,old,s) for old,lib in s.libraries.items()}
    targets = defaultdict(set)
    for sheet in s.sheets:
        for old,new in sheet.ids.items():
            targets[old].add(new)
    global_ids = {old:next(iter(news)) for old,news in targets.items() if len(news)==1}
    for sheet in s.sheets:
        sheet.page = page_counter
        page_counter += 1
    for sheet in s.sheets:
        root = sheet.tree
        sx.put(root,'generator',sx.q('wayri_project_fusion'))
        sx.remove(root,'generator_version')
        sx.remove(root,'sheet_instances')
        sx.remove(root,'symbol_instances')
        text_ids = dict(global_ids)
        text_ids.update(sheet.ids)  # References to a local reused-sheet item stay local.
        for n in sx.walk(root):
            for atom in n:
                if isinstance(atom,sx.Quoted):
                    for target in re.findall(r'\$\{([^}:]+):',str(atom)):
                        if sx.UUID_RE.fullmatch(target) and target not in text_ids:
                            raise MergeError(f'{s.alias}: cross-sheet UUID field reference {target} is ambiguous or missing after sheet cloning. Resolve it in a source copy first.')
        sx.remap_identifiers(root,text_ids)
        namespace_text(root,s)
        for n in sx.walk(root):
            if sx.tag(n) in {'label','global_label','hierarchical_label'} and len(n)>1:
                # New names are deliberately visible; geometry is not changed.
                n[1] = sx.q(isolated(str(n[1]),s))
            if sx.tag(n)=='property' and len(n)>2 and str(n[1]).casefold()=='net class':
                n[2] = sx.q(s.class_map.get(str(n[2]),str(n[2])))
        cache = sx.child(root,'lib_symbols')
        if cache is not None:
            cache[:] = ['lib_symbols',*[copy.deepcopy(transformed_libs[str(lib[1])]) for lib in sx.children(cache,'symbol')]]
        for r in sheet.symbols:
            symbol = r.node
            sx.put(symbol,'lib_id',sx.q(s.lib_map[r.lib_id]))
            sx.remove(symbol,'lib_name')
            p = sx.prop(symbol,'Reference')
            if p is None:
                raise MergeError(f'{s.alias}: symbol {r.old_ref} has no Reference property.')
            p[2] = sx.q(r.new_ref)
            val = sx.prop(symbol,'Value')
            lib = s.libraries[r.lib_id]
            if val is not None and sx.child(lib,'power') is not None:
                val[2] = sx.q(isolated(str(val[2]),s))
            fp = sx.prop(symbol,'Footprint')
            if fp is not None:
                fp[2] = sx.q(remap_footprint_id(str(fp[2]),s))
            sx.put(symbol,'instances',['project',sx.q(project_name),
                ['path',sx.q(sheet.new_path),['reference',sx.q(r.new_ref)],['unit',str(r.unit)]]])
        for node,sub in sheet.sub_sheets:
            pf = sx.prop(node,'Sheetfile') or sx.prop(node,'Sheet file')
            pf[2] = sx.q(Path(sub.relative_file).name)
            for pin in sx.children(node,'pin'):
                pin[1] = sx.q(isolated(str(pin[1]),s))
            sx.put(node,'instances',['project',sx.q(project_name),
                ['path',sx.q(sheet.new_path),['page',sx.q(sub.page)]]])
        sx.save(output/sheet.relative_file,root)
    # Freeze the embedded symbol definitions under collision-free library names.
    # Schematic-owned embedded resources are retained there; external references
    # in these libraries are rejected by the asset pass when unresolved.
    library=['kicad_symbol_lib',['version','20231120'],['generator',sx.q('wayri_project_fusion')]]
    for old,lib in transformed_libs.items():
        lib=copy.deepcopy(lib)
        lib[1]=sx.q(str(lib[1]).split(':')[-1])
        library.append(lib)
    # Embedded dependencies were attached to each frozen symbol by the asset pass.
    sx.save(output/f'libraries/Fusion_{s.alias}.kicad_sym',library)
    return page_counter


def make_parent(sources, project_name, root_uuid):
    version=max(int(sx.value(s.sheets[0].tree,'version','20250114')) for s in sources)
    root=['kicad_sch',['version',str(version)],['generator',sx.q('wayri_project_fusion')],
          ['uuid',sx.q(root_uuid)],['paper',sx.q('A3')],['lib_symbols'],
          ['sheet_instances',['path',sx.q('/'),['page',sx.q('1')]]]]
    y=25.4
    for i in range(0,len(sources),2):
        height=20.32
        pair=sources[i:i+2]
        for j,s in enumerate(pair):
            x=25.4+j*127.0
            sheet_y=y
            position=getattr(s.spec,'sheet_position_mm',[])
            if position:x,sheet_y=map(float,position)
            labels={str(n[1]):sx.value(n,'shape','bidirectional') for n in sx.children(s.sheets[0].tree,'hierarchical_label')}
            h=max(20.32,(len(labels)+2)*2.54)
            height=max(height,h)
            sheet=['sheet',['at',str(x),str(y)],['size','101.6',str(h)],
                   ['stroke',['width','0'],['type','default']],['fill',['color','0','0','0','0']],
                   ['uuid',sx.q(s.wrapper_uuid)],
                   ['property',sx.q('Sheetname'),sx.q(s.alias),['at',str(x),str(y-1.27),'0'],['effects',['font',['size','1.27','1.27']],['justify','left','bottom']]],
                   ['property',sx.q('Sheetfile'),sx.q(s.sheets[0].relative_file),['at',str(x),str(y+h+1.27),'0'],['effects',['font',['size','1.27','1.27']],['justify','left','top']]],
                   ['instances',['project',sx.q(project_name),['path',sx.q('/'+root_uuid),['page',sx.q(s.sheets[0].page)]]]]]
            for k,(name,shape) in enumerate(labels.items()):
                sheet.append(['pin',sx.q(name),shape,['at',str(x),str(y+(k+1)*2.54),'180'],['effects',['font',['size','1.27','1.27']]],['uuid',sx.q(new_uuid())]])
            root.append(sheet)
            if sheet_y!=y:
                for node in sx.walk(sheet):
                    if sx.tag(node)=='at' and len(node)>2:node[2]=str(float(node[2])+sheet_y-y)
        y+=height+20.32
    if y>270:
        sx.put(root,'paper',sx.q('User'),'420',str(y+25.4))
    # Primary schematic-owned worksheet/font references remain valid at the
    # combined project root as well as within its imported copy.
    if sources:
        for head in ('embedded_files','embedded_fonts'):
            node=sx.child(sources[0].sheets[0].tree,head)
            if node is not None: root.append(copy.deepcopy(node))
    return root
