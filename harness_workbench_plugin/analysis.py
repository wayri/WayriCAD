"""Cross-project connector and cable mapping backend."""

from __future__ import annotations

import csv
import fnmatch
import math
import re
from html import escape
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass(frozen=True)
class PinRecord:
    project: str
    connector: str
    pin: str
    net: str
    function: str = ""
    voltage: str = ""
    connector_part: str = ""
    contact_part: str = ""
    endpoint_type: str = "board"
    load_a: float = 0.0


@dataclass
class HarnessLink:
    source: PinRecord
    destination: PinRecord
    wire_id: str
    gauge_awg: str = "24"
    pair: str = ""
    shield: str = ""
    status: str = "linked"
    bundle: str = ""
    splice: str = ""
    color: str = ""
    length_m: float = 1.0
    notes: str = ""


@dataclass(frozen=True)
class ConnectorRule:
    source_project: str
    source_connector: str
    destination_project: str
    destination_connector: str
    pin_offset: int = 0
    explicit_pin_map: tuple[tuple[str, str], ...] = ()
    rule_name: str = "Pin correspondence"


@dataclass(frozen=True)
class VirtualLoad:
    project: str
    reference: str
    pin: str
    net: str
    function: str = "External load"
    voltage: str = ""
    current_a: float = 0.0
    connector_part: str = ""


@dataclass
class HarnessBundle:
    name: str
    wire_ids: list[str] = field(default_factory=list)
    gauge_awg: str = "24"
    shield: str = ""
    sleeve: str = ""
    length_m: float = 1.0
    service_loop_percent: float = 10.0


@dataclass
class HarnessSplice:
    splice_id: str
    wire_ids: list[str] = field(default_factory=list)
    splice_type: str = "Crimp splice"
    location: str = ""
    part_number: str = ""


def load_pin_csv(path: str | Path, project: str = "") -> list[PinRecord]:
    source = Path(path)
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    records = []
    for row in rows:
        folded = {str(key).strip().casefold(): str(value or "").strip() for key, value in row.items()}
        records.append(PinRecord(
            project or folded.get("project", source.stem),
            folded.get("connector", folded.get("reference", folded.get("ref", ""))),
            folded.get("pin", folded.get("pad", "")),
            folded.get("net", folded.get("net name", "")),
            folded.get("function", folded.get("signal", "")),
            folded.get("voltage", ""),
            folded.get("connector part", folded.get("connector_part", folded.get("connector pn", ""))),
            folded.get("contact part", folded.get("contact_part", folded.get("terminal part", ""))),
            folded.get("endpoint type", "board"),
            _safe_float(folded.get("load a", folded.get("current a", "0"))),
        ))
    return [record for record in records if record.connector and record.pin]


def _safe_float(value: str | None) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def load_pin_documents(paths: list[str | Path], maximum_projects: int = 50) -> list[PinRecord]:
    """Load many board exports with deterministic de-duplication and a project cap."""
    records: dict[tuple[str, str, str, str], PinRecord] = {}
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() != ".csv":
            continue
        for record in load_pin_csv(path):
            records[(record.project, record.connector, record.pin, record.net)] = record
    projects = {record.project for record in records.values()}
    if len(projects) > maximum_projects:
        raise ValueError(f"Imported {len(projects)} projects; the configured limit is {maximum_projects}.")
    return sorted(records.values(), key=lambda item: (item.project.casefold(), item.connector.casefold(), _pin_key(item.pin), item.net.casefold()))


def discover_pin_documents(directory: str | Path, recursive: bool = True) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    return sorted(root.rglob("*.csv") if recursive else root.glob("*.csv"))


def virtual_load_records(loads: list[VirtualLoad]) -> list[PinRecord]:
    return [PinRecord(load.project, load.reference, load.pin, load.net, load.function,
                      load.voltage, load.connector_part, "", "virtual-load", load.current_a)
            for load in loads]


