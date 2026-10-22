"""Conservative, read-only silk label planning for native KiCad boards.

All settings are millimetres. Envelopes enclose native rendered glyphs;
rejected labels remain untouched. Optional bounded sizing never
shrinks below the user minimum or native fabrication floors.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import time
import fnmatch
import heapq

def point_segment_distance(point,start,end):
    dx,dy=end[0]-start[0],end[1]-start[1]
    length=dx*dx+dy*dy
    t=max(0,min(1,((point[0]-start[0])*dx+(point[1]-start[1])*dy)/length)) if length else 0
    return math.hypot(point[0]-start[0]-t*dx,point[1]-start[1]-t*dy)

def edges(ring):
    return zip(ring,ring[1:]+ring[:1])

def inside_ring(point,ring):
    x,y=point;inside=False
    for (ax,ay),(bx,by) in edges(ring):
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:inside=not inside
    return inside

def inside_polygon(point,outline,holes=()):
    return inside_ring(point,outline) and not any(inside_ring(point,h) for h in holes)

def disk_inside(point,radius,outline,holes=()):
    return inside_polygon(point,outline,holes) and all(
        point_segment_distance(point,a,b)>=radius for ring in [outline,*holes] for a,b in edges(ring))

def polygons(native):
    def ring(chain):
        return [(chain.CPoint(i).x,chain.CPoint(i).y) for i in range(chain.PointCount())]
    return [(ring(native.COutline(i)),[ring(native.CHole(i,h)) for h in range(native.HoleCount(i))]) for i in range(native.OutlineCount())]

def segment_hits_box(start,end,box,margin=0):
    """Liang-Barsky clipping, including endpoints and tangencies."""
    left,top,right,bottom=box.GetLeft()-margin,box.GetTop()-margin,box.GetRight()+margin,box.GetBottom()+margin
    dx,dy=end.x-start.x,end.y-start.y
    low,high=0.,1.
    for p,q in ((-dx,start.x-left),(dx,right-start.x),(-dy,start.y-top),(dy,bottom-start.y)):
        if p==0:
            if q<0:return False
            continue
        r=q/p
        if p<0:low=max(low,r)
        else:high=min(high,r)
        if low>high:return False
    return True

def board_fingerprint(board,ignore=()):
    """Snapshot relevant geometry; ignore only objects owned by this preview."""
    import hashlib,json
    ignored={item_id(x) for x in ignore}
    data=[]
    for getter in ('GetFootprints','GetTracks','GetDrawings','Zones'):
        for item in getattr(board,getter,lambda:[])():
            if item_id(item) in ignored:continue
            box=item.GetBoundingBox(False) if getter == 'GetFootprints' else item.GetBoundingBox()
            row=[item_id(item),box.GetLeft(),box.GetTop(),box.GetRight(),box.GetBottom()]
            for name in ('GetNetname','GetLayer','GetWidth','GetOrientationDegrees','GetDrillValue','GetAttribute'):
                fn=getattr(item,name,None)
                if fn:
                    try:row.append((name,str(fn(item.TopLayer()) if name=='GetWidth' and hasattr(item,'TopLayer') else fn())))
                    except (AttributeError,TypeError):pass
            for name in ('GetStart','GetEnd'):
                fn=getattr(item,name,None)
                if fn:
                    try:
                        point=fn();row.append((name,point.x,point.y))
                    except (AttributeError,TypeError):pass
            if getter=='GetFootprints':
                row.append([(item_id(p),p.GetPosition().x,p.GetPosition().y,p.GetNetname(),
                             p.GetSize().x,p.GetSize().y,float(p.GetOrientationDegrees()),
                             int(p.GetAttribute()),str(p.GetShape()),list(p.GetLayerSet().Seq())) for p in item.Pads()])
            if getter=='Zones':
                row.append(polygons(item.Outline()))
                row.append([(layer,polygons(item.GetFilledPolysList(layer))) for layer in item.GetLayerSet().Seq()])
            data.append(row)
    return hashlib.sha256(json.dumps(sorted(data,key=lambda x:x[0]),sort_keys=True).encode()).hexdigest()

def item_id(item):
    key=getattr(item,'m_Uuid',None)
    return str(key.AsString()) if key is not None else str(id(item))

def segment_segment_distance(a,b,c,d):
    """Minimum separation of closed 2D segments, including crossing segments."""
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    first,second=cross(a,b,c),cross(a,b,d)
    third,fourth=cross(c,d,a),cross(c,d,b)
    if first*second < 0 and third*fourth < 0:return 0.
    return min(point_segment_distance(a,c,d),point_segment_distance(b,c,d),
               point_segment_distance(c,a,b),point_segment_distance(d,a,b))

def segment_inside_native(start,end,radius,native):
    a,b=(start.x,start.y),(end.x,end.y)
    return any(disk_inside(a,radius,outer,holes) and disk_inside(b,radius,outer,holes)
               and all(segment_segment_distance(a,b,c,d)>=radius for ring in [outer,*holes] for c,d in edges(ring))
               for outer,holes in polygons(native))

DEFAULTS = dict(references=True, values=False, board_text=False, selected_only=False,
                problem_only=False, preserve_acceptable=True, orientation_preference='Footprint axis',
                height=1.0, thickness=0.15, clearance=0.2, max_radius=12.0,
                step=0.5, leaders=False, leader_distance=3.0, body_clearance=0.0, guide_thickness=0.08, edge_margin=0.5,
                normal_distance=2.0, min_width=0.6, min_width_ratio=0.75,
                repack_neighbours=6, repack_displacement=2.0, leader_limit=10, leader_max_length=3.0,
                auto_size=True, min_height=0.8, size_step=0.1,
                allowed_rotations=(0, 90, 45, 135, 15, 30, 60, 75, 105, 120, 150, 165), reading_direction='Bottom/right',
                formatting_rules=[], testpoint_net_names=False, testpoint_pattern='TP*',
                protect_tented_drills=False)
GUIDE_PREFIX = 'WayriCAD Silk guide '
NET_PREFIX = 'WayriCAD Silk net '


def _state(text):
    p, s = text.GetPosition(), text.GetTextSize()
    return (p.x, p.y, text.GetTextAngle().AsDegrees(), s.x, s.y,
            text.GetTextThickness(), text.IsMirrored(), text.IsBold(),
            text.IsItalic(), text.IsKnockout(),
            text.IsKeepUpright() if hasattr(text, 'IsKeepUpright') else None)


def _set(text, state, api):
    x, y, angle, w, h, stroke, mirror = state[:7]
    text.SetPosition(api.VECTOR2I(x, y))
    text.SetTextAngle(api.EDA_ANGLE(angle, api.DEGREES_T))
    text.SetTextSize(api.VECTOR2I(w, h))
    text.SetMirrored(mirror)
    if len(state) > 7:
        text.SetBold(state[7]); text.SetItalic(state[8]); text.SetIsKnockout(state[9])
        if state[10] is not None and hasattr(text, 'SetKeepUpright'):
            text.SetKeepUpright(state[10])
    # Native SetBold recalculates stroke width. Restore the reviewed width last.
    text.SetTextThickness(stroke)


def _texts(board, api):
    for fp in board.GetFootprints():
        for text in fp.GraphicalItems():
            if isinstance(text, api.PCB_TEXT):
                yield text, fp, 'graphic'
        for text in fp.GetFields():
            yield text, fp, 'reference' if text == fp.Reference() else 'value' if text == fp.Value() else 'field'
    for text in board.GetDrawings():
        if isinstance(text, api.PCB_TEXT):
            yield text, None, 'board'


def fingerprint(board, api):
    """Include text geometry, native silk floors and resolved via exposure."""
    rows = [(item_id(t), _state(t), t.GetText(), t.IsVisible(), t.IsLocked(), t.GetLayer(),
             t.IsBold(), t.IsItalic(), str(t.GetHorizJustify()), str(t.GetVertJustify()),
             t.GetFontName(), t.GetLineSpacing())
            for t, _, _ in _texts(board, api)]
    rows += [(item_id(fp), fp.IsLocked(), [(item_id(p), p.GetDrillSize().x,
             p.GetDrillSize().y, p.GetSolderMaskExpansion(api.F_Mask),
             p.GetSolderMaskExpansion(api.B_Mask)) for p in fp.Pads()])
             for fp in board.GetFootprints()]
    rows += [(item_id(track), track.HasSolderMask(), track.GetSolderMaskExpansion(),
              (track.TopLayer(),track.BottomLayer(),str(track.GetViaType()),
               track.IsTented(api.F_Mask),track.IsTented(api.B_Mask))
              if isinstance(track,api.PCB_VIA) else None)
             for track in board.GetTracks()]
    rows += [(item_id(group), group.GetName(), sorted(item_id(i) for i in group.GetItems()))
             for group in board.Groups()]
    for fp in board.GetFootprints():
        for graphic in fp.GraphicalItems():
            if isinstance(graphic, api.PCB_TEXT):continue
            box = graphic.GetBoundingBox()
            row = [item_id(graphic), graphic.GetLayer(), box.GetLeft(), box.GetTop(),
                   box.GetRight(), box.GetBottom()]
            for name in ('GetStart', 'GetEnd', 'GetMid'):
                getter = getattr(graphic, name, None)
                if getter:
                    point = getter();row.append((name, point.x, point.y))
            for name in ('GetShape', 'GetWidth', 'IsFilled'):
                getter = getattr(graphic, name, None)
                if getter:row.append((name, str(getter())))
            if hasattr(graphic, 'GetPolyShape'):
                row.append(polygons(graphic.GetPolyShape()))
            rows.append(row)
    ds = board.GetDesignSettings()
    floors = [getattr(ds, k, 0) for k in
              ('m_MinSilkTextHeight', 'm_MinSilkTextThickness', 'm_SilkClearance')]
    rows.append(('board-properties',sorted((str(key),str(value)) for key,value in board.GetProperties().items())))
    # Native Remove/Add can reorder identical text/groups during Undo.
    # Compare current properties canonically, never incidental container order.
    rows.sort(key=lambda row:str(row[0]))
    return hashlib.sha256((board_fingerprint(board) + json.dumps([rows, floors])).encode()).hexdigest()


@dataclass
class Change:
    item: object
    before: tuple
    after: tuple
    label: str
    box: object
    leader: tuple = None
    previous_guides: list = field(default_factory=list)
    leader_path: tuple = ()
    preview_item: object = None
    annotation: object = None
    sightline: tuple = ()
    footprint: object = None

    @property
    def suppressed_reference_id(self):
        return item_id(self.annotation.reference) if self.annotation and not self.annotation.remove else ''

    @property
    def suppressed_item_ids(self):
        return tuple(item_id(text) for text in self.annotation.originals) if self.annotation else ()

    @property
    def text(self): return self.item

    @property
    def position(self): return self.after[:2]

    @property
    def angle(self): return self.after[2]

    @property
    def size(self): return self.after[3:5]

    @property
    def thickness(self): return self.after[5]


@dataclass
class Plan:
    source_fingerprint: str
    settings: dict
    changes: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    unresolved_ids: set = field(default_factory=set)
    outcomes: list = field(default_factory=list)


@dataclass
class NetAnnotation:
    reference: object
    text: object
    group: object
    original_visibility: bool
    reference_visible_before: bool
    text_before: str
    net: str
    originals: tuple
    create: bool = False
    remove: bool = False


def _net_ownership(board, api):
    """Resolve saved ownership conservatively; never adopt arbitrary silk text."""
    footprints = {item_id(fp): fp for fp in board.GetFootprints()}
    drawings = {item_id(text) for text in board.GetDrawings()}
    result = {}
    for group in board.Groups():
        if not group.GetName().startswith(NET_PREFIX):continue
        try:
            data = json.loads(group.GetName()[len(NET_PREFIX):])
            if (not isinstance(data,dict) or set(data) != {'v','footprint','reference','visible'}
                    or data['v'] != 1 or not isinstance(data['visible'],bool)):
                raise ValueError('unsupported ownership metadata')
            fp = footprints[data['footprint']]
            reference = fp.Reference()
            members = list(group.GetItems())
            if (data['reference'] != item_id(reference) or len(members) != 1
                    or not isinstance(members[0],api.PCB_TEXT)
                    or item_id(members[0]) not in drawings
                    or members[0].GetParentFootprint() is not None
                    or members[0].GetParentGroup() is None
                    or members[0].GetParentGroupId().AsString() != item_id(group)
                    or data['footprint'] in result):
                raise ValueError('ownership does not resolve uniquely')
            result[data['footprint']] = (reference,members[0],group,data['visible'])
        except (ValueError,KeyError,TypeError) as exc:
            raise ValueError('Managed test-point label ownership is invalid. Restore or remove the affected ownership group before retrying.') from exc
    return result


def _selected_label(fp, reference, annotation=None):
    return (reference.IsSelected() or annotation is not None and annotation.IsSelected()
            or fp.IsSelected() or any(pad.IsSelected() for pad in fp.Pads()))


def _annotation_targets(board, api, options, texts, result):
    """Build detached presentation targets; reference values are never rewritten."""
    owners = _net_ownership(board,api)
    managed_ids = {item_id(row[1]) for row in owners.values()}
    actions, renders, blocked = {}, {}, set()
    targets = []
    patterns = [part.strip().casefold() for part in options['testpoint_pattern'].split(',') if part.strip()]
    for fp in board.GetFootprints():
        reference = fp.Reference();ref_id = item_id(reference)
        record = owners.get(item_id(fp))
        wanted = options['testpoint_net_names'] and any(fnmatch.fnmatchcase(fp.GetReference().casefold(),pattern) for pattern in patterns)
        if not wanted and record is None:continue
        blocked.add(ref_id)
        text, group = (record[1],record[2]) if record else (None,None)
        label = fp.GetReference() + ' / net'
        if options['selected_only'] and not _selected_label(fp,reference,text):continue
        if (fp.IsLocked() or reference.IsLocked() or text is not None and text.IsLocked()
                or group is not None and (group.IsLocked() or group.GetParentGroup() is not None)):
            result.skipped.append((label,'Locked footprint, reference or managed annotation; original retained.'));continue
        if wanted:
            if (text is None and not reference.IsVisible()) or text is not None and not text.IsVisible():
                result.skipped.append((label,'Hidden reference or managed annotation; original retained.'));continue
            nets = {pad.GetNetname() for pad in fp.Pads() if pad.GetNetCode() > 0 and pad.GetNetname()}
            if len(nets) != 1:
                reason = 'No connected pad net' if not nets else 'Ambiguous connected pad nets: ' + ', '.join(sorted(nets))
                result.skipped.append((label,reason+'; original retained.'));continue
            net = next(iter(nets))
            if '${' in net or any(ord(char)<32 or ord(char)==127 for char in net):
                result.skipped.append((label,'Net contains text-variable or control syntax that cannot be displayed literally; original retained.'));continue
            create = record is None
            if create:
                text = api.PCB_TEXT(board)
                text.SetAttributes(reference)
                text.SetLayer(reference.GetLayer());text.SetText(net);text.SetVisible(True)
                group = api.PCB_GROUP(board)
                data = dict(v=1,footprint=item_id(fp),reference=ref_id,visible=reference.IsVisible())
                group.SetName(NET_PREFIX+json.dumps(data,sort_keys=True,separators=(',',':')))
            render = api.PCB_TEXT(text);render.SetText(net)
            originals = (reference,) if create else (reference,text)
            action = NetAnnotation(reference,text,group,record[3] if record else reference.IsVisible(),
                                   reference.IsVisible(),text.GetText(),net,originals,create=create)
            targets.append((text,fp,'testpoint'))
        else:
            net = text.GetText()
            render = api.PCB_TEXT(reference);render.SetVisible(record[3])
            action = NetAnnotation(reference,text,group,record[3],reference.IsVisible(),
                                   text.GetText(),net,(reference,text),remove=True)
            targets.append((reference,fp,'restore_reference'))
        key = item_id(targets[-1][0]);actions[key] = action;renders[key] = render
    # Managed board text is handled only through its explicit owner, never by
    # the unrelated "board text" switch. Blocked references stay fixed unless
    # a safe replacement/restoration is accepted.
    working = [(text,fp,kind) for text,fp,kind in texts
               if item_id(text) not in managed_ids and item_id(text) not in blocked]
    return working+targets, actions, renders


def text_geometry(text, state, api):
    """Native filled glyph/knockout geometry at the reviewed size and placement."""
    clone = api.PCB_TEXT(text)
    clone.SetText(text.GetShownText(False))
    clone.SetLayer(text.GetLayer())
    _set(clone, state, api)
    shape = api.SHAPE_POLY_SET()
    clone.TransformTextToPolySet(shape, 0, api.FromMM(.001), api.ERROR_OUTSIDE)
    return clone, shape


def _box(text, state, api):
    """Reserve the complete visible glyph envelope, without font layout padding.

    KiCad's text layout box includes ascent/descent padding beyond the rendered
    strokes. The native filled polygons include stroke and knockout geometry;
    their bounding rectangle plus clearance is the manufacturing obstacle.
    """
    clone, shape = text_geometry(text, state, api)
    return shape.BBox() if shape.OutlineCount() else clone.GetBoundingBox()


def courtyard_envelopes(fp, api):
    """Refresh native caches and reserve each face's whole courtyard envelope.

    Open/invalid courtyards still reserve their drawn extents. A footprint with
    no courtyard on its component face uses its conservative native body hull.
    """
    fp.BuildCourtyardCaches()
    owner = api.B_SilkS if fp.GetLayer() == api.B_Cu else api.F_SilkS
    result = {}
    for silk, court in ((api.F_SilkS, api.F_CrtYd), (api.B_SilkS, api.B_CrtYd)):
        hull = fp.GetCourtyard(court)
        box = hull.BBox() if hull.OutlineCount() else None
        for graphic in fp.GraphicalItems():
            if not hull.OutlineCount() and graphic.GetLayer() == court:
                if box is None:box = graphic.GetBoundingBox()
                else:box.Merge(graphic.GetBoundingBox())
        if box is None and silk == owner:
            hull = fp.GetBoundingHull()
            box = hull.BBox() if hull.OutlineCount() else fp.GetBoundingBox(False)
        if box is not None:result[silk] = box
    return result


def _typography(options):
    """Validate finite explicit reading angles and ordered style rules."""
    rotations = options['allowed_rotations']
    if not isinstance(rotations, (list, tuple)) or not rotations:
        raise ValueError('Choose at least one allowed rotation in [0, 180) degrees.')
    if len(rotations)>36 or any(isinstance(a, bool) or not isinstance(a,(int,float)) or not math.isfinite(a) or not 0<=a<180 for a in rotations):
        raise ValueError('Choose at most 36 finite angles in [0, 180) degrees.')
    options['allowed_rotations'] = tuple(dict.fromkeys(rotations))
    if options['reading_direction'] not in ('Bottom/right', 'Top/left', 'Either'):
        raise ValueError('Unknown reading direction.')
    rules = options['formatting_rules']
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError('Formatting rules must be a list with at most 100 entries.')
    keys = {'name', 'ref_pattern', 'value_pattern', 'text_pattern', 'bold', 'italic', 'knockout'}
    for rule in rules:
        if not isinstance(rule, dict) or set(rule)-keys:
            raise ValueError('Unknown formatting rule fields.')
        if not any(rule.get(k, '') for k in ('ref_pattern', 'value_pattern', 'text_pattern')):
            raise ValueError('A formatting rule needs an explicit reference, value or text pattern.')
        for key in ('name', 'ref_pattern', 'value_pattern', 'text_pattern'):
            if key in rule and not isinstance(rule[key], str):
                raise ValueError('Formatting patterns must be strings.')
        for key in ('bold', 'italic', 'knockout'):
            if key in rule and not isinstance(rule[key], bool):
                raise ValueError('Formatting styles must be true or false.')


def _style(text, fp, rules):
    """First matching rule wins; provided wildcard criteria are ANDed."""
    values = {'ref_pattern': fp.GetReference() if fp else '',
              'value_pattern': fp.GetValue() if fp else '',
              'text_pattern': text.GetShownText(False)}
    for rule in rules:
        if all(any(fnmatch.fnmatchcase(values[key].casefold(), pattern.strip().casefold())
                       for pattern in rule[key].split(',') if pattern.strip())
               for key in values if rule.get(key, '')):
            return rule
    return {}


def _angles(options, old_angle, footprint_axis=None):
    """Angles are board coordinates viewed from the text's own board side."""
    bases = options['allowed_rotations']
    direction = options['reading_direction']
    angles = [float(a+d) for d in ((0, 180) if direction == 'Either' else
                                  (180,) if direction == 'Top/left' else (0,)) for a in bases]
    # A common direction wins over each label's existing rotation. Explicit
    # Orthogonal reading directions dominate the public reference-board corpus.
    # Diagonal 45-degree increments precede finer-angle fallbacks.
    ordered=sorted(angles, key=lambda a: (a%180 != 0, a%90 != 0, a%45 != 0, a%180, a))
    if options.get('orientation_preference')=='Footprint axis' and footprint_axis is not None:
        axis=footprint_axis%180
        preferred=(axis,(axis+90)%180)
        ordered.sort(key=lambda a: preferred.index(a%180) if a%180 in preferred else 2)
    return ordered


