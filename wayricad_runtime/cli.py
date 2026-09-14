"""Local routing CLI. Run with KiCad 10's bundled Python, which provides pcbnew."""
import argparse
import json
from pathlib import Path
import sys
from .routing import (plan_document, plan_fanout, plan_stitching, fanout_items,
                      FanoutPlanner, StitchingPlanner, netclass_names, copper_layer_names)
from .operations import add_group
from .fanout_profiles import FANOUT_PATTERNS, SIGNAL_PROFILES, ANGLE_MODES, PAIR_MODES, profile_defaults


def write_svg(document, destination, board=None, api=None):
    """Portable local preview of exactly the coordinates in a review plan."""
    from html import escape
    entries=document['candidates']; points=[]
    for item in entries:
        points.extend(item.get('path_mm') or [item['start_mm'],item['end_mm']] if document['kind']=='fanout' else [item['position_mm']])
    if document['kind']=='fanout' and board is not None and api is not None:
        references={item['reference'] for item in entries}
        for footprint in board.GetFootprints():
            if footprint.GetReference() in references:
                box=footprint.GetBoundingBox()
                points.extend(([api.ToMM(box.GetLeft()),api.ToMM(box.GetTop())],
                               [api.ToMM(box.GetRight()),api.ToMM(box.GetBottom())]))
    xs=[p[0] for p in points] or [0,10];ys=[p[1] for p in points] or [0,10]
    x,y=min(xs)-2,min(ys)-2;w,h=max(xs)-x+2,max(ys)-y+2
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" width="1000" height="800">',
           '<title>WayriCAD routing review — millimetres</title>',f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fbfcfd"/>']
    if board is not None and api is not None:
        from .geometry import polygons
        mm=api.ToMM
        def line(a,b,stroke,color):
            return f'<line x1="{mm(a.x)}" y1="{mm(a.y)}" x2="{mm(b.x)}" y2="{mm(b.y)}" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round"/>'
        for track in board.GetTracks():
            if 'VIA' in track.GetClass():
                p=track.GetPosition();diameter=mm(track.GetWidth(track.TopLayer()));drill=mm(track.GetDrillValue())
                parts.append(f'<circle cx="{mm(p.x)}" cy="{mm(p.y)}" r="{diameter/2}" fill="#cbd9d4"/><circle cx="{mm(p.x)}" cy="{mm(p.y)}" r="{drill/2}" fill="#fbfcfd"/>')
            elif track.GetClass()=='PCB_TRACK':parts.append(line(track.GetStart(),track.GetEnd(),mm(track.GetWidth()),'#b47c6f'))
        for fp in board.GetFootprints():
            for graphic in fp.GraphicalItems():
                if hasattr(graphic,'GetShape') and graphic.GetShape()==api.SHAPE_T_SEGMENT:
                    parts.append(line(graphic.GetStart(),graphic.GetEnd(),.08,'#596877'))
            for pad in fp.Pads():
                paths=[]
                for outer,holes in polygons(pad.GetEffectivePolygon(pad.GetLayer())):
                    for ring in [outer,*holes]:
                        if ring:paths.append('M '+' L '.join(f'{mm(px)},{mm(py)}' for px,py in ring)+' Z')
                if paths:parts.append('<path d="'+' '.join(paths)+'" fill="#d7b36c" stroke="#9d793d" stroke-width="0.025" fill-rule="evenodd"/>')
                pos=pad.GetPosition();size=pad.GetSize();label=escape(str(pad.GetNumber()))
                parts.append(f'<text x="{mm(pos.x-size.x/2)-.2}" y="{mm(pos.y)+.1}" font-size="0.3" text-anchor="end" fill="#56411e">{label}</text>')
            pos=fp.GetPosition();parts.append(f'<text x="{mm(pos.x)}" y="{mm(pos.y)}" font-size="0.35" text-anchor="middle" fill="#495763">{escape(fp.GetReference())}</text>')
        for graphic in board.GetDrawings():
            if hasattr(graphic,'GetShape') and graphic.GetLayer()==api.Edge_Cuts and graphic.GetShape()==api.SHAPE_T_SEGMENT:
                parts.append(line(graphic.GetStart(),graphic.GetEnd(),.06,'#687582'))
    else:
        parts.append(f'<text x="{x+.3}" y="{y+.6}" font-size="0.35" fill="#596877">Candidate geometry only - millimetres</text>')
    for item in entries:
        fan=document['kind']=='fanout';end=item['end_mm'] if fan else item['position_mm']
        label=escape(str(item.get('reference',''))+'.'+str(item.get('pad',''))+' '+str(item['net']))
        if fan and 'length_mm' in item:
            label += escape(f' | {item["length_mm"]:.4f} mm' + (' | pair '+str(item['pair_id']) if item.get('pair_id') else ''))
        parts.append('<g><title>'+label+'</title>')
        if fan and item['add_track']:
            path=item.get('path_mm') or [item['start_mm'],end]
            vertices=' '.join(f'{point[0]},{point[1]}' for point in path)
            parts.append(f'<polyline points="{vertices}" fill="none" stroke="#087f98" stroke-width="{item["width_mm"]}" stroke-linecap="round" stroke-linejoin="round"/>')
        positions=([item['start_mm']] if fan and item.get('start_via') else [])+([end] if not fan or item['add_via'] else [])
        for end in positions:
            diameter=item['via_diameter_mm'] if fan else item['diameter_mm']
            drill=item['via_drill_mm'] if fan else item['drill_mm']
            parts.append(f'<circle cx="{end[0]}" cy="{end[1]}" r="{diameter/2}" fill="#62c1c5"/><circle cx="{end[0]}" cy="{end[1]}" r="{drill/2}" fill="#fbfcfd"/>')
        parts.append('</g>')
    parts.append('</svg>')
    Path(destination).write_text(''.join(parts),encoding='utf-8')


