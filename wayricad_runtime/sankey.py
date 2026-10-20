"""Dependency-free, offline power-flow diagrams for analysis review.

Values are watts, never inferred from geometry or normalized to hide a balance
error. A single linear scale is used for every ribbon in a directed acyclic
graph. Tiny flows retain their real width; labels and the table retain values.
"""
from __future__ import annotations

from collections import deque
from html import escape
import math
import uuid


def layout_sankey(nodes, links):
    """Validate and lay out ID/label nodes and source/target/value links in W.

    Returns independent layout records. Negative, nonfinite, cyclic and dangling
    flows are rejected. Empty graphs and zero-power nodes are valid evidence.
    Nonconservation is retained in the incoming/outgoing totals, not repaired.
    """
    if len(nodes) > 500 or len(links) > 2000:
        raise ValueError('Sankey exceeds 500 nodes or 2,000 flows; summarize the study first.')
    records = {}
    for item in nodes:
        ident = item['id']
        if not isinstance(ident, str) or not ident or ident in records:
            raise ValueError('Sankey node IDs must be unique nonempty strings.')
        records[ident] = dict(id=ident, label=str(item['label']), incoming=0.0,
                              outgoing=0.0, level=0)
    edges, degree = [], dict.fromkeys(records, 0)
    followers = {ident: [] for ident in records}
    for item in links:
        source, target, raw = item['source'], item['target'], item['value']
        if source not in records or target not in records:
            raise ValueError('Sankey flow refers to an unknown node.')
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError('Sankey power must be a finite nonnegative number in W.')
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError('Sankey power must be finite and nonnegative in W.')
        edges.append(dict(source=source, target=target, value=value))
        records[source]['outgoing'] += value
        records[target]['incoming'] += value
        followers[source].append(target)
        degree[target] += 1
    pending = deque(ident for ident in records if degree[ident] == 0)
    visited = 0
    while pending:
        ident = pending.popleft()
        visited += 1
        for target in followers[ident]:
            records[target]['level'] = max(records[target]['level'], records[ident]['level']+1)
            degree[target] -= 1
            if degree[target] == 0:
                pending.append(target)
    if visited != len(records):
        raise ValueError('Sankey flows must form a directed acyclic graph.')
    columns = {}
    for node in records.values():
        node['power'] = max(node['incoming'], node['outgoing'])
        if not math.isfinite(node['power']):
            raise ValueError('Sankey total power exceeds the finite numeric range.')
        columns.setdefault(node['level'], []).append(node)
    height = max(360, max((len(column) for column in columns.values()), default=0)*46+60)
    width = max(960, (len(columns)-1)*340+300)
    # Reserve a readable label row independently of ribbon width. The reserve
    # is node padding, not extra power; all links share the same W-to-pixel scale.
    reference = max((node['power'] for node in records.values()), default=0.0) or 1.0
    scales = []
    for column in columns.values():
        total = math.fsum(node['power']/reference for node in column)
        if total:
            scales.append((height-60-len(column)*26-(len(column)-1)*16)/total)
    scale = min(scales, default=1.0)
    last_level = max(columns, default=1)
    for level, column in columns.items():
        occupied = sum(node['power']/reference*scale+26 for node in column)+(len(column)-1)*16
        y = (height-occupied)/2
        for node in column:
            node.update(x=24+level*(width-300)/max(1, last_level), y=y,
                        height=node['power']/reference*scale+26)
            y += node['height']+16
    offsets_in, offsets_out = dict.fromkeys(records, 0.0), dict.fromkeys(records, 0.0)
    for edge in edges:
        source, target = records[edge['source']], records[edge['target']]
        thickness = edge['value']/reference*scale
        edge.update(x1=source['x']+16, x2=target['x'], thickness=thickness,
                    y1=source['y']+13+offsets_out[source['id']],
                    y2=target['y']+13+offsets_in[target['id']])
        offsets_out[source['id']] += thickness
        offsets_in[target['id']] += thickness
    return dict(nodes=list(records.values()), links=edges, width=width, height=height,
                watts_reference=reference, pixels_per_reference=scale)


def _watts(value):
    return format(value, '.8g')+' W'


