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
            if args.board or args.html or args.net or args.source or args.sink or args.command or args.converge_levels or args.mesh_only:raise ValueError('--verify uses no board, path, convergence or HTML options. Use --output for JSON.')
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
    if request['action']=='solve' and not args.command and (not args.source or not args.sink):parser.error('Choose --source and --sink pad labels or UUIDs.')
    try:
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
        if args.converge_levels:
            if request['action']!='solve' or args.mesh_only:raise ValueError('Convergence requires a solved path, not inventory or mesh-only mode.')
            from .convergence import assess
            assess([],args.convergence_tolerance_percent)
            request.update(action='converge',convergence_levels=args.converge_levels,convergence_tolerance_percent=args.convergence_tolerance_percent)
        if args.html and request['action'] not in ('solve','converge'):
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