def connector_correspondence(records: list[PinRecord], rules: list[ConnectorRule]) -> list[HarnessLink]:
    """Link connectors in O(records + rules*pins), defaulting to pin N -> pin N."""
    index: dict[tuple[str, str], dict[str, PinRecord]] = {}
    for record in records:
        index.setdefault((record.project.casefold(), record.connector.casefold()), {})[record.pin.casefold()] = record
    links: list[HarnessLink] = []
    for rule in rules:
        source_pins = index.get((rule.source_project.casefold(), rule.source_connector.casefold()), {})
        destination_pins = index.get((rule.destination_project.casefold(), rule.destination_connector.casefold()), {})
        explicit = {source.casefold(): destination.casefold() for source, destination in rule.explicit_pin_map}
        for source_pin, source in sorted(source_pins.items(), key=lambda item: _pin_key(item[0])):
            destination_pin = explicit.get(source_pin)
            if destination_pin is None:
                try: destination_pin = str(int(source.pin) + rule.pin_offset).casefold()
                except ValueError: destination_pin = source_pin
            destination = destination_pins.get(destination_pin)
            status = "linked" if destination else "unmatched"
            if destination is None:
                destination = PinRecord(rule.destination_project, rule.destination_connector, destination_pin, "")
            links.append(HarnessLink(source, destination, f"W{len(links)+1:05d}", status=status,
                                     notes=rule.rule_name))
    return links


def parse_connector_rules(text: str) -> list[ConnectorRule]:
    """Parse `BOARD:J1 -> BOARD:J2 [offset=N] [map=1:3,2:4]` rules."""
    rules = []
    expression = re.compile(r"^\s*([^:]+):([^\s]+)\s*->\s*([^:]+):([^\s]+)(.*)$")
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"): continue
        match = expression.match(line)
        if not match: raise ValueError(f"Invalid connector rule on line {line_number}: {line}")
        source_project, source_connector, destination_project, destination_connector, options = match.groups()
        offset_match = re.search(r"offset\s*=\s*(-?\d+)", options, re.I)
        map_match = re.search(r"map\s*=\s*([^;\]]+)", options, re.I)
        pin_map = []
        if map_match:
            for pair in map_match.group(1).split(","):
                if ":" not in pair: continue
                source, destination = pair.split(":", 1); pin_map.append((source.strip(), destination.strip()))
        rules.append(ConnectorRule(source_project.strip(), source_connector.strip(),
                                   destination_project.strip(), destination_connector.strip(),
                                   int(offset_match.group(1)) if offset_match else 0, tuple(pin_map),
                                   f"Connector rule {line_number}"))
    return rules


def _pin_key(value: str):
    parts = re.split(r"(\d+)", str(value))
    return tuple(int(part) if part.isdigit() else part.casefold() for part in parts)


def _capture(pattern: str, value: str, regex: bool) -> str | None:
    if regex:
        match = re.fullmatch(pattern, value, flags=re.IGNORECASE)
        if not match: return None
        return match.groupdict().get("link", match.group(1) if match.groups() else match.group(0)).casefold()
    if not fnmatch.fnmatchcase(value.casefold(), pattern.casefold()): return None
    escaped = re.escape(pattern).replace(r"\*", "(.*)").replace(r"\?", "(.)")
    match = re.fullmatch(escaped, value, flags=re.IGNORECASE)
    return "|".join(match.groups()).casefold() if match and match.groups() else value.casefold()


def auto_link(sources: list[PinRecord], destinations: list[PinRecord], source_pattern: str = "*",
              destination_pattern: str = "*", regex: bool = False) -> list[HarnessLink]:
    source_keys = [(record, _capture(source_pattern, record.net, regex)) for record in sources]
    destination_keys = [(record, _capture(destination_pattern, record.net, regex)) for record in destinations]
    links = []
    for source, key in source_keys:
        if key is None: continue
        matches = [record for record, other_key in destination_keys if other_key == key]
        status = "linked" if len(matches) == 1 else "ambiguous" if matches else "unmatched"
        if not matches:
            placeholder = PinRecord("", "", "", source.net)
            links.append(HarnessLink(source, placeholder, f"W{len(links)+1:04d}", status=status))
        else:
            for destination in matches:
                links.append(HarnessLink(source, destination, f"W{len(links)+1:04d}", status=status))
    return links


