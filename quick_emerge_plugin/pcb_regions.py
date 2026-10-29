"""Read-only native KiCad rule-area copper extraction (no refill or save)."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
import re


def _uid(item):
    return item.m_Uuid.AsString()


def _polygons(poly, api):
    def ring(chain):
        points = [[api.ToMM(chain.CPoint(i).x), api.ToMM(chain.CPoint(i).y)] for i in range(chain.PointCount())]
        if points and points[0] == points[-1]:
            points.pop()
        return points
    return [{"outer_mm": ring(poly.COutline(i)), "holes_mm": [ring(poly.CHole(i, h)) for h in range(poly.HoleCount(i))]} for i in range(poly.OutlineCount())]


def _clip(poly, roi, api):
    result = api.SHAPE_POLY_SET(poly)
    result.BooleanIntersection(roi)
    return result


def _shape(item, layer, error, api):
    poly = api.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(poly, layer, 0, error, api.ERROR_INSIDE)
    return poly


def _dielectric(text, diagnostics=None):
    # Read saved evidence, not the API's synthesized default stackup.
    match = re.search(r'\(stackup\s', text)
    if not match:
        return None
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text[match.start():])
    root = []; stack = [root]
    for token in tokens:
        if token == '(':
            child = []; stack[-1].append(child); stack.append(child)
        elif token == ')':
            stack.pop()
            if len(stack) == 1:
                break
        else:
            stack[-1].append(token.strip('"'))
    rows = [r for r in root[0][1:] if isinstance(r, list) and r and r[0] == 'layer']
    def field(row, name):
        return [x[1] for x in row if isinstance(x, list) and len(x) > 1 and x[0] == name]
    copper = [i for i, r in enumerate(rows) if field(r, 'type') == ['copper']]
    if len(copper) != 2:
        return None
    total = 0.0
    for row in rows[copper[0]+1:copper[1]]:
        types = field(row, 'type'); values = field(row, 'thickness')
        if not types or types[0].lower() not in ('core', 'prepreg', 'dielectric') or len(values) != 1:
            return None
        try:
            value = float(values[0])
        except ValueError:
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        total += value
    if diagnostics is not None and copper[1] - copper[0] > 2:
        diagnostics.append('Saved stackup contains multiple dielectric intervals; summed separation does not establish a homogeneous material. Review the effective substrate material explicitly.')
    return total or None


def collect_regions(source_path, area_id=None, *, curve_tolerance_mm=0.005):
    """List rule areas or clip saved physical copper to one area and Edge.Cuts."""
    import pcbnew as api
    path = Path(source_path).resolve()
    raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    board = api.LoadBoard(str(path))
    if board is None:
        raise ValueError('KiCad could not load the saved PCB.')
    if not 0 < curve_tolerance_mm <= 0.1:
        raise ValueError('Curve tolerance must be within (0, 0.1] mm.')
    error = api.FromMM(curve_tolerance_mm)
    outline = api.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outline, False) or not outline.OutlineCount():
        raise ValueError('A valid closed Edge.Cuts outline is required.')
    zones = list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]
    # Board rule areas are the qualified enclosure source. Footprint-local
    # rule-area transforms require separate qualification.
    areas = [z for z in board.Zones() if z.GetIsRuleArea()]
    def area_record(z):
        curved = z.Outline().ArcCount() > 0
        return {'id': _uid(z), 'name': str(z.GetZoneName()), 'outline': [] if curved else _polygons(z.Outline(), api),
                'unsupported': ['Curved rule-area contours are unsupported'] if curved else [],
                'layer_names': [str(api.LayerName(l)) for l in board.GetEnabledLayers().CuStack() if z.IsOnLayer(l)]}
    points = [p for row in _polygons(outline, api) for p in row['outer_mm']]
    result = {'schema': 1, 'schema_version': 1, 'source': {'path': str(path), 'sha256': digest},
              'board_outline': _polygons(outline, api), 'kicad_version': api.Version(),
              'board_bounds_mm': [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)],
              'copper_net_names': sorted({str(n.GetNetname()) for n in board.GetNetInfo().NetsByNetcode().values()}),
              'areas': [area_record(z) for z in areas]}
    if area_id is not None:
        selected = next((z for z in areas if _uid(z) == area_id), None)
        if selected is None:
            raise ValueError('Rule area UUID was not found in the saved PCB: ' + str(area_id))
        if selected.Outline().ArcCount():
            raise ValueError('The selected rule area has unsupported curved contours; use a polygonal enclosure.')
        if board.GetCopperLayerCount() != 2:
            raise ValueError('The first Quick EMerge region path requires exactly two copper layers.')
        roi = _clip(selected.Outline(), outline, api)
        if not roi.OutlineCount():
            raise ValueError('The rule area has no physical area inside Edge.Cuts.')
        unsupported = []; groups = {}
        layers = [api.F_Cu, api.B_Cu]
        def include(item, layer, poly, kind=None):
            clipped = _clip(poly, roi, api)
            if not clipped.OutlineCount():
                return False
            if kind:
                unsupported.append(kind + ': ' + _uid(item))
                return True
            key = (str(api.LayerName(layer)), str(item.GetNetname()))
            group = groups.setdefault(key, {'poly': api.SHAPE_POLY_SET(), 'ids': set()})
            group['poly'].Append(clipped); group['ids'].add(_uid(item))
            return True
        for item in list(board.GetTracks()) + [p for fp in board.GetFootprints() for p in fp.Pads()]:
            via = isinstance(item, api.PCB_VIA)
            drilled = via or (isinstance(item, api.PAD) and (item.GetDrillSize().x > 0 or item.GetDrillSize().y > 0))
            for layer in layers:
                if item.IsOnLayer(layer):
                    include(item, layer, _shape(item, layer, error, api), 'Drilled pad/via is unsupported' if drilled else None)
            if drilled:
                hole = item.GetEffectiveHoleShape()
                if hole and hole.GetWidth() > 0:
                    poly = api.SHAPE_POLY_SET(); hole.TransformToPolygon(poly, error, api.ERROR_OUTSIDE)
                    include(item, api.F_Cu, poly, 'Drilled pad/via is unsupported')
        for zone in zones:
            if zone.GetIsRuleArea():
                continue
            for layer in layers:
                if not zone.IsOnLayer(layer):
                    continue
                if not zone.IsFilled() or not zone.HasFilledPolysForLayer(layer):
                    if _clip(zone.Outline(), roi, api).OutlineCount():
                        unsupported.append('Unfilled copper zone: ' + _uid(zone))
                else:
                    include(zone, layer, zone.GetFilledPolysList(layer))
        drawings = list(board.GetDrawings()) + [g for fp in board.GetFootprints() for g in fp.GraphicalItems()]
        for item in drawings:
            for layer in layers:
                if item.IsOnLayer(layer):
                    include(item, layer, _shape(item, layer, error, api), 'Copper graphics are unsupported')
        copper = []
        for (layer, net), group in sorted(groups.items()):
            group['poly'].Simplify()
            copper.append({'layer': layer, 'net': net, 'polygons': _polygons(group['poly'], api), 'source_ids': sorted(group['ids'])})
        diagnostics = []
        thickness = _dielectric(raw.decode('utf-8-sig'), diagnostics)
        if thickness is None:
            diagnostics.append('Saved explicit dielectric separation is unavailable; define and save the KiCad stackup before simulation.')
        result.update(area=area_record(selected), substrate={'outline': _polygons(roi, api), 'thickness_mm': thickness,
                      'board_thickness_mm': api.ToMM(board.GetDesignSettings().GetBoardThickness())}, copper=copper,
                      unsupported=sorted(set(unsupported)), curve_tolerance_mm=curve_tolerance_mm,
                      diagnostics=diagnostics)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Saved PCB changed during extraction; reload and retry.')
    return result

