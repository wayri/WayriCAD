"""Shared read-only transient study provenance, plots and offline reports."""
from __future__ import annotations

import base64
import hashlib
from html import escape
import io
import json
from pathlib import Path


def execute_study(request, solver):
    """Run explicit model inputs, retaining and checking any saved PCB context."""
    study=request.get('study')
    if not isinstance(study,dict):raise ValueError('Transient study must be an object.')
    study_path=Path(request['study_input_path']).resolve() if request.get('study_input_path') else None
    study_hash=None
    if study_path:
        if not study_path.is_file() or study_path.stat().st_size>1024*1024:
            raise ValueError('Transient input must be a JSON file no larger than 1 MiB.')
        content=study_path.read_bytes()
        study_hash=hashlib.sha256(content).hexdigest()
        if request.get('study_file_sha256') and study_hash!=request['study_file_sha256']:
            raise ValueError('Transient input study changed. Reload before running.')
    source=Path(request['board_path']).resolve() if request.get('board_path') else None
    before=None
    if source:
        if source.suffix.lower()!='.kicad_pcb' or not source.is_file():raise ValueError('Choose a saved KiCad PCB.')
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        if request.get('source_sha256') and before!=request['source_sha256']:
            raise ValueError('Saved board changed. Reload before running a transient study.')
    result=solver(study)
    if source and hashlib.sha256(source.read_bytes()).hexdigest()!=before:
        raise ValueError('Saved board changed during the transient study; discard this result.')
    if study_path and hashlib.sha256(study_path.read_bytes()).hexdigest()!=study_hash:
        raise ValueError('Input study changed during the transient study; discard this result.')
    return {'transient':result,'study':study,'source_sha256':before,
            'board_path':str(source) if source else None,'study_input_path':str(study_path) if study_path else None,
            'study_file_sha256':study_hash}


def limits_violated(result):
    return result.get('feasibility',{}).get('feasible') is False or result.get('limits',{}).get('within_all_specified_limits') is False


def study_title(result):
    return 'Quick PI · Transient RLC load steps' if 'loads' in result else 'QuickTherm · Transient RC power steps'


def draw_study(figure,bundle):
    """Time plots of raw state samples; field interpolation is never implied."""
    result=bundle['transient'];times=result['times_s']
    figure.clear();voltage=figure.add_subplot(211);power=figure.add_subplot(212,sharex=voltage)
    is_pi='loads' in result
    rows=result['loads'] if is_pi else result['components']
    shown=rows[:12]
    for row in shown:
        label=str(row.get('label') or row.get('reference') or row['id'])
        voltage.plot(times,row['voltage_V'] if is_pi else row['temperature_c'],label=label,linewidth=1.5)
        if is_pi:
            for key in ('min_voltage_V','max_voltage_V'):
                bound=row.get('limits',{}).get(key)
                if bound is not None:voltage.axhline(bound,color='#8c544c',linestyle=':',linewidth=.8)
        else:
            power.step(times,row['power_W'],where='post',label=label,linewidth=1.2)
            if row.get('limit_c') is not None:voltage.axhline(row['limit_c'],color='#8c544c',linestyle=':',linewidth=.8)
    if is_pi:
        power.plot(times,result['source_current_A'],label='Source branch current',linewidth=1.5)
        limit=bundle['study'].get('source_current_limit_A')
        if limit is not None:power.axhline(limit,color='#b54236',linestyle='--',label='Current budget (diagnostic)')
    voltage.set_ylabel('Load-node voltage (V)' if is_pi else 'Component temperature (°C)')
    power.set_ylabel('Source current (A)' if is_pi else 'Applied power (W)')
    power.set_xlabel('Time (s)')
    for ax in (voltage,power):
        ax.grid(True,alpha=.2)
        if ax.lines:ax.legend(loc='best',fontsize=8)
    voltage.set_title(('LIMIT VIOLATION · ' if limits_violated(result) else '')+study_title(result)+(' · first 12 traces shown' if len(rows)>12 else ''),fontsize=10)
    figure.tight_layout()
    return voltage,power


