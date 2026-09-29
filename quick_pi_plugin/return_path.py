"""Conservative, saved-board return-path evidence for Quick PI.

This is a geometric screening tool, not a return-current or impedance solver.
The pure ``audit_return_path`` function accepts JSON-compatible evidence so the
same findings can be shown in a UI, CLI, or report without a KiCad dependency.
``collect_board_evidence`` reads native, *filled* copper zones from pcbnew.
"""
from __future__ import annotations

import math
from typing import Any


def _xy(point: Any, pcbnew: Any) -> list[float]:
    return [pcbnew.ToMM(point.x), pcbnew.ToMM(point.y)]


def _ring(chain: Any, pcbnew: Any) -> list[list[float]]:
    points = [_xy(chain.CPoint(i), pcbnew) for i in range(chain.PointCount())]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def collect_board_evidence(board: Any, signal_net: str, return_nets: list[str] | tuple[str, ...]) -> dict:
    """Read routed tracks, vias, and actual filled return zones from a board.

    An unfilled return zone is explicitly recorded as missing evidence. This
    function does not refill the board or alter the editor. The caller should
    load a saved board if its results must correspond to a saved revision.
    """
    import pcbnew

    signal_net = str(signal_net).strip()
    returns = {str(name).strip() for name in return_nets if str(name).strip()}
    if not signal_net or not returns or signal_net in returns:
        raise ValueError("Choose a signal net and distinct, explicit return net(s).")
    copper_layers = list(board.GetEnabledLayers().CuStack())
    layer_names = {layer: str(board.GetLayerName(layer)) for layer in copper_layers}
    evidence: dict[str, Any] = {
        "signal_net": signal_net, "return_nets": sorted(returns),
        "layer_order": [layer_names[layer] for layer in copper_layers],
        "segments": [], "signal_vias": [], "return_vias": [],
        "reference_regions": [], "unfilled_reference_layers": [], "unsupported_geometry": [],
    }
    for item in board.GetTracks():
        net = str(item.GetNetname())
        if net != signal_net and net not in returns:
            continue
        if isinstance(item, pcbnew.PCB_VIA):
            entry = {
                "net": net, "position": _xy(item.GetPosition(), pcbnew),
                "layers": [layer_names[layer] for layer in copper_layers if item.IsOnLayer(layer)],
            }
            evidence["signal_vias" if net == signal_net else "return_vias"].append(entry)
        elif net == signal_net:
            if isinstance(item, pcbnew.PCB_ARC):
                # Chords can jump over a plane slit. Do not claim coverage for them.
                evidence["unsupported_geometry"].append("Arc on " + layer_names[item.GetLayer()])
                continue
            evidence["segments"].append({
                "layer": layer_names[item.GetLayer()],
                "start": _xy(item.GetStart(), pcbnew), "end": _xy(item.GetEnd(), pcbnew),
                "width_mm": pcbnew.ToMM(item.GetWidth()),
            })
    for zone in board.Zones():
        if zone.GetIsRuleArea() or str(zone.GetNetname()) not in returns:
            continue
        for layer in copper_layers:
            if not zone.IsOnLayer(layer):
                continue
            layer_name = layer_names[layer]
            if not zone.IsFilled() or not zone.HasFilledPolysForLayer(layer):
                evidence["unfilled_reference_layers"].append(layer_name)
                continue
            filled = zone.GetFilledPolysList(layer)
            for i in range(filled.OutlineCount()):
                evidence["reference_regions"].append({
                    "net": str(zone.GetNetname()), "layer": layer_name,
                    "outer": _ring(filled.COutline(i), pcbnew),
                    "holes": [_ring(filled.CHole(i, h), pcbnew)
                              for h in range(filled.HoleCount(i))],
                })
    return evidence


def _on_segment(point: tuple[float, float], a: list[float], b: list[float]) -> bool:
    cross = (point[0]-a[0])*(b[1]-a[1])-(point[1]-a[1])*(b[0]-a[0])
    return abs(cross) < 1e-9 and min(a[0], b[0])-1e-9 <= point[0] <= max(a[0], b[0])+1e-9 and min(a[1], b[1])-1e-9 <= point[1] <= max(a[1], b[1])+1e-9


def _inside_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if _on_segment(point, a, b):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if point[0] < x:
                inside = not inside
    return inside


def _in_region(point: tuple[float, float], region: dict) -> bool:
    return _inside_ring(point, region["outer"]) and not any(
        _inside_ring(point, hole) for hole in region.get("holes", [])
    )


def _finding(level: str, code: str, detail: str, *, layer: str = "", position: list[float] | None = None) -> dict:
    return {"level": level, "code": code, "detail": detail,
            "layer": layer, "position_mm": position}


