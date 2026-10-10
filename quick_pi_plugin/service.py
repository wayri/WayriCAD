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
    from wayricad_runtime.runtime_setup import ensure_runtime, REQUIREMENTS_QUICK_PI, child_environment
    requirements={name: spec for name, spec in REQUIREMENTS_QUICK_PI.items() if name != 'kipy'}
    if request.get('model_dimension')=='3d':
        requirements['gmsh']='gmsh>=4.11,<5'
    python=ensure_runtime(requirements)
    with tempfile.TemporaryDirectory(prefix='wayricad-quick-pi-') as temporary:
        root=Path(temporary); source=root/'request.json';target=root/'response.json'
        source.write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        with (root/'worker.log').open('w+',encoding='utf-8') as log:
            command=[str(python),'-I',str(Path(__file__).with_name('quickmain.py')),'--worker',str(source),str(target)]
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
            try:
                result=json.loads(target.read_text(encoding='utf-8-sig'))
            except (ValueError,OSError) as exc:
                raise RuntimeError('Quick PI worker returned an incomplete or invalid result. '+details) from exc
            if not isinstance(result,dict):raise RuntimeError('Quick PI worker returned an invalid result object. '+details)
            if result.get('error'):raise ValueError(result['error'])
            if process.returncode:raise RuntimeError('Quick PI worker failed: '+details)
            return result


