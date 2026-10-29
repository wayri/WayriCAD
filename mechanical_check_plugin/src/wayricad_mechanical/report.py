"""Portable, offline reports with immutable run metadata and interactive geometry."""
import csv
import html
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def export(report, output, *, pocket_kivi=False):
    # Live geometry ownership and query tokens never belong in portable evidence.
    report = {key: value for key, value in report.items() if key != '_measurement_session'}
    portable = protected = guard = None
    unavailable = None
    if pocket_kivi:
        kind = str(report.get('source_kind', '')).casefold()
        if 'live' in kind or 'snapshot' in kind:
            unavailable = 'Live/snapshot scene retained in full JSON; no verified saved-PCB binding was created.'
        elif report.get('comparison_board'):
            unavailable = 'Multi-board scene retained in full JSON; portable multi-board source bindings are not yet supported.'
        else:
            from wayricad_runtime.pocket_report import evidence_context, prepare_report
            evidence = evidence_context(report, tool='mechanical-check', module_file=__file__,
                package=__package__, version=report.get('version'),
                coordinate_frame='Mechanical scene coordinates',
                units=report.get('units') if isinstance(report.get('units'), dict) else None)
            portable, protected, guard = prepare_report(report, evidence)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    project = re.sub(r'[^a-zA-Z0-9._-]+', '-', report['project_name']).strip('.-')[:80] or 'project'
    folder = Path(output) / (project + '_' + stamp)
    json_path, csv_path, html_path = [folder / ('WayriCAD-Mechanical-Check-report.' + ext) for ext in ('json', 'csv', 'html')]
    numerical = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
    stream = io.StringIO(newline='')
    columns = ['project', 'completed_at', 'id', 'severity', 'rule', 'refs', 'summary', 'evidence', 'measured', 'limit', 'unit', 'side', 'excess_mm', 'action', 'waiver']
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for f in report['findings']:
        row = {key: f.get(key, '') for key in columns}
        row.update(project=report['project_name'], completed_at=report['completed_at'], refs=', '.join(f['refs']))
        # Spreadsheet formula injection prevention for user-controlled board text.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v) for k, v in row.items()})
    payload = json.dumps(report, ensure_ascii=True, allow_nan=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = Path(__file__).with_name('report_template.html').read_text(encoding='utf-8')
    scene = Path(__file__).with_name('report_scene.js').read_text(encoding='utf-8')
    rows=[]
    for finding in report['findings']:
        measured='' if finding.get('measured') is None else str(finding['measured'])+' '+str(finding.get('unit',''))
        values=(', '.join(finding['refs'])+' / '+finding['rule'],
                finding['summary']+' ('+str(finding.get('evidence',''))+') '+measured,
                str(finding.get('action',''))+(' WAIVED: '+str(finding['waiver']) if finding.get('waiver') else ''))
        rows.append('<tr>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in values)+'</tr>')
    replacements={'TITLE':html.escape(report['project_name']),'REPORT_DATA':payload,'SCENE_SCRIPT':scene,'FINDING_ROWS':''.join(rows)}
    document = re.sub(r'__(TITLE|REPORT_DATA|SCENE_SCRIPT|FINDING_ROWS)__',lambda m:replacements[m[1]],template)
    documents = {json_path: numerical, csv_path: stream.getvalue().encode('utf-8-sig'), html_path: document}
    result = dict(html=str(html_path.resolve()), json=str(json_path.resolve()), csv=str(csv_path.resolve()))
    if portable is not None:
        destination = folder / 'WayriCAD-Mechanical-Check-report.pocket-kivi.json'
        documents[destination] = portable
        result['pocket_kivi_json'] = str(destination.resolve())
    if unavailable:
        result['pocket_kivi_unavailable'] = unavailable
    from wayricad_runtime.report_ui import publish_documents
    folder.mkdir(parents=True, exist_ok=False)
    try:
        publish_documents(documents, sources=protected or (), source_guard=guard)
    except Exception:
        try:
            folder.rmdir()
        except OSError:
            pass
        raise
    return result
