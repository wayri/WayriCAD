"""Native operational acceptance on copied Marble data and explicit fixtures.

Execution success and electrical/design findings are separate fields. This never
changes Marble source files, suppresses DRC findings, or invents its cable mates.
Run with ordinary Python; workers use KiCad 10's bundled Python.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
KINDS = ('heater', 'magnetics', 'harness', 'manufacturing')


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(cli, args, cwd, label, timeout=240):
    env = os.environ.copy()
    config = cwd / '.validation-config'; config.mkdir(exist_ok=True)
    env['KICAD_CONFIG_HOME'] = str(config)
    env['KICAD_DOCUMENTS_HOME'] = str(config / 'documents')
    started = time.monotonic()
    result = subprocess.run([str(cli), *map(str,args)], cwd=cwd, env=env,
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (cwd/(label+'.stdout.log')).write_text(result.stdout, encoding='utf-8')
    (cwd/(label+'.stderr.log')).write_text(result.stderr, encoding='utf-8')
    return {'returncode':result.returncode,'elapsed_seconds':round(time.monotonic()-started,2),
            'command':[str(cli), *map(str,args)]}


def drc(cli, board, out, label='drc'):
    from manufacturing_readiness_plugin.verification import drc_evidence
    report = out/(label+'.json')
    result = command(cli, ['pcb','drc','--format','json','--output',report,
                          '--exit-code-violations',board],out,label)
    result.update(drc_evidence(report,result['returncode']))
    result['executed'] = result['returncode'] in (0,5)
    assert result['executed'], result
    return result


def native():
    import pcbnew as p
    import wx
    app = wx.App.Get() or wx.App(False)
    p.ActionPlugin.register = lambda self:None
    p.Refresh = lambda:None
    def error(message,*args,**kwargs):
        raise RuntimeError(str(message))
    wx.MessageBox = error
    return p,wx,app


def copy_project(project,out):
    target = out/'project'; target.mkdir(exist_ok=True)
    for path in project.iterdir():
        if path.is_file() and path.suffix in ('.kicad_pcb','.kicad_pro','.kicad_sch','.kicad_dru'):
            shutil.copy2(path,target/path.name)
    return target


def generated(kind, project, out, cli):
    p,wx,app = native()
    from heater_designer_plugin.heater_designer_plugin import HeaterFrame
    from planar_magnetics_plugin.planar_magnetics_plugin import MagneticsFrame
    copied = copy_project(project,out)
    board = p.LoadBoard(str(copied/'Marble.kicad_pcb'))
    original = {x.m_Uuid.AsString() for x in board.GetTracks()}
    frame = (HeaterFrame if kind=='heater' else MagneticsFrame)(None,board)
    try:
        # This is an explicit operation fixture, not a proposed Marble design.
        bbox=board.GetBoardEdgesBoundingBox()
        ox=p.ToMM(bbox.GetRight())+12;oy=p.ToMM(bbox.GetTop())+12
        # A separate outlined test coupon on the copied board avoids guessing
        # a free, electrically appropriate insertion site in occupied Marble.
        for a,b in (((ox-2,oy-2),(ox+8,oy-2)),((ox+8,oy-2),(ox+8,oy+8)),
                    ((ox+8,oy+8),(ox-2,oy+8)),((ox-2,oy+8),(ox-2,oy-2))):
            edge=p.PCB_SHAPE(board);edge.SetShape(p.SHAPE_T_SEGMENT);edge.SetLayer(p.Edge_Cuts)
            edge.SetStart(p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1])))
            edge.SetEnd(p.VECTOR2I(p.FromMM(b[0]),p.FromMM(b[1])))
            edge.SetWidth(p.FromMM(.05));board.Add(edge)
        values={'width':6,'height':6,'layers':2,'trace':.25,'spacing':.3,'origin_x':ox,'origin_y':oy}
        if kind=='magnetics':values['turns']=3
        for key,value in values.items():frame.fields[key].SetValue(str(value))
        expected_net='WayriCAD_OPERATION_FIXTURE_'+kind.upper()
        net = p.NETINFO_ITEM(board,expected_net);board.Add(net)
        frame.net.Append(net.GetNetname())
        frame.net.SetValue(net.GetNetname())
        getattr(frame,'generate' if kind=='heater' else 'analyze')(None)
        frame.show_pcb(None)
        assert {x.m_Uuid.AsString() for x in board.GetTracks()}==original
        proposed=len(frame.preview_items);assert proposed>0
        frame.commit(None)
        created=[x for x in board.GetTracks() if x.m_Uuid.AsString() not in original]
        assert len(created)==proposed
        assert all(x.GetNetname()==expected_net for x in created),('apply',expected_net,frame.net.GetValue(),set(x.GetNetname() for x in created))
        via_count=sum(isinstance(x,p.PCB_VIA) for x in created);assert via_count>0
        frame.undo(None);assert {x.m_Uuid.AsString() for x in board.GetTracks()}==original
        frame.redo(None);assert len(list(board.GetTracks()))==len(original)+proposed
        assert all(x.GetNetname()==expected_net for x in board.GetTracks() if x.m_Uuid.AsString() not in original), 'Redo changed nets'
        output=copied/('Marble-'+kind+'.kicad_pcb')
        board.BuildConnectivity()
        p.PCB_IO_KICAD_SEXPR().SaveBoard(str(output),board)
        shutil.copy2(copied/'Marble.kicad_pro',output.with_suffix('.kicad_pro'))
        reloaded=p.LoadBoard(str(output))
        new=[x for x in reloaded.GetTracks() if x.m_Uuid.AsString() not in original]
        assert len(new)==proposed
        assert all(x.GetNetname()==expected_net for x in new),('reload',expected_net,set(x.GetNetname() for x in new))
        assert any(len(list(g.GetItems()))==proposed for g in reloaded.Groups())
        result={'execution':'PASS','source':'Marble copy','intent':'Explicit non-production insertion fixture',
                'placement':'Separate outlined test coupon added only to the copy',
                'settings':values,'new_items':proposed,'vias':via_count,
                'review_nonmutating':True,'apply_undo_redo':True,'native_reload':True,'output':str(output)}
    finally:frame.Destroy();wx.Yield()
    dump(out/'operations.json',result)
    result['drc']=drc(cli,output,out)
    result['design_acceptance']='Not approved; full DRC findings are retained.'
    return result


def fixture_board(p,path,label):
    board=p.BOARD()
    def vec(x,y):return p.VECTOR2I(p.FromMM(x),p.FromMM(y))
    for a,b in (((0,0),(30,0)),((30,0),(30,20)),((30,20),(0,20)),((0,20),(0,0))):
        edge=p.PCB_SHAPE(board);edge.SetShape(p.SHAPE_T_SEGMENT);edge.SetLayer(p.Edge_Cuts)
        edge.SetStart(vec(*a));edge.SetEnd(vec(*b));edge.SetWidth(p.FromMM(.05));board.Add(edge)
    fp=p.FOOTPRINT(board);fp.SetReference('J1');fp.SetValue('Explicit '+label+' harness fixture');board.Add(fp)
    for i,name in enumerate(('SIGNAL','RETURN'),1):
        net=p.NETINFO_ITEM(board,name);board.Add(net)
        pad=p.PAD(fp);pad.SetNumber(str(i));pad.SetPosition(vec(10+i*3,10))
        pad.SetSize(vec(1,1));pad.SetAttribute(p.PAD_ATTRIB_SMD)
        layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers);pad.SetNet(net);fp.Add(pad)
    p.SaveBoard(str(path),board)
    return p.LoadBoard(str(path))


def harness(project,out,cli):
    p,wx,app=native()
    from harness_workbench_plugin.analysis import (PinRecord,PinMapRow,links_from_pin_map,validate_pin_map,
        HarnessBundle,HarnessSplice,apply_bundle,apply_splice,harness_bom,export_rows,export_csv,
        pin_map_editor_rows,load_pin_map_csv,validate_links,universal_harness_svg)
    from harness_workbench_plugin.report import interactive_harness_html
    marble=p.LoadBoard(str(project/'Marble.kicad_pcb'))
    inventory=[PinRecord('Marble',fp.GetReference(),pad.GetNumber(),pad.GetNetname())
               for fp in marble.GetFootprints() if fp.GetReference().startswith('J') for pad in fp.Pads()]
    assert inventory
    dump(out/'Marble-connectors.json',[asdict(x) for x in inventory])
    (out/'Marble-inventory.html').write_text(interactive_harness_html(inventory,[],title='Marble inventory — no external destination supplied'),encoding='utf-8')
    records=[]
    for project_name in ('Fixture_A','Fixture_B'):
        board=fixture_board(p,out/(project_name+'.kicad_pcb'),project_name)
        records += [PinRecord(project_name,fp.GetReference(),pad.GetNumber(),pad.GetNetname())
                    for fp in board.GetFootprints() for pad in fp.Pads()]
    rows=[PinMapRow('Fixture_A','J1',str(i),'Fixture_B','J1',str(i),'W'+str(i),color=color,length_m=.4)
          for i,color in ((1,'Blue'),(2,'Black'))]
    assert not validate_pin_map(records,rows)
    export_rows(out/'fixture-pin-map.csv',pin_map_editor_rows(rows))
    loaded=load_pin_map_csv(out/'fixture-pin-map.csv');assert loaded==rows
    links=links_from_pin_map(records,loaded);assert len(links)==2 and all(l.status=='linked' for l in links)
    bundle=HarnessBundle('B1',['W1','W2'],length_m=.4,shield='braid')
    splice=HarnessSplice('S1',['W2'],location='Explicit fixture only')
    apply_bundle(links,bundle);apply_splice(links,splice)
    assert links[0].bundle=='B1' and links[1].splice=='S1'
    bom=harness_bom(records,links,[bundle],[splice]);assert bom
    export_rows(out/'fixture-bom.csv',bom);export_csv(out/'fixture-wires.csv',links)
    html=interactive_harness_html(records,links,[bundle],[splice],title='Explicit two-board acceptance fixture — not Marble wiring')
    (out/'fixture-harness.html').write_text(html,encoding='utf-8')
    (out/'fixture-harness.svg').write_text(universal_harness_svg(links),encoding='utf-8')
    assert 'Fixture_A' in html and 'Fixture_B' in html
    return {'execution':'PASS','Marble_connector_pins':len(inventory),'Marble_external_links':0,
            'separate_fixture_boards':2,'fixture_links':len(links),'pin_map_roundtrip':True,
            'bom_rows':len(bom),'validation_findings':validate_links(links),
            'exports':['fixture-pin-map.csv','fixture-bom.csv','fixture-wires.csv','fixture-harness.html','fixture-harness.svg']}


def jobset_file(path):
    # Native KiCad jobset schema: jobset.cpp and JOB_EXPORT_PCB_GERBERS parameters.
    dump(path,{'meta':{'version':1},'jobs':[{'id':str(uuid.uuid4()),'type':'pcb_export_gerbers',
          'description':'Explicit acceptance fixture Gerbers','settings':{'layers':['F.Cu','B.Cu','Edge.Cuts'],
          'output_filename':'gerbers','use_protel_file_extension':True}}],
          'outputs':[{'id':str(uuid.uuid4()),'type':'folder','only':[],
          'description':'Local validation output','settings':{'output_path':'generated'}}]})


def manufacturing(project,out,cli):
    p,wx,app=native()
    from manufacturing_readiness_plugin.verification import capture_inputs,VerificationSnapshot
    from manufacturing_readiness_plugin.analysis import FabricatorProfile,audit_metrics,build_release
    copied=copy_project(project,out)
    profile=FabricatorProfile()
    source=copied/'Marble.kicad_pcb'
    files,key,job=capture_inputs(source,copied,profile,'',source.read_text(encoding='utf-8'))
    snapshot=VerificationSnapshot(files,key,source.name,job)
    try:
        result=drc(cli,snapshot.root/source.name,snapshot.root,'Marble-drc')
        snapshot.record('drc',result['clean'],result)
        shutil.copy2(snapshot.root/'Marble-drc.json',out/'Marble-drc.json')
        for suffix in ('stdout.log','stderr.log'):
            shutil.copy2(snapshot.root/('Marble-drc.'+suffix),out/('Marble-drc.'+suffix))
        blocked=False
        try:snapshot.ready(key)
        except ValueError:blocked=True
        assert blocked != result['clean']
        marble={'drc':result,'release_blocked':blocked,'audit':[asdict(c) for c in audit_metrics(snapshot.metrics,profile)]}
    finally:snapshot.owner.cleanup()
    dump(out/'Marble-verification.json',marble)
    clean=out/'clean-fixture';clean.mkdir(exist_ok=True)
    board=p.BOARD()
    for a,b in (((0,0),(30,0)),((30,0),(30,20)),((30,20),(0,20)),((0,20),(0,0))):
        edge=p.PCB_SHAPE(board);edge.SetShape(p.SHAPE_T_SEGMENT);edge.SetLayer(p.Edge_Cuts)
        edge.SetStart(p.VECTOR2I(p.FromMM(a[0]),p.FromMM(a[1])))
        edge.SetEnd(p.VECTOR2I(p.FromMM(b[0]),p.FromMM(b[1])))
        edge.SetWidth(p.FromMM(.05));board.Add(edge)
    clean_board=clean/'Clean.kicad_pcb';p.SaveBoard(str(clean_board),board)
    dump(clean/'Clean.kicad_pro',{'meta':{'version':1},'board':{'design_settings':{'rules':{'min_clearance':.15}}}})
    jobset_file(clean/'acceptance.kicad_jobset')
    files,key,job=capture_inputs(clean_board,clean,profile,clean/'acceptance.kicad_jobset',clean_board.read_text(encoding='utf-8'))
    snapshot=VerificationSnapshot(files,key,clean_board.name,job)
    try:
        clean_drc=drc(cli,snapshot.root/clean_board.name,snapshot.root,'clean-drc')
        snapshot.record('drc',clean_drc['clean'],clean_drc);assert clean_drc['clean'],clean_drc
        job_result=command(cli,['jobset','run','--stop-on-error','--file',snapshot.root/job,
                          snapshot.root/'Clean.kicad_pro'],snapshot.root,'jobset',30)
        generated=list((snapshot.root/'generated').rglob('*'))
        gerbers=[x for x in generated if x.is_file() and x.suffix.lower() in ('.gbr','.gtl','.gbl','.gm1')]
        assert job_result['returncode']==0 and gerbers,(job_result,generated)
        job_result['gerbers']=[x.relative_to(snapshot.root).as_posix() for x in gerbers]
        snapshot.record('jobset',True,job_result)
        hashes=snapshot.ready(key)
        checks=audit_metrics(snapshot.metrics,profile);assert all(c.status=='PASS' for c in checks)
        archive=out/'fixture-release.zip'
        manifest=build_release(archive,[snapshot.root/name for name in hashes],checks,'validation',
                              expected_hashes=hashes,base_directory=snapshot.root,
                              evidence={'input_key':key,'checks':snapshot.evidence})
        with zipfile.ZipFile(archive) as z:assert z.testzip() is None
        return {'execution':'PASS','Marble':marble,'clean_fixture':{'drc':clean_drc,'jobset':job_result,
                'release_zip':str(archive),'release_files':len(manifest['files'])},
                'design_acceptance':'Marble release remains blocked when its actual DRC has findings.'}
    finally:snapshot.owner.cleanup()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=ROOT/'.validation/marble/Marble/design')
    parser.add_argument('--output',type=Path,default=ROOT/'.validation/marble/operations')
    parser.add_argument('--native-python',default='C:/Program Files/KiCad/10.0/bin/python.exe')
    parser.add_argument('--kinds',nargs='+',choices=KINDS,default=list(KINDS))
    parser.add_argument('--worker',choices=KINDS)
    args=parser.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    args.project=args.project.resolve()
    if args.worker:
        started=time.monotonic();out=args.output/args.worker;out.mkdir(exist_ok=True)
        cli=Path(args.native_python).with_name('kicad-cli.exe' if os.name=='nt' else 'kicad-cli')
        try:
            if args.worker in ('heater','magnetics'):result=generated(args.worker,args.project,out,cli)
            else:result=globals()[args.worker](args.project,out,cli)
        except Exception as exc:
            traceback.print_exc();result={'execution':'FAILED','error':str(exc)}
        result['elapsed_seconds']=round(time.monotonic()-started,2)
        dump(out/'result.json',result);sys.stdout.flush();sys.stderr.flush();os._exit(0 if result['execution']=='PASS' else 1)
    before={str(p):sha(p) for p in args.project.iterdir() if p.is_file()}
    results={}
    for kind in args.kinds:
        out=args.output/kind;out.mkdir(exist_ok=True)
        with (out/'worker.stdout.log').open('w',encoding='utf-8') as stdout, (out/'worker.stderr.log').open('w',encoding='utf-8') as stderr:
            try:
                proc=subprocess.run([args.native_python,str(Path(__file__).resolve()),'--worker',kind,
                        '--project',str(args.project),'--output',str(args.output),'--native-python',args.native_python],
                        stdout=stdout,stderr=stderr,timeout=480)
                results[kind]=json.loads((out/'result.json').read_text(encoding='utf-8'))
            except subprocess.TimeoutExpired:
                results[kind]={'execution':'TIMEOUT','timeout_seconds':480}
        print(kind,results[kind]['execution'],flush=True)
    assert all(sha(Path(path))==value for path,value in before.items()),'Source project changed'
    dump(args.output/'summary.json',{'operations':results,'source_unchanged':True})
    return 0 if all(x['execution']=='PASS' for x in results.values()) else 1


if __name__=='__main__':raise SystemExit(main())
