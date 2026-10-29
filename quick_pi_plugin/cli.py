"""Quick PI CLI. Analyze saved files; never mutate PCB copper."""
import argparse
import json
import math
import sys
from pathlib import Path


def _loads(loads, limits, powers=None):
    """Parse explicit constant-current loads without silently discarding limits."""
    rows=[];by_terminal={}
    for terminal,current in loads or []:
        value=float(current)
        if not math.isfinite(value) or value<=0:raise ValueError('Load current must be finite and positive.')
        if terminal in by_terminal:raise ValueError('Duplicate load terminal: '+terminal)
        row={'terminal':terminal,'current_A':value};rows.append(row);by_terminal[terminal]=row
    for terminal,power in powers or []:
        value=float(power)
        if not math.isfinite(value) or value<=0:raise ValueError('Load power must be finite and positive.')
        if terminal in by_terminal:raise ValueError('Duplicate load terminal: '+terminal)
        row={'terminal':terminal,'power_W':value};rows.append(row);by_terminal[terminal]=row
    bounded=set()
    for terminal,minimum,maximum in limits or []:
        if terminal not in by_terminal:raise ValueError('Voltage limits require a matching --load or --power-load: '+terminal)
        if terminal in bounded:raise ValueError('Duplicate load voltage limits: '+terminal)
        bounded.add(terminal);row=by_terminal[terminal]
        for key,text in [('min_voltage_V',minimum),('max_voltage_V',maximum)]:
            if text=='-':continue
            value=float(text)
            if not math.isfinite(value) or value<0:raise ValueError('Load voltage limits must be finite and nonnegative.')
            row[key]=value
        if row.get('max_voltage_V',math.inf)<row.get('min_voltage_V',0):raise ValueError('Maximum load voltage must be at least the minimum.')
    return rows


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board',type=Path,nargs='?')
    parser.add_argument('--insulation-result',type=Path,help='Saved multi-net batch result JSON for post-solve engineering screening only.')
    parser.add_argument('--insulation-policy',type=Path,help='Explicit rule/material/environment/voltage and spacing policy JSON; requires --insulation-result.')
    parser.add_argument('--power-tree',type=Path,help='Validate a reviewed/draft power-intent JSON; does not run or configure a copper solve.')
    parser.add_argument('--infer-power-tree',action='store_true',help='Suggest unreviewed power intent from a saved board; requires review of roles, returns and polarity.')
    parser.add_argument('--probe-result',type=Path,help='Saved single-case PI JSON for read-only differential voltage probing; no new solve.')
    parser.add_argument('--probe-a',nargs=3,metavar=('LAYER','X_MM','Y_MM'),help='Differential point A on solved 2.5D sheet copper.')
    parser.add_argument('--probe-b',nargs=3,metavar=('LAYER','X_MM','Y_MM'),help='Differential point B; reports V(A)-V(B) in the same saved potential reference.')
    parser.add_argument('--batch',type=Path,help='Multi-net DC study JSON (wayricad.pi-batch/v1), pad units, shared-return groups and optional independent return review/thermal feedback.')
    parser.add_argument('--transient',type=Path,help='Explicit R/L/C load-step JSON; optional board supplies saved-file provenance. Returns 4 for limit violations.')
    parser.add_argument('--electrothermal',type=Path,help='Explicit steady/transient electrothermal study JSON. Returns 3 for nonconvergence, 4 for operating-limit violations.')
    parser.add_argument('--ac',type=Path,help='Explicit straight-conductor/return AC cross-section JSON (wayricad.pi-ac/v1): skin/proximity effects and DC plus harmonic Joule losses. No converter or HV insulation simulation.')
    parser.add_argument('--verify',action='store_true',help='Run analytical/reference benchmarks in the prepared PI runtime; no board required.')
    parser.add_argument('--net');parser.add_argument('--source');parser.add_argument('--sink')
    parser.add_argument('--voltage',type=float,default=1.);parser.add_argument('--current',type=float)
    parser.add_argument('--load',nargs=2,action='append',metavar=('PAD','CURRENT_A'),help='Repeat for each constant-current sink; cannot combine with --sink, --current or --command.')
    parser.add_argument('--power-load',nargs=2,action='append',metavar=('PAD','POWER_W'),help='Repeat for constant-power sinks; can mix with --load. Fixed-temperature 2.5D only.')
    parser.add_argument('--load-power',type=float,help='Constant-power watts at a single --sink; cannot combine with --current or --load-ohms.')
    parser.add_argument('--load-voltage-limits',nargs=3,action='append',metavar=('PAD','MIN_V','MAX_V'),help='Limits for a matching --load; use - for either omitted bound.')
    parser.add_argument('--sink-min-voltage',type=float,help='Minimum voltage for a legacy single sink or --command path; default 0 V.')
    parser.add_argument('--sink-max-voltage',type=float,help='Maximum voltage for a legacy single sink or --command path; omitted means unbounded.')
    parser.add_argument('--source-current-limit',type=float,help='Nonnegative source current budget in amperes; omitted means unlimited. Infeasible results return 4.')
    parser.add_argument('--load-ohms',type=float,help='Solve DC current from source voltage and a resistive load to 0 V.')
    parser.add_argument('--sweep',nargs=3,metavar=('START_A','STOP_A','POINTS'),help='Sweep prescribed DC currents (2–200 points).')
    parser.add_argument('--return-path',action='store_true',help='Screen saved signal tracks against explicitly selected return nets.')
    parser.add_argument('--return-nets',nargs='+');parser.add_argument('--return-pitch',type=float,default=.25)
    parser.add_argument('--return-via-radius',type=float,default=2.)
    parser.add_argument('--mesh-edge',type=float);parser.add_argument('--plating',type=float,default=.025)
    parser.add_argument('--auto-mesh',action='store_true',help='Use geometry-recommended background and dynamic local 2.5D refinement; cannot combine with --mesh-edge. Budget failures are not coarsened automatically.')
    parser.add_argument('--max-cells',type=int,
                        help='Explicit 2.5D copper triangle budget across all layers: 1000–2000000; default 400000. Batch studies set max_cells per case/group.')
    parser.add_argument('--mesh-backend',choices=('auto','gmsh','vtk'),default='auto',
                        help='Use Gmsh if installed (auto), require Gmsh, or use the VTK mesher.')
    parser.add_argument('--model-dimension',choices=('2.5d','3d'),default='2.5d',
                        help='Opt in to Gmsh tetrahedral, full-volume DC copper conduction.')
    parser.add_argument('--max-tetrahedra',type=int,default=250000,
                        help='Full 3D tetrahedron budget (default 250000).')
    parser.add_argument('--pulse',type=float);parser.add_argument('--temperature',type=float,default=20.)
    parser.add_argument('--melting-temperature',type=float,help='Copper melting threshold in °C (default 1084.62); 2.5D adiabatic screen, not fuse opening.')
    parser.add_argument('--latent-heat',type=float,help='Heat of fusion in J/kg (default 206750); 2.5D copper melting screen.')
    parser.add_argument('--ambient',type=float,default=20.);parser.add_argument('--temperature-limit',type=float,default=105.)
    parser.add_argument('--mesh-only',action='store_true');parser.add_argument('--output',type=Path)
    parser.add_argument('--html',type=Path);parser.add_argument('--timeout',type=float,default=300.)
    parser.add_argument('--converge-levels',type=int,choices=(3,4,5),help='Run a fixed-input study, halving mesh edge each level; returns 3 if incomplete or not stable.')
    parser.add_argument('--convergence-tolerance-percent',type=float,default=1.,help='Maximum change in each of the final two refinements; default 1%%. Does not certify local peaks.')
    parser.add_argument('--package-conduction',type=Path,help='JSON list of explicit lead/solder/BGA paths; 2.5D constant-current DC only.')
    parser.add_argument('--command',help='Console command, including a series-component path; quote the entire command.')
    parser.add_argument('--series-file',type=Path,help='Reviewed series-editor JSON, including explicitly selected parallel R/L parts.')
    args=parser.parse_args(argv)
    if args.insulation_result or args.insulation_policy:
        try:
            from .insulation_cli import run
            return run(args, argv if argv is not None else sys.argv[1:])
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'status':'ERROR','error':str(exc)}));return 2
    if args.power_tree or args.infer_power_tree:
        try:
            from .power_tree_cli import run
            return run(args, argv if argv is not None else sys.argv[1:])
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'status':'ERROR','error':str(exc)}));return 2
    if args.probe_result:
        try:
            from .differential_probe import differential_probe
            from wayricad_runtime.report_ui import checked_sources,publish_documents
            options={word.split('=')[0] for word in (argv if argv is not None else sys.argv[1:]) if word.startswith('--')}
            if args.board or options-{'--probe-result','--probe-a','--probe-b','--output'}:
                raise ValueError('Saved differential probing accepts only --probe-result, --probe-a, --probe-b and optional --output.')
            if not args.probe_a or not args.probe_b:raise ValueError('Provide both --probe-a and --probe-b as LAYER X_MM Y_MM.')
            if args.probe_result.stat().st_size>128*1024*1024:raise ValueError('Saved PI result exceeds 128 MiB.')
            def invalid_constant(value):raise ValueError('Non-finite saved JSON value: '+value)
            raw=args.probe_result.read_bytes();bundle=json.loads(raw,parse_constant=invalid_constant)
            if not isinstance(bundle,dict):raise ValueError('Saved PI result must be a single-case JSON object.')
            point=lambda row:dict(layer=row[0],x_mm=float(row[1]),y_mm=float(row[2]))
            reading=differential_probe(bundle,point(args.probe_a),point(args.probe_b))
            import hashlib
            reading['result_sha256']=hashlib.sha256(raw).hexdigest()
            payload=json.dumps(reading,indent=2,allow_nan=False)+'\n'
            if args.probe_result.read_bytes()!=raw:raise ValueError('Saved PI result changed during probing.')
            if args.output:
                if args.output.suffix.lower()!='.json':raise ValueError('Choose a separate .json differential result output.')
                publish_documents({args.output:payload},sources=[args.probe_result,*checked_sources(bundle)])
            else:print(payload,end='')
            return 0 if reading['status']=='SAMPLED' else 3
        except (ValueError,RuntimeError,OSError,TypeError,RecursionError) as error:
            print(json.dumps({'status':'ERROR','error':str(error)}));return 2
    if args.probe_a or args.probe_b:
        print(json.dumps({'status':'ERROR','error':'--probe-a and --probe-b require --probe-result.'}));return 2
    if args.ac:
        try:
            from .ac_cli import main as ac_cli
            from .service import run_job
            options={word.split('=')[0] for word in (argv if argv is not None else sys.argv[1:]) if word.startswith('--')}
            return ac_cli(args,run_job,forbidden=bool(options-{'--ac','--output','--html','--timeout'}))
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'error':str(exc)}));return 2
    if args.batch:
        try:
            from .batch import cli_main
            from .service import run_job
            options={word.split('=')[0] for word in (argv if argv is not None else sys.argv[1:]) if word.startswith('--')}
            return cli_main(args,run_job,forbidden=bool(options-{'--batch','--output','--html','--timeout'}))
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'error':str(exc)}));return 2
    if args.electrothermal:
        try:
            from .electrothermal_cli import main as electrothermal_cli
            from .service import run_job
            options={word.split('=')[0] for word in (argv if argv is not None else sys.argv[1:]) if word.startswith('--')}
            return electrothermal_cli(args,run_job,forbidden=bool(options-{'--electrothermal','--output','--html','--timeout'}))
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'error':str(exc)}));return 2
    if args.transient:
        try:
            from wayricad_runtime.transient_study import transient_cli
            from .service import run_job
            options={word.split('=')[0] for word in (argv if argv is not None else sys.argv[1:]) if word.startswith('--')}
            return transient_cli(args,run_job,forbidden=bool(options-{'--transient','--output','--html','--timeout'}))
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'error':str(exc)}));return 2
    if args.verify:
        try:
            if args.max_cells is not None:raise ValueError('--max-cells applies to a saved-board 2.5D copper mesh, not reference benchmarks.')
            if args.package_conduction or args.board or args.html or args.net or args.source or args.sink or args.command or args.converge_levels or args.mesh_only or args.load_ohms is not None or args.sweep or args.return_path or args.load or args.load_voltage_limits or args.source_current_limit is not None or args.sink_min_voltage is not None or args.sink_max_voltage is not None:raise ValueError('--verify uses no board, load, path, convergence or HTML options. Use --output for JSON.')
            if args.output and args.output.suffix.lower()!='.json':raise ValueError('Benchmark output must be a .json report.')
            from .service import run_job
            report=run_job({'action':'verify'},timeout=args.timeout)
            payload=json.dumps(report,indent=2,allow_nan=False)
            if args.output:
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload+'\n',encoding='utf-8')
            print(payload);return 0 if report['pass'] else 1
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            print(json.dumps({'error':str(exc)}));return 2
    if not args.board:parser.error('Supply a saved board or use --verify for reference benchmarks.')
    request={'action':'inspect' if not args.net else ('mesh' if args.mesh_only else 'solve'),
        'board_path':str(args.board.resolve()),'net':args.net,'source_terminal':args.source,'sink_terminal':args.sink,
        'source_voltage':args.voltage,'sink_current':1. if args.current is None else args.current,'edge_mm':.5 if args.mesh_edge is None else args.mesh_edge,'plating_mm':args.plating,
        'mesh_backend':args.mesh_backend,
        'model_dimension':args.model_dimension,'max_tetrahedra':args.max_tetrahedra,
        'options':{'temperature_c':args.temperature,'ambient_c':args.ambient,'temperature_limit_c':args.temperature_limit}}
    if args.auto_mesh:request['mesh_sizing']='auto'
    if args.model_dimension=='3d':request['options']={'temperature_c':args.temperature}
    if args.pulse is not None:request['options']['pulse_duration_s']=args.pulse
    if args.melting_temperature is not None:request['options']['melting_temperature_c']=args.melting_temperature
    if args.latent_heat is not None:request['options']['latent_heat_J_kg']=args.latent_heat
    try:
        if args.series_file and (args.command or args.load or args.power_load or args.load_power is not None or args.return_path or args.model_dimension=='3d'):
            raise ValueError('--series-file cannot combine with a console command, multiple loads, power loads, return review or 3D.')
        if args.auto_mesh and args.mesh_edge is not None:raise ValueError('Choose --auto-mesh or a manual --mesh-edge, not both.')
        from .mesh_sizing import mode as sizing_mode
        sizing_mode(request)
        if args.max_cells is not None:
            request['max_cells']=args.max_cells
            from .service import mesh_cell_budget
            mesh_cell_budget(request)
        if args.package_conduction:
            request['package_conduction']=json.loads(args.package_conduction.read_text(encoding='utf-8-sig'))
            from .package_contacts import guard_request
            guard_request(request)
        if args.model_dimension=='3d' and (args.html or args.command or args.load or args.power_load or args.load_power is not None or args.source_current_limit is not None or args.sink_min_voltage is not None or args.sink_max_voltage is not None or args.load_ohms is not None or args.sweep or args.converge_levels or args.return_path or args.pulse is not None or args.melting_temperature is not None or args.latent_heat is not None or args.mesh_backend=='vtk'):
            raise ValueError('Full 3D supports a selected net with prescribed current and JSON output; HTML, series commands, load/sweep, pulse screening, return-path and VTK modes remain 2.5D.')
        if sum(bool(value) for value in (args.return_path,args.load_ohms is not None,args.sweep))>1:
            raise ValueError('Choose one of return-path, load-resistance or current-sweep mode.')
        if args.load_ohms is not None and args.sweep:raise ValueError('Choose either --load-ohms or --sweep.')
        if (args.load or args.power_load) and (args.sink or args.current is not None or args.command or args.load_ohms is not None or args.load_power is not None or args.sweep or args.return_path):
            raise ValueError('--load cannot combine with --sink, --current or --command. Multisink series paths are not supported.')
        loads=_loads(args.load,args.load_voltage_limits,args.power_load)
        if args.load_power is not None:
            if (args.current is not None or args.load_ohms is not None or args.command or args.sweep or args.return_path or args.converge_levels):
                raise ValueError('--load-power requires a single --sink and cannot combine with other operating modes.')
            if not math.isfinite(args.load_power) or args.load_power<=0:raise ValueError('Load power must be finite and positive.')
            request.pop('sink_current',None);request['load_power_W']=args.load_power;request['action']='solve'
        if loads:
            if not args.net:raise ValueError('--load requires --net and --source.')
            request.pop('sink_terminal',None);request.pop('sink_current',None);request['sinks']=loads
        if args.sink_min_voltage is not None or args.sink_max_voltage is not None:
            if loads:raise ValueError('Use --load-voltage-limits with --load, not legacy --sink-min-voltage/--sink-max-voltage.')
            for value,key in [(args.sink_min_voltage,'sink_min_voltage'),(args.sink_max_voltage,'sink_max_voltage')]:
                if value is None:continue
                if not math.isfinite(value) or value<0:raise ValueError('Sink voltage limits must be finite and nonnegative.')
                request[key]=value
            if request.get('sink_max_voltage',math.inf)<request.get('sink_min_voltage',0):raise ValueError('Maximum sink voltage must be at least the minimum.')
        if args.source_current_limit is not None:
            if not math.isfinite(args.source_current_limit) or args.source_current_limit<0:raise ValueError('Source current limit must be finite and nonnegative.')
            request['source_current_limit']=args.source_current_limit
        if args.output and args.output.resolve()==args.board.resolve():
            raise ValueError('The result output must not overwrite the source PCB.')
        if args.html:
            request['html_output']=str(args.html.resolve())
        from .service import run_job
        if args.command or args.series_file:
            from .console import parse_command
            inventory=run_job({'action':'inspect','board_path':str(args.board.resolve())},timeout=args.timeout)
            if args.series_file:
                from .series_editor import parse_saved_path
                from wayricad_runtime.jobs import load_json
                data=load_json(args.series_file)
                if data.get('schema')!=1 or not isinstance(data.get('branches'),list):raise ValueError('Unsupported series-editor JSON.')
                parsed=parse_saved_path(data,inventory)
            else:parsed=parse_command(args.command,inventory)
            if 'console_output' in parsed:print(parsed['console_output']);return 0
            request.update(parsed)
        if args.return_path:
            if not args.net or not args.return_nets:raise ValueError('Return-path review requires --net and --return-nets.')
            request.update(action='return_path',signal_net=args.net,return_nets=args.return_nets,
                sample_pitch_mm=args.return_pitch,return_via_radius_mm=args.return_via_radius)
        if args.load_ohms is not None:
            request['action']='solve';request['load_resistance_ohm']=args.load_ohms
        if args.sweep:
            request['action']='sweep'
            request['sweep']={'start_A':float(args.sweep[0]),'stop_A':float(args.sweep[1]),'points':int(args.sweep[2])}
        if request['action'] in ('solve','sweep') and (not request.get('source_terminal') or not (request.get('sink_terminal') or request.get('sinks'))):
            raise ValueError('Choose source and sink pads for a solved or swept path.')
        if request['action'] in ('solve','sweep') and not request.get('net'):
            raise ValueError('Choose --net or a run pi --command for a solved or swept path.')
        if args.converge_levels:
            if request['action']!='solve' or args.mesh_only:raise ValueError('Convergence requires a solved path, not inventory or mesh-only mode.')
            from .convergence import assess
            assess([],args.convergence_tolerance_percent)
            request.update(action='converge',convergence_levels=args.converge_levels,convergence_tolerance_percent=args.convergence_tolerance_percent)
        if args.html and request['action'] not in ('solve','converge','sweep','return_path'):
            raise ValueError('HTML export needs a solved path. Supply --net, --source and --sink, or a run pi --command.')
        from .package_contacts import guard_request
        guard_request(request)
        if args.max_cells is not None:
            from .service import mesh_cell_budget
            mesh_cell_budget(request)
        result=run_job(request,timeout=args.timeout)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        summary={k:v for k,v in result.items() if k not in ('mesh','geometry')}
        if 'result' in summary:
            summary['result']={k:v for k,v in summary['result'].items() if not isinstance(v,(list,dict)) or k in ('sinks','feasibility','package_contacts','package_port_voltages_V','fusing')}
        print(json.dumps(summary,indent=2,allow_nan=False))
        if result.get('result',{}).get('feasibility',{}).get('feasible') is False:return 4
        return 3 if result.get('convergence',{}).get('status','STABLE_WITHIN_TOLERANCE')!='STABLE_WITHIN_TOLERANCE' else 0
    except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
        print(json.dumps({'error':str(exc)}));return 2


if __name__=='__main__':raise SystemExit(main())
