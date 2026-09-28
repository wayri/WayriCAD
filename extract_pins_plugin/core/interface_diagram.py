"""Selected-pin interface diagrams backed by exact extracted net membership.

The renderer never turns a label, nearby pad, or similarly named net into an
electrical connection. A net in this report means only the pins present in the
supplied extraction snapshot; other board endpoints may exist.
"""

from __future__ import annotations

from collections import defaultdict
from fnmatch import fnmatchcase
from hashlib import sha1
from html import escape
import re
from typing import Any, Mapping


_COLORS = ("#5dd6ad", "#efad56", "#72c7e8", "#dc7bb2", "#aa9ae8", "#bad35d", "#e18c77")
_PROTOCOLS = ("USB", "CAN", "ETH", "RGMII", "MII", "MDIO", "DDR", "SPI", "I2C", "I3C", "UART", "QSPI", "PCIe", "HDMI", "CSI", "GPIO", "JTAG", "SWD")


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _e(value: Any) -> str:
    return escape(_s(value), quote=True)


def _natural(value: Any) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", _s(value)))


def _protocol(net: str, functions: list[str], overrides: Mapping[str, str] | None) -> tuple[str, bool]:
    for pattern, label in (overrides or {}).items():
        if fnmatchcase(net.casefold(), _s(pattern).casefold()):
            return _s(label).strip() or "Other", False
    haystack = " ".join([net, *functions]).upper()
    for label in _PROTOCOLS:
        if re.search(r"(?<![A-Z])" + re.escape(label.upper()) + r"(?![A-Z])", haystack):
            return label, True
    return "Other", True


