"""Regenerate small public Pocket KiView examples with native saved-PCB producers.

Run with KiCad's existing Python (pcbnew, NumPy, SciPy, VTK, Matplotlib).
No packages, editor settings or private boards are used or installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
DEFAULT_OUTPUT=ROOT/'docs/examples/pocket-kivi'
NET='/Front outputs/SLOT1'
MODULES=(
    'tools/generate_pocket_kivi_examples.py',
    'wayricad_runtime/pocket_kivi_export.py','wayricad_runtime/pocket_report.py',
    'quick_pi_plugin/service.py','quick_pi_plugin/board_geometry.py','quick_pi_plugin/mesh.py','quick_pi_plugin/solver.py',
    'signal_integrity_advisor_plugin/service.py','signal_integrity_advisor_plugin/quick_si.py',
    'signal_integrity_advisor_plugin/measurement.py','signal_integrity_advisor_plugin/eye_model.py',
    'quick_therm_plugin/service.py','quick_therm_plugin/thermal_geometry.py','quick_therm_plugin/thermal_multilayer.py',
    'quick_therm_plugin/thermal_spatial_transient.py',
)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sha(path):
    """Ignore only Git checkout newline conversion in producer source identities."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def create_board(path):
    """Author one standalone public fixture; keep it unchanged on later reruns."""
    import pcbnew as p
    if path.exists():return
    board=p.BOARD();board.SetCopperLayerCount(2)
    point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
    identity=lambda name:p.KIID(str(uuid.uuid5(uuid.NAMESPACE_URL,'wayricad-pocket-example/'+name)))
    signal=p.NETINFO_ITEM(board,NET,1);ground=p.NETINFO_ITEM(board,'GND',2)
    board.Add(signal);board.Add(ground)
    front=p.LSET();front.AddLayer(p.F_Cu)
    for ref,x in (('J1',5),('U1',25)):
        fp=p.FOOTPRINT(board);fp.SetReference(ref);fp.SetValue('Public example');fp.SetPosition(point(x,5))
        fp.SetUuid(identity(ref));board.Add(fp)
        pad=p.PAD(fp);pad.SetNumber('1');pad.SetAttribute(p.PAD_ATTRIB_SMD);pad.SetShape(p.PAD_SHAPE_RECT)
        pad.SetPosition(point(x,5));pad.SetSize(point(2,2));pad.SetLayerSet(front);pad.SetNet(signal)
        pad.SetUuid(identity(ref+'.1'));fp.Add(pad)
    for name,start,end,width in (('route',(5,5),(25,5),1.),('floating-island',(10,7),(12,7),.5)):
        track=p.PCB_TRACK(board);track.SetStart(point(*start));track.SetEnd(point(*end));track.SetWidth(p.FromMM(width))
        track.SetLayer(p.F_Cu);track.SetNet(signal);track.SetUuid(identity(name));board.Add(track)
    for label,corners in (('perimeter',[(0,0),(30,0),(30,15),(0,15)]),
                          ('cutout',[(12,9),(18,9),(18,13),(12,13)])):
        for i,(a,b) in enumerate(zip(corners,corners[1:]+corners[:1])):
            edge=p.PCB_SHAPE(board);edge.SetShape(p.SHAPE_T_SEGMENT);edge.SetStart(point(*a));edge.SetEnd(point(*b))
            edge.SetLayer(p.Edge_Cuts);edge.SetWidth(p.FromMM(.05));edge.SetUuid(identity(label+str(i)));board.Add(edge)
    poly=p.SHAPE_POLY_SET();poly.NewOutline()
    for x,y in ((.5,.5),(29.5,.5),(29.5,14.5),(.5,14.5)):poly.Append(p.FromMM(x),p.FromMM(y))
    hole=poly.NewHole()
    for x,y in ((12,9),(12,13),(18,13),(18,9)):poly.Append(p.FromMM(x),p.FromMM(y),0,hole)
    zone=p.ZONE(board);zone.SetLayer(p.B_Cu);zone.SetNet(ground);zone.SetUuid(identity('saved-ground-plane'))
    zone.Outline().Append(poly);zone.SetFilledPolysList(p.B_Cu,poly);zone.SetIsFilled(True);board.Add(zone)
    p.SaveBoard(str(path),board)
    text=path.read_text(encoding='utf-8')
    if '(stackup' not in text:
        stack='''(stackup
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4") (epsilon_r 4.2) (loss_tangent 0.02))
      (layer "B.Cu" (type "copper") (thickness 0.035))
    )'''
        text=text.replace('(setup','(setup\n    '+stack,1)
        path.write_text(text,encoding='utf-8',newline='\n')
    if p.LoadBoard(str(path)) is None:raise ValueError('Native fixture failed KiCad readback.')


