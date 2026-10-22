"""Read-only saved-board silkscreen placement previews. Apply stays in PCB Editor."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def run_native(options):
    import pcbnew as api
    from .placement import plan, fingerprint, item_id
    source=Path(options['board']).resolve(strict=True)
    if source.suffix.lower()!='.kicad_pcb':raise ValueError('Choose a saved .kicad_pcb file.')
    inputs=[source,*[source.with_suffix(ext) for ext in ('.kicad_pro','.kicad_dru')]]
    def context_hashes():
        return {path:hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None for path in inputs}
    hashes=context_hashes()
    settings=options.get('settings',{})
    if not isinstance(settings,dict):raise ValueError('Settings must be a JSON object.')
    board=api.LoadBoard(str(source))
    if board is None:raise ValueError('KiCad could not load the saved PCB.')
    if options.get('operation')=='audit-generated':
        from . import lifecycle
        report=lifecycle.audit(board,api)
        checked=lifecycle.audit(board,api)
        if checked.source_fingerprint!=report.source_fingerprint or context_hashes()!=hashes:
            raise ValueError('Saved board or generated-object state changed during audit; reload and retry.')
        return {'schema':'wayricad.silkscreen-generated-audit/v1','status':'AUDIT','writes_board':False,'can_apply':False,
                'source_sha256':hashes[source],'context_hashes':{path.name:digest for path,digest in hashes.items()},
                **report.as_dict()}
    refs=options.get('refs',[])
    if refs:
        available={fp.GetReference() for fp in board.GetFootprints()}
        missing=set(refs)-available
        if missing:raise ValueError('Unknown footprint references: '+', '.join(sorted(missing)))
        for fp in board.GetFootprints():
            if fp.GetReference() in refs:fp.SetSelected()
            else:fp.ClearSelected()
        settings={**settings,'selected_only':True}
    before=fingerprint(board,api);preview=plan(board,api,settings)
    if before!=fingerprint(board,api):raise RuntimeError('Preview changed in-memory source geometry; result discarded.')
    if context_hashes()!=hashes:
        raise ValueError('Saved board or rules changed during planning; reload and retry.')
    def state(value):
        return {'position_mm':[api.ToMM(value[0]),api.ToMM(value[1])],'rotation_deg':value[2],
                'size_mm':[api.ToMM(value[3]),api.ToMM(value[4])],'stroke_mm':api.ToMM(value[5]),
                'mirrored':value[6]}
    payload={'schema':'wayricad.silkscreen-preview/v1','status':'PREVIEW','source_sha256':hashes[source],
            'context_hashes':{path.name:digest for path,digest in hashes.items()},
            'model':'Read-only saved-board envelope placement; active editor rules and native DRC require separate review.',
            'settings':preview.settings,'stats':preview.stats,'rejected':preview.rejected,'skipped':preview.skipped,
            'outcomes':getattr(preview,'outcomes',[]),
            'changes':[{'id':item_id(change.item),'label':change.label,'before':state(change.before),'after':state(change.after),
                        'guide_mm':[[api.ToMM(point[0]),api.ToMM(point[1])] for point in change.leader_path],
                        'sightline_mm':[[api.ToMM(point[0]),api.ToMM(point[1])] for point in change.sightline]}
                       for change in preview.changes]}
    if options.get('include_report_geometry'):
        from .report import capture_geometry
        payload['review_geometry']=capture_geometry(board,preview,api)
        if before!=fingerprint(board,api) or context_hashes()!=hashes:
            raise ValueError('Saved board or rules changed while capturing report geometry; reload and retry.')
    return payload


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='operation',required=True)
    subs.add_parser('settings',help='Print setting names and defaults; no KiCad runtime required.')
    audit=subs.add_parser('audit-generated',help='Read-only audit of generated silkscreen objects on a saved board.')
    audit.add_argument('board',type=Path)
    preview=subs.add_parser('preview',help='Plan labels without saving or editing the PCB.')
    preview.add_argument('board',type=Path);preview.add_argument('--settings',type=Path)
    preview.add_argument('--refs',nargs='+',help='Exact footprint references; omit for the whole board.')
    preview.add_argument('--references-only',action='store_true',help='Arrange reference fields only; preserve manual text and values even when enabled in settings.')
    preview.add_argument('--problems-only',action='store_true',help='Restrict planning to references the planner identifies as problematic.')
    preview.add_argument('--output',type=Path,help='NEW JSON preview file.')
    preview.add_argument('--report',type=Path,help='Write a separate NEW self-contained HTML review report.')
    preview.add_argument('--timeout',type=float,default=1800,help='Native planner timeout in seconds.')
    args=parser.parse_args(argv)
    try:
        if args.operation=='settings':
            from .placement import DEFAULTS
            print(json.dumps({'settings':DEFAULTS,'units':'mm and degrees','writes_board':False},indent=2));return 0
        from wayricad_runtime.jobs import load_json
        settings=load_json(args.settings) if args.operation=='preview' and args.settings else {}
        if not isinstance(settings,dict):raise ValueError('Settings must be an object.')
        if args.operation=='preview' and args.references_only:settings.update(references=True,values=False,board_text=False)
        if args.operation=='preview' and args.problems_only:settings['problem_only']=True
        if args.operation=='preview' and args.output and (args.output.exists() or args.output.suffix.lower()!='.json' or args.output.resolve()==args.board.resolve()):
            raise ValueError('Choose a separate NEW .json preview file.')
        if args.operation=='preview' and args.report:
            if args.report.exists() or args.report.suffix.lower() not in ('.html','.htm') or args.report.resolve()==args.board.resolve():
                raise ValueError('Choose a separate NEW .html/.htm report file.')
            if args.output and args.report.resolve()==args.output.resolve():
                raise ValueError('Choose separate paths for the JSON preview and HTML report.')
        import math
        timeout=args.timeout if args.operation=='preview' else 1800
        if not math.isfinite(timeout) or timeout<=0:raise ValueError('Timeout must be finite and positive.')
        from wayricad_runtime.runtime_setup import native_python
        native=native_python()
        if not native:raise ValueError('KiCad 10 Python is required. Set WAYRICAD_KICAD_PYTHON or use a prepared native interpreter.')
        with tempfile.TemporaryDirectory(prefix='wayricad-silk-preview-') as raw:
            request,result=Path(raw)/'request.json',Path(raw)/'result.json'
            request.write_text(json.dumps({'board':str(args.board.resolve()),'operation':args.operation,'settings':settings,
                'refs':getattr(args,'refs',None) or [],'include_report_geometry':bool(getattr(args,'report',None))}),encoding='utf-8')
            process=subprocess.run([str(native),str(Path(__file__).with_name('cli_worker.py')),str(request),str(result)],capture_output=True,text=True,timeout=timeout)
            if not result.is_file():raise RuntimeError('Native planner did not return a result. '+process.stderr[-300:])
            payload=json.loads(result.read_text(encoding='utf-8'))
            if process.returncode or payload.get('status')=='ERROR':raise ValueError(payload.get('error','Native planning failed.'))
        rendered=json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
        output=getattr(args,'output',None)
        report_output=getattr(args,'report',None)
        if report_output:
            from .report import render_report
            report_html=render_report(payload)
            payload.pop('review_geometry',None)
            report_output.parent.mkdir(parents=True,exist_ok=True)
            with report_output.open('x',encoding='utf-8') as stream:stream.write(report_html)
            rendered=json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
        if output:
            output.parent.mkdir(parents=True,exist_ok=True)
            with output.open('x',encoding='utf-8') as stream:stream.write(rendered)
        print(rendered,end='');return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)}),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
