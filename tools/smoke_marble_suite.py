"""Bounded, reproducible real-Marble core smoke; never edits the source project.

Run ordinary Python tools/smoke_marble_suite.py --project .validation/marble/Marble/design
Each tool runs in a native KiCad child with a 45 second budget. PASS means the
stated operation succeeded, never complete GUI/live IPC or design acceptance.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict,is_dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TOOLS=sorted(p.parent.name for p in ROOT.glob('*_plugin/metadata.json'))

def dump(path,value):
    def encode(obj):
        if hasattr(obj,'as_report'):return obj.as_report()
        if is_dataclass(obj):return {k:v for k,v in vars(obj).items() if k!='board_items'}
        return str(obj)
    Path(path).write_text(json.dumps(value,indent=2,default=encode)+'\n',encoding='utf-8')

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def operation(tool,project,out):
    boardfile=project/'Marble.kicad_pcb';schematic=project/'Marble.kicad_sch'
    out.mkdir(parents=True,exist_ok=True)
    if tool=='bom_studio_plugin':
        sys.path.insert(0,str(ROOT/tool))
        from bomstudio.native import Project
        result=Project(schematic);status=result.status();dump(out/'project.json',status)
        assert len(result.components)>500
        return 'LIMITED',status,'Native schematic hierarchy/BOM inventory; old format blockers preserved; no browser acceptance.'
    if tool=='variant_workbench_plugin':
        from variant_workbench_plugin.kicad_variant_manager import discover_hierarchy,load_project_variants
        documents=discover_hierarchy(schematic)
        variants=load_project_variants(project/'Marble.kicad_pro')
        result={'sheets':len(documents),'objects':sum(len(d.objects) for d in documents),'variants':variants[0]}
        assert result['objects']>500;dump(out/'variants.json',result)
        return 'LIMITED',result,'Read-only native variant inventory; no fabricated variant, promotion or Tk GUI acceptance.'
    if tool=='embed_3d_plugin':
        from embed_3d_plugin.workspace import scan_design
        inv=scan_design(pcb=boardfile,follow=False)
        result={'components':len(inv.rows),'models':sum(len(r.models) for r in inv.rows),'model_status':dict(Counter(m['status'] for r in inv.rows for m in r.models)),'warnings':inv.warnings}
        assert result['components']>500;dump(out/'inventory.json',result)
        return 'LIMITED',result,'Read-only asset inventory; missing external CERN models cannot be embedded.'
    if tool=='portable_assets_plugin':
        from portable_assets_plugin.portable_assets.core.engine import ProjectContext,scan_project
        result=scan_project(ProjectContext(project));dump(out/'inventory.json',result)
        return 'LIMITED',{'report':str(out/'inventory.json')},'Read-only saved project dependency scan; no portability writes or GUI acceptance.'
    if tool=='kilo_plugin':
        sys.path.insert(0,str(ROOT/tool))
        from kilo.kicad.project import discover_project
        from dataclasses import replace
        from kilo.dependencies.scanner import scan_project
        selected=replace(discover_project(boardfile),root_schematic=project/'PMOD.kicad_sch')
        result=scan_project(selected);summary=result.summary();summary['sheet']='PMOD.kicad_sch';dump(out/'dependencies.json',summary)
        return 'LIMITED',summary,'PMOD sheet localization dependency scan against full real board; missing library/model coverage remains unresolved.'
    if tool=='visual_diff_plugin':
        from visual_diff_plugin.kicad_vizdiff.cli import main
        repo=out/'git';repo.mkdir(exist_ok=True);shutil.copy2(boardfile,repo/boardfile.name)
        def git(*args):subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,timeout=15)
        git('init');git('add',boardfile.name);git('-c','user.name=WayriCAD smoke','-c','user.email=smoke@localhost','commit','--allow-empty','-m','Disposable Marble snapshot')
        report=out/'visual-diff.html'
        code=main(['diff',boardfile.name,'--repo',str(repo),'--layers','Edge.Cuts','--output',str(report),'--kicad-cli',str(Path(sys.executable).with_name('kicad-cli.exe'))])
        assert code==0 and report.stat().st_size>1000
        return 'PASS',{'html_bytes':report.stat().st_size,'layers':['Edge.Cuts']},'Native SVG Git HEAD-versus-identical-WORKTREE comparison; local report only.'
    import pcbnew as p
    p.ActionPlugin.register=lambda self:None
    board=p.LoadBoard(str(boardfile));assert board
    fps=list(board.GetFootprints());tracks=list(board.GetTracks());mm=p.ToMM
    base={'footprints':len(fps),'tracks_and_vias':len(tracks),'copper_layers':board.GetCopperLayerCount()}
    def point(v):return (mm(v.x),mm(v.y))
    if tool=='extract_pins_plugin':
        from extract_pins_plugin.core.board_extract import extract_board_pin_rows
        rows=extract_board_pin_rows(board,reference_filter='J*',include_power=True)
        assert rows;dump(out/'connector-pins.json',rows)
        return 'PASS',dict(base,connector_pin_rows=len(rows)),'Actual J* connector pin/net extraction.'
    if tool=='bulk_label_editor_plugin':
        from bulk_label_editor_plugin.bulk_label_editor_plugin import EditableItem,wildcard_replace
        from wayricad_runtime.fields import apply_fields
        chosen=sorted(fps,key=lambda f:f.GetReference())[:3];changes=[]
        for fp in chosen:
            old=fp.GetValue();new=wildcard_replace(old,'*','SMOKE_'+old)
            item=EditableItem('Value',fp.GetReference(),old,fp.SetValue,fp,fp.GetValue)
            changes.append((item,old,new))
        apply_fields(changes);assert all(i.getter()==new for i,old,new in changes)
        apply_fields(changes,reverse=True);assert all(i.getter()==old for i,old,new in changes)
        return 'PASS',dict(base,references=[f.GetReference() for f in chosen]),'Three real footprint values preview/apply/undo on memory-only copy; source not saved.'
    if tool in ('fanout_generator_plugin','via_stitching_plugin'):
        from wayricad_runtime.routing import plan_document
        kind='fanout' if tool=='fanout_generator_plugin' else 'stitching'
        chosen=next(f for f in fps if len(list(f.Pads()))==2 and any(a.GetAttribute()==p.PAD_ATTRIB_SMD and a.GetNetCode()>0 for a in f.Pads()))
        x,y=point(chosen.GetPosition())
        settings={'scope':'Reference wildcard','ref':chosen.GetReference(),'output_mode':'Via-in-pad','width':.15,'via_diameter':.45,'via_drill':.2,'clearance':.15} if kind=='fanout' else {'universal':False,'x_min':x-2,'y_min':y-2,'x_max':x+2,'y_max':y+2,'spacing':2,'net_choice':'GND'}
        result=plan_document(kind,board,p,settings);dump(out/'plan.json',result)
        return 'PASS',dict(base,reference=chosen.GetReference(),settings=settings,accepted=len(result['candidates']),rejected=result['rejected']),'Bounded dry-run geometry with actual obstacles; rejected candidates preserved; no DRC/apply certification.'
    if tool=='copper_balancer_plugin':
        from copper_balancer_plugin.copper_balancer.engine import Settings
        from copper_balancer_plugin.copper_balancer.kicad_backend import build_preview
        x,y=point(fps[0].GetPosition());settings=Settings(region=(x-3,y-3,x+3,y+3),max_shapes=10,size=.5,gap=.5)
        started=time.monotonic()
        previews,warnings=build_preview(board,[p.F_Cu],settings,progress=lambda *args:time.monotonic()-started<25)
        result={'region':settings.region,'shapes':sum(len(r.plan.shapes) for r in previews),'candidates':sum(r.plan.candidates for r in previews),'warnings':warnings};dump(out/'preview.json',result)
        return 'PASS',dict(base,**result),'6×6 mm F.Cu planning region, max 10 shapes; no board write.'
    if tool=='mechanical_check_plugin':
        sys.path.insert(0,str(ROOT/tool/'src'))
        from wayricad_mechanical.extract import prepare
        from wayricad_mechanical.config import load
        result=prepare(board,out/'extraction',project,load());dump(out/'coverage.json',result)
        data={'components':len(result['components']),'coverage_gaps':len(result['gaps']),'pads':len(result['pads'])}
        return 'LIMITED',data,'Native extraction/model coverage only; missing CERN models prevent complete solid-check acceptance.'
    if tool=='test_point_descriptor_plugin':
        from test_point_descriptor_plugin.test_point_descriptor_plugin import extract_test_points
        rows=extract_test_points(board);dump(out/'test-points.json',rows)
        return 'PASS',dict(base,test_points=len(rows)),'Actual board test-point/function extraction; zero is valid if none match.'
    pads=[(fp,pad) for fp in fps for pad in fp.Pads() if pad.GetNetname()]
    if tool=='pdn_decoupling_plugin':
        from pdn_decoupling_plugin.analysis import PadNode,analyze_decoupling,infer_regulators
        nodes=[PadNode(fp.GetReference(),a.GetNumber(),a.GetNetname(),*point(a.GetPosition()),fp.GetValue()) for fp,a in pads]
        rail=next((a.net for a in nodes if a.net in ('+3V3','3V3','VCC3V3')),'*3V3*')
        results=analyze_decoupling(nodes,rail,'GND');dump(out/'decoupling.json',results)
        return 'PASS',dict(base,pads=len(nodes),rail=rail,findings=len(results),regulators=infer_regulators(nodes)),'Real pad/rail/ground topology and capacitor-distance analysis; heuristic, not power-integrity simulation.'
    if tool=='protocol_constraint_composer_plugin':
        from protocol_constraint_composer_plugin.analysis import detect_protocols,generate_rules,merge_managed_rules
        names=sorted({a.GetNetname() for fp,a in pads});assignments=detect_protocols(names);rules=generate_rules(assignments)
        merged=merge_managed_rules('(version 1)\n',rules);assert merge_managed_rules(merged,rules)==merged
        (out/'Marble-preview.kicad_dru').write_text(merged,encoding='utf-8')
        return 'PASS',dict(base,nets=len(names),assignments=len(assignments)),'Protocol detection and idempotent rules export; does not assert board-specific constraints are approved.'
    if tool=='harness_workbench_plugin':
        from harness_workbench_plugin.analysis import PinRecord,auto_link_multi,validate_links
        from harness_workbench_plugin.report import interactive_harness_html
        records=[PinRecord('Marble',fp.GetReference(),a.GetNumber(),a.GetNetname()) for fp,a in pads if fp.GetReference().startswith('J')]
        links=auto_link_multi(records,include_power=False,max_links=100)
        html=interactive_harness_html(records,links,title='Marble connector connectivity smoke');(out/'harness.html').write_text(html,encoding='utf-8')
        return 'LIMITED',dict(base,connector_pins=len(records),links=len(links),issues=validate_links(links)),'Single-board connector connectivity report; no invented external harness destination.'
    if tool=='manufacturing_readiness_plugin':
        from manufacturing_readiness_plugin.analysis import BoardMetrics,FabricatorProfile,audit_metrics
        vias=[t for t in tracks if isinstance(t,p.PCB_VIA)];segments=[t for t in tracks if not isinstance(t,p.PCB_VIA)]
        drill=min(mm(t.GetDrillValue()) for t in vias);annular=min((mm(t.GetWidth(t.TopLayer()))-mm(t.GetDrillValue()))/2 for t in vias)
        metrics=BoardMetrics(min(mm(t.GetWidth()) for t in segments),mm(board.GetDesignSettings().m_MinClearance),drill,annular,mm(board.GetDesignSettings().GetBoardThickness())/drill,board.GetCopperLayerCount())
        checks=audit_metrics(metrics,FabricatorProfile());dump(out/'readiness.json',{'metrics':metrics,'checks':checks})
        return 'LIMITED',dict(base,checks=dict(Counter(c.status for c in checks))),'Real measured fabrication metrics against default demo profile; full DRC/jobset release gate not run.'
    if tool in ('heater_designer_plugin','planar_magnetics_plugin'):
        box=board.GetBoardEdgesBoundingBox();width=min(30,mm(box.GetWidth())/5);height=min(30,mm(box.GetHeight())/5)
        if tool=='heater_designer_plugin':
            from heater_designer_plugin.analysis import HeaterSpec,HeaterEngine,ThermalSpec
            result=HeaterEngine.generate(HeaterSpec(width_mm=width,height_mm=height));thermal=HeaterEngine.simulate(result,ThermalSpec(board_thickness_mm=mm(board.GetDesignSettings().GetBoardThickness()),grid_x=10,grid_y=8,iterations=20))
            data={'width_mm':width,'height_mm':height,'segments':len(result.segments),'resistance_ohm':result.resistance_ohm,'maximum_c':thermal.maximum_c}
        else:
            from planar_magnetics_plugin.analysis import CoilSpec,MagneticsEngine
            result=MagneticsEngine.analyze(CoilSpec(outer_width_mm=width,outer_height_mm=height,turns=3,layers=2));data={'width_mm':width,'height_mm':height,'result':result}
        dump(out/'design.json',data)
        return 'LIMITED',dict(base,width_mm=width,height_mm=height),'Bounded generated design derived from actual Marble board size/thickness; no claim it fits occupied copper or is a Marble requirement.'
    if tool in ('trace_impedance_plugin','signal_integrity_advisor_plugin','return_path_auditor_plugin'):
        from trace_impedance_plugin.measurement import TraceMeasurementEngine
        engine=TraceMeasurementEngine(board);counts=Counter(a.GetNetname() for fp,a in pads)
        candidate=[name for name,count in counts.items() if count==2 and not name.startswith(('+','-')) and any(s in name.upper() for s in ('CLK','USB','TX','RX','SCL'))]
        via_counts=Counter(t.GetNetname() for t in tracks if isinstance(t,p.PCB_VIA))
        track_counts=Counter(t.GetNetname() for t in tracks)
        net=sorted(candidate or [n for n,c in counts.items() if c==2],key=lambda name:(not bool(via_counts[name]),track_counts[name],name))[0];ends=engine.pads_for_net(net)
        if tool=='trace_impedance_plugin':
            result=engine.measure(net,ends[0],ends[1],reference_layer='In1.Cu');report=result.as_report() if hasattr(result,'as_report') else result.as_dict();dump(out/'route.json',report)
            return 'LIMITED',dict(base,net=net,endpoints=ends,result=report),'One actual routed net, connected pad pair, vias/layers and RLC; layer following only, no copper movement.'
        if tool=='signal_integrity_advisor_plugin':
            from signal_integrity_advisor_plugin.analysis import SignalIntegrityEngine
            result=SignalIntegrityEngine(board).validate_impedance(net,*ends,'In1.Cu',100,50,10);dump(out/'signal-integrity.json',result)
            return 'LIMITED',dict(base,net=net,endpoints=ends,result=result),'One actual route against explicit illustrative 50-ohm/10% target, not approved system constraints.'
        from return_path_auditor_plugin.analysis import CopperSegment,ViaPoint,ReturnPathAnalyzer
        selected=[t for t in tracks if t.GetNetname()==net];ground=[t for t in tracks if isinstance(t,p.PCB_VIA) and t.GetNetname()=='GND']
        segments=[CopperSegment(net,board.GetLayerName(t.GetLayer()),point(t.GetStart()),point(t.GetEnd()),mm(t.GetWidth())) for t in selected if not isinstance(t,p.PCB_VIA)]
        vias=[ViaPoint(t.GetNetname(),point(t.GetPosition()),tuple(board.GetLayerName(l) for l in board.GetEnabledLayers().CuStack() if t.IsOnLayer(l))) for t in selected+ground if isinstance(t,p.PCB_VIA)]
        result=ReturnPathAnalyzer().audit(segments,vias,[]);dump(out/'return-path.json',result)
        return 'LIMITED',dict(base,net=net,segments=len(segments),vias=len(vias),findings=len(result.findings)),'Real signal/ground via transition and stub audit; reference-plane polygons omitted and not certified.'
    raise ValueError('Unimplemented smoke: '+tool)

def worker(args):
    started=time.monotonic();output=Path(args.output);target=output/args.worker;target.mkdir(parents=True,exist_ok=True)
    try:
        status,details,scope=operation(args.worker,Path(args.project).resolve(),target)
        result={'tool':args.worker,'status':status,'scope':scope,'details':details}
    except Exception as exc:
        traceback.print_exc();result={'tool':args.worker,'status':'BLOCKED','scope':'Operation did not complete','error':str(exc),'exception':type(exc).__name__}
    result['elapsed_seconds']=round(time.monotonic()-started,2);dump(target/'result.json',result)
    sys.stdout.flush();sys.stderr.flush();os._exit(0)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',default=str(ROOT/'.validation/marble/Marble/design'))
    parser.add_argument('--output',default=str(ROOT/'.validation/marble/suite'))
    parser.add_argument('--native-python',default='C:/Program Files/KiCad/10.0/bin/python.exe')
    parser.add_argument('--timeout',type=int,default=45)
    parser.add_argument('--tools',nargs='*',choices=TOOLS)
    parser.add_argument('--worker',choices=TOOLS)
    args=parser.parse_args()
    if args.worker:return worker(args)
    project=Path(args.project).resolve();output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    before={str(p):digest(p) for p in project.glob('*') if p.suffix in ('.kicad_pcb','.kicad_sch','.kicad_pro')}
    results=[]
    for tool in args.tools or TOOLS:
        target=output/tool;target.mkdir(exist_ok=True);resultfile=target/'result.json';resultfile.unlink(missing_ok=True)
        env=os.environ.copy()
        for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'):env.pop(key,None)
        with (target/'worker.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([args.native_python,str(Path(__file__).resolve()),'--worker',tool,'--project',str(project),'--output',str(output)],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            dump(target/'process.json',{'pid':process.pid,'tool':tool,'started':time.time()})
            try:process.wait(timeout=min(45,args.timeout))
            except subprocess.TimeoutExpired:
                # Taskkill /T only affects the exact process tree this harness started.
                try:
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=5)
                    if process.poll() is None:process.kill()
                    process.wait(timeout=3)
                except (OSError,subprocess.TimeoutExpired) as exc:
                    dump(target/'cleanup-error.json',{'pid':process.pid,'error':str(exc)})
        if resultfile.exists():result=json.loads(resultfile.read_text(encoding='utf-8'))
        else:
            result={'tool':tool,'status':'BLOCKED','scope':'Worker did not complete within the bounded execution/runtime budget','exit_code':process.returncode};dump(resultfile,result)
        results.append(result);print(tool,result['status'],flush=True)
    unchanged=all(Path(p).is_file() and digest(p)==hash_ for p,hash_ in before.items())
    manifest=ROOT/'.validation/marble/source-manifest.json'
    source_checks=[]
    if manifest.exists():
        for row in json.loads(manifest.read_text(encoding='utf-8-sig')):source_checks.append({'path':row['path'],'unchanged':digest(row['path'])==row['sha256']})
    results=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(output.glob('*/result.json'))]
    summary={'project':str(project),'project_files_unchanged':unchanged,'original_source_checks':source_checks,'results':results}
    dump(output/'summary.json',summary)
    assert unchanged and all(r['unchanged'] for r in source_checks),'Input/source hash changed'
    return 0

if __name__=='__main__':raise SystemExit(main())
