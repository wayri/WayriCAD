"""Quick PI CLI. Analyze saved files; never mutate PCB copper."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board',type=Path,nargs='?')
    parser.add_argument('--verify',action='store_true',help='Run analytical/reference benchmarks in the prepared PI runtime; no board required.')
    parser.add_argument('--net');parser.add_argument('--source');parser.add_argument('--sink')
    parser.add_argument('--voltage',type=float,default=1.);parser.add_argument('--current',type=float,default=1.)
    parser.add_argument('--load-ohms',type=float,help='Solve DC current from source voltage and a resistive load to 0 V.')
    parser.add_argument('--sweep',nargs=3,metavar=('START_A','STOP_A','POINTS'),help='Sweep prescribed DC currents (2–200 points).')
    parser.add_argument('--quick-therm',choices=('air','vacuum'),help='Run a mapped-field steady-state board thermal screen.')
    parser.add_argument('--power-field');parser.add_argument('--theta-ja-field');parser.add_argument('--theta-jb-field')
    parser.add_argument('--theta-jc-field',help='Mapped junction-to-case K/W field for components with virtual heatsinks.')
    parser.add_argument('--heatsinks',type=Path,help='JSON mapping of component references to virtual heatsink dimensions and thermal resistances.')
    parser.add_argument('--thermal-refs',nargs='+',help='Component references included in QuickTherm.')
    parser.add_argument('--board-rtheta',type=float,help='Vacuum board-to-environment K/W; requires a real conductive/radiative sink estimate.')
    parser.add_argument('--return-path',action='store_true',help='Screen saved signal tracks against explicitly selected return nets.')
    parser.add_argument('--return-nets',nargs='+');parser.add_argument('--return-pitch',type=float,default=.25)
    parser.add_argument('--return-via-radius',type=float,default=2.)
    parser.add_argument('--mesh-edge',type=float,default=.5);parser.add_argument('--plating',type=float,default=.025)
    parser.add_argument('--pulse',type=float);parser.add_argument('--temperature',type=float,default=20.)
    parser.add_argument('--ambient',type=float,default=20.);parser.add_argument('--temperature-limit',type=float,default=105.)
    parser.add_argument('--mesh-only',action='store_true');parser.add_argument('--output',type=Path)
    parser.add_argument('--html',type=Path);parser.add_argument('--timeout',type=float,default=300.)
    parser.add_argument('--converge-levels',type=int,choices=(3,4,5),help='Run a fixed-input study, halving mesh edge each level; returns 3 if incomplete or not stable.')
    parser.add_argument('--convergence-tolerance-percent',type=float,default=1.,help='Maximum change in each of the final two refinements; default 1%%. Does not certify local peaks.')
    parser.add_argument('--command',help='Console command, including a series-component path; quote the entire command.')
    args=parser.parse_args(argv)
    if args.verify:
        try:
            if args.board or args.html or args.net or args.source or args.sink or args.command or args.converge_levels or args.mesh_only or args.load_ohms or args.sweep or args.quick_therm or args.return_path or args.heatsinks or args.theta_jc_field:raise ValueError('--verify uses no board, path, convergence or HTML options. Use --output for JSON.')
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
        'source_voltage':args.voltage,'sink_current':args.current,'edge_mm':args.mesh_edge,'plating_mm':args.plating,
        'options':{'temperature_c':args.temperature,'ambient_c':args.ambient,'temperature_limit_c':args.temperature_limit}}
    if args.pulse is not None:request['options']['pulse_duration_s']=args.pulse
    try:
        if sum(bool(value) for value in (args.quick_therm,args.return_path,args.load_ohms is not None,args.sweep))>1:
            raise ValueError('Choose one of QuickTherm, return-path, load-resistance or current-sweep mode.')
        if (args.heatsinks or args.theta_jc_field) and not args.quick_therm:
            raise ValueError('--heatsinks and --theta-jc-field require --quick-therm.')
        if args.load_ohms is not None and args.sweep:raise ValueError('Choose either --load-ohms or --sweep.')
        if args.output and args.output.resolve()==args.board.resolve():
            raise ValueError('The result output must not overwrite the source PCB.')
        if args.html:
            request['html_output']=str(args.html.resolve())
        from .service import run_job
        if args.command:
            from .console import parse_command
            inventory=run_job({'action':'inspect','board_path':str(args.board.resolve())},timeout=args.timeout)
            parsed=parse_command(args.command,inventory)
            if 'console_output' in parsed:print(parsed['console_output']);return 0
            request.update(parsed)
        if args.quick_therm:
            if not args.power_field:
                raise ValueError('Map --power-field for QuickTherm.')
            heatsinks={}
            if args.heatsinks:
                if args.heatsinks.stat().st_size>262144:raise ValueError('Virtual heatsink JSON exceeds 256 KiB.')
                heatsinks=json.loads(args.heatsinks.read_text(encoding='utf-8'))
                if not isinstance(heatsinks,dict):raise ValueError('Virtual heatsinks must be a JSON object keyed by reference.')
            if heatsinks and not args.theta_jc_field:
                raise ValueError('Map --theta-jc-field for virtual heatsinks.')
            needed=args.theta_ja_field if args.quick_therm=='air' else args.theta_jb_field
            if not needed and not (heatsinks and args.thermal_refs and set(args.thermal_refs)<=set(heatsinks)):
                raise ValueError('Map the ambient/board thermal-resistance field for components without heatsinks.')
            field_map={'power_w':args.power_field}
            if needed:field_map['theta_ja_air_k_per_w' if args.quick_therm=='air' else 'theta_jb_k_per_w']=needed
            if args.theta_jc_field:field_map['theta_jc_k_per_w']=args.theta_jc_field
            request.update(action='quick_therm',environment=args.quick_therm,ambient_c=args.ambient,
                field_map=field_map,heatsinks=heatsinks,references=args.thermal_refs,
                vacuum_board_to_environment_k_per_w=args.board_rtheta)
        if args.return_path:
            if not args.net or not args.return_nets:raise ValueError('Return-path review requires --net and --return-nets.')
            request.update(action='return_path',signal_net=args.net,return_nets=args.return_nets,
                sample_pitch_mm=args.return_pitch,return_via_radius_mm=args.return_via_radius)
        if args.load_ohms is not None:
            request['action']='solve';request['load_resistance_ohm']=args.load_ohms
        if args.sweep:
            request['action']='sweep'
            request['sweep']={'start_A':float(args.sweep[0]),'stop_A':float(args.sweep[1]),'points':int(args.sweep[2])}
        if request['action'] in ('solve','sweep') and (not request.get('source_terminal') or not request.get('sink_terminal')):
            raise ValueError('Choose source and sink pads for a solved or swept path.')
        if request['action'] in ('solve','sweep') and not request.get('net'):
            raise ValueError('Choose --net or a run pi --command for a solved or swept path.')
        if args.converge_levels:
            if request['action']!='solve' or args.mesh_only:raise ValueError('Convergence requires a solved path, not inventory or mesh-only mode.')
            from .convergence import assess
            assess([],args.convergence_tolerance_percent)
            request.update(action='converge',convergence_levels=args.converge_levels,convergence_tolerance_percent=args.convergence_tolerance_percent)
        if args.html and request['action'] not in ('solve','converge','sweep','quick_therm','return_path'):
            raise ValueError('HTML export needs a solved path. Supply --net, --source and --sink, or a run pi --command.')
        result=run_job(request,timeout=args.timeout)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        summary={k:v for k,v in result.items() if k not in ('mesh','geometry')}
        if 'result' in summary:
            summary['result']={k:v for k,v in summary['result'].items() if not isinstance(v,(list,dict))}
        print(json.dumps(summary,indent=2,allow_nan=False))
        return 3 if result.get('convergence',{}).get('status','STABLE_WITHIN_TOLERANCE')!='STABLE_WITHIN_TOLERANCE' else 0
    except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
        print(json.dumps({'error':str(exc)}));return 2


if __name__=='__main__':raise SystemExit(main())
