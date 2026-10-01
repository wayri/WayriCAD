"""Read-only board geometry and a bounded display of QuickTherm estimates.

The color field interpolates *junction estimates at component locations*. It is
not a board-surface temperature, heat-flow, or thermal-coupling solution.
"""
from __future__ import annotations

import math
import statistics


def _mm(point):
    # KiCad 10 pcbnew uses integer nanometres internally.
    return [point.x / 1_000_000, point.y / 1_000_000]


def _inside(point, ring):
    """Even-odd polygon containment; boundary counts as inside."""
    x, y = point
    hit = False
    for i, a in enumerate(ring):
        b = ring[(i + 1) % len(ring)]
        cross = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
        if abs(cross) < 1e-9 and min(a[0], b[0]) - 1e-9 <= x <= max(a[0], b[0]) + 1e-9 and min(a[1], b[1]) - 1e-9 <= y <= max(a[1], b[1]) + 1e-9:
            return True
        if (a[1] > y) != (b[1] > y):
            if x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
                hit = not hit
    return hit


def _hull(points):
    """Return the convex hull of distinct anchor positions in board mm."""
    points = sorted(set(tuple(p) for p in points))
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


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
        outer = [_mm(chain.CPoint(i)) for i in range(chain.PointCount())]
        holes = []
        for hole_index in range(polygon.HoleCount(index)):
            hole = polygon.CHole(index, hole_index)
            holes.append([_mm(hole.CPoint(i)) for i in range(hole.PointCount())])
        if len(outer) >= 3:
            contours.append({"outer_mm": outer, "holes_mm": holes})
    if not contours:
        return [], "The saved Edge.Cuts outline has no valid closed contour."
    return contours, None


def _on_board(point, outlines):
    return any(_inside(point, shape["outer_mm"]) and
               not any(_inside(point, hole) for hole in shape["holes_mm"])
               for shape in outlines)


def _analytics(result):
    rows = result.get("components", [])
    values = [float(row["junction_c"]) for row in rows]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("QuickTherm returned a non-finite junction estimate.")
    by_hot = sorted(rows, key=lambda row: (-float(row["junction_c"]), row["reference"]))
    by_cool = sorted(rows, key=lambda row: (float(row["junction_c"]), row["reference"]))
    powers = [float(row["power_w"]) for row in rows]
    if any(not math.isfinite(value) or value < 0 for value in powers):
        raise ValueError("QuickTherm returned invalid component power.")
    coverage = result.get("coverage", {})
    return {
        "basis": "Solved component junction estimates only; excluded components are omitted from statistics.",
        "temperature_c": {"min": min(values) if values else None,
                          "max": max(values) if values else None,
                          "mean": statistics.fmean(values) if values else None,
                          "median": statistics.median(values) if values else None},
        "hottest_reference": by_hot[0]["reference"] if by_hot else None,
        "coolest_reference": by_cool[0]["reference"] if by_cool else None,
        "power_w": {"solved_total": math.fsum(powers),
                    "solved_max": max(powers) if powers else None,
                    "solved_mean": statistics.fmean(powers) if powers else None},
        "coverage": {"scoped": int(coverage.get("scoped", len(rows))),
                     "solved": len(rows),
                     "excluded": list(coverage.get("excluded", []))},
    }


