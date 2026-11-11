"""Cheh Lin et al. (2023), DOI 10.3390/mi14071284, conditional geometry.

Figure 1/Table 1 supply dimensions, not source CAD. The selected unresolved
interpretations are data in ``geometry_spec``; no performance is claimed.
"""
from __future__ import annotations


MM = 1e-3


def geometry_spec():
    """Return fresh, JSON-compatible geometry and provenance, in millimetres.

    Axes retain the audit/paper convention (+x across the guide, +y away from
    feed, +z above PCB). Audit y is translated +14.5 to centre the full board.
    Copper is represented by zero-thickness PEC sheets at substrate interfaces.
    """
    shift = 14.5

    def rectangle(x0, y0, x1, y1, z=0.0, role="top"):
        return {"role": role, "vertices_mm": [
            [x0, y0 + shift, z], [x1, y0 + shift, z],
            [x1, y1 + shift, z], [x0, y1 + shift, z]]}

    slots = [(-11.5, -5.5, 11.5, 1.5),
             (-11.5, -25.5, -5.5, -5.5),
             (5.5, -25.5, 11.5, -5.5)]
    # Tile the actual remaining copper, so the preview cannot fill the U slot.
    xs = [-32.0, -11.5, -5.5, 5.5, 11.5, 32.0]
    ys = [-28.0, -25.5, -5.5, 1.5, 28.0]
    sheets = []
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            x, y = (x0 + x1) / 2, (y0 + y1) / 2
            if not any(a < x < c and b < y < d for a, b, c, d in slots):
                sheets.append(rectangle(x0, y0, x1, y1))
    sheets.append(rectangle(-1.475, -57.0, 1.475, -47.0, role="feed"))
    sheets.append({"role": "taper", "vertices_mm": [
        [-1.475, -32.5, 0.0], [1.475, -32.5, 0.0],
        [10.0, -13.5, 0.0], [-10.0, -13.5, 0.0]]})
    sheets.append(rectangle(-32.0, -57.0, 32.0, 28.0, -1.6, "ground"))
    centers = {(x, -24.0 + 8 * n) for x in (-28.0, 28.0) for n in range(7)}
    centers.update((-28.0 + 8 * n, 24.0) for n in range(8))
    assumptions = [
        {"id": "origin", "status": "convention", "detail":
         "Audit main-SIW centre translated y +14.5 mm; full 64 x 85 mm board centred. "
         "Axes unchanged; z=0 is substrate top, not finite copper top."},
        {"id": "slot", "status": "assumed", "detail":
         "sx=0, sy=-2 locate transverse-bar centre in audit coordinates; sl=23 is "
         "outer transverse span, sw=7; sl2=20 excludes the bar, sw2=6; opens toward -y."},
        {"id": "vias", "status": "assumed", "detail":
         "20 unique centres: side x=+/-28, audit y=-24:8:24; end audit y=24, "
         "x=-28:8:28. a4=2 interpreted as hole-edge clearance; lattice phase inferred."},
        {"id": "posts", "status": "idealized", "detail":
         "Genuine radius-2 mm solid PEC cylinders join ground to top copper, not solid "
         "replacement walls. Published plated-hole/barrel/pad dimensions are unknown."},
        {"id": "width_conflict", "status": "unresolved", "detail":
         "Table 1 Weq=52, Wsiw=56, d=4, p=8 conflict with Eq. (7), which gives "
         "49.870769 mm, not 56 mm. Conditional lattice follows Table 1; no equation repair."},
        {"id": "copper", "status": "idealized", "detail":
         "Published 0.035 mm copper is collapsed to zero-thickness PEC sheets at z=0 "
         "and -1.6 mm; no conductor loss or roughness. Slot removes only top copper."},
        {"id": "dra_contact", "status": "assumed", "detail":
         "40 x 40 x 21 mm DRA directly seated at z=0; glue and air gap omitted, "
         "not specified. DRA audit centre (0,-2) agrees with a1=6,a2=10,a3=12."},
        {"id": "feed", "status": "idealized", "detail":
         "One bounded 2.95 x 1.6 mm vertical ideal port at board feed edge y=-42.5 mm; "
         "50 ohm reference is a downstream port setting, not a proven matched launch. "
         "Female SMA, solder, connector loss and launch details omitted."},
        {"id": "validation", "status": "unvalidated", "detail":
         "Dimension-derived conditional reconstruction, not source-CAD equivalence or "
         "validated waves/lobes. No solve, convergence, bandwidth or gain claim. "
         "Section 2 TEy_1delta1 estimate differs from Figure 6 TEy_2delta1 labels."},
    ]
    return {
        "kind": "research_solids", "unit": "mm",
        "doi": "10.3390/mi14071284", "source": "Figure 1, Table 1; pp. 2-3",
        "audit_to_model_shift_mm": [0.0, shift, 0.0],
        "board_mm": [64.0, 85.0], "substrate_height_mm": 1.6,
        "published_copper_thickness_mm": 0.035,
        "bbox_mm": [-32.0, -42.5, 32.0, 42.5],
        "main_region_bounds_mm": [-32.0, -13.5, -1.6, 32.0, 42.5, 0.0],
        "dielectrics": [
            {"role": "substrate", "bounds_mm": [-32.0, -42.5, -1.6, 32.0, 42.5, 0.0],
             "er": 4.6, "loss_tangent": 0.019},
            {"role": "dra", "bounds_mm": [-20.0, -7.5, 0.0, 20.0, 32.5, 21.0],
             "er": 10.0, "loss_tangent": 0.0019}],
        "sheets": sheets,
        "slot_rectangles_mm": [[a, b + shift, c, d + shift] for a, b, c, d in slots],
        "vias": [{"x_mm": x, "y_mm": y + shift, "z0_mm": -1.6,
                  "z1_mm": 0.0, "radius_mm": 2.0} for x, y in sorted(centers)],
        "ports": [[[0.0, -42.5, -1.6], [0.0, -42.5, 0.0]]],
        "port_widths_mm": [2.95], "port_reference_ohm": 50.0,
        "assumptions": assumptions,
    }


