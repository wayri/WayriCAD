"""Safeguarded controller-to-connector path mapping.

The mapper crosses a component only when an exact entry/exit pin pair is
approved.  This is intentionally stricter than treating a reference pattern
as an all-pin net tie, which is unsafe for transistors and multi-pin ICs.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class TraversalRule:
    """One approved component pin-pair crossing."""

    ref_pattern: str
    pin_a: str
    pin_b: str
    mode: str = "passive"
    note: str = ""

    @property
    def conditional(self) -> bool:
        return self.mode.lower() not in {"passive", "fixed", "confirmed"}


DEFAULT_PASSIVE_RULE_TEXT = """\
R* | 1-2 | passive | two-terminal series resistor
L* | 1-2 | passive | two-terminal series inductor
FB* | 1-2 | passive | two-terminal ferrite bead
F* | 1-2 | passive | two-terminal fuse
"""

ACTIVE_RULE_EXAMPLES = """\
Q* | D-S | active | MOSFET channel; state and direction are not inferred
Q* | C-E | active | BJT path; bias and direction are not inferred
U7 | IN-OUT | active | explicitly reviewed IC pass-through
"""


def parse_traversal_rules(text: str) -> List[TraversalRule]:
    """Parse ``ref | pin-pair[, pin-pair] | mode | note`` rules.

    Pin tokens match either the physical pin number or schematic pin function.
    ``<->`` and ``-`` are accepted as bidirectional pair separators.
    """

    rules: List[TraversalRule] = []
    for line_number, raw_line in enumerate(str(text or "").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", 3)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid traversal rule on line {line_number}.")
        ref_pattern = parts[0]
        mode = parts[2].lower() if len(parts) > 2 and parts[2] else "passive"
        if mode not in {"passive", "fixed", "confirmed", "conditional", "active"}:
            raise ValueError(
                f"Invalid traversal mode '{mode}' on line {line_number}."
            )
        note = parts[3] if len(parts) > 3 else ""
        for pair_text in re.split(r"[,;]", parts[1]):
            pair_text = pair_text.strip()
            separator = "<->" if "<->" in pair_text else "-"
            pair = [token.strip() for token in pair_text.split(separator, 1)]
            if len(pair) != 2 or not all(pair):
                raise ValueError(
                    f"Invalid pin pair '{pair_text}' on line {line_number}."
                )
            if "*" in pair or "?" in pair:
                raise ValueError(
                    f"Wildcards are not allowed in pin pairs (line {line_number})."
                )
            rules.append(TraversalRule(ref_pattern, pair[0], pair[1], mode, note))
    return rules


class ControllerConnectorMapper:
    """Trace selected source pins to connector pins through approved devices."""

    def __init__(self, parser: Any) -> None:
        self.parser = parser
        self.last_diagnostics: List[str] = []
        self._pins_by_ref: Dict[str, List[str]] = {}
        self._nets_by_pin: Dict[Tuple[str, str], List[str]] = {}
        for net_name, endpoints in parser.net_to_pins.items():
            for ref, pin in endpoints:
                ref, pin = str(ref), str(pin)
                self._pins_by_ref.setdefault(ref, [])
                if pin not in self._pins_by_ref[ref]:
                    self._pins_by_ref[ref].append(pin)
                self._nets_by_pin.setdefault((ref, pin), []).append(str(net_name))

    @staticmethod
    def _matches(value: str, patterns: Sequence[str]) -> bool:
        return any(fnmatch.fnmatchcase(value.upper(), p.upper()) for p in patterns)

    def _pin_tokens(self, ref: str, pin: str) -> Set[str]:
        function = str(self.parser.pin_functions.get((ref, pin), "")).strip()
        graph_node = self.parser.pin_node(ref, pin)
        if graph_node in self.parser.graph:
            function = str(
                self.parser.graph.nodes[graph_node].get("function", function)
            ).strip()
        tokens = {str(pin).strip().upper()}
        if function:
            tokens.add(function.upper())
        return tokens

    def _rule_exits(
        self,
        ref: str,
        entry_pin: str,
        rules: Sequence[TraversalRule],
        include_conditional: bool,
    ) -> List[Tuple[str, TraversalRule]]:
        entry_tokens = self._pin_tokens(ref, entry_pin)
        exits: List[Tuple[str, TraversalRule]] = []
        for rule in rules:
            if not fnmatch.fnmatchcase(ref.upper(), rule.ref_pattern.upper()):
                continue
            if rule.conditional and not include_conditional:
                continue
            a, b = rule.pin_a.upper(), rule.pin_b.upper()
            wanted = b if a in entry_tokens else a if b in entry_tokens else ""
            if not wanted:
                continue
            for exit_pin in self._pins_by_ref.get(ref, []):
                if exit_pin == entry_pin:
                    continue
                if wanted in self._pin_tokens(ref, exit_pin):
                    exits.append((exit_pin, rule))
        return exits

    def _field_rules(self, ref: str) -> List[TraversalRule]:
        """Read exact pin pairs from NetTie_Path; never infer all-pin crossing."""

        field_name = getattr(self.parser, "pass_through_field", "NetTie_Path")
        value = str(self.parser.components.get(ref, {}).get(field_name, "")).strip()
        if not value:
            return []
        try:
            return parse_traversal_rules(f"{ref} | {value} | confirmed | {field_name}")
        except ValueError:
            self.last_diagnostics.append(
                f"{ref}: ignored {field_name}; use explicit pairs such as 1-2 or D-S."
            )
            return []

    def trace(
        self,
        source_patterns: Sequence[str],
        destination_patterns: Sequence[str],
        rules: Sequence[TraversalRule],
        *,
        include_conditional: bool = False,
        include_ambiguous: bool = True,
        max_component_hops: int = 12,
        max_paths: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Return auditable source-to-destination routes.

        Source/destination express reporting scope, not electrical direction.
        A conditional route proves graph connectivity under the stated device
        assumption only; it does not prove transistor state or logic behavior.
        """

        self.last_diagnostics = []
        source_patterns = [p.strip() for p in source_patterns if p.strip()]
        destination_patterns = [p.strip() for p in destination_patterns if p.strip()]
        if not source_patterns or not destination_patterns:
            return []
        sources = sorted(
            (ref for ref in self._pins_by_ref if self._matches(ref, source_patterns)),
            key=self.parser.natural_sort_key,
        )
        destinations = {
            ref for ref in self._pins_by_ref if self._matches(ref, destination_patterns)
        }
        all_rules = list(rules)
        for ref in self._pins_by_ref:
            all_rules.extend(self._field_rules(ref))

        results: List[Dict[str, Any]] = []
        truncated = False
        for source_ref in sources:
            for source_pin in self._pins_by_ref.get(source_ref, []):
                for source_net in self._nets_by_pin.get((source_ref, source_pin), []):
                    stack = [{
                        "net": source_net,
                        "nets": [source_net],
                        "steps": [],
                        "visited": set(),
                        "conditional": False,
                        "branched": False,
                        "notes": [],
                    }]
                    while stack:
                        state = stack.pop()
                        net_name = state["net"]
                        for ref, pin in self.parser.net_to_pins.get(net_name, []):
                            ref, pin = str(ref), str(pin)
                            if ref == source_ref:
                                continue
                            if ref in destinations:
                                results.append(self._make_row(
                                    source_ref, source_pin, source_net,
                                    ref, pin, net_name, state,
                                ))
                                if len(results) >= max_paths:
                                    truncated = True
                                    break
                                continue
                            if len(state["steps"]) >= max_component_hops:
                                continue
                            exits = self._rule_exits(
                                ref, pin, all_rules, include_conditional
                            )
                            if len(exits) > 1:
                                state["branched"] = True
                            for exit_pin, rule in exits:
                                if ref in state["visited"]:
                                    continue
                                for next_net in self._nets_by_pin.get((ref, exit_pin), []):
                                    if next_net == net_name:
                                        continue
                                    next_state = {
                                        "net": next_net,
                                        "nets": state["nets"] + [next_net],
                                        "steps": state["steps"] + [{
                                            "ref": ref,
                                            "entry": pin,
                                            "exit": exit_pin,
                                            "mode": rule.mode,
                                            "note": rule.note,
                                        }],
                                        "visited": state["visited"] | {ref},
                                        "conditional": state["conditional"] or rule.conditional,
                                        "branched": state["branched"] or len(exits) > 1,
                                        "notes": state["notes"] + ([rule.note] if rule.note else []),
                                    }
                                    stack.append(next_state)
                        if truncated:
                            break
                    if truncated:
                        break
                if truncated:
                    break
            if truncated:
                break

        grouped: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
        for row in results:
            key = (
                row["Source Reference"], row["Source Pin"],
                row["Connector Reference"], row["Connector Pin"],
            )
            grouped.setdefault(key, []).append(row)
        final: List[Dict[str, Any]] = []
        for candidates in grouped.values():
            unique_paths = {row["Ordered Path"] for row in candidates}
            ambiguous = len(unique_paths) > 1 or any(
                row.pop("_branched", False) for row in candidates
            )
            for row in candidates:
                if ambiguous:
                    row["Status"] = "Ambiguous"
                    row["Confidence"] = "Low"
                if not ambiguous or include_ambiguous:
                    final.append(row)
        if truncated:
            self.last_diagnostics.append(
                f"Stopped after {max_paths} routes; narrow the scope or raise the limit."
            )
        return sorted(
            final,
            key=lambda row: (
                self.parser.natural_sort_key(row["Source Reference"]),
                self.parser.natural_sort_key(row["Source Pin"]),
                self.parser.natural_sort_key(row["Connector Reference"]),
                self.parser.natural_sort_key(row["Connector Pin"]),
                row["Ordered Path"],
            ),
        )

    def _make_row(
        self,
        source_ref: str,
        source_pin: str,
        source_net: str,
        destination_ref: str,
        destination_pin: str,
        destination_net: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        source = self.parser.components.get(source_ref, {})
        destination = self.parser.components.get(destination_ref, {})
        step_labels = [
            f'{step["ref"]}.{step["entry"]}->{step["ref"]}.{step["exit"]}'
            for step in state["steps"]
        ]
        active_refs = [
            step["ref"] for step in state["steps"]
            if step["mode"] in {"active", "conditional"}
        ]
        status = "Conditional" if state["conditional"] else "Resolved"
        confidence = "Conditional" if state["conditional"] else "High"
        path_parts = [f"{source_ref}.{source_pin}", f"[{source_net}]"]
        for index, step in enumerate(state["steps"]):
            path_parts.extend([
                f'{step["ref"]}.{step["entry"]}',
                f'{step["ref"]}.{step["exit"]}',
                f'[{state["nets"][index + 1]}]',
            ])
        path_parts.append(f"{destination_ref}.{destination_pin}")
        return {
            "Source Reference": source_ref,
            "Source Value": str(source.get("value", "")),
            "Source Pin": source_pin,
            "Source Pin Function": self._function(source_ref, source_pin),
            "Source Net": source_net,
            "Connector Reference": destination_ref,
            "Connector Value": str(destination.get("value", "")),
            "Connector Pin": destination_pin,
            "Connector Pin Function": self._function(destination_ref, destination_pin),
            "Connector Net": destination_net,
            "Net Sequence": " -> ".join(state["nets"]),
            "Inline Components": ", ".join(step["ref"] for step in state["steps"]),
            "Pin Transitions": "; ".join(step_labels),
            "Active Devices": ", ".join(dict.fromkeys(active_refs)),
            "Condition Notes": "; ".join(dict.fromkeys(state["notes"])),
            "Status": status,
            "Confidence": confidence,
            "Component Hops": len(state["steps"]),
            "Ordered Path": " -> ".join(path_parts),
            "_branched": bool(state["branched"]),
        }

    def _function(self, ref: str, pin: str) -> str:
        return str(self.parser.pin_functions.get((ref, pin), ""))


def rows_to_markdown(rows: Iterable[Dict[str, Any]]) -> str:
    rows = list(rows)
    if not rows:
        return "# Controller to Connector Map\n\nNo routes matched.\n"
    headers = [key for key in rows[0] if not key.startswith("_")]
    lines = [
        "# Controller to Connector Map",
        "",
        "> Source and destination describe the selected reporting scope. "
        "Conditional active-device paths require engineering verification.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = [
            str(row.get(header, "")).replace("|", "\\|").replace("\n", " ")
            for header in headers
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"
