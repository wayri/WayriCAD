"""
Advanced graph construction and signal intelligence for KiWay Extract Pins.

The parser builds a networkx graph from the currently open pcbnew board and,
optionally, from KiCad XML netlists.  KiCad does not expose full schematic
symbol metadata through pcbnew, so the board parser is the reliable baseline
inside an ActionPlugin while XML netlists add schematic fields/pin names when
available.
"""

from __future__ import annotations

import fnmatch
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import networkx as nx
except ImportError as exc:  # pragma: no cover - depends on KiCad Python env
    nx = None
    NETWORKX_IMPORT_ERROR = exc
else:
    NETWORKX_IMPORT_ERROR = None


PASSIVE_PREFIXES = ("R", "C", "L", "FB", "F", "JP", "JMP")
ACTIVE_PREFIXES = ("U", "IC", "Q", "M")
CONNECTOR_PREFIXES = ("J", "P", "CON", "X")
TMT_C_TOKENS = {"TM", "TC", "TA", "TD", "CA", "CD"}


@dataclass
class InterfaceSignal:
    """A signal parsed from a KiWay net label convention."""

    net_name: str
    source_board: str = ""
    destination_board: str = ""
    interface: str = ""
    signal: str = ""
    channel: str = ""
    tm_tc_type: str = ""
    boards_seen: List[str] = field(default_factory=list)


