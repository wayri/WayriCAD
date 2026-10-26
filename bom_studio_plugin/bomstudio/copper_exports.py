"""Standalone saved-copper report exports, independent of BOM mappings."""
import csv,html,io,json
from pathlib import Path

TABLES={'layers':'layers','nets':'nets','net_layers':'net_layers','zones':'zones','pad_contacts':'components'}
COLUMNS={
'layers':['layer','track_count','track_length_mm','pad_count','pad_area_mm2','via_count','zone_count','zone_boundary_area_mm2','filled_zone_area_mm2','copper_area_mm2','coverage_percent'],
'nets':['net','layers','track_count','track_length_mm','pad_count','pad_area_mm2','via_count','transition_count','zone_count','filled_zone_area_mm2','copper_area_mm2'],
'net_layers':['net','layer','track_count','track_length_mm','pad_count','pad_area_mm2','via_count','zone_count','zone_boundary_area_mm2','filled_zone_area_mm2','copper_area_mm2','coverage_percent'],
'zones':['id','name','net','layer','boundary_area_mm2','filled_zone_area_mm2','filled_polygon_count','status'],
'pad_contacts':['reference','value','side','pad_count','placement_pad_area_mm2','pad_area_by_layer','issues']}


def render(report,format='json',table='layers'):
    if table not in TABLES:raise ValueError('Choose a copper report table.')
    if format not in ('json','csv','tsv','html'):raise ValueError('Copper exports support JSON, CSV, TSV and HTML.')
    stem=Path(report.get('source',{}).get('path') or 'board').stem+'-copper'
    if format=='json':return (json.dumps(report,indent=2,allow_nan=False)+'\n').encode(),stem+'.json','application/json'
    rows=report.get(TABLES[table],[]);columns=COLUMNS[table]
    def value(v):return json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else '' if v is None else str(v)
    if format in ('csv','tsv'):
        output=io.StringIO(newline='');writer=csv.writer(output,delimiter='\t' if format=='tsv' else ',',lineterminator='\r\n')
        writer.writerow(['Source SHA-256',*columns])
        for row in rows:
            values=[report.get('source',{}).get('sha256',''),*[value(row.get(c)) for c in columns]]
            writer.writerow("'"+x if isinstance(x,str) and x.startswith(('=','+','-','@')) else x for x in values)
        return output.getvalue().encode('utf-8-sig'),stem+'-'+table+'.'+format,'text/tab-separated-values' if format=='tsv' else 'text/csv'
    esc=lambda v:html.escape(value(v))
    sections=[]
    for key,field in TABLES.items():
        cols=COLUMNS[key]
        sections.append('<h2>'+esc(key.replace('_',' ').title())+'</h2><div class="table"><table><thead><tr>'+''.join('<th>'+esc(c)+'</th>' for c in cols)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(row.get(c))+'</td>' for c in cols)+'</tr>' for row in report.get(field,[]))+'</tbody></table></div>')
    summary=''.join('<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>' for k,v in report.get('summary',{}).items())
    page='<!doctype html><meta charset="utf-8"><title>Saved PCB copper analysis</title><style>body{font:16px system-ui;margin:2em;color:#243746}table{border-collapse:collapse}td,th{border:1px solid #bac8d0;padding:.4em;text-align:left}.table{overflow:auto}dt{font-weight:bold}dd{margin-bottom:.6em}</style><h1>Saved PCB copper analysis</h1><p>'+esc(report.get('source',{}).get('path'))+'</p><p>Status: '+esc(report.get('status'))+' · SHA-256: '+esc(report.get('source',{}).get('sha256'))+'</p><p>Areas are mm²; lengths are mm. Unknown values remain blank. Layer totals sum separate copper faces. No electrical/thermal simulation or source edits.</p><dl>'+summary+'</dl><ul>'+''.join('<li>'+esc(w)+'</li>' for w in report.get('warnings',[]))+'</ul>'+''.join(sections)
    return page.encode(),stem+'.html','text/html; charset=utf-8'
