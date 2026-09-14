"""Bounded worker processes keep meshing and native board IO out of wx."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time


def run_job(request, cancelled=None, timeout=300):
    if not math.isfinite(float(timeout)) or float(timeout)<=0:
        raise ValueError('Worker timeout must be finite and positive.')
    if cancelled and cancelled():raise InterruptedError('Quick PI cancelled before starting the worker.')
    from wayricad_runtime.native_analysis import native_python, child_environment
    with tempfile.TemporaryDirectory(prefix='wayricad-quick-pi-') as temporary:
        root=Path(temporary); source=root/'request.json';target=root/'response.json'
        source.write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        with (root/'worker.log').open('w+',encoding='utf-8') as log:
            command=[str(native_python()),str(Path(__file__).with_name('quickmain.py')),'--worker',str(source),str(target)]
            process=subprocess.Popen(command,env=child_environment(),stdin=subprocess.DEVNULL,
                stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started=time.monotonic()
            try:
                while process.poll() is None:
                    if cancelled and cancelled():raise InterruptedError('Quick PI cancelled. No board files were changed.')
                    if time.monotonic()-started>timeout:raise TimeoutError('Quick PI exceeded its time budget. Use a coarser mesh or smaller net.')
                    time.sleep(.1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            log.seek(0); details=log.read()[-4000:]
            if not target.is_file():raise RuntimeError('Quick PI worker did not produce a result. '+details)
            result=json.loads(target.read_text(encoding='utf-8'))
            if result.get('error'):raise ValueError(result['error'])
            if process.returncode:raise RuntimeError('Quick PI worker failed: '+details)
            return result


def execute(request):
    import pcbnew
    path=Path(request['board_path']).resolve()
    if not path.is_file() or path.suffix.lower()!='.kicad_pcb':raise ValueError('Choose a saved KiCad PCB.')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    board=pcbnew.LoadBoard(str(path))
    if board is None:raise ValueError('KiCad could not load this PCB.')
    action=request.get('action','inspect')
    if action=='inspect':
        nets=sorted({str(p.GetNetname()) for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode()>0})
        terminals=[{'id':p.m_Uuid.AsString(),'label':f'{fp.GetReference()}.{p.GetNumber()}', 'net':str(p.GetNetname())}
                   for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode()>0]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:
            raise ValueError('The board changed during inspection. Reload and run again.')
        return {'nets':nets,'terminals':terminals,'layers':[{'id':layer,'name':board.GetLayerName(layer)}
                for layer in board.GetEnabledLayers().CuStack()],'source_sha256':before}
    if action not in ('geometry','mesh','solve'):raise ValueError('Unknown Quick PI action: '+str(action))
    from .board_geometry import extract
    if request.get('series'):
        output=series_execute(board,path,request)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during analysis. Reload and run again.')
        return output
    geometry=extract(board,request['net'],source_path=path,stackup_override=request.get('stackup_override'))
    output={'geometry':geometry,'request':request,'model':'2.5D DC copper conduction; layered sheets and plated barrels'}
    if action!='geometry':
        from .mesh import build_mesh
        mesh=build_mesh(geometry,edge_mm=float(request.get('edge_mm',.5)),plating_mm=float(request.get('plating_mm',.025)))
        output['mesh']=mesh
        if action=='solve':
            from .solver import solve
            def nodes(key):
                chosen=request[key]
                if chosen in mesh['terminal_nodes']:return mesh['terminal_nodes'][chosen]
                match=[t['id'] for t in geometry['terminals'] if t['label']==chosen]
                if len(match)!=1:raise ValueError('Select one unambiguous source and sink pad on this net: '+str(chosen))
                return mesh['terminal_nodes'][match[0]]
            output['result']=solve(mesh,nodes('source_terminal'),nodes('sink_terminal'),
                source_voltage=float(request.get('source_voltage',1.)),sink_current=float(request.get('sink_current',1.)),
                options=request.get('options'))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during analysis. Reload and run again.')
    return output


def series_execute(board,path,request):
    """Separate copper domains joined only by explicit lumped components."""
    import math
    inventory=[]
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode()>0:
                inventory.append({'id':pad.m_Uuid.AsString(),'label':f'{fp.GetReference()}.{pad.GetNumber()}',
                                  'net':str(pad.GetNetname()),'footprint':fp.m_Uuid.AsString()})
    def terminal(value):
        matches=[p for p in inventory if p['id']==value or p['label']==value]
        if len(matches)!=1:raise ValueError('Choose an unambiguous pad: '+str(value))
        return matches[0]
    start=terminal(request['source_terminal']);end=terminal(request['sink_terminal'])
    if start['id']==end['id']:raise ValueError('Source and sink terminals must be distinct.')
    seen={start['id'],end['id']}
    previous=start;branches=[];nets=[start['net']]
    if request.get('net') and request['net']!=start['net']:raise ValueError('The named net does not contain the starting pad.')
    for index,branch in enumerate(request['series']):
        a=terminal(branch['from_pad']);b=terminal(branch['to_pad'])
        if a['id']==b['id'] or a['footprint']!=b['footprint']:raise ValueError('Each series branch must join distinct pads of one component.')
        if a['id'] in seen or b['id'] in seen:
            raise ValueError('Repeated series endpoint. Each component pad must occur once in the requested path.')
        seen.update((a['id'],b['id']))
        if previous['net']!=a['net']:raise ValueError(f"Copper path changes net without a component: {previous['label']} → {a['label']}")
        resistance=float(branch['resistance_ohm']);inductance=float(branch.get('inductance_h',0.))
        if not all(math.isfinite(v) and v>=0 for v in (resistance,inductance)):
            raise ValueError('Series R and L must be finite and nonnegative.')
        branches.append({**branch,'id':str(branch.get('id',a['label'].split('.')[0]))+f':{index}',
                         'from_terminal':a['id'],'to_terminal':b['id'],'resistance_ohm':resistance,'inductance_h':inductance})
        previous=b;nets.append(b['net'])
    if previous['net']!=end['net']:raise ValueError('The last component and ending pad do not share a net.')
    # Validate the circuit before loading optional numerical dependencies.
    from .board_geometry import extract
    from .mesh import build_mesh
    from .solver import solve
    mesh={'points_mm':[],'triangles':[],'triangle_thickness_mm':[],'triangle_layer':[],
          'vias':[],'terminal_nodes':{},'mesh_report':[],'lumped_branches':[],
          'edge_mm':float(request.get('edge_mm',.5)),'plating_mm':float(request.get('plating_mm',.025))}
    merged_layers={};all_terminals=[];all_vias=[];warnings=[];domain_counts=[]
    for net in dict.fromkeys(nets):
        geometry=extract(board,net,source_path=path,stackup_override=request.get('stackup_override'))
        local=build_mesh(geometry,edge_mm=mesh['edge_mm'],plating_mm=mesh['plating_mm'])
        offset=len(mesh['points_mm']);mesh['points_mm'].extend(local['points_mm'])
        mesh['triangles'].extend([[i+offset for i in t] for t in local['triangles']])
        if len(mesh['points_mm'])>250000 or len(mesh['triangles'])>500000:
            raise ValueError('The complete series circuit exceeds the mesh budget. Increase mesh edge length.')
        for key in ('triangle_thickness_mm','triangle_layer'):mesh[key].extend(local[key])
        for via in local['vias']:
            mesh['vias'].append({**via,'top_nodes':[i+offset for i in via['top_nodes']],
                                'bottom_nodes':[i+offset for i in via['bottom_nodes']]})
        mesh['terminal_nodes'].update({key:[i+offset for i in value] for key,value in local['terminal_nodes'].items()})
        mesh['mesh_report'].extend([{'net':net,**row} for row in local['mesh_report']])
        for layer in geometry['layers']:
            if layer['id'] not in merged_layers:merged_layers[layer['id']]={**layer,'polygons':[],'mesh_regions':[]}
            merged_layers[layer['id']]['polygons'].extend(layer['polygons'])
        all_terminals.extend(geometry['terminals']);all_vias.extend(geometry['vias'])
        warnings.extend(geometry.get('warnings',[]));domain_counts.append({'net':net,**geometry.get('counts',{})})
    for branch in branches:
        mesh['lumped_branches'].append({**branch,'top_nodes':mesh['terminal_nodes'][branch['from_terminal']],
                                       'bottom_nodes':mesh['terminal_nodes'][branch['to_terminal']]})
    geometry={**geometry,'net':' → '.join(nets),'nets':list(dict.fromkeys(nets)),
              'layers':list(merged_layers.values()),'terminals':all_terminals,'vias':all_vias,
              'counts':{'nets':len(set(nets))},'domain_counts':domain_counts,'warnings':sorted(set(warnings))}
    geometry['geometry_sha256']=hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest()
    mesh['geometry']=geometry
    result=solve(mesh,mesh['terminal_nodes'][start['id']],mesh['terminal_nodes'][end['id']],
        source_voltage=float(request.get('source_voltage',1.)),sink_current=float(request.get('sink_current',1.)),
        options=request.get('options'))
    return {'geometry':geometry,'mesh':mesh,'result':result,'request':request,
            'model':'2.5D DC copper conduction with explicit series RL components; inductors are steady-state DC branches'}
