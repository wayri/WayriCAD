"""Read-only reference-net suggestions from saved filled-zone coverage.

Suggestions are candidates for explicit review, never selected return domains
or evidence of electrical continuity. Ground names only break coverage ties.
"""
from __future__ import annotations

import math

from .return_path import audit_return_path, collect_board_evidence
from .return_setup import suggest_return_nets


def _validate(sample_pitch_mm, max_candidates):
    if (isinstance(sample_pitch_mm, bool) or not isinstance(sample_pitch_mm, (int, float))
            or not math.isfinite(sample_pitch_mm) or sample_pitch_mm <= 0):
        raise ValueError("Sample pitch must be finite and positive.")
    if (isinstance(max_candidates, bool) or not isinstance(max_candidates, int)
            or not 1 <= max_candidates <= 32):
        raise ValueError("max_candidates must be an integer from 1 to 32.")


def suggest_return_candidates_from_evidence(evidence, *, sample_pitch_mm=.5,
                                            max_candidates=32, zone_inventory=None):
    """Rank each zone net separately without mutating JSON-compatible evidence.

    ``zone_inventory`` optionally maps each net to its unfilled layer names;
    the collector's legacy global unfilled list cannot establish net identity.
    Missing coverage counts as zero, including segments without any adjacent
    reference evidence. Sampling cannot establish a continuous return path.
    """
    _validate(sample_pitch_mm, max_candidates)
    signal = evidence.get("signal_net")
    if not signal:
        raise ValueError("Choose a signal net.")
    inventory = {str(net): list(layers) for net, layers in (zone_inventory or {}).items()}
    for region in evidence.get("reference_regions", []):
        if region.get("net"):
            inventory.setdefault(region["net"], [])
    names = sorted((net for net in inventory if net and net != signal),
                   key=lambda net: (net.casefold(), net))
    evaluated = names[:max_candidates]
    ground_order = {row["name"]: i for i, row in enumerate(suggest_return_nets(names, signal))}
    total = sum(max(1, math.ceil(math.dist(segment["start"], segment["end"])
                                 / sample_pitch_mm))+1
                for segment in evidence.get("segments", []))
    rows = []
    for net in evaluated:
        selected = dict(evidence)
        selected["return_nets"] = [net]
        for field in ("reference_regions", "return_vias"):
            selected[field] = [row for row in evidence.get(field, []) if row.get("net") == net]
        selected["terminals"] = [row for row in evidence.get("terminals", [])
                                 if row.get("net") in (signal, net)]
        selected["unfilled_reference_layers"] = list(inventory[net])
        audit = audit_return_path(selected, sample_pitch_mm=sample_pitch_mm)
        covered = sum(row["covered_sample_count"] for row in audit["coverage"])
        unsupported = list(evidence.get("unsupported_geometry", []))
        if unsupported:
            status, reason = "UNSUPPORTED_ROUTE_EVIDENCE", "Unsupported signal geometry was not sampled; whole-route coverage is unknown."
        elif inventory[net]:
            status, reason = "UNFILLED_REFERENCE_EVIDENCE", "Some reference zones have no saved fill; coverage is unknown until refill and review."
        elif not total:
            status, reason = "NO_ROUTED_EVIDENCE", "No straight routed signal segments were available."
        elif not selected["reference_regions"]:
            status, reason = "MISSING_FILLED_EVIDENCE", "No saved filled copper polygons were available for this net."
        elif covered == total:
            status, reason = "SAMPLED_COVERAGE", "All sampled straight-route points have adjacent filled copper; continuity remains unknown."
        elif covered:
            status, reason = "PARTIAL_SAMPLED_COVERAGE", "Only some sampled straight-route points have adjacent filled copper."
        else:
            status, reason = "NO_SAMPLED_COVERAGE", "No sampled straight-route points have adjacent filled copper."
        rows.append({"net": net, "covered_samples": covered, "total_samples": total,
                     "coverage_fraction": covered/total if total and not unsupported and not inventory[net] else None,
                     "status": status, "reason": reason,
                     "evidence_status": ("UNFILLED_REFERENCE_EVIDENCE" if inventory[net] else
                                         "FILLED_REFERENCE_EVIDENCE" if selected["reference_regions"] else
                                         "MISSING_FILLED_EVIDENCE"),
                     "unfilled_reference_layers": sorted(set(inventory[net])),
                     "unsupported_geometry": unsupported})
    rows.sort(key=lambda row: (-row["covered_samples"], ground_order.get(row["net"], len(names)),
                               row["net"].casefold(), row["net"]))
    return {"candidates": rows, "candidate_count": len(names), "evaluated_count": len(rows),
            "truncated": len(names) > len(rows), "omitted_nets": names[max_candidates:],
            "sample_pitch_mm": sample_pitch_mm,
            "limitations": ["Candidates require explicit user review; no return net is selected.",
                            "Filled-zone sampling does not prove connectivity, continuity or a closed current loop.",
                            "Arcs and gaps smaller than the sampling pitch remain unresolved.",
                            "When truncated, only the first net names in deterministic alphabetical order were evaluated."]}


def suggest_return_candidates(board, signal_net, sample_pitch_mm=.5, max_candidates=32):
    """Collect one read-only board snapshot and suggest bounded reference nets.

    Zones are never refilled and no board object is modified. Callers should
    supply a saved board to bind suggestions to saved source geometry.
    """
    _validate(sample_pitch_mm, max_candidates)
    signal_net = str(signal_net).strip()
    if not signal_net:
        raise ValueError("Choose a signal net.")
    layers = list(board.GetEnabledLayers().CuStack())
    inventory = {}
    for zone in board.Zones():
        net = str(zone.GetNetname())
        if zone.GetIsRuleArea() or not net or net == signal_net:
            continue
        for layer in layers:
            if not zone.IsOnLayer(layer):
                continue
            unfilled = inventory.setdefault(net, [])
            if not zone.IsFilled() or not zone.HasFilledPolysForLayer(layer):
                unfilled.append(str(board.GetLayerName(layer)))
    names = sorted(inventory, key=lambda net: (net.casefold(), net))[:max_candidates]
    if names:
        evidence = collect_board_evidence(board, signal_net, names)
    else:
        evidence = {"signal_net": signal_net, "segments": []}
    # Keep omitted inventory names so the pure helper can report truncation,
    # while expensive polygon collection stays bounded to evaluated nets.
    return suggest_return_candidates_from_evidence(
        evidence, sample_pitch_mm=sample_pitch_mm,
        max_candidates=max_candidates, zone_inventory=inventory)
