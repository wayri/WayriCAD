"""Offline searchable geometric heat map, retaining unknown coupling evidence."""
from html import escape
import json
from pathlib import Path
from .neighbours import NOTICE


def colour(closeness):
    """Fixed geometric legend: teal (radius) through amber to red (contact)."""
    stops=((34,135,142),(230,165,44),(197,49,61))
    value=max(0.,min(1.,closeness))*2;i=min(1,int(value));f=value-i
    return '#'+''.join(f'{round(stops[i][k]*(1-f)+stops[i+1][k]*f):02x}' for k in range(3))


def pair_text(pair):
    voltage='UNKNOWN' if pair['next_peak_v'] is None else f"{pair['next_peak_v']*1000:.6g} mV (assumed local matched section)"
    x,y=pair['location_mm']
    study='; '.join(f"{row['pair_id']}: {row['next_peak_v']*1000:.6g} mV over {row['section_length_mm']:.6g} mm ({row['status']})" for row in pair.get('study_sections',[]))
    return (f"{pair['a']['net']} ↔ {pair['b']['net']} · {pair['layer']} · edge gap {pair['gap_mm']:.6g} mm · "
            f"parallel overlap {pair['parallel_length_mm']:.6g} mm · closest location ({x:.6g}, {y:.6g}) mm · "
            f"local NEXT {voltage} · {pair['reason']}"+(' · Explicit study sections: '+study+'; study extent may exceed map segment; peaks are not added.' if study else ''))


def svg_map(report):
    pairs=report['pairs'];coords=[p for row in pairs for side in ('a','b') for p in (row[side]['start_mm'],row[side]['end_mm'])]
    if not coords:return '<p>No neighbours found within this bounded search. This does not establish zero interference.</p>'
    low=[min(p[k] for p in coords) for k in (0,1)];high=[max(p[k] for p in coords) for k in (0,1)]
    scale=900/max(1.,high[0]-low[0],high[1]-low[1])
    point=lambda p:((p[0]-low[0])*scale+35,(p[1]-low[1])*scale+35)
    width=(high[0]-low[0])*scale+70;height=(high[1]-low[1])*scale+70
    out=[f'<svg id="neighbour-map" aria-label="Geometric edge-gap heat map" role="img" viewBox="0 0 {width:.3f} {height:.3f}" data-box="0 0 {width:.3f} {height:.3f}" style="width:100%;height:540px;background:#f6f9fa;border:1px solid #b9cbd0;touch-action:none">']
    for row in reversed(pairs):
        out.append(f'<g data-pair="{row["id"]}" tabindex="0" role="button" aria-label="{escape(pair_text(row),quote=True)}"><title>{escape(pair_text(row))}</title>')
        for side in ('a','b'):
            track=row[side];a,b=point(track['start_mm']),point(track['end_mm'])
            out.append(f'<line x1="{a[0]:.4f}" y1="{a[1]:.4f}" x2="{b[0]:.4f}" y2="{b[1]:.4f}" stroke="{colour(row["closeness"])}" stroke-width="{max(2.,track["width_mm"]*scale):.3f}" stroke-linecap="round"/>')
        x,y=point(row['location_mm'])
        out.append(f'<circle cx="{x:.4f}" cy="{y:.4f}" r="5" fill="white" stroke="{colour(row["closeness"])}" stroke-width="2"/></g>')
    out.append('</svg>')
    return ''.join(out)