def _side_field(bbox, outlines, components, side, grid_size):
    """Interpolate only components mounted on the displayed side."""
    anchors=[(item['position_mm'],item['junction_c']) for item in components
             if item['side']==side and item['solved'] and item['on_board']]
    hull=_hull([point for point,_ in anchors])
    reason=("A valid saved Edge.Cuts outline is required." if not outlines or not bbox else
            "At least three non-collinear solved parts on this side are needed." if len(hull)<3 else None)
    result={"label":f"Interpolated {side}-side component junction estimates (°C); illustrative only",
            "meaning":"Inverse-distance interpolation of same-side solved component junction estimates; not board-surface temperature or a thermal solve.",
            "status":"unavailable" if reason else "available","reason":reason,
            "method":"inverse-distance-squared","support_hull_mm":hull,
            "sampled_min_c":None,"sampled_max_c":None,
            "x_centers_mm":[],"y_centers_mm":[],"values_c":[]}
    if reason:return result
    xmin,ymin,xmax,ymax=bbox
    width,height=xmax-xmin,ymax-ymin
    if width<=0 or height<=0:
        result.update(status='unavailable',reason='The saved board has zero area.')
        return result
    nx=grid_size;ny=max(2,min(200,round(grid_size*height/width)))
    xs=[xmin+(i+.5)*width/nx for i in range(nx)]
    ys=[ymin+(j+.5)*height/ny for j in range(ny)]
    values=[];valid=[]
    for y in ys:
        line=[]
        for x in xs:
            point=[x,y]
            if not _inside(point,hull) or not _on_board(point,outlines):
                line.append(None);continue
            exact=next((value for anchor,value in anchors
                        if (x-anchor[0])**2+(y-anchor[1])**2<1e-18),None)
            if exact is None:
                weights=[(1/((x-anchor[0])**2+(y-anchor[1])**2),value)
                         for anchor,value in anchors]
                exact=math.fsum(weight*value for weight,value in weights)/math.fsum(weight for weight,_ in weights)
            line.append(exact);valid.append(exact)
        values.append(line)
    result.update(x_centers_mm=xs,y_centers_mm=ys,values_c=values,
                  sampled_min_c=min(valid) if valid else None,
                  sampled_max_c=max(valid) if valid else None)
    if not valid:result.update(status='unavailable',reason='No supported sample centers on this side.')
    return result


