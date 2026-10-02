"""Read-only native PCB geometry preview for Fusion's placed source boards.

Coordinates and widths are millimetres.  The display is deliberately a review
aid: the merge engine, rather than this module, decides what is written.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
import hashlib
import math

import wx

_GEOMETRY_CACHE = {}


@dataclass(frozen=True)
class Primitive:
    alias: str
    layer: str
    kind: str                 # line, arc, polygon, circle
    points: tuple             # world XY coordinates, after placement
    width: float = 0.0
    hole: bool = False
    filled: bool = False
    text: str = ''


def _mm(value):
    import pcbnew
    return float(pcbnew.ToMM(value))


def _xy(point, shift):
    return (_mm(point.x) + shift[0], _mm(point.y) + shift[1])


def _contours(poly, shift, alias, layer, kind='polygon'):
    result = []
    for i in range(poly.OutlineCount()):
        chains = [(poly.COutline(i), False)]
        chains += [(poly.CHole(i, j), True) for j in range(poly.HoleCount(i))]
        for chain, hole in chains:
            points = tuple(_xy(chain.CPoint(j), shift) for j in range(chain.PointCount()))
            if len(points) >= 3:
                result.append(Primitive(alias, layer, kind, points, hole=hole))
    return result


def _arc_points(start, mid, end, shift):
    """Sample the actual three-point KiCad arc in its native world frame."""
    a, b, c = [_xy(p, shift) for p in (start, mid, end)]
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax * (by-cy) + bx * (cy-ay) + cx * (ay-by))
    if abs(d) < 1e-10:
        return (a, b, c)
    ux = ((ax*ax+ay*ay)*(by-cy)+(bx*bx+by*by)*(cy-ay)+(cx*cx+cy*cy)*(ay-by))/d
    uy = ((ax*ax+ay*ay)*(cx-bx)+(bx*bx+by*by)*(ax-cx)+(cx*cx+cy*cy)*(bx-ax))/d
    radius = math.hypot(ax-ux, ay-uy)
    angles = [math.atan2(y-uy, x-ux) for x, y in (a, b, c)]
    sweep = (angles[2]-angles[0]) % (2*math.pi)
    if (angles[1]-angles[0]) % (2*math.pi) > sweep:
        sweep -= 2*math.pi
    steps = max(8, min(256, math.ceil(abs(sweep)*radius/0.35)))
    return tuple((ux+radius*math.cos(angles[0]+sweep*i/steps),
                  uy+radius*math.sin(angles[0]+sweep*i/steps)) for i in range(steps+1))


def extract_board(source):
    """Extract visible geometry from the verified saved PCB, without changing it.

    Returns (primitives, status).  A stale or unparseable board is unavailable,
    never silently replaced with a bounding rectangle.
    """
    import pcbnew as p
    path = Path(source.pcb_file)
    if not path.is_file():
        return [], 'PCB file unavailable'
    expected = source.hashes.get(str(path.resolve())) or source.hashes.get(str(path))
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return [], f'PCB geometry unavailable: {exc}'
    if expected and actual != expected:
        return [], 'PCB changed since analysis; run Analyse again'
    mapping = source.layer_map or {}
    copper_layers = tuple(source.copper_layers or ['F.Cu', 'B.Cu'])
    key = (str(path.resolve()), actual, tuple(sorted(mapping.items())), copper_layers)
    placement = tuple(float(v) for v in source.translation)
    alias = source.alias
    def placed(items):
        return [replace(item, alias=alias, points=tuple((x+placement[0], y+placement[1])
                       for x, y in item.points)) for item in items]
    if key in _GEOMETRY_CACHE:
        geometry, status = _GEOMETRY_CACHE[key]
        return placed(geometry), status
    try:
        board = p.LoadBoard(str(path))
        if board is None:
            raise ValueError('KiCad returned no board')
        shift = (0.0, 0.0)
        alias = ''
        def layer_name(item):
            name = board.GetLayerName(item.GetLayer())
            return mapping.get(name, name)
        def is_copper(name):
            return name.endswith('.Cu')
        out = []
        # Tracks include straight segments, arcs and vias. Native widths and
        # drill diameters are kept so the display does not invent copper.
        for item in board.GetTracks():
            if isinstance(item, p.PCB_VIA):
                layers = [(board.GetLayerID(name), mapping.get(name, name))
                          for name in copper_layers
                          if item.IsOnLayer(board.GetLayerID(name))]
                center = _xy(item.GetPosition(), shift)
                for native_layer, layer in layers:
                    out.append(Primitive(alias, layer, 'circle', (center,),
                                         _mm(item.GetWidth(native_layer)), filled=True))
                if item.GetDrillValue():
                    out.append(Primitive(alias, 'Hole', 'circle', (center,), _mm(item.GetDrillValue()), True))
            else:
                layer = layer_name(item)
                if isinstance(item, p.PCB_ARC):
                    points = _arc_points(item.GetStart(), item.GetArcMid(), item.GetEnd(), shift)
                else:
                    points = (_xy(item.GetStart(), shift), _xy(item.GetEnd(), shift))
                out.append(Primitive(alias, layer, 'line', points, _mm(item.GetWidth())))
        for fp in board.GetFootprints():
            out.append(Primitive(alias,'Reference','text',(_xy(fp.GetPosition(),shift),),text=fp.GetReference()))
            for pad in fp.Pads():
                for layer in copper_layers:
                    native_layer = board.GetLayerID(layer)
                    if pad.IsOnLayer(native_layer):
                        target = mapping.get(layer, layer)
                        out += _contours(pad.GetEffectivePolygon(native_layer), shift, alias, target)
                drill = pad.GetDrillSize()
                if drill.x and drill.y:
                    hole = pad.GetEffectiveHoleShape()
                    start, end = _xy(hole.GetStart(), shift), _xy(hole.GetEnd(), shift)
                    diameter = _mm(hole.GetWidth())
                    out.append(Primitive(alias, 'Hole', 'circle' if start == end else 'line',
                                         (start,) if start == end else (start, end), diameter, True))
            for graphic in fp.GraphicalItems():
                out += _drawing(graphic, shift, alias, mapping, board, p)
            for zone in fp.Zones():
                out += _zone(zone, shift, alias, mapping, board, p)
        for graphic in board.GetDrawings():
            out += _drawing(graphic, shift, alias, mapping, board, p)
        for zone in board.Zones():
            out += _zone(zone, shift, alias, mapping, board, p)
        status = 'PCB geometry loaded' if out else 'PCB has no displayable geometry'
        if len(_GEOMETRY_CACHE) >= 128:
            _GEOMETRY_CACHE.pop(next(iter(_GEOMETRY_CACHE)))
        _GEOMETRY_CACHE[key] = (out, status)
        return placed(out), status
    except Exception as exc:
        return [], f'PCB geometry unavailable: {exc}'


def _drawing(item, shift, alias, mapping, board, p):
    if not isinstance(item, p.PCB_SHAPE):
        return []
    name = board.GetLayerName(item.GetLayer())
    if name != 'Edge.Cuts' and not name.endswith(('.Cu','.SilkS','.Fab','.CrtYd')):
        return []
    layer = mapping.get(name, name)
    shape = item.GetShape()
    width = _mm(item.GetWidth())
    if shape == p.SHAPE_T_CIRCLE:
        center = _xy(item.GetStart(), shift)
        radius = math.dist(center, _xy(item.GetEnd(), shift))
        return [Primitive(alias, layer, 'circle', (center,), radius*2+width)]
    if shape == p.SHAPE_T_ARC:
        points = _arc_points(item.GetStart(), item.GetArcMid(), item.GetEnd(), shift)
    elif shape == p.SHAPE_T_RECT:
        a = _xy(item.GetStart(), shift); b = _xy(item.GetEnd(), shift)
        points = (a, (b[0], a[1]), b, (a[0], b[1]), a)
    elif shape == p.SHAPE_T_POLY:
        return _contours(item.GetPolyShape(), shift, alias, layer)
    else:
        points = (_xy(item.GetStart(), shift), _xy(item.GetEnd(), shift))
    return [Primitive(alias, layer, 'line', points, width)]


def _zone(zone, shift, alias, mapping, board, p):
    if zone.GetIsRuleArea():
        return []
    out = []
    for native in range(p.PCB_LAYER_ID_COUNT):
        if not zone.IsOnLayer(native):
            continue
        name = board.GetLayerName(native)
        if not name.endswith('.Cu'):
            continue
        layer = mapping.get(name, name)
        filled = zone.GetFilledPolysList(native) if zone.HasFilledPolysForLayer(native) else None
        if filled is not None and filled.OutlineCount():
            out += _contours(filled, shift, alias, layer, 'zone_polygon')
        else:
            out += _contours(zone.Outline(), shift, alias, layer, 'zone_outline')
    return out


class PlacementPreview(wx.Panel):
    """Pan, zoom and inspect placed copper, holes and board cuts."""
    def __init__(self, parent):
        super().__init__(parent, size=(-1, 220))
        self.boxes = []
        self.primitives = []
        self.statuses = {}
        self.layers = {}
        self.layer = None
        self.selected_alias = None
        self.show_details = False
        self.show_references = False
        self.on_select = None
        self.on_move = None
        self.locked_aliases = set()
        self._move_alias = None
        self._move_delta = (0.0, 0.0)
        self.scale = None
        self.center = (0.0, 0.0)
        self._drag = None
        self.SetMinSize((-1, 170))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL, self._wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._down)
        self.Bind(wx.EVT_LEFT_UP, self._up)
        self.Bind(wx.EVT_MOTION, self._motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._capture_lost)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda event: self.fit())

    def show_sources(self, sources):
        self.boxes = [(s.alias, s.bbox[0]+s.translation[0], s.bbox[1]+s.translation[1],
                       s.bbox[2]+s.translation[0], s.bbox[3]+s.translation[1]) for s in sources]
        self.primitives = []
        self.statuses = {}
        for source in sources:
            geometry, status = extract_board(source)
            self.primitives.extend(geometry)
            self.statuses[source.alias] = status
        self.layers = {name: name for name in sorted({item.layer for item in self.primitives
                       if item.layer.endswith('.Cu')}, key=lambda x: (x != 'F.Cu', x == 'B.Cu', x))}
        self.fit()

    def clear(self):
        self.boxes = []
        self.primitives = []
        self.statuses = {}
        self.layers = {}
        self.selected_alias = None
        self.scale = None
        self.Refresh()

    def set_layer(self, layer=None):
        self.layer = layer
        self.Refresh()

    def set_selected_alias(self, alias=None):
        self.selected_alias = alias
        self.Refresh()

    def fit(self):
        if not self.boxes:
            self.scale = None; self.Refresh(); return
        x1 = min(b[1] for b in self.boxes); y1 = min(b[2] for b in self.boxes)
        x2 = max(b[3] for b in self.boxes); y2 = max(b[4] for b in self.boxes)
        w, h = self.GetClientSize()
        self.scale = max(0.001, min(max(1, w-45)/max(1, x2-x1),
                                    max(1, h-65)/max(1, y2-y1)))
        self.center = ((x1+x2)/2, (y1+y2)/2)
        self.Refresh()

    def _screen(self, point):
        w, h = self.GetClientSize()
        return (round(w/2+(point[0]-self.center[0])*self.scale),
                round(h/2+(point[1]-self.center[1])*self.scale))

    def _wheel(self, event):
        if self.scale is None:
            self.fit()
        if self.scale:
            self.scale *= 1.2 if event.GetWheelRotation() > 0 else 1/1.2
            self.Refresh()

    def _down(self, event):
        selected = None
        if self.scale and self.boxes:
            point = event.GetPosition()
            x = self.center[0] + (point.x-self.GetClientSize().width/2)/self.scale
            y = self.center[1] + (point.y-self.GetClientSize().height/2)/self.scale
            selected = next((a for a, x1, y1, x2, y2 in reversed(self.boxes)
                             if x1 <= x <= x2 and y1 <= y <= y2), None)
            if selected:
                self.set_selected_alias(selected)
                if callable(self.on_select): self.on_select(selected)
        self._move_alias = selected if selected not in self.locked_aliases and not event.ShiftDown() else None
        self._move_delta = (0.0, 0.0)
        self._drag = event.GetPosition()
        self.CaptureMouse()

    def _up(self, event):
        alias = self._move_alias
        delta = self._move_delta
        self._drag = None
        self._move_alias = None
        if self.HasCapture(): self.ReleaseMouse()
        if alias and delta != (0.0, 0.0) and callable(self.on_move):
            box = next(b for b in self.boxes if b[0] == alias)
            self.on_move(alias, box[1], box[2], delta)

    def _capture_lost(self, event):
        # Cancel an interrupted gesture; no placement commit was delivered.
        if self._move_alias:
            self.translate(self._move_alias, -self._move_delta[0], -self._move_delta[1])
        self._drag = self._move_alias = None
        self._move_delta = (0.0, 0.0)

    def translate(self, alias, dx, dy):
        self.boxes = [(a, x1+dx, y1+dy, x2+dx, y2+dy) if a == alias else (a,x1,y1,x2,y2)
                      for a,x1,y1,x2,y2 in self.boxes]
        self.primitives = [replace(p, points=tuple((x+dx,y+dy) for x,y in p.points))
                           if p.alias == alias else p for p in self.primitives]
        self.Refresh()

    def _motion(self, event):
        if self._drag is None or not event.Dragging() or not self.scale:
            return
        pos = event.GetPosition()
        if self._move_alias:
            dx, dy = (pos.x-self._drag.x)/self.scale, (pos.y-self._drag.y)/self.scale
            self.translate(self._move_alias, dx, dy)
            self._move_delta = (self._move_delta[0]+dx, self._move_delta[1]+dy)
            self._drag = pos
            return
        self.center = (self.center[0]-(pos.x-self._drag.x)/self.scale,
                       self.center[1]-(pos.y-self._drag.y)/self.scale)
        self._drag = pos
        self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        dc.SetBackground(wx.Brush(bg)); dc.Clear(); dc.SetTextForeground(fg)
        if not self.boxes:
            dc.DrawText('Run Analyse to preview source PCB geometry.', 12, 12)
            return
        if self.scale is None:
            self.fit()
        colours = {'F.Cu': wx.Colour(210, 70, 65), 'B.Cu': wx.Colour(65, 105, 210),
                   'Edge.Cuts': wx.Colour(80, 160, 90), 'Sheet':wx.Colour(65,145,175), 'Hole': bg}
        # Draw filled zone islands and their voids together, followed by pads,
        # traces and vias. A track inside a zone void must remain visible. The
        # actual drilled holes are the only geometry painted over all copper.
        for item in sorted(self.primitives, key=lambda p:
                           2 if p.layer == 'Hole' else
                           0 if p.kind in ('zone_polygon', 'zone_outline') else 1):
            if item.layer=='Reference' and not self.show_references:continue
            if item.layer.endswith(('.SilkS','.Fab','.CrtYd')) and not self.show_details:continue
            if self.layer and item.layer not in (self.layer, 'Edge.Cuts', 'Hole','Reference'):
                continue
            colour = colours.get(item.layer, wx.Colour(190, 145, 65))
            if self.selected_alias and item.alias != self.selected_alias:
                colour = wx.Colour(145, 145, 145)
            if item.hole:
                colour = bg
            dc.SetPen(wx.Pen(colour, max(1, round(item.width*self.scale)) if item.kind=='line' else 1,
                             wx.PENSTYLE_SHORT_DASH if item.kind=='zone_outline' else wx.PENSTYLE_SOLID))
            dc.SetBrush(wx.Brush(colour) if item.kind in ('polygon', 'zone_polygon')
                        or item.hole or item.filled else wx.TRANSPARENT_BRUSH)
            pts = [wx.Point(*self._screen(pt)) for pt in item.points]
            if item.kind=='text':
                dc.SetTextForeground(fg);dc.DrawText(item.text,pts[0].x+3,pts[0].y+3)
            elif item.kind in ('polygon', 'zone_polygon', 'zone_outline') and len(pts)>=3:
                dc.DrawPolygon(pts)
            elif item.kind == 'circle':
                diameter = max(1, round(item.width*self.scale))
                dc.DrawCircle(pts[0], max(1, diameter//2))
            elif len(pts)>=2:
                dc.DrawLines(pts)
        for alias, x1, y1, x2, y2 in self.boxes:
            a = self._screen((x1, y1)); b = self._screen((x2, y2))
            dc.SetPen(wx.Pen(wx.Colour(90, 130, 155), 1, wx.PENSTYLE_DOT))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(a[0], a[1], b[0]-a[0], b[1]-a[1])
            dc.DrawText(alias, a[0]+4, a[1]+3)
        unavailable = [f'{a}: {s}' for a, s in self.statuses.items() if s != 'PCB geometry loaded']
        if unavailable:
            dc.SetTextForeground(wx.Colour(170, 55, 45))
            dc.DrawText('; '.join(unavailable)[:180], 8, max(0, self.GetClientSize().height-22))
