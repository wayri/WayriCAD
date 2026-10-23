"""Read-only native PCB display geometry, shared by analysis previews.

Coordinates are millimetres. KiCad tessellates curved display shapes at 0.01 mm;
this scene is never solver input and never invents unfilled zone copper.
"""
from __future__ import annotations
import math
from collections import defaultdict

COPPER_ROLES = {'track', 'pad', 'via', 'zone'}


class DisplayScene(dict):
    """JSON-compatible immutable display snapshot with a private lazy pick index.

    Re-extract the scene after board changes. Call invalidate() after changing
    primitive geometry in place; selection/style changes need no invalidation.
    The acceleration data is never exported or used for electrical analysis.
    """
    def invalidate(self):
        self._pick_index = None
        self._render_paths = {}
        self._render_token = None

    def polygon_path(self, row):
        """Reuse immutable display paths across selection and layer redraws."""
        from matplotlib.path import Path
        token = (id(self['primitives']), len(self['primitives']))
        if getattr(self, '_render_token', None) != token:
            self._render_paths = {}
            self._render_token = token
        key = id(row)
        if key not in self._render_paths:
            vertices, codes = [], []
            for ring in _rings(row):
                if len(ring) < 3:continue
                vertices.extend(ring + [ring[0]])
                codes.extend([Path.MOVETO] + [Path.LINETO]*(len(ring)-1) + [Path.CLOSEPOLY])
            self._render_paths[key] = Path(vertices, codes) if vertices else None
        return self._render_paths[key]

    def pick_index(self):
        token = (id(self['primitives']), len(self['primitives']))
        if getattr(self, '_pick_token', None) != token or getattr(self, '_pick_index', None) is None:
            self._pick_index = _PickIndex(self['primitives'])
            self._pick_token = token
        return self._pick_index


def prepare_scene(scene):
    """Prepare a loaded display snapshot without adding report JSON fields."""
    return scene if isinstance(scene, DisplayScene) else DisplayScene(scene)


def _bounds(row):
    points = row.get('points', ())
    if points:
        xs, ys = zip(*points)
        return min(xs), min(ys), max(xs), max(ys)
    if row.get('kind') == 'circle':
        x, y = row['center'];r = row['radius']
        return x-r, y-r, x+r, y+r
    return None


class _PickIndex:
    def __init__(self, rows):
        self.rows = rows;self.boxes = {};self.cells = defaultdict(list)
        self.broad = [];self.drills = defaultdict(list)
        for i, row in enumerate(rows):
            if row['role'] == 'drill':self.drills[(row['uuid'], row['layer'])].append(row)
            if row['role'] in COPPER_ROLES:
                box = _bounds(row)
                if box:self.boxes[i] = box
        if not self.boxes:
            self.cell = 1.;return
        left = min(b[0] for b in self.boxes.values());right = max(b[2] for b in self.boxes.values())
        top = min(b[1] for b in self.boxes.values());bottom = max(b[3] for b in self.boxes.values())
        self.cell = max(math.sqrt(max(right-left, .01)*max(bottom-top, .01)/max(1, len(self.boxes))), .01)
        for i, (a, b, c, d) in self.boxes.items():
            x0, y0, x1, y1 = (math.floor(value/self.cell) for value in (a, b, c, d))
            if (x1-x0+1)*(y1-y0+1) > 256:
                self.broad.append(i);continue
            for x in range(x0, x1+1):
                for y in range(y0, y1+1):self.cells[x, y].append(i)

    def candidates(self, x, y, tolerance):
        x0, y0, x1, y1 = (math.floor(value/self.cell) for value in
                           (x-tolerance, y-tolerance, x+tolerance, y+tolerance))
        # A large pick radius must not allocate an unbounded cell walk.
        if (x1-x0+1)*(y1-y0+1) > 256:indices = self.boxes.keys()
        else:
            indices = set(self.broad)
            for a in range(x0, x1+1):
                for b in range(y0, y1+1):indices.update(self.cells.get((a, b), ()))
        return [self.rows[i] for i in sorted(indices)
                if self.boxes[i][0]-tolerance <= x <= self.boxes[i][2]+tolerance
                and self.boxes[i][1]-tolerance <= y <= self.boxes[i][3]+tolerance]