def build_board_thermal_view(board, result, *, grid_size=80):
    """Combine a saved pcbnew BOARD and QuickTherm result into JSON-safe view data.

    The grid is inverse-distance interpolation of solved junction estimates,
    only inside their convex hull and a valid board outline. ``None`` cells are
    unsupported. Its extrema must never be presented as physical board maxima.
    """
    if not hasattr(board, "GetFootprints"):
        raise ValueError("Pass a loaded KiCad board.")
    try:
        board_thickness_mm = board.GetDesignSettings().GetBoardThickness() / 1_000_000
        if not math.isfinite(board_thickness_mm) or board_thickness_mm <= 0:
            board_thickness_mm = None
    except (AttributeError, TypeError, ValueError):
        board_thickness_mm = None
    if not isinstance(grid_size, int) or not 2 <= grid_size <= 200:
        raise ValueError("Grid size must be an integer from 2 to 200.")
    outlines, outline_issue = _outline(board)
    points = [point for shape in outlines for point in shape["outer_mm"]]
    bbox = ([min(p[0] for p in points), min(p[1] for p in points),
             max(p[0] for p in points), max(p[1] for p in points)] if points else None)
    bbox_status = "verified_outline" if bbox else "unavailable"
    if bbox is None and hasattr(board, "GetBoardEdgesBoundingBox"):
        bounds = board.GetBoardEdgesBoundingBox()
        if bounds.GetWidth() > 0 and bounds.GetHeight() > 0:
            bbox = [bounds.GetX() / 1_000_000, bounds.GetY() / 1_000_000,
                    (bounds.GetX() + bounds.GetWidth()) / 1_000_000,
                    (bounds.GetY() + bounds.GetHeight()) / 1_000_000]
            bbox_status = "unverified_edge_bounds"
    solved = {str(row["reference"]): row for row in result.get("components", [])}
    excluded = {str(row["reference"]): row for row in result.get("coverage", {}).get("excluded", [])}
    components = []
    seen = set()
    for fp in board.GetFootprints():
        ref = str(fp.GetReference())
        # KiCad's unannotated graphic footprints (for example two G***) are
        # not addressable thermal components and may share a placeholder ref.
        if "*" in ref:
            continue
        if ref in seen:
            raise ValueError(f"Duplicate footprint reference: {ref}")
        seen.add(ref)
        pos = _mm(fp.GetPosition())
        # False excludes reference/value text, which otherwise inflates the
        # thermal source area well beyond the physical footprint geometry.
        bounds = fp.GetBoundingBox(False)
        fp_bbox = [bounds.GetX() / 1_000_000, bounds.GetY() / 1_000_000,
                   (bounds.GetX() + bounds.GetWidth()) / 1_000_000,
                   (bounds.GetY() + bounds.GetHeight()) / 1_000_000]
        row = solved.get(ref)
        components.append({"id": fp.m_Uuid.AsString(), "reference": ref,
                           "position_mm": pos, "bbox_mm": fp_bbox,
                           "rotation_deg": float(fp.GetOrientationDegrees()),
                           "side": "bottom" if fp.IsFlipped() else "top",
                           "top_side": not fp.IsFlipped(),
                           "on_board": _on_board(pos, outlines) if outlines else None,
                           "in_scope": ref in solved or ref in excluded,
                           "solved": row is not None,
                           "junction_c": float(row["junction_c"]) if row else None,
                           "power_w": float(row["power_w"]) if row else None,
                           "issues": list(excluded[ref].get("issues", [])) if ref in excluded else []})
    components.sort(key=lambda row: row["reference"])
    missing = sorted((set(solved) | set(excluded)) - seen)
    if missing:
        raise ValueError("QuickTherm references absent from saved board: " + ", ".join(missing))
    anchors = [(entry["position_mm"], entry["junction_c"]) for entry in components
               if entry["solved"] and entry["on_board"]]
    hull = _hull([p for p, _ in anchors])
    reason = outline_issue
    if reason is None and len(hull) < 3:
        reason = "At least three non-collinear solved component positions inside the board are needed for interpolation."
    field = {"label": "Interpolated component junction estimates (°C); illustrative only",
             "meaning": "Inverse-distance interpolation of solved junction estimates at footprint centers; not board-surface temperature or a thermal solve.",
             "status": "unavailable" if reason else "available", "reason": reason,
             "method": "inverse-distance-squared", "support_hull_mm": hull,
             "sampled_min_c": None, "sampled_max_c": None,
             "x_centers_mm": [], "y_centers_mm": [], "values_c": []}
    if reason is None:
        xmin, ymin, xmax, ymax = bbox
        width, height = xmax - xmin, ymax - ymin
        if width <= 0 or height <= 0:
            field["status"] = "unavailable"
            field["reason"] = "The board outline has zero area."
        else:
            nx = grid_size
            ny = max(2, min(200, round(grid_size * height / width)))
            xs = [xmin + (i + .5) * width / nx for i in range(nx)]
            ys = [ymin + (j + .5) * height / ny for j in range(ny)]
            grid = []
            valid = []
            for y in ys:
                line = []
                for x in xs:
                    p = [x, y]
                    if not _inside(p, hull) or not _on_board(p, outlines):
                        line.append(None)
                        continue
                    weights = []
                    exact = None
                    for anchor, value in anchors:
                        d2 = (x - anchor[0]) ** 2 + (y - anchor[1]) ** 2
                        if d2 < 1e-18:
                            exact = value
                            break
                        weights.append((1 / d2, value))
                    estimate = exact if exact is not None else math.fsum(w*v for w, v in weights) / math.fsum(w for w, _ in weights)
                    line.append(estimate)
                    valid.append(estimate)
                grid.append(line)
            field.update(x_centers_mm=xs, y_centers_mm=ys, values_c=grid,
                         sampled_min_c=min(valid) if valid else None,
                         sampled_max_c=max(valid) if valid else None)
            if not valid:
                field["status"] = "unavailable"
                field["reason"] = "The selected grid has no supported cell centers."
    return {"view": "saved PCB top-side coordinates", "unit": "mm",
            "board_thickness_mm": board_thickness_mm,
            "outline": outlines, "outline_status": "valid" if outlines else "unavailable",
            "outline_issue": outline_issue, "bbox_mm": bbox, "bbox_status": bbox_status,
            "components": components, "analytics": _analytics(result), "field": field,
            "fields_by_side":{side:_side_field(bbox,outlines,components,side,grid_size)
                              for side in ('top','bottom')}}
