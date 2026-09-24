"""Offline connector and selected-component pin report.

The diagram is a pin-order view, not an inferred electrical schematic or a
claim that the illustrated rows reproduce physical pad placement.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape
from typing import Any, Mapping


def _text(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def _pin_key(value: Any) -> tuple[int, str]:
    text = str(value)
    return (0, text.zfill(12)) if text.isdigit() else (1, text.lower())


def common_net_rows(data: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """List nets that connect at least two distinct extracted components."""
    by_net: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ref, component in data.items():
        for pin in component.get("pins", []):
            net = str(pin.get("Net Name", "")).strip()
            if net:
                by_net[net].append((str(ref), str(pin.get("Pad Name/Number", ""))))
    return [
        {"net": net, "endpoints": sorted(endpoints, key=lambda item: (item[0].lower(), _pin_key(item[1]))),
         "component_count": len({ref for ref, _pad in endpoints})}
        for net, endpoints in sorted(by_net.items(), key=lambda item: item[0].lower())
        if len({ref for ref, _pad in endpoints}) >= 2
    ]


def _dimension(footprint: Any) -> str:
    if footprint is None:
        return "Footprint dimensions unavailable"
    try:
        box = footprint.GetBoundingBox()
        width = float(box.GetWidth()) / 1_000_000
        height = float(box.GetHeight()) / 1_000_000
        if width > 0 and height > 0:
            return f"Footprint bounding box: {width:.2f} × {height:.2f} mm"
    except (AttributeError, TypeError, ValueError, RuntimeError):
        pass
    return "Footprint dimensions unavailable"


def render_connector_report(
    data: Mapping[str, Mapping[str, Any]],
    footprints: Mapping[str, Any] | None = None,
) -> str:
    """Build a self-contained HTML preview with cross-highlighting by net."""
    footprints = footprints or {}
    cards = []
    total_pins = 0
    for ref, component in data.items():
        props = component.get("general_properties", {})
        pins = sorted(component.get("pins", []), key=lambda pin: _pin_key(pin.get("Pad Name/Number", "")))
        total_pins += len(pins)
        rows = []
        for pin in pins:
            number = str(pin.get("Pad Name/Number", ""))
            net = str(pin.get("Net Name", ""))
            is_pin_one = number == "1"
            rows.append(
                '<tr class="pin-row" data-net="' + _text(net) + '">'
                '<th scope="row"><span class="pin-number">' + _text(number) + '</span>'
                + ('<span class="pin-one" title="Pin 1">● PIN 1</span>' if is_pin_one else '')
                + '</th><td>' + (_text(pin.get("Pin Function", "")) or '<span class="muted">—</span>')
                + '</td><td class="net-name">' + (_text(net) or '<span class="muted">Unconnected</span>')
                + '</td><td>' + _text(pin.get("Net Type", "")) + '</td></tr>'
            )
        cards.append(
            '<section class="connector" id="component-' + _text(ref) + '">'
            '<header><div><span class="eyebrow">Extracted component</span><h2>' + _text(ref) + '</h2>'
            '<p class="value">' + _text(props.get("Value", "")) + '</p></div>'
            '<div class="measure"><strong>' + _text(_dimension(footprints.get(ref))) + '</strong>'
            '<span>' + _text(props.get("Layer", "")) + ' · ' + _text(props.get("Position", "")) + '</span></div></header>'
            '<p class="diagram-note">Pin-order view; row spacing does not represent physical pad pitch.</p>'
            '<table><thead><tr><th>Pin / pad</th><th>Pin function</th><th>Net name</th><th>Type</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></section>'
        )
    shared_rows = []
    for entry in common_net_rows(data):
        shared_rows.append(
            '<tr class="pin-row" data-net="' + _text(entry["net"]) + '"><th scope="row">'
            + _text(entry["net"]) + '</th><td>' + str(entry["component_count"])
            + '</td><td>' + _text(', '.join(f'{ref}:{pad}' for ref, pad in entry["endpoints"])) + '</td></tr>'
        )
    shared = ''.join(shared_rows) or '<tr><td colspan="3" class="muted">No nets shared by two or more extracted components.</td></tr>'
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WayriCAD pin and connector report</title><style>
:root{font-family:Segoe UI,Arial,sans-serif;color-scheme:light dark;--bg:#101921;--panel:#1c2a34;--line:#406071;--text:#eff7fa;--muted:#abc0cb;--accent:#73d3c6;--selected:#315c60}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}main{max-width:1250px;margin:auto;padding:24px}h1{font-size:2rem;margin:0 0 6px}h2{font-size:1.8rem;margin:0}.muted,.diagram-note,.measure span{color:var(--muted)}.lead{margin:0 0 22px;color:var(--muted)}
.toolbar{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap}input{padding:10px 12px;background:var(--panel);border:1px solid var(--line);border-radius:6px;color:var(--text);min-width:240px;flex:1}button{padding:10px 14px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--text);cursor:pointer}button:hover,tr.pin-row:hover{background:var(--selected)}
.connector,.shared{margin:22px 0;padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:10px}.connector header{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.eyebrow{text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-size:.75rem;font-weight:700}.value{margin:4px 0 0;font-size:1.1rem}.measure{text-align:right;display:flex;flex-direction:column;gap:5px}table{border-collapse:collapse;width:100%;margin-top:14px}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line)}thead{color:var(--accent)}.pin-row{cursor:pointer}.pin-number{font-size:1.2rem;font-weight:700}.pin-one{color:#ffd28a;font-size:.76rem;font-weight:800;margin-left:12px}.net-name{font-weight:600}.active{background:var(--selected)!important;outline:2px solid var(--accent);outline-offset:-2px}.hidden{display:none}.empty{padding:30px;text-align:center;color:var(--muted)}
@media print{.toolbar{display:none}body{background:white;color:black}.connector,.shared{break-inside:avoid;background:white;border-color:#777}.muted,.diagram-note,.measure span{color:#444}}
</style></head><body><main><h1>Pin and connector report</h1><p class="lead">''' + str(len(data)) + ''' components · ''' + str(total_pins) + ''' pin rows. Click a net to highlight every matching extracted pin.</p>
<div class="toolbar"><input id="search" type="search" placeholder="Find reference, pad or net" aria-label="Find reference, pad or net"><button id="clear" type="button">Clear highlight</button><span id="selected-net" aria-live="polite">No net selected</span></div>
<section class="shared"><h2>Common nets</h2><p class="muted">Nets present on at least two extracted components.</p><table><thead><tr><th>Net</th><th>Components</th><th>Reference:pin endpoints</th></tr></thead><tbody>''' + shared + '''</tbody></table></section>
''' + (''.join(cards) or '<p class="empty">No extracted components match this preview.</p>') + '''</main><script>
const rows=[...document.querySelectorAll('.pin-row')];const status=document.getElementById('selected-net');
function selectNet(net){rows.forEach(r=>r.classList.toggle('active',!!net&&r.dataset.net===net));status.textContent=net?'Net: '+net:'No net selected'}
rows.forEach(r=>r.addEventListener('click',()=>selectNet(r.dataset.net)));
document.getElementById('clear').addEventListener('click',()=>selectNet(''));
document.getElementById('search').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();document.querySelectorAll('.connector').forEach(card=>card.classList.toggle('hidden',!!q&&!card.textContent.toLowerCase().includes(q)));});
</script></body></html>'''
