"""Read-only native PCB display geometry, shared by analysis previews.

Coordinates are millimetres. KiCad tessellates curved display shapes at 0.01 mm;
this scene is never solver input and never invents unfilled zone copper.
"""
from __future__ import annotations
import math

COPPER_ROLES = {'track', 'pad', 'via', 'zone'}


def extract_board(board):
    import pcbnew as p
    scene = {'layers': {}, 'primitives': [], 'bounds': None, 'warnings': [],
             'tessellation_mm': .01}
    enabled = list(board.GetEnabledLayers().Seq())
    copper = set(board.GetEnabledLayers().CuStack())
    scene['layers'] = {int(layer): str(board.GetLayerName(layer)) for layer in enabled}
    def uid(item):
        return item.m_Uuid.AsString()
    def ring(chain):
        return [[p.ToMM(chain.CPoint(i).x), p.ToMM(chain.CPoint(i).y)]
                for i in range(chain.PointCount())]
    def polygons(poly, meta):
        for i in range(poly.OutlineCount()):
            scene['primitives'].append(dict(meta, kind='polygon', points=ring(poly.COutline(i)),
                holes=[ring(poly.CHole(i, h)) for h in range(poly.HoleCount(i))]))
    def shape(item, layer, role, **extra):
        meta = dict(layer=int(layer), role=role, uuid=uid(item),
                    net=str(item.GetNetname()) if hasattr(item, 'GetNetname') else '', **extra)
        try:
            poly = p.SHAPE_POLY_SET()
            item.TransformShapeToPolygon(poly, layer, 0, p.FromMM(.01), p.ERROR_INSIDE)
            if role in ('pad', 'via'):
                hole = item.GetEffectiveHoleShape()
                if hole and hole.GetWidth() > 0:
                    drilled = p.SHAPE_POLY_SET()
                    hole.TransformToPolygon(drilled, p.FromMM(.01), p.ERROR_OUTSIDE)
                    poly.BooleanSubtract(drilled)
                    polygons(drilled, dict(meta, role='drill'))
            polygons(poly, meta)
        except (AttributeError, TypeError, RuntimeError) as exc:
            scene['warnings'].append(f'{role} {meta["uuid"]}: display geometry unavailable ({exc})')
    try:
        poly = p.SHAPE_POLY_SET()
        if board.GetBoardPolygonOutlines(poly, False):
            polygons(poly, dict(layer=int(p.Edge_Cuts), role='outline', uuid='', net=''))
        else:
            scene['warnings'].append('Edge.Cuts is not a closed outline; saved edge graphics are shown.')
    except (AttributeError, TypeError, RuntimeError) as exc:
        scene['warnings'].append(f'Closed board outline unavailable: {exc}')
    for item in board.GetTracks():
        role = 'via' if isinstance(item, p.PCB_VIA) else 'track'
        layers = [layer for layer in copper if item.IsOnLayer(layer)] if role == 'via' else [item.GetLayer()]
        for layer in layers:
            shape(item, layer, role)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            for layer in copper:
                if pad.IsOnLayer(layer):
                    shape(pad, layer, 'pad', reference=fp.GetReference(), parent_uuid=uid(fp))
        for item in fp.GraphicalItems():
            if hasattr(item, 'TransformShapeToPolygon'):
                shape(item, item.GetLayer(), 'footprint', reference=fp.GetReference(), parent_uuid=uid(fp))
        pos = fp.GetPosition()
        scene['primitives'].append(dict(kind='text', center=[p.ToMM(pos.x), p.ToMM(pos.y)],
            text=fp.GetReference(), reference=fp.GetReference(), uuid=uid(fp), net='',
            role='reference', layer=int(fp.GetLayer())))
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            continue
        for layer in copper:
            if zone.IsOnLayer(layer):
                poly = zone.GetFilledPolysList(layer)
                if poly.OutlineCount():
                    polygons(poly, dict(layer=int(layer), role='zone', uuid=uid(zone), net=str(zone.GetNetname())))
                else:
                    scene['warnings'].append(f'Zone {uid(zone)} on {board.GetLayerName(layer)} has no saved fill.')
    for item in board.GetDrawings():
        if hasattr(item, 'TransformShapeToPolygon'):
            shape(item, item.GetLayer(), 'drawing')
    points = [point for row in scene['primitives'] for point in row.get('points', [])]
    if points:
        xs, ys = zip(*points)
        scene['bounds'] = [min(xs), min(ys), max(xs), max(ys)]
    return scene


