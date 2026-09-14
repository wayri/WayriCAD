"""Geometry-based return-path and discontinuity checks."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Iterable

try:
    from .diff_pairs import find_mate as _shared_find_mate
except ImportError:  # Direct-file execution (automation) has no package parent.
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("_wayricad_diff_pairs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "diff_pairs.py"))
    _diff_pairs = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_diff_pairs)
    _shared_find_mate = _diff_pairs.find_mate


@dataclass(frozen=True)
class CopperSegment:
    net: str
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]
    width_mm: float


@dataclass(frozen=True)
class ViaPoint:
    net: str
    position: tuple[float, float]
    layers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceRegion:
    net: str
    layer: str
    bounds: tuple[float, float, float, float]

    def contains(self, point: tuple[float, float]) -> bool:
        x1, y1, x2, y2 = self.bounds
        return min(x1, x2) <= point[0] <= max(x1, x2) and min(y1, y2) <= point[1] <= max(y1, y2)


@dataclass
class Finding:
    severity: str
    check: str
    net: str
    layer: str
    x_mm: float
    y_mm: float
    detail: str
    remedy: str


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    segments: list[CopperSegment] = field(default_factory=list)
    vias: list[ViaPoint] = field(default_factory=list)


class ReturnPathAnalyzer:
    def __init__(self, ground_patterns: Iterable[str] = ("GND", "AGND", "DGND", "PGND", "VSS")) -> None:
        self.ground_patterns = tuple(value.upper() for value in ground_patterns if value)

    def is_return_net(self, net: str) -> bool:
        upper = net.upper().strip("/ ")
        return any(token in upper for token in self.ground_patterns)

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    @staticmethod
    def _key(point: tuple[float, float], tolerance_mm: float = 0.02) -> tuple[int, int]:
        return round(point[0] / tolerance_mm), round(point[1] / tolerance_mm)

    def audit(self, segments: Iterable[CopperSegment], vias: Iterable[ViaPoint],
              references: Iterable[ReferenceRegion], return_via_radius_mm: float = 2.0,
              stub_limit_mm: float = 5.0, differential_gap_limit_mm: float = 1.0,
              differential_skew_limit_mm: float = 0.5) -> AuditResult:
        signal_segments = [segment for segment in segments if segment.net and not self.is_return_net(segment.net)]
        all_vias = list(vias); regions = list(references); findings: list[Finding] = []
        return_vias = [via for via in all_vias if self.is_return_net(via.net)]

        for via in (item for item in all_vias if item.net and not self.is_return_net(item.net)):
            nearest = min((self._distance(via.position, ground.position) for ground in return_vias), default=math.inf)
            if nearest > return_via_radius_mm:
                findings.append(Finding(
                    "warning", "Layer transition return via", via.net, "/".join(via.layers), *via.position,
                    f"No configured return-net via within {return_via_radius_mm:g} mm; nearest is " +
                    ("unavailable." if math.isinf(nearest) else f"{nearest:.2f} mm."),
                    "Add a return via beside the signal transition or verify an uninterrupted plane transition.",
                ))

        for segment in signal_segments:
            midpoint = ((segment.start[0] + segment.end[0]) / 2, (segment.start[1] + segment.end[1]) / 2)
            candidates = [region for region in regions if self.is_return_net(region.net) and region.layer != segment.layer]
            if candidates and not any(region.contains(midpoint) for region in candidates):
                findings.append(Finding(
                    "warning", "Reference-plane coverage", segment.net, segment.layer, *midpoint,
                    "Segment midpoint is outside every supplied return-plane region.",
                    "Inspect plane splits/voids and reroute over continuous reference copper.",
                ))

        by_net: dict[str, list[CopperSegment]] = {}
        for segment in signal_segments:
            by_net.setdefault(segment.net, []).append(segment)
        for net, net_segments in by_net.items():
            degree: dict[tuple[int, int], int] = {}
            for segment in net_segments:
                for point in (segment.start, segment.end):
                    key = self._key(point); degree[key] = degree.get(key, 0) + 1
            branch_keys = {key for key, count in degree.items() if count > 2}
            for segment in net_segments:
                length = self._distance(segment.start, segment.end)
                if length >= stub_limit_mm and any(self._key(point) in branch_keys for point in (segment.start, segment.end)):
                    midpoint = ((segment.start[0] + segment.end[0]) / 2, (segment.start[1] + segment.end[1]) / 2)
                    findings.append(Finding(
                        "warning", "Possible routed stub", net, segment.layer, *midpoint,
                        f"A {length:.2f} mm branch leaves a node with more than two routed connections.",
                        "Confirm intended topology; shorten/remove the branch or validate it with SI simulation.",
                    ))
        checked_pairs = set()
        for net, net_segments in by_net.items():
            mate = differential_mate(net, by_net)
            pair_key = tuple(sorted((net, mate))) if mate else ()
            if not mate or pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            mate_segments = by_net[mate]
            length = sum(self._distance(item.start, item.end) for item in net_segments)
            mate_length = sum(self._distance(item.start, item.end) for item in mate_segments)
            skew = abs(length - mate_length)
            anchor = net_segments[0].start
            layers = ",".join(sorted({item.layer for item in net_segments + mate_segments}))
            if skew > differential_skew_limit_mm:
                findings.append(Finding(
                    "warning", "Differential-pair skew", f"{net} / {mate}", layers, *anchor,
                    f"Routed-length difference is {skew:.2f} mm (limit {differential_skew_limit_mm:g} mm).",
                    "Length-match the pair using the protocol timing budget and KiCad constraints.",
                ))
            uncoupled = 0
            for segment in net_segments:
                midpoint = ((segment.start[0] + segment.end[0]) / 2, (segment.start[1] + segment.end[1]) / 2)
                same_layer = [item for item in mate_segments if item.layer == segment.layer]
                nearest = min((self._distance(midpoint, ((item.start[0] + item.end[0]) / 2,
                                                          (item.start[1] + item.end[1]) / 2))
                               for item in same_layer), default=math.inf)
                if nearest > differential_gap_limit_mm:
                    uncoupled += 1
            if uncoupled:
                findings.append(Finding(
                    "warning", "Differential-pair uncoupling", f"{net} / {mate}", layers, *anchor,
                    f"{uncoupled} primary segment(s) have no mate midpoint within {differential_gap_limit_mm:g} mm on the same layer.",
                    "Inspect coupling, layer transitions, neck-downs, and reference continuity.",
                ))
        return AuditResult(findings, signal_segments, all_vias)


def differential_mate(net: str, available: Iterable[str]) -> str:
    """Shared pattern detector with the legacy suffix fallbacks."""
    names = list(available)
    mate = _shared_find_mate(net, names)
    if mate:
        return mate
    candidates = []
    if net.endswith("_P"): candidates.append(net[:-2] + "_N")
    if net.endswith("_N"): candidates.append(net[:-2] + "_P")
    if net.endswith("+"): candidates.append(net[:-1] + "-")
    if net.endswith("-"): candidates.append(net[:-1] + "+")
    lookup = {value.casefold(): value for value in names}
    return next((lookup[value.casefold()] for value in candidates if value.casefold() in lookup), "")