def html_report(report):
    radius=report['settings']['radius_mm'];rows=[]
    for pair in report['pairs']:
        values=(pair['a']['net'],pair['b']['net'],pair['layer'],f"{pair['gap_mm']:.6g}",
                f"{pair['parallel_length_mm']:.6g}",'UNKNOWN' if pair['next_peak_v'] is None else f"{1000*pair['next_peak_v']:.6g}",
                ', '.join(f"{r['next_peak_v']*1000:.6g}" for r in pair.get('study_sections',[])) or 'UNKNOWN',pair['coupling_status'],pair_text(pair))
        rows.append(f'<tr tabindex="0" data-row="{pair["id"]}" data-layer="{escape(pair["layer"],quote=True)}" data-description="{escape(pair_text(pair),quote=True)}">'+''.join('<td>'+escape(str(v))+'</td>' for v in values)+'</tr>')
    layers=sorted({p['layer'] for p in report['pairs']})
    document=('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
              '<title>Quick SI neighbour trace exposure map</title><style>body{font:15px system-ui,sans-serif;color:#173942;max-width:1450px;margin:28px auto;padding:0 20px}button,input,select{font:inherit;padding:7px}table{width:100%;border-collapse:collapse}td,th{padding:8px;text-align:left;border-bottom:1px solid #ccd9dc}tr[aria-selected=true]{background:#e0f2f3}g[data-pair]{cursor:pointer}g[aria-selected=true]{filter:drop-shadow(0 0 3px #173942)}.legend{width:280px;height:16px;background:linear-gradient(90deg,#c5313d,#e6a52c,#22878e)}pre{white-space:pre-wrap}#picked{padding:12px;background:#edf4f5;min-height:3em} @media print{svg{height:420px!important}}</style>'
              '<h1>Quick SI · Neighbour trace exposure map</h1><p>'+escape(NOTICE)+'</p><p><strong>Search status: '+escape(report['status'])+'</strong> · '+str(len(rows))+' retained pairs</p>'
              '<div class="legend" aria-label="Gap colour scale"></div><p>Red: edge gap ≤ 0 mm · Amber: '+f'{radius/2:.4g}'+' mm · Teal: '+f'{radius:.4g}'+' mm search radius. Colour never represents NEXT voltage. UNKNOWN means coupling was not solved.</p>'
              '<label>Search nets / evidence <input id="search" type="search"></label> <label>Layer <select id="layer"><option value="">All mapped layers</option>'+''.join('<option>'+escape(v)+'</option>' for v in layers)+'</select></label> <button id="fit">Fit map</button><p>Hover for evidence; click a trace marker or table row to select its gap, overlap and closest location. Wheel zooms; drag pans. Only retained neighbour pairs are drawn.</p>'
              +svg_map(report)+'<p id="picked" aria-live="polite">Choose a pair to inspect its evidence.</p><div style="overflow:auto"><table><thead><tr>'+''.join('<th>'+v+'</th>' for v in ('Trace net','Neighbour net','Layer','Edge gap mm','Parallel overlap mm','Local NEXT mV','Study section NEXT mV','Coupling status','Evidence / unknown reason'))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
              '<h2>Coverage and budgets</h2><pre>'+escape(json.dumps(report['coverage'],indent=2))+'</pre><h2>Warnings</h2><ul>'+''.join('<li>'+escape(v)+'</li>' for v in report['warnings'])+'</ul><details><summary>Explicit settings and local-model assumptions</summary><pre>'+escape(json.dumps(report['settings'],indent=2))+'</pre><ul>'+''.join('<li>'+escape(v)+'</li>' for v in report['model_limitations'])+'</ul></details>')
    fingerprints={Path(name).suffix:stamp for name,stamp in report.get('source_fingerprints',{}).items()}
    document+='<h2>Saved-source fingerprints</h2><pre>'+escape(json.dumps(fingerprints or {'status':'Not supplied'},indent=2))+'</pre>'
    return document+'''<script>(()=>{
const svg=document.querySelector('#neighbour-map'),rows=[...document.querySelectorAll('tr[data-row]')],groups=[...document.querySelectorAll('g[data-pair]')];
function pick(id){let row=rows.find(r=>r.dataset.row===id);if(!row)return;rows.forEach(r=>r.setAttribute('aria-selected',r===row));groups.forEach(g=>g.setAttribute('aria-selected',g.dataset.pair===id));document.querySelector('#picked').textContent=row.dataset.description;}
function filter(){let q=document.querySelector('#search').value.toLowerCase(),layer=document.querySelector('#layer').value;rows.forEach(r=>{r.hidden=!((!layer||r.dataset.layer===layer)&&r.textContent.toLowerCase().includes(q));let g=groups.find(g=>g.dataset.pair===r.dataset.row);if(g)g.style.display=r.hidden?'none':'';});}
rows.forEach(r=>{r.onclick=()=>pick(r.dataset.row);r.onkeydown=e=>{if(e.key==='Enter')pick(r.dataset.row);};});groups.forEach(g=>{g.onclick=()=>pick(g.dataset.pair);g.onkeydown=e=>{if(e.key==='Enter')pick(g.dataset.pair);};});
document.querySelector('#search').oninput=filter;document.querySelector('#layer').onchange=filter;
if(svg){let box=()=>svg.viewBox.baseVal,drag=null;document.querySelector('#fit').onclick=()=>svg.setAttribute('viewBox',svg.dataset.box);
svg.addEventListener('wheel',e=>{e.preventDefault();let b=box(),f=e.deltaY>0?1.2:1/1.2;if(b.width*f<.1||b.width*f>1e7)return;let r=svg.getBoundingClientRect(),x=b.x+b.width*(e.clientX-r.left)/r.width,y=b.y+b.height*(e.clientY-r.top)/r.height;b.x=x+(b.x-x)*f;b.y=y+(b.y-y)*f;b.width*=f;b.height*=f;},{passive:false});
svg.onpointerdown=e=>{if(e.target.closest('g[data-pair]'))return;drag=[e.clientX,e.clientY,box().x,box().y];svg.setPointerCapture(e.pointerId);};svg.onpointermove=e=>{if(!drag)return;let r=svg.getBoundingClientRect();box().x=drag[2]-(e.clientX-drag[0])*box().width/r.width;box().y=drag[3]-(e.clientY-drag[1])*box().height/r.height;};svg.onpointerup=()=>drag=null;svg.onpointercancel=()=>drag=null;}
})();</script></html>'''
