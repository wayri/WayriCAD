"""Quick PI CLI. Analyze saved files; never mutate PCB copper."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board',type=Path)
    parser.add_argument('--net');parser.add_argument('--source');parser.add_argument('--sink')
    parser.add_argument('--voltage',type=float,default=1.);parser.add_argument('--current',type=float,default=1.)
    parser.add_argument('--mesh-edge',type=float,default=.5);parser.add_argument('--plating',type=float,default=.025)
    parser.add_argument('--pulse',type=float);parser.add_argument('--temperature',type=float,default=20.)
    parser.add_argument('--ambient',type=float,default=20.);parser.add_argument('--temperature-limit',type=float,default=105.)
    parser.add_argument('--mesh-only',action='store_true');parser.add_argument('--output',type=Path)
    parser.add_argument('--html',type=Path);parser.add_argument('--timeout',type=float,default=300.)
    parser.add_argument('--command',help='Console command, including a series-component path; quote the entire command.')
    args=parser.parse_args(argv)
    request={'action':'inspect' if not args.net else ('mesh' if args.mesh_only else 'solve'),
        'board_path':str(args.board.resolve()),'net':args.net,'source_terminal':args.source,'sink_terminal':args.sink,
        'source_voltage':args.voltage,'sink_current':args.current,'edge_mm':args.mesh_edge,'plating_mm':args.plating,
        'options':{'temperature_c':args.temperature,'ambient_c':args.ambient,'temperature_limit_c':args.temperature_limit}}
    if args.pulse is not None:request['options']['pulse_duration_s']=args.pulse
    if request['action']=='solve' and not args.command and (not args.source or not args.sink):parser.error('Choose --source and --sink pad labels or UUIDs.')
    try:
        if args.output and args.output.resolve()==args.board.resolve():
            raise ValueError('The result output must not overwrite the source PCB.')
        from .service import run_job
        if args.command:
            from .console import parse_command
            inventory=run_job({'action':'inspect','board_path':str(args.board.resolve())},timeout=args.timeout)
            parsed=parse_command(args.command,inventory)
            if 'console_output' in parsed:print(parsed['console_output']);return 0
            request.update(parsed)
        result=run_job(request,timeout=args.timeout)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        if args.html:
            from .report import write_report
            write_report(args.html,result)
        summary={k:v for k,v in result.items() if k not in ('mesh','geometry')}
        if 'result' in summary:
            summary['result']={k:v for k,v in summary['result'].items() if not isinstance(v,(list,dict))}
        print(json.dumps(summary,indent=2,allow_nan=False));return 0
    except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
        print(json.dumps({'error':str(exc)}));return 2


if __name__=='__main__':raise SystemExit(main())
