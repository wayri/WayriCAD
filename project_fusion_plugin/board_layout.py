"""Reviewed PCB-only imports with isolated nets and unchanged target schematics.

Incoming footprints become explicit Board Only items. Their routing is isolated
from schematic nets; native parity still checks every schematic-owned target.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import copy
import json
import math
import re
import shutil
import tempfile

from . import sexpr as sx
from .assets import sha256
from .board import HEADER, ITEMS, board_bounds, fp_reference, net_name, net_table, translate
from .engine import publish
from .insertion import _target_integrity, apply_import
from .layers import copper_sequence, plan_layers, remap_item
from .model import MergeError
from .netlist import KiCadCLI
from .repair import copy_project, fingerprint
from .schematic import new_uuid


def _finding_key(finding):
    return (finding.get('type'), finding.get('severity'),
            tuple(sorted(str(item.get('uuid','')) for item in finding.get('items',[]))))


def _check_findings(before, after):
    """Require no newly introduced native DRC or unconnected findings."""
    from collections import Counter
    for category in ('violations', 'unconnected_items'):
        added=Counter(_finding_key(item) for item in after.get(category,[]))-Counter(
            _finding_key(item) for item in before.get(category,[]))
        if added:
            raise MergeError('Layout import introduces '+category.replace('_',' ')+
                             '; change placement or repair the source and preview again. First finding: '+str(next(iter(added))))


def _import_items(board, target, alias, translation, source_path, candidate):
    """Remap source UUIDs/references/nets and preserve both outside faces."""
    unsupported=[sx.tag(item) for item in sx.children(board) if sx.tag(item) not in HEADER|ITEMS]
    if unsupported or sx.children(board,'image') or sx.child(board,'embedded_files') is not None:
        raise MergeError('Layout-only import does not support image/embedded-file or unknown PCB payloads: '+str(unsupported))
    source=SimpleNamespace(board=board,alias=alias)
    plan_layers([source],True,target_layers=copper_sequence(target),preserve_outer=True,through_vias_only=True)
    table=net_table(board)
    used_names=set(net_table(target).values())
    used_names.update(net_name(item,net_table(target)) for item in sx.walk(target) if sx.child(item,'net') is not None)
    names={net_name(item,table) for item in sx.walk(board) if sx.child(item,'net') is not None}
    names.update(table.values());names.discard('')
    net_map={name:'/'+alias+'/'+name.lstrip('/') for name in names}
    if len(set(net_map.values()))!=len(net_map):
        raise MergeError('Incoming net names become ambiguous when namespaced; rename them explicitly before import.')
    if set(net_map.values()) & used_names:
        raise MergeError('Layout net namespace already exists; choose a different alias.')
    identifiers=sx.declared_uuids(board)
    if len(identifiers)!=len(set(identifiers)):
        raise MergeError('Incoming PCB has duplicate UUIDs.')
    ids={ident:new_uuid() for ident in identifiers}
    target_refs={fp_reference(fp) for fp in sx.children(target,'footprint')}
    refs={}
    for fp in sx.children(board,'footprint'):
        ref=fp_reference(fp)
        if not ref or ref in refs:
            raise MergeError('Incoming PCB references are missing or duplicated.')
        newref=alias+'_'+ref
        if newref in target_refs:
            raise MergeError('Layout reference namespace already exists; choose a different alias.')
        refs[ref]=newref
    direct=any(sx.tag(item)=='net' and len(item)==2 and isinstance(item[1],sx.Quoted) for item in sx.walk(target))
    codes={name:code for code,name in net_table(target).items()}
    next_code=max([int(code) for code in codes.values() if code.isdigit()]+[0])+1
    for name in sorted(net_map.values()):
        codes[name]=str(next_code);next_code+=1
        if not direct:target.append(['net',codes[name],sx.q(name)])
    imported=[];dependencies=[]
    for original in sx.children(board):
        if sx.tag(original) not in ITEMS:continue
        item=copy.deepcopy(original)
        # Source outline becomes a placement guide; the target outline owns fabrication.
        if sx.value(item,'layer')=='Edge.Cuts':sx.put(item,'layer',sx.q('Dwgs.User'))
        for node in sx.walk(item):
            if sx.tag(node) in {'uuid','tstamp','id'} and len(node)>1 and str(node[1]) in ids:
                node[1]=sx.q(ids[str(node[1])])
            elif sx.tag(node)=='members':
                if any(str(ident) not in ids for ident in node[1:]):
                    raise MergeError('Incoming group points to an unknown PCB UUID.')
                node[1:]=[sx.q(ids[str(ident)]) for ident in node[1:]]
            if sx.tag(node)=='net':
                old=net_name(['item',node],table);new=net_map.get(old,'')
                node[:]=['net',sx.q(new)] if direct else ['net',codes.get(new,'0'),sx.q(new)]
            if sx.tag(node)=='zone':
                sx.remove(node,'filled_polygon');sx.remove(node,'fill_segments')
                old=sx.value(node,'net_name')
                if old:sx.put(node,'net_name',sx.q(net_map[old]))
            if sx.tag(node)=='model' and len(node)>1:
                raw=str(node[1])
                if raw.startswith('embedded://'):
                    raise MergeError('Extract embedded model files before layout-only import.')
                if '${' in raw and not raw.startswith('${KIPRJMOD}/'):continue
                resolved=Path(raw.replace('${KIPRJMOD}',str(source_path.parent)))
                if not resolved.is_absolute():resolved=source_path.parent/resolved
                if not resolved.is_file():raise MergeError('Incoming model cannot be resolved: '+raw)
                relative=Path('fusion_layout')/alias/'models'/(sha256(resolved)[:12]+'-'+resolved.name)
                out=candidate/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(resolved,out)
                dependencies.append({'original_path':str(resolved.resolve()),'sha256':sha256(resolved)})
                node[1]=sx.q('${KIPRJMOD}/'+relative.as_posix())
        if sx.tag(item)=='footprint':
            oldref=fp_reference(original);property_node=sx.prop(item,'Reference')
            if property_node is not None:property_node[2]=sx.q(refs[oldref])
            for text in sx.children(item,'fp_text'):
                if len(text)>2 and text[1]=='reference':text[2]=sx.q(refs[oldref])
            sx.remove(item,'path');sx.remove(item,'sheetname');sx.remove(item,'sheetfile')
            sx.remove(item,'variants');sx.remove(item,'variant')
            attr=sx.child(item,'attr') or sx.put(item,'attr')
            for flag in ('board_only','exclude_from_bom'):
                if flag not in attr:attr.append(flag)
        remap_item(item,source)
        translate(item,*translation)
        imported.append(item)
    group_id=new_uuid()
    members=[sx.q(sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')) for item in imported]
    if any(not str(member) for member in members):raise MergeError('Incoming PCB item lacks a UUID.')
    imported.append(['group',sx.q('Layout '+alias),['uuid',sx.q(group_id)],['members',*members]])
    target.extend(imported)
    return {'reference_map':refs,'net_map':net_map,'layer_map':source.layer_map,
            'layer_notes':source.layer_notes,'group_uuid':group_id,'items':len(imported)-1},dependencies


def preview_layout_import(target_project, incoming_pcb, destination, *, alias='Layout',
                          x_mm=20.0,y_mm=20.0,cli_path=''):
    """Create a native-checked PCB-only candidate at an explicit top-left position.

    Original source and target remain untouched. The returned plan uses the
    existing backed-up offline apply transaction; close target editors to apply.
    Newly introduced DRC/unconnected findings prevent a successful preview.
    """
    target_project=Path(target_project).resolve().with_suffix('.kicad_pro')
    source_path=Path(incoming_pcb).resolve();destination=Path(destination).resolve()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,23}',alias):raise MergeError('Use a 1–24 character layout alias starting with a letter.')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and abs(v)<=10000 for v in (x_mm,y_mm)):
        raise MergeError('Layout position must be finite millimetres within ±10000 mm.')
    if source_path.suffix.lower()!='.kicad_pcb' or not source_path.is_file():raise MergeError('Select a saved incoming PCB.')
    root=target_project.parent
    pcb=target_project.with_suffix('.kicad_pcb')
    if not all(path.is_file() for path in (target_project,target_project.with_suffix('.kicad_sch'),pcb)):
        raise MergeError('Layout target needs its saved project, root schematic and PCB.')
    if destination.exists() or destination==root or root in destination.parents:
        raise MergeError('Choose a new review directory outside the target project.')
    original_hashes=fingerprint(root);source_hash=sha256(source_path)
    cli=KiCadCLI(cli_path)
    with tempfile.TemporaryDirectory(prefix='fusion-layout-',dir=destination.parent) as temporary:
        work=Path(temporary);candidate=work/'candidate';baseline=work/'baseline'
        copy_project(root,candidate);copy_project(root,baseline)
        before=cli.drc(baseline/pcb.name,work/'baseline-drc.json')
        target=sx.load(candidate/pcb.name);incoming=sx.load(source_path)
        if sx.tag(incoming)!='kicad_pcb':raise MergeError('Incoming file is not a modern KiCad PCB.')
        box=board_bounds(incoming)
        shift=(round(x_mm-box[0],6),round(y_mm-box[1],6))
        original=copy.deepcopy(target)
        mapping,dependencies=_import_items(incoming,target,alias,shift,source_path,candidate)
        _target_integrity(original,target)
        sx.save(candidate/pcb.name,target)
        expected=sx.load(candidate/pcb.name)
        after=cli.drc(candidate/pcb.name,work/'candidate-drc.json')
        actual=sx.load(candidate/pcb.name)
        _target_integrity(expected,actual)
        _check_findings(before,after)
        schematics={relative:digest for relative,digest in original_hashes.items() if relative.endswith('.kicad_sch')}
        final_hashes=fingerprint(candidate)
        if any(final_hashes.get(relative)!=digest for relative,digest in schematics.items()):
            raise MergeError('Layout import changed a target schematic.')
        if final_hashes.get(target_project.name)!=original_hashes[target_project.name]:
            raise MergeError('Layout import changed target project configuration.')
        report={'mode':'layout_only','include_layout':True,'target_schematic_preserved':True,'native_target_parity_verified':True,
                'native_drc_no_new_findings':True,'incoming_board_only':True,'translation_mm':list(shift),
                'mapping':mapping,'limitations':['Imported nets are isolated; they do not connect to target schematic nets.',
                'Source Edge.Cuts becomes a Dwgs.User guide; target outline and stackup remain authoritative.',
                'Imported board-only footprints do not become schematic symbols or schematic BOM entries.']}
        (candidate/'layout-import-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        if fingerprint(root)!=original_hashes or sha256(source_path)!=source_hash:
            raise MergeError('Source or target changed during layout preview.')
        for dependency in dependencies:
            if sha256(Path(dependency['original_path']))!=dependency['sha256']:raise MergeError('Incoming model changed during preview.')
        publish(candidate,destination)
    return {'target_project':str(target_project),'target_hashes':original_hashes,'source_hashes':[],
            'source_file_hashes':[{'original_path':str(source_path),'sha256':source_hash},*dependencies],
            'candidate_directory':str(destination),'candidate_hashes':fingerprint(destination),'report':report}


def apply_layout_import(plan):
    """Apply only an unchanged layout candidate using Fusion's verified backup."""
    if plan.get('report',{}).get('mode')!='layout_only':raise MergeError('Select a reviewed layout-only plan.')
    return apply_import(plan)
