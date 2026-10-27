"""Offline, escaped protocol-screen evidence and route illustrations."""
import html
import json
import math


def text(value):
    if value is None:return 'Unknown'
    if isinstance(value,(dict,list,tuple)):return json.dumps(value,ensure_ascii=False,allow_nan=False)
    if isinstance(value,float):return f'{value:.6g}'
    return str(value)


def route_svg(path):
    lines=[]
    if not isinstance(path,dict):return '<p>No route geometry available.</p>'
    segments=path.get('segments',[])
    if not isinstance(segments,list):return '<p>No route geometry available.</p>'
    for segment in segments[:20000]:
        try:
            a,b=segment['start_mm'],segment['end_mm']
            values=[float(v) for v in (*a,*b)]
            if len(values)!=4 or not all(math.isfinite(v) for v in values):continue
            lines.append(values)
        except (KeyError,TypeError,ValueError,OverflowError):continue
    if not lines:return '<p>No drawable section coordinates in this path report.</p>'
    xs=[v for row in lines for v in (row[0],row[2])];ys=[v for row in lines for v in (row[1],row[3])]
    x,y=min(xs)-.5,min(ys)-.5;w,h=max(xs)-x+.5,max(ys)-y+.5
    return f'<svg role="img" aria-label="Reviewed route centerlines" viewBox="{x} {y} {w} {h}" width="100%" height="240">'+''.join(
        f'<line x1="{a}" y1="{b}" x2="{c}" y2="{d}" stroke="#247b9c" stroke-width=".12"/>' for a,b,c,d in lines)+'</svg>'


def render_section(report):
    escape=lambda v:html.escape(text(v),quote=True)
    profile=report.get('profile',{})
    title=profile.get('title',profile.get('id','Protocol suite')) if isinstance(profile,dict) else profile
    checks=''.join('<tr>'+''.join('<td>'+escape(v)+'</td>' for v in (
        check.get('status'),check.get('name',check.get('id','').replace('_',' ')),
        check.get('measured'),check.get('limit'),check.get('unit',''),check.get('evidence','')))+' </tr>'
        for check in report.get('checks',[]))
    notes=''.join('<li>'+escape(note)+'</li>' for note in report.get('limitations',[]))
    references=''.join('<li><a href="'+escape(url)+'">'+escape(url)+'</a></li>' for url in profile.get('references',[]) if isinstance(url,str) and url.startswith('https://')) if isinstance(profile,dict) else ''
    return '<section><h2>'+escape(title)+'</h2><p><b>'+escape(report.get('status'))+'</b> · Engineering screening, not protocol certification.</p><table><thead><tr><th>Status</th><th>Check</th><th>Measured</th><th>Limit</th><th>Unit</th><th>Evidence</th></tr></thead><tbody>'+checks+'</tbody></table><ul>'+notes+'</ul><details><summary>Profile references (internet links)</summary><ul>'+references+'</ul></details></section>'


def timing_section(timing):
    """Static, printable pair timing tables; no script needed to read results."""
    if not timing or not timing.get('pairs'):
        return ''
    escape=lambda v:html.escape(text(v),quote=True)
    def table(headers, fields):
        rows=''.join('<tr>'+''.join('<td>'+escape(row.get(k))+'</td>' for k in fields)+'</tr>' for row in timing['pairs'])
        return '<table><thead><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+rows+'</tbody></table>'
    delays=table(('Pair','Evidence','P delay ns','N delay ns','N - P ps','Absolute skew ps'),
                 ('group','status','p_delay_ns','n_delay_ns','signed_skew_ps','absolute_skew_ps'))
    phase=table(('Pair','Unwrapped mismatch deg','Wrapped mismatch deg'),
                ('group','phase_mismatch_deg','wrapped_phase_mismatch_deg'))
    lanes=table(('Pair','Mean delay ns','Reference pair','Lane skew ps','Lane phase deg'),
                ('group','mean_delay_ns','reference_group','lane_skew_ps','lane_phase_deg'))
    evidence=''.join('<li><b>'+escape(row['group'])+'</b>: '+escape('; '.join(row['evidence']))+'</li>' for row in timing['pairs'])
    return ('<section><h2>Differential pair delay and phase matching</h2>'
            '<p>Frequency: '+escape(timing.get('frequency_hz'))+' Hz. Reference pair: '+escape(timing.get('reference_group'))+'.</p>'
            '<p>'+escape(timing['conventions'])+'</p><h3>Within each pair: leg delays and skew</h3>'+delays+
            '<h3>Within each pair: propagation phase mismatch</h3>'+phase+
            '<h3>Between pairs: mean-delay matching</h3>'+lanes+
            '<h3>Delay model evidence</h3><ul>'+evidence+'</ul><ul>'+
            ''.join('<li>'+escape(note)+'</li>' for note in timing['limitations'])+'</ul></section>')


def html_report(report):
    escape=lambda v:html.escape(text(v),quote=True)
    paths=''
    for path_report in report.get('paths',[]):
        if not isinstance(path_report,dict):continue
        path=path_report.get('path',{})
        if not isinstance(path,dict):continue
        paths+='<h3>'+escape(path.get('net_name','Route'))+' · '+escape(path.get('start_pad'))+' → '+escape(path.get('end_pad'))+'</h3>'+route_svg(path)
        if path_report.get('eye'):
            from .eye_view import eye_section
            try:paths+=eye_section(path_report['eye'])
            except (KeyError,TypeError,ValueError,IndexError,ZeroDivisionError,AttributeError,OverflowError):
                paths+='<p>Eye plot unavailable: incomplete or invalid imported eye data. Rerun the Quick SI eye model.</p>'
    document='<!doctype html><meta charset="utf-8"><title>WayriCAD protocol suite</title><style>body{font:15px system-ui;max-width:1200px;margin:24px auto;color:#20303c;padding:0 16px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ccd7df;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}svg{background:#f7fafc}</style><h1>Quick SI · Protocol suite</h1>'+render_section(report)+timing_section(report.get('pair_timing'))+paths+'<details><summary>Profile, inputs and evidence JSON</summary><pre>'+escape(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False))+'</pre></details>'

    from wayricad_runtime.report_ui import enhance_report, provenance
    checks=report.get('checks',[])
    counts={status:sum(row.get('status')==status for row in checks) for status in ('PASS','FAIL','UNKNOWN','INCOMPLETE')}
    summary=[('Model','Declared protocol screening checks; not certification'),('Checks',len(checks)),('Failed checks',counts['FAIL']),('Unknown checks',counts['UNKNOWN']+counts['INCOMPLETE']),('Included route reports',len(report.get('paths',[])))]
    return enhance_report(document,status=report.get('status','UNKNOWN'),summary=summary,notice='Only the listed modeled checks are evaluated. Unresolved coupling, discontinuities, device behavior or channel evidence remain outside this result; a check pass is not whole-protocol qualification.',provenance=provenance(report))