def generate(output=DEFAULT_OUTPUT,viewer_extension=None):
    import pcbnew
    import numpy,scipy,vtk,matplotlib
    from wayricad_runtime.pocket_report import evidence_context
    from wayricad_runtime.pocket_kivi_export import portable_json
    from quick_pi_plugin.service import execute as pi_execute
    from quick_therm_plugin.service import execute as therm_execute
    from signal_integrity_advisor_plugin.service import execute as si_execute,source_fingerprints
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    board=output/'example.kicad_pcb';create_board(board)
    board_before=board.read_bytes();digest=sha(board)
    modules={name:source_sha(ROOT/name) for name in MODULES}
    pi_request=dict(action='solve',board_path=str(board),net=NET,source_terminal='J1.1',sink_terminal='U1.1',
        source_voltage=3.3,sink_current=.25,edge_mm=1.,mesh_backend='vtk',max_cells=20000)
    print('Running saved-PCB Quick PI',flush=True)
    pi=pi_execute(pi_request)
    print('Running saved-PCB Quick SI',flush=True)
    si_request=dict(mode='screen',board_path=str(board),source_fingerprints=source_fingerprints(board),
        net=NET,start='J1.1',end='U1.1',reference='B.Cu',
        inputs=dict(rise_ns=1.,frequency_mhz=100.,source_ohm=20.,load_ohm=None,
                    z0_ohm=50.,epsilon_eff=3.,eye_bitrate_mbps=100.,eye_swing_v=1.))
    si=si_execute(si_request)['report']
    thermal_request=dict(action='quick_therm',board_path=str(board),expected_source_sha256=digest,
        environment='air',ambient_c=20.,references=['U1'],input_mode='manual',
        manual_values={'U1':{'power_w':.05,'theta_jb_k_per_w':4.}},
        thermal_model_kind='multilayer',board_power_only=True,
        thermal_network_settings=dict(dielectric_k_w_mk=.3,via_plating_mm=.025,grid_cells_long_axis=24,
            board_h_w_m2k=10.,board_emissivity=0.,source_contact_pad_numbers={'U1':'1'}),
        probes=[dict(label='Heater',x_mm=25.,y_mm=5.,side='top'),dict(label='Cutout',x_mm=15.,y_mm=11.,side='top')])
    print('Running saved-PCB QuickTherm steady',flush=True)
    thermal=therm_execute(thermal_request)
    transient_request=dict(thermal_request,transient_settings=dict(duration_s=1.,timestep_s=.25,frame_interval_s=.5,
        initial_c=20.,copper_volumetric_capacity_j_m3k=3450000.,dielectric_volumetric_capacity_j_m3k=1700000.,
        power_schedules={'U1':[[0.,1.],[.5,1.],[1.,0.]]},schedule_interpolation='step'))
    print('Running saved-PCB QuickTherm transient',flush=True)
    transient=therm_execute(transient_request)
    cases=[('quick-pi.pocket-kivi.json',pi,'Quick PI','quick_pi_plugin',
            {'points_mm':'mm','potential_V':'V','cell_power_W':'W','cell_J_A_mm2':'A/mm²'},'front-depth'),
           ('quick-si.pocket-kivi.json',si,'Quick SI','signal_integrity_advisor_plugin',
            {'length_mm':'mm','delay_ns':'ns','z0_ohm':'Ω','time_ui':'UI','traces_v':'V'},None),
           ('quick-therm.pocket-kivi.json',thermal,'QuickTherm','quick_therm_plugin',
            {'x_centers_mm':'mm','y_centers_mm':'mm','values_c':'°C','power_w':'W'},None),
           ('quick-therm-transient.pocket-kivi.json',transient,'QuickTherm','quick_therm_plugin',
            {'x_centers_mm':'mm','y_centers_mm':'mm','temperatures_c':'°C','time_s':'s','power_w':'W'},None)]
    payloads={}
    versions={}
    for filename,bundle,tool,package,units,z_basis in cases:
        context=evidence_context(bundle,tool=tool,package=package,board_path=board,units=units,
            coordinate_frame=None if tool=='Quick SI' else 'KiCad PCB XY in mm',z_basis=z_basis)
        payloads[filename]=portable_json(bundle,**context)
        versions[tool]=context['version']
    if board.read_bytes()!=board_before:raise ValueError('A producer changed the public source PCB.')
    if any(source_sha(ROOT/name)!=value for name,value in modules.items()):raise ValueError('Producer source changed during generation; rerun.')
    total=sum(map(len,payloads.values()))+len(board_before)
    if total>5*1024*1024:raise ValueError('Example collection exceeds the 5 MiB target.')
    for name,payload in payloads.items():(output/name).write_bytes(payload)
    # KiCad may create fixture-local project/display defaults. Project rules are
    # part of SI custody; local display state is not a published design input.
    board.with_suffix('.kicad_prl').unlink(missing_ok=True)
    provenance=dict(schema='wayricad.pocket-kivi-examples/v1',fixture='example.kicad_pcb',source_sha256=digest,
        runtime=dict(python=sys.version.split()[0],kicad=pcbnew.GetBuildVersion(),numpy=numpy.__version__,
                     scipy=scipy.__version__,vtk=vtk.vtkVersion.GetVTKVersion(),matplotlib=matplotlib.__version__),
        producer_versions=versions,
        producer_modules=modules,producer_source_normalization='CRLF to LF only',
        files={name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()},
        request_inputs={'pi':{k:v for k,v in pi_request.items() if k!='board_path'},
                        'si':{k:v for k,v in si_request.items() if k not in ('board_path','source_fingerprints')},
                        'thermal':{k:v for k,v in thermal_request.items() if k not in ('board_path','expected_source_sha256')},
                        'transient_settings':transient_request['transient_settings']},
        checks={'native_saved_board_producers':'passed','unchanged_source_bytes':True,
                'viewer_adapters':'not run; pass --viewer-extension with the local extension folder'})
    if viewer_extension is not None:
        provenance['checks']['viewer_adapters']=viewer_checks(output,viewer_extension)
        provenance['files']['viewer-probes.json']=sha(output/'viewer-probes.json')
    project=board.with_suffix('.kicad_pro')
    if project.exists():provenance['files'][project.name]=sha(project)
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=list(payloads),total_sample_bytes=total,source_sha256=digest)))
    return provenance


