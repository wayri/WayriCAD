"""Conservative, read-only silk label planning for native KiCad boards.

All settings are millimetres. Native text envelopes deliberately overestimate
glyph area; rejected labels remain untouched. Optional bounded sizing never
shrinks below the user minimum or native fabrication floors.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import time
import fnmatch
from .guide_routing import dogleg_paths, visibility_path

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
                height=1.0, thickness=0.15, clearance=0.2, max_radius=12.0,
                step=0.5, leaders=True, leader_distance=3.0,
                auto_size=True, min_height=0.8, size_step=0.1,
                allowed_rotations=(0, 45, 90, 135, 15, 30, 60, 75, 105, 120, 150, 165), reading_direction='Bottom/right',
                formatting_rules=[], testpoint_net_names=False, testpoint_pattern='TP*')
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
    """Include field visibility/content, text geometry and native silk floors."""
    rows = [(item_id(t), _state(t), t.GetText(), t.IsVisible(), t.IsLocked(), t.GetLayer(),
             t.IsBold(), t.IsItalic(), str(t.GetHorizJustify()), str(t.GetVertJustify()),
             t.GetFontName(), t.GetLineSpacing())
            for t, _, _ in _texts(board, api)]
    rows += [(item_id(fp), fp.IsLocked(), [(item_id(p), p.GetDrillSize().x,
             p.GetDrillSize().y, p.GetSolderMaskExpansion(api.F_Mask),
             p.GetSolderMaskExpansion(api.B_Mask)) for p in fp.Pads()])
             for fp in board.GetFootprints()]
    rows += [(item_id(track), track.HasSolderMask(), track.GetSolderMaskExpansion())
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
    clone, shape = text_geometry(text, state, api)
    box = clone.GetBoundingBox()
    if shape.OutlineCount():
        box.Merge(shape.BBox())
    return box


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
            if graphic.GetLayer() == court:
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


def _angles(options, old_angle):
    """Angles are board coordinates viewed from the text's own board side."""
    bases = options['allowed_rotations']
    direction = options['reading_direction']
    angles = [float(a+d) for d in ((0, 180) if direction == 'Either' else
                                  (180,) if direction == 'Top/left' else (0,)) for a in bases]
    # A common direction wins over each label's existing rotation. Explicit
    # angles remain supported; 45-degree increments precede finer fallbacks.
    return sorted(angles, key=lambda a: (a%180 != 0, a%45 != 0, a%180, a))


def _inflate(box, distance, api):
    return api.BOX2I(api.VECTOR2I(box.GetLeft()-distance, box.GetTop()-distance),
                    api.VECTOR2I(box.GetWidth()+2*distance, box.GetHeight()+2*distance))


def _line_state(shape):
    a,b = shape.GetStart(),shape.GetEnd()
    return (a.x,a.y,b.x,b.y,shape.GetWidth(),shape.GetLayer())


