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
from collections import OrderedDict
from threading import RLock


class _ResultCache:
    """Bounded JSON bytes only; no live boards, arrays or mutable result aliases."""
    def __init__(self,max_bytes=96*1024*1024,max_entries=4):
        self.max_bytes=max_bytes;self.max_entries=max_entries
        self.entries=OrderedDict();self.size=0;self.lock=RLock()

    def get(self,key):
        if key is None:return None
        with self.lock:
            value=self.entries.get(key)
            if value is not None:self.entries.move_to_end(key)
            return value

    def put(self,key,value):
        if key is None or len(value)>self.max_bytes//2:return
        with self.lock:
            previous=self.entries.pop(key,None)
            if previous is not None:self.size-=len(previous)
            self.entries[key]=value;self.size+=len(value)
            while self.size>self.max_bytes or len(self.entries)>self.max_entries:
                _,removed=self.entries.popitem(last=False);self.size-=len(removed)


_RESULT_CACHE=_ResultCache()


def _request_key(request):
    """Identity of a read-only saved-board request and all saved rule inputs."""
    if request.get('action','inspect') not in ('inspect','geometry','mesh','solve') or request.get('html_output'):
        return None
    if not request.get('board_path'):return None
    try:
        source=Path(request['board_path']).resolve()
        if source.suffix.lower()!='.kicad_pcb' or not source.is_file():return None
        inputs=[]
        for path in (source,source.with_suffix('.kicad_pro'),source.with_suffix('.kicad_dru')):
            inputs.append((str(path),hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
        # Runtime overrides select different native installations. Never serve
        # an earlier result after the caller changes that explicit identity.
        payload=[request,inputs,os.environ.get('WAYRICAD_KICAD_PYTHON')]
        return hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    except OSError:
        return None  # Let the worker provide its normal saved-source diagnostic.


def _display_output(output,request,board,path,source_hash):
    """Return display-only JSON from the worker's already owned native board."""
    if not request.get('include_display_scene'):return output
    from wayricad_runtime.board_render import extract_board
    geometry=output.get('geometry',{})
    scope=request.get('display_nets',geometry.get('nets') or ([geometry['net']] if geometry.get('net') else None))
    if scope=='default':
        names=output.get('nets',[])
        scope=[next((name for name in names if name.startswith(('+','VCC','VDD'))),names[0])] if names else []
    if scope is not None and (not isinstance(scope,(list,tuple)) or any(not isinstance(n,str) for n in scope)):
        raise ValueError('display_nets must be a list of net names, default, or null for all board copper.')
    scene=extract_board(board,visible_nets=scope,include_fabrication=False)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source_hash:
        raise ValueError('The board changed during display extraction. Reload and run again.')
    scene['source_sha256']=source_hash
    output['board_scene']=scene;output['scene_nets']=None if scope is None else sorted(set(scope))
    return output


def mesh_cell_budget(request):
    """Explicit total triangle capacity for one saved-board 2.5D copper mesh."""
    value=request.get('max_cells',400000)
    if isinstance(value,bool) or not isinstance(value,int) or not 1000<=value<=2000000:
        raise ValueError('max_cells must be an integer from 1,000 to 2,000,000 (default 400,000).')
    if 'max_cells' in request and (request.get('model_dimension','2.5d')!='2.5d' or
                                   request.get('series') or request.get('package_conduction')):
        raise ValueError('max_cells supports 2.5D copper only; 3D, series and package paths retain their separate budgets.')
    return value


def _solver_mesh_budgets(request):
    # Keep existing direct callers and default requests on the original guards.
    if 'max_cells' not in request:return {}
    value=mesh_cell_budget(request)
    return {'mesh_cell_budget':max(500000,value),
            'mesh_vertex_budget':max(250000,min(2000000,value))}


def _requires_gmsh(request):
    """Inspect only supported mesh-setting locations before preparing a worker."""
    def selected(settings):
        return isinstance(settings,dict) and (settings.get('model_dimension')=='3d' or settings.get('mesh_backend')=='gmsh')
    if selected(request):return True
    if request.get('action')!='batch':return False
    study=request.get('study')
    if not isinstance(study,dict):return False
    cases=study.get('cases',[])
    if isinstance(cases,list):
        for case in cases:
            if isinstance(case,dict) and any(selected(case.get(key)) for key in ('electrical','return_conduction')):
                return True
    groups=study.get('shared_returns',[])
    return isinstance(groups,list) and any(selected(group) for group in groups)


def run_job(request, cancelled=None, timeout=300):
    from .mesh_sizing import mode as sizing_mode
    sizing_mode(request)
    if not math.isfinite(float(timeout)) or float(timeout)<=0:
        raise ValueError('Worker timeout must be finite and positive.')
    if cancelled and cancelled():raise InterruptedError('Quick PI cancelled before starting the worker.')
    cache_started=time.monotonic();cache_key=_request_key(request)
    cached=_RESULT_CACHE.get(cache_key)
    if cached is not None:
        result=json.loads(cached)
        if cancelled and cancelled():raise InterruptedError('Quick PI cancelled. No board files were changed.')
        if time.monotonic()-cache_started>timeout:raise TimeoutError('Quick PI exceeded its time budget.')
        if _request_key(request)!=cache_key:raise ValueError('The board or project rules changed during cached analysis. Reload and run again.')
        return result
    from wayricad_runtime.runtime_setup import ensure_runtime, REQUIREMENTS_QUICK_PI, child_environment
    requirements={name: spec for name, spec in REQUIREMENTS_QUICK_PI.items() if name != 'kipy'}
    if request.get('action')=='ac':
        # Explicit cross-sections need no native board IO, VTK or mesher imports.
        requirements={name:spec for name,spec in requirements.items() if name in ('numpy','scipy')}
    if _requires_gmsh(request):
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
                payload=target.read_bytes();result=json.loads(payload)
            except (ValueError,OSError) as exc:
                raise RuntimeError('Quick PI worker returned an incomplete or invalid result. '+details) from exc
            if not isinstance(result,dict):raise RuntimeError('Quick PI worker returned an invalid result object. '+details)
            if result.get('error'):raise ValueError(result['error'])
            if process.returncode:raise RuntimeError('Quick PI worker failed: '+details)
            if cache_key is not None:
                if cancelled and cancelled():raise InterruptedError('Quick PI cancelled. No board files were changed.')
                if _request_key(request)!=cache_key:raise ValueError('The board or project rules changed during analysis. Reload and run again.')
                _RESULT_CACHE.put(cache_key,payload)
            return result


def execute(request,*,_boards=None):
    from .mesh_sizing import mode as sizing_mode
    sizing_mode(request)
    if request.get('action')=='ac':
        from .ac_analysis import run_study
        study=request.get('study')
        source=Path(request['board_path']).resolve() if request.get('board_path') else None
        study_source=Path(request['study_input_path']).resolve() if request.get('study_input_path') else None
        study_before=None
        if study_source:
            study_before=hashlib.sha256(study_source.read_bytes()).hexdigest()
            if request.get('study_file_sha256') and request['study_file_sha256']!=study_before:
                raise ValueError('AC input file changed. Reload before running.')
        before=None
        if source:
            if source.suffix.lower()!='.kicad_pcb' or not source.is_file():
                raise ValueError('Choose a saved KiCad PCB for AC provenance.')
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            if request.get('source_sha256') and request['source_sha256']!=before:
                raise ValueError('Saved board changed. Reload before the AC study.')
        result=run_study(study)
        if source and hashlib.sha256(source.read_bytes()).hexdigest()!=before:
            raise ValueError('Saved board changed during the AC study; discard the result.')
        if study_source and hashlib.sha256(study_source.read_bytes()).hexdigest()!=study_before:
            raise ValueError('AC input file changed during analysis; discard the result.')
        return {'ac':result,'study':study,'study_sha256':hashlib.sha256(
                    json.dumps(study,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
                'board_path':str(source) if source else None,'source_sha256':before,
                'board_binding':'provenance_only','study_input_path':str(study_source) if study_source else None,
                'study_file_sha256':study_before}
    if request.get('action')=='batch':
        from .batch import execute as execute_batch
        # One owned native board per batch, never shared across workers or jobs.
        # Each case still checks the saved bytes before and after its analysis.
        boards={}
        return execute_batch(request,lambda case:execute(case,_boards=boards))
    max_cells=mesh_cell_budget(request)
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
    identity=(str(path),before)
    board=_boards.get(identity) if _boards is not None else None
    if board is None:
        board=pcbnew.LoadBoard(str(path))
        if board is not None and _boards is not None:
            _boards.clear();_boards[identity]=board
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
        output={'nets':nets,'terminals':terminals,'layers':[{'id':layer,'name':board.GetLayerName(layer)}
                for layer in board.GetEnabledLayers().CuStack()],'source_sha256':before}
        return _display_output(output,request,board,path,before)
    if action=='return_path':
        from .return_path import collect_board_evidence,audit_return_path
        evidence=collect_board_evidence(board,request['signal_net'],request['return_nets'])
        result=audit_return_path(evidence,
            sample_pitch_mm=float(request.get('sample_pitch_mm',.25)),
            return_via_radius_mm=float(request.get('return_via_radius_mm',2.)),return_terminal_ids=request.get('return_terminal_ids'),return_terminal_roles=request.get('return_terminal_roles'))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during return-path review. Reload and run again.')
        return {'return_path':result,'evidence':evidence,'request':request,'source_sha256':before}
    if action not in ('geometry','mesh','solve'):raise ValueError('Unknown Quick PI action: '+str(action))
    if action=='solve':
        from .terminals import source_names
        source_names(request)
        specs=sink_requests(request)
        grouped='source_terminals' in request or any('terminals' in spec for spec in specs)
        if grouped and (request.get('model_dimension','2.5d')!='2.5d' or request.get('series') or
                        request.get('package_conduction') or voltage_mode or sweep_mode):
            raise ValueError('Grouped pad units support fixed-current 2.5D copper only; package, series, 3D and resistive/sweep modes are unsupported.')
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
        return _display_output(output,request,board,path,before)
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
        return _display_output(output,request,board,path,before)
    output={'geometry':geometry,'request':request,'model':'2.5D DC copper conduction; layered sheets and plated barrels'}
    if sizing_mode(request)=='auto':
        from .mesh_sizing import recommend
        output['mesh_sizing_recommendation']=recommend(geometry,max_cells)
    if action!='geometry':
        from .mesh import build_mesh
        mesh=build_mesh(geometry,edge_mm=float(request.get('edge_mm',.5)),plating_mm=float(request.get('plating_mm',.025)),
                        backend=request.get('mesh_backend','auto'),max_cells=max_cells,sizing=request.get('mesh_sizing','manual'))
        output['mesh']=mesh
        if action=='solve':
            from .solver import solve
            from .terminals import resolve_units
            source_rows,source_nodes,sink_specs,units=resolve_units(request,geometry,mesh,sink_requests(request))
            source_row=source_rows[0]
            output['terminal_units']=units
            if request.get('package_conduction'):
                from .package_contacts import attach
                mesh,source_nodes,sink_specs=attach(mesh,geometry,request['package_conduction'],source_row['id'],sink_specs)
                output['mesh']=mesh
            output['result']=solve(mesh,source_nodes,
                source_voltage=request.get('source_voltage',1.),sinks=sink_specs,
                source_current_limit=request.get('source_current_limit'),options=request.get('options'),
                **_solver_mesh_budgets(request))
    output=_operating_result(output,request,original_request,voltage_mode,sweep_mode)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('The board changed during analysis. Reload and run again.')
    return _display_output(output,request,board,path,before)


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
                               source_current_limit=request.get('source_current_limit'),options=request.get('options'),
                               **_solver_mesh_budgets(request))
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
    from .terminals import pad_names
    result=[];seen=set();identifiers=set()
    for spec in specs:
        if not isinstance(spec,dict): raise ValueError('Each sink needs a terminal and current_A.')
        unknown=set(spec)-{'terminal','terminals','id','label','current_A','min_voltage_V','max_voltage_V'}
        if unknown: raise ValueError('Unknown sink parameter: '+', '.join(sorted(unknown)))
        chosen=pad_names(spec)
        if seen.intersection(chosen):raise ValueError('Repeated sink terminal: '+', '.join(chosen))
        seen.update(chosen)
        if 'id' in spec:
            if not isinstance(spec['id'],str) or not spec['id'].strip() or spec['id'] in identifiers:
                raise ValueError('Load unit IDs must be unique nonempty strings.')
            identifiers.add(spec['id'])
        current=number(spec.get('current_A'),'Sink current',True)
        minimum=number(spec.get('min_voltage_V',0),'Sink minimum voltage')
        maximum=spec.get('max_voltage_V')
        if maximum is not None:
            maximum=number(maximum,'Sink maximum voltage')
            if maximum<minimum: raise ValueError('Sink maximum voltage must be at least its minimum voltage.')
        result.append({**spec,'current_A':current,'min_voltage_V':minimum,'max_voltage_V':maximum})
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
                         backend=request.get('mesh_backend','auto'),sizing=request.get('mesh_sizing','manual'),
                         max_cells=min(400000,500000-len(mesh['triangles'])))
        mesh.setdefault('mesh_sizing',{'mode':request.get('mesh_sizing','manual'),'domains':[]})['domains'].append(
            {'net':net,**local['mesh_sizing']})
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
