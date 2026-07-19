"""Cross-project pin-document import, matching, and harness visualization."""

from __future__ import annotations

import csv
import html
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PinEndpoint:
    """A normalized pin endpoint imported from any supported document row."""

    project: str
    board: str
    sheet: str
    sheet_path: str
    reference: str
    pin: str
    net_name: str
    label: str
    source_file: str
    row_number: int = 0

    @property
    def endpoint_id(self) -> str:
        location = self.sheet or self.board or self.project
        return f"{self.project}:{location}:{self.reference}.{self.pin}"

    def match_values(self) -> List[str]:
        return list(dict.fromkeys(value for value in (self.net_name, self.label) if value))


@dataclass
class ImportedPinDocument:
    project: str
    path: str
    endpoints: List[PinEndpoint] = field(default_factory=list)


@dataclass
class LinkRule:
    """An ordered source-to-destination label matching rule."""

    name: str
    mode: str
    source_pattern: str
    destination_pattern: str

    def __post_init__(self) -> None:
        self.mode = self.mode.lower().strip()
        if self.mode not in {"wildcard", "regex"}:
            raise ValueError(f"Rule {self.name!r} mode must be wildcard or regex.")
        if not self.source_pattern or not self.destination_pattern:
            raise ValueError(f"Rule {self.name!r} requires source and destination patterns.")
        if self.mode == "regex":
            re.compile(self.source_pattern)
            re.compile(self.destination_pattern)