def auto_link_multi(records: list[PinRecord], net_pattern: str = "*", regex: bool = False,
                    include_power: bool = False, max_links: int = 50000) -> list[HarnessLink]:
    """Index signals across many projects and link unique cross-connector peers."""
    buckets: dict[str, list[PinRecord]] = {}
    for record in records:
        if not record.net or (not include_power and _looks_power(record.net)): continue
        key = _capture(net_pattern, record.net, regex)
        if key is not None: buckets.setdefault(key, []).append(record)
    links=[]
    for key, endpoints in sorted(buckets.items()):
        unique=list({(e.project,e.connector,e.pin,e.net):e for e in endpoints}.values())
        candidates=[]
        for index,source in enumerate(unique):
            for destination in unique[index+1:]:
                if (source.project.casefold(),source.connector.casefold()) == (destination.project.casefold(),destination.connector.casefold()): continue
                candidates.append((source,destination))
        status="linked" if len(candidates)==1 else "ambiguous" if candidates else "unmatched"
        for source,destination in candidates:
            links.append(HarnessLink(source,destination,f"W{len(links)+1:05d}",status=status,notes=f"Indexed net match: {key}"))
            if len(links)>=max_links: raise ValueError(f"Automatic linking exceeded {max_links} wires. Narrow the net pattern or use connector rules.")
    return links


def _looks_power(net: str) -> bool:
    value=re.sub(r"[^A-Z0-9]","",net.upper())
    return bool(re.match(r"^(GND|AGND|DGND|PGND|VSS|VCC|VDD|VBAT|PWR|POWER|[0-9]+V[0-9]*)",value))


def validate_links(links: list[HarnessLink]) -> list[str]:
    issues = []
    destinations: dict[tuple[str, str, str], int] = {}
    for link in links:
        key = (link.destination.project, link.destination.connector, link.destination.pin)
        if all(key): destinations[key] = destinations.get(key, 0) + 1
        if link.source.voltage and link.destination.voltage and link.source.voltage != link.destination.voltage:
            issues.append(f"Voltage mismatch {link.source.voltage} -> {link.destination.voltage} on {link.wire_id}")
        if link.status != "linked": issues.append(f"{link.status.title()} mapping on {link.wire_id}: {link.source.net}")
    issues.extend(f"Multiple wires terminate at {project}:{connector}.{pin}" for (project, connector, pin), count in destinations.items() if count > 1)
    return issues


def export_csv(path: str | Path, links: list[HarnessLink]) -> None:
    fields = ["wire_id", "source_project", "source_connector", "source_pin", "source_net",
              "destination_project", "destination_connector", "destination_pin", "destination_net",
              "gauge_awg", "pair", "bundle", "splice", "shield", "color", "length_m", "status", "notes"]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for link in links:
            writer.writerow({"wire_id": link.wire_id, "source_project": link.source.project,
                             "source_connector": link.source.connector, "source_pin": link.source.pin,
                             "source_net": link.source.net, "destination_project": link.destination.project,
                             "destination_connector": link.destination.connector, "destination_pin": link.destination.pin,
                             "destination_net": link.destination.net, "gauge_awg": link.gauge_awg,
                             "pair": link.pair, "bundle": link.bundle, "splice": link.splice,
                             "shield": link.shield, "color": link.color, "length_m": f"{link.length_m:.3f}",
                             "status": link.status, "notes": link.notes})


def pin_map_rows(links: list[HarnessLink]) -> list[dict[str, str]]:
    return [{
        "Wire": link.wire_id,
        "Source": f"{link.source.project}:{link.source.connector}.{link.source.pin}",
        "Source Net": link.source.net,
        "Destination": f"{link.destination.project}:{link.destination.connector}.{link.destination.pin}",
        "Destination Net": link.destination.net,
        "Function": link.source.function or link.destination.function,
        "Bundle": link.bundle,
        "Splice": link.splice,
        "Status": link.status,
    } for link in links]


def net_map_rows(links: list[HarnessLink]) -> list[dict[str, str]]:
    groups: dict[str, dict[str, object]] = {}
    for link in links:
        key = link.source.net or link.destination.net or link.wire_id
        row = groups.setdefault(key, {"Net / Signal": key, "Endpoints": set(), "Wires": [], "Bundles": set(), "Loads (A)": 0.0})
        row["Endpoints"].update((f"{link.source.project}:{link.source.connector}.{link.source.pin}",
                                 f"{link.destination.project}:{link.destination.connector}.{link.destination.pin}"))
        row["Wires"].append(link.wire_id)
        if link.bundle: row["Bundles"].add(link.bundle)
        row["Loads (A)"] += max(link.source.load_a, link.destination.load_a)
    return [{"Net / Signal": str(row["Net / Signal"]), "Endpoints": "; ".join(sorted(row["Endpoints"])),
             "Wires": ", ".join(row["Wires"]), "Bundles": ", ".join(sorted(row["Bundles"])),
             "Loads (A)": f"{row['Loads (A)']:.3f}"} for row in groups.values()]