def viewer_checks(output,extension):
    extension=Path(extension).resolve()
    script=r'''const fs=require('fs'),root=process.argv[1],dir=process.argv[2],a=require(root+'/analysis-data.js'),s=require(root+'/analysis-spatial.js');const names=['quick-pi','quick-si','quick-therm','quick-therm-transient'],rows=[];for(const name of names){const value=JSON.parse(fs.readFileSync(dir+'/'+name+'.pocket-kivi.json','utf8')),parsed=a.parse(name+'.json',JSON.stringify(value));if(!parsed.plots.length)throw Error(name+' has no saved plots');if(!s.sourceBindings(value).some(b=>b.path==='example.kicad_pcb'&&b.sha256===value.source_sha256))throw Error('Source binding lost');const plots=parsed.plots.map(p=>({title:p.title,type:p.type||'waveform',unit:p.unit||null}));const row={name,plots};if(name==='quick-pi'){const p=parsed.plots.find(p=>p.type==='mesh-field'&&p.nodal);row.probe=a.probe(p,15,5);}if(name==='quick-therm-transient'){const p=parsed.plots.find(p=>p.type==='heatmap'&&p.frames);row.heater=a.probe(p,25,5);row.cutout=a.probe(p,15,11);row.history=s.pointHistory(p,25,5);}rows.push(row);}process.stdout.write(JSON.stringify(rows));'''
    node=shutil.which('node')
    if not node:raise RuntimeError('Node.js is unavailable for the requested viewer adapter check.')
    result=subprocess.run([node,'-e',script,str(extension),str(output)],stdin=subprocess.DEVNULL,
                          capture_output=True,text=True,encoding='utf-8',check=True,timeout=30,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    rows=json.loads(result.stdout)
    (output/'viewer-probes.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    return dict(status='passed',module_hashes={name:sha(extension/name) for name in ('analysis-data.js','analysis-spatial.js')})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--viewer-extension',type=Path)
    args=parser.parse_args(argv)
    generate(args.output,args.viewer_extension)


if __name__=='__main__':main()
