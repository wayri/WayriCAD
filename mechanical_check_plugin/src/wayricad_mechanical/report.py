"""Portable, offline reports with immutable run metadata and interactive geometry."""
import csv
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def export(report, output):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    project = re.sub(r'[^a-zA-Z0-9._-]+', '-', report['project_name']).strip('.-')[:80] or 'project'
    folder = Path(output) / (project + '_' + stamp)
    folder.mkdir(parents=True, exist_ok=False)
    json_path, csv_path, html_path = [folder / ('WayriCAD-Mechanical-Check-report.' + ext) for ext in ('json', 'csv', 'html')]
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    with csv_path.open('w', newline='', encoding='utf-8-sig') as stream:
        columns = ['project', 'completed_at', 'id', 'severity', 'rule', 'refs', 'summary', 'evidence', 'measured', 'limit', 'unit', 'action', 'waiver']
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for f in report['findings']:
            row = {key: f.get(key, '') for key in columns}
            row.update(project=report['project_name'], completed_at=report['completed_at'], refs=', '.join(f['refs']))
            # Spreadsheet formula injection prevention for user-controlled board text.
            writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')) else v) for k, v in row.items()})
    payload = json.dumps(report, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    template = Path(__file__).with_name('report_template.html').read_text(encoding='utf-8')
    scene = Path(__file__).with_name('report_scene.js').read_text(encoding='utf-8')
    replacements={'TITLE':html.escape(report['project_name']),'REPORT_DATA':payload,'SCENE_SCRIPT':scene}
    html_path.write_text(re.sub(r'__(TITLE|REPORT_DATA|SCENE_SCRIPT)__',lambda m:replacements[m[1]],template), encoding='utf-8')
    return dict(html=str(html_path.resolve()), json=str(json_path.resolve()), csv=str(csv_path.resolve()))
