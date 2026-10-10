"""Read-only KiCad copper snapshot for a future multilayer thermal solve.

The snapshot records *physical* copper and plated barrels. It does not infer
dielectric thermal conductivity, via plating thickness, or thermal contact to a
fixture from electrical net membership.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import time

from .board_geometry import _hole, _polygons, _shape, _uid, stackup
from .thermal_board_view import _outline


def _mm(api, point):
    return [api.ToMM(point.x), api.ToMM(point.y)]


def _drill(api, item, is_via):
    if is_via:
        value = api.ToMM(item.GetDrillValue())
    else:
        size = item.GetDrillSize()
        value = min(api.ToMM(size.x), api.ToMM(size.y))
    return value


def _backdrilled(item):
    for name in ("GetSecondaryDrillSize", "GetTertiaryDrillSize"):
        getter = getattr(item, name, None)
        if getter is not None:
            value = getter()
            if value is not None and value != 0:
                return True
    return False


def collect_thermal_geometry(board, source_path, *, curve_tolerance_mm=0.005,
                             contact_pads=None, package_contacts=(), progress=None):
    """Return JSON-safe physical copper, barrel and hole data from a saved PCB.

    The caller loads ``board`` from ``source_path`` and checks that it has not
    changed before consuming the snapshot. A named in-memory test board may use
    an explicit source text with the same stackup; no board mutation occurs.
    """
    import pcbnew as api

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
    if contact_pads is None:
        contact_pads = {}
    if not isinstance(contact_pads, dict) or any(
            not str(ref).strip() or not str(number).strip()
            for ref, number in contact_pads.items()):
        raise ValueError("contact_pads must map references to pad numbers.")
    selected_contacts = {str(ref): str(number) for ref, number in contact_pads.items()}
    requested_faces = {(path['reference'], str(path['pad_number']), path['layer_id'])
                       for path in package_contacts}
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
    source_contacts = []
    contact_shapes = []
    mounting_holes = []
    counts = {"tracks_and_arcs": 0, "vias": 0, "pads": 0, "zones": 0,
              "plated_pads": 0, "mounting_holes": 0}

    footprints = list(board.GetFootprints())
    pads = [pad for fp in footprints for pad in fp.Pads()]
    tracks = list(board.GetTracks())
    drawings = list(board.GetDrawings()) + [graphic for fp in footprints for graphic in fp.GraphicalItems()]
    zones = list(board.Zones()) + [zone for fp in footprints for zone in fp.Zones()]
    copper_items = tracks + pads
    extraction_started = time.monotonic()
    if progress:
        progress("geometry extraction", 0, len(copper_items), 0.0, None)
    for item_index, item in enumerate(copper_items, 1):
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
        if progress and (item_index == len(copper_items) or
                         item_index % max(1, len(copper_items)//100) == 0):
            elapsed = time.monotonic()-extraction_started
            progress("geometry extraction", item_index, len(copper_items),
                     elapsed, elapsed*(len(copper_items)-item_index)/item_index)
        if not (via or pad):
            continue
        hole = _hole(api, item, error)
        drilled = hole.OutlineCount() > 0
        if drilled:
            hole_span = span if via else enabled
            for layer in hole_span:
                holes[layer].Append(hole)
        plated = via or (pad and item.GetAttribute() == api.PAD_ATTRIB_PTH)
        if pad:
            reference = str(item.GetParentFootprint().GetReference())
            pad_number = str(item.GetNumber())
            for layer in flashed:
                if (selected_contacts.get(reference) == pad_number or
                        (reference, pad_number, layer) in requested_faces):
                    contact = _shape(api, item, layer, error)
                    contact_shapes.append((reference, pad_number, layer, _uid(item),
                                           str(item.GetNetname()), contact))
        drill_shape = {}
        if drilled:
            if via:
                drill_shape = {"drill_size_mm": [_drill(api, item, True)] * 2, "drill_angle_deg": 0.0}
            else:
                drill_shape = {"drill_size_mm": _mm(api, item.GetDrillSize()),
                               "drill_angle_deg": float(item.GetOrientationDegrees())}
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
                      "plane_connection_verified": False, **drill_shape}
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
                            "plating_thickness_mm": None, **drill_shape})
            if pad and item.GetDrillSize().x != item.GetDrillSize().y:
                land_size = _mm(api, item.GetSize())
                if any(land <= hole_size for land, hole_size in zip(land_size, drill_shape["drill_size_mm"])):
                    raise ValueError("Plated slot land must exceed both drill dimensions: " + _uid(item))
                # Retain actual flashed land geometry for the distributed slot
                # wall stencil; a circular land radius loses long slot ends.
                barrels[-1]["land_polygons_mm"] = {}
                for layer in flashed:
                    land = _shape(api, item, layer, error)
                    land.BooleanSubtract(hole)
                    barrels[-1]["land_polygons_mm"][str(layer)] = _polygons(land, api)
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
    # The selected SMD contact can contain thermal vias belonging to separate
    # PCB items. Subtract the *complete* layer hole set only after every via and
    # drilled pad has been collected; subtracting the pad's own hole is not enough.
    for reference, pad_number, layer, pad_uuid, net, contact in contact_shapes:
        contact.BooleanSubtract(holes[layer])
        source_contacts.append({"reference": reference, "pad_number": pad_number,
                                "layer_id": layer, "pad_uuid": pad_uuid, "net": net,
                                "polygons_mm": _polygons(contact, api)})
    if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(data).digest():
        raise ValueError("Saved PCB changed during thermal geometry extraction; reload and retry.")
    return {"schema_version": 1, "source_path": str(path),
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "outline": outline, "bbox_mm": bbox, "outline_status": "valid",
            "layers": layers, "barrels": barrels, "mounting_holes": mounting_holes,
            "source_contacts": source_contacts,
            "counts": counts, "curve_tolerance_mm": tolerance,
            "geometry_meaning": "Physical copper occupancy from saved filled geometry; no thermal conductivity or contact inferred.",
            "missing_material_inputs": ["dielectric thermal conductivity by interval",
                                        "via/plated-hole barrel plating thickness",
                                        "mount/fixture thermal contact resistance"]}