def sankey_svg(title, layout):
    """Return a static SVG; hover titles also work when JavaScript is disabled."""
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="'+escape(title, quote=True)+
             '" viewBox="0 0 '+str(layout['width'])+' '+str(layout['height'])+
             '" style="display:block;width:100%;min-width:900px;background:#f6f8fa;color:#182b3a">',
             '<title>'+escape(title)+'</title>',
             '<rect width="100%" height="100%" fill="#f6f8fa"/>']
    lookup = {node['id']: node for node in layout['nodes']}
    colors = ['#157f92', '#a85518', '#6752a0', '#297d45', '#ad4365', '#436bb0']
    for index, edge in enumerate(layout['links']):
        if not edge['value']:
            continue
        label = lookup[edge['source']]['label']+' → '+lookup[edge['target']]['label']+': '+_watts(edge['value'])
        x1, x2, y1, y2, thick = (edge[key] for key in ('x1', 'x2', 'y1', 'y2', 'thickness'))
        mid = (x1+x2)/2
        path = f'M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2} L{x2},{y2+thick} C{mid},{y2+thick} {mid},{y1+thick} {x1},{y1+thick} Z'
        parts.append('<path tabindex="0" role="button" data-probe="'+escape(label, quote=True)+
                     '" aria-label="'+escape(label, quote=True)+'" d="'+path+'" fill="'+colors[index % len(colors)]+
                     '" fill-opacity="0.55"><title>'+escape(label)+'</title></path>')
    for node in layout['nodes']:
        label = node['label']+' | In '+_watts(node['incoming'])+' | Out '+_watts(node['outgoing'])
        x, y, height = node['x'], node['y'], node['height']
        parts.append(f'<rect x="{x}" y="{y}" width="16" height="{height}" fill="#203f50" tabindex="0" role="button" data-probe="'+
                     escape(label, quote=True)+'" aria-label="'+escape(label, quote=True)+'"><title>'+escape(label)+'</title></rect>')
        short = node['label'] if len(node['label']) <= 32 else node['label'][:29]+'…'
        parts.append(f'<rect x="{x+20}" y="{y-1}" width="250" height="34" rx="3" fill="#f6f8fa" fill-opacity="0.96" pointer-events="none"/>')
        parts.append(f'<text x="{x+23}" y="{y+13}" fill="#182b3a" font-family="sans-serif" font-size="12">'+
                     escape(short)+f'<tspan x="{x+23}" dy="15">'+_watts(node['power'])+'</tspan><title>'+escape(label)+'</title></text>')
    return ''.join(parts)+'</svg>'


def sankey_html(title, nodes, links, note=''):
    """Embed an offline left-to-right Sankey, exact-value table and pin probes.

    No external scripts, fonts, plotting packages or network requests are used.
    Labels and notes are escaped, including component/net names from the PCB.
    """
    layout = layout_sankey(nodes, links)
    ident = 'sankey-'+uuid.uuid4().hex
    lookup = {node['id']: node for node in layout['nodes']}
    rows = ''.join('<tr><td>'+escape(lookup[edge['source']]['label'])+'</td><td>'+
                   escape(lookup[edge['target']]['label'])+'</td><td>'+_watts(edge['value'])+'</td></tr>'
                   for edge in layout['links'])
    empty = '<p>No quantified power flows are available for this result.</p>' if not any(edge['value'] for edge in layout['links']) else ''
    return ('<section class="power-sankey" id="'+ident+'"><h2>'+escape(title)+'</h2><p>'+escape(note)+
            '</p><p>Left → right. Ribbon widths use one linear power scale in watts. Hover or focus for values; click or press Enter to pin a probe. Labels include padding for readability.</p>'+empty+
            '<style>.power-sankey [data-probe]{cursor:crosshair}.power-sankey [data-probe]:focus,.power-sankey [data-probe]:hover{outline:2px solid #b26000;fill-opacity:0.9}.power-sankey .sankey-scroll{overflow:auto;max-height:75vh;border:1px solid #8c9ba5}.power-sankey output{display:block;min-height:1.6em}@media print{.power-sankey .sankey-scroll{max-height:none;overflow:visible}.power-sankey svg{min-width:0!important}}</style>'+
            '<div class="sankey-scroll">'+sankey_svg(title, layout)+'</div><output aria-live="polite">No probe</output>'+
            '<button type="button" data-clear-probes>Clear probes</button><ol data-probes></ol>'+
            '<details><summary>Exact power flows</summary><table><tr><th>From</th><th>To</th><th>Power</th></tr>'+rows+'</table></details>'+
            '<script>(()=>{const host=document.getElementById("'+ident+'"),out=host.querySelector("output"),list=host.querySelector("[data-probes]");'
            'host.querySelectorAll("[data-probe]").forEach(item=>{const value=item.dataset.probe;item.addEventListener("pointerenter",()=>out.textContent=value);'
            'item.addEventListener("focus",()=>out.textContent=value);const pin=()=>{const li=document.createElement("li");li.textContent=value;list.append(li);out.textContent=value;};'
            'item.addEventListener("click",pin);item.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();pin();}});});'
            'host.querySelector("[data-clear-probes]").onclick=()=>{list.replaceChildren();out.textContent="No probe";};})();</script></section>')
