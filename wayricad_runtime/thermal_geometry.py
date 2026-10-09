"""Shared read-only KiCad copper snapshot for layer thermal and PI coupling.

The snapshot records *physical* copper and plated barrels. It does not infer
dielectric thermal conductivity, via plating thickness, or thermal contact to a
fixture from electrical net membership.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

def _uid(item):
    return item.m_Uuid.AsString()

def _outline(board):
    try:
        import pcbnew
        polygon = pcbnew.SHAPE_POLY_SET()
        valid = board.GetBoardPolygonOutlines(polygon, False)
    except (ImportError, AttributeError, TypeError):
        return [], "KiCad could not extract the saved Edge.Cuts outline."
    if not valid or polygon.OutlineCount() == 0:
        return [], "The saved Edge.Cuts outline is incomplete or invalid."
    contours = []
    for index in range(polygon.OutlineCount()):
        chain = polygon.COutline(index)
        outer = [_mm(pcbnew, chain.CPoint(i)) for i in range(chain.PointCount())]
        holes = []
        for hole_index in range(polygon.HoleCount(index)):
            hole = polygon.CHole(index, hole_index)
            holes.append([_mm(pcbnew, hole.CPoint(i)) for i in range(hole.PointCount())])
        if len(outer) >= 3:
            contours.append({"outer_mm": outer, "holes_mm": holes})
    if not contours:
        return [], "The saved Edge.Cuts outline has no valid closed contour."
    return contours, None




def _mm(api, point):
    return [api.ToMM(point.x), api.ToMM(point.y)]


def _drill(api, item, is_via):
    if is_via:
        value = api.ToMM(item.GetDrillValue())
    else:
        size = item.GetDrillSize()
        if size.x != size.y:
            raise ValueError("Plated or mounting slots require a noncircular thermal-contact model: " + _uid(item))
        value = api.ToMM(size.x)
    return value


def _backdrilled(item):
    for name in ("GetSecondaryDrillSize", "GetTertiaryDrillSize"):
        getter = getattr(item, name, None)
        if getter is not None:
            value = getter()
            if value is not None and value != 0:
                return True
    return False


def collect_thermal_geometry(board, source_path, *, geometry_helpers, curve_tolerance_mm=0.005):
    """Return JSON-safe physical copper, barrel and hole data from a saved PCB.

    The caller loads ``board`` from ``source_path`` and checks that it has not
    changed before consuming the snapshot. A named in-memory test board may use
    an explicit source text with the same stackup; no board mutation occurs.
    """
    import pcbnew as api
    _hole = geometry_helpers._hole
    _polygons = geometry_helpers._polygons
    _shape = geometry_helpers._shape
    stackup = geometry_helpers.stackup

    if getattr(api, "_wayricad_ipc", False) or not hasattr(api, "SHAPE_POLY_SET"):
        raise ValueError("Thermal copper extraction requires native KiCad polygon geometry.")
    path = Path(source_path).resolve()
    data = path.read_bytes()
    board_path = str(board.GetFileName()) if hasattr(board, "GetFileName") else ""
    if board_path and Path(board_path).resolve() != path:
        raise ValueError("Loaded PCB path does not match the saved thermal geometry source.")
    try:
        tolerance = float(curve_tolerance_mm)
        if not 0 < tolerance <= 0.1:
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise ValueError("Curve tolerance must be within (0, 0.1] mm.") from exc
    error = api.FromMM(tolerance)
    outline, outline_issue = _outline(board)
    if outline_issue:
        raise ValueError("A valid closed Edge.Cuts outline is required: " + outline_issue)
    all_points = [p for ring in outline for p in ring["outer_mm"]]
    bbox = [min(p[0] for p in all_points), min(p[1] for p in all_points),
            max(p[0] for p in all_points), max(p[1] for p in all_points)]
    layers = stackup(board, api, data.decode("utf-8-sig"))
    enabled = [row["id"] for row in layers]
    copper = {layer: api.SHAPE_POLY_SET() for layer in enabled}
    holes = {layer: api.SHAPE_POLY_SET() for layer in enabled}
    barrels = []
    mounting_holes = []
    counts = {"tracks_and_arcs": 0, "vias": 0, "pads": 0, "zones": 0,
              "plated_pads": 0, "mounting_holes": 0}

    footprints = list(board.GetFootprints())
    pads = [pad for fp in footprints for pad in fp.Pads()]
    tracks = list(board.GetTracks())
    drawings = list(board.GetDrawings()) + [graphic for fp in footprints for graphic in fp.GraphicalItems()]
    zones = list(board.Zones()) + [zone for fp in footprints for zone in fp.Zones()]
    for item in tracks + pads:
        via = isinstance(item, api.PCB_VIA)
        pad = isinstance(item, api.PAD)
        if via and _backdrilled(item):
            raise ValueError("Backdrilled vias require a stepped-barrel thermal model: " + _uid(item))
        if via:
            top, bottom = item.TopLayer(), item.BottomLayer()
            if top not in enabled or bottom not in enabled:
                raise ValueError("Via span includes unavailable copper layers: " + _uid(item))
            ia, ib = sorted((enabled.index(top), enabled.index(bottom)))
            span = enabled[ia:ib + 1]
        else:
            span = [layer for layer in enabled if item.IsOnLayer(layer)]
        flashed = []
        for layer in span:
            if (via or pad) and not item.FlashLayer(layer):
                continue
            polygon = _shape(api, item, layer, error)
            if polygon.OutlineCount():
                copper[layer].Append(polygon)
                flashed.append(layer)
        if via:
            counts["vias"] += 1
        elif pad:
            counts["pads"] += 1
        else:
            counts["tracks_and_arcs"] += 1
        if not (via or pad):
            continue
        hole = _hole(api, item, error)
        drilled = hole.OutlineCount() > 0
        if drilled:
            hole_span = span if via else enabled
            for layer in hole_span:
                holes[layer].Append(hole)
        plated = via or (pad and item.GetAttribute() == api.PAD_ATTRIB_PTH)
        if pad and drilled:
            drill = _drill(api, item, False)
            if drill <= 0:
                raise ValueError("Mounting-hole pad has an invalid drill: " + _uid(item))
            record = {"id": _uid(item), "reference": str(item.GetParentFootprint().GetReference()),
                      "pad_number": str(item.GetNumber()), "net": str(item.GetNetname()),
                      "x_mm": _mm(api, item.GetPosition())[0], "y_mm": _mm(api, item.GetPosition())[1],
                      "drill_mm": drill, "plated": bool(plated),
                      "flashed_copper_layers": flashed,
                      "contact_evidence": "flashed_plated_land" if plated and flashed else "no_plated_land",
                      "plane_connection_verified": False}
            mounting_holes.append(record)
            counts["mounting_holes"] += 1
        if plated:
            drill = _drill(api, item, via)
            if drill <= 0:
                raise ValueError("Plated barrel has an invalid drill: " + _uid(item))
            if not flashed:
                raise ValueError("Plated barrel has no flashed copper contact: " + _uid(item))
            diameters = {str(layer): api.ToMM(item.GetWidth(layer)) if via else
                         min(api.ToMM(item.GetSize().x), api.ToMM(item.GetSize().y))
                         for layer in flashed}
            if any(diameter <= drill for diameter in diameters.values()):
                raise ValueError("Plated barrel land must exceed its drill: " + _uid(item))
            pos = item.GetPosition()
            barrels.append({"id": _uid(item), "kind": "via" if via else "plated_pad",
                            "net": str(item.GetNetname()), "x_mm": api.ToMM(pos.x), "y_mm": api.ToMM(pos.y),
                            "drill_mm": drill, "outer_diameters_mm": diameters,
                            "span_layers": span, "contact_layers": flashed,
                            "plating_thickness_mm": None})
            if pad:
                counts["plated_pads"] += 1
    for item in drawings:
        if not hasattr(item, "TransformShapeToPolygon"):
            continue
        for layer in enabled:
            if item.IsOnLayer(layer):
                polygon = _shape(api, item, layer, error)
                if polygon.OutlineCount():
                    copper[layer].Append(polygon)
    for zone in zones:
        if zone.GetIsRuleArea():
            continue
        for layer in enabled:
            if not zone.IsOnLayer(layer):
                continue
            if not zone.IsFilled() or not zone.HasFilledPolysForLayer(layer):
                raise ValueError("Copper zone is unfilled on " + board.GetLayerName(layer) + "; refill and save in KiCad.")
            copper[layer].Append(zone.GetFilledPolysList(layer))
            counts["zones"] += 1
    for row in layers:
        layer = row["id"]
        copper[layer].Simplify()
        holes[layer].Simplify()
        copper[layer].BooleanSubtract(holes[layer])
        row["polygons_mm"] = _polygons(copper[layer], api)
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
        raise ValueError("Saved PCB changed during thermal geometry extraction; reload and retry.")
    return {"schema_version": 1, "source_path": str(path),
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "outline": outline, "bbox_mm": bbox, "outline_status": "valid",
            "layers": layers, "barrels": barrels, "mounting_holes": mounting_holes,
            "counts": counts, "curve_tolerance_mm": tolerance,
            "geometry_meaning": "Physical copper occupancy from saved filled geometry; no thermal conductivity or contact inferred.",
            "missing_material_inputs": ["dielectric thermal conductivity by interval",
                                        "via/plated-hole barrel plating thickness",
                                        "mount/fixture thermal contact resistance"]}