def execute(request):
    from .package_contacts import guard_request
    guard_request(request)
    if request.get('action')=='electrothermal':
        from .electrothermal_service import execute as electrothermal_execute
        return electrothermal_execute(request)
    if request.get('action')=='transient':
        from .transient import solve_transient
        from wayricad_runtime.transient_study import execute_study
        return execute_study(request,solve_transient)
    if request.get('action')=='verify':
        from .verification import run_benchmarks
        return run_benchmarks()
    if request.get('action')=='converge':
        from .convergence import run_study
        return run_study(request,execute)
    original_request=request
    requested_action=request.get('action','inspect')
    voltage_mode=request.get('load_resistance_ohm') is not None
    sweep_mode=requested_action=='sweep'
    if (voltage_mode or sweep_mode) and 'sinks' in request:
        raise ValueError('Voltage-driven load and current sweep require one legacy sink; multisink demands use constant-current mode.')
    if sweep_mode and any(request.get(key) is not None for key in ('source_current_limit','sink_min_voltage','sink_max_voltage')):
        raise ValueError('Current sweeps do not evaluate source budgets or sink voltage bounds. Use a single solved operating point to check those limits.')
    if sweep_mode or voltage_mode:
        if requested_action not in ('solve','sweep'):
            raise ValueError('Voltage-driven load and sweep modes require a solved path.')
        request={**request,'action':'solve','sink_current':1.}
    import pcbnew
    path=Path(request['board_path']).resolve()
    if not path.is_file() or path.suffix.lower()!='.kicad_pcb':raise ValueError('Choose a saved KiCad PCB.')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    board=pcbnew.LoadBoard(str(path))
    if board is None:raise ValueError('KiCad could not load this PCB.')
    action=request.get('action','inspect')
    if action=='inspect':
        nets=sorted({str(p.GetNetname()) for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode()>0})
        terminals=[{'id':p.m_Uuid.AsString(),'pad_uuid':p.m_Uuid.AsString(),
                    'reference':str(fp.GetReference()),'pad_number':str(p.GetNumber()),
                    'layer_ids':[int(l) for l in board.GetEnabledLayers().CuStack() if p.IsOnLayer(l)],
                    'label':f'{fp.GetReference()}.{p.GetNumber()}', 'net':str(p.GetNetname())}
                   for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetCode()>0]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:
            raise ValueError('The board changed during inspection. Reload and run again.')
        return {'nets':nets,'terminals':terminals,'layers':[{'id':layer,'name':board.GetLayerName(layer)}
                for layer in board.GetEnabledLayers().CuStack()],'source_sha256':before}
    if action=='return_path':
        from .return_path import collect_board_evidence,audit_return_path
        evidence=collect_board_evidence(board,request['signal_net'],request['return_nets'])
        result=audit_return_path(evidence,
            sample_pitch_mm=float(request.get('sample_pitch_mm',.25)),
            return_via_radius_mm=float(request.get('return_via_radius_mm',2.)))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during return-path review. Reload and run again.')
        return {'return_path':result,'evidence':evidence,'request':request,'source_sha256':before}
    if action not in ('geometry','mesh','solve'):raise ValueError('Unknown Quick PI action: '+str(action))
    if action=='solve': sink_requests(request)
    from .board_geometry import extract
    full3d=request.get('model_dimension','2.5d')=='3d'
    if request.get('model_dimension','2.5d') not in ('2.5d','3d'):
        raise ValueError('Choose model_dimension 2.5d or 3d.')
    if full3d and (request.get('series') or voltage_mode or sweep_mode or request.get('html_output') or 'sinks' in request or
                   any(request.get(key) is not None for key in ('source_current_limit','sink_min_voltage','sink_max_voltage'))):
        raise ValueError('Full 3D currently supports one net with prescribed current and JSON output; series, load/sweep and HTML views require 2.5D.')
    if full3d and request.get('mesh_backend')=='vtk':
        raise ValueError('Full 3D requires Gmsh; VTK is only a 2.5D meshing backend.')
    if request.get('series'):
        output=series_execute(board,path,request)
        output=_operating_result(output,request,original_request,voltage_mode,sweep_mode)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during analysis. Reload and run again.')
        return output
    geometry=extract(board,request['net'],source_path=path,stackup_override=request.get('stackup_override'))
    if full3d:
        output={'geometry':geometry,'request':request,
                'model':'3D DC copper-volume conductivity; tetrahedral FEM'}
        if action!='geometry':
            from .full3d import build_volume_mesh,solve_volume
            mesh=build_volume_mesh(geometry,edge_mm=float(request.get('edge_mm',.25)),
                                   plating_mm=float(request.get('plating_mm',.025)),
                                   max_tetrahedra=int(request.get('max_tetrahedra',250000)))
            output['mesh']=mesh
            if action=='solve':
                def nodes(key):
                    chosen=request[key]
                    if chosen in mesh['terminal_nodes']:return mesh['terminal_nodes'][chosen]
                    match=[t['id'] for t in geometry['terminals'] if t['label']==chosen]
                    if len(match)!=1:raise ValueError('Select one unambiguous source and sink pad on this net: '+str(chosen))
                    if match[0] not in mesh['terminal_nodes']:
                        raise ValueError('Selected pad has no 3D electrode mesh vertices. Reduce the mesh edge: '+str(chosen))
                    return mesh['terminal_nodes'][match[0]]
                output['result']=solve_volume(mesh,nodes('source_terminal'),nodes('sink_terminal'),
                    source_voltage=float(request.get('source_voltage',1.)),
                    sink_current=float(request.get('sink_current',1.)),options=request.get('options'))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:
            raise ValueError('The board changed during analysis. Reload and run again.')
        return output
    output={'geometry':geometry,'request':request,'model':'2.5D DC copper conduction; layered sheets and plated barrels'}
    if action!='geometry':
        from .mesh import build_mesh
        mesh=build_mesh(geometry,edge_mm=float(request.get('edge_mm',.5)),plating_mm=float(request.get('plating_mm',.025)),
                        backend=request.get('mesh_backend','auto'))
        output['mesh']=mesh
        if action=='solve':
            from .solver import solve
            def terminal(chosen):
                if chosen in mesh['terminal_nodes']:
                    row=next(t for t in geometry['terminals'] if t['id']==chosen)
                    return row,mesh['terminal_nodes'][chosen]
                match=[t['id'] for t in geometry['terminals'] if t['label']==chosen]
                if len(match)!=1:raise ValueError('Select one unambiguous source and sink pad on this net: '+str(chosen))
                return next(t for t in geometry['terminals'] if t['id']==match[0]),mesh['terminal_nodes'][match[0]]
            sink_specs=[]
            for spec in sink_requests(request):
                row,indices=terminal(spec['terminal'])
                sink_specs.append({**spec,'nodes':indices,'id':row['id'],'label':row['label']})
            source_row,source_nodes=terminal(request['source_terminal'])
            if request.get('package_conduction'):
                from .package_contacts import attach
                mesh,source_nodes,sink_specs=attach(mesh,geometry,request['package_conduction'],source_row['id'],sink_specs)
                output['mesh']=mesh
            output['result']=solve(mesh,source_nodes,
                source_voltage=request.get('source_voltage',1.),sinks=sink_specs,
                source_current_limit=request.get('source_current_limit'),options=request.get('options'))
    output=_operating_result(output,request,original_request,voltage_mode,sweep_mode)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during analysis. Reload and run again.')
    return output


