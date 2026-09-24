"""Quick SI saved-board inspection, screening and offline report export."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def protocol_budgets(command):
    for flag in ('max-delay-ns','max-skew-ps','max-impedance-error-percent','max-delay-to-rise-ratio'):
        command.add_argument('--'+flag,type=float,help='Explicit user budget; not a protocol compliance limit.')


def parser():
    root=argparse.ArgumentParser(description=__doc__)
    subs=root.add_subparsers(dest='command',required=True)
    desktop=subs.add_parser('desktop',help='Run the complete optional upstream SignalIntegrity desktop; waits until it closes.')
    desktop.add_argument('project',type=Path,nargs='?',help='Optional trusted upstream .si project.')
    desktop.add_argument('--python',type=Path,help='Python executable with SignalIntegrity and Tk; defaults to this interpreter.')
    desktop.add_argument('--check',action='store_true',help='Check desktop imports/version without opening a window.')
    network=subs.add_parser('network',help='Read Touchstone 1.0 with optional Nubis SignalIntegrity; no KiCad required.')
    network.add_argument('source',type=Path)
    network.add_argument('--to-port',type=int,default=2,help='One-based receiving port; default 2.')
    network.add_argument('--from-port',type=int,default=1,help='One-based driven port; default 1.')
    network.add_argument('--output',type=Path)
    line=subs.add_parser('line-network',help='Export a screened route as an explicitly ideal lossless Touchstone two-port.')
    line.add_argument('source',type=Path,help='Complete Quick SI JSON route report.')
    line.add_argument('--stop-hz',type=float,required=True,help='Explicit final frequency in Hz; grid starts at DC.')
    line.add_argument('--points',type=int,default=1001)
    line.add_argument('--reference-ohm',type=float,default=50.)
    line.add_argument('--output',type=Path,required=True,help='Separate .s2p file.')
    subs.add_parser('profiles',help='List protocol screening profiles; no KiCad runtime required.')
    suite=subs.add_parser('suite',help='Screen saved Quick SI JSON reports; no KiCad runtime required.')
    suite.add_argument('--profile',required=True,help='Profile ID from profiles.')
    suite.add_argument('--reports',nargs='+',type=Path,required=True,help='Quick SI report files; set suite_role and suite_group for pairs/buses.')
    suite.add_argument('--output',type=Path)
    suite.add_argument('--html',type=Path)
    protocol_budgets(suite)
    for name in ('inspect','screen'):
        sub=subs.add_parser(name)
        sub.add_argument('board',type=Path,help='Saved KiCad PCB; never modified.')
        sub.add_argument('--net',required=name=='screen')
        sub.add_argument('--output',type=Path,help='Separate JSON report; replaces an existing report atomically.')
        if name=='screen':
            sub.add_argument('--start',required=True,help='Source pad, e.g. U1.1.')
            sub.add_argument('--end',required=True,help='Receiver pad, e.g. J1.1.')
            sub.add_argument('--reference',default='Auto',help='Reference copper layer, or Auto ground search.')
            sub.add_argument('--rise-ns',type=float,default=1.,help='Driver edge rise time; default 1 ns is an editable assumption.')
            sub.add_argument('--frequency-mhz',type=float,default=100.,help='Frequency for electrical length; not a data-rate assumption.')
            sub.add_argument('--source-ohm',type=float,default=20.,help='Resistive driver output impedance; default 20 ohm is an assumption.')
            sub.add_argument('--load-ohm',type=float,help='Resistive receiver/termination load; omitted means open circuit.')
            sub.add_argument('--z0-ohm',type=float,help='Explicit assumed uniform Z0 when geometry cannot establish one.')
            sub.add_argument('--epsilon-eff',type=float,help='Explicit effective permittivity for total-route delay screening.')
            sub.add_argument('--html',type=Path,help='Self-contained local HTML with route geometry and evidence.')
            sub.add_argument('--eye-bitrate-mbps',type=float,help='Opt in to an illustrative uniform-line PRBS7 eye at this bit rate.')
            sub.add_argument('--eye-swing-v',type=float,default=1.,help='Eye source open-circuit swing, default 1 V; an explicit modeling assumption.')
            sub.add_argument('--role',choices=['P','N','clock','data','control'],help='Optional protocol suite assignment for this route report.')
            sub.add_argument('--group',default='',help='Pair/bus group for --role, e.g. lane0 or byte0.')
    eye=subs.add_parser('eye',help='Standalone illustrative eye/step model; no KiCad runtime required.')
    for flag,label in [('z0-ohm','Uniform line impedance'),('delay-ns','One-way line delay'),('source-ohm','Source resistance'),('rise-ns','10–90 percent driver rise time'),('bitrate-mbps','NRZ bit rate')]:
        eye.add_argument('--'+flag,type=float,required=True,help=label)
    eye.add_argument('--load-ohm',type=float,help='Resistive load; omitted means open.')
    eye.add_argument('--swing-v',type=float,default=1.,help='Source open-circuit swing; default 1 V.')
    eye.add_argument('--output',type=Path)
    eye.add_argument('--html',type=Path)
    return root


def write_report(destination,payload,source,extension):
    destination=Path(destination).resolve();source=Path(source).resolve()
    if destination==source or destination.suffix.lower()!=extension:
        raise ValueError('Choose a separate '+extension+' report file, not a design file.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.wayricad-si-',dir=destination.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:stream.write(payload)
        os.replace(temporary,destination)
    finally:Path(temporary).unlink(missing_ok=True)


def execute(args):
    if args.command=='desktop':
        from .signalintegrity_backend import run_desktop
        return run_desktop(python=args.python,project=args.project,check=args.check)
    if args.command=='network':
        from .signalintegrity_backend import analyze_touchstone
        report=analyze_touchstone(args.source,to_port=args.to_port,from_port=args.from_port)
        if args.output:write_report(args.output,json.dumps(report,indent=2,allow_nan=False)+'\n',args.source,'.json')
        return report
    if args.command=='line-network':
        from .signalintegrity_backend import ideal_line_touchstone
        if args.source.stat().st_size>16*1024*1024:raise ValueError('Input route report must be smaller than 16 MiB.')
        def reject_constant(value):raise ValueError('Non-finite JSON number: '+value)
        original=args.source.read_bytes()
        report=json.loads(original.decode('utf-8-sig'),parse_constant=reject_constant)
        if not isinstance(report,dict):raise ValueError('Input must be a Quick SI report object.')
        payload=ideal_line_touchstone(report,stop_hz=args.stop_hz,points=args.points,reference_ohm=args.reference_ohm)
        write_report(args.output,payload,args.source,'.s2p')
        return {'schema':'wayricad.ideal-line-export/v1','status':'ILLUSTRATIVE','output':str(args.output.resolve()),
                'source_sha256':hashlib.sha256(original).hexdigest(),
                'model':'Lossless uniform line only; not extracted board S-parameters.'}
    if args.command=='profiles':
        from .protocol_profiles import list_profiles
        return {'schema':'wayricad.protocol-profiles/v1','profiles':list_profiles()}
    if args.command=='suite':
        from .protocol_suite import screen_suite
        from .protocol_view import html_report
        if len(args.reports)>64:raise ValueError('Use at most 64 report files per suite.')
        sources={p.resolve() for p in args.reports}
        for target in (args.output,args.html):
            if target and target.resolve() in sources:raise ValueError('A suite output must not overwrite an input report.')
        paths=[]
        def reject_constant(value):raise ValueError('Non-finite JSON number: '+value)
        for source in args.reports:
            if source.stat().st_size>16*1024*1024:raise ValueError('Each input report must be smaller than 16 MiB.')
            report=json.loads(source.read_text(encoding='utf-8-sig'),parse_constant=reject_constant)
            if not isinstance(report,dict):raise ValueError('Each input must be one Quick SI JSON report object.')
            paths.append(report)
        budgets={key:getattr(args,key) for key in ('max_delay_ns','max_skew_ps','max_impedance_error_percent','max_delay_to_rise_ratio') if getattr(args,key) is not None}
        report=screen_suite(args.profile,paths,budgets=budgets)
        report['paths']=paths
        if args.output:write_report(args.output,json.dumps(report,indent=2,allow_nan=False)+'\n',__file__,'.json')
        if args.html:write_report(args.html,html_report(report),__file__,'.html')
        return report
    if args.command=='eye':
        from .eye_model import simulate_eye
        from .eye_view import standalone_html
        report=simulate_eye(**{name:getattr(args,name) for name in ('z0_ohm','delay_ns','source_ohm','load_ohm','rise_ns','bitrate_mbps','swing_v')})
        if args.output:write_report(args.output,json.dumps(report,indent=2,allow_nan=False)+'\n',__file__,'.json')
        if args.html:write_report(args.html,standalone_html(report),__file__,'.html')
        return report
    try:import pcbnew
    except ImportError as exc:raise RuntimeError("Use KiCad's Python interpreter for saved-board SI analysis; --help works with ordinary Python.") from exc
    source=args.board.resolve()
    if not source.is_file() or source.suffix.lower()!='.kicad_pcb':raise ValueError('Choose an existing .kicad_pcb file.')
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    board=pcbnew.LoadBoard(str(source))
    if board is None:raise ValueError('KiCad could not load the board.')
    from .measurement import TraceMeasurementEngine
    from .quick_si import analyze,html_report
    if args.command=='inspect':
        engine=TraceMeasurementEngine(board)
        report={'schema':'wayricad.quick-si-inventory/v1','nets':engine.net_names(),'layers':engine.available_layers(),'ground_nets':engine.ground_nets()}
        if args.net:report['pads']=engine.pads_for_net(args.net)
    else:
        report,_=analyze(board,args.net,args.start,args.end,args.reference,**{name:getattr(args,name) for name in ('rise_ns','frequency_mhz','source_ohm','load_ohm','z0_ohm','epsilon_eff','eye_bitrate_mbps','eye_swing_v')})
    if hashlib.sha256(source.read_bytes()).hexdigest()!=original:raise ValueError('Board file changed during analysis; rerun before exporting.')
    report.update(board=str(source),board_sha256=original)
    if args.command=='screen':
        if args.role and not args.group.strip():raise ValueError('Supply --group with a protocol --role.')
        if args.group.strip() and not args.role:raise ValueError('Supply --role with a protocol --group.')
        if args.role:report.update(suite_role=args.role,suite_group=args.group.strip())
    if args.output:write_report(args.output,json.dumps(report,indent=2,allow_nan=False)+'\n',source,'.json')
    if getattr(args,'html',None):write_report(args.html,html_report(report),source,'.html')
    return report


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command in ('inspect','screen'):
            try:import pcbnew
            except ImportError:
                from wayricad_runtime.native_analysis import run_cli
                return run_cli(Path(__file__).resolve().parent,list(sys.argv[1:] if argv is None else argv))
        report=execute(args)
        print(json.dumps(report,indent=2,allow_nan=False))
        return 2 if report.get('status') in ('UNRESOLVED','BLOCKED') else 3 if report.get('status') in ('INCOMPLETE','REVIEW') or report.get('eye',{}).get('status')=='UNAVAILABLE' else 0
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