def interface_net_rows(
    data: Mapping[str, Mapping[str, Any]], *, protocol_overrides: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Return selected endpoints per exact nonempty net; no pairwise inference.

    Every entry has ``net``, ``endpoints`` ({reference, pad, function}),
    ``protocol`` and ``protocol_inferred``. Nets with one selected endpoint are
    retained in the table, but no connection line is drawn for them.
    """
    by_net: dict[str, list[dict[str, str]]] = defaultdict(list)
    for ref in sorted(data, key=_natural):
        component = data[ref]
        for pin in sorted(component.get("pins", []), key=lambda p: _natural(p.get("Pad Name/Number", ""))):
            net = _s(pin.get("Net Name", "")).strip()
            if not net or net.upper() in ("NC", "N/C", "UNCONNECTED"):
                continue
            by_net[net].append({
                "reference": _s(ref),
                "pad": _s(pin.get("Pad Name/Number", "")),
                "function": _s(pin.get("Pin Function", "")),
            })
    rows = []
    for net in sorted(by_net, key=_natural):
        endpoints = by_net[net]
        protocol, inferred = _protocol(net, [p["function"] for p in endpoints], protocol_overrides)
        rows.append({"net": net, "endpoints": endpoints, "protocol": protocol, "protocol_inferred": inferred})
    return rows


def _layout(data: Mapping[str, Mapping[str, Any]], center_ref: str | None) -> tuple[dict[str, dict[str, Any]], int]:
    refs = sorted(data, key=_natural)
    if center_ref is not None and center_ref not in data:
        raise ValueError("Center component is not in the selected extraction")
    center = center_ref or next((ref for ref in refs if ref.upper().startswith("U")), refs[0] if refs else "")
    sides: dict[str, list[str]] = {"left": [], "center": [], "right": []}
    for ref in refs:
        if ref == center:
            sides["center"].append(ref)
        elif ref.upper().startswith(("J", "P", "X")):
            sides["left"].append(ref)
        else:
            sides["right"].append(ref)
    if not sides["left"] and len(sides["right"]) > 1:
        sides["left"].append(sides["right"].pop(0))
    placed: dict[str, dict[str, Any]] = {}
    for side, x in (("left", 28), ("center", 460), ("right", 892)):
        y = 92
        for ref in sides[side]:
            pins = sorted(data[ref].get("pins", []), key=lambda p: _natural(p.get("Pad Name/Number", "")))
            height = max(104, 75 + len(pins) * 23)
            placed[ref] = {"x": x, "y": y, "height": height, "side": side, "pins": pins}
            y += height + 28
    return placed, max(360, *(int(card["y"] + card["height"] + 40) for card in placed.values())) if placed else 360


def _color(label: str) -> str:
    return _COLORS[int.from_bytes(sha1(label.encode("utf-8")).digest()[:2], "big") % len(_COLORS)]


def render_interface_svg(
    data: Mapping[str, Mapping[str, Any]], *, center_ref: str | None = None,
    protocol_overrides: Mapping[str, str] | None = None, title: str | None = None,
) -> str:
    """Draw a deterministic, scalable selected-component pin map as SVG.

    Components are arranged in three columns. For nets with multiple selected
    endpoints, each endpoint joins a single net hub. The hub is a diagram
    convention, not an assertion of copper topology or signal direction.
    """
    placed, height = _layout(data, center_ref)
    net_rows = interface_net_rows(data, protocol_overrides=protocol_overrides)
    net_sides = {
        row["net"]: {placed[p["reference"]]["side"] for p in row["endpoints"] if p["reference"] in placed}
        for row in net_rows
    }
    points: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    row_points: dict[tuple[str, int], tuple[int, int]] = {}
    for ref, card in placed.items():
        for index, pin in enumerate(card["pins"]):
            pad = _s(pin.get("Pad Name/Number", ""))
            # Both sides of the center card are visually available; lines join
            # at a shared hub, so a repeated pad ID is still one endpoint.
            if card["side"] == "left":
                x = card["x"] + 344
            elif card["side"] == "right":
                x = card["x"]
            else:
                x = card["x"] if "left" in net_sides.get(_s(pin.get("Net Name", "")).strip(), set()) else card["x"] + 344
            point = (x, card["y"] + 69 + index * 23)
            points[(ref, pad)].append(point)
            row_points[(ref, index)] = point
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1264 {height}" role="img" '
        f'aria-label="{_e(title or "Selected pin-to-pin interface map")}">',
        '<style>.bg{fill:#111923}.card{fill:#1c2935;stroke:#42576b;stroke-width:1.5}.center{fill:#192434;stroke:#67bac1;stroke-width:2}.head{fill:#f2f6fb;font:700 17px Segoe UI,Arial,sans-serif}.sub{fill:#aabdc9;font:12px Segoe UI,Arial,sans-serif}.pin{fill:#dbe8ef;font:12px Consolas,monospace}.netlabel{fill:#e2edf2;font:10px Consolas,monospace}.wire{fill:none;stroke-width:2;stroke-opacity:.86}.node{stroke:#111923;stroke-width:2}.net-row:hover .wire,.pin-node:hover .node{stroke-width:4;stroke-opacity:1}.note{fill:#aabdc9;font:12px Segoe UI,Arial,sans-serif}</style>',
        f'<rect class="bg" width="1264" height="{height}" fill="#111923"/>',
        f'<text class="head" x="28" y="34" fill="#f2f6fb" font-family="Segoe UI,Arial,sans-serif" font-size="17" font-weight="700">{_e(title or "Pin-to-pin interface map")}</text>',
        '<text class="note" x="28" y="57" fill="#aabdc9" font-family="Segoe UI,Arial,sans-serif" font-size="12">Selected endpoints on exact matching nets · protocol labels inferred unless overridden · physical routing not shown</text>',
    ]
    # Draw links first so cards and pin labels stay readable. One net hub makes
    # fanout (including duplicate/shared nets) explicit without fake pair links.
    for row in net_rows:
        net = row["net"]
        endpoints = row["endpoints"]
        if len(endpoints) < 2:
            continue
        used: dict[tuple[str, str], int] = defaultdict(int)
        coords = []
        for endpoint in endpoints:
            key = (endpoint["reference"], endpoint["pad"])
            candidates = points.get(key, [])
            index = used[key]
            if index < len(candidates):
                coords.append(candidates[index])
                used[key] += 1
        if len(coords) < 2:
            continue
        # Keep the net hub in a corridor between cards so its native-preview
        # hit target remains visible even for left/center/right fanout.
        endpoint_sides = {placed[p["reference"]]["side"] for p in endpoints if p["reference"] in placed}
        hub_x = 416 if "left" in endpoint_sides else 850
        hub_y = sum(y for _, y in coords) // len(coords)
        color = _color(row["protocol"])
        parts.append(f'<g class="net-row" data-net="{_e(net)}" data-protocol="{_e(row["protocol"])}">')
        # Native preview hit-testing reads this immediate rect child. It is a
        # small visible hub control, not a full-lane overlay obscuring pins.
        parts.append(f'<rect x="{hub_x-9}" y="{hub_y-9}" width="18" height="18" rx="4" fill="{color}" fill-opacity="0.25"/>')
        parts.append(f'<title>{_e(net)} · {_e(row["protocol"])} · {len(coords)} selected pins</title>')
        for x, y in coords:
            mid_x = (x + hub_x) // 2
            parts.append(f'<path class="wire" fill="none" stroke="{color}" stroke-width="2" stroke-opacity="0.86" d="M{x},{y} C{mid_x},{y} {mid_x},{hub_y} {hub_x},{hub_y}"/>')
        parts.append(f'<circle class="node" cx="{hub_x}" cy="{hub_y}" r="5" fill="{color}" stroke="#111923" stroke-width="2"/>')
        parts.append(f'<text class="netlabel" x="{hub_x-38}" y="{hub_y-9}" fill="#e2edf2" font-family="Consolas,monospace" font-size="10">{_e(net[:12])}</text></g>')
    for ref in sorted(placed, key=lambda r: (placed[r]["side"], _natural(r))):
        card = placed[ref]
        x, y, h = card["x"], card["y"], card["height"]
        props = data[ref].get("general_properties", {})
        value = _s(props.get("Value", ""))
        is_center = card["side"] == "center"
        card_class = "center" if is_center else ""
        card_fill = "#192434" if is_center else "#1c2935"
        card_stroke = "#67bac1" if is_center else "#42576b"
        card_stroke_width = 2 if is_center else 1.5
        parts.extend([
            f'<g class="component" data-reference="{_e(ref)}">',
            f'<rect class="card {card_class}" x="{x}" y="{y}" width="344" height="{h}" rx="9" fill="{card_fill}" stroke="{card_stroke}" stroke-width="{card_stroke_width}"/>',
            f'<text class="head" x="{x+14}" y="{y+27}" fill="#f2f6fb" font-family="Segoe UI,Arial,sans-serif" font-size="17" font-weight="700">{_e(ref)}</text>',
            f'<text class="sub" x="{x+14}" y="{y+45}" fill="#aabdc9" font-family="Segoe UI,Arial,sans-serif" font-size="12">{_e(value[:45])}</text>',
        ])
        for index, pin in enumerate(card["pins"]):
            pad = _s(pin.get("Pad Name/Number", ""))
            net = _s(pin.get("Net Name", "")).strip()
            connected_net = "" if net.upper() in ("NC", "N/C", "UNCONNECTED") else net
            function = _s(pin.get("Pin Function", "")).strip()
            py = y + 69 + index * 23
            label = f'{pad}  {function or net or "NC"}'
            parts.append(f'<g class="pin-node" data-net="{_e(connected_net)}" data-reference="{_e(ref)}" data-pad="{_e(pad)}">'
                         f'<title>{_e(ref)}:{_e(pad)} · {_e(function)} · {_e(connected_net or "Unconnected")}</title>'
                         f'<text class="pin" x="{x+14}" y="{py+4}" fill="#dbe8ef" font-family="Consolas,monospace" font-size="12">{_e(label[:48])}</text>'
                         f'<circle class="node" cx="{row_points[(ref,index)][0]}" cy="{py}" r="3" fill="#78c9c1" stroke="#111923" stroke-width="2"/></g>')
        parts.append('</g>')
    if not placed:
        parts.append('<text class="note" x="28" y="112" fill="#aabdc9" font-family="Segoe UI,Arial,sans-serif" font-size="12">No selected components to draw.</text>')
    parts.append('</svg>')
    return "".join(parts)


def render_interface_html(
    data: Mapping[str, Mapping[str, Any]], *, center_ref: str | None = None,
    protocol_overrides: Mapping[str, str] | None = None, title: str | None = None,
) -> str:
    """Standalone offline diagram with net highlighting, filters, and pin table."""
    svg = render_interface_svg(data, center_ref=center_ref, protocol_overrides=protocol_overrides, title=title)
    net_rows = interface_net_rows(data, protocol_overrides=protocol_overrides)
    protocols = sorted({row["protocol"] for row in net_rows}, key=_natural)
    options = ''.join(f'<option value="{_e(p)}">{_e(p)}</option>' for p in protocols)
    rows = []
    for row in net_rows:
        endpoint_text = ", ".join(f'{p["reference"]}:{p["pad"]}' + (f' ({p["function"]})' if p["function"] else "") for p in row["endpoints"])
        coverage = "one selected endpoint" if len(row["endpoints"]) == 1 else f'{len(row["endpoints"])} selected endpoints'
        rows.append(f'<tr class="net-row" data-net="{_e(row["net"])}" data-protocol="{_e(row["protocol"])}" tabindex="0">'
                    f'<th scope="row">{_e(row["net"])}</th><td>{_e(row["protocol"])}'
                    f'{" (inferred)" if row["protocol_inferred"] else " (set by user)"}</td>'
                    f'<td>{_e(endpoint_text)}</td><td>{_e(coverage)}</td></tr>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + _e(title or "WayriCAD interface map") + '</title><style>'
            ':root{color-scheme:dark;font:15px Segoe UI,Arial,sans-serif;background:#101822;color:#eef5f8}'
            '*{box-sizing:border-box}body{margin:0}main{max-width:1500px;margin:auto;padding:24px}h1{margin:0 0 7px}'
            'p{color:#b9cad2;line-height:1.5}.tools{display:flex;flex-wrap:wrap;gap:10px;position:sticky;top:0;background:#101822;padding:12px 0;z-index:2}'
            'input,select,button{background:#233443;color:#eef5f8;border:1px solid #567086;border-radius:6px;padding:9px 12px;font:inherit}'
            'input{min-width:280px;flex:1}.diagram{max-height:66vh;overflow:auto;border:1px solid #42576b;border-radius:9px;background:#111923}'
            '.diagram svg{display:block;width:max(100%,950px);height:auto;min-width:950px}.active .wire{stroke-width:4;stroke-opacity:1}.active .node{stroke:#fff;stroke-width:3}'
            '.dim{opacity:.13}table{border-collapse:collapse;width:100%;margin:14px 0}th,td{text-align:left;border-bottom:1px solid #3c5365;padding:9px;vertical-align:top}'
            'thead{color:#8dd9d0}tbody tr{cursor:pointer}tbody tr:hover,.active-row{background:#254453}.muted{color:#b9cad2}'
            '@media print{.tools{display:none}.diagram{max-height:none;overflow:visible}body{background:white;color:black}p,.muted{color:#333}}'
            '</style></head><body><main><h1>' + _e(title or "WayriCAD pin-to-pin interface map") + '</h1>'
            '<p>Read-only map of selected extracted pins. Matching net names identify shared selected endpoints; the drawing does not establish signal direction, copper topology, or whether additional endpoints exist outside the selection. Protocol labels marked “inferred” are name/function hints, not verified electrical types.</p>'
            '<div class="tools"><input id="search" type="search" aria-label="Search nets and components" placeholder="Search net, component, pin, function…">'
            '<select id="protocol" aria-label="Filter protocol"><option value="">All protocols</option>' + options + '</select>'
            '<button id="clear" type="button">Clear selection</button><span id="status" aria-live="polite">No net selected</span></div>'
            '<div class="diagram">' + svg + '</div><h2>Exact selected-net endpoints</h2>'
            '<table><thead><tr><th scope="col">Net</th><th scope="col">Protocol</th><th scope="col">Selected pins</th><th scope="col">Coverage</th></tr></thead><tbody>'
            + (''.join(rows) or '<tr><td colspan="4" class="muted">No connected nets in the selected pins.</td></tr>')
            + '</tbody></table></main><script>'
            'const svg=document.querySelector(".diagram svg"), items=[...svg.querySelectorAll(".net-row,.pin-node")], rows=[...document.querySelectorAll("table .net-row")];'
            'const search=document.getElementById("search"), protocol=document.getElementById("protocol"), status=document.getElementById("status");let chosen="";'
            'function update(){const q=search.value.trim().toLocaleLowerCase(), p=protocol.value;'
            'rows.forEach(r=>{const ok=(!p||r.dataset.protocol===p)&&(!q||r.textContent.toLocaleLowerCase().includes(q));r.hidden=!ok;r.classList.toggle("active-row",!!chosen&&r.dataset.net===chosen)});'
            'items.forEach(el=>{const net=el.dataset.net||"", ref=el.dataset.reference||"", pad=el.dataset.pad||"";'
            'const ok=(!p||el.dataset.protocol===p||!el.dataset.protocol)&&(!q||(net+" "+ref+" "+pad+" "+el.textContent).toLocaleLowerCase().includes(q));'
            'el.classList.toggle("dim",!ok||!!chosen&&net!==chosen);el.classList.toggle("active",!!chosen&&net===chosen)});'
            'status.textContent=chosen?"Selected net: "+chosen:"No net selected"}'
            'document.addEventListener("click",ev=>{const target=ev.target.closest("[data-net]");if(target&&target.dataset.net){chosen=target.dataset.net;update()}});'
            'document.addEventListener("keydown",ev=>{if((ev.key==="Enter"||ev.key===" ")&&ev.target.matches(".net-row")){ev.preventDefault();chosen=ev.target.dataset.net;update()}});'
            'search.addEventListener("input",update);protocol.addEventListener("change",update);'
            'document.getElementById("clear").addEventListener("click",()=>{chosen="";update()});update();'
            '</script></body></html>')