def study_summary(bundle):
    result=bundle['transient']
    summary={key:result[key] for key in ('notice','feasibility','limits','checks','numerics','energy_balance') if key in result}
    return json.dumps(summary,indent=2,allow_nan=False)


def write_study_report(path,bundle):
    """Export paired HTML/JSON without replacing a board or input study file."""
    from .report_ui import report_paths, publish_report, enhance_report, provenance
    from .transient_review import review_html, review_rows
    path,json_path=report_paths(Path(path).absolute())
    protected={Path(bundle[key]).resolve() for key in ('board_path','study_input_path') if bundle.get(key)}
    if any(target in protected for target in (path,json_path)):
        raise ValueError('Transient report must not overwrite the source PCB or study input.')
    if bundle.get('board_path'):
        source=Path(bundle['board_path'])
        if hashlib.sha256(source.read_bytes()).hexdigest()!=bundle.get('source_sha256'):
            raise ValueError('Saved board changed. Reload and rerun before exporting.')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure=Figure(figsize=(10,6),dpi=130);FigureCanvasAgg(figure)
    draw_study(figure,bundle)
    stream=io.BytesIO();figure.savefig(stream,format='png',facecolor='white')
    result=bundle['transient']
    html='<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD transient study</title><style>body{font:15px system-ui;max-width:1100px;margin:30px auto;padding:0 20px}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    html+='<h1>'+escape(study_title(result))+'</h1><p>'+escape(result.get('notice',''))+'</p>'
    html+='<p><a href="'+escape(json_path.name)+'">All raw time samples and explicit inputs (JSON)</a></p>'
    html+='<img alt="Transient time traces" src="data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')+'">'
    html+=review_html(bundle)
    html+='<h2>Checks and limits</h2><pre>'+escape(study_summary(bundle))+'</pre><h2>Explicit model inputs</h2><pre>'+escape(json.dumps(bundle['study'],indent=2,allow_nan=False))+'</pre></html>'
    rows=review_rows(result)
    status='LIMIT VIOLATION' if limits_violated(result) else 'MODEL SCREEN COMPLETE'
    html=enhance_report(html,status=status,summary=[('Model',result.get('model')),
        ('Simulated units',len(rows)),('Computed samples per unit',len(result['times_s'])),
        ('Units without specified limits',sum(row['status']=='NOT EVALUATED' for row in rows))],
        notice=result.get('notice',''),provenance=provenance(bundle))
    return publish_report(path,html,bundle)


def transient_cli(args,run_job,forbidden=False):
    """Bounded JSON intake shared by the two independently installed CLIs."""
    if forbidden:raise ValueError('--transient cannot combine with steady-state analysis options.')
    source=args.transient.resolve()
    if not source.is_file() or source.stat().st_size>262144:raise ValueError('Transient input must be a JSON file no larger than 256 KiB.')
    content=source.read_bytes()
    study=json.loads(content.decode('utf-8-sig'))
    if not isinstance(study,dict):raise ValueError('Transient input must contain an object.')
    protected={source}
    if args.board:protected.add(args.board.resolve())
    for output in (args.output,args.html):
        if output and output.resolve() in protected:raise ValueError('Output must not overwrite the source PCB or study input.')
    if args.html and args.html.resolve().with_suffix('.json') in protected:
        raise ValueError('Report JSON must not overwrite the study input.')
    if args.html and args.output and args.output.resolve()==args.html.resolve().with_suffix('.html'):
        raise ValueError('JSON output and HTML report must use different files.')
    request={'action':'transient','study':study,'study_input_path':str(source),
             'study_file_sha256':hashlib.sha256(content).hexdigest()}
    if args.board:request['board_path']=str(args.board.resolve())
    if args.html:request['html_output']=str(args.html.resolve())
    result=run_job(request,timeout=args.timeout)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,allow_nan=False))
    analysis=result.get('transient',{})
    return 4 if limits_violated(analysis) else 0