def apply_bundle(links: list[HarnessLink], bundle: HarnessBundle) -> None:
    targets = set(bundle.wire_ids)
    for link in links:
        if link.wire_id in targets:
            link.bundle = bundle.name; link.gauge_awg = bundle.gauge_awg
            link.shield = bundle.shield; link.length_m = bundle.length_m


def apply_splice(links: list[HarnessLink], splice: HarnessSplice) -> None:
    targets = set(splice.wire_ids)
    for link in links:
        if link.wire_id in targets: link.splice = splice.splice_id


def harness_bom(records: list[PinRecord], links: list[HarnessLink], bundles: list[HarnessBundle] = (),
                splices: list[HarnessSplice] = ()) -> list[dict[str, str]]:
    """Create a procurement-oriented aggregate without inventing missing part numbers."""
    rows: list[dict[str, str]] = []
    connectors: dict[str, set[tuple[str, str]]] = {}
    contacts: dict[str, int] = {}
    for record in records:
        connector_part = record.connector_part or "UNSPECIFIED CONNECTOR"
        connectors.setdefault(connector_part, set()).add((record.project, record.connector))
        contact_part = record.contact_part or f"UNSPECIFIED CONTACT AWG {next((l.gauge_awg for l in links if l.source == record or l.destination == record), 'TBD')}"
        contacts[contact_part] = contacts.get(contact_part, 0) + 1
    for part, instances in sorted(connectors.items()):
        rows.append({"Category":"Connector","Part Number":part,"Description":"Connector housing","Quantity":str(len(instances)),"Unit":"ea","Notes":"; ".join(f"{p}:{c}" for p,c in sorted(instances))})
    for part, count in sorted(contacts.items()):
        rows.append({"Category":"Contact","Part Number":part,"Description":"Crimp/contact terminal","Quantity":str(count),"Unit":"ea","Notes":"Verify plating and mating family"})
    wire_groups: dict[tuple[str, str], float] = {}
    for link in links:
        key=(link.gauge_awg or "TBD",link.color or "Unspecified")
        wire_groups[key]=wire_groups.get(key,0.0)+max(0.0,link.length_m)
    for (gauge,color),length in sorted(wire_groups.items()):
        rows.append({"Category":"Wire","Part Number":"TBD","Description":f"AWG {gauge}, {color}","Quantity":f"{length*1.10:.2f}","Unit":"m","Notes":"Includes 10% general cut allowance"})
    for bundle in bundles:
        rows.append({"Category":"Bundle","Part Number":"TBD","Description":bundle.sleeve or bundle.shield or "Harness bundle protection","Quantity":f"{bundle.length_m*(1+bundle.service_loop_percent/100):.2f}","Unit":"m","Notes":bundle.name})
    for splice in splices:
        rows.append({"Category":"Splice","Part Number":splice.part_number or "TBD","Description":splice.splice_type,"Quantity":"1","Unit":"ea","Notes":f"{splice.splice_id} {splice.location}".strip()})
    labels={link.bundle for link in links if link.bundle}
    if labels: rows.append({"Category":"Identification","Part Number":"TBD","Description":"Harness/bundle labels","Quantity":str(len(labels)),"Unit":"ea","Notes":", ".join(sorted(labels))})
    return rows


def export_rows(path: str | Path, rows: list[dict[str, str]]) -> None:
    if not rows: return
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def connector_graph(links: list[HarnessLink]) -> tuple[list[str], list[tuple[str, str, HarnessLink]]]:
    nodes=set();edges=[]
    for link in links:
        source=f"{link.source.project}:{link.source.connector}";destination=f"{link.destination.project}:{link.destination.connector}"
        nodes.update((source,destination));edges.append((source,destination,link))
    return sorted(nodes),edges


