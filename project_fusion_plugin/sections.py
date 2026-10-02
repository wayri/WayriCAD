"""Conservative, reviewed extraction of an exact sheet occurrence and routed region.

No copper is clipped. Objects touching the selection boundary are refused.
Native geometry is measured in an isolated KiCad Python process.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import copy
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile

from . import sexpr as sx
from .model import MergeError, SourceSpec, validate_source_aliases
from .schematic import discover, new_uuid, canonical_path
from .repair import fingerprint, copy_project, project_files
from .netlist import KiCadCLI
from .board import net_name, net_table, HEADER, ITEMS, prepare_board
from .variants import effective_board_flags


def list_sections(spec):
    source = discover(spec, new_uuid(), require_board=False)
    return [{'sheet_path': s.old_path, 'display_path': s.display_path,
             'file': str(s.source_path), 'symbols': len(s.symbols),
             'descendant_symbols': sum(len(c.symbols) for c in source.sheets
                                      if c.old_path == s.old_path or c.old_path.startswith(s.old_path + '/'))}
            for s in source.sheets[1:]]


def suggest_region(spec,sheet_path,cli_path='',max_depth=None):
    """Initial footprint envelope with 1 mm margin; preview still must approve it."""
    source=discover(spec,new_uuid()); path=canonical_path(sheet_path)
    selected = next((s for s in source.sheets if s.old_path == path), None)
    if selected is None:
        raise MergeError('The exact sheet UUID instance no longer exists.')
    if max_depth is not None and (isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0):
        raise MergeError('Selection depth must be a nonnegative integer or unlimited.')
    wanted={canonical_path(r.old_path) for s in source.sheets
            if (s.old_path==path or s.old_path.startswith(path+'/'))
            and (max_depth is None or s.old_path.count('/')-path.count('/') <= max_depth)
            for r in s.symbols}
    boxes=_native_bounds(source.pcb_file,KiCadCLI(cli_path))
    board=sx.load(source.pcb_file)
    selected=[boxes[sx.value(fp,'uuid') or sx.value(fp,'tstamp')]
              for fp in sx.children(board,'footprint')
              if source.link_map.get(canonical_path(sx.value(fp,'path'))) is not None
              and canonical_path(source.link_map[canonical_path(sx.value(fp,'path'))].old_path) in wanted]
    if not selected: raise MergeError('This sheet instance has no placed PCB footprints.')
    return [min(b[0] for b in selected)-1,min(b[1] for b in selected)-1,
            max(b[2] for b in selected)+1,max(b[3] for b in selected)+1]


def _region(value):
    if len(value) != 4:
        raise MergeError('Supply four region coordinates: X1, Y1, X2, Y2 in mm.')
    box = tuple(float(x) for x in value)
    if not all(math.isfinite(x) and abs(x) <= 10000 for x in box) or box[0] >= box[2] or box[1] >= box[3]:
        raise MergeError('Region must be a finite, positive rectangle within ±10000 mm.')
    return box


def _relation(bounds, region):
    # Native bounding boxes include the stroke width, vias and complete arcs.
    x1,y1,x2,y2 = bounds; a,b,c,d = region
    if x2 < a or x1 > c or y2 < b or y1 > d:
        return 'outside'
    if x1 > a and y1 > b and x2 < c and y2 < d:
        return 'inside'
    return 'boundary'


def _native_bounds(pcb, cli):
    python = Path(cli.path).with_name('python.exe' if os.name == 'nt' else 'python3')
    if not python.is_file():
        raise MergeError('Subsheet extraction requires KiCad’s isolated Python runtime beside kicad-cli.')
    code = '''import json,sys,pcbnew
b=pcbnew.LoadBoard(sys.argv[1]); result={}
for item in list(b.GetFootprints())+list(b.GetTracks())+list(b.Zones())+list(b.GetDrawings()):
 r=item.GetBoundingBox(); result[item.m_Uuid.AsString()]=[pcbnew.ToMM(r.GetX()),pcbnew.ToMM(r.GetY()),pcbnew.ToMM(r.GetRight()),pcbnew.ToMM(r.GetBottom())]
print(json.dumps(result))
'''
    env = dict(os.environ)
    for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'): env.pop(key, None)
    run = subprocess.run([str(python), '-I', '-X', 'faulthandler', '-c', code, str(pcb)],
                         capture_output=True, text=True, timeout=120, env=env,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if run.returncode:
        raise MergeError('Native region geometry failed in an isolated process: '+run.stderr[-2000:])
    try: return json.loads(run.stdout)
    except ValueError as error: raise MergeError('Native geometry returned an invalid result.') from error


def _partitions(netlist, refs):
    return {frozenset(ep for ep in endpoints if ep[0] in refs): name
            for name,endpoints in netlist.nets.items() if any(ep[0] in refs for ep in endpoints)}


def _geometry_signature(item):
    """Compare placements, pad/copper geometry and outlines across native rewrite."""
    selected={'at','start','mid','end','center','size','drill','offset','width','layer','layers',
              'polygon','primitives','keepout','locked','status','type','rect_delta','chamfer_ratio',
              'roundrect_rratio','chamfer','options','members'}
    def normalize(node):
        if isinstance(node,list):
            if sx.tag(node)=='members':return ('members',*sorted(str(x) for x in node[1:]))
            return tuple(normalize(x) for x in node)
        if isinstance(node,sx.Quoted): return str(node)
        try: return round(float(node),7)
        except (ValueError,TypeError): return str(node)
    geometry=[normalize(n) for n in sx.children(item) if sx.tag(n) in selected]
    if sx.tag(item)=='footprint':
        geometry.extend((str(p[1]),str(p[2]),str(p[3]),_geometry_signature(p)) for p in sx.children(item,'pad'))
        geometry.extend(normalize(n) for n in sx.children(item) if sx.tag(n)=='model' or sx.tag(n).startswith('fp_'))
        geometry.extend(normalize(n) for n in sx.children(item,'property'))
    return tuple(sorted(geometry,key=repr))


def _write_hierarchy(source, selected, folder, stem, max_depth=None):
    if max_depth is not None and (isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0):
        raise MergeError('Selection depth must be a nonnegative integer or unlimited.')
    base_depth = selected.old_path.count('/')
    descendants = [s for s in source.sheets
                   if (s.old_path == selected.old_path or s.old_path.startswith(selected.old_path+'/'))
                   and (max_depth is None or s.old_path.count('/')-base_depth <= max_depth)]
    root_uuid = sx.value(selected.tree,'uuid')
    paths = {s.old_path: '/'+root_uuid+s.old_path[len(selected.old_path):] for s in descendants}
    names = {s.old_path: (stem+'.kicad_sch' if s is selected else 'fusion_sections/sheet_%03d.kicad_sch'%i)
             for i,s in enumerate(descendants)}
    for s in descendants:
        tree = copy.deepcopy(s.tree)
        for node in sx.walk(tree):
            for index,value in enumerate(node):
                if isinstance(value,sx.Quoted):node[index]=sx.q(str(value).replace('${VARIANT}',source.selected_variant))
        sx.remove(tree,'sheet_instances')
        if s is selected: tree.append(['sheet_instances',['path',sx.q('/'),['page',sx.q('1')]]])
        for symbol,record in zip(sx.children(tree,'symbol'),s.symbols):
            for flag,value in effective_board_flags(record).items():sx.put(symbol,flag,value)
            sx.put(symbol,'instances',['project',sx.q(stem),['path',sx.q(paths[s.old_path]),
                       ['reference',sx.q(record.old_ref)],['unit',str(record.unit)]]])
        child_nodes = list(zip(sx.children(tree,'sheet'),s.sub_sheets))
        for node,(_,child) in child_nodes:
            if child.old_path not in paths:
                tree.remove(node)
                continue
            target = folder/names[child.old_path]
            relative = os.path.relpath(target, (folder/names[s.old_path]).parent).replace('\\','/')
            field = sx.prop(node,'Sheetfile') or sx.prop(node,'Sheet file')
            field[2] = sx.q(relative)
            sx.put(node,'instances',['project',sx.q(stem),['path',sx.q(paths[s.old_path]),['page',sx.q(str(descendants.index(child)+1))]]])
        output = folder/names[s.old_path]; output.parent.mkdir(parents=True,exist_ok=True); sx.save(output,tree)
    return paths


def _build(spec, sheet_path, region, cli_path, stage, max_depth=None):
    original_root=Path(spec.project).resolve().parent
    snapshot=fingerprint(original_root)
    source = discover(spec,new_uuid())
    prepare_board(source)
    selected = next((s for s in source.sheets if s.old_path == canonical_path(sheet_path)),None)
    if selected is None: raise MergeError('The exact sheet UUID instance no longer exists.')
    if selected is source.sheets[0]: raise MergeError('Choose a subsheet instance; use ordinary Fusion import for a full project.')
    root = source.project_file.parent
    if any(root != s.source_path.parent and root not in s.source_path.parents for s in source.sheets):
        raise MergeError('External schematic files must be copied into the source project before extracting a section.')
    cli = KiCadCLI(cli_path)
    # Export an effective full hierarchy first: parent wiring is the authority.
    full=stage/'full';copy_project(root,full)
    if fingerprint(full)!=snapshot: raise MergeError('Copied source differs from the reviewed snapshot; retry after saving.')
    _write_hierarchy(source,source.sheets[0],full,source.project_file.stem)
    output = stage/'candidate'; copy_project(root,output)
    if fingerprint(output)!=snapshot: raise MergeError('Copied source differs from the reviewed snapshot; retry after saving.')
    stem = source.project_file.stem
    paths = _write_hierarchy(source,selected,output,stem,max_depth)
    project = copy.deepcopy(source.project)
    for container in (project,project.setdefault('schematic',{})):
        for key in ('variants','variant','current_variant'): container.pop(key,None)
    for key,value in project.get('text_variables',{}).items():
        project['text_variables'][key]=str(value).replace('${VARIANT}',source.selected_variant)
    (full/source.project_file.name).write_text(json.dumps(project,indent=2),encoding='utf-8')
    expected=cli.export_netlist(full/source.schematic_file.name,stage/'full.xml')
    (output/source.project_file.name).write_text(json.dumps(project,indent=2),encoding='utf-8')
    extracted = cli.export_netlist(output/source.schematic_file.name,stage/'section.xml')
    records = [r for s in source.sheets if s.old_path in paths for r in s.symbols]
    refs = {r.old_ref for r in records}
    omitted_refs = {r.old_ref for s in source.sheets
                    if s.old_path.startswith(selected.old_path+'/') and s.old_path not in paths
                    for r in s.symbols}
    if any(any(ref in refs for ref, _ in endpoints) and
           any(ref in omitted_refs for ref, _ in endpoints)
           for endpoints in expected.nets.values()):
        raise MergeError('Selected pages share electrical nets with descendants excluded by the depth limit.')
    if set(extracted.components) != set(expected.components)&refs:
        raise MergeError('Extracted component inventory differs from the full source; inherited assembly flags are unsupported.')
    for ref,component in extracted.components.items():
        if any(component.get(key)!=expected.components[ref].get(key) for key in ('footprint','value')):
            raise MergeError('Extracted effective component value or footprint differs from the full source: '+ref)
    before = _partitions(expected,refs); after = _partitions(extracted,refs)
    if set(before) != set(after):
        raise MergeError('This section depends on wiring outside its sheet hierarchy. Its standalone electrical partitions differ; add explicit sheet boundary connectivity before extraction.')
    names = {before[key]:after[key] for key in before}
    board = copy.deepcopy(source.board)
    for node in sx.walk(board):
        for index,value in enumerate(node):
            if isinstance(value,sx.Quoted):node[index]=sx.q(str(value).replace('${VARIANT}',source.selected_variant))
    unknown={sx.tag(n) for n in sx.children(board)}-HEADER-ITEMS
    if unknown: raise MergeError('Unsupported PCB objects cannot be discarded: '+', '.join(sorted(unknown)))
    bounds = _native_bounds(source.pcb_file,cli)
    wanted_paths = {canonical_path(r.old_path) for r in records}
    retained=[]; excluded=[]; counts={}; selected_fp=[]
    geometry_tags=ITEMS-{'group'}
    selected_nets=set(names)
    for item in board[1:]:
        tag=sx.tag(item)
        if tag not in geometry_tags: continue
        ident=sx.value(item,'uuid') or sx.value(item,'tstamp')
        if ident not in bounds: raise MergeError('Unsupported geometry without a native bounding box: '+tag)
        relation=_relation(bounds[ident],region)
        record=source.link_map.get(canonical_path(sx.value(item,'path'))) if tag=='footprint' else None
        is_selected=record is not None and canonical_path(record.old_path) in wanted_paths
        if is_selected and relation!='inside': raise MergeError('The rectangle must fully contain every selected footprint, with space around its graphics and pads.')
        if tag=='footprint' and not is_selected and relation!='outside': raise MergeError('The region intersects a footprint belonging to another sheet or a board-only footprint. Choose a separate region.')
        if relation=='boundary': raise MergeError('The rectangle intersects '+tag+' '+ident+'. Cross-boundary copper, zones and drawings cannot be clipped; move the region boundary.')
        if relation=='outside': excluded.append(ident); continue
        if tag=='footprint': selected_fp.append(item)
        else:
            net=sx.child(item,'net')
            if net is not None and len(net)>1 and str(net[1])!='0':
                name=net_name(item,net_table(board))
                if name not in selected_nets: raise MergeError('Region contains copper on an outside-only or unproven net: '+name)
        retained.append(item); counts[tag]=counts.get(tag,0)+1
    if not selected_fp: raise MergeError('Selected sheet subtree has no placed PCB footprints.')
    # A multi-unit component split between hierarchies cannot be extracted safely.
    for r in records:
        if any(other.old_ref==r.old_ref and other.sheet.old_path not in paths for other in source.symbols):
            raise MergeError('A multi-unit component spans the selected and excluded sheets: '+r.old_ref)
    retained_ids={sx.value(n,'uuid') for item in retained for n in sx.walk(item) if sx.value(n,'uuid')}
    group_by_id={sx.value(g,'uuid'):g for g in sx.children(board,'group')}
    def group_leaves(ident,ancestors=()):
        if ident in ancestors: raise MergeError('Cyclic PCB groups are unsupported.')
        if ident not in group_by_id:return {ident}
        leaves=set()
        for member in sx.child(group_by_id[ident],'members',[])[1:]:
            leaves.update(group_leaves(str(member),ancestors+(ident,)))
        return leaves
    groups=[]
    for ident,group in group_by_id.items():
        members=group_leaves(ident);overlap=members&retained_ids
        if overlap and overlap!=members: raise MergeError('A PCB group crosses the section boundary; separate it in a source copy first.')
        if overlap: groups.append(group)
    metadata=[n for n in board[1:] if sx.tag(n) not in geometry_tags|{'net','group'}]
    for n in retained:
        if sx.tag(n)=='footprint':
            old=canonical_path(source.link_map[canonical_path(sx.value(n,'path'))].old_path)
            owning=old.rsplit('/',1)[0]; sx.put(n,'path',sx.q(paths[owning]+'/'+old.rsplit('/',1)[1]))
        for child in sx.walk(n):
            layer=sx.child(child,'layer')
            if layer is not None and len(layer)>1 and str(layer[1])=='Edge.Cuts': layer[1]=sx.q('Dwgs.User')
            net=sx.child(child,'net')
            if net is not None:
                old_name=net_name(child,net_table(board))
                if old_name:
                    if old_name not in names: raise MergeError('A retained pad or object is attached to an unproven outside net: '+old_name)
                    if len(net)>2: net[2]=sx.q(names[old_name])
                    elif isinstance(net[1],sx.Quoted): net[1]=sx.q(names[old_name])
    netdefs=[['net','0',sx.q('')]]
    for net in sx.children(board,'net'):
        if len(net)>2 and str(net[2]) in names: netdefs.append(['net',net[1],sx.q(names[str(net[2])])])
    result=['kicad_pcb',*metadata,*netdefs,*retained,*groups]
    a,b,c,d=region
    result.append(['gr_rect',['start',str(a),str(b)],['end',str(c),str(d)],['stroke',['width','0.05'],['type','default']],['fill','none'],['layer',sx.q('Edge.Cuts')],['uuid',sx.q(new_uuid())]])
    signatures={sx.value(n,'uuid') or sx.value(n,'tstamp'):_geometry_signature(n) for n in retained}
    sx.save(output/source.pcb_file.name,result)
    # Native load, zone refill, parity and physical findings all run off-process.
    candidate_bounds=_native_bounds(output/source.pcb_file.name,cli)
    for ident in signatures:
        if ident not in candidate_bounds or _relation(candidate_bounds[ident],region)!='inside':
            raise MergeError('Effective variant geometry is outside the selected rectangle: '+ident)
    drc=cli.drc(output/source.pcb_file.name,output/'section-drc.json')
    rewritten=sx.load(output/source.pcb_file.name)
    by_id={sx.value(n,'uuid') or sx.value(n,'tstamp'):n for n in sx.children(rewritten)}
    for ident,signature in signatures.items():
        if ident not in by_id or _geometry_signature(by_id[ident])!=signature:
            raise MergeError('Native refill changed retained geometry '+ident+'; nothing published.')
    ports=[{'source_net':name,'selected_pins':sorted([list(ep) for ep in endpoints if ep[0] in refs]),
            'outside_pins':sorted([list(ep) for ep in endpoints if ep[0] not in refs])}
           for name,endpoints in expected.nets.items() if any(ep[0] in refs for ep in endpoints) and any(ep[0] not in refs for ep in endpoints)]
    counts['group']=len(groups)
    report={'source_alias':source.alias,'source_project':str(source.project_file),'selected_variant':source.selected_variant,
            'source_spec':asdict(spec),
            'sheet_path':selected.old_path,'display_path':selected.display_path,'sheet_file':str(selected.source_path),
            'descendant_sheets':len(paths),'max_depth':max_depth,
            'region_mm':list(region),'counts':counts,'excluded_geometry_count':len(excluded),
            'boundary_ports':ports,'drc_findings':len(drc.get('violations',[])),
            'unconnected_findings':len(drc.get('unconnected_items',[])),
            'manufacturing_approved':False,'electrical_partitions_verified':True,'native_parity_verified':True,'retained_geometry_verified':True,
            'outline':'New rectangular Edge.Cuts; fully contained original outlines retained on Dwgs.User.'}
    (output/'section-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return output,report


def preview_section(spec, sheet_path, region_mm, cli_path='', max_depth=None):
    validate_source_aliases([spec]); region=_region(region_mm)
    root=Path(spec.project).resolve().parent; hashes=fingerprint(root)
    with tempfile.TemporaryDirectory(prefix='fusion-section-') as temp:
        _,report=_build(spec,sheet_path,region,cli_path,Path(temp),max_depth)
    if fingerprint(root)!=hashes: raise MergeError('Source changed during section preview; retry after saving.')
    return {'spec':asdict(spec),'sheet_path':canonical_path(sheet_path),'region_mm':list(region),
            'cli_path':cli_path,'max_depth':max_depth,'hashes':hashes,'report':report}


def apply_section(plan,new_directory):
    from .engine import publish
    spec=SourceSpec(**plan['spec']); validate_source_aliases([spec])
    root=Path(spec.project).resolve().parent; dest=Path(new_directory).resolve()
    if dest.exists() or dest==root or root in dest.parents: raise MergeError('Choose a new section folder outside the original project.')
    if fingerprint(root)!=plan['hashes']: raise MergeError('Source changed since preview; preview again.')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-section-',dir=dest.parent) as temp:
        candidate,report=_build(spec,plan['sheet_path'],_region(plan['region_mm']),plan['cli_path'],Path(temp),
                                plan.get('max_depth'))
        if fingerprint(root)!=plan['hashes']: raise MergeError('Source changed during extraction; nothing published.')
        with zipfile.ZipFile(candidate/'original-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in project_files(root): archive.write(path,str(path.relative_to(root)))
        (candidate/'original-source-hashes.json').write_text(json.dumps(plan['hashes'],indent=2),encoding='utf-8')
        if fingerprint(root)!=plan['hashes']: raise MergeError('Source changed while archiving; nothing published.')
        publish(candidate,dest)
    def relocate(value):
        path=Path(value).expanduser()
        if path.is_absolute():
            try:return str(dest/path.resolve().relative_to(root))
            except ValueError:pass
        return value
    return SourceSpec(project=str(dest/Path(spec.project).with_suffix('.kicad_pro').name),alias=spec.alias,
                      variant='<Default>',path_variables={key:relocate(value) for key,value in spec.path_variables.items()},
                      path_remaps={key:relocate(value) for key,value in spec.path_remaps.items()},
                      section_origin={'project':str(Path(spec.project).resolve()),
                                      'sheet_path':plan['sheet_path'], 'region_mm':list(plan['region_mm']),
                                      **({'max_depth':plan['max_depth']} if plan.get('max_depth') is not None else {})},
                      extra_asset_paths=[*[relocate(value) for value in spec.extra_asset_paths],str(dest/'section-report.json'),str(dest/'section-drc.json'),
                                         str(dest/'original-source.zip'),str(dest/'original-source-hashes.json')])


def _schematic_selection(source, sheet_paths, allow_root=False):
    paths = [canonical_path(path) for path in sheet_paths]
    if not paths or len(paths) > 100 or len(set(paths)) != len(paths):
        raise MergeError('Select 1–100 distinct subsheet occurrences.')
    selected = []
    for path in paths:
        candidates = source.sheets if allow_root else source.sheets[1:]
        sheet = next((s for s in candidates if s.old_path == path), None)
        if sheet is None:
            raise MergeError('The selected subsheet occurrence no longer exists: '+path)
        if any(other != path and path.startswith(other+'/') for other in paths):
            raise MergeError('Choose either a parent subsheet or its descendant, not both.')
        selected.append(sheet)
    return selected


def _build_schematic_sections(spec, sheet_paths, cli_path, stage, max_depth=None, allow_root=False):
    source = discover(spec, new_uuid(), require_board=False)
    selected = _schematic_selection(source, sheet_paths, allow_root)
    root = source.project_file.parent
    if any(root != s.source_path.parent and root not in s.source_path.parents for s in source.sheets):
        raise MergeError('Copy external schematic files into the source project before extracting subsheets.')
    snapshot = fingerprint(root)
    full = stage/'full'; copy_project(root, full)
    if fingerprint(full) != snapshot:
        raise MergeError('Source changed while copying the selected hierarchy.')
    project = copy.deepcopy(source.project)
    for container in (project, project.setdefault('schematic', {})):
        for key in ('variants', 'variant', 'current_variant'):
            container.pop(key, None)
    for key, value in project.get('text_variables', {}).items():
        project['text_variables'][key] = str(value).replace('${VARIANT}', source.selected_variant)
    _write_hierarchy(source, source.sheets[0], full, source.project_file.stem)
    (full/source.project_file.name).write_text(json.dumps(project, indent=2), encoding='utf-8')
    cli = KiCadCLI(cli_path)
    expected = cli.export_netlist(full/source.schematic_file.name, stage/'full.xml')
    candidate = stage/'candidate'; candidate.mkdir()
    reports = []
    for index, sheet in enumerate(selected, 1):
        folder = candidate/f'section_{index:03d}'
        copy_project(root, folder)
        if fingerprint(folder) != snapshot:
            raise MergeError('Source changed while copying a subsheet.')
        paths = _write_hierarchy(source, sheet, folder, source.project_file.stem, max_depth)
        (folder/source.project_file.name).write_text(json.dumps(project, indent=2), encoding='utf-8')
        # A schematic-only source must never accidentally carry the full source PCB.
        for pcb in folder.rglob('*.kicad_pcb'):
            pcb.unlink()
        extracted = cli.export_netlist(folder/source.schematic_file.name, folder/'section-netlist.xml')
        records = [r for s in source.sheets if s.old_path in paths for r in s.symbols]
        refs = {r.old_ref for r in records}
        omitted_refs = {r.old_ref for s in source.sheets
                        if s.old_path.startswith(sheet.old_path+'/') and s.old_path not in paths
                        for r in s.symbols}
        if any(any(ref in refs for ref, _ in endpoints) and
               any(ref in omitted_refs for ref, _ in endpoints)
               for endpoints in expected.nets.values()):
            raise MergeError('Selected pages share electrical nets with descendants excluded by the depth limit.')
        if any(r.old_ref in refs and r.sheet.old_path not in paths for r in source.symbols):
            raise MergeError('A multi-unit component crosses the selected hierarchy boundary.')
        if set(extracted.components) != set(expected.components)&refs:
            raise MergeError('Extracted component inventory differs from the full source.')
        for ref, component in extracted.components.items():
            if any(component.get(key) != expected.components[ref].get(key) for key in ('value', 'footprint')):
                raise MergeError('Extracted effective component differs from the full source: '+ref)
        if set(_partitions(expected, refs)) != set(_partitions(extracted, refs)):
            raise MergeError('Subsheet depends on outside wiring; its standalone electrical partitions differ.')
        report = {'sheet_path': sheet.old_path, 'display_path': sheet.display_path,
                  'source_spec':asdict(spec), 'selected_variant':source.selected_variant,
                  'directory': folder.name, 'components': len(extracted.components),
                  'descendant_sheets': len(paths), 'max_depth': max_depth, 'layout_included': False,
                  'electrical_partitions_verified': True}
        reports.append(report)
        (folder/'schematic-section-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if fingerprint(root) != snapshot:
        raise MergeError('Source changed during extraction; nothing published.')
    return candidate, reports


def preview_schematic_sections(spec, sheet_paths, cli_path='', max_depth=None, allow_root=False):
    """Review multiple exact subtrees without a PCB or a physical rectangle."""
    validate_source_aliases([spec])
    root = Path(spec.project).resolve().parent; hashes = fingerprint(root)
    with tempfile.TemporaryDirectory(prefix='fusion-schematic-sections-') as temp:
        _, reports = _build_schematic_sections(spec, sheet_paths, cli_path, Path(temp), max_depth, allow_root)
    if fingerprint(root) != hashes:
        raise MergeError('Source changed during preview; save and preview again.')
    return {'spec': asdict(spec), 'sheet_paths': [r['sheet_path'] for r in reports],
            'cli_path': cli_path, 'max_depth': max_depth, 'allow_root': allow_root,
            'hashes': hashes, 'report': reports}


def apply_schematic_sections(plan, new_directory):
    """Publish reviewed schematic-only sources; originals remain unchanged."""
    from .engine import publish
    spec = SourceSpec(**plan['spec']); validate_source_aliases([spec])
    root = Path(spec.project).resolve().parent; dest = Path(new_directory).resolve()
    if dest.exists() or dest == root or root in dest.parents:
        raise MergeError('Choose a new section folder outside the source project.')
    if fingerprint(root) != plan['hashes']:
        raise MergeError('Source changed since preview; preview again.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-schematic-sections-', dir=dest.parent) as temp:
        candidate, reports = _build_schematic_sections(spec, plan['sheet_paths'], plan['cli_path'], Path(temp),
                                                      plan.get('max_depth'), plan.get('allow_root', False))
        with zipfile.ZipFile(candidate/'original-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in project_files(root):
                archive.write(path, str(path.relative_to(root)))
        (candidate/'original-source-hashes.json').write_text(json.dumps(plan['hashes'], indent=2), encoding='utf-8')
        if fingerprint(root) != plan['hashes']:
            raise MergeError('Source changed during archival; nothing published.')
        publish(candidate, dest)
    result = []
    for index, report in enumerate(reports, 1):
        suffix = f'_{index}'
        folder = dest/report['directory']
        def relocate(value):
            path = Path(value).expanduser()
            if path.is_absolute():
                try:
                    return str(folder/path.resolve().relative_to(root))
                except ValueError:
                    pass
            return value
        result.append(SourceSpec(str(folder/source_name(spec)), spec.alias[:24-len(suffix)]+suffix,
            variant='<Default>', path_variables={k: relocate(v) for k,v in spec.path_variables.items()},
            path_remaps={k: relocate(v) for k,v in spec.path_remaps.items()},
            extra_asset_paths=[*[relocate(v) for v in spec.extra_asset_paths], str(folder/'schematic-section-report.json')],
            section_origin={'project': str(Path(spec.project).resolve()), 'sheet_path': report['sheet_path'], 'region_mm': None,
                            **({'max_depth':report['max_depth']} if report.get('max_depth') is not None else {})}))
    return result


def source_name(spec):
    return Path(spec.project).with_suffix('.kicad_pro').name