def audit_return_path(evidence: dict, *, sample_pitch_mm: float = 0.25,
                      return_via_radius_mm: float = 2.0) -> dict:
    """Screen sampled track reference coverage and selected via transitions.

    A sampled clear route is never labelled a proved continuous return plane:
    gaps narrower than the sample pitch and parallel-plane coupling are unknown.
    Reference nets must be chosen by the user; name guessing is unsafe.
    """
    if not math.isfinite(sample_pitch_mm) or sample_pitch_mm <= 0:
        raise ValueError("Sample pitch must be finite and positive.")
    if not math.isfinite(return_via_radius_mm) or return_via_radius_mm <= 0:
        raise ValueError("Return-via radius must be finite and positive.")
    layers = list(evidence.get("layer_order", []))
    if len(layers) != len(set(layers)) or not layers:
        raise ValueError("Provide an ordered list of enabled copper layers.")
    if not evidence.get("signal_net") or not evidence.get("return_nets"):
        raise ValueError("Signal and explicit return net names are required.")
    positions = {name: index for index, name in enumerate(layers)}
    regions = [item for item in evidence.get("reference_regions", [])
               if item.get("net") in evidence["return_nets"]]
    by_layer: dict[str, list[dict]] = {name: [] for name in layers}
    for region in regions:
        if region["layer"] in by_layer:
            by_layer[region["layer"]].append(region)
    unfilled = set(evidence.get("unfilled_reference_layers", []))
    findings: list[dict] = []
    segments = list(evidence.get("segments", []))
    if not segments:
        findings.append(_finding("unknown", "NO_ROUTED_TRACKS", "No routed straight signal tracks were supplied."))
    for segment in segments:
        layer = segment["layer"]
        if layer not in positions:
            raise ValueError("Signal segment uses an unknown copper layer: " + layer)
        a, b = segment["start"], segment["end"]
        length = math.dist(a, b)
        count = max(1, math.ceil(length / sample_pitch_mm))
        adjacent = [layers[i] for i in (positions[layer]-1, positions[layer]+1) if 0 <= i < len(layers)]
        if not adjacent or not any(by_layer[name] for name in adjacent):
            level = "unknown" if any(name in unfilled for name in adjacent) else "warning"
            findings.append(_finding(level, "NO_ADJACENT_REFERENCE",
                "No filled selected return-net zone was found on an adjacent copper layer; unfilled zones need refill before review."
                if level == "unknown" else "No filled selected return-net zone was found on an adjacent copper layer.",
                layer=layer, position=[(a[0]+b[0])/2, (a[1]+b[1])/2]))
            continue
        uncovered = None
        for i in range(count + 1):
            t = i / count
            point = (a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1]))
            if not any(_in_region(point, region) for name in adjacent for region in by_layer[name]):
                uncovered = list(point)
                break
        if uncovered is not None:
            findings.append(_finding("warning", "REFERENCE_GAP_SAMPLED",
                f"A sampled point lacks filled return copper on either adjacent layer (sample pitch {sample_pitch_mm:g} mm).",
                layer=layer, position=uncovered))
    for arc in evidence.get("unsupported_geometry", []):
        findings.append(_finding("unknown", "UNSUPPORTED_GEOMETRY",
            "Coverage for " + str(arc) + " was not checked."))
    # Only a via with routed segments on two distinct layers is a known signal
    # transition. A physical through-via may span unused copper layers.
    for via in evidence.get("signal_vias", []):
        xy = via["position"]
        connected = set()
        for segment in segments:
            if (math.dist(segment["start"], xy) <= 0.02 or
                    math.dist(segment["end"], xy) <= 0.02):
                connected.add(segment["layer"])
        if len(connected) < 2:
            findings.append(_finding("unknown", "TRANSITION_LAYERS_UNKNOWN",
                "Signal via has fewer than two evidenced connected routing layers; its return transfer cannot be assessed.",
                position=xy))
            continue
        reference_layers = {layers[i] for layer in connected for i in
                            (positions[layer]-1, positions[layer]+1) if 0 <= i < len(layers)
                            and by_layer[layers[i]] and any(_in_region(tuple(xy), region)
                                for region in by_layer[layers[i]])}
        if len(reference_layers) < 2:
            findings.append(_finding("unknown", "REFERENCE_TRANSFER_UNKNOWN",
                "The selected filled zones do not identify two distinct local reference layers at this signal transition.",
                position=xy))
            continue
        nearby = [item for item in evidence.get("return_vias", [])
                  if item.get("net") in evidence["return_nets"]
                  and reference_layers.issubset(set(item.get("layers", [])))
                  and math.dist(xy, item["position"]) <= return_via_radius_mm]
        if not nearby:
            findings.append(_finding("warning", "NO_NEARBY_RETURN_VIA",
                f"No selected return-net via spanning the local reference layers lies within {return_via_radius_mm:g} mm.",
                position=xy))
    warnings = sum(item["level"] == "warning" for item in findings)
    unknowns = sum(item["level"] == "unknown" for item in findings)
    return {"signal_net": evidence["signal_net"], "return_nets": list(evidence["return_nets"]),
            "findings": findings, "warning_count": warnings, "unknown_count": unknowns,
            "checked_segment_count": len(segments), "checked_signal_via_count": len(evidence.get("signal_vias", [])),
            "basis": "Sampled saved-board geometry; not a proof of return current, plane continuity, loop inductance, or impedance."}


def analyze_return_path(board: Any, signal_net: str, return_nets: list[str] | tuple[str, ...],
                        *, sample_pitch_mm: float = 0.25, return_via_radius_mm: float = 2.0) -> dict:
    """Convenience entry point for a caller holding a native pcbnew BOARD."""
    evidence = collect_board_evidence(board, signal_net, return_nets)
    return audit_return_path(evidence, sample_pitch_mm=sample_pitch_mm,
                             return_via_radius_mm=return_via_radius_mm)
