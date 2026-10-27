"""Generate reviewed layer counters on a candidate PCB; never overwrite source."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board',type=Path)
    parser.add_argument('--output',type=Path,help='New candidate board; omit for read-only JSON preview')
    from .core import STYLES,MIRROR_MODES
    parser.add_argument('--style',choices=list(STYLES),default='row')
    parser.add_argument('--layers',help='Physical numbers, e.g. L1,L2,L4; default all enabled copper layers')
    parser.add_argument('--core-pairs',help='Explicit adjacent physical pairs, e.g. L1/L2,L3/L4')
    for key,value in [('x',10.),('y',10.),('size',1.),('stroke',.2),('pitch',4.),('margin',.5)]:
        parser.add_argument('--'+key,type=float,default=value,help='Millimetres')
    parser.add_argument('--mirror-mode',choices=list(MIRROR_MODES),help='Default lower-half mirrors every physical layer below the full stack midline; subset selection does not move the midline.')
    parser.add_argument('--no-mirror-bottom','--no-mirror',dest='no_mirror_bottom',action='store_true',help='Legacy alias for --mirror-mode none')
    args=parser.parse_args(argv)
    if args.no_mirror_bottom and args.mirror_mode not in (None,'none'):
        parser.error('--no-mirror-bottom/--no-mirror conflicts with the selected --mirror-mode.')
    try:
        import pcbnew as api
        from .core import defaults,copper_layers,plan,apply
        source=args.board.resolve()
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        source_hash=digest(source)
        board=api.LoadBoard(str(source))
        if board is None:raise ValueError('KiCad could not load the source PCB.')
        settings=defaults(board,api)
        settings.update({key:getattr(args,key) for key in ('style','x','y','size','stroke','pitch','margin')})
        mode='none' if args.no_mirror_bottom else args.mirror_mode or 'lower-half'
        settings.update(mirror_mode=mode,mirror_bottom=mode!='none')
        if args.core_pairs is not None:settings['core_pairs']=args.core_pairs
        if args.layers is not None:
            numbers=[int(value.strip().upper().removeprefix('L')) for value in args.layers.split(',')]
            mapping={number:layer for layer,_,number in copper_layers(board,api)}
            if len(set(numbers))!=len(numbers) or set(numbers)-set(mapping):raise ValueError('Choose distinct physical layer numbers from the source stack.')
            settings['layers']=[mapping[n] for n in numbers]
        preview=plan(board,api,settings)
        report=dict(style=preview.settings['style'],mirror_mode=preview.settings['mirror_mode'],labels=preview.labels,bounds=preview.bounds,
                    zone_keepout_layers=preview.settings['layers'],source_sha256=source_hash,
                    applied=False)
        if args.output:
            destination=args.output.resolve()
            if destination.suffix.lower()!='.kicad_pcb':raise ValueError('Output must have a .kicad_pcb extension.')
            if destination==source:raise ValueError('Output must be a new candidate; the source cannot be overwritten.')
            targets=[(None,destination)]
            for suffix in ('.kicad_pro','.kicad_dru'):
                companion=source.with_suffix(suffix)
                if companion.exists():targets.append((companion,destination.with_suffix(suffix)))
            if any(target.exists() for _,target in targets):raise ValueError('An output board or companion already exists; choose a new candidate name.')
            captured={path:path.read_bytes() for path,_ in targets if path is not None}
            apply(board,api,preview)
            destination.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.layer-counter-',dir=destination.parent) as raw:
                stage=Path(raw)/'candidate.kicad_pcb'
                if api.SaveBoard(str(stage),board) is False:raise OSError('KiCad could not save the candidate.')
                if digest(source)!=source_hash or any(path.read_bytes()!=data for path,data in captured.items()):
                    raise ValueError('Source changed during generation; no candidate published.')
                created=[]
                try:
                    # Exclusive creation protects against destination races. Commit
                    # board last; roll back only files created by this invocation.
                    for path,target in targets[1:]+targets[:1]:
                        with target.open('xb') as stream:
                            created.append(target)
                            stream.write(stage.read_bytes() if path is None else captured[path])
                except Exception:
                    for target in reversed(created):target.unlink()
                    raise
            report['applied']=True
        print(json.dumps(report,indent=2))
        return 0
    except (ImportError,ValueError,OSError,RuntimeError) as exc:
        parser.exit(2,str(exc)+'\n')


if __name__=='__main__':raise SystemExit(main())
