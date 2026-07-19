"""Test point to function extraction built on the KiWay connectivity graph."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schematic_graph import SchematicGraphParser


class TestPointExtractor:
    """Resolve TP footprints back to the most likely source IC pin/function."""

    def __init__(self, parser: SchematicGraphParser) -> None:
        self.parser = parser

    def extract(self, max_hops: int = 12) -> Dict[str, Dict[str, Any]]:
        """
        Return ``TP Reference -> Net Name -> Resolved IC Function -> IC Pin``.

        The resolved value is stored as a structured dict to preserve connector
        and path detail for Markdown/CSV output.
        """
        if not self.parser.graph.nodes:
            self.parser.build()

        result: Dict[str, Dict[str, Any]] = {}
        for ref, meta in sorted(self.parser.components.items()):
            value = str(meta.get("value", ""))
            if not (ref.upper().startswith("TP") or "TESTPOINT" in value.upper()):
                continue

            tp_rows = self.parser.get_component_pin_nets(ref)
            for row in tp_rows:
                pin = row["pin"]
                net_name = row["net"]
                targets = self.parser.trace_from_pin(ref, pin, target_kinds={"active"}, max_hops=max_hops)
                resolved = self._best_target(targets)
                parsed = self.parser.parse_interface_label(net_name)
                tp_sheet = self.parser.get_component_sheet(ref)
                ic_sheet = self.parser.get_component_sheet(resolved.get("reference", ""))
                result[ref] = {
                    "TP Reference": ref,
                    "TP Pin": pin,
                    "TP Sheet": tp_sheet["name"],
                    "TP Sheet Path": tp_sheet["path"],
                    "Net Name": net_name,
                    "Resolved IC": resolved.get("reference", ""),
                    "Resolved IC Value": resolved.get("value", ""),
                    "Resolved IC Sheet": ic_sheet["name"],
                    "Resolved IC Sheet Path": ic_sheet["path"],
                    "Resolved IC Function": self._resolve_pin_function(resolved),
                    "IC Pin": self._resolve_pin_number(resolved),
                    "Path": " -> ".join(resolved.get("path", [])),
                    "TM/TC Type": parsed.tm_tc_type,
                    "Source Board": parsed.source_board,
                    "Destination Board": parsed.destination_board,
                    "Interface": parsed.interface,
                    "Signal": parsed.signal,
                }
        return result

    def as_rows(self, max_hops: int = 12) -> List[Dict[str, Any]]:
        return list(self.extract(max_hops=max_hops).values())

    def _best_target(self, targets: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not targets:
            return {}
        return sorted(targets, key=lambda t: (len(t.get("path", [])), str(t.get("reference", ""))))[0]

    def _resolve_pin_number(self, resolved: Dict[str, Any]) -> str:
        path = resolved.get("path", [])
        if len(path) < 2:
            return ""
        pin_nodes = [node for node in path if node.startswith("PIN:")]
        if not pin_nodes:
            return ""
        last_pin = pin_nodes[-1]
        return last_pin.split(":", 2)[-1]

    def _resolve_pin_function(self, resolved: Dict[str, Any]) -> str:
        ref = resolved.get("reference", "")
        pin = self._resolve_pin_number(resolved)
        if not ref or not pin:
            return ""
        return self.parser.pin_functions.get((ref, pin), "")
