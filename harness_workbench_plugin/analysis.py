"""Cross-project connector and cable mapping backend."""

from __future__ import annotations

import csv
import fnmatch
import re
from html import escape
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class PinRecord:
    project: str
    connector: str
    pin: str
    net: str
    function: str = ""
    voltage: str = ""


@dataclass
class HarnessLink:
    source: PinRecord
    destination: PinRecord
    wire_id: str
    gauge_awg: str = "24"
    pair: str = ""
    shield: str = ""
    status: str = "linked"


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
        ))
    return [record for record in records if record.connector and record.pin]


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
              "gauge_awg", "pair", "shield", "status"]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for link in links:
            writer.writerow({"wire_id": link.wire_id, "source_project": link.source.project,
                             "source_connector": link.source.connector, "source_pin": link.source.pin,
                             "source_net": link.source.net, "destination_project": link.destination.project,
                             "destination_connector": link.destination.connector, "destination_pin": link.destination.pin,
                             "destination_net": link.destination.net, "gauge_awg": link.gauge_awg,
                             "pair": link.pair, "shield": link.shield, "status": link.status})


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