def load_api():
    try:
        import pcbnew
    except ImportError as exc:
        raise RuntimeError('Use KiCad 10 bundled Python for native board-file routing. This interpreter has no pcbnew module.') from exc
    return pcbnew


def execute(args):
    kind='stitching' if args.kind=='stitch' else args.kind
    if args.operation=='settings':
        defaults=dict(FanoutPlanner.defaults if kind=='fanout' else StitchingPlanner.defaults)
        choices={'pattern': ['Square grid','Staggered grid']} if kind=='stitching' else {
            'pattern':list(FANOUT_PATTERNS), 'signal_profile':list(SIGNAL_PROFILES),
            'angle_mode':list(ANGLE_MODES),'pair_mode':list(PAIR_MODES),
            'output_mode':['Escape traces','Via-in-pad'],
            'scope':['Selected pads','Selected footprints','Reference wildcard','All SMD pads'],
            'netclass_filter':['All netclasses','Default'],
            'escape_layer':['Pad layer']}
        if args.board:
            api=load_api();board=api.LoadBoard(str(Path(args.board).resolve()))
            if kind=='fanout':
                choices['netclass_filter']=['All netclasses']+netclass_names(board)
                choices['escape_layer']=['Pad layer']+copper_layer_names(board)
            else:choices['net_choice']=[net.GetNetname() for net in board.GetNetsByName().values() if net.GetNetname()]
        result = {'defaults':defaults,'choices':choices,'units':'Dimensions in mm; angles in degrees.',
                  'note':'Pass --board to list actual enabled copper layers and project netclasses. Changing fanout layer adds a source via.'}
        if kind=='fanout':
            result['profiles']={name:profile_defaults(name) for name in SIGNAL_PROFILES}
            result['high_speed_note']='Profiles suggest escape geometry and net-name filters. Pair length/skew describe generated traces only; use board-specific KiCad constraints for impedance, delay and full-channel matching.'
        return result
    api=load_api();source=Path(args.board).resolve()
    if not source.is_file():raise ValueError('Board file does not exist: '+str(source))
    board=api.LoadBoard(str(source))
    kind='stitching' if args.kind=='stitch' else args.kind
    if args.operation=='plan':
        settings=json.loads(Path(args.settings).read_text(encoding='utf-8-sig')) if args.settings else {}
        if not isinstance(settings,dict):raise ValueError('Settings JSON must contain an object.')
        document=plan_document(kind,board,api,settings)
        destination=Path(args.output).resolve()
        if destination==source:raise ValueError('Plan output must not overwrite the source board.')
        if args.svg and Path(args.svg).resolve() in (source,destination):raise ValueError('SVG output must have a separate path.')
        destination.write_text(json.dumps(document,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        if args.svg:write_svg(document,args.svg,board,api)
        return {'plan':str(destination),'accepted':len(document['candidates']),'rejected':document['rejected']}
    document=json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
    if document.get('schema')!=1 or document.get('kind')!=kind:raise ValueError('Plan schema or routing kind does not match.')
    current=plan_document(kind,board,api,document['settings'])
    if any(current[key]!=document.get(key) for key in ('board_fingerprint','candidates','rejected')):
        raise ValueError('Board or reviewed geometry changed. Generate a new plan before applying.')
    destination=Path(args.output).resolve()
    if destination==source or destination.exists():raise ValueError('Apply requires a new output board path; existing files are never overwritten.')
    if destination.suffix.lower()!='.kicad_pcb':raise ValueError('Output board must end in .kicad_pcb.')
    if not current['candidates']:raise ValueError('Plan contains no accepted candidates.')
    plans,_=(plan_fanout if kind=='fanout' else plan_stitching)(board,api,document['settings'])
    items=fanout_items(board,api,plans) if kind=='fanout' else plans
    add_group(board,items,'WayriCAD '+kind.title()+' CLI',api.PCB_GROUP)
    if not api.SaveBoard(str(destination),board):raise RuntimeError('KiCad could not save the output board.')
    return {'board':str(destination),'created_items':len(items),'next_step':'Open the output board in KiCad and run DRC.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description='WayriCAD local routing: review JSON/SVG, then apply to a new board copy.')
    kinds=parser.add_subparsers(dest='kind',required=True)
    for kind in ('fanout','stitching','stitch'):
        operations=kinds.add_parser(kind).add_subparsers(dest='operation',required=True)
        settings=operations.add_parser('settings',help='List JSON setting names/defaults; --board adds actual netclasses and enabled layers.')
        settings.add_argument('--board')
        plan=operations.add_parser('plan',help='Generate a read-only review plan.')
        plan.add_argument('--board',required=True);plan.add_argument('--settings',help='JSON settings file; omit for defaults.')
        plan.add_argument('--output',required=True);plan.add_argument('--svg',help='Optional local SVG preview.')
        apply=operations.add_parser('apply',help='Apply a verified plan to a new board file.')
        apply.add_argument('--board',required=True);apply.add_argument('--plan',required=True);apply.add_argument('--output',required=True)
    try:
        result=execute(parser.parse_args(argv))
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
        print('WayriCAD: '+str(exc),file=sys.stderr);return 2
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
