"""Conservative PDN topology and decoupling proximity checks."""

from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PadNode:
    reference: str
    pad: str
    net: str
    x_mm: float
    y_mm: float
    value: str = ""


@dataclass(frozen=True)
class PdnFinding:
    severity: str
    rail: str
    load: str
    check: str
    detail: str


def matches_any(value: str, patterns: str) -> bool:
    return any(fnmatch.fnmatchcase(value.casefold(), pattern.strip().casefold())
               for pattern in patterns.split(",") if pattern.strip())


def analyze_decoupling(pads: list[PadNode], rail_patterns: str, ground_patterns: str,
                       capacitor_patterns: str = "C*", load_patterns: str = "U*",
                       maximum_distance_mm: float = 3.0) -> list[PdnFinding]:
    rails = [pad for pad in pads if matches_any(pad.net, rail_patterns)]
    grounds = {pad.reference for pad in pads if matches_any(pad.net, ground_patterns)}
    capacitors = {pad.reference for pad in pads if matches_any(pad.reference, capacitor_patterns) and pad.reference in grounds}
    cap_rail_pads = [pad for pad in rails if pad.reference in capacitors]
    findings = []
    for load in (pad for pad in rails if matches_any(pad.reference, load_patterns)):
        candidates = [cap for cap in cap_rail_pads if cap.net == load.net]
        nearest = min((math.hypot(load.x_mm-cap.x_mm, load.y_mm-cap.y_mm) for cap in candidates), default=math.inf)
        if math.isinf(nearest):
            findings.append(PdnFinding("error", load.net, f"{load.reference}.{load.pad}", "Missing local decoupling",
                                       "No capacitor was found between this rail and a configured ground net."))
        elif nearest > maximum_distance_mm:
            findings.append(PdnFinding("warning", load.net, f"{load.reference}.{load.pad}", "Decoupling distance",
                                       f"Nearest rail/ground capacitor pad is {nearest:.2f} mm away (limit {maximum_distance_mm:g} mm)."))
        else:
            findings.append(PdnFinding("pass", load.net, f"{load.reference}.{load.pad}", "Decoupling distance",
                                       f"Nearest rail/ground capacitor pad is {nearest:.2f} mm away."))
    return findings


def infer_regulators(pads: list[PadNode], keywords: str = "LDO,BUCK,BOOST,REGULATOR,DCDC") -> list[str]:
    tokens = [token.strip().casefold() for token in keywords.split(",") if token.strip()]
    return sorted({pad.reference for pad in pads if any(token in pad.value.casefold() for token in tokens)})
