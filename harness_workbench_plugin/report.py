"""Self-contained interactive HTML harness report."""

from __future__ import annotations

import json
from dataclasses import asdict
from html import escape
from typing import Iterable

from .analysis import (
    HarnessBundle, HarnessLink, HarnessSplice, PinRecord,
    SystemSignalPath, harness_bom, system_signal_rows, validate_links,
)


def _table(rows: list[dict[str, object]], table_id: str) -> str:
    if not rows:
        return '<p class="empty">No rows available.</p>'
    headers = list(rows[0])
    head = "".join(f"<th>{escape(str(item))}</th>" for item in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(item, '')))}</td>" for item in headers)
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table id="{table_id}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _wire_rows(links: Iterable[HarnessLink]) -> list[dict[str, object]]:
    return [{
        "Wire": link.wire_id,
        "Source": f"{link.source.project}:{link.source.connector}.{link.source.pin}",
        "Source Net": link.source.net,
        "Destination": f"{link.destination.project}:{link.destination.connector}.{link.destination.pin}",
        "Destination Net": link.destination.net,
        "AWG": link.gauge_awg,
        "Color": link.color,
        "Bundle": link.bundle or "Unbundled",
        "Splice": link.splice,
        "Length m": f"{link.length_m:.3f}",
        "Shield": link.shield,
        "Status": link.status,
        "Notes": link.notes,
    } for link in links]


def _bundle_rows(bundles: Iterable[HarnessBundle], links: Iterable[HarnessLink]) -> list[dict[str, object]]:
    links = list(links); configured = {bundle.name: bundle for bundle in bundles}
    names = sorted({link.bundle or "Unbundled" for link in links} | set(configured))
    rows = []
    for name in names:
        members = [link for link in links if (link.bundle or "Unbundled") == name]
        config = configured.get(name)
        rows.append({
            "Bundle": name, "Wires": len(members),
            "AWG": config.gauge_awg if config else ", ".join(sorted({item.gauge_awg for item in members})),
            "Shield": config.shield if config else ", ".join(sorted({item.shield for item in members if item.shield})),
            "Sleeve": config.sleeve if config else "",
            "Nominal Length m": f"{config.length_m:.3f}" if config else "",
            "Service Loop %": f"{config.service_loop_percent:g}" if config else "",
            "Wire IDs": ", ".join(item.wire_id for item in members),
        })
    return rows


def interactive_harness_html(records: list[PinRecord], links: list[HarnessLink],
                             bundles: list[HarnessBundle] = (), splices: list[HarnessSplice] = (),
                             system_paths: list[SystemSignalPath] = (),
                             title: str = "KiWay Interactive Harness") -> str:
    """Create an offline HTML report with an interactive system/harness canvas."""
    path_rows = system_signal_rows(system_paths)
    wire_rows = _wire_rows(links)
    bundle_rows = _bundle_rows(bundles, links)
    bom_rows = harness_bom(records, links, bundles, splices)
    findings = [{"Severity": "Warning", "Finding": item} for item in validate_links(links)]
    findings.extend({
        "Severity": "Warning" if item.status in ("Incomplete", "Ambiguous") else "Review",
        "Finding": f"{item.path_id} is {item.status}: {item.ordered_path}",
    } for item in system_paths if item.status != "Resolved")
    data = {
        "title": title,
        "paths": [asdict(item) for item in system_paths],
        "links": [asdict(item) for item in links],
        "bundles": bundle_rows,
    }
    payload = json.dumps(data, ensure_ascii=True).replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f4f6f8;--panel:#fff;--ink:#17212b;--muted:#66727d;--line:#c9d1d8;--accent:#147d75;--power:#c64b3c;--warn:#bc7514;--ok:#1d7a4d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px "Segoe UI",Arial,sans-serif;letter-spacing:0}
