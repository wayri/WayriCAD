"""Automatic PCB power-tree extraction and issue reporting."""

from __future__ import annotations

import html
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .data_extractor import DataExtractor


CONVERTER_KEYWORDS = (
    ("buck-boost", ("buck-boost", "buck boost", "step-up/down")),
    ("buck", ("buck", "step-down", "step down")),
    ("boost", ("boost", "step-up", "step up")),
    ("ldo", ("ldo", "low dropout", "linear regulator")),
    ("pmic", ("pmic", "power management ic")),
    ("load switch", ("load switch", "efuse", "e-fuse", "hot swap")),
    ("converter", ("dc/dc", "dc-dc", "dcdc", "voltage regulator", "converter", "regulator")),
)
FILTER_KEYWORDS = ("ferrite", "emi filter", "power filter", "common mode", "fuse", "polyfuse")
INPUT_PIN_WORDS = ("VIN", "PVIN", "AVIN", "INPUT", "VCC", "SOURCE")
OUTPUT_PIN_WORDS = ("VOUT", "OUTPUT", "SW", "LX", "PHASE", "DRAIN")
CONTROL_PIN_WORDS = ("EN", "ENABLE", "FB", "COMP", "PG", "PGOOD", "SYNC", "MODE", "SS")


class PowerTreeAnalyzer:
    """Infer rail-to-rail conversion paths from an open pcbnew board."""

    def __init__(self, extractor: DataExtractor) -> None:
        self.extractor = extractor

    def analyze(self) -> Dict[str, Any]:
        pads_by_component = {
            fp.GetReference(): self._component_pads(fp)
            for fp in self.extractor.footprints
        }
        component_info = {
            fp.GetReference(): self._component_info(fp)
            for fp in self.extractor.footprints
        }
        ground_nets = {
            net for net in self.extractor.all_nets
            if self.extractor.classify_net(net) == "ground"
        }
        candidate_nets = {
            net for net in self.extractor.all_nets
            if self.extractor.classify_net(net) in {"supply", "power"}
        }

        # Converter pin names and adjacent pass-through parts expose switching
        # nodes that are often intentionally not named like global power rails.
        for ref, info in component_info.items():
            if not info["kind"]:
                continue
            for pad in pads_by_component[ref]:
                role = self._pin_role(pad["role"])
                if role in {"input", "output"}:
                    candidate_nets.add(pad["net"])
        changed = True
        while changed:
            changed = False
            for ref, info in component_info.items():
                if info["kind"] != "filter":
                    continue
                nets = {pad["net"] for pad in pads_by_component[ref] if pad["net"] not in ground_nets}
                if nets & candidate_nets and not nets <= candidate_nets:
                    candidate_nets.update(nets)
                    changed = True

        edges: List[Dict[str, Any]] = []
        issues: List[Dict[str, str]] = []
        for ref, info in component_info.items():
            kind = info["kind"]
            if not kind:
                continue
            all_component_nets = {
                pad["net"] for pad in pads_by_component[ref] if pad["net"]
            }
            # A filter-looking two-terminal part connected to ground is a
            # shunt/decoupling branch, not a series element in a single-line
            # power diagram.  Keep it out even when a custom rule forgot to
            # classify that ground alias.
            if kind == "filter" and any(self._ground_like(net) for net in all_component_nets):
                continue
            pads = [
                pad for pad in pads_by_component[ref]
                if pad["net"] in candidate_nets and pad["net"] not in ground_nets
            ]
            nets = sorted({pad["net"] for pad in pads})
            if len(nets) < 2:
                if kind != "filter":
                    issues.append(self._issue("Warning", "Incomplete converter path", ref, f"{ref} ({info['value']}) exposes fewer than two recognized power-path nets."))
                continue
            inferred_edges, inference_issues = self._component_edges(ref, info, pads)
            edges.extend(inferred_edges)
            issues.extend(inference_issues)

        edge_keys = set()
        unique_edges = []
        for edge in edges:
            key = (edge["Source Net"], edge["Destination Net"], edge["Component"])
            if edge["Source Net"] == edge["Destination Net"] or key in edge_keys:
                continue
            edge_keys.add(key)
            unique_edges.append(edge)
        edges = unique_edges

        incoming: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        outgoing: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            outgoing[edge["Source Net"]].append(edge)
            incoming[edge["Destination Net"]].append(edge)
            candidate_nets.update((edge["Source Net"], edge["Destination Net"]))

        pad_map = self.extractor.get_net_to_pads_map()
        nodes = []
        for net in sorted(candidate_nets, key=DataExtractor.natural_sort_key):
            attached = pad_map.get(net, [])
            refs = sorted({fp.GetReference() for fp, _pad in attached}, key=DataExtractor.natural_sort_key)
            sources = [ref for ref in refs if ref.upper().startswith(("J", "P", "X", "BT"))]
            converter_refs = {edge["Component"] for edge in incoming[net] + outgoing[net]}
            loads = [ref for ref in refs if ref not in converter_refs and ref not in sources]
            nodes.append({
                "Net": net,
                "Class": self.extractor.classify_net(net),
                "Voltage": self.parse_voltage(net),
                "Sources": ", ".join(sources),
                "Loads": ", ".join(loads),
                "Load Count": len(loads),
                "Incoming": len(incoming[net]),
                "Outgoing": len(outgoing[net]),
            })
            if len(incoming[net]) > 1:
                drivers = ", ".join(edge["Component"] for edge in incoming[net])
                issues.append(self._issue("Warning", "Multiple rail drivers", net, f"{net} has multiple inferred drivers: {drivers}."))
            if not incoming[net] and not sources:
                issues.append(self._issue("Info", "Unresolved rail source", net, f"No connector or upstream converter was inferred for {net}."))

        for net in sorted(self.extractor.all_nets, key=DataExtractor.natural_sort_key):
            if net not in candidate_nets and self.looks_like_voltage_net(net):
                issues.append(self._issue("Warning", "Unclassified voltage net", net, f"{net} looks like a voltage rail but is classified as signal. Add a power pattern or force it to signal intentionally."))

        cycles = self._find_cycles(edges)
        for cycle in cycles:
            issues.append(self._issue("Error", "Power-tree cycle", cycle[0], " -> ".join(cycle)))

        roots = sorted(
            [node["Net"] for node in nodes if node["Incoming"] == 0],
            key=DataExtractor.natural_sort_key,
        )
        return {"nodes": nodes, "edges": edges, "issues": issues, "roots": roots}

    def _component_edges(
        self,
        ref: str,
        info: Dict[str, str],
        pads: Sequence[Dict[str, str]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        kind = info["kind"]
        issues: List[Dict[str, str]] = []
        input_pads = [pad for pad in pads if self._pin_role(pad["role"]) == "input"]
        output_pads = [pad for pad in pads if self._pin_role(pad["role"]) == "output"]
        confidence = "Pin-name"
        if kind == "filter":
            ordered = sorted(pads, key=lambda pad: DataExtractor.natural_sort_key(pad["pin"]))
            input_pads, output_pads = ordered[:1], ordered[1:]
            confidence = "Pad-order"
        elif not input_pads or not output_pads:
            input_pads, output_pads = self._voltage_direction(kind, pads)
            confidence = "Voltage heuristic"
            issues.append(self._issue("Info", "Inferred converter direction", ref, f"{ref} direction was inferred from rail names because VIN/VOUT-style pin functions were unavailable."))

        edges = []
        for source in input_pads:
            for destination in output_pads:
                if source["net"] == destination["net"]:
                    continue
                edge = {
                    "Source Net": source["net"],
                    "Destination Net": destination["net"],
                    "Component": ref,
                    "Value": info["value"],
                    "Function": kind,
                    "Input Pin": source["pin"],
                    "Output Pin": destination["pin"],
                    "Confidence": confidence,
                }
                edges.append(edge)
                vin = self.parse_voltage(source["net"])
                vout = self.parse_voltage(destination["net"])
                if vin is not None and vout is not None:
                    if kind in {"buck", "ldo"} and vout >= vin:
                        issues.append(self._issue("Warning", "Voltage direction conflict", ref, f"{kind.upper()} {ref} was inferred as {source['net']} -> {destination['net']}, but output voltage is not lower."))
                    if kind == "boost" and vout <= vin:
                        issues.append(self._issue("Warning", "Voltage direction conflict", ref, f"BOOST {ref} was inferred as {source['net']} -> {destination['net']}, but output voltage is not higher."))
        return edges, issues

    def _voltage_direction(
        self,
        kind: str,
        pads: Sequence[Dict[str, str]],
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        unique: Dict[str, Dict[str, str]] = {}
        for pad in pads:
            unique.setdefault(pad["net"], pad)
        ordered = sorted(
            unique.values(),
            key=lambda pad: (
                self.parse_voltage(pad["net"]) is None,
                self.parse_voltage(pad["net"]) or 0,
                pad["net"],
            ),
        )
        if len(ordered) < 2:
            return [], []
        if kind == "boost":
            return ordered[:1], ordered[1:]
        return ordered[-1:], ordered[:-1]

    def _component_info(self, footprint: Any) -> Dict[str, str]:
        ref = str(footprint.GetReference())
        value = str(footprint.GetValue())
        fields = self._footprint_fields(footprint)
        text = " ".join([ref, value, str(footprint.GetFPID()), *fields.values()]).lower()
        kind = ""
        for candidate, keywords in CONVERTER_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                kind = candidate
                break
        if not kind and (ref.upper().startswith(("FB", "F", "L")) or any(keyword in text for keyword in FILTER_KEYWORDS)):
            kind = "filter"
        if not kind and ref.upper().startswith(("Q", "D")) and any(keyword in text for keyword in ("ideal diode", "reverse polarity", "power mosfet")):
            kind = "load switch"
        return {"reference": ref, "value": value, "kind": kind, "description": fields.get("Description", "")}

    def _component_pads(self, footprint: Any) -> List[Dict[str, str]]:
        rows = []
        for pad in footprint.Pads():
            net = pad.GetNet()
            net_name = str(net.GetNetname()) if net else ""
            if not net_name:
                continue
            pin = str(pad.GetPadName() if hasattr(pad, "GetPadName") else pad.GetNumber())
            functions = []
            for method_name in ("GetPinFunction", "GetName"):
                method = getattr(pad, method_name, None)
                if callable(method):
                    try:
                        functions.append(str(method() or ""))
                    except Exception:
                        pass
            rows.append({"pin": pin, "net": net_name, "role": " ".join([pin, *functions])})
        return rows

    @staticmethod
    def _footprint_fields(footprint: Any) -> Dict[str, str]:
        result = {}
        try:
            for field in footprint.GetFields():
                result[str(field.GetName())] = str(field.GetText())
        except Exception:
            pass
        return result

    @staticmethod
    def _pin_role(value: str) -> str:
        tokens = set(re.findall(r"[A-Z0-9]+", str(value).upper()))
        if tokens & set(CONTROL_PIN_WORDS):
            return "control"
        if tokens & set(INPUT_PIN_WORDS):
            return "input"
        if tokens & set(OUTPUT_PIN_WORDS):
            return "output"
        return ""

    @staticmethod
    def parse_voltage(net_name: str) -> Optional[float]:
        text = str(net_name).upper()
        match = re.search(r"(?<![A-Z0-9])(\d{1,3})V(\d{1,3})?(?:DC|AC)?(?![A-Z0-9])", text)
        if match:
            whole = float(match.group(1))
            fraction = match.group(2)
            return whole + (float(fraction) / (10 ** len(fraction)) if fraction else 0.0)
        match = re.search(r"(?<![A-Z0-9])(\d+(?:\.\d+)?)\s*V(?:DC|AC)?(?![A-Z0-9])", text)
        return float(match.group(1)) if match else None

    @classmethod
    def looks_like_voltage_net(cls, net_name: str) -> bool:
        return cls.parse_voltage(net_name) is not None or bool(
            re.search(r"(^|[^A-Z0-9])(VCC|VDD|VBAT|VBUS|VIN|VOUT|PWR)([^A-Z0-9]|$)", str(net_name).upper())
        )

    @staticmethod
    def _ground_like(net_name: str) -> bool:
        tokens = set(re.findall(r"[A-Z0-9]+", str(net_name).upper()))
        return bool(tokens & {"GND", "GROUND", "AGND", "DGND", "PGND", "GNDA", "GNDD", "VSS"})

    @staticmethod
    def _issue(severity: str, category: str, item: str, detail: str) -> Dict[str, str]:
        return {"Severity": severity, "Category": category, "Item": item, "Detail": detail}

    @staticmethod
    def _find_cycles(edges: Sequence[Dict[str, Any]]) -> List[List[str]]:
        adjacency: Dict[str, Set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge["Source Net"]].add(edge["Destination Net"])
        cycles: List[List[str]] = []
        visiting: List[str] = []
        visited: Set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                cycle = visiting[visiting.index(node):] + [node]
                if cycle not in cycles:
                    cycles.append(cycle)
                return
            if node in visited:
                return
            visiting.append(node)
            for destination in adjacency.get(node, set()):
                visit(destination)
            visiting.pop()
            visited.add(node)

        for node in list(adjacency):
            visit(node)
        return cycles


def generate_power_tree_svg(result: Dict[str, Any], title: str = "KiWay Power Tree") -> str:
    """Render a layered rail/converter diagram with an issue summary."""
    nodes = {node["Net"]: node for node in result.get("nodes", [])}
    edges = list(result.get("edges", []))
    issues = list(result.get("issues", []))
    if not nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 240"><rect width="100%" height="100%" fill="#15191d"/><text x="450" y="120" text-anchor="middle" fill="#f4f7fa" font-family="Segoe UI">No power rails found. Update net classification patterns.</text></svg>'

    incoming: Dict[str, List[str]] = defaultdict(list)
    outgoing: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["Source Net"]].append(edge["Destination Net"])
        incoming[edge["Destination Net"]].append(edge["Source Net"])
    levels = {name: 0 for name in nodes}
    for _ in range(len(nodes)):
        changed = False
        for edge in edges:
            desired = levels[edge["Source Net"]] + 1
            if desired > levels[edge["Destination Net"]] and desired < len(nodes):
                levels[edge["Destination Net"]] = desired
                changed = True
        if not changed:
            break
    columns: Dict[int, List[str]] = defaultdict(list)
    for name, level in levels.items():
        columns[level].append(name)
    max_level = max(columns) if columns else 0
    box_w, box_h, col_gap, row_gap, margin = 235, 76, 150, 34, 50
    graph_width = margin * 2 + (max_level + 1) * box_w + max_level * col_gap
    max_rows = max(len(items) for items in columns.values())
    issue_height = min(len(issues), 8) * 22 + 72
    width = max(1100, graph_width)
    height = max(420, 105 + max_rows * (box_h + row_gap) + issue_height)
    positions: Dict[str, Tuple[float, float]] = {}
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#54c7d9"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#15191d"/>',
        '<style>.title{font:700 22px Segoe UI;fill:#f4f7fa}.rail{font:700 14px Segoe UI;fill:#f4f7fa}.small{font:11px Segoe UI;fill:#aebdca}.edge{font:10px Segoe UI;fill:#f4ca64}.issue{font:11px Segoe UI;fill:#d8e0e6}.net-row{cursor:pointer}.net-row:hover .rail-box{stroke-width:4}</style>',
        f'<text x="{width / 2}" y="34" class="title" text-anchor="middle">{html.escape(title)}</text>',
    ]
    for level in sorted(columns):
        x = margin + level * (box_w + col_gap)
        names = sorted(columns[level], key=DataExtractor.natural_sort_key)
        for row_index, name in enumerate(names):
            y = 72 + row_index * (box_h + row_gap)
            positions[name] = (x, y)
            node = nodes[name]
            classification = node.get("Class", "power")
            fill = {"supply": "#294d63", "power": "#57462c", "signal": "#3c3f45"}.get(classification, "#3c3f45")
            stroke = "#63c5da" if classification != "signal" else "#d6a84f"
            svg.append(f'<g class="net-row" data-net="{html.escape(name)}"><title>{html.escape(name)} | click to highlight in PCB Editor</title>')
            svg.append(f'<rect class="rail-box" x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
            svg.append(f'<text x="{x + 12}" y="{y + 25}" class="rail">{html.escape(name[:28])}</text>')
            voltage = node.get("Voltage")
            detail = f'{voltage:g} V' if voltage is not None else classification
            svg.append(f'<text x="{x + 12}" y="{y + 45}" class="small">{html.escape(detail)} | {node.get("Load Count", 0)} loads</text>')
            source_text = node.get("Sources") or "upstream inferred"
            svg.append(f'<text x="{x + 12}" y="{y + 63}" class="small">Source: {html.escape(str(source_text)[:28])}</text>')
            svg.append('</g>')
    for edge_index, edge in enumerate(edges):
        source = positions.get(edge["Source Net"])
        destination = positions.get(edge["Destination Net"])
        if not source or not destination:
            continue
        sx, sy = source[0] + box_w, source[1] + box_h / 2
        dx, dy = destination[0], destination[1] + box_h / 2
        bend = (sx + dx) / 2
        svg.append(f'<path d="M {sx} {sy} C {bend} {sy}, {bend} {dy}, {dx} {dy}" fill="none" stroke="#54c7d9" stroke-width="2.2" marker-end="url(#arrow)"/>')
        label = f'{edge["Component"]} | {edge["Function"]}'
        svg.append(f'<text x="{bend}" y="{(sy + dy) / 2 - 6}" class="edge" text-anchor="middle">{html.escape(label[:30])}</text>')
    issue_y = height - issue_height + 20
    svg.append(f'<line x1="{margin}" y1="{issue_y - 16}" x2="{width - margin}" y2="{issue_y - 16}" stroke="#48535c"/>')
    svg.append(f'<text x="{margin}" y="{issue_y}" class="rail">Checks: {len(issues)} findings</text>')
    colors = {"Error": "#ff6b6b", "Warning": "#f0a84b", "Info": "#70b7d6"}
    for index, issue in enumerate(issues[:8]):
        y = issue_y + 22 + index * 22
        color = colors.get(issue.get("Severity", "Info"), "#70b7d6")
        text = f'{issue.get("Severity")}: {issue.get("Category")} - {issue.get("Item")} - {issue.get("Detail")}'
        svg.append(f'<text x="{margin}" y="{y}" class="issue" fill="{color}">{html.escape(text[:155])}</text>')
    svg.append('</svg>')
    return "\n".join(svg)