class SchematicGraphParser:
    """
    Construct and query a KiCad connectivity graph.

    Graph layout:
    - Component nodes: ``COMP:<ref>``
    - Pin nodes: ``PIN:<ref>:<pin>``
    - Net nodes: ``NET:<net_name>``
    - Edges connect component-to-pin and pin-to-net.

    A passive or explicit pass-through component can be traversed through its
    pins, allowing a TP on the far side of a resistor to resolve back to an IC.
    """

    def __init__(
        self,
        board: Any = None,
        schematic_paths: Optional[Sequence[str]] = None,
        board_sequence: Optional[Sequence[str]] = None,
        pass_through_field: str = "NetTie_Path",
    ) -> None:
        if nx is None:
            raise ImportError(
                "networkx is required for advanced KiWay graph tracing. "
                "Install it into KiCad's Python environment."
            ) from NETWORKX_IMPORT_ERROR

        self.board = board
        self.schematic_paths = list(schematic_paths or [])
        self.board_sequence = [b.strip().upper() for b in (board_sequence or []) if b.strip()]
        self.pass_through_field = pass_through_field
        self.graph = nx.Graph()
        self.components: Dict[str, Dict[str, Any]] = {}
        self.net_to_pins: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.pin_functions: Dict[Tuple[str, str], str] = {}

    @staticmethod
    def component_node(ref: str) -> str:
        return f"COMP:{ref}"

    @staticmethod
    def pin_node(ref: str, pin: str) -> str:
        return f"PIN:{ref}:{pin}"

    @staticmethod
    def net_node(net_name: str) -> str:
        return f"NET:{net_name}"

    @staticmethod
    def natural_sort_key(text: str) -> List[Any]:
        return [int(s) if s.isdigit() else s.lower() for s in re.split(r"([0-9]+)", text)]

    def build(self) -> Any:
        """Build the graph from configured board and schematic/netlist files."""
        if self.board is not None:
            self._add_board_connectivity(self.board)

        for path in self.schematic_paths:
            if os.path.isdir(path):
                self._add_schematics_from_directory(path)
            elif os.path.isfile(path):
                self._add_schematic_file(path)

        self._add_pass_through_edges()
        return self.graph

    def _add_schematics_from_directory(self, directory: str) -> None:
        for root, _, files in os.walk(directory):
            for name in files:
                if name.lower().endswith((".xml", ".net")):
                    self._add_schematic_file(os.path.join(root, name))

    def _add_schematic_file(self, path: str) -> None:
        """Parse a KiCad XML netlist if one is supplied by the user."""
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            return

        root = tree.getroot()
        comp_meta: Dict[str, Dict[str, str]] = {}
        for comp in root.findall(".//components/comp"):
            ref = comp.attrib.get("ref", "")
            if not ref:
                continue
            fields = {
                field.attrib.get("name", ""): (field.text or "")
                for field in comp.findall("./fields/field")
            }
            comp_meta[ref] = {
                "value": (comp.findtext("value") or ""),
                "footprint": (comp.findtext("footprint") or ""),
                "datasheet": (comp.findtext("datasheet") or ""),
                **fields,
            }
            self._ensure_component(ref, comp_meta[ref])

        for net in root.findall(".//nets/net"):
            net_name = net.attrib.get("name", "") or net.attrib.get("code", "")
            if not net_name:
                continue
            self._ensure_net(net_name)
            for node in net.findall("./node"):
                ref = node.attrib.get("ref", "")
                pin = node.attrib.get("pin", "")
                pinfunction = node.attrib.get("pinfunction", "") or node.attrib.get("pintype", "")
                if ref and pin:
                    self._add_pin(ref, pin, net_name, pinfunction=pinfunction)

    def _add_board_connectivity(self, board: Any) -> None:
        for fp in board.GetFootprints():
            ref = fp.GetReference()
            fields = self._get_footprint_fields(fp)
            meta = {
                "reference": ref,
                "value": fp.GetValue(),
                "footprint": str(fp.GetFPID()),
                "layer": fp.GetLayerName(),
                **fields,
            }
            self._ensure_component(ref, meta)
            for pad in fp.Pads():
                net = pad.GetNet()
                net_name = net.GetNetname() if net else ""
                if not net_name:
                    continue
                pin_name = pad.GetPadName()
                pin_function = self._read_pad_function(pad)
                self._add_pin(ref, pin_name, net_name, pinfunction=pin_function)

    def _ensure_component(self, ref: str, meta: Optional[Dict[str, Any]] = None) -> None:
        node = self.component_node(ref)
        data = self.components.setdefault(ref, {})
        if meta:
            data.update({k: v for k, v in meta.items() if v is not None})
        data.setdefault("reference", ref)
        data.setdefault("kind", self._classify_component(ref, data.get("value", "")))
        self.graph.add_node(node, node_type="component", ref=ref, **data)

    def _ensure_net(self, net_name: str) -> None:
        parsed = self.parse_interface_label(net_name)
        self.graph.add_node(
            self.net_node(net_name),
            node_type="net",
            net_name=net_name,
            interface=parsed.interface,
            signal=parsed.signal,
            tm_tc_type=parsed.tm_tc_type,
            source_board=parsed.source_board,
            destination_board=parsed.destination_board,
        )

    def _add_pin(self, ref: str, pin: str, net_name: str, pinfunction: str = "") -> None:
        self._ensure_component(ref)
        self._ensure_net(net_name)
        pin_node = self.pin_node(ref, pin)
        self.graph.add_node(
            pin_node,
            node_type="pin",
            ref=ref,
            pin=pin,
            function=pinfunction or self.pin_functions.get((ref, pin), ""),
        )
        self.graph.add_edge(self.component_node(ref), pin_node, edge_type="has_pin")
        self.graph.add_edge(pin_node, self.net_node(net_name), edge_type="connected_to", net=net_name)
        self.net_to_pins[net_name].append((ref, pin))
        if pinfunction:
            self.pin_functions[(ref, pin)] = pinfunction

    def _add_pass_through_edges(self) -> None:
        for ref, meta in self.components.items():
            pin_nodes = [
                n for n in self.graph.neighbors(self.component_node(ref))
                if self.graph.nodes[n].get("node_type") == "pin"
            ]
            if len(pin_nodes) < 2:
                continue
            if not self.is_pass_through_component(ref):
                continue
            for idx, a in enumerate(pin_nodes):
                for b in pin_nodes[idx + 1:]:
                    self.graph.add_edge(a, b, edge_type="pass_through", via=ref)

    def is_pass_through_component(self, ref: str) -> bool:
        meta = self.components.get(ref, {})
        if str(meta.get(self.pass_through_field, "")).strip():
            return True
        return ref.upper().startswith(PASSIVE_PREFIXES)

    def _classify_component(self, ref: str, value: str = "") -> str:
        ref_u = ref.upper()
        value_u = value.upper()
        if ref_u.startswith(PASSIVE_PREFIXES):
            return "passive"
        if ref_u.startswith(CONNECTOR_PREFIXES) or "CONN" in value_u:
            return "connector"
        if ref_u.startswith(ACTIVE_PREFIXES):
            return "active"
        if ref_u.startswith("TP") or "TESTPOINT" in value_u:
            return "testpoint"
        return "component"

    def parse_interface_label(self, net_name: str) -> InterfaceSignal:
        """
        Parse flexible board labels without requiring a fixed naming template.

        Board order is the only positional contract: the first and second
        configured board names found anywhere in the label are source and
        destination.  Separators may be underscores, slashes, hyphens, plus
        signs, parentheses, or spaces.  TM/TC markers are standalone tokens
        separated by any non-alphanumeric character.
        """
        raw = str(net_name or "")
        upper = raw.upper()

        board_hits: List[Tuple[int, int, str]] = []
        for board in self.board_sequence:
            if not board:
                continue
            for match in re.finditer(re.escape(board), upper):
                before = upper[match.start() - 1] if match.start() else ""
                after = upper[match.end()] if match.end() < len(upper) else ""
                if before.isalnum() or after.isalnum():
                    continue
                board_hits.append((match.start(), match.end(), board))
        board_hits.sort(key=lambda item: (item[0], item[1]))
        non_overlapping: List[Tuple[int, int, str]] = []
        for hit in board_hits:
            if not non_overlapping or hit[0] >= non_overlapping[-1][1]:
                non_overlapping.append(hit)
        boards_seen = [item[2] for item in non_overlapping]
        source = boards_seen[0] if boards_seen else ""
        destination = boards_seen[1] if len(boards_seen) > 1 else ""

        marker_matches = list(re.finditer(r"(?<![A-Z0-9])(TM|TC|TA|TD|CA|CD)(?![A-Z0-9])", upper))
        tm_tc = marker_matches[0].group(1) if marker_matches else ""

        masked = list(upper)
        for start, end, _board in non_overlapping:
            for index in range(start, end):
                masked[index] = " "
        for match in marker_matches:
            for index in range(match.start(), match.end()):
                masked[index] = " "
        payload = "".join(masked)
        tokens = [token for token in re.findall(r"[A-Z0-9]+", payload) if token not in {"SIGNAL", "SIG", "NET"}]

        interface = next(
            (token for token in tokens if re.match(r"^(I2C|I3C|SPI|QSPI|UART|CAN|LIN|RS485|RS422|USB|ETH|ADC|DAC|GPIO|JTAG|SWD|MIPI|LVDS)\d*$", token)),
            "",
        )
        channel = next((token for token in tokens if token.isdigit()), "")
        signal = "_".join(token for token in tokens if token != interface and token != channel)

        return InterfaceSignal(
            net_name=net_name,
            source_board=source,
            destination_board=destination,
            interface=interface,
            signal=signal,
            channel=channel,
            tm_tc_type=tm_tc,
            boards_seen=boards_seen,
        )

    def group_interfaces(self) -> Dict[str, Dict[str, Any]]:
        """Group diff pairs, buses, and convention-based labels."""
        interfaces: Dict[str, Dict[str, Any]] = {}
        for net_name in sorted(self.net_to_pins, key=self.natural_sort_key):
            parsed = self.parse_interface_label(net_name)
            key = parsed.interface or self._infer_bus_name(net_name) or "UNCLASSIFIED"
            entry = interfaces.setdefault(
                key,
                {
                    "name": key,
                    "nets": [],
                    "pins": [],
                    "source_board": parsed.source_board,
                    "destination_board": parsed.destination_board,
                    "tm_tc_types": set(),
                    "diff_pairs": [],
                },
            )
            entry["nets"].append(net_name)
            entry["pins"].extend(self.net_to_pins.get(net_name, []))
            if parsed.tm_tc_type:
                entry["tm_tc_types"].add(parsed.tm_tc_type)

        self._attach_diff_pairs(interfaces)
        for entry in interfaces.values():
            entry["tm_tc_types"] = sorted(entry["tm_tc_types"])
            entry["pins"] = sorted(set(entry["pins"]))
        return interfaces

    def trace_from_pin(
        self,
        ref: str,
        pin: str,
        target_kinds: Optional[Set[str]] = None,
        max_hops: int = 10,
    ) -> List[Dict[str, Any]]:
        """Trace from a pin through nets and pass-through parts to target components."""
        start = self.pin_node(ref, pin)
        if start not in self.graph:
            return []
        target_kinds = target_kinds or {"active"}
        results: List[Dict[str, Any]] = []
        queue: List[Tuple[str, List[str]]] = [(start, [start])]
        seen: Set[str] = {start}

        while queue:
            node, path = queue.pop(0)
            if len(path) > max_hops:
                continue
            for neighbor in self.graph.neighbors(node):
                if neighbor in seen:
                    continue
                edge_type = self.graph.edges[node, neighbor].get("edge_type")
                ndata = self.graph.nodes[neighbor]
                if edge_type == "has_pin" and ndata.get("node_type") == "component":
                    kind = ndata.get("kind", "")
                    candidate_ref = ndata.get("ref", "")
                    if candidate_ref != ref and kind in target_kinds:
                        results.append(
                            {
                                "reference": candidate_ref,
                                "value": ndata.get("value", ""),
                                "kind": kind,
                                "path": path + [neighbor],
                            }
                        )
                    continue
                if edge_type in {"connected_to", "pass_through", "has_pin"}:
                    seen.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return results

    def get_component_pin_nets(self, ref: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        comp_node = self.component_node(ref)
        if comp_node not in self.graph:
            return rows
        for pin_node in self.graph.neighbors(comp_node):
            if self.graph.nodes[pin_node].get("node_type") != "pin":
                continue
            pin = self.graph.nodes[pin_node].get("pin", "")
            nets = [
                self.graph.nodes[n].get("net_name", "")
                for n in self.graph.neighbors(pin_node)
                if self.graph.nodes[n].get("node_type") == "net"
            ]
            for net_name in nets:
                rows.append({"reference": ref, "pin": pin, "net": net_name})
        return sorted(rows, key=lambda r: self.natural_sort_key(r["pin"]))

    def _infer_bus_name(self, net_name: str) -> str:
        match = re.search(r"\b(I2C|SPI|UART|CAN|USB|ETH|RS485|RS422|ADC|DAC|GPIO)\d*", net_name.upper())
        if match:
            return match.group(0)
        diff = re.match(r"(.+?)(?:[_-]?[PN]|[_-]?[+-])$", net_name.upper())
        return diff.group(1) if diff else ""

    def _attach_diff_pairs(self, interfaces: Dict[str, Dict[str, Any]]) -> None:
        by_base: Dict[str, Dict[str, str]] = defaultdict(dict)
        for net_name in self.net_to_pins:
            match = re.match(r"(.+?)(?:[_-]?([PN])|[_-]?([+-]))$", net_name.upper())
            if not match:
                continue
            base = match.group(1)
            polarity = match.group(2) or match.group(3)
            by_base[base][polarity] = net_name

        for base, pair in by_base.items():
            if ("P" in pair and "N" in pair) or ("+" in pair and "-" in pair):
                key = self._infer_bus_name(base) or "DIFF_PAIRS"
                entry = interfaces.setdefault(
                    key,
                    {"name": key, "nets": [], "pins": [], "tm_tc_types": set(), "diff_pairs": []},
                )
                entry["diff_pairs"].append({"base": base, "positive": pair.get("P") or pair.get("+"), "negative": pair.get("N") or pair.get("-")})

    def _get_footprint_fields(self, fp: Any) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        get_fields = getattr(fp, "GetFields", None)
        if not get_fields:
            return fields
        try:
            for field in get_fields():
                fields[field.GetName()] = field.GetText()
        except Exception:
            return fields
        return fields

    def _read_pad_function(self, pad: Any) -> str:
        for attr in ("GetPinFunction", "GetName"):
            method = getattr(pad, attr, None)
            if callable(method):
                try:
                    value = method()
                except Exception:
                    continue
                if value:
                    return str(value)
        return ""


def wildcard_match(text: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(text.upper(), pattern.upper())