def _operating_result(output,request,original_request,voltage_mode,sweep_mode):
    """Reuse one mesh for a bounded voltage-driven operating point or sweep."""
    if not (voltage_mode or sweep_mode):return output
    from .operating_point import current_sweep,load_current
    from .solver import solve
    base=output['result'];mesh=output['mesh']
    branches=mesh.get('lumped_branches',[])
    forward=sum(float(row.get('forward_drop_V',0.)) for row in base.get('components',[]))
    linear=base['voltage_drop_V']-forward  # one-ampere solve, so V/A = ohms
    if linear < -1e-8:raise ValueError('The one-ampere path resistance is inconsistent; review the mesh and component models.')
    linear=max(0.,linear)
    source=float(request.get('source_voltage',1.))
    if sweep_mode:
        sweep=request.get('sweep')
        if not isinstance(sweep,dict):raise ValueError('Specify sweep start_A, stop_A and points.')
        start,stop=float(sweep['start_A']),float(sweep['stop_A']);points=int(sweep['points'])
        if not all(math.isfinite(v) for v in (start,stop)) or start<=0 or stop<=start or not 2<=points<=200:
            raise ValueError('Sweep requires 0 < start < stop and 2–200 points.')
        currents=[start+(stop-start)*i/(points-1) for i in range(points)]
        output['sweep']={'rows':current_sweep(source,linear,branches,currents),'linear_path_ohm':linear,
                         'source_voltage_V':source,'model':'fixed-temperature DC path sweep; no transient or thermal feedback'}
        output.pop('result',None)
    else:
        load=float(request['load_resistance_ohm'])
        current=load_current(source,linear,load,branches)
        def terminal(key):
            chosen=request[key]
            if chosen in mesh['terminal_nodes']:return mesh['terminal_nodes'][chosen]
            matches=[t['id'] for t in output['geometry']['terminals'] if t['label']==chosen]
            if len(matches)!=1:raise ValueError('Select one unambiguous source and sink pad: '+str(chosen))
            return mesh['terminal_nodes'][matches[0]]
        spec=sink_requests({**request,'sink_current':current})[0]
        output['result']=solve(mesh,terminal('source_terminal'),
                               source_voltage=source,sinks=[{**spec,'nodes':terminal('sink_terminal')}],
                               source_current_limit=request.get('source_current_limit'),options=request.get('options'))
        output['result']['load_resistance_ohm']=load
        output['result']['load_power_W']=current*current*load
        output['result']['operating_mode']='voltage_driven_resistive_load'
    output['request']=original_request
    return output


