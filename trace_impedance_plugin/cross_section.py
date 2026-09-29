"""Explicit-input transmission-line estimates separate from board extraction."""

import math

from . import emerge_lines


TOPOLOGIES = (
    "microstrip", "symmetric-stripline", "cpw", "grounded-cpw", "edge-coupled-stripline"
)


def estimate(topology, width_mm, height_mm, er, *, copper_mm=0.0, gap_mm=None):
    """Return a labelled quasi-static estimate or reject unsupported geometry."""
    name = str(topology).strip().lower()
    if name not in TOPOLOGIES:
        raise ValueError("Unsupported cross-section topology: " + name)
    w, h, dielectric, copper = map(float, (width_mm, height_mm, er, copper_mm))
    if not all(math.isfinite(v) for v in (w, h, dielectric, copper)):
        raise ValueError("All cross-section inputs must be finite")
    if copper < 0:
        raise ValueError("Copper thickness cannot be negative")
    pair = name == "edge-coupled-stripline"
    coplanar = name in ("cpw", "grounded-cpw")
    if pair or coplanar:
        if gap_mm is None:
            raise ValueError("A measured pair or lateral-ground gap is required")
        gap = float(gap_mm)
        if not math.isfinite(gap) or gap <= 0:
            raise ValueError("Gap must be positive and finite")
        if copper:
            raise ValueError("This coupled/coplanar model assumes zero copper thickness; use a field solver for finite copper")
    else:
        gap = None
    if name == "microstrip":
        z0, eeff = emerge_lines.microstrip(w, h, copper, dielectric)
        quantity = "single_ended_z0_ohm"
    elif name == "symmetric-stripline":
        z0, eeff = emerge_lines.stripline(w, h, copper, dielectric)
        quantity = "single_ended_z0_ohm"
    elif coplanar:
        z0, eeff = emerge_lines.coplanar(w, gap, h, dielectric, backside_ground=name == "grounded-cpw")
        quantity = "single_ended_z0_ohm"
    else:
        z0 = emerge_lines.edge_coupled_stripline(w, gap, h, dielectric)
        eeff = dielectric
        quantity = "differential_z0_ohm"
    return {
        "status": "ESTIMATE",
        "topology": name,
        quantity: z0,
        "effective_permittivity": eeff,
        "geometry": {"width_mm": w, "height_mm": h, "copper_mm": copper,
                     "gap_mm": gap, "relative_permittivity": dielectric},
        "source": "EMerge calculator 50283a2; quasi-static closed-form cross section",
        "limitations": [
            "Manual geometry only; not verified against the selected board section.",
            "Requires homogeneous dielectric and continuous reference conductors.",
            "No soldermask, finite lateral-ground width, via transition, roughness, loss or channel compliance.",
        ],
    }