class PinDocumentImporter:
    """Read KiWay CSV and Markdown table exports into normalized endpoints."""

    def load(self, path: str, project_name: str = "") -> ImportedPinDocument:
        source = os.path.abspath(path)
        project = project_name.strip() or Path(path).stem
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            rows = self._csv_rows(source)
        elif suffix in {".md", ".markdown"}:
            rows = self._markdown_rows(source)
        else:
            raise ValueError(f"Unsupported pin document: {path}. Use CSV or Markdown.")
        endpoints = self.endpoints_from_rows(rows, project, source)
        return ImportedPinDocument(project=project, path=source, endpoints=endpoints)

    def endpoints_from_rows(
        self,
        rows: Iterable[Dict[str, Any]],
        project: str,
        source_file: str = "Current PCB",
    ) -> List[PinEndpoint]:
        endpoints: List[PinEndpoint] = []
        for row_number, row in enumerate(rows, start=2):
            normalized = {
                self._header_key(key): str(value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            endpoints.extend(
                self._row_endpoints(normalized, project.strip() or "Unnamed Project", source_file, row_number)
            )
        unique: Dict[Tuple[str, ...], PinEndpoint] = {}
        for endpoint in endpoints:
            key = (
                endpoint.project,
                endpoint.board,
                endpoint.sheet_path,
                endpoint.reference,
                endpoint.pin,
                endpoint.net_name,
                endpoint.label,
            )
            unique[key] = endpoint
        return list(unique.values())

    def _row_endpoints(
        self,
        row: Dict[str, str],
        project: str,
        source_file: str,
        row_number: int,
    ) -> List[PinEndpoint]:
        net = self._first(row, "netname", "net", "connectednet", "netlabel", "signalname")
        label = self._first(row, "label", "signal", "signalname", "function", "resolvedicfunction") or net
        common_board = self._first(row, "board", "boardname")
        common_sheet = self._first(row, "sheet", "sheetname")
        common_sheet_path = self._first(row, "sheetpath", "nativepath")
        specifications = [
            ("source", ("sourcereference", "sourceref"), ("sourcepin",), ("sourceboard",), ("sourcesheet",)),
            ("destination", ("destinationreference", "destinationref"), ("destinationpin",), ("destinationboard",), ("destinationsheet",)),
            ("tp", ("tpreference",), ("tppin",), (), ("tpsheet",)),
            ("resolved", ("resolvedic",), ("icpin",), (), ("resolvedicsheet",)),
            (
                "generic",
                ("reference", "connector", "ref", "componentreference", "designator"),
                ("pin", "pad", "padnamenumber", "pinnumber", "connectorpin"),
                (),
                (),
            ),
        ]
        endpoints: List[PinEndpoint] = []
        seen_roles = set()
        for role, reference_keys, pin_keys, board_keys, sheet_keys in specifications:
            reference = self._first(row, *reference_keys)
            pin = self._first(row, *pin_keys)
            if not reference or not pin:
                continue
            identity = (reference.upper(), pin.upper())
            if identity in seen_roles:
                continue
            seen_roles.add(identity)
            endpoints.append(
                PinEndpoint(
                    project=project,
                    board=self._first(row, *board_keys) or common_board or project,
                    sheet=self._first(row, *sheet_keys) or common_sheet,
                    sheet_path=common_sheet_path,
                    reference=reference,
                    pin=pin,
                    net_name=net,
                    label=label,
                    source_file=source_file,
                    row_number=row_number,
                )
            )
        return endpoints

    @staticmethod
    def _header_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    @staticmethod
    def _first(row: Dict[str, str], *keys: str) -> str:
        return next((row.get(key, "") for key in keys if row.get(key, "")), "")

    @staticmethod
    def _csv_rows(path: str) -> List[Dict[str, str]]:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _markdown_rows(self, path: str) -> List[Dict[str, str]]:
        with open(path, "r", encoding="utf-8-sig") as handle:
            lines = handle.readlines()
        rows: List[Dict[str, str]] = []
        index = 0
        while index + 1 < len(lines):
            header = self._split_markdown_row(lines[index])
            separator = self._split_markdown_row(lines[index + 1])
            if not header or len(header) != len(separator) or not all(
                re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separator
            ):
                index += 1
                continue
            index += 2
            while index < len(lines):
                values = self._split_markdown_row(lines[index])
                if not values or len(values) != len(header):
                    break
                rows.append(dict(zip(header, values)))
                index += 1
        return rows

    @staticmethod
    def _split_markdown_row(line: str) -> List[str]:
        value = line.strip()
        if not value.startswith("|"):
            return []
        return [cell.strip().replace(r"\|", "|") for cell in value.strip("|").split("|")]


class CrossProjectLinker:
    """Build an auditable board-to-board pin tracker from imported documents."""

    def __init__(self, documents: Sequence[ImportedPinDocument]) -> None:
        self.documents = list(documents)
        self.endpoints = [endpoint for document in self.documents for endpoint in document.endpoints]

    def link(
        self,
        rules: Sequence[LinkRule] = (),
        exact_match: bool = True,
        normalized_match: bool = True,
        include_power: bool = False,
        max_links: int = 50000,
    ) -> List[Dict[str, str]]:
        self._max_links = max_links
        eligible_endpoints = [
            endpoint for endpoint in self.endpoints
            if include_power or not self._is_power_endpoint(endpoint)
        ]
        links: Dict[Tuple[PinEndpoint, PinEndpoint], Dict[str, str]] = {}
        if exact_match:
            exact_index: Dict[str, List[PinEndpoint]] = {}
            for endpoint in eligible_endpoints:
                for value in endpoint.match_values():
                    exact_index.setdefault(value.strip().upper(), []).append(endpoint)
            self._link_index_buckets(links, exact_index, "Exact", "Automatic", "High")

        if normalized_match:
            normalized_index: Dict[str, List[PinEndpoint]] = {}
            for endpoint in eligible_endpoints:
                for value in endpoint.match_values():
                    key = self._canonical_signal(value)
                    if key:
                        normalized_index.setdefault(key, []).append(endpoint)
            self._link_index_buckets(links, normalized_index, "Normalized", "Automatic", "Medium")

        for rule in rules:
            source_index: Dict[Tuple[str, ...], List[PinEndpoint]] = {}
            destination_index: Dict[Tuple[str, ...], List[PinEndpoint]] = {}
            for endpoint in eligible_endpoints:
                for value in endpoint.match_values():
                    source_capture = self._pattern_capture(rule.mode, value, rule.source_pattern)
                    if source_capture is not None:
                        source_index.setdefault(source_capture, []).append(endpoint)
                    destination_capture = self._pattern_capture(rule.mode, value, rule.destination_pattern)
                    if destination_capture is not None:
                        destination_index.setdefault(destination_capture, []).append(endpoint)
            for capture in source_index.keys() & destination_index.keys():
                signal_key = " / ".join(capture) if capture else rule.name
                for source in self._unique_endpoints(source_index[capture]):
                    for destination in self._unique_endpoints(destination_index[capture]):
                        self._store_link(
                            links,
                            source,
                            destination,
                            rule.mode.title(),
                            rule.name,
                            signal_key,
                            "Rule",
                        )

        rows = list(links.values())
        endpoint_counts: Dict[str, int] = {}
        for row in rows:
            for key in ("Source Endpoint", "Destination Endpoint"):
                endpoint = row[key]
                endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
        for row in rows:
            row["Status"] = (
                "Ambiguous"
                if endpoint_counts[row["Source Endpoint"]] > 1
                or endpoint_counts[row["Destination Endpoint"]] > 1
                else "Resolved"
            )
        return sorted(
            rows,
            key=lambda row: (
                row["Source Project"],
                row["Destination Project"],
                row["Signal Key"],
                row["Source Endpoint"],
            ),
        )

    def unmatched(
        self,
        links: Sequence[Dict[str, str]],
        include_power: bool = False,
    ) -> List[PinEndpoint]:
        linked = {
            endpoint
            for row in links
            for endpoint in (row.get("Source Endpoint", ""), row.get("Destination Endpoint", ""))
        }
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.endpoint_id not in linked
            and (include_power or not self._is_power_endpoint(endpoint))
        ]

    def _link_index_buckets(
        self,
        links: Dict[Tuple[PinEndpoint, PinEndpoint], Dict[str, str]],
        index: Dict[str, List[PinEndpoint]],
        method: str,
        rule_name: str,
        confidence: str,
    ) -> None:
        for signal_key, bucket in index.items():
            endpoints = self._unique_endpoints(bucket)
            for source_index, source in enumerate(endpoints):
                for destination in endpoints[source_index + 1 :]:
                    self._store_link(
                        links,
                        source,
                        destination,
                        method,
                        rule_name,
                        signal_key,
                        confidence,
                    )

    @staticmethod
    def _canonical_signal(value: str) -> str:
        return "_".join(re.findall(r"[A-Z0-9]+", str(value).upper())).strip("_")

    @classmethod
    def _is_power_endpoint(cls, endpoint: PinEndpoint) -> bool:
        for value in endpoint.match_values():
            key = cls._canonical_signal(value)
            if re.match(r"^(GND|AGND|DGND|PGND|VCC|VDD|VSS|VBAT|PWR|POWER)(_|$)", key):
                return True
            if re.match(r"^(\+|-)?(1V|1V2|1V8|2V5|3V3|5V|12V|24V)(_|$)", key):
                return True
        return False

    def _pattern_capture(
        self,
        mode: str,
        value: str,
        pattern: str,
    ) -> Optional[Tuple[str, ...]]:
        if mode == "wildcard":
            return self._wildcard_capture(value, pattern)
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        return self._regex_capture(match) if match else None

    @staticmethod
    def _unique_endpoints(endpoints: Sequence[PinEndpoint]) -> List[PinEndpoint]:
        return list(dict.fromkeys(endpoints))

    def _store_link(
        self,
        links: Dict[Tuple[PinEndpoint, PinEndpoint], Dict[str, str]],
        source: PinEndpoint,
        destination: PinEndpoint,
        method: str,
        rule_name: str,
        signal_key: str,
        confidence: str,
    ) -> None:
        if source == destination:
            return
        if source.project == destination.project and source.source_file == destination.source_file:
            return
        pair = tuple(sorted((source, destination), key=lambda endpoint: endpoint.endpoint_id))
        if pair in links:
            return
        if len(links) >= self._max_links:
            raise ValueError(
                f"Cross-link result exceeds the safety limit of {self._max_links} links. "
                "Disable power matching or narrow the wildcard/regex rules."
            )
        links[pair] = self._link_row(
            source,
            destination,
            method,
            rule_name,
            signal_key,
            confidence,
        )

    @staticmethod
    def _wildcard_capture(value: str, pattern: str) -> Optional[Tuple[str, ...]]:
        regex_parts: List[str] = []
        for character in pattern:
            if character == "*":
                regex_parts.append("(.*?)")
            elif character == "?":
                regex_parts.append("(.)")
            else:
                regex_parts.append(re.escape(character))
        match = re.fullmatch("".join(regex_parts), value, re.IGNORECASE)
        if not match:
            return None
        return tuple(group.upper() for group in match.groups())

    @staticmethod
    def _regex_capture(match: re.Match[str]) -> Tuple[str, ...]:
        if match.groupdict():
            return tuple(str(value or "").upper() for _key, value in sorted(match.groupdict().items()))
        return tuple(str(value or "").upper() for value in match.groups())

    @staticmethod
    def _link_row(
        source: PinEndpoint,
        destination: PinEndpoint,
        method: str,
        rule: str,
        signal_key: str,
        confidence: str,
    ) -> Dict[str, str]:
        return {
            "Source Project": source.project,
            "Source Board": source.board,
            "Source Sheet": source.sheet,
            "Source Reference": source.reference,
            "Source Pin": source.pin,
            "Source Net/Label": source.net_name or source.label,
            "Source Endpoint": source.endpoint_id,
            "Destination Project": destination.project,
            "Destination Board": destination.board,
            "Destination Sheet": destination.sheet,
            "Destination Reference": destination.reference,
            "Destination Pin": destination.pin,
            "Destination Net/Label": destination.net_name or destination.label,
            "Destination Endpoint": destination.endpoint_id,
            "Signal Key": signal_key,
            "Match Method": method,
            "Rule": rule,
            "Confidence": confidence,
        }

    def harness_svg(
        self,
        links: Sequence[Dict[str, str]],
        title: str = "KiWay Cross-Project Harness",
    ) -> str:
        if not links:
            return self._empty_svg("No cross-project links found")
        projects = sorted(
            {
                row[key]
                for row in links
                for key in ("Source Project", "Destination Project")
                if row.get(key)
            }
        )
        endpoints_by_project: Dict[str, List[str]] = {project: [] for project in projects}
        endpoint_labels: Dict[str, Tuple[str, str]] = {}
        for row in links:
            for prefix in ("Source", "Destination"):
                project = row[f"{prefix} Project"]
                endpoint = row[f"{prefix} Endpoint"]
                if endpoint not in endpoints_by_project[project]:
                    endpoints_by_project[project].append(endpoint)
                endpoint_labels[endpoint] = (
                    f"{row[f'{prefix} Reference']}.{row[f'{prefix} Pin']}",
                    row[f"{prefix} Net/Label"],
                )
        column_width = 260
        gap = 170
        margin = 50
        width = max(1000, margin * 2 + len(projects) * column_width + (len(projects) - 1) * gap)
        row_height = 66
        height = max(390, 165 + max(len(items) for items in endpoints_by_project.values()) * row_height)
        positions: Dict[str, Tuple[int, int, int]] = {}
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
            '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" '
            'orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="context-stroke"/></marker></defs>',
            '<rect width="100%" height="100%" fill="#15191d"/>',
            '<style>.title{font:700 22px Segoe UI;fill:#f4f7fa}.project{font:700 16px Segoe UI;fill:#f4f7fa}'
            '.pin{font:600 12px Segoe UI;fill:#f4f7fa}.net{font:11px Segoe UI;fill:#aebdca}'
            '.wire{fill:none;stroke:#42b8d5;stroke-width:2;opacity:.82;marker-end:url(#arrow)}'
            '.wire.rule{stroke:#ad83e6}.wire.ambiguous{stroke:#f0a84b;stroke-dasharray:7 4}'
            '.tag{font:10px Segoe UI;fill:#f5c451}.legend{font:11px Segoe UI;fill:#aebdca}</style>',
            f'<text x="{width / 2}" y="34" text-anchor="middle" class="title">{html.escape(title)}</text>',
        ]
        for column, project in enumerate(projects):
            x = margin + column * (column_width + gap)
            parts.append(
                f'<text x="{x + column_width / 2}" y="72" text-anchor="middle" class="project">{html.escape(project)}</text>'
            )
            for row_index, endpoint in enumerate(endpoints_by_project[project]):
                y = 94 + row_index * row_height
                positions[endpoint] = (x, x + column_width, y + 24)
                pin_label, net_label = endpoint_labels[endpoint]
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{column_width}" height="48" rx="4" '
                    'fill="#27313a" stroke="#607786"/>'
                )
                parts.append(f'<text x="{x + 10}" y="{y + 19}" class="pin">{html.escape(pin_label)}</text>')
                parts.append(f'<text x="{x + 10}" y="{y + 37}" class="net">{html.escape(net_label[:36])}</text>')
        for row in links:
            source_position = positions.get(row["Source Endpoint"])
            destination_position = positions.get(row["Destination Endpoint"])
            if not source_position or not destination_position:
                continue
            source_left, source_right, sy = source_position
            destination_left, destination_right, dy = destination_position
            if source_left <= destination_left:
                sx, dx = source_right, destination_left
            else:
                sx, dx = source_left, destination_right
            if sx > dx:
                sx, dx = dx, sx
                sy, dy = dy, sy
            bend = (sx + dx) / 2
            classes = ["wire"]
            if row.get("Match Method") in {"Wildcard", "Regex"}:
                classes.append("rule")
            if row.get("Status") == "Ambiguous":
                classes.append("ambiguous")
            parts.append(
                f'<path d="M {sx} {sy} C {bend} {sy}, {bend} {dy}, {dx} {dy}" '
                f'class="{" ".join(classes)}"/>'
            )
            parts.append(
                f'<text x="{bend}" y="{(sy + dy) / 2 - 4}" text-anchor="middle" class="tag">'
                f'{html.escape(row["Signal Key"][:28])}</text>'
            )
        legend_y = height - 24
        parts.extend(
            [
                f'<line x1="50" y1="{legend_y - 4}" x2="82" y2="{legend_y - 4}" class="wire"/>',
                f'<text x="90" y="{legend_y}" class="legend">Automatic</text>',
                f'<line x1="180" y1="{legend_y - 4}" x2="212" y2="{legend_y - 4}" class="wire rule"/>',
                f'<text x="220" y="{legend_y}" class="legend">Wildcard / regex rule</text>',
                f'<line x1="390" y1="{legend_y - 4}" x2="422" y2="{legend_y - 4}" class="wire ambiguous"/>',
                f'<text x="430" y="{legend_y}" class="legend">Ambiguous endpoint</text>',
            ]
        )
        parts.append("</svg>")
        return "\n".join(parts)

    @staticmethod
    def _empty_svg(message: str) -> str:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300">'
            '<rect width="100%" height="100%" fill="#15191d"/>'
            f'<text x="450" y="150" text-anchor="middle" fill="#f4f7fa" '
            f'font-family="Segoe UI" font-size="20">{html.escape(message)}</text></svg>'
        )


def parse_link_rules(text: str) -> List[LinkRule]:
    """Parse ``Name | mode | source | destination`` rules from the GUI.

    A double-pipe delimiter may be used when regex patterns contain alternation.
    """
    rules: List[LinkRule] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        delimiter = "||" if "||" in line else "|"
        parts = [part.strip() for part in line.split(delimiter)]
        if len(parts) != 4:
            raise ValueError(
                f"Cross-link rule line {line_number} must contain: "
                "Name | wildcard/regex | source pattern | destination pattern."
            )
        try:
            rules.append(LinkRule(*parts))
        except (ValueError, re.error) as exc:
            raise ValueError(f"Cross-link rule line {line_number}: {exc}") from exc
    return rules
