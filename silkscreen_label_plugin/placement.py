"""Conservative, read-only silk label planning for native KiCad boards.

All settings are millimetres. Native text envelopes deliberately overestimate
glyph area; a rejected label is left untouched rather than shrunk or forced.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import time

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
                step=0.5, leaders=True, leader_distance=3.0)
GUIDE_PREFIX = 'WayriCAD Silk guide '


def _state(text):
    p, s = text.GetPosition(), text.GetTextSize()
    return (p.x, p.y, text.GetTextAngle().AsDegrees(), s.x, s.y,
            text.GetTextThickness(), text.IsMirrored())


def _set(text, state, api):
    x, y, angle, w, h, stroke, mirror = state
    text.SetPosition(api.VECTOR2I(x, y))
    text.SetTextAngle(api.EDA_ANGLE(angle, api.DEGREES_T))
    text.SetTextSize(api.VECTOR2I(w, h))
    text.SetTextThickness(stroke)
    text.SetMirrored(mirror)


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
    ds = board.GetDesignSettings()
    floors = [getattr(ds, k, 0) for k in
              ('m_MinSilkTextHeight', 'm_MinSilkTextThickness', 'm_SilkClearance')]
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


def _box(text, state, api):
    clone = api.PCB_TEXT(text)
    clone.SetText(text.GetShownText(False))
    clone.SetLayer(text.GetLayer())
    _set(clone, state, api)
    return clone.GetBoundingBox()


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
    bounds a deterministic orthogonal search. leaders link distant fields to
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
    for name in ('height', 'thickness', 'clearance', 'max_radius', 'step', 'leader_distance'):
        value = float(options[name])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name + ' must be finite and positive.')
        options[name] = value
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
        hull = fp.GetCourtyard(api.B_CrtYd if layer == api.B_SilkS else api.F_CrtYd)
        if not hull.OutlineCount():
            hull = fp.GetBoundingHull()
        body = hull.BBox() if hull.OutlineCount() else fp.GetBoundingBox(False)
        bodies[item_id(fp)] = body
        obstacles[layer].append((body, 'body:' + item_id(fp)))
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
    for text, fp, kind in texts:
        layer,key = text.GetLayer(),item_id(text)
        label = (fp.GetReference() + ' / ' if fp else '') + text.GetShownText(False)
        enabled = options['references'] if kind == 'reference' else options['values'] if kind == 'value' else options['board_text'] if kind == 'board' else False
        if not enabled or layer not in obstacles:
            continue
        if not text.IsVisible() or text.IsLocked() or (fp and fp.IsLocked()):
            result.skipped.append((label,'Hidden or locked text/footprint.'))
            continue
        if options['selected_only'] and not (text.IsSelected() or fp and
                (fp.IsSelected() or any(p.IsSelected() for p in fp.Pads()))):
            continue
        before = _state(text)
        base = list(before)
        base[2] = 90.0 if round(before[2]/90) % 2 else 0.0
        base[3],base[4] = max(before[3],height),max(before[4],height)
        base[5] = max(before[5],stroke)
        base[6] = layer == api.B_SilkS
        templates = []
        for angle in (base[2],90.0-base[2]):
            state = tuple(base[:2]+[angle]+base[3:])
            templates.append((state,_box(text,state,api)))
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

    def inside(a,b,radius):
        first,second = (a.x,a.y),(b.x,b.y)
        if not outline.Contains(a) or not outline.Contains(b):
            return False
        region = _line_box((*first,*second,0,0),api,radius)
        return all(segment_segment_distance(first,second,*boundary_edges[index])>=radius
                   for _,index in boundary.query(region))

    def positions(origin,before,fp,templates):
        yield before[0],before[1]
        if fp:
            body = bodies[item_id(fp)]
            # Clearance-derived side positions find narrow slots even when
            # their centre does not lie on the user-visible search grid.
            for state,box in templates:
                left = body.GetLeft()-clearance-1-(box.GetRight()-before[0])
                right = body.GetRight()+clearance+1-(box.GetLeft()-before[0])
                top = body.GetTop()-clearance-1-(box.GetBottom()-before[1])
                bottom = body.GetBottom()+clearance+1-(box.GetTop()-before[1])
                for distance in range(min(rings,12)+1):
                    for offset in ({0} if not distance else (-distance*step,distance*step)):
                        for x,y in ((left,origin.y+offset),(right,origin.y+offset),
                                    (origin.x+offset,top),(origin.x+offset,bottom)):
                            if math.hypot(x-origin.x,y-origin.y)<=api.FromMM(options['max_radius']):
                                yield x,y
        for ring in range(1,rings+1):
            offsets = [(x,y) for x in range(-ring,ring+1)
                       for y in (-ring,ring)]
            offsets += [(x,y) for x in (-ring,ring)
                        for y in range(-ring+1,ring)]
            offsets.sort(key=lambda xy:(xy[0]*xy[0]+xy[1]*xy[1],xy[1],xy[0]))
            for x,y in offsets:
                if x*x+y*y <= rings*rings:
                    yield origin.x+x*step,origin.y+y*step

    def check_leader(box,origin,fp,key,index,layer):
        gap = clearance+stroke//2+1
        label_box = _inflate(box,gap,api)
        body = _inflate(bodies[item_id(fp)],gap,api)
        a = (min(max(origin.x,label_box.GetLeft()),label_box.GetRight()),
             min(max(origin.y,label_box.GetTop()),label_box.GetBottom()))
        b = (min(max(box.GetCenter().x,body.GetLeft()),body.GetRight()),
             min(max(box.GetCenter().y,body.GetTop()),body.GetBottom()))
        paths = [(a,b),(a,(a[0],b[1]),b),(a,(b[0],a[1]),b)]
        own_label = _inflate(box,gap-1,api)
        for path in paths:
            path = tuple(point for i,point in enumerate(path) if not i or point != path[i-1])
            valid = len(path)>1
            for first,second in zip(path,path[1:]):
                p,q = api.VECTOR2I(*first),api.VECTOR2I(*second)
                segment = (*first,*second,stroke,layer)
                if not inside(p,q,clearance+stroke//2) or segment_hits_box(p,q,own_label):
                    valid = False;break
                near = index.query(_line_box(segment,api,clearance))
                if any(segment_hits_box(p,q,obstacle,clearance+stroke//2)
                       for obstacle,oid in near if oid not in (key,'guide:'+key)):
                    valid = False;break
            if valid:
                return path
        return None

    def assign(active):
        indices = {layer:_SpatialIndex(api.FromMM(4)) for layer in obstacles}
        for layer,rows in obstacles.items():
            for box,key in rows:
                if key.startswith('guide:') and key[6:] in active:
                    continue
                indices[layer].add(box,key)
        for text,_,_ in texts:
            layer,key = text.GetLayer(),item_id(text)
            if layer in indices and text.IsVisible() and key not in active:
                indices[layer].add(text.GetBoundingBox(),key)
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
            for x,y in positions(origin,before,fp,templates):
                for state,template in templates:
                    attempts += 1;checks[0] += 1
                    if attempts > 4096 or time.monotonic()>deadline:
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
                    chosen = Change(text,before,after,label,box,leader,guides.get(key,[]),path)
                    break
                if chosen or attempts>4096 or time.monotonic()>deadline:
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
        text = text_by_key[key]
        if text.IsVisible() and text.GetLayer() in preserved_indices:
            preserved_indices[text.GetLayer()].add(text.GetBoundingBox(),key)
        for _,shapes in guides.get(key,[]):
            for shape in shapes:
                preserved_indices[shape.GetLayer()].add(shape.GetBoundingBox(),'guide:'+key)
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
        if chosen.after != chosen.before or not matches:
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
                # Text setters can fail after one of the individual attributes.
                journal.append(lambda c=change:_set(c.item,c.before,self.api))
                _set(change.item,change.after,self.api)
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
