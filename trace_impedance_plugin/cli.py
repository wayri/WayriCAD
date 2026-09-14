"""Read-only trace, via and copper-zone estimates using native KiCad Python."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def parser():
    root=argparse.ArgumentParser(description=__doc__)
    commands=root.add_subparsers(dest='command',required=True)
    for name in ('inspect','path','zone'):
        command=commands.add_parser(name)
        command.add_argument('board',type=Path)
        command.add_argument('--output',type=Path,help='Write JSON atomically; source design files are never replaced.')
        if name=='inspect':
            command.add_argument('--net',help='Include endpoints and zone IDs for this exact net.')
        else:
            command.add_argument('--net',required=True)
            command.add_argument('--start',required=True,help='Start pad, e.g. U1.1.')
            command.add_argument('--end',required=True,help='End pad, e.g. J1.1.')
            command.add_argument('--reference',default='Auto',help='Auto ground reference, or an explicit copper layer.')
            command.add_argument('--frequency-mhz',type=float,default=100.)
        if name=='zone':
            command.add_argument('--zone-id',required=True,help='Filled-island ID from inspect --net.')
            command.add_argument('--corridor-width-mm',type=float,default=.2,
                                 help='Assumed current corridor width for terminal-dependent sheet R/L.')
    return root


def analyze(args):
    source=args.board.resolve()
    if not source.is_file() or source.suffix.lower()!='.kicad_pcb':
        raise ValueError('Choose an existing .kicad_pcb file.')
    try:
        import pcbnew
    except ImportError as exc:
        raise RuntimeError("Run this command with KiCad 10's Python interpreter, which provides pcbnew.") from exc
    from .measurement import TraceMeasurementEngine
    board=pcbnew.LoadBoard(str(source))
    if board is None:raise ValueError('KiCad could not load the board.')
    engine=TraceMeasurementEngine(board)
    if args.command=='inspect':
        report={'nets':engine.net_names(),'ground_nets':engine.ground_nets(),
                'layers':engine.available_layers(), 'zones':engine.zone_options(args.net)}
        if args.net:report['pads']=engine.pads_for_net(args.net)
    elif args.command=='path':
        report=engine.measure(args.net,args.start,args.end,args.frequency_mhz,args.reference).as_report()
    else:
        report=engine.measure_zone(args.net,args.start,args.end,args.zone_id,
            reference_layer=args.reference,frequency_mhz=args.frequency_mhz,
            corridor_width_mm=args.corridor_width_mm).as_report()
    return {'schema':'wayricad.rlc/v1','board':str(source),
            'board_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'operation':args.command,'result':report}


def write_report(destination,document,source):
    destination=destination.resolve()
    if destination.suffix.lower()!='.json' or destination==source.resolve():
        raise ValueError('Output must be a separate .json report file.')
    payload=json.dumps(document,indent=2,allow_nan=False)+'\n'
    destination.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.wayricad-rlc-',suffix='.json',dir=destination.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:stream.write(payload)
        os.replace(temporary,destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        report=analyze(args)
        if args.output:write_report(args.output,report,args.board)
        else:print(json.dumps(report,indent=2,allow_nan=False))
        status=report['result'].get('status','ok')
        return 2 if status=='disconnected' else 3 if status=='partial' else 0
    except (RuntimeError,ValueError,OSError) as exc:
        print('WayriCAD RLC: '+str(exc),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