def _inflate(box, distance, api):
    return api.BOX2I(api.VECTOR2I(box.GetLeft()-distance, box.GetTop()-distance),
                    api.VECTOR2I(box.GetWidth()+2*distance, box.GetHeight()+2*distance))


def box_distance(first, second):
    """Shortest distance between closed native rectangles, in board units."""
    return math.hypot(max(first.GetLeft()-second.GetRight(),
                          second.GetLeft()-first.GetRight(),0),
                      max(first.GetTop()-second.GetBottom(),
                          second.GetTop()-first.GetBottom(),0))


def edge_alignment(bounds,body,margin):
    """Rank projected edge corridors using the label centre, allowing spill.

    A wide label centred on a short edge remains aligned even when its ends
    extend outside the two projected corner lines. This is a reading preference,
    not a clearance exemption; every candidate still passes the geometry gates.
    """
    left,top,right,bottom=bounds
    bl,bt,br,bb=body
    cx,cy=(left+right)/2,(top+bottom)/2
    offsets=[]
    if (right<=bl or left>=br) and bt-margin<=cy<=bb+margin:
        offsets.append(abs(cy-(bt+bb)/2))
    if (bottom<=bt or top>=bb) and bl-margin<=cx<=br+margin:
        offsets.append(abs(cx-(bl+br)/2))
    return (0,min(offsets)) if offsets else (1,min(abs(cx-(bl+br)/2),abs(cy-(bt+bb)/2)))


