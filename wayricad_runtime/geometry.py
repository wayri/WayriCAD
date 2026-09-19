"""Pure geometry checks shared by native and IPC routing adapters."""
import math


def positive(value, label, allow_zero=False):
    number=float(value)
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f'{label} must be a finite {"non-negative" if allow_zero else "positive"} number.')
    return number


def dimensions(width, length, diameter, drill):
    values=[positive(x,n) for x,n in zip((width,length,diameter,drill),('Track width','Escape length','Via diameter','Drill'))]
    if values[3]>=values[2]:raise ValueError('Via drill must be smaller than via diameter.')
    return values


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


def inside_native(position,radius,native):
    point=(position.x,position.y)
    return any(disk_inside(point,radius,outer,holes) for outer,holes in polygons(native))


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


def segment_hits_pad(start, end, pad, margin, api):
    """Use a pad-aligned conservative envelope instead of its rotated AABB."""
    from types import SimpleNamespace
    supported = tuple(getattr(api, name, object()) for name in
                      ('PAD_SHAPE_RECT','PAD_SHAPE_ROUNDRECT','PAD_SHAPE_OVAL','PAD_SHAPE_CIRCLE'))
    if not hasattr(pad,'GetAttribute') or pad.GetShape() not in supported:
        return segment_hits_box(start,end,pad.GetBoundingBox(),margin)
    angle = -math.radians(float(pad.GetOrientationDegrees()))
    cosine,sine = math.cos(angle),math.sin(angle)
    center = pad.GetPosition()
    offset = getattr(pad,'GetOffset',lambda: SimpleNamespace(x=0,y=0))()
    cx = center.x+cosine*offset.x-sine*offset.y
    cy = center.y+sine*offset.x+cosine*offset.y
    def local(point):
        dx,dy = point.x-cx,point.y-cy
        return SimpleNamespace(x=cosine*dx+sine*dy,y=-sine*dx+cosine*dy)
    size = pad.GetSize()
    box = SimpleNamespace(GetLeft=lambda:-size.x/2, GetRight=lambda:size.x/2,
                          GetTop=lambda:-size.y/2, GetBottom=lambda:size.y/2)
    return segment_hits_box(local(start),local(end),box,margin)


def board_fingerprint(board,ignore=()):
    """Snapshot relevant geometry; ignore only objects owned by this preview."""
    import hashlib,json
    ignored={item_id(x) for x in ignore}
    data=[]
    for getter in ('GetFootprints','GetTracks','GetDrawings','Zones'):
        for item in getattr(board,getter,lambda:[])():
            if item_id(item) in ignored:continue
            box=item.GetBoundingBox()
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


def remove_owned(board,items):
    """Retain unresolved objects so a failed cleanup can be retried."""
    errors=[]
    for item in list(items):
        try:board.Remove(item)
        except Exception as exc:errors.append(str(exc))
        else:items.remove(item)
    if errors:raise RuntimeError(f'{len(items)} preview objects could not be removed. Retry Clear Preview. '+ '; '.join(errors))


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