def universal_harness_svg(links: list[HarnessLink], title: str = "Universal Harness Architecture") -> str:
    nodes,edges=connector_graph(links);columns=max(2,math.ceil(math.sqrt(max(len(nodes),1))));rows=math.ceil(max(len(nodes),1)/columns);width=max(1200,columns*300);height=max(700,rows*190+100)
    positions={node:(160+(index%columns)*300,100+(index//columns)*190) for index,node in enumerate(nodes)}
    bundle_colors={name:color for name,color in zip(sorted({l.bundle or "Unbundled" for l in links}),("#237c73","#d15b45","#5577aa","#8d62a8","#d39b32","#3c8d56","#b84d72"))}
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">','<rect width="100%" height="100%" fill="#f6f8fa"/>',f'<text x="30" y="38" font-family="Segoe UI" font-size="24" font-weight="bold" fill="#263744">{escape(title)}</text>','<g fill="none" stroke-linecap="round">']
    grouped:dict[tuple[str,str],list[HarnessLink]]={}
    for source,destination,link in edges:grouped.setdefault((source,destination),[]).append(link)
    for (source,destination),group in grouped.items():
        x1,y1=positions[source];x2,y2=positions[destination]
        for index,link in enumerate(group):
            offset=(index-(len(group)-1)/2)*3;color=bundle_colors[link.bundle or "Unbundled"];lines.append(f'<path d="M{x1+105} {y1+offset} C {(x1+x2)/2} {y1+offset}, {(x1+x2)/2} {y2+offset}, {x2-105} {y2+offset}" stroke="{color}" stroke-width="2"><title>{escape(link.wire_id)} {escape(link.source.net)} {escape(link.gauge_awg)} AWG</title></path>')
    lines.append('</g>')
    for node,(x,y) in positions.items():
        project,connector=node.split(":",1);pin_count=sum(1 for l in links if node in (f"{l.source.project}:{l.source.connector}",f"{l.destination.project}:{l.destination.connector}"));lines.extend([f'<g><rect x="{x-105}" y="{y-42}" width="210" height="84" rx="6" fill="#ffffff" stroke="#4c6475" stroke-width="2"/>',f'<text x="{x-92}" y="{y-12}" font-family="Segoe UI" font-size="15" font-weight="bold" fill="#263744">{escape(connector)}</text>',f'<text x="{x-92}" y="{y+10}" font-family="Segoe UI" font-size="12" fill="#52616b">{escape(project)}</text>',f'<text x="{x-92}" y="{y+29}" font-family="Segoe UI" font-size="11" fill="#52616b">{pin_count} mapped wire(s)</text></g>'])
    lines.append('</svg>');return "\n".join(lines)


def harness_svg(links: list[HarnessLink]) -> str:
    row_height = 34; height = max(180, 90 + row_height * len(links)); width = 1200
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#f7f9fb"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#17202a}.h{font-size:18px;font-weight:bold}.p{font-size:12px}.w{font-size:11px}</style>',
             '<text class="h" x="35" y="35">Source connector pins</text><text class="h" x="930" y="35">Destination connector pins</text>']
    colors = {"linked": "#2e8b57", "ambiguous": "#d9822b", "unmatched": "#c23b53"}
    for index, link in enumerate(links):
        y = 70 + index * row_height; color = colors.get(link.status, "#607d8b")
        source = f"{link.source.project} {link.source.connector}.{link.source.pin}  {link.source.net}"
        destination = f"{link.destination.project} {link.destination.connector}.{link.destination.pin}  {link.destination.net}" if link.destination.connector else "UNRESOLVED"
        lines.extend([f'<text class="p" x="35" y="{y+4}">{escape(source)}</text>',
                      f'<text class="p" x="930" y="{y+4}">{escape(destination)}</text>',
                      f'<path d="M 340 {y} C 560 {y-12}, 650 {y+12}, 910 {y}" fill="none" stroke="{color}" stroke-width="3"/>',
                      f'<text class="w" x="570" y="{y-7}">{escape(link.wire_id)} AWG {escape(link.gauge_awg)} {escape(link.pair)} {escape(link.shield)}</text>'])
    lines.append('</svg>')
    return "\n".join(lines)