def native_shape_gap(first,second,api):
    """Distance in millimetres between native filled polygons, or unknown."""
    if not first.OutlineCount() or not second.OutlineCount():return None
    if first.Collide(second,0):return 0.
    a,b=api.VECTOR2I(),api.VECTOR2I()
    if not first.NearestPoints(second,a,b):return None
    return math.hypot(a.x-b.x,a.y-b.y)/api.FromMM(1)


def _line_state(shape):
    a,b = shape.GetStart(),shape.GetEnd()
    return (a.x,a.y,b.x,b.y,shape.GetWidth(),shape.GetLayer())


class _SpatialIndex:
    """Uniform grid of conservative envelopes, including large global items."""
    def __init__(self, cell):
        self.cell = cell
        self.buckets, self.large, self.rows = {}, [], []
        self.removed = set()
        self.segments = {}

    def _cells(self, box):
        left,right = box.GetLeft()//self.cell,box.GetRight()//self.cell
        top,bottom = box.GetTop()//self.cell,box.GetBottom()//self.cell
        if (right-left+1)*(bottom-top+1) > 1024:
            return None
        return [(x,y) for x in range(left,right+1) for y in range(top,bottom+1)]

    def add(self, box, key, segment=None):
        row = len(self.rows)
        self.rows.append((box,key))
        if segment is not None:self.segments[id(box)] = segment
        cells = self._cells(box)
        if cells is None:
            self.large.append(row)
        else:
            for cell in cells:
                self.buckets.setdefault(cell,[]).append(row)

    def discard(self, key):
        """Remove an owner's envelopes without rebuilding the spatial grid."""
        self.removed.update(i for i, (_, owner) in enumerate(self.rows) if owner == key)

    def query(self, box):
        cells = self._cells(box)
        if cells is None:
            return [row for i,row in enumerate(self.rows) if i not in self.removed]
        rows = set(self.large)
        for cell in cells:
            rows.update(self.buckets.get(cell,()))
        return [self.rows[i] for i in sorted(rows) if i not in self.removed]

    def hits_box(self, box, clearance, body_clearance, api, ignore=()):
        """Broad-phase rectangles; full guide strokes get a segment narrow phase."""
        for obstacle,key in self.query(_inflate(box,max(clearance,body_clearance),api)):
            if key in ignore:continue
            margin=0 if key.startswith('sight:') else body_clearance if key.startswith('body:') else clearance
            segment=self.segments.get(id(obstacle))
            if segment is not None:
                if segment_hits_box(api.VECTOR2I(*segment[:2]),api.VECTOR2I(*segment[2:4]),box,margin+segment[4]//2):return True
            elif _inflate(box,margin,api).Intersects(obstacle):return True
        return False

    def hits_segment(self, segment, clearance, body_clearance, api, ignore=()):
        """Use centreline separation for guides, not filled diagonal AABBs."""
        p,q=api.VECTOR2I(*segment[:2]),api.VECTOR2I(*segment[2:4])
        for obstacle,key in self.query(_line_box(segment,api,max(clearance,body_clearance))):
            if key in ignore:continue
            margin=0 if key.startswith('sight:') else body_clearance if key.startswith('body:') else clearance
            other=self.segments.get(id(obstacle))
            if other is not None:
                if segment_segment_distance(segment[:2],segment[2:4],other[:2],other[2:4])<=margin+(segment[4]+other[4])/2:return True
            elif segment_hits_box(p,q,obstacle,margin+segment[4]//2):return True
        return False


def via_silkscreen_obstacle(via, silk, api, protect_tented_drills=False):
    """Reserve exposed annulus or physical drill on the relevant via face.

    Native per-face tenting determines whether a mask opening exists. Covered
    vias do not obstruct silk; optional drill protection reserves the physical
    drill even beneath tenting. Exposed vias reserve their entire annulus.
    Blind/buried vias reserve only faces reached by their copper layer span.
    """
    copper,mask=(api.F_Cu,api.F_Mask) if silk==api.F_SilkS else (api.B_Cu,api.B_Mask)
    if not via.IsOnLayer(copper):return None
    if via.IsTented(mask):
        if not protect_tented_drills:return None
        diameter=via.GetDrillValue()
        if diameter<=0:return None
        position=via.GetPosition()
        return api.BOX2I(api.VECTOR2I(position.x-diameter//2,position.y-diameter//2),
                         api.VECTOR2I(diameter,diameter))
    return _inflate(via.GetBoundingBox(),max(0,via.GetSolderMaskExpansion()),api)


def _leader_segments(change):
    if change.leader_path:
        width,layer = change.leader[4:]
        return [(a[0],a[1],b[0],b[1],width,layer)
                for a,b in zip(change.leader_path,change.leader_path[1:])]
    return [change.leader] if change.leader else []


def _line_box(segment, api, margin=0):
    a,b,c,d,w,_ = segment
    radius = w//2+margin
    return api.BOX2I(api.VECTOR2I(min(a,c)-radius,min(b,d)-radius),
                     api.VECTOR2I(abs(a-c)+2*radius,abs(b-d)+2*radius))


def plan(board, api, settings=None, progress=None):
    """Return proposed text moves; never mutate the board during planning.

    references/values select shown footprint fields; board_text selects existing
    silk text. selected_only restricts to selected footprints/text. max_radius
    bounds a deterministic orthogonal search. auto_size searches the preferred
    height down to the larger user/native minimum in bounded size steps. Allowed
    orientations and reading direction apply on each text's own board side.
    Ordered wildcard rules explicitly select styles; unspecified styles remain.
    leaders link distant fields to
    their body envelope only when the complete guide line is obstacle-free.
    """
    if getattr(board, 'raw', None) is not None:
        raise ValueError('Silkscreen placement requires the live native KiCad board.')
    options = dict(DEFAULTS)
    if settings:
        unknown = set(settings)-set(options)
        if unknown:
            raise ValueError('Unknown settings: ' + ', '.join(sorted(unknown)))
        options.update(settings)
    for name in ('height', 'thickness', 'clearance', 'max_radius', 'step', 'leader_distance', 'min_height', 'size_step', 'guide_thickness','normal_distance','min_width','min_width_ratio','leader_max_length'):
        value = float(options[name])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name + ' must be finite and positive.')
        options[name] = value
    options['body_clearance']=float(options['body_clearance'])
    if not math.isfinite(options['body_clearance']) or options['body_clearance']<0:
        raise ValueError('Courtyard padding must be finite and nonnegative.')
    options['edge_margin']=float(options['edge_margin'])
    if not math.isfinite(options['edge_margin']) or options['edge_margin']<0:
        raise ValueError('Projected-edge margin must be finite and nonnegative.')
    if options['min_width_ratio']>1:raise ValueError('Minimum width ratio must not exceed 1.')
    options['repack_displacement']=float(options['repack_displacement'])
    if not math.isfinite(options['repack_displacement']) or options['repack_displacement']<0:
        raise ValueError('Local repacking displacement must be finite and nonnegative.')
    for name,maximum in (('repack_neighbours',12),('leader_limit',100000)):
        if isinstance(options[name],bool) or not isinstance(options[name],int) or not 0<=options[name]<=maximum:
            raise ValueError(name+' must be an integer between 0 and '+str(maximum)+'.')
    for name in ('preserve_acceptable','problem_only'):
        if not isinstance(options[name],bool):raise ValueError(name+' must be enabled or disabled explicitly.')
    if options['orientation_preference'] not in ('Footprint axis','Common direction'):
        raise ValueError('Choose footprint-axis or common-direction orientation.')
    _typography(options)
    if not isinstance(options['protect_tented_drills'],bool):
        raise ValueError('Tented-via drill protection must be enabled or disabled explicitly.')
    if not isinstance(options['testpoint_net_names'],bool):
        raise ValueError('Test-point net names must be enabled or disabled explicitly.')
    if (not isinstance(options['testpoint_pattern'],str)
            or options['testpoint_net_names'] and not any(part.strip() for part in options['testpoint_pattern'].split(','))):
        raise ValueError('Enter at least one test-point reference pattern.')
    if api.FromMM(options['size_step']) < 1:
        raise ValueError('Size step must be at least one native distance unit.')
    if options['min_height'] > options['height'] and options['auto_size']:
        raise ValueError('Minimum text height must not exceed preferred height.')
    if options['auto_size'] and (options['height']-options['min_height'])/options['size_step'] > 15:
        raise ValueError('Automatic sizing supports at most 16 size steps.')
    if options['max_radius']/options['step'] > 40:
        raise ValueError('Search radius must be at most 40 search steps.')
    ds = board.GetDesignSettings()
    height = max(api.FromMM(options['height']), ds.m_MinSilkTextHeight)
    stroke = max(api.FromMM(options['thickness']), ds.m_MinSilkTextThickness)
    clearance = max(api.FromMM(options['clearance']), ds.m_SilkClearance)
    body_clearance = api.FromMM(options['body_clearance'])
    guide_stroke = max(api.FromMM(options['guide_thickness']), ds.m_MinSilkTextThickness)
    if stroke*4 > height:
        raise ValueError('Text height must be at least four times its stroke.')
    outline = api.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(outline, False) or not outline.OutlineCount():
        raise ValueError('A closed valid Edge.Cuts outline is required.')
    result = Plan(fingerprint(board, api), options)
    texts = list(_texts(board, api))
    working_texts, annotation_actions, render_items = _annotation_targets(board,api,options,texts,result)
    obstacles = {api.F_SilkS: [], api.B_SilkS: []}
    bodies = {}
    guides, guide_owners = {}, {}
    obstacle_segments = {}
    from .lifecycle import verified_group_ids, audit
    verified_groups=verified_group_ids(board,api)
    # Namespace-only guides are never deleted, but their semantic corridors
    # still block unrelated associations rather than becoming decorative ink.
    legacy_guides={item_id(shape) for group in board.Groups()
                   if group.GetName().startswith(GUIDE_PREFIX) and item_id(group) not in verified_groups
                   for shape in group.GetItems()}
    for finding in audit(board,api).findings:
        if finding.get('status') in ('legacy_unverified','uncertain','orphan_metadata','orphan','duplicate','detached'):
            result.skipped.append(('Generated objects',finding.get('reason') or finding['status']))
    for group in board.Groups():
        if item_id(group) not in verified_groups:
            continue
        owner = group.GetName()[len(GUIDE_PREFIX):]
        shapes = list(group.GetItems())
        if shapes and all(isinstance(s,api.PCB_SHAPE) and s.GetShape() == api.SHAPE_T_SEGMENT
                          and s.GetLayer() in obstacles for s in shapes):
            guides.setdefault(owner,[]).append((group,shapes))
            guide_owners.update((item_id(s),owner) for s in shapes)
    for fp in board.GetFootprints():
        layer = api.B_SilkS if fp.GetLayer() == api.B_Cu else api.F_SilkS
        envelopes = courtyard_envelopes(fp, api)
        bodies[item_id(fp)] = envelopes[layer]
        for silk, body in envelopes.items():
            bodies[(item_id(fp),silk)] = body
            obstacles[silk].append((body, 'body:' + item_id(fp)))
        # Fabrication outlines can reveal an undersized/missing courtyard.
        # Reserve their envelope on the physical component face, excluding
        # reference/value placeholders. This remains a 2D package proxy.
        fab=api.B_Fab if layer==api.B_SilkS else api.F_Fab
        package=None
        for graphic in fp.GraphicalItems():
            if graphic.GetLayer()==fab and not isinstance(graphic,api.PCB_TEXT):
                if package is None:package=graphic.GetBoundingBox()
                else:package.Merge(graphic.GetBoundingBox())
        if package is not None:obstacles[layer].append((package,'body:'+item_id(fp)))
        for pad in fp.Pads():
            for silk, mask in ((api.F_SilkS, api.F_Mask), (api.B_SilkS, api.B_Mask)):
                if pad.IsOnLayer(mask) or pad.GetDrillSize().x or pad.GetDrillSize().y:
                    expansion = max(0, pad.GetSolderMaskExpansion(mask))
                    obstacles[silk].append((_inflate(pad.GetBoundingBox(), expansion, api), item_id(pad)))
        for graphic in fp.GraphicalItems():
            if graphic.GetLayer() in obstacles and not isinstance(graphic, api.PCB_TEXT):
                obstacles[graphic.GetLayer()].append((graphic.GetBoundingBox(), item_id(graphic)))
            for silk, mask in ((api.F_SilkS,api.F_Mask),(api.B_SilkS,api.B_Mask)):
                if graphic.GetLayer() == mask:
                    obstacles[silk].append((graphic.GetBoundingBox(),item_id(graphic)))
    for graphic in board.GetDrawings():
        if graphic.GetLayer() in obstacles and not isinstance(graphic, api.PCB_TEXT):
            oid = item_id(graphic)
            box=graphic.GetBoundingBox()
            obstacles[graphic.GetLayer()].append((box,'guide:'+guide_owners[oid] if oid in guide_owners else
                'legacy-guide:'+oid if oid in legacy_guides else oid))
            if isinstance(graphic,api.PCB_SHAPE) and graphic.GetShape()==api.SHAPE_T_SEGMENT:obstacle_segments[id(box)]=_line_state(graphic)
        for silk, mask in ((api.F_SilkS,api.F_Mask),(api.B_SilkS,api.B_Mask)):
            if graphic.GetLayer() == mask:
                obstacles[silk].append((graphic.GetBoundingBox(),item_id(graphic)))
    for track in board.GetTracks():
        for silk, copper in ((api.F_SilkS,api.F_Cu),(api.B_SilkS,api.B_Cu)):
            if isinstance(track,api.PCB_VIA):
                box=via_silkscreen_obstacle(track,silk,api,options['protect_tented_drills'])
                if box is not None:obstacles[silk].append((box,item_id(track)))
            elif track.GetLayer() == copper and track.HasSolderMask():
                expansion = max(0,track.GetSolderMaskExpansion())
                obstacles[silk].append((_inflate(track.GetBoundingBox(),expansion,api),item_id(track)))
    eligible = []
    for text, fp, kind in working_texts:
        layer,key = text.GetLayer(),item_id(text)
        annotation = annotation_actions.get(key)
        render = render_items.get(key,text)
        label = (fp.GetReference() + ' / ' if fp else '') + render.GetShownText(False)
        enabled = True if annotation else options['references'] if kind == 'reference' else options['values'] if kind == 'value' else options['board_text'] if kind == 'board' else False
        if not enabled:continue
        if layer not in obstacles:
            if kind=='reference' and (not options['selected_only'] or _selected_label(fp,text)):
                result.skipped.append((label,'Reference is on '+board.GetLayerName(layer)+'; outside silkscreen scope, original retained.'))
            continue
        if (not text.IsVisible() and not (annotation and annotation.remove)) or text.IsLocked() or (fp and fp.IsLocked()):
            result.skipped.append((label,'Hidden or locked text/footprint.'))
            continue
        if options['selected_only'] and annotation is None and not (text.IsSelected() or fp and
                (fp.IsSelected() or any(p.IsSelected() for p in fp.Pads()))):
            continue
        before = _state(text)
        base = list(before)
        style = _style(render, fp, options['formatting_rules'])
        base[7] = style.get('bold', before[7])
        base[8] = style.get('italic', before[8])
        base[9] = style.get('knockout', before[9])
        # Native field keep-upright otherwise reverses intentional 180/270 text.
        base[10] = False if before[10] is not None else None
        base[6] = layer == api.B_SilkS
        templates = []
        if options['auto_size']:
            minimum = max(api.FromMM(options['min_height']), ds.m_MinSilkTextHeight,
                          4*ds.m_MinSilkTextThickness)
            if minimum > height:
                raise ValueError('Preferred height is below the native text/stroke floor.')
            # Correcting a small reference must not enlarge it merely because
            # the preferred-height control has a larger default value.
            preferred = max(minimum,min(height,before[4]))
            sizes = list(range(preferred, minimum-1, -api.FromMM(options['size_step'])))
            if not sizes or sizes[-1] != minimum:
                sizes.append(minimum)
        else:
            sizes = [None]
        for size in sizes:
            if size is None:
                base[3],base[4] = max(before[3],height),max(before[4],height)
                base[5] = max(before[5],stroke)
            else:
                # Preserve deliberately condensed or stretched lettering;
                # changing only placement must not widen an existing label.
                base[3] = max(1,round(before[3]*size/max(1,before[4])))
                base[4] = size
                base[5] = max(ds.m_MinSilkTextThickness,
                              min(before[5],stroke, round(stroke*size/height)))
            if base[5]*4 > base[4]:
                continue
            floor=max(api.FromMM(options['min_width']),round(base[4]*options['min_width_ratio']),4*base[5])
            base[3]=max(base[3],floor)
            widths=list(dict.fromkeys((base[3],floor))) if options['auto_size'] else [base[3]]
            for width in widths:
                sized=list(base);sized[3]=width
                for angle in _angles(options, before[2],fp.GetOrientationDegrees() if fp else None):
                    state = tuple(sized[:2]+[angle]+sized[3:])
                    templates.append((state,_box(render,state,api)))
        if not templates:
            raise ValueError('Text height must be at least four times its stroke.')
        priority = max(box.GetWidth()*box.GetHeight() for _,box in templates)
        eligible.append((text,fp,key,label,before,templates,priority))
    eligible.sort(key=lambda row:(-row[6],row[3].casefold(),row[2]))
    label_by_key = {row[2]:row[3] for row in eligible}
    all_keys = set(label_by_key)
    # Dense mode automatically samples at the clearance scale while preserving
    # the user's text floors. Candidate and wall-time budgets bound finer grids.
    step = min(api.FromMM(options['step']),clearance,api.FromMM(.25))
    rings = int(api.FromMM(options['max_radius'])/step)
    native_polygons = polygons(outline)
    boundary = _SpatialIndex(api.FromMM(4))
    boundary_edges = []
    for outer,holes in native_polygons:
        for ring in [outer,*holes]:
            for a,b in edges(ring):
                segment = (*a,*b,0,0)
                boundary.add(_line_box(segment,api),len(boundary_edges))
                boundary_edges.append((a,b))
    started = time.monotonic()
    # Each reference receives its own allowance, independent of board size.
    # A crowded early label cannot consume the later labels' search time.
    checks = [0]
    attempts_by_key = {}
    leader_budget_keys=set();leader_length_keys=set()
    limited_keys = set()
    label_deadline = [float('inf')]

    def inside(a,b,radius):
        first,second = (a.x,a.y),(b.x,b.y)
        if not outline.Contains(a) or not outline.Contains(b):
            return False
        region = _line_box((*first,*second,0,0),api,radius)
        return all(segment_segment_distance(first,second,*boundary_edges[index])>=radius
                   for _,index in boundary.query(region))

    def raw_positions(origin,before,fp,templates,layer,local,index):
        radius = api.FromMM(min(options['normal_distance'],options['max_radius']) if local else options['max_radius'])
        body = bodies.get((item_id(fp),layer),bodies[item_id(fp)]) if fp else None
        def near(x,y):
            # Search distance is measured from the footprint envelope, so large
            # connectors are not penalized for their distance from their origin.
            if body:
                for _,template in templates:
                    left,top=template.GetLeft()+x-before[0],template.GetTop()+y-before[1]
                    dx=max(body.GetLeft()-left-template.GetWidth(),left-body.GetRight(),0)
                    dy=max(body.GetTop()-top-template.GetHeight(),top-body.GetBottom(),0)
                    if math.hypot(dx,dy)<=radius:return True
                return False
            return math.hypot(x-origin.x,y-origin.y)<=radius
        if near(before[0],before[1]):yield before[0],before[1]
        if fp:
            body = bodies.get((item_id(fp),layer),bodies[item_id(fp)])
            # Clearance-derived side positions find narrow slots even when
            # their centre does not lie on the user-visible search grid.
            for state,box in templates:
                left = body.GetLeft()-body_clearance-1-(box.GetRight()-before[0])
                right = body.GetRight()+body_clearance+1-(box.GetLeft()-before[0])
                top = body.GetTop()-body_clearance-1-(box.GetBottom()-before[1])
                bottom = body.GetBottom()+body_clearance+1-(box.GetTop()-before[1])
                centre_x=body.GetCenter().x-(box.GetCenter().x-before[0])
                centre_y=body.GetCenter().y-(box.GetCenter().y-before[1])
                for distance in range((min(rings,12) if local else rings)+1):
                    for offset in ({0} if not distance else (-distance*step,distance*step)):
                        corridor = 2*clearance+guide_stroke+api.FromMM(.1)
                        offsets = (0,corridor) if options['leaders'] else (0,)
                        for extra in offsets:
                            for x,y in ((left-extra,centre_y+offset),(right+extra,centre_y+offset),
                                        (centre_x+offset,top-extra),(centre_x+offset,bottom+extra)):
                                if near(x,y):
                                    yield x,y
        # Native obstacle edges reveal narrow off-grid slots without scanning
        # thousands of empty grid positions. Limit axes before combining them.
        region = _inflate(body,radius,api) if body else api.BOX2I(
            api.VECTOR2I(origin.x-radius,origin.y-radius),api.VECTOR2I(2*radius,2*radius))
        nearby = sorted((obstacle for obstacle,_ in index.query(region)),
                        key=lambda r:(abs(r.GetCenter().x-origin.x)+abs(r.GetCenter().y-origin.y),r.GetLeft(),r.GetTop()))[:64]
        for state,box in templates:
            xs={origin.x};ys={origin.y}
            for obstacle in nearby:
                xs.update((obstacle.GetLeft()-clearance-1-(box.GetRight()-before[0]),
                           obstacle.GetRight()+clearance+1-(box.GetLeft()-before[0])))
                ys.update((obstacle.GetTop()-clearance-1-(box.GetBottom()-before[1]),
                           obstacle.GetBottom()+clearance+1-(box.GetTop()-before[1])))
            xs=sorted(xs,key=lambda x:(abs(x-origin.x),x))[:12]
            ys=sorted(ys,key=lambda y:(abs(y-origin.y),y))[:12]
            for x,y in sorted(((x,y) for x in xs for y in ys),
                              key=lambda xy:((xy[0]-origin.x)**2+(xy[1]-origin.y)**2,xy)):
                if near(x,y):yield x,y
        for ring in range(1,int(radius/step)+1):
            offsets = [(x,y) for x in range(-ring,ring+1)
                       for y in (-ring,ring)]
            offsets += [(x,y) for x in (-ring,ring)
                        for y in range(-ring+1,ring)]
            offsets.sort(key=lambda xy:(xy[0]*xy[0]+xy[1]*xy[1],xy[1],xy[0]))
            for x,y in offsets:
                if x*x+y*y <= (radius/step)**2:
                    yield origin.x+x*step,origin.y+y*step

    def positions(origin,before,fp,templates,layer,local,index,limit,projection_tier=None):
        # Search the closest courtyard slots, including the original, in one
        # order. A legal but distant original must not bypass nearby options.
        points = []
        seen = set()
        for point in raw_positions(origin,before,fp,templates,layer,local,index):
            if point not in seen:
                seen.add(point)
                if fp and projection_tier is not None:
                    body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
                    _,template=templates[0]
                    left,top=template.GetLeft()+point[0]-before[0],template.GetTop()+point[1]-before[1]
                    tier,_=edge_alignment((left,top,left+template.GetWidth(),top+template.GetHeight()),
                        (body.GetLeft(),body.GetTop(),body.GetRight(),body.GetBottom()),api.FromMM(options['edge_margin']))
                    if tier!=projection_tier:continue
                if fp and not local:
                    body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
                    _,template=templates[0]
                    left,top=template.GetLeft()+point[0]-before[0],template.GetTop()+point[1]-before[1]
                    distance=math.hypot(max(body.GetLeft()-left-template.GetWidth(),left-body.GetRight(),0),
                                        max(body.GetTop()-top-template.GetHeight(),top-body.GetBottom(),0))
                    # Count only this phase's candidates. Otherwise a distant
                    # search can exhaust its cap repeating the local slots.
                    if distance<=api.FromMM(options['normal_distance']):continue
                points.append(point)
            if len(points)>=limit:break
        if fp:
            body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
            state,template=templates[0]
            def rank(point):
                x,y=point
                left,top=template.GetLeft()+x-before[0],template.GetTop()+y-before[1]
                right,bottom=left+template.GetWidth(),top+template.GetHeight()
                distance=math.hypot(max(body.GetLeft()-right,left-body.GetRight(),0),
                                    max(body.GetTop()-bottom,top-body.GetBottom(),0))
                projection,offset=edge_alignment((left,top,right,bottom),
                    (body.GetLeft(),body.GetTop(),body.GetRight(),body.GetBottom()),api.FromMM(options['edge_margin']))
                gap=round(distance/api.FromMM(.01))
                return ((*((projection,gap) if local else (gap,projection)),offset,
                         ((left+right)//2-origin.x)**2+((top+bottom)//2-origin.y)**2,distance,y,x))
            points.sort(key=rank)
        else:points.sort(key=lambda p:((p[0]-origin.x)**2+(p[1]-origin.y)**2,p))
        yield from points

    def ambiguous_owner(box,fp,layer,index):
        """A label beside a different component needs an association guide."""
        own='body:'+item_id(fp)
        body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
        distance=box_distance(box,body)
        margin=api.FromMM(.2)
        return distance>api.FromMM(options['normal_distance']) or any(
            oid.startswith('body:') and oid!=own and box_distance(box,other)+margin<distance
            for other,oid in index.query(_inflate(box,math.ceil(distance+margin),api)))

    text_keys = {item_id(text) for text,_,_ in texts}

    def check_association(box,origin,fp,key,index,layer,printed):
        """Return a straight visible association; never route around a part.

        A virtual connector is required even when no leader is printed. Its
        corridor remains reserved against later text and association crossings.
        Physical leaders additionally pass the manufacturing-clearance gate.
        """
        raw_body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
        own='body:'+item_id(fp)
        label_box=_inflate(box,clearance+guide_stroke//2+1 if printed else 1,api)
        body=_inflate(raw_body,body_clearance+guide_stroke//2+1 if printed else 1,api)
        region=_inflate(raw_body,api.FromMM(options['max_radius']),api)
        nearby=[_inflate(obstacle,(body_clearance if oid.startswith('body:') else clearance)+guide_stroke//2,api)
                for obstacle,oid in index.query(region)
                if oid not in (key,own,'guide:'+key) and not oid.startswith('sight:')]
        def exits(rect,other):
            x=min(max(other.GetCenter().x,rect.GetLeft()),rect.GetRight())
            y=min(max(other.GetCenter().y,rect.GetTop()),rect.GetBottom())
            points=[(rect.GetLeft(),y),(rect.GetRight(),y),
                (x,rect.GetTop()),(x,rect.GetBottom()),
                (rect.GetLeft(),rect.GetTop()),(rect.GetRight(),rect.GetTop()),
                (rect.GetLeft(),rect.GetBottom()),(rect.GetRight(),rect.GetBottom())]
            # Free face intervals expose direct corridors between tightly
            # packed parts that a midpoint/corner-only search would miss.
            for vertical,fixed,low,high in (
                    (True,rect.GetLeft(),rect.GetTop(),rect.GetBottom()),
                    (True,rect.GetRight(),rect.GetTop(),rect.GetBottom()),
                    (False,rect.GetTop(),rect.GetLeft(),rect.GetRight()),
                    (False,rect.GetBottom(),rect.GetLeft(),rect.GetRight())):
                marks={low,high}
                for obstacle in nearby:
                    if (obstacle.GetLeft()<=fixed<=obstacle.GetRight() if vertical
                            else obstacle.GetTop()<=fixed<=obstacle.GetBottom()):
                        first,last=(obstacle.GetTop(),obstacle.GetBottom()) if vertical else (obstacle.GetLeft(),obstacle.GetRight())
                        marks.update((max(low,min(high,first-1)),max(low,min(high,last+1))))
                marks=sorted(marks)
                for first,last in zip(marks,marks[1:]):
                    coordinate=(first+last)//2
                    points.append((fixed,coordinate) if vertical else (coordinate,fixed))
            return list(dict.fromkeys(points))
        targets=exits(body,label_box)
        if printed and clearance>body_clearance:
            targets.extend(exits(_inflate(raw_body,clearance+guide_stroke//2+1,api),label_box))
        pairs=sorted(((a,b) for a in exits(label_box,body) for b in targets),
                     key=lambda pair:(math.dist(*pair),pair))
        for first,second in pairs:
            if time.monotonic()>label_deadline[0]:return None
            p,q=api.VECTOR2I(*first),api.VECTOR2I(*second)
            # Both endpoints must face each other: no chord through the label
            # or the owner's courtyard is a valid line of sight.
            if segment_hits_box(p,q,box) or segment_hits_box(p,q,raw_body):continue
            blocked=False
            sight=(*first,*second,0,layer)
            for obstacle,oid in index.query(_line_box(sight,api,1)):
                if oid in (key,own,'guide:'+key):continue
                if not (oid.startswith(('body:','guide:','legacy-guide:','leader:','sight:')) or oid in text_keys):continue
                other=index.segments.get(id(obstacle))
                if (segment_segment_distance(first,second,other[:2],other[2:4])<=other[4]/2
                    if other is not None else segment_hits_box(p,q,obstacle)):
                    blocked=True;break
            if blocked or not inside(p,q,1):continue
            if printed:
                segment=(*first,*second,guide_stroke,layer)
                if segment_hits_box(p,q,_inflate(box,clearance+guide_stroke//2,api)):continue
                if not inside(p,q,clearance+guide_stroke//2):continue
                if index.hits_segment(segment,clearance,body_clearance,api,ignore=(key,'guide:'+key)):continue
            return (first,second)
        return None

    acceptable=set()
    if options['preserve_acceptable'] or options['problem_only']:
        existing={layer:_SpatialIndex(api.FromMM(4)) for layer in obstacles}
        for layer,rows in obstacles.items():
            for box,key in rows:existing[layer].add(box,key,obstacle_segments.get(id(box)))
        for text,_,_ in texts:
            if text.IsVisible() and text.GetLayer() in existing:
                existing[text.GetLayer()].add(_box(text,_state(text),api),item_id(text))
        for text,fp,key,_,before,templates,_ in eligible:
            action=annotation_actions.get(key)
            if action and (action.create or action.remove or action.text_before!=action.net):continue
            if not any(state[2:10]==before[2:10] for state,_ in templates):continue
            layer=text.GetLayer();box=_box(render_items.get(key,text),before,api)
            if existing[layer].hits_box(box,clearance,body_clearance,api,ignore=(key,'guide:'+key)):continue
            expanded=_inflate(box,clearance,api)
            corners=[api.VECTOR2I(x,y) for x,y in ((expanded.GetLeft(),expanded.GetTop()),
                (expanded.GetRight(),expanded.GetTop()),(expanded.GetRight(),expanded.GetBottom()),
                (expanded.GetLeft(),expanded.GetBottom()))]
            if any(not inside(corners[i],corners[(i+1)%4],1) for i in range(4)):continue
            if any(expanded.GetLeft()<=x<=expanded.GetRight() and expanded.GetTop()<=y<=expanded.GetBottom()
                   for _,holes in native_polygons for hole in holes for x,y in hole):continue
            if fp:
                body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
                if box_distance(box,body)>api.FromMM(options['normal_distance']):continue
                if edge_alignment((box.GetLeft(),box.GetTop(),box.GetRight(),box.GetBottom()),
                    (body.GetLeft(),body.GetTop(),body.GetRight(),body.GetBottom()),api.FromMM(options['edge_margin']))[0]:continue
                if ambiguous_owner(box,fp,layer,existing[layer]):continue
                sight=check_association(box,fp.GetPosition(),fp,key,existing[layer],layer,False)
                if not sight:continue
                segment=(*sight[0],*sight[1],0,layer)
                existing[layer].add(_line_box(segment,api),'sight:'+key,segment)
            acceptable.add(key)

    def assign(active, fixed=(), repair=False, priority=None, seeds=None, target_only=False):
        replaced = {item_id(text) for key in active if key in annotation_actions
                    for text in annotation_actions[key].originals}
        fixed_keys = {item_id(change.item) for change in fixed}
        fixed_replaced = {item_id(text) for key in fixed_keys if key in annotation_actions
                          for text in annotation_actions[key].originals}
        removed_guide_owners = fixed_keys | fixed_replaced
        if not repair:removed_guide_owners |= active | replaced
        indices = {layer:_SpatialIndex(api.FromMM(4)) for layer in obstacles}
        for layer,rows in obstacles.items():
            for box,key in rows:
                if key.startswith('guide:') and key[6:] in removed_guide_owners:
                    continue
                indices[layer].add(box,key,obstacle_segments.get(id(box)))
        for text,_,_ in texts:
            layer,key = text.GetLayer(),item_id(text)
            if layer in indices and text.IsVisible() and key not in fixed_keys and key not in fixed_replaced and (repair or key not in active and key not in replaced):
                indices[layer].add(_box(text,_state(text),api),key)
        for change in fixed:
            layer,key=change.item.GetLayer(),item_id(change.item)
            indices[layer].add(change.box,key)
            if change.sightline:
                segment=(*change.sightline[0],*change.sightline[1],0,layer)
                indices[layer].add(_line_box(segment,api),'sight:'+key,segment)
            for segment in _leader_segments(change):
                indices[layer].add(_line_box(segment,api),'leader:'+key,segment)
        assignments,rejected = [],set()
        leader_count=sum(bool(change.leader) for change in fixed)
        # A selection must not receive a fresh allowance on every invocation.
        # Count manifest-verified guide owners retained outside this trial.
        replaced_owners=active | replaced | fixed_keys | fixed_replaced
        leader_count+=sum(bool(rows) for owner,rows in guides.items() if owner not in replaced_owners)
        completed = 0
        ordered=sorted(eligible,key=lambda row:row[2] not in acceptable) if priority is None else sorted(eligible,key=lambda row:row[2]!=priority)
        if target_only:ordered=[row for row in ordered if row[2]==priority]
        for text,fp,key,label,before,templates,_ in ordered:
            if key not in active:
                continue
            if progress is not None and progress(completed,len(active),('Rearrange neighbours: ' if priority is not None else 'Retry unresolved: ' if repair else '')+label) is False:
                raise ValueError('Placement cancelled; board unchanged.')
            completed += 1
            layer = text.GetLayer()
            origin = fp.GetPosition() if fp else text.GetPosition()
            chosen,attempts = None,0
            owner_ids = {key}
            if key in annotation_actions:owner_ids.update(item_id(t) for t in annotation_actions[key].originals)
            if repair:
                for owner_id in owner_ids:
                    indices[layer].discard(owner_id)
                    indices[layer].discard('guide:'+owner_id)
            # Share the plan budget across difficult labels and replans.
            # An impossible long name must not starve the rest of a dense board.
            label_started=time.monotonic()
            label_deadline[0] = label_started + (1.5 if repair or len(active)<=20 else .1)
            local_deadline=label_started+.6*max(0,label_deadline[0]-label_started)
            angle_groups = []
            for angle in dict.fromkeys(state[2] for state,_ in templates):
                angle_groups.append([t for t in templates if t[0][2]==angle])
            def candidates():
                seed=seeds.get(key) if seeds else None
                if seed is not None:
                    for state,envelope in templates:
                        if state[2:10]==seed.after[2:10]:
                            yield seed.after[0],seed.after[1],state,envelope
                            break
                if key in acceptable and (not seeds or key not in seeds):
                    yield before[0],before[1],before,_box(render_items.get(key,text),before,api)
                body=bodies.get((item_id(fp),layer),bodies[item_id(fp)]) if fp else None
                def stream(template,local,limit,projection_tier):
                    state,envelope=template
                    for x,y in positions(origin,before,fp,[template],layer,local,indices[layer],limit,projection_tier):
                        left,top=envelope.GetLeft()+x-before[0],envelope.GetTop()+y-before[1]
                        right,bottom=left+envelope.GetWidth(),top+envelope.GetHeight()
                        distance=(math.hypot(max(body.GetLeft()-right,left-body.GetRight(),0),
                                             max(body.GetTop()-bottom,top-body.GetBottom(),0))
                                  if body else math.hypot(x-origin.x,y-origin.y))
                        if local and distance>api.FromMM(options['normal_distance']):continue
                        if not local and distance<=api.FromMM(options['normal_distance']):continue
                        # Proximity takes precedence over type size. Equal-gap
                        # positions prefer the larger readable text and avoid
                        # unnecessary rotations or movement along the edge.
                        projection,offset=(edge_alignment((left,top,right,bottom),
                            (body.GetLeft(),body.GetTop(),body.GetRight(),body.GetBottom()),api.FromMM(options['edge_margin']))
                            if body else (0,0))
                        gap=round(distance/api.FromMM(.01))
                        rank=(*((projection,gap) if local else (gap,projection)),-state[4],-state[3],offset,
                              ((left+right)//2-origin.x)**2+((top+bottom)//2-origin.y)**2,distance,y,x)
                        yield rank,(x,y,state,envelope)
                for local in (True,False):
                    # Remote component references require an explicitly enabled
                    # leader; do not spend far-search quota on forbidden states.
                    if not local and fp is not None and not options['leaders']:break
                    phase_deadline=local_deadline if local else label_deadline[0]
                    # Reserve far-search checks as well as time: many local
                    # sizes/angles must not exhaust the owner's entire quota.
                    phase_attempts=0
                    phase_limit=7200 if local else 4800
                    groups=angle_groups if local else [[t for group in angle_groups for t in group]]
                    for projection_tier in ((0,1) if local and fp else (None,)):
                        for group in groups:
                            if phase_attempts>=phase_limit:
                                limited_keys.add(key);break
                            if time.monotonic()>phase_deadline:break
                            streams=[stream(template,local,max(64,(768 if local else 4096)//len(group)),projection_tier)
                                     for template in group]
                            for _,candidate in heapq.merge(*streams,key=lambda row:row[0]):
                                if phase_attempts>=phase_limit:
                                    limited_keys.add(key);break
                                if time.monotonic()>phase_deadline:break
                                phase_attempts+=1
                                yield candidate
            for x,y,state,template in candidates():
                attempts += 1;checks[0] += 1
                if attempts>12000 or time.monotonic()>label_deadline[0]:
                    break
                after = (x,y)+state[2:]
                if seeds and key in seeds and key!=priority and math.dist(after[:2],seeds[key].after[:2])>api.FromMM(options['repack_displacement']):continue
                box = api.BOX2I(api.VECTOR2I(template.GetLeft()+x-before[0],template.GetTop()+y-before[1]),
                                api.VECTOR2I(template.GetWidth(),template.GetHeight()))
                expanded = _inflate(box,clearance,api)
                if indices[layer].hits_box(box,clearance,body_clearance,api):
                    continue
                corners = [api.VECTOR2I(a,b) for a,b in ((expanded.GetLeft(),expanded.GetTop()),(expanded.GetRight(),expanded.GetTop()),(expanded.GetRight(),expanded.GetBottom()),(expanded.GetLeft(),expanded.GetBottom()))]
                if any(not inside(corners[i],corners[(i+1)%4],1) for i in range(4)):
                    continue
                if any(expanded.GetLeft() <= x <= expanded.GetRight() and
                       expanded.GetTop() <= y <= expanded.GetBottom()
                       for _,holes in native_polygons for hole in holes for x,y in hole):
                    continue
                path,leader = (),None
                needs_guide = fp and ambiguous_owner(box,fp,layer,indices[layer])
                if needs_guide and not options['leaders']:
                    continue
                sightline=()
                if fp:
                    printed=bool(options['leaders'] and (needs_guide or box_distance(
                        box,bodies.get((item_id(fp),layer),bodies[item_id(fp)]))>api.FromMM(options['leader_distance'])))
                    sightline=check_association(box,origin,fp,key,indices[layer],layer,printed)
                    if not sightline:continue
                    if printed:
                        if leader_count>=options['leader_limit']:
                            leader_budget_keys.add(key);continue
                        if math.dist(*sightline)>api.FromMM(options['leader_max_length']):
                            leader_length_keys.add(key);continue
                        path=sightline
                        leader=(*path[0],*path[1],guide_stroke,layer)
                previous = []
                owner_ids = {key}
                if key in annotation_actions:owner_ids.update(item_id(t) for t in annotation_actions[key].originals)
                for owner_id in sorted(owner_ids):previous.extend(guides.get(owner_id,[]))
                chosen = Change(text,before,after,label,box,leader,previous,path,
                                preview_item=render_items.get(key),annotation=annotation_actions.get(key),sightline=sightline,footprint=fp)
                break
            attempts_by_key[key]=attempts_by_key.get(key,0)+attempts
            if chosen is None:
                if time.monotonic()>label_deadline[0] or attempts>12000:limited_keys.add(key)
                rejected.add(key)
                if repair:
                    originals=annotation_actions[key].originals if key in annotation_actions else (text,)
                    for original in originals:
                        if original.IsVisible():indices[layer].add(_box(original,_state(original),api),item_id(original))
                        for _,shapes in guides.get(item_id(original),[]):
                            for shape in shapes:indices[layer].add(shape.GetBoundingBox(),'guide:'+item_id(original),_line_state(shape))
                continue
            assignments.append(chosen)
            if target_only:return assignments,set()
            leader_count+=bool(chosen.leader)
            indices[layer].add(chosen.box,key)
            if chosen.sightline:
                segment=(*chosen.sightline[0],*chosen.sightline[1],0,layer)
                indices[layer].add(_line_box(segment,api),'sight:'+key,segment)
            for segment in _leader_segments(chosen):
                indices[layer].add(_line_box(segment,api),'leader:'+key,segment)
        return assignments,rejected

    # Movable originals are not obstacles to one another. Restore unresolved
    # originals below and demote every dependent placement to close conflicts.
    # Do not replan the entire active set against a nearly expired deadline:
    # that discarded successful placements simply because time had run out.
    active,preserved = set(all_keys),set()
    assignments,rejected = assign(active)
    preserved.update(rejected)
    preserved_indices = {layer:_SpatialIndex(api.FromMM(4)) for layer in obstacles}
    text_by_key = {item_id(text):text for text,_,_ in texts}
    def preserve(key):
        originals = annotation_actions[key].originals if key in annotation_actions else (text_by_key[key],)
        for text in originals:
            owner_id = item_id(text)
            if text.IsVisible() and text.GetLayer() in preserved_indices:
                preserved_indices[text.GetLayer()].add(_box(text,_state(text),api),owner_id)
            for _,shapes in guides.get(owner_id,[]):
                for shape in shapes:
                    preserved_indices[shape.GetLayer()].add(shape.GetBoundingBox(),'guide:'+owner_id,_line_state(shape))
    for key in preserved:
        preserve(key)
    # Restoring failures may expose a chain of preserved originals. Demotion to
    # the unchanged state closes that chain without ever applying an overlap.
    changed = True
    while changed:
        changed = False
        for change in list(assignments):
            layer,key = change.item.GetLayer(),item_id(change.item)
            expanded = _inflate(change.box,clearance,api)
            conflict = preserved_indices[layer].hits_box(change.box,clearance,body_clearance,api)
            for segment in _leader_segments(change):
                p,q = api.VECTOR2I(*segment[:2]),api.VECTOR2I(*segment[2:4])
                conflict = conflict or preserved_indices[layer].hits_segment(segment,clearance,body_clearance,api)
            if change.sightline:
                segment=(*change.sightline[0],*change.sightline[1],0,layer)
                conflict=conflict or preserved_indices[layer].hits_segment(segment,0,0,api)
            if conflict:
                assignments.remove(change);preserved.add(key);preserve(key);changed = True
    # Retry every failure, including placements demoted by retained originals.
    # Accepted geometry is fixed; other unresolved originals remain obstacles.
    # Removing one owner at a time makes each successful repair safe immediately,
    # without a second cascade or asking the user to select smaller groups.
    retry_keys=set(preserved)
    repair_attempts=len(preserved)
    repaired,remaining=assign(set(preserved),fixed=assignments,repair=True) if preserved else ([],set())
    assignments.extend(repaired)
    preserved=remaining
    # A greedy neighbour may occupy a useful slot or its guide corridor. Use
    # an original-layout proposal to identify actual blockers, including remote
    # labels along a direct association. Keep a trial only if ALL cluster members
    # fit; failed trials never replace previously accepted geometry.
    cluster_attempts=cluster_resolved=0
    rows_by_key={row[2]:row for row in eligible}
    def blocks(proposal,accepted):
        if proposal.item.GetLayer()!=accepted.item.GetLayer():return False
        index=_SpatialIndex(api.FromMM(4))
        index.add(accepted.box,item_id(accepted.item))
        if accepted.sightline:
            segment=(*accepted.sightline[0],*accepted.sightline[1],0,accepted.item.GetLayer())
            index.add(_line_box(segment,api),'sight:'+item_id(accepted.item),segment)
        for segment in _leader_segments(accepted):index.add(_line_box(segment,api),'leader',segment)
        return index.hits_box(proposal.box,clearance,body_clearance,api) or any(
            index.hits_segment(segment,clearance,body_clearance,api) for segment in _leader_segments(proposal)) or bool(
            proposal.sightline and index.hits_segment((*proposal.sightline[0],*proposal.sightline[1],0,
                                                     proposal.item.GetLayer()),0,0,api))
    for key in sorted(tuple(preserved),key=lambda key:(label_by_key[key],key)):
        text,fp=rows_by_key[key][:2]
        if fp is None:continue
        proposal,failed=assign({key},repair=True)
        seed=proposal[0] if proposal else None
        if seed is not None:
            neighbours=[change for change in assignments if blocks(seed,change)]
        else:
            layer=text.GetLayer()
            body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
            region=_inflate(body,api.FromMM(options['normal_distance']),api)
            def nearby_owner(change):
                owner=rows_by_key[item_id(change.item)][1]
                return owner is not None and bodies.get((item_id(owner),layer),bodies[item_id(owner)]).Intersects(region)
            neighbours=[change for change in assignments if change.item.GetLayer()==layer and
                        (change.box.Intersects(region) or nearby_owner(change) or
                         any(_line_box(segment,api).Intersects(region) for segment in _leader_segments(change)))]
            neighbours.sort(key=lambda change:(box_distance(change.box,body),change.label,item_id(change.item)))
            neighbours=neighbours[:options['repack_neighbours']]
        if options['problem_only']:neighbours=[change for change in neighbours if item_id(change.item) not in acceptable]
        if len(neighbours)>options['repack_neighbours'] or options['repack_neighbours']==0:continue
        if seed is None and neighbours:
            # Probe with only the bounded local owners released. Repack the
            # actual blockers of that slot, not every nearby accepted label.
            released={item_id(change.item) for change in neighbours}
            probe,_=assign({key,*released},fixed=[change for change in assignments
                if item_id(change.item) not in released],priority=key,target_only=True)
            if probe:
                seed=probe[0]
                neighbours=[change for change in neighbours if blocks(seed,change)]
        cluster={key,*[item_id(change.item) for change in neighbours]}
        if seed is None and len(cluster)==1:continue
        cluster_attempts+=1
        retry_keys.update(cluster)
        fixed=[change for change in assignments if item_id(change.item) not in cluster]
        seeds={item_id(change.item):change for change in neighbours}
        if seed is not None:seeds[key]=seed
        trial,failed=assign(cluster,fixed=fixed,priority=key,seeds=seeds)
        if not failed:
            assignments=fixed+trial
            preserved.remove(key)
            cluster_resolved+=1
    for key in sorted(preserved,key=lambda key:(label_by_key[key],key)):
        text=text_by_key.get(key)
        reason=('Search time/candidate limit reached after automatic retry.' if key in limited_keys else
                'No unambiguous safe text/guide position found after automatic retry.')
        if key in leader_budget_keys:reason+=' Some checked guide candidates exceeded the board-wide guide count; review the guide allowance in Options.'
        if key in leader_length_keys:reason+=' Some checked guide candidates exceeded the maximum guide length.'
        if text is not None:
            original=_box(text,_state(text),api)
            corners=[api.VECTOR2I(x,y) for x,y in ((original.GetLeft(),original.GetTop()),
                     (original.GetRight(),original.GetTop()),(original.GetRight(),original.GetBottom()),
                     (original.GetLeft(),original.GetBottom()))]
            if any(not inside(corners[i],corners[(i+1)%4],1) for i in range(4)):
                reason+=' Original crosses the board edge or a cutout.'
            elif any(original.Intersects(box) for box,oid in obstacles[text.GetLayer()]
                     if oid.startswith('body:')):
                reason+=' Original overlaps a component courtyard/body.'
        result.rejected.append((label_by_key[key],reason+' Original retained, not approved.'))
    result.unresolved_ids = set(preserved)
    for key in preserved:
        if key in annotation_actions:
            result.unresolved_ids.update(item_id(text) for text in annotation_actions[key].originals)
    for chosen in assignments:
        old_shapes = [shape for _,shapes in chosen.previous_guides for shape in shapes]
        matches = sorted(_line_state(shape) for shape in old_shapes) == sorted(_leader_segments(chosen))
        annotation = chosen.annotation
        presentation_changed = annotation and (annotation.create or annotation.remove
            or annotation.text_before != annotation.net or annotation.reference_visible_before)
        if chosen.after != chosen.before or not matches or presentation_changed:
            result.changes.append(chosen)
    changed_keys={item_id(change.item) for change in result.changes}
    accepted_keys={item_id(change.item) for change in assignments}
    proximity={};distances={}
    accepted_by_key={item_id(change.item):change for change in assignments}
    footprint_refs={item_id(fp):fp.GetReference() for fp in board.GetFootprints()}
    association_indices={layer:_SpatialIndex(api.FromMM(4)) for layer in obstacles}
    for layer in obstacles:
        for box,oid in obstacles[layer]:
            if oid.startswith('body:'):association_indices[layer].add(box,oid)
    def association_review(box,fp,layer):
        """Explain distance/nearest-owner exceptions using conservative 2D envelopes."""
        own='body:'+item_id(fp)
        body=bodies.get((item_id(fp),layer),bodies[item_id(fp)])
        distance=box_distance(box,body);margin=api.FromMM(.2)
        neighbours=[(box_distance(box,other),footprint_refs.get(oid[5:],'unknown'))
                    for other,oid in association_indices[layer].query(_inflate(box,math.ceil(distance+margin),api))
                    if oid!=own and box_distance(box,other)+margin<distance]
        warnings=[]
        if distance>api.FromMM(options['normal_distance']):
            warnings.append('Outside the normal courtyard-distance target; review this exceptional placement.')
        if neighbours:
            nearest=min(neighbours)
            warnings.append('Potential association ambiguity: '+nearest[1]+' is nearer by the conservative 2D envelope metric.')
        return ' '.join(warnings)
    for text,fp,key,_,before,_,_ in eligible:
        if fp is None:continue
        court=fp.GetCourtyard(api.F_CrtYd if text.GetLayer()==api.F_SilkS else api.B_CrtYd)
        hull=fp.GetBoundingHull() if text.GetLayer()==(api.B_SilkS if fp.GetLayer()==api.B_Cu else api.F_SilkS) else api.SHAPE_POLY_SET()
        action=annotation_actions.get(key)
        original=action.reference if action and action.create else action.text if action and action.remove else text
        before_shape=text_geometry(original,_state(original),api)[1]
        change=accepted_by_key.get(key)
        after_shape=text_geometry(render_items.get(key,text),change.after,api)[1] if change else api.SHAPE_POLY_SET()
        distances[key]=dict(before_courtyard_gap_mm=native_shape_gap(before_shape,court,api),
            courtyard_gap_mm=native_shape_gap(after_shape,court,api),
            before_body_hull_gap_mm=native_shape_gap(before_shape,hull,api),
            body_hull_gap_mm=native_shape_gap(after_shape,hull,api),
            before_association_warning=association_review(_box(original,_state(original),api),fp,text.GetLayer()),
            association_warning=association_review(change.box,fp,text.GetLayer()) if change else
                'Unresolved original retained; component association is not approved.',
            body_distance_source='Native 2D footprint hull proxy; not a verified physical package model')
    for change in assignments:
        key=item_id(change.item)
        fp=rows_by_key[key][1]
        if fp is not None:
            body=bodies.get((item_id(fp),change.item.GetLayer()),bodies[item_id(fp)])
            proximity[key]=api.ToMM(box_distance(change.box,body))
    associations={item_id(change.item):[[api.ToMM(x),api.ToMM(y)] for x,y in change.sightline]
                  for change in assignments}
    result.outcomes=[dict(id=key,label=label_by_key[key],
                         status='CHANGED' if key in changed_keys else 'UNCHANGED' if key in accepted_keys else 'UNRESOLVED',
                         candidate_checks=attempts_by_key.get(key,0),retried=key in retry_keys,
                         guide_budget_limited=key in preserved and key in leader_budget_keys,
                         guide_length_limited=key in preserved and key in leader_length_keys,
                         envelope_gap_mm=proximity.get(key),sightline_mm=associations.get(key),
                         preserved_acceptable=key in acceptable and key not in changed_keys,**distances.get(key,{}))
                     for key in sorted(all_keys,key=lambda key:(label_by_key[key],key))]
    result.stats = dict(eligible=len(eligible),placed=len(assignments),changed=len(result.changes),
                        unresolved=len(preserved),repair_attempts=repair_attempts,repaired=len(repaired),
                        guides=sum(bool(change.leader_path) for change in assignments)+sum(bool(rows)
                            for owner,rows in guides.items() if owner not in all_keys and
                            owner not in {item_id(text) for action in annotation_actions.values() for text in action.originals}),
                        guide_budget_limited=len(preserved & leader_budget_keys),
                        guide_length_limited=len(preserved & leader_length_keys),
                        reviewed=len(all_keys),cluster_attempts=cluster_attempts,cluster_resolved=cluster_resolved,
                        candidate_checks=checks[0],
                        elapsed_seconds=round(time.monotonic()-started,3),
                        search_limit_reached=bool(preserved & limited_keys))
    if progress is not None and progress(len(eligible),len(eligible),'Placement complete') is False:
        raise ValueError('Placement cancelled; board unchanged.')
    if fingerprint(board,api) != result.source_fingerprint:
        raise ValueError('Board changed during planning; preview again.')
    return result


class Transaction:
    """Explicit reversible native edits; stale checks protect undo and redo."""
    def __init__(self, board, api, preview):
        self.board, self.api, self.preview = board, api, preview
        self.leaders = []
        self.groups = []
        self.applied = False
        self.expected = preview.source_fingerprint
        from .lifecycle import _properties
        self.properties_before=_properties(board)
        self.layout_before=self._layout_fingerprint()

    def _layout_fingerprint(self,leaders=()):
        ignored=list(leaders)
        for change in self.preview.changes:
            ignored.append(change.item)
            if change.annotation:ignored.append(change.annotation.text)
            ignored.extend(shape for _,shapes in change.previous_guides for shape in shapes)
        fields=[(item_id(fp),[(item_id(field),field.GetName(),field.GetText()) for field in fp.GetFields()])
                for fp in self.board.GetFootprints()]
        return board_fingerprint(self.board,ignored),fields

    def _check(self):
        if fingerprint(self.board,self.api) != self.expected:
            raise ValueError('Board changed; preview again before applying or undoing.')

    def _rollback(self, journal, original):
        errors = []
        for inverse in reversed(journal):
            try:
                inverse()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            failure = RuntimeError('Placement recovery needs attention: ' + '; '.join(errors))
            failure.transaction = self
            raise failure from original

    def _owned_presence(self, item, present, journal):
        """Journal before writes, including a native call which raises after mutation."""
        def exists():
            items = self.board.Groups() if isinstance(item,self.api.PCB_GROUP) else self.board.GetDrawings()
            return any(item_id(value)==item_id(item) for value in items)
        def ensure(wanted):
            if exists() != wanted:
                (self.board.Add if wanted else self.board.Remove)(item)
        before = exists()
        journal.append(lambda:ensure(before))
        ensure(present)

    @staticmethod
    def _owned_membership(group, text, present, journal):
        def exists():return any(item_id(value)==item_id(text) for value in group.GetItems())
        def ensure(wanted):
            if exists() != wanted:(group.AddItem if wanted else group.RemoveItem)(text)
        before = exists()
        journal.append(lambda:ensure(before))
        ensure(present)

    @staticmethod
    def _presentation_set(item, getter, setter, value, journal):
        before = getattr(item,getter)()
        journal.append(lambda:getattr(item,setter)(before))
        getattr(item,setter)(value)
        if getattr(item,getter)() != value:
            raise ValueError('KiCad did not retain the reviewed annotation presentation.')

    def _annotation_redo(self, action, journal):
        if action.remove:
            self._owned_membership(action.group,action.text,False,journal)
            self._owned_presence(action.text,False,journal)
            self._owned_presence(action.group,False,journal)
            self._presentation_set(action.reference,'IsVisible','SetVisible',action.original_visibility,journal)
        else:
            self._presentation_set(action.text,'GetText','SetText',action.net,journal)
            self._presentation_set(action.reference,'IsVisible','SetVisible',False,journal)
            if action.create:
                self._owned_presence(action.text,True,journal)
                self._owned_membership(action.group,action.text,True,journal)
                self._owned_presence(action.group,True,journal)

    def _annotation_undo(self, action, journal):
        if action.remove:
            self._owned_presence(action.group,True,journal)
            self._owned_presence(action.text,True,journal)
            self._owned_membership(action.group,action.text,True,journal)
        elif action.create:
            self._owned_membership(action.group,action.text,False,journal)
            self._owned_presence(action.group,False,journal)
            self._owned_presence(action.text,False,journal)
        self._presentation_set(action.reference,'IsVisible','SetVisible',action.reference_visible_before,journal)
        self._presentation_set(action.text,'GetText','SetText',action.text_before,journal)

    def redo(self):
        if self.applied:
            raise ValueError('This placement is already applied.')
        self._check()
        journal, leaders, groups, entries = [], [], [], []
        retained = iter(self.leaders)
        retained_groups = iter(self.groups)
        try:
            for change in self.preview.changes:
                generated_group=None
                for group, shapes in change.previous_guides:
                    for shape in shapes:
                        self._owned_membership(group,shape,False,journal)
                        self._owned_presence(shape,False,journal)
                    self._owned_presence(group,False,journal)
                if change.annotation:self._annotation_redo(change.annotation,journal)
                # Text setters can fail after one of the individual attributes.
                journal.append(lambda c=change:_set(c.item,c.before,self.api))
                _set(change.item,change.after,self.api)
                glyphs = self.api.SHAPE_POLY_SET()
                change.item.TransformTextToPolySet(glyphs,0,self.api.FromMM(.001),self.api.ERROR_OUTSIDE)
                actual = glyphs.BBox() if glyphs.OutlineCount() else change.item.GetBoundingBox()
                if not change.box.Contains(actual):
                    raise ValueError('Applied text exceeds its reviewed envelope; placement was rolled back.')
                if change.leader:
                    group = next(retained_groups,None)
                    if group is None:
                        group = self.api.PCB_GROUP(self.board)
                        group.SetName(GUIDE_PREFIX+item_id(change.item))
                    for x,y,a,b,w,layer in _leader_segments(change):
                        shape = next(retained,None)
                        if shape is None:
                            shape = self.api.PCB_SHAPE(self.board)
                            shape.SetShape(self.api.SHAPE_T_SEGMENT)
                            shape.SetStart(self.api.VECTOR2I(x,y)); shape.SetEnd(self.api.VECTOR2I(a,b))
                            shape.SetWidth(w); shape.SetLayer(layer)
                        self._owned_presence(shape,True,journal)
                        self._owned_membership(group,shape,True,journal)
                        leaders.append(shape)
                    self._owned_presence(group,True,journal)
                    groups.append(group)
                    generated_group=group
                if change.footprint is not None:
                    entries.append((change.footprint,change.item,generated_group))
            if self._layout_fingerprint(leaders)!=self.layout_before:
                raise ValueError('Underlying components, metadata or board geometry changed; placement rolled back.')
            if entries:
                from .lifecycle import _properties, _native_properties, generation_properties
                before=_properties(self.board)
                after=generation_properties(self.board,self.api,entries,self.preview.settings,
                    removed_text_ids=[item_id(change.annotation.text) for change in self.preview.changes
                                      if change.annotation and change.annotation.remove])
                journal.append(lambda:self.board.SetProperties(_native_properties(self.api,before)))
                self.board.SetProperties(after)
        except Exception as exc:
            self._rollback(journal,exc)
            raise
        self.leaders, self.groups = leaders, groups
        self.applied = True
        self.expected = fingerprint(self.board,self.api)
        return self

    def undo(self):
        if not self.applied:
            raise ValueError('This placement is not applied.')
        self._check()
        journal = []
        try:
            for group in self.groups:
                for shape in list(group.GetItems()):
                    self._owned_membership(group,shape,False,journal)
                self._owned_presence(group,False,journal)
            for shape in self.leaders:
                self._owned_presence(shape,False,journal)
            for change in self.preview.changes:
                journal.append(lambda c=change:_set(c.item,c.after,self.api))
                _set(change.item,change.before,self.api)
                if change.annotation:self._annotation_undo(change.annotation,journal)
                for group,shapes in change.previous_guides:
                    self._owned_presence(group,True,journal)
                    for shape in shapes:
                        self._owned_presence(shape,True,journal)
                        self._owned_membership(group,shape,True,journal)
            from .lifecycle import _properties, _native_properties
            before=_properties(self.board)
            journal.append(lambda:self.board.SetProperties(_native_properties(self.api,before)))
            self.board.SetProperties(_native_properties(self.api,self.properties_before))
            if self._layout_fingerprint()!=self.layout_before:
                raise ValueError('Underlying board geometry changed during Undo; operation rolled back.')
        except Exception as exc:
            self._rollback(journal,exc)
            raise
        self.applied = False
        self.expected = fingerprint(self.board,self.api)


def apply(board, api, preview):
    """Apply a current read-only preview and return its undo/redo transaction."""
    return Transaction(board,api,preview).redo()