def visible_primitives(scene, visible_layers=None):
    layers = None if visible_layers is None else set(visible_layers)
    return [row for row in scene['primitives'] if row['role'] == 'outline'
            or layers is None or row['layer'] in layers]


def _inside(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        cross = (b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])
        if abs(cross) < 1e-9 and min(a[0], b[0])-1e-9 <= x <= max(a[0], b[0])+1e-9 and min(a[1], b[1])-1e-9 <= y <= max(a[1], b[1])+1e-9:
            return True
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def hit_test(scene, x, y, visible_layers=None, net=None, tolerance_mm=0):
    hits = []
    for row in visible_primitives(scene, visible_layers):
        if row['role'] not in COPPER_ROLES or (net is not None and row.get('net') != net):
            continue
        if row['kind'] == 'polygon':
            hit = _inside((x, y), row['points']) and not any(_inside((x, y), hole) for hole in row.get('holes', []))
            # Explicit drill primitives share copper identity and are excluded from probes.
            if hit:
                drills = [d for d in scene['primitives'] if d['role']=='drill' and d['uuid']==row['uuid'] and d['layer']==row['layer']]
                hit = not any(_inside((x,y), d['points']) for d in drills)
        elif row['kind'] == 'circle':
            hit = math.hypot(x-row['center'][0], y-row['center'][1]) <= row['radius']+tolerance_mm
        else:
            hit = False
        if hit:
            hits.append(row)
    return hits


def _color(row, highlight_ids, highlight_nets):
    if row.get('uuid') in highlight_ids or row.get('net') in highlight_nets:
        return '#ffbf40', 1.0
    if row['role'] == 'drill': return '#18202b', 1.0
    if row['role'] == 'outline': return '#90a69c', .22
    if row['role'] in ('drawing', 'footprint', 'reference'): return '#c2cbd7', .7
    return ('#d46363' if row['layer'] == 0 else '#649ee6'), .5 if row['role']=='zone' else .85


def _rings(row):
    # Nonzero fill rule requires holes opposite to the exterior orientation.
    rings = [row['points']] + row.get('holes', [])
    def area(r): return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(r,r[1:]+r[:1]))
    return [r if (area(r)>0)==(i==0) else list(reversed(r)) for i,r in enumerate(rings)]


def draw_matplotlib(ax, scene, visible_layers=None, highlight_ids=(), alpha=.45, highlight_nets=()):
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    artists = []
    for row in sorted(visible_primitives(scene, visible_layers), key=lambda r: r['role']=='drill'):
        color, opacity = _color(row, set(highlight_ids), set(highlight_nets))
        highlighted = row.get('uuid') in highlight_ids or row.get('net') in highlight_nets
        if row['kind'] == 'polygon':
            vertices, codes = [], []
            for ring in _rings(row):
                if len(ring)<3: continue
                vertices.extend(ring+[ring[0]])
                codes.extend([Path.MOVETO]+[Path.LINETO]*(len(ring)-1)+[Path.CLOSEPOLY])
            if not vertices: continue
            patch = PathPatch(Path(vertices, codes), facecolor=color, edgecolor=color,
                              linewidth=1.2 if highlighted else .4,
                              alpha=opacity*alpha, zorder=6 if highlighted else 0)
            ax.add_patch(patch); artists.append(patch)
        elif row['kind'] == 'text':
            artists.append(ax.text(*row['center'], row['text'], fontsize=6, color=color,
                                   alpha=alpha, clip_on=True, zorder=1))
    return artists


def draw_wx(gc, scene, project, visible_layers=None, highlight_ids=(), alpha=.45, scale=1, highlight_nets=()):
    import wx
    for row in sorted(visible_primitives(scene, visible_layers), key=lambda r:r['role']=='drill'):
        color, opacity = _color(row, set(highlight_ids), set(highlight_nets))
        c = wx.Colour(color); c.Set(c.Red(),c.Green(),c.Blue(),int(255*opacity*alpha))
        gc.SetPen(wx.Pen(c,1)); gc.SetBrush(wx.Brush(c))
        if row['kind'] == 'polygon':
            path = gc.CreatePath()
            for ring in _rings(row):
                if not ring: continue
                path.MoveToPoint(*project(ring[0]))
                for point in ring[1:]: path.AddLineToPoint(*project(point))
                path.CloseSubpath()
            gc.DrawPath(path, wx.WINDING_RULE)
        elif row['kind']=='text':
            gc.SetFont(wx.Font(8,wx.FONTFAMILY_DEFAULT,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_NORMAL),c)
            gc.DrawText(row['text'],*project(row['center']))