def extract_board(board, visible_nets=None):
    import pcbnew as p
    nets=None if visible_nets is None else set(visible_nets)
    scene = DisplayScene(layers={}, primitives=[], bounds=None, warnings=[], tessellation_mm=.01)
    if nets is not None:scene['net_scope']=sorted(nets)
    def excluded(item):
        name=str(item.GetNetname())
        return nets is not None and bool(name) and name not in nets
    enabled = list(board.GetEnabledLayers().Seq())
    copper = set(board.GetEnabledLayers().CuStack())
    scene['layers'] = {int(layer): str(board.GetLayerName(layer)) for layer in enabled}
    scene['canonical_layers'] = {int(layer): str(p.LayerName(layer)) for layer in enabled}
    def uid(item):
        return item.m_Uuid.AsString()
    def ring(chain):
        return [[p.ToMM(point.x), p.ToMM(point.y)] for point in chain.CPoints()]
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
        if excluded(item):continue
        role = 'via' if isinstance(item, p.PCB_VIA) else 'track'
        layers = [layer for layer in copper if item.IsOnLayer(layer)] if role == 'via' else [item.GetLayer()]
        for layer in layers:
            shape(item, layer, role)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if excluded(pad):continue
            for layer in copper:
                if pad.IsOnLayer(layer):
                    shape(pad, layer, 'pad', reference=fp.GetReference(), parent_uuid=uid(fp))
        items=list(fp.GraphicalItems())+list(fp.GetFields())
        seen=set()
        reference=uid(fp.Reference())
        for item in items:
            identity=uid(item)
            if identity in seen or not getattr(item,'IsVisible',lambda:True)():continue
            seen.add(identity)
            if hasattr(item, 'TransformShapeToPolygon'):
                shape(item, item.GetLayer(), 'reference' if identity==reference else 'footprint',
                      reference=fp.GetReference(), parent_uuid=uid(fp))
    for zone in board.Zones():
        if zone.GetIsRuleArea() or excluded(zone):
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


def visible_primitives(scene, visible_layers=None, visible_nets=None):
    layers = None if visible_layers is None else set(visible_layers)
    nets = None if visible_nets is None else set(visible_nets)
    return [row for row in scene['primitives'] if
            (row['role'] == 'outline' or layers is None or row['layer'] in layers)
            and (nets is None or row['role'] not in COPPER_ROLES | {'drill'} or row.get('net') in nets
                 or row['role']=='drill' and not row.get('net'))]


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
    layers = None if visible_layers is None else set(visible_layers)
    index = scene.pick_index() if isinstance(scene, DisplayScene) else None
    rows = index.candidates(x, y, max(1e-9, tolerance_mm)) if index else visible_primitives(scene, layers)
    drills = index.drills if index else None
    for row in rows:
        if layers is not None and row['layer'] not in layers:continue
        if row['role'] not in COPPER_ROLES or (net is not None and row.get('net') != net):
            continue
        if row['kind'] == 'polygon':
            hit = _inside((x, y), row['points']) and not any(_inside((x, y), hole) for hole in row.get('holes', []))
            # Explicit drill primitives share copper identity and are excluded from probes.
            if hit:
                matching = (drills.get((row['uuid'], row['layer']), ()) if drills is not None else
                            [d for d in scene['primitives'] if d['role']=='drill' and d['uuid']==row['uuid'] and d['layer']==row['layer']])
                hit = not any(_inside((x,y), d['points']) for d in matching)
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


def draw_matplotlib(ax, scene, visible_layers=None, highlight_ids=(), alpha=.45, highlight_nets=(), visible_nets=None,path_source=None):
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    artists = []
    rows = sorted(visible_primitives(scene, visible_layers, visible_nets), key=lambda r: r['role']=='drill')
    ids, nets = set(highlight_ids), set(highlight_nets)
    batches = defaultdict(list) if len(rows)>256 else None
    for row in rows:
        color, opacity = _color(row, ids, nets)
        highlighted = row.get('uuid') in ids or row.get('net') in nets
        if row['kind'] == 'polygon':
            provider=path_source if isinstance(path_source,DisplayScene) else scene
            if isinstance(provider, DisplayScene):path = provider.polygon_path(row)
            else:
                vertices, codes = [], []
                for ring in _rings(row):
                    if len(ring)<3: continue
                    vertices.extend(ring+[ring[0]])
                    codes.extend([Path.MOVETO]+[Path.LINETO]*(len(ring)-1)+[Path.CLOSEPOLY])
                path = Path(vertices, codes) if vertices else None
            if path is None:continue
            width=1.2 if highlighted else .4 if row['role']=='outline' else 0
            if batches is not None:
                batches[color, opacity, highlighted, row['role']=='drill',width].append(path)
                continue
            patch = PathPatch(path, facecolor=color, edgecolor=color,
                              linewidth=width,
                              alpha=opacity*alpha, zorder=6 if highlighted else 0)
            ax.add_patch(patch); artists.append(patch)
        elif row['kind'] == 'text':
            artists.append(ax.text(*row['center'], row['text'], fontsize=6, color=color,
                                   alpha=alpha, clip_on=True, zorder=1))
    if batches is not None:
        from matplotlib.collections import PathCollection
        for (color, opacity, highlighted, drill,width), paths in batches.items():
            collection = PathCollection(paths, facecolors=[color], edgecolors=[color],
                                        linewidths=width, alpha=opacity*alpha,
                                        zorder=6 if highlighted else .1 if drill else 0,
                                        transform=ax.transData)
            ax.add_collection(collection);artists.append(collection)
    return artists


def draw_wx(gc, scene, project, visible_layers=None, highlight_ids=(), alpha=.45, scale=1, highlight_nets=()):
    import wx
    ids, nets = set(highlight_ids), set(highlight_nets)
    for row in sorted(visible_primitives(scene, visible_layers), key=lambda r:r['role']=='drill'):
        color, opacity = _color(row, ids, nets)
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
