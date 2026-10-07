"""Non-destructive merge transaction and verification orchestration."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import copy
import csv
import ctypes
import errno
import fnmatch
import json
import hashlib
import os
import re
import shutil
import tempfile
import time
import zipfile

from . import sexpr as sx
from .assets import audit_assets, sha256, prepare_assets
from .board import prepare_board, arrange, compose, verify_board, geometry_signature
from .model import MergeError, Options
from .layers import plan_layers
from .netlist import KiCadCLI, compare_netlists
from .schematic import discover, annotate, make_parent, new_uuid, transform_schematics


def jwrite(path,data):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')


def _settings_without_plot(source):
    setup=copy.deepcopy(sx.child(source.board,'setup',['setup']))
    for key in ('pcbplotparams','aux_axis_origin','grid_origin','stackup'):
        sx.remove(setup,key)
    return {'setup':sx.dumps(setup),
            'design_settings':source.project.get('board',{}).get('design_settings',{}),
            'net_settings':source.project.get('net_settings',{})}


def check_settings(sources,accept_primary,log):
    base=_settings_without_plot(sources[0])
    for s in sources[1:]:
        differences=[key for key,value in _settings_without_plot(s).items() if base[key]!=value]
        if differences:
            message=f'{s.alias}: settings differ from {sources[0].alias}: {", ".join(differences)}.'
            if not accept_primary:
                raise MergeError(message+' Either normalize settings or explicitly select primary-board settings. Layout geometry is preserved, but a single board cannot retain multiple conflicting stackups/rule sets.')
            log('WARNING: '+message+' Output uses the primary board setup; review archived originals.')
    for s in sources:
        dru=s.project_file.with_suffix('.kicad_dru')
        if dru.is_file():
            data=dru.read_bytes()
            s.hashes[str(dru)]=hashlib.sha256(data).hexdigest()
            text=data.decode('utf-8-sig')
            # Ignore a header-only custom-rule file, not any real custom rule.
            if '(rule' in text:
                if not accept_primary:
                    raise MergeError(f'{s.alias}: custom .kicad_dru rules exist. Explicitly acknowledge manual rule migration; automatic rewriting of rule expressions is intentionally disabled.')
                log(f'WARNING: {s.alias}: custom rules are archived, not activated in the output. Port and validate them before manufacturing.')
        classes=s.project.get('net_settings',{}).get('classes',[])
        s.class_map={c['name']:s.alias+'__'+c['name'] for c in classes if 'name' in c}


def analyse(options:Options,log=lambda m:None):
    options.validate()
    root_uuid=new_uuid()
    sources=[]
    for index,spec in enumerate(options.sources,1):
        log(f'[{index}/{len(options.sources)}] Reading {spec.alias} ({spec.kind})…')
        s=discover(spec,root_uuid,log)
        prepare_board(s)
        sources.append(s)
    plan_layers(sources,options.acknowledge_layer_remap,log)
    check_settings(sources,options.accept_primary_settings,log)
    annotate(sources,options.annotation,options.block_size)
    placement=arrange(sources,options.columns,options.gap_mm)
    report={'sources':[], 'placements':placement, 'annotation':options.annotation}
    for s in sources:
        report['sources'].append({'alias':s.alias,'project':str(s.project_file),'sheets':len(s.sheets),
            'kind':s.spec.kind, 'section_origin':copy.deepcopy(s.spec.section_origin),
            'footprints':len(sx.children(s.board,'footprint')),'symbols':len(s.symbols),
            'translation_mm':s.translation,'reference_map':s.ref_map,
            'selected_variant':s.selected_variant,'detected_variants':s.variant_names,'variant_changes':s.variant_changes,
            'copper_map':s.layer_map,
            'unused_planar_layers':[name for name in s.target_copper_layers
                                    if name not in s.layer_map.values()],
            'stackup_donor':s.stackup_donor,'layer_notes':s.layer_notes})
    return root_uuid,sources,report


def build_project(sources,name):
    result=copy.deepcopy(sources[0].portable_project or sources[0].project)
    result.setdefault('schematic',{})['variants']=[]
    result['schematic'].pop('current_variant',None)
    result['schematic'].pop('variant',None)
    result['schematic'].pop('top_level_sheets',None)
    result.setdefault('meta',{})['filename']=name+'.kicad_pro'
    result['sheets']=[]
    result['text_variables']={}
    result.pop('boards',None)
    result.pop('board_presets',None)
    for s in sources:
        for k,v in (s.portable_project or s.project).get('text_variables',{}).items():
            text=str(v)
            for kk in s.project.get('text_variables',{}):
                text=text.replace('${'+kk+'}','${'+s.alias+'__'+kk+'}')
            if s.portable_project is None:
                text=text.replace('${KIPRJMOD}',s.project_file.parent.as_posix())
            if s.selected_variant!='<Default>':
                text=text.replace('${VARIANT}',s.selected_variant)
            result['text_variables'][s.alias+'__'+k]=text
    settings=result.setdefault('board',{}).setdefault('design_settings',{})
    settings['drc_exclusions']=[]
    settings.pop('drc_exclusions_comment',None)
    if isinstance(result.get('erc'),dict):
        result['erc']['erc_exclusions']=[]
    result.setdefault('pcbnew',{})['last_paths']={}
    # Frozen namespaced classes. Patterns are expanded to exact names for current
    # nets: this avoids prefix heuristics for hierarchy-generated net names.
    ns=result.setdefault('net_settings',{})
    default=next((copy.deepcopy(c) for c in ns.get('classes',[]) if c.get('name')=='Default'),None)
    ns['classes']=[default] if default else []
    ns['netclass_patterns']=[]
    ns['netclass_assignments']={}
    ns['net_colors']={}
    for s in sources:
        original=s.project.get('net_settings',{})
        for cls in original.get('classes',[]):
            item=copy.deepcopy(cls)
            item['name']=s.class_map[item['name']]
            ns['classes'].append(item)
        for old,new in s.net_map.items():
            assigned=[]
            explicit=(original.get('netclass_assignments') or {}).get(old,[])
            if isinstance(explicit,str):
                explicit=[explicit]
            assigned.extend(explicit)
            for pat in original.get('netclass_patterns',[]):
                pattern=pat.get('pattern','')
                if '[' in pattern or ']' in pattern or '\\' in pattern:
                    raise MergeError(f'{s.alias}: complex netclass pattern {pattern!r} needs manual normalization to scalar/*/? patterns before merge.')
                if fnmatch.fnmatchcase(old,pattern):
                    assigned.append(pat.get('netclass','Default'))
            if not assigned and 'Default' in s.class_map:
                assigned=['Default']
            for cls in dict.fromkeys(assigned):
                if cls not in s.class_map:
                    raise MergeError(f'{s.alias}: undefined netclass {cls!r}.')
                undecorated = re.sub(r'~\{[^{}]*\}', '', new).replace('{slash}','/')
                if any(ch in undecorated for ch in '[]{}*?\\'):
                    raise MergeError(f'{s.alias}: net name {new!r} needs literal/bus netclass handling not supported in this release. Normalize the bus/net labels in a source copy first; no potentially overmatching rule will be emitted.')
                ns['netclass_patterns'].append({'netclass':s.class_map[cls],'pattern':new})
                ns['netclass_assignments'].setdefault(new,[]).append(s.class_map[cls])
            if old in (original.get('net_colors') or {}):
                ns['net_colors'][new]=original['net_colors'][old]
    return result


def _snapshot(sources,stage):
    with zipfile.ZipFile(stage/'source-backup.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        manifest=[]
        for s in sources:
            for i,p in enumerate(sorted(s.files,key=str)):
                p=Path(p)
                digest=sha256(p)
                expected=s.hashes.get(str(p))
                if expected is not None and expected!=digest:
                    raise MergeError(f'Source changed while merging: {p}. Save/stop editing and run again.')
                s.hashes[str(p)]=digest
                # Unique per-file keys preserve even external hierarchy/assets;
                # manifest records the exact original path for restoration.
                arc=f'{s.alias}/{i:05d}_{p.name}'
                archive.write(p,arc)
                manifest.append({'source':s.alias,'original_path':str(p),'archive_member':arc,'sha256':digest})
        archive.writestr('manifest.json',json.dumps(manifest,indent=2))
    return manifest


def _assert_sources_unchanged(sources):
    for s in sources:
        for p,digest in s.hashes.items():
            if not Path(p).is_file() or sha256(p)!=digest:
                raise MergeError(f'Source changed while merging: {p}. The output was not published.')


def publish(stage,dest):
    """Atomic, no-replace directory publish on Windows and Linux."""
    stage,dest=Path(stage),Path(dest)
    if os.name=='nt':
        os.rename(stage,dest)  # Windows refuses an existing destination.
        return
    libc=ctypes.CDLL(None,use_errno=True)
    renameat2=getattr(libc,'renameat2',None)
    if renameat2 is not None:
        renameat2.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        renameat2.restype=ctypes.c_int
        if renameat2(-100,os.fsencode(stage),-100,os.fsencode(dest),1)!=0: # RENAME_NOREPLACE
            err=ctypes.get_errno()
            raise OSError(err,os.strerror(err),str(dest))
        return
    raise MergeError('Atomic no-overwrite publishing is implemented for Windows/Linux in this release; this OS is not supported.')


def export_selected_netlist(source,cli,destination):
    """Export a native base-state view of the explicitly selected variant.

    KiCad 10 XML export can omit variant field overrides. Keep the source
    unchanged and let the real CLI parse a disposable effective hierarchy.
    """
    if source.selected_variant=='<Default>':
        return cli.export_netlist(source.schematic_file,destination)
    from .variants import set_field
    with tempfile.TemporaryDirectory(prefix='fusion-native-selection-') as folder:
        folder=Path(folder)
        targets={sheet.old_path:folder/(source.schematic_file.name if i==0 else f'view_sheet_{i:03}.kicad_sch')
                 for i,sheet in enumerate(source.sheets)}
        for sheet in source.sheets:
            tree=copy.deepcopy(sheet.tree)
            for child_node,child in zip(sx.children(tree,'sheet'),[sub for _,sub in sheet.sub_sheets]):
                key='Sheetfile' if sx.prop(child_node,'Sheetfile') is not None else 'Sheet file'
                set_field(child_node,key,targets[child.old_path].name)
            for node in sx.walk(tree):
                if sx.tag(node) in {'embedded_files','data'}:continue
                for i,value in enumerate(node):
                    if isinstance(value,sx.Quoted):
                        node[i]=sx.q(str(value).replace('${VARIANT}',source.selected_variant).replace('${KIPRJMOD}',source.project_file.parent.as_posix()))
            sx.save(targets[sheet.old_path],tree)
        project=copy.deepcopy(source.project)
        schematic=project.setdefault('schematic',{});schematic['variants']=[]
        schematic.pop('variant',None);schematic.pop('current_variant',None)
        for key,value in project.get('text_variables',{}).items():
            project['text_variables'][key]=str(value).replace('${VARIANT}',source.selected_variant).replace('${KIPRJMOD}',source.project_file.parent.as_posix())
        jwrite(folder/source.project_file.name,project)
        return cli.export_netlist(folder/source.schematic_file.name,destination)


def merge(options:Options,log=lambda m:None,cli=None):
    messages=[]
    def emit(msg):
        messages.append(msg); log(msg)
    root_uuid,sources,summary=analyse(options,emit)
    dest=Path(options.destination).expanduser().resolve()
    if dest.exists():
        raise MergeError('Output folder already exists. Choose a new folder; existing projects are never overwritten.')
    if not dest.parent.is_dir():
        raise MergeError('The output parent folder does not exist.')
    for s in sources:
        if dest==s.project_file.parent or s.project_file.parent in dest.parents:
            raise MergeError('Choose an output folder outside every source-project directory.')
        for p in s.files:
            digest=sha256(p)
            if str(p) in s.hashes and s.hashes[str(p)]!=digest:
                raise MergeError(f'Source changed during preflight: {p}. Save and run again.')
            s.hashes[str(p)]=digest
    cli=cli or KiCadCLI(options.cli_path,emit)
    stage=Path(tempfile.mkdtemp(prefix='.'+options.name+'-fusion-',dir=dest.parent))
    report={'plugin_version':'0.9.5','kicad_cli_version':cli.version,
            'validation_backend':'native-kicad-cli' if isinstance(cli,KiCadCLI) else 'injected-adapter-NOT-native-certified',
            'options':options.to_dict(),
            'summary':summary,'manufacturing_ready':False}
    try:
        reports=stage/'reports'; reports.mkdir()
        # Repeated instances share native validation of the same saved input,
        # but never share mutable schematic/PCB trees or output identities.
        netlist_cache={}
        for index,s in enumerate(sources,1):
            emit(f'[{index}/{len(sources)}] Validating {s.alias} ({s.spec.kind})…')
            key=(str(s.project_file.resolve()), s.selected_variant,
                 tuple(sorted(s.hashes.items())),
                 json.dumps({'variables':s.spec.path_variables,'remaps':s.spec.path_remaps},sort_keys=True))
            target=reports/(s.alias+'-source.xml')
            if key in netlist_cache:
                validated,xml_file=netlist_cache[key]
                s.xml=copy.deepcopy(validated)
                shutil.copy2(xml_file,target)
            else:
                s.xml=export_selected_netlist(s,cli,target)
                netlist_cache[key]=(copy.deepcopy(s.xml),target)
            unknown=set(s.xml.components)-set(s.ref_map)
            if unknown:
                raise MergeError(f'{s.alias}: exported references are not present in the parsed source instance table: {sorted(unknown)[:8]}')
        report['native_source_exports']=len(netlist_cache)
        from .bom_fields import inventory,grouped_bom,export_csv
        bom_input=inventory(sources)
        prepare_assets(sources,stage,emit,strict=options.strict_assets,copy_assets=options.copy_assets)
        # Initial .pro must exist before exporting the combined hierarchy so
        # project variables are evaluated in the correct project context.
        jwrite(stage/(options.name+'.kicad_pro'),build_project(sources,options.name))
        page=2
        for s in sources:
            page=transform_schematics(s,stage,options.name,page)
        parent=make_parent(sources,options.name,root_uuid)
        sx.save(stage/(options.name+'.kicad_sch'),parent)
        merged=cli.export_netlist(stage/(options.name+'.kicad_sch'),reports/'combined.xml')
        report['connectivity']=compare_netlists(sources,merged)
        jwrite(stage/(options.name+'.kicad_pro'),build_project(sources,options.name))
        board=compose(sources,merged,options.outline,options.margin_mm)
        report['footprints']=verify_board(board,sources,merged)
        field_rows=inventory(sources)
        reference_map={(source.alias,record.sheet.old_path,record.old_ref):record.new_ref
                       for source in sources for record in source.symbols}
        bom_rows=grouped_bom(bom_input,reference_map=reference_map)
        export_csv(reports/'bom.csv',bom_rows,bom=True)
        export_csv(reports/'fields.csv',field_rows)
        report['bom']={'groups':len(bom_rows),'included_quantity':sum(row['quantity'] for row in bom_rows),
                       'grouping':'exact selected-source fields and assembly flags; DNP separate',
                       'csv':'reports/bom.csv','field_inventory':'reports/fields.csv'}
        pcb=stage/(options.name+'.kicad_pcb')
        sx.save(pcb,board)
        before=geometry_signature(board)
        drc=cli.drc(pcb,reports/'drc.json')
        after=sx.load(pcb)
        verify_board(after,sources,merged)
        if before!=geometry_signature(after):
            raise MergeError('KiCad validation changed a footprint/track/via geometry or identity unexpectedly. Output was not published.')
        report['drc']={'violations':len(drc.get('violations',[])),
                       'unconnected_items':len(drc.get('unconnected_items',[])),
                       'schematic_parity':0,'zones_refilled':True}
        if report['drc']['violations'] or report['drc']['unconnected_items']:
            emit('WARNING: KiCad reported DRC/unconnected items. Read reports/drc.json; this is a merged design, not a manufacturing approval.')
        report['references']=[]
        for s in sources:
            for old,new in s.ref_map.items():
                records=[r for r in s.symbols if r.old_ref==old]
                report['references'].append({'source':s.alias,'old_reference':old,'new_reference':new,
                    'old_paths':[r.old_path for r in records],'new_paths':[r.new_path for r in records],
                    'board_only':old in s.board_ref_map})
        with (reports/'reference-map.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f); writer.writerow(['Source','Original reference','Combined reference','Original UUID paths','Combined UUID paths','Board only'])
            for r in report['references']:
                writer.writerow([r['source'],r['old_reference'],r['new_reference'],';'.join(r['old_paths']),';'.join(r['new_paths']),r['board_only']])
        with (reports/'net-map.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f); writer.writerow(['Source','Original schematic net','Combined net'])
            for s in sources:
                writer.writerows((s.alias,old,new) for old,new in sorted(s.net_map.items()))
        report['assets']=audit_assets(sources,stage)
        jwrite(reports/'asset-manifest.json',report['assets'])
        report['variants']=[{'source':s.alias,'selected':s.selected_variant,'detected':s.variant_names,
                             'changes':s.variant_changes,'strategy':'flatten chosen effective state into new base'} for s in sources]
        jwrite(reports/'variant-selection.json',report['variants'])
        with (reports/'layer-map.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f); writer.writerow(['Source','Input copper layer','Output copper layer','Stackup donor','Unused output planar layers'])
            for s in sources:
                for old,new in s.layer_map.items():
                    writer.writerow([s.alias,old,new,s.stackup_donor,';'.join(s.target_copper_layers[len(s.copper_layers):])])
        report['snapshot_manifest']=_snapshot(sources,stage)
        if isinstance(cli,KiCadCLI):
            from .linked_updates import record_import,_load as load_links,_write as write_links
            record_import(stage,stage/(options.name+'.kicad_pro'),sources,parent,'',after,merged,True,options.cli_path)
            _,links=load_links(stage/(options.name+'.kicad_pro'))
            for source,link in zip(sources,links['links']):
                if any(old!=new for old,new in source.layer_map.items()):
                    link['update_unsupported_reason']='This combined design uses mixed-stack layer/via mapping. Rebuild a reviewed combined candidate to propagate changes.'
                elif options.outline!='rectangle':
                    link['update_unsupported_reason']='This combined design retains source outlines. Rebuild a reviewed combined candidate to propagate changes.'
            write_links(stage,links)
            report['linked_sources']=len(links['links'])
        _assert_sources_unchanged(sources)
        report['messages']=messages
        report['status']=('merged; connectivity and UUID parity checked through KiCad; engineering review required'
                          if isinstance(cli,KiCadCLI) else
                          'TEST/INJECTED ADAPTER RESULT — NOT native KiCad certified; engineering review required')
        jwrite(reports/'merge-report.json',report)
        jwrite(reports/'cli-log.json',cli.commands)
        (stage/'READ-ME-FIRST.txt').write_text(
            'Wayri Project Fusion generated this NEW project. Source files are unchanged.\n'
            'Open '+options.name+'.kicad_pro in KiCad 10.\n'
            'Read reports/merge-report.json, reference-map.csv, net-map.csv and drc.json.\n'
            'Circuits are electrically isolated by source. Add intentional interconnects in the schematic and route them.\n'
            'All source custom .kicad_dru files are archived, not activated. Review and migrate them.\n'
            +('ALL original Edge.Cuts (including slots/cutouts) were moved to Dwgs.User; a new rectangular boundary was generated. Recreate required internal cutouts.\n' if options.outline=='rectangle' else 'Original outlines were retained; multiple islands are NOT automatically one manufacturable board or a finished panel.\n')+
            'Source backups are in source-backup.zip with an original-path/SHA256 manifest.\n'
            'Do not enable reference-only re-association during the first Update PCB from Schematic.\n'
            'The explicitly selected source variants were flattened into the new project. Originals are unchanged.\n'
            'Read layer-map.csv for outer-face copper mapping; imported vias span the full stack. Requalify PTH barrels and impedance.\n'
            'Read asset-manifest.json for copied, embedded, unresolved and external dependencies.\n'
            'No autorouting, cross-project wiring, or automatic custom-rule migration was performed.\n',encoding='utf-8')
        # No temporary CLI backup files are part of the published design.
        for p in stage.glob('*.kicad_pcb-bak'):
            p.unlink()
        from .workspace import check_originals
        check_originals({'selection_originals':getattr(options,'_selection_originals',[])})
        publish(stage,dest)
        emit(f'Created {dest/options.name}.kicad_pro')
        return {'directory':str(dest),'project':str(dest/(options.name+'.kicad_pro')),'report':report}
    except Exception as e:
        failure=dest.parent/(options.name+'-fusion-failure-'+time.strftime('%Y%m%d-%H%M%S')+'.json')
        try:
            jwrite(failure,{'error':str(e),'messages':messages,'cli_commands':getattr(cli,'commands',[]),
                            'source_files_modified_by_plugin':False,'output_published':False})
            emit('Failure details: '+str(failure))
        except OSError:
            pass
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage,ignore_errors=True)