def build(em, np, config, template):
    """Commit conditional geometry only; return the standard research model tuple."""
    from .research_geometry import (
        _base_model, _finish, _material, _polygon, _rect, _vertical_port,
    )

    spec = geometry_spec()
    if config["advanced"]["conductor"] != "pec":
        raise ValueError("SIW+DRA geometry supports only ideal PEC sheets and solid posts")
    if config["advanced"]["boundary"] == "pml":
        raise ValueError("SIW+DRA PML enclosure has not been geometry-qualified")
    if config["air_margin_mm"] <= 21.0:
        raise ValueError("SIW+DRA requires air_margin_mm > 21 for DRA clearance")
    model, air = _base_model(em, config, 64.0, 85.0, 1.6, 21.0)
    for item in spec["dielectrics"]:
        x0, y0, z0, x1, y1, z1 = item["bounds_mm"]
        solid = em.geo.Box((x1 - x0) * MM, (y1 - y0) * MM, (z1 - z0) * MM,
                           position=(x0 * MM, y0 * MM, z0 * MM))
        if item["role"] == "substrate":
            substrate = solid
        solid.set_material(_material(em, item["er"], item["loss_tangent"]))
    top = _rect(em, -32.0, -13.5, 64.0, 56.0)
    for x0, y0, x1, y1 in spec["slot_rectangles_mm"]:
        top = em.geo.remove(top, _rect(em, x0, y0, x1 - x0, y1 - y0))
    for item in spec["sheets"]:
        if item["role"] in ("feed", "taper"):
            top = em.geo.add(top, _polygon(em, [v[:2] for v in item["vertices_mm"]]))
    ground = _rect(em, -32.0, -42.5, 64.0, 85.0, -1.6)
    conductors = [top.set_material(em.lib.PEC), ground.set_material(em.lib.PEC)]
    for via in spec["vias"]:
        post = em.geo.Cylinder(via["radius_mm"] * MM,
                               (via["z1_mm"] - via["z0_mm"]) * MM,
                               cs=em.GCS.displace(via["x_mm"] * MM,
                                                  via["y_mm"] * MM, via["z0_mm"] * MM))
        # Remove dielectric from the metal volume, retaining the actual cylinder.
        substrate = em.geo.remove(substrate, post, remove_tool=False)
        # EMerge's PEC material alone does not install a volume exclusion or
        # shell PEC condition. VoidAttribute installs both during commit.
        post.properties += em.VoidAttribute()
        conductors.append(post.set_material(em.lib.PEC))
    port = _vertical_port(em, np, 0.0, -42.5, -1.6, 0.0, 2.95)
    widths = [2.95 * MM]
    assumptions = [item["detail"] for item in spec["assumptions"]]
    if template.get("model_scope"):
        assumptions.insert(0, template["model_scope"])
    _finish(model, config, conductors, [port], widths, [1.6 * MM], [em.ZAX],
            spec, [1 + 0j], "Single bounded ideal edge microstrip port", assumptions)
    return model, air, [port], widths, 1.6 * MM, spec["bbox_mm"]