def sink_requests(request):
    """Validate terminal-based load requests before expensive mesh construction."""
    def number(value,label,positive=False):
        if isinstance(value,bool): raise ValueError(label+' must be a finite number.')
        try: value=float(value)
        except (ValueError,TypeError) as exc: raise ValueError(label+' must be a finite number.') from exc
        if not math.isfinite(value) or (value<=0 if positive else value<0):
            raise ValueError(label+' must be finite and '+('positive.' if positive else 'nonnegative.'))
        return value
    if request.get('source_current_limit') is not None:
        number(request['source_current_limit'],'Source current limit')
    if 'sinks' in request:
        if any(request.get(key) is not None for key in ('sink_terminal','sink_current','sink_min_voltage','sink_max_voltage')):
            raise ValueError('Choose sinks or the legacy sink_terminal/sink_current fields, not both.')
        if request.get('series'):
            raise ValueError('Multisink requests cannot be combined with a series-component path.')
        specs=request['sinks']
    else:
        specs=[{'terminal':request.get('sink_terminal'),'current_A':request.get('sink_current',1.),
                'min_voltage_V':request.get('sink_min_voltage',0.)}]
        if request.get('sink_max_voltage') is not None: specs[0]['max_voltage_V']=request['sink_max_voltage']
    if not isinstance(specs,(list,tuple)) or not 1<=len(specs)<=1024:
        raise ValueError('Specify 1 to 1,024 sinks.')
    result=[];seen=set()
    for spec in specs:
        if not isinstance(spec,dict): raise ValueError('Each sink needs a terminal and current_A.')
        unknown=set(spec)-{'terminal','current_A','min_voltage_V','max_voltage_V'}
        if unknown: raise ValueError('Unknown sink parameter: '+', '.join(sorted(unknown)))
        chosen=spec.get('terminal')
        if not isinstance(chosen,str) or not chosen.strip(): raise ValueError('Each sink needs a nonempty pad label or UUID.')
        if chosen in seen: raise ValueError('Repeated sink terminal: '+chosen)
        seen.add(chosen)
        current=number(spec.get('current_A'),'Sink current',True)
        minimum=number(spec.get('min_voltage_V',0),'Sink minimum voltage')
        maximum=spec.get('max_voltage_V')
        if maximum is not None:
            maximum=number(maximum,'Sink maximum voltage')
            if maximum<minimum: raise ValueError('Sink maximum voltage must be at least its minimum voltage.')
        result.append({'terminal':chosen,'current_A':current,'min_voltage_V':minimum,'max_voltage_V':maximum})
    try: total=math.fsum(row['current_A'] for row in result)
    except OverflowError as exc: raise ValueError('Total sink current must be finite.') from exc
    if not math.isfinite(total):
        raise ValueError('Total sink current must be finite.')
    return result


def series_execute(board,path,request):
    """Separate copper domains joined only by explicit lumped components."""
    import math
    from .series_models import validate_model
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
    sink_spec=sink_requests(request)[0]
    start=terminal(request['source_terminal']);end=terminal(sink_spec['terminal'])
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
        validate_model(branch)
        resistance=float(branch.get('resistance_ohm',0.));inductance=float(branch.get('inductance_h',0.))
        if not all(math.isfinite(v) and v>=0 for v in (resistance,inductance)):
            raise ValueError('Series R and L must be finite and nonnegative.')
        if not (resistance or inductance or 'fixed_drop_v' in branch or 'diode' in branch):
            raise ValueError('A series component needs resistance, inductance or a forward-drop model.')
        branches.append({**branch,'id':str(branch.get('id',a['label'].split('.')[0]))+f':{index}',
                         'from_terminal':a['id'],'to_terminal':b['id'],'resistance_ohm':resistance,'inductance_h':inductance,
                         'from_domain':index,'to_domain':index+1})
        previous=b;nets.append(b['net'])
    if previous['net']!=end['net']:raise ValueError('The last component and ending pad do not share a net.')
    has_drop=any('fixed_drop_v' in branch or 'diode' in branch for branch in branches)
    if has_drop and len(set(nets))!=len(nets):
        raise ValueError('Forward-drop paths must cross each net only once; a repeated net creates an alternate path.')
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
        local=build_mesh(geometry,edge_mm=mesh['edge_mm'],plating_mm=mesh['plating_mm'],
                         backend=request.get('mesh_backend','auto'))
        offset=len(mesh['points_mm']);mesh['points_mm'].extend(local['points_mm'])
        if has_drop:mesh.setdefault('series_domains',[]).append({'net':net,'start':offset,'end':len(mesh['points_mm'])})
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
    result=solve(mesh,mesh['terminal_nodes'][start['id']],
        source_voltage=request.get('source_voltage',1.),
        sinks=[{**sink_spec,'nodes':mesh['terminal_nodes'][end['id']],'id':end['id'],'label':end['label']}],
        source_current_limit=request.get('source_current_limit'),options=request.get('options'))
    return {'geometry':geometry,'mesh':mesh,'result':result,'request':request,
            'model':'2.5D DC copper conduction with explicit series R/L and forward-drop branches at prescribed current'}