class _SpatialIndex:
    """Uniform grid of conservative envelopes, including large global items."""
    def __init__(self, cell):
        self.cell = cell
        self.buckets, self.large, self.rows = {}, [], []

    def _cells(self, box):
        left,right = box.GetLeft()//self.cell,box.GetRight()//self.cell
        top,bottom = box.GetTop()//self.cell,box.GetBottom()//self.cell
        if (right-left+1)*(bottom-top+1) > 1024:
            return None
        return [(x,y) for x in range(left,right+1) for y in range(top,bottom+1)]

    def add(self, box, key):
        row = len(self.rows)
        self.rows.append((box,key))
        cells = self._cells(box)
        if cells is None:
            self.large.append(row)
        else:
            for cell in cells:
                self.buckets.setdefault(cell,[]).append(row)

    def query(self, box):
        cells = self._cells(box)
        if cells is None:
            return self.rows
        rows = set(self.large)
        for cell in cells:
            rows.update(self.buckets.get(cell,()))
        return [self.rows[i] for i in sorted(rows)]


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
    for name in ('height', 'thickness', 'clearance', 'max_radius', 'step', 'leader_distance', 'min_height', 'size_step'):
        value = float(options[name])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name + ' must be finite and positive.')
        options[name] = value
    _typography(options)
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
    for group in board.Groups():
        if not group.GetName().startswith(GUIDE_PREFIX):
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
            obstacles[graphic.GetLayer()].append((graphic.GetBoundingBox(),
                'guide:'+guide_owners[oid] if oid in guide_owners else oid))
        for silk, mask in ((api.F_SilkS,api.F_Mask),(api.B_SilkS,api.B_Mask)):
            if graphic.GetLayer() == mask:
                obstacles[silk].append((graphic.GetBoundingBox(),item_id(graphic)))
    for track in board.GetTracks():
        for silk, copper in ((api.F_SilkS,api.F_Cu),(api.B_SilkS,api.B_Cu)):
            if isinstance(track,api.PCB_VIA) or (track.GetLayer() == copper and track.HasSolderMask()):
                expansion = max(0,track.GetSolderMaskExpansion())
                obstacles[silk].append((_inflate(track.GetBoundingBox(),expansion,api),item_id(track)))
    eligible = []
    for text, fp, kind in working_texts:
        layer,key = text.GetLayer(),item_id(text)
        annotation = annotation_actions.get(key)
        render = render_items.get(key,text)
        label = (fp.GetReference() + ' / ' if fp else '') + render.GetShownText(False)
        enabled = True if annotation else options['references'] if kind == 'reference' else options['values'] if kind == 'value' else options['board_text'] if kind == 'board' else False
        if not enabled or layer not in obstacles:
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
            sizes = list(range(height, minimum-1, -api.FromMM(options['size_step'])))
            if not sizes or sizes[-1] != minimum:
                sizes.append(minimum)
        else:
            sizes = [None]
        for size in sizes:
            if size is None:
                base[3],base[4] = max(before[3],height),max(before[4],height)
                base[5] = max(before[5],stroke)
            else:
                base[3] = base[4] = size
                base[5] = max(ds.m_MinSilkTextThickness,
                              min(stroke, round(stroke*size/height)))
            if base[5]*4 > base[4]:
                continue
            for angle in _angles(options, before[2]):
                state = tuple(base[:2]+[angle]+base[3:])
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
    deadline = started+30.0
    checks = [0]
    label_deadline = [deadline]

    def inside(a,b,radius):
        first,second = (a.x,a.y),(b.x,b.y)
        if not outline.Contains(a) or not outline.Contains(b):
            return False
        region = _line_box((*first,*second,0,0),api,radius)
        return all(segment_segment_distance(first,second,*boundary_edges[index])>=radius
                   for _,index in boundary.query(region))

    def positions(origin,before,fp,templates,layer,local,index):
        radius = api.FromMM(min(2.,options['max_radius']) if local else options['max_radius'])
        body = bodies.get((item_id(fp),layer),bodies[item_id(fp)]) if fp else None
        def near(x,y):
            # Search distance is measured from the footprint envelope, so large
            # connectors are not penalized for their distance from their origin.
            dx=max(body.GetLeft()-x,0,x-body.GetRight()) if body else x-origin.x
            dy=max(body.GetTop()-y,0,y-body.GetBottom()) if body else y-origin.y
            return math.hypot(dx,dy)<=radius
        if near(before[0],before[1]):yield before[0],before[1]
        if fp:
            body = bodies.get((item_id(fp),layer),bodies[item_id(fp)])
            # Clearance-derived side positions find narrow slots even when
            # their centre does not lie on the user-visible search grid.
            for state,box in templates:
                left = body.GetLeft()-clearance-1-(box.GetRight()-before[0])
                right = body.GetRight()+clearance+1-(box.GetLeft()-before[0])
                top = body.GetTop()-clearance-1-(box.GetBottom()-before[1])
                bottom = body.GetBottom()+clearance+1-(box.GetTop()-before[1])
                for distance in range((min(rings,12) if local else rings)+1):
                    for offset in ({0} if not distance else (-distance*step,distance*step)):
                        corridor = 2*clearance+stroke+api.FromMM(.1)
                        offsets = (0,corridor) if options['leaders'] else (0,)
                        for extra in offsets:
                            for x,y in ((left-extra,origin.y+offset),(right+extra,origin.y+offset),
                                        (origin.x+offset,top-extra),(origin.x+offset,bottom+extra)):
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

    def check_leader(box,origin,fp,key,index,layer):
        gap = clearance+stroke//2+1
        label_box = _inflate(box,gap,api)
        body = _inflate(bodies.get((item_id(fp),layer),bodies[item_id(fp)]),gap,api)
        a = (min(max(origin.x,label_box.GetLeft()),label_box.GetRight()),
             min(max(origin.y,label_box.GetTop()),label_box.GetBottom()))
        b = (min(max(box.GetCenter().x,body.GetLeft()),body.GetRight()),
             min(max(box.GetCenter().y,body.GetTop()),body.GetBottom()))
        own_label = _inflate(box,gap-1,api)
        def clear(first,second):
            if time.monotonic()>label_deadline[0]:return False
            p,q = api.VECTOR2I(*first),api.VECTOR2I(*second)
            segment = (*first,*second,stroke,layer)
            if not inside(p,q,clearance+stroke//2) or segment_hits_box(p,q,own_label):return False
            return not any(segment_hits_box(p,q,obstacle,clearance+stroke//2)
                           for obstacle,oid in index.query(_line_box(segment,api,clearance))
                           if oid not in (key,'guide:'+key))
        region = _line_box((*a,*b,stroke,layer),api,api.FromMM(options['max_radius']))
        nearby = [obstacle for obstacle,oid in index.query(region)
                  if oid not in (key,'guide:'+key) and obstacle.Intersects(region)]
        boxes = [(r.GetLeft(),r.GetTop(),r.GetRight(),r.GetBottom()) for r in nearby]
        def candidate_paths():
            dx,dy=b[0]-a[0],b[1]-a[1]
            diagonal=min(abs(dx),abs(dy))
            sx=1 if dx>=0 else -1;sy=1 if dy>=0 else -1
            yield from ((a,b),(a,(a[0]+sx*diagonal,a[1]+sy*diagonal),b),
                        (a,(b[0]-sx*diagonal,b[1]-sy*diagonal),b),
                        (a,(a[0],b[1]),b),(a,(b[0],a[1]),b))
            yield from dogleg_paths(a,b,boxes,gap,limit=16)
        for path in candidate_paths():
            path = tuple(point for i,point in enumerate(path) if not i or point!=path[i-1])
            if len(path)>1 and all(clear(first,second) for first,second in zip(path,path[1:])):return path
        # Multi-bend fallback is strictly bounded. The same native full-stroke
        # checker validates every edge, including holes and previously routed guides.
        return visibility_path(a,b,boxes,gap,clear,max_nodes=48,max_checks=2048)

    def assign(active):
        replaced = {item_id(text) for key in active if key in annotation_actions
                    for text in annotation_actions[key].originals}
        removed_guide_owners = active | replaced
        indices = {layer:_SpatialIndex(api.FromMM(4)) for layer in obstacles}
        for layer,rows in obstacles.items():
            for box,key in rows:
                if key.startswith('guide:') and key[6:] in removed_guide_owners:
                    continue
                indices[layer].add(box,key)
        for text,_,_ in texts:
            layer,key = text.GetLayer(),item_id(text)
            if layer in indices and text.IsVisible() and key not in active and key not in replaced:
                indices[layer].add(_box(text,_state(text),api),key)
        assignments,rejected = [],set()
        completed = 0
        for text,fp,key,label,before,templates,_ in eligible:
            if key not in active:
                continue
            if progress is not None and progress(completed,len(active),label) is False:
                raise ValueError('Placement cancelled; board unchanged.')
            completed += 1
            layer = text.GetLayer()
            origin = fp.GetPosition() if fp else text.GetPosition()
            chosen,attempts = None,0
            # Share the plan budget across difficult labels and replans.
            # An impossible long name must not starve the rest of a dense board.
            label_deadline[0] = min(deadline,time.monotonic()+max(.04,min(.4,30./(2*max(1,len(eligible))))))
            angle_groups = []
            for angle in dict.fromkeys(state[2] for state,_ in templates):
                angle_groups.append([t for t in templates if t[0][2]==angle])
            def candidates():
                # Exhaust nearby common-direction sizes before rotations. Only
                # after all nearby angle alternatives try distant guided slots.
                for local in (True,False):
                    for angle_index,group in enumerate(angle_groups):
                        for template in group:
                            state,envelope = template
                            for count,(x,y) in enumerate(positions(origin,before,fp,[template],layer,local,indices[layer])):
                                if count >= ((768 if angle_index==0 else 128) if local else (4096 if angle_index==0 else 512)):break
                                yield x,y,state,envelope
            for x,y,state,template in candidates():
                attempts += 1;checks[0] += 1
                if attempts>12000 or time.monotonic()>label_deadline[0]:
                    break
                after = (x,y)+state[2:]
                box = api.BOX2I(api.VECTOR2I(template.GetLeft()+x-before[0],template.GetTop()+y-before[1]),
                                api.VECTOR2I(template.GetWidth(),template.GetHeight()))
                expanded = _inflate(box,clearance,api)
                if any(expanded.Intersects(obstacle) for obstacle,_ in indices[layer].query(expanded)):
                    continue
                corners = [api.VECTOR2I(a,b) for a,b in ((expanded.GetLeft(),expanded.GetTop()),(expanded.GetRight(),expanded.GetTop()),(expanded.GetRight(),expanded.GetBottom()),(expanded.GetLeft(),expanded.GetBottom()))]
                if any(not inside(corners[i],corners[(i+1)%4],1) for i in range(4)):
                    continue
                if any(expanded.GetLeft() <= x <= expanded.GetRight() and
                       expanded.GetTop() <= y <= expanded.GetBottom()
                       for _,holes in native_polygons for hole in holes for x,y in hole):
                    continue
                path,leader = (),None
                if fp and options['leaders'] and math.hypot(x-origin.x,y-origin.y)>api.FromMM(options['leader_distance']):
                    path = check_leader(box,origin,fp,key,indices[layer],layer)
                    if not path:
                        continue
                    leader = (*path[0],*path[1],stroke,layer)
                previous = []
                owner_ids = {key}
                if key in annotation_actions:owner_ids.update(item_id(t) for t in annotation_actions[key].originals)
                for owner_id in sorted(owner_ids):previous.extend(guides.get(owner_id,[]))
                chosen = Change(text,before,after,label,box,leader,previous,path,
                                preview_item=render_items.get(key),annotation=annotation_actions.get(key))
                break
            if chosen is None:
                rejected.add(key)
                continue
            assignments.append(chosen)
            indices[layer].add(chosen.box,key)
            for segment in _leader_segments(chosen):
                indices[layer].add(_line_box(segment,api),'leader:'+key)
        return assignments,rejected

    # Movable original fields are not obstacles to one another. When a field
    # cannot be placed, its original envelope is restored as a fixed obstacle
    # and the active set is replanned. This avoids both deadlocks and overlaps
    # with labels which must remain in their original positions.
    active,preserved = set(all_keys),set()
    assignments = []
    for _ in range(4):
        assignments,rejected = assign(active)
        if not rejected:
            break
        active -= rejected;preserved.update(rejected)
        if time.monotonic()>deadline:
            break
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
                    preserved_indices[shape.GetLayer()].add(shape.GetBoundingBox(),'guide:'+owner_id)
    for key in preserved:
        preserve(key)
    # Bounded replanning may expose a chain of preserved originals. Demotion to
    # the unchanged state closes that chain without ever applying an overlap.
    changed = True
    while changed:
        changed = False
        for change in list(assignments):
            layer,key = change.item.GetLayer(),item_id(change.item)
            expanded = _inflate(change.box,clearance,api)
            conflict = any(expanded.Intersects(box) for box,_ in preserved_indices[layer].query(expanded))
            for segment in _leader_segments(change):
                p,q = api.VECTOR2I(*segment[:2]),api.VECTOR2I(*segment[2:4])
                conflict = conflict or any(segment_hits_box(p,q,box,clearance+segment[4]//2)
                    for box,_ in preserved_indices[layer].query(_line_box(segment,api,clearance)))
            if conflict:
                assignments.remove(change);preserved.add(key);preserve(key);changed = True
    for key in sorted(preserved,key=lambda key:(label_by_key[key],key)):
        result.rejected.append((label_by_key[key],'No safe text/guide position within the bounded dense search; original retained.'))
    for chosen in assignments:
        old_shapes = [shape for _,shapes in chosen.previous_guides for shape in shapes]
        matches = sorted(_line_state(shape) for shape in old_shapes) == sorted(_leader_segments(chosen))
        annotation = chosen.annotation
        presentation_changed = annotation and (annotation.create or annotation.remove
            or annotation.text_before != annotation.net or annotation.reference_visible_before)
        if chosen.after != chosen.before or not matches or presentation_changed:
            result.changes.append(chosen)
    result.stats = dict(eligible=len(eligible),placed=len(assignments),changed=len(result.changes),
                        unresolved=len(preserved),candidate_checks=checks[0],
                        elapsed_seconds=round(time.monotonic()-started,3),
                        search_limit_reached=time.monotonic()>deadline)
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

    @staticmethod
    def _do(action, inverse, journal):
        action()
        journal.append(inverse)

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
        journal, leaders, groups = [], [], []
        retained = iter(self.leaders)
        retained_groups = iter(self.groups)
        try:
            for change in self.preview.changes:
                for group, shapes in change.previous_guides:
                    for shape in shapes:
                        self._do(lambda g=group,s=shape:g.RemoveItem(s),
                                 lambda g=group,s=shape:g.AddItem(s),journal)
                        self._do(lambda s=shape:self.board.Remove(s),
                                 lambda s=shape:self.board.Add(s),journal)
                    self._do(lambda g=group:self.board.Remove(g),
                             lambda g=group:self.board.Add(g),journal)
                if change.annotation:self._annotation_redo(change.annotation,journal)
                # Text setters can fail after one of the individual attributes.
                journal.append(lambda c=change:_set(c.item,c.before,self.api))
                _set(change.item,change.after,self.api)
                actual = change.item.GetBoundingBox()
                glyphs = self.api.SHAPE_POLY_SET()
                change.item.TransformTextToPolySet(glyphs,0,self.api.FromMM(.001),self.api.ERROR_OUTSIDE)
                if glyphs.OutlineCount():actual.Merge(glyphs.BBox())
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
                        self._do(lambda s=shape:self.board.Add(s),
                                 lambda s=shape:self.board.Remove(s),journal)
                        self._do(lambda g=group,s=shape:g.AddItem(s),
                                 lambda g=group,s=shape:g.RemoveItem(s),journal)
                        leaders.append(shape)
                    self._do(lambda g=group:self.board.Add(g),
                             lambda g=group:self.board.Remove(g),journal)
                    groups.append(group)
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
                    self._do(lambda g=group,s=shape:g.RemoveItem(s),
                             lambda g=group,s=shape:g.AddItem(s),journal)
                self._do(lambda g=group:self.board.Remove(g),
                         lambda g=group:self.board.Add(g),journal)
            for shape in self.leaders:
                self._do(lambda s=shape:self.board.Remove(s),
                         lambda s=shape:self.board.Add(s),journal)
            for change in self.preview.changes:
                journal.append(lambda c=change:_set(c.item,c.after,self.api))
                _set(change.item,change.before,self.api)
                if change.annotation:self._annotation_undo(change.annotation,journal)
                for group,shapes in change.previous_guides:
                    self._do(lambda g=group:self.board.Add(g),
                             lambda g=group:self.board.Remove(g),journal)
                    for shape in shapes:
                        self._do(lambda s=shape:self.board.Add(s),
                                 lambda s=shape:self.board.Remove(s),journal)
                        self._do(lambda g=group,s=shape:g.AddItem(s),
                                 lambda g=group,s=shape:g.RemoveItem(s),journal)
        except Exception as exc:
            self._rollback(journal,exc)
            raise
        self.applied = False
        self.expected = fingerprint(self.board,self.api)


def apply(board, api, preview):
    """Apply a current read-only preview and return its undo/redo transaction."""
    return Transaction(board,api,preview).redo()
