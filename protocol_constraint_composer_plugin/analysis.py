"""Protocol detection and reviewed KiCad custom-rule generation."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolPreset:
    name: str
    patterns: tuple[str, ...]
    width_mm: float
    clearance_mm: float
    diff_gap_mm: float
    max_skew_mm: float
    target_ohm: float


PRESETS = {
    preset.name: preset for preset in (
        ProtocolPreset("USB2", ("*USB*D+*", "*USB*D-*", "*USB*_P", "*USB*_N"), 0.15, 0.15, 0.15, 0.50, 90),
        ProtocolPreset("USB3/4", ("*SSTX*", "*SSRX*", "*TX_P", "*TX_N", "*RX_P", "*RX_N"), 0.12, 0.15, 0.15, 0.15, 90),
        ProtocolPreset("CAN", ("*CANH*", "*CANL*", "*CAN_H*", "*CAN_L*"), 0.20, 0.20, 0.20, 2.0, 120),
        ProtocolPreset("Ethernet", ("*ETH*P*", "*ETH*N*", "*MDI*P*", "*MDI*N*"), 0.15, 0.20, 0.15, 0.50, 100),
        ProtocolPreset("PCIe/SerDes", ("*PCIE*", "*SERDES*"), 0.12, 0.20, 0.15, 0.10, 100),
        ProtocolPreset("DDR", ("*DDR*", "*DQS*", "*DQ[0-9]*", "*CLK*"), 0.12, 0.15, 0.0, 0.25, 50),
        ProtocolPreset("RS-485", ("*RS485*", "*485_A*", "*485_B*"), 0.20, 0.20, 0.20, 2.0, 120),
        ProtocolPreset("RF", ("*RF*", "*ANT*"), 0.25, 0.30, 0.0, 0.0, 50),
    )
}


@dataclass(frozen=True)
class Assignment:
    protocol: str
    net: str
    confidence: str


def detect_protocols(nets: list[str], presets: dict[str, ProtocolPreset] = PRESETS) -> list[Assignment]:
    assignments = []
    for net in nets:
        matched = [preset.name for preset in presets.values()
                   if any(fnmatch.fnmatchcase(net.casefold(), pattern.casefold()) for pattern in preset.patterns)]
        if matched:
            assignments.append(Assignment(matched[0], net, "ambiguous" if len(matched) > 1 else "pattern"))
    return assignments


def generate_rules(assignments: list[Assignment], presets: dict[str, ProtocolPreset] = PRESETS) -> str:
    blocks = ["# BEGIN KIWAY MANAGED PROTOCOL RULES"]
    by_protocol: dict[str, list[str]] = {}
    for assignment in assignments: by_protocol.setdefault(assignment.protocol, []).append(assignment.net)
    for protocol, nets in sorted(by_protocol.items()):
        preset = presets[protocol]
        condition = " || ".join(f"A.NetName == '{net.replace(chr(39), '')}'" for net in sorted(set(nets)))
        blocks.extend([
            f'(rule "KiWay {protocol} geometry"', f'  (condition "{condition}")',
            f'  (constraint track_width (min {preset.width_mm:g}mm))',
            f'  (constraint clearance (min {preset.clearance_mm:g}mm))', ')',
        ])
        if preset.diff_gap_mm:
            blocks.extend([f'(rule "KiWay {protocol} differential gap"',
                           f'  (condition "{condition}")',
                           f'  (constraint diff_pair_gap (opt {preset.diff_gap_mm:g}mm))',
                           f'  (constraint skew (max {preset.max_skew_mm:g}mm))', ')'])
    blocks.append("# END KIWAY MANAGED PROTOCOL RULES")
    return "\n".join(blocks) + "\n"


def merge_managed_rules(existing: str, generated: str) -> str:
    begin, end = "# BEGIN KIWAY MANAGED PROTOCOL RULES", "# END KIWAY MANAGED PROTOCOL RULES"
    if begin in existing and end in existing:
        prefix, remainder = existing.split(begin, 1); _old, suffix = remainder.split(end, 1)
        return prefix.rstrip() + "\n\n" + generated.rstrip() + suffix
    base = existing.rstrip() or "(version 1)"
    return base + "\n\n" + generated