header{height:58px;background:#202a33;color:#fff;display:flex;align-items:center;padding:0 22px;gap:18px}header h1{font-size:20px;margin:0}header .summary{color:#cdd6dd}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:10px 14px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:3}
button,select,input{height:32px;border:1px solid #aeb8c1;background:#fff;color:var(--ink);padding:0 10px;font:inherit}button{cursor:pointer}button:hover{border-color:var(--accent)}input{min-width:240px}.spacer{flex:1}.legend{display:flex;gap:12px;color:var(--muted)}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}
#viewport{height:68vh;min-height:520px;background:#eef2f5;border-bottom:1px solid var(--line);overflow:hidden;touch-action:none;position:relative}
#diagram{width:100%;height:100%;display:block}.stage{font-size:13px;font-weight:600;fill:#52616d}.node rect{fill:#fff;stroke:#6b7b88;stroke-width:1.5}.node.endpoint rect{stroke:#2b806f}.node.connector rect{stroke:#2775a0}.node.bundle rect{stroke:#a66919;fill:#fff8ec}.node text{pointer-events:none;fill:var(--ink)}.node .sub{fill:var(--muted);font-size:11px}.edge{fill:none;stroke-width:2.5;opacity:.76;cursor:pointer}.edge:hover,.edge.selected{stroke-width:6;opacity:1}.node{cursor:move}.node.dim,.edge.dim{opacity:.08}.hidden{display:none!important}
#detail{position:absolute;right:14px;top:14px;width:min(420px,40vw);max-height:calc(100% - 28px);overflow:auto;background:rgba(255,255,255,.96);border:1px solid var(--line);padding:12px;box-shadow:0 5px 18px #0002}.detail-title{font-size:15px;font-weight:700;margin-bottom:8px}.kv{display:grid;grid-template-columns:120px 1fr;gap:4px 8px}.kv div:nth-child(odd){color:var(--muted)}
main{padding:16px;max-width:1800px;margin:auto}.tabs{display:flex;gap:0;border-bottom:1px solid var(--line)}.tab{border:1px solid var(--line);border-bottom:0;padding:9px 14px;background:#e8edf1}.tab.active{background:#fff;font-weight:600}.pane{display:none;background:#fff;padding:12px;border:1px solid var(--line);border-top:0}.pane.active{display:block}.table-wrap{overflow:auto;max-height:58vh}table{border-collapse:collapse;width:100%;font-size:12px}th{position:sticky;top:0;background:#e8edf1;text-align:left;z-index:1}th,td{border:1px solid #cfd6dc;padding:6px;vertical-align:top}tbody tr:hover{background:#edf7f5}.empty{color:var(--muted)}
@media(max-width:600px){header{height:auto;min-height:58px;padding:10px 14px;align-items:flex-start;flex-direction:column;gap:3px}.toolbar button,.toolbar select{flex:1 1 auto}.toolbar input{min-width:0;width:100%;flex:1 0 100%}.toolbar .spacer{display:none}.legend{width:100%;flex-wrap:wrap}.tabs{flex-wrap:wrap}#detail{right:8px;top:8px;width:calc(100% - 16px);max-height:45%}main{padding:10px}#viewport{min-height:480px}}
@media(max-width:800px){#viewport{height:62vh}.legend{display:none}#detail{width:calc(100% - 28px);max-height:45%}.toolbar input{min-width:100px}.summary{display:none}}
</style></head><body>
<header><h1>__TITLE__</h1><div class="summary">__PATHCOUNT__ system paths | __WIRECOUNT__ wires | __BUNDLECOUNT__ bundles</div></header>
<div class="toolbar"><button id="fit">Fit</button><button id="zoomIn">+</button><button id="zoomOut">-</button><select id="bundleFilter"><option value="">All bundles</option></select><select id="statusFilter"><option value="">All statuses</option><option>Resolved</option><option>Conditional</option><option>Ambiguous</option><option>Incomplete</option></select><input id="search" placeholder="Search signal, IC, connector, wire..."><span class="spacer"></span><div class="legend"><span><i class="dot" style="background:#147d75"></i>Signal</span><span><i class="dot" style="background:#c64b3c"></i>Power</span><span><i class="dot" style="background:#bc7514"></i>Conditional</span></div></div>
<div id="viewport"><svg id="diagram"><g id="scene"></g></svg><aside id="detail"><div class="detail-title">Interactive harness</div><p>Wheel to zoom, drag empty space to pan, drag nodes to reposition, and click a path for complete board and harness details.</p></aside></div>
<main><div class="tabs"><button class="tab active" data-pane="paths">System paths</button><button class="tab" data-pane="wires">Wire list</button><button class="tab" data-pane="bundles">Bundles</button><button class="tab" data-pane="bom">BoM</button><button class="tab" data-pane="findings">Findings</button></div>
<section class="pane active" id="paths">__PATHTABLE__</section><section class="pane" id="wires">__WIRETABLE__</section><section class="pane" id="bundles">__BUNDLETABLE__</section><section class="pane" id="bom"><h2>Harness BoM</h2>__BOMTABLE__</section><section class="pane" id="findings">__FINDINGTABLE__</section></main>
<script>
const DATA=__DATA__;const svg=document.getElementById('diagram'),scene=document.getElementById('scene'),detail=document.getElementById('detail');
const NS='http://www.w3.org/2000/svg',colors=['#147d75','#d15b45','#3c70a4','#8d62a8','#d08a27','#378b58','#b64d72'];let scale=1,pan={x:0,y:0},drag=null,nodes=new Map(),edges=[];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const id=s=>String(s).replace(/[^a-zA-Z0-9_-]/g,'_');
const bundleNames=[...new Set((DATA.paths.length?DATA.paths.map(p=>p.bundle):DATA.links.map(l=>l.bundle||'Unbundled')))].sort();bundleNames.forEach((b,i)=>{let o=document.createElement('option');o.value=o.textContent=b;document.getElementById('bundleFilter').append(o)});const bundleColor=Object.fromEntries(bundleNames.map((b,i)=>[b,colors[i%colors.length]]));
function addNode(key,label,sub,stage,row,kind){if(nodes.has(key))return nodes.get(key);let g=document.createElementNS(NS,'g');g.classList.add('node',kind);g.dataset.key=key;g.dataset.search=(label+' '+sub).toLowerCase();let x=90+stage*300,y=72+row*92;g.dataset.x=x;g.dataset.y=y;g.innerHTML='<rect x="-105" y="-32" width="210" height="64" rx="5"/><text x="-92" y="-6" font-size="13" font-weight="600">'+esc(label)+'</text><text class="sub" x="-92" y="15">'+esc(sub)+'</text>';g.setAttribute('transform',`translate(${x} ${y})`);scene.append(g);nodes.set(key,g);g.addEventListener('pointerdown',e=>{e.stopPropagation();drag={node:g,x:e.clientX,y:e.clientY};g.setPointerCapture(e.pointerId)});g.addEventListener('pointermove',e=>{if(!drag||drag.node!==g)return;let dx=(e.clientX-drag.x)/scale,dy=(e.clientY-drag.y)/scale;drag.x=e.clientX;drag.y=e.clientY;g.dataset.x=+g.dataset.x+dx;g.dataset.y=+g.dataset.y+dy;g.setAttribute('transform',`translate(${g.dataset.x} ${g.dataset.y})`);updateEdges()});g.addEventListener('pointerup',()=>drag=null);return g}
function addEdge(path,from,to,bundle){let e=document.createElementNS(NS,'path');e.classList.add('edge');e.dataset.bundle=bundle;e.dataset.status=path.status||'linked';e.dataset.search=JSON.stringify(path).toLowerCase();e.style.stroke=(path.status==='Conditional'?'#bc7514':bundleColor[bundle]||'#147d75');e.addEventListener('click',ev=>{ev.stopPropagation();document.querySelectorAll('.edge.selected').forEach(x=>x.classList.remove('selected'));e.classList.add('selected');showDetail(path)});scene.insertBefore(e,scene.firstChild);edges.push({element:e,from,to});updateEdge(edges[edges.length-1])}
function updateEdge(edge){let a=nodes.get(edge.from),b=nodes.get(edge.to);if(!a||!b)return;let x1=+a.dataset.x+105,y1=+a.dataset.y,x2=+b.dataset.x-105,y2=+b.dataset.y,m=(x1+x2)/2;edge.element.setAttribute('d',`M${x1} ${y1} C${m} ${y1},${m} ${y2},${x2} ${y2}`)}function updateEdges(){edges.forEach(updateEdge)}
function build(){let rows=[0,0,0,0,0];if(DATA.paths.length){DATA.paths.forEach(p=>{let s=`se:${p.source_project}:${p.source_reference}:${p.source_pin}`,sc=`sc:${p.source_project}:${p.source_connector}`,b=`b:${p.bundle}`,dc=`dc:${p.destination_project}:${p.destination_connector}`,d=`de:${p.destination_project}:${p.destination_reference}:${p.destination_pin}`;addNode(s,p.source_reference||'Unresolved endpoint',`${p.source_project} | ${p.source_pin} ${p.source_function}`,0,rows[0]++,'endpoint');addNode(sc,p.source_connector,`${p.source_project} | pin ${p.source_connector_pin}`,1,rows[1]++,'connector');addNode(b,p.bundle,`${p.wire_id} | ${p.protocol}`,2,rows[2]++,'bundle');addNode(dc,p.destination_connector,`${p.destination_project} | pin ${p.destination_connector_pin}`,3,rows[3]++,'connector');addNode(d,p.destination_reference||'Unresolved endpoint',`${p.destination_project} | ${p.destination_pin} ${p.destination_function}`,4,rows[4]++,'endpoint');addEdge(p,s,sc,p.bundle);addEdge(p,sc,b,p.bundle);addEdge(p,b,dc,p.bundle);addEdge(p,dc,d,p.bundle)})}else{DATA.links.forEach(l=>{let s=`sc:${l.source.project}:${l.source.connector}`,b=`b:${l.bundle||'Unbundled'}`,d=`dc:${l.destination.project}:${l.destination.connector}`;addNode(s,l.source.connector,`${l.source.project} | pin ${l.source.pin}`,1,rows[1]++,'connector');addNode(b,l.bundle||'Unbundled',l.wire_id,2,rows[2]++,'bundle');addNode(d,l.destination.connector,`${l.destination.project} | pin ${l.destination.pin}`,3,rows[3]++,'connector');addEdge(l,s,b,l.bundle||'Unbundled');addEdge(l,b,d,l.bundle||'Unbundled')})}['Source IC / peripheral','Source connector','Harness bundle','Destination connector','Destination IC / peripheral'].forEach((t,i)=>{let x=document.createElementNS(NS,'text');x.classList.add('stage');x.setAttribute('x',25+i*300);x.setAttribute('y',28);x.textContent=t;scene.append(x)});fit()}
function showDetail(p){let fields=['path_id','protocol','status','confidence','source_project','source_reference','source_value','source_pin','source_function','source_net','source_connector','source_connector_pin','wire_id','bundle','destination_connector','destination_connector_pin','destination_project','destination_reference','destination_value','destination_pin','destination_function','destination_net','inline_components','board_net_sequence','ordered_path','notes'];detail.innerHTML='<div class="detail-title">'+esc(p.path_id||p.wire_id||'Harness path')+'</div><div class="kv">'+fields.filter(k=>p[k]).map(k=>'<div>'+esc(k.replaceAll('_',' '))+'</div><div>'+esc(p[k])+'</div>').join('')+'</div>'}
function transform(){scene.setAttribute('transform',`translate(${pan.x} ${pan.y}) scale(${scale})`)}function fit(){let b=scene.getBBox(),w=svg.clientWidth,h=svg.clientHeight;scale=Math.min((w-50)/Math.max(b.width,1),(h-50)/Math.max(b.height,1),1.3);pan={x:(w-b.width*scale)/2-b.x*scale,y:(h-b.height*scale)/2-b.y*scale};transform()}document.getElementById('fit').onclick=fit;document.getElementById('zoomIn').onclick=()=>{scale=Math.min(4,scale*1.2);transform()};document.getElementById('zoomOut').onclick=()=>{scale=Math.max(.2,scale/1.2);transform()};svg.addEventListener('wheel',e=>{e.preventDefault();let r=svg.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top,old=scale;scale=Math.max(.2,Math.min(4,scale*(e.deltaY<0?1.12:.89)));pan.x=mx-(mx-pan.x)*scale/old;pan.y=my-(my-pan.y)*scale/old;transform()},{passive:false});svg.addEventListener('pointerdown',e=>{if(e.target===svg)drag={pan:true,x:e.clientX,y:e.clientY}});svg.addEventListener('pointermove',e=>{if(!drag?.pan)return;pan.x+=e.clientX-drag.x;pan.y+=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;transform()});svg.addEventListener('pointerup',()=>drag=null);
function filter(){let bundle=document.getElementById('bundleFilter').value,status=document.getElementById('statusFilter').value.toLowerCase(),query=document.getElementById('search').value.toLowerCase();edges.forEach(x=>{let keep=(!bundle||x.element.dataset.bundle===bundle)&&(!status||x.element.dataset.status.toLowerCase()===status)&&(!query||x.element.dataset.search.includes(query));x.element.classList.toggle('hidden',!keep)});nodes.forEach(n=>{let connected=edges.some(e=>!e.element.classList.contains('hidden')&&(e.from===n.dataset.key||e.to===n.dataset.key));n.classList.toggle('dim',!connected)})}['bundleFilter','statusFilter','search'].forEach(x=>document.getElementById(x).addEventListener('input',filter));document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab,.pane').forEach(x=>x.classList.remove('active'));t.classList.add('active');document.getElementById(t.dataset.pane).classList.add('active')});document.querySelectorAll('th').forEach(th=>{th.title='Sort this column';th.addEventListener('click',()=>{let table=th.closest('table'),body=table.tBodies[0],column=[...th.parentElement.children].indexOf(th),ascending=th.dataset.order!=='asc';let rows=[...body.rows].sort((a,b)=>a.cells[column].textContent.localeCompare(b.cells[column].textContent,undefined,{numeric:true,sensitivity:'base'})*(ascending?1:-1));rows.forEach(row=>body.append(row));th.parentElement.querySelectorAll('th').forEach(item=>delete item.dataset.order);th.dataset.order=ascending?'asc':'desc'})});window.addEventListener('resize',fit);build();
</script></body></html>'''
    replacements = {
        "__TITLE__": escape(title), "__PATHCOUNT__": str(len(system_paths)),
        "__WIRECOUNT__": str(len(links)), "__BUNDLECOUNT__": str(len(bundle_rows)),
        "__PATHTABLE__": _table(path_rows, "pathTable"), "__WIRETABLE__": _table(wire_rows, "wireTable"),
        "__BUNDLETABLE__": _table(bundle_rows, "bundleTable"), "__BOMTABLE__": _table(bom_rows, "bomTable"),
        "__FINDINGTABLE__": _table(findings, "findingTable"), "__DATA__": payload,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template
