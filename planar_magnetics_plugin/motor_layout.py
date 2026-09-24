"""Annular *logical* winding projection for phase/slot review.

Each polygon indicates one coil's start and return slots inside a dedicated
phase display lane. It is not a copper trace, spacing check, end-turn route,
or manufacturable PCB winding pattern.
"""

from __future__ import annotations

import math
from typing import Any


def annular_coil_paths(winding: dict[str, Any], inner_radius_mm: float, outer_radius_mm: float) -> list[dict[str, Any]]:
    """Project coils onto concentric phase lanes with explicit dimensions."""
    inner = float(inner_radius_mm)
    outer = float(outer_radius_mm)
    if not math.isfinite(inner) or not math.isfinite(outer) or inner <= 0 or outer <= inner:
        raise ValueError("Preview radii require 0 < inner radius < outer radius (mm).")
    slots = int(winding["slots"])
    phases = int(winding["phases"])
    pitch = int(winding["coil_pitch_slots"])
    if slots < 4 or phases < 2 or pitch < 1 or pitch >= slots:
        raise ValueError("Winding slots, phases, or coil pitch are invalid for annular preview.")
    lane = (outer - inner) / phases
    result = []
    for coil in winding["coils"]:
        phase = int(coil["phase"])
        start_slot = int(coil["start_slot"])
        end_slot = int(coil["end_slot"])
        if not 0 <= phase < phases or not 1 <= start_slot <= slots or not 1 <= end_slot <= slots:
            raise ValueError("Coil phase or slot is outside the winding preview range.")
        if (start_slot - 1 + pitch) % slots + 1 != end_slot:
            raise ValueError("Coil end slot does not match the winding pitch.")
        r0 = inner + (phase + .16) * lane
        r1 = inner + (phase + .84) * lane
        theta = 2 * math.pi * (start_slot - 1) / slots
        sweep = 2 * math.pi * pitch / slots
        segments = max(12, math.ceil(sweep * 16))
        outer_arc = [(r1 * math.cos(theta + sweep * index / segments),
                      r1 * math.sin(theta + sweep * index / segments)) for index in range(segments + 1)]
        inner_arc = [(r0 * math.cos(theta + sweep * index / segments),
                      r0 * math.sin(theta + sweep * index / segments)) for index in range(segments, -1, -1)]
        result.append({
            "phase": phase,
            "start_slot": start_slot,
            "end_slot": end_slot,
            "polarity": int(coil["polarity"]),
            "inner_radius_mm": r0,
            "outer_radius_mm": r1,
            "points_mm": outer_arc + inner_arc + [outer_arc[0]],
            "start_mm": (r1 * math.cos(theta), r1 * math.sin(theta)),
        })
    return result
