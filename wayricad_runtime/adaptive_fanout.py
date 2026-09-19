"""Bounded, read-only search for simple 45-degree fanout escapes."""
import math
import time
from .geometry import segment_segment_distance, segment_hits_box

MAX_CANDIDATES = 4096
MAX_SEARCH_SECONDS = 3.0

def _xy(point):
    return point.x, point.y

def _identity(item):
    return str(item.m_Uuid.AsString())

def _near(a, b):
    return math.hypot(a.x-b.x, a.y-b.y) <= 2

def _anchor(planner, pad, pads, tracks, zones, layer):
    """Continue only a simple endpoint-connected track chain, never a routed branch."""
    if not planner._on_layer(pad,layer):
        return pad.GetPosition(), []
    net = pad.GetNetCode()
    same = [t for t in tracks if t.GetNetCode() == net and planner._on_layer(t, layer)]
    starts = [t for t in same if pad.HitTest(t.GetStart()) or pad.HitTest(t.GetEnd())]
    if not starts:
        # A crossing with no endpoint in the pad is still an existing connection.
        if any(segment_hits_box(pad.GetPosition(),pad.GetPosition(),t.GetBoundingBox(),max(pad.GetSize().x,pad.GetSize().y)/2) if t.GetClass()!='PCB_TRACK' else segment_hits_box(t.GetStart(),t.GetEnd(),pad.GetBoundingBox(),t.GetWidth()/2) for t in same):
            raise ValueError('Adaptive routing cannot continue an interior pad/track connection.')
        return pad.GetPosition(), []
    if len(starts) != 1:
        raise ValueError('Adaptive routing refuses a branched or ambiguous pad connection.')
    current = starts[0]
    chain = []
    entry = pad.GetPosition()
    for _ in range(256):
        if current.GetClass() != 'PCB_TRACK':
            raise ValueError('Adaptive continuation requires straight tracks and an open endpoint; existing vias/arcs are retained.')
        a,b = current.GetStart(),current.GetEnd()
        if not chain:
            ina,inb = bool(pad.HitTest(a)),bool(pad.HitTest(b))
            if ina == inb:
                raise ValueError('Adaptive routing cannot resolve the existing pad launch.')
            entry, endpoint = (a,b) if ina else (b,a)
        else:
            endpoint = b if _near(a,entry) else a
        chain.append(current)
        for other in pads:
            if _identity(other) != _identity(pad) and planner._on_layer(other,layer) and segment_hits_box(a,b,other.GetBoundingBox(),current.GetWidth()/2):
                raise ValueError('Existing route reaches another pad; adaptive routing will not extend it.')
        touching=[]
        for other in same:
            if any(_identity(other)==_identity(old) for old in chain):continue
            c,d=other.GetStart(),other.GetEnd()
            if 'VIA' in other.GetClass():
                if segment_hits_box(a,b,other.GetBoundingBox(),current.GetWidth()/2):
                    raise ValueError('Adaptive continuation requires an open endpoint; existing vias/arcs are retained.')
                continue
            if segment_segment_distance(_xy(a),_xy(b),_xy(c),_xy(d)) <= (current.GetWidth()+other.GetWidth())/2:
                if not (_near(endpoint,c) or _near(endpoint,d)):
                    raise ValueError('Adaptive routing refuses an interior junction or overlapping existing copper.')
                touching.append(other)
        if len(touching)>1:
            raise ValueError('Adaptive routing refuses a branched existing route.')
        if not touching:
            for old in chain[:-1]:
                if _near(endpoint,old.GetStart()) or _near(endpoint,old.GetEnd()):
                    raise ValueError('Adaptive routing refuses a closed existing loop.')
            return endpoint,chain
        current,entry=touching[0],endpoint
    raise ValueError('Adaptive continuation exceeds the 256-track inspection budget.')

def _paths(radius, step):
    """Finite lattice family: axis/diagonal legs with at most two bends."""
    count=int(radius//step)
    candidates=set()
    def join(target):
        x,y=target; ax,ay=abs(x),abs(y); sx=1 if x>=0 else -1;sy=1 if y>=0 else -1
        if x==0 or y==0 or ax==ay:return [(target,)]
        diagonal=min(ax,ay)
        return [((sx*diagonal,sy*diagonal),target),((x-sx*diagonal,y-sy*diagonal),target)]
    for ix in range(-count,count+1):
        for iy in range(-count,count+1):
            x,y=ix*step,iy*step
            if not (x or y) or math.hypot(x,y)>radius+1:continue
            for tail in join((x,y)):candidates.add(((0,0),)+tail)
            # Short axis launches add a second bend around close obstacles.
            for dx,dy in ((step,0),(-step,0),(0,step),(0,-step)):
                for tail in join((x-dx,y-dy)):
                    points=((0,0),(dx,dy))+tuple((a+dx,b+dy) for a,b in tail)
                    if len(set(points))==len(points):candidates.add(points)
    return sorted(candidates,key=lambda pts:(sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(pts,pts[1:])),len(pts),pts))

def _search_paths(radius, step, fp, pad, values, pattern, chain, api):
    paths=_paths(radius,step)
    if pattern=='Perimeter pitch expansion' and not chain:
        from .perimeter_escape import _basis
        basis=_basis(fp,pad)
        if basis is None:raise ValueError('A center/exposed pad needs via-in-pad or a BGA style.')
        _,normal,tangent=basis
        size=pad.GetSize();angle=-math.radians(float(pad.GetOrientationDegrees()))
        half=(abs(normal[0]*math.cos(angle)+normal[1]*math.sin(angle))*size.x+abs(-normal[0]*math.sin(angle)+normal[1]*math.cos(angle))*size.y)/2
        launch=math.ceil(half+api.FromMM(float(values['launch_length'])))
        if launch>radius:raise ValueError('Adaptive radius is insufficient for the straight pad launch; increase radius or reduce launch length.')
        result={((0,0),(launch,0))}
        for points in paths:
            if any(b[0]<a[0] for a,b in zip(points,points[1:])) or points[1][0]<=0:continue
            expanded=((0,0),)+tuple((launch+x,y) for x,y in points)
            # Collapse collinear legs before limiting the complete route to two bends.
            compact=[]
            for point in expanded:
                while len(compact)>1 and (compact[-1][0]-compact[-2][0])*(point[1]-compact[-1][1])==(compact[-1][1]-compact[-2][1])*(point[0]-compact[-1][0]):compact.pop()
                compact.append(point)
            if len(compact)<=4 and all(math.hypot(x,y)<=radius+1 for x,y in compact):result.add(tuple(compact))
        paths=[tuple((round(x*normal[0]+y*tangent[0]),round(x*normal[1]+y*tangent[1])) for x,y in points) for points in result]
    else:
        paths=[points for points in paths if all(math.hypot(x,y)<=radius+1 for x,y in points)]
    direction=(0,0)
    if chain:
        a,b=chain[-1].GetStart(),chain[-1].GetEnd()
        direction=(b.x-a.x,b.y-a.y)
        if len(chain)>1 and (_near(b,chain[-2].GetStart()) or _near(b,chain[-2].GetEnd())):direction=(-direction[0],-direction[1])
        elif len(chain)==1 and pad.HitTest(b):direction=(-direction[0],-direction[1])
    def rank(points):
        dx,dy=points[1][0]-points[0][0],points[1][1]-points[0][1]
        alignment=(dx*direction[0]+dy*direction[1])/math.hypot(dx,dy)
        return sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:])),len(points),-alignment,points
    return sorted(paths,key=rank)


def adaptive_paths(planner, fp, pad, values, pattern, accepted, pads, tracks, zones, outline, margin):
    """Return the shortest valid enumerated candidate, or a bounded failure reason."""
    started=time.monotonic()
    try:
        radius,step = float(values.get('adaptive_radius',3)),float(values.get('adaptive_step',.25))
        if not all(math.isfinite(v) and v>0 for v in (radius,step)) or step>radius or radius/step>20 or radius>20:
            raise ValueError('Adaptive radius/step must be positive, step <= radius <= 20 mm and radius/step <= 20.')
        if pattern == 'Via-in-pad' or values.get('output_mode') == 'Via-in-pad':
            raise ValueError('Via-in-pad has a fixed location; use Fixed routing mode.')
        if values.get('pair_mode','Independent') != 'Independent':
            raise ValueError('Adaptive routing requires independent pads; coupled pairs need explicit paired routing.')
        layer=planner._layer(pad)
        anchor,chain=_anchor(planner,pad,pads,tracks,zones,layer)
        same_zones=[zone for zone in zones if not zone.GetIsRuleArea() and zone.GetNetCode()==pad.GetNetCode() and planner._on_layer(zone,layer)]
        for zone in same_zones:
            if any(segment_hits_box(t.GetStart(),t.GetEnd(),zone.GetBoundingBox(),t.GetWidth()/2) for t in chain):
                raise ValueError('Existing stub intersects a same-net zone; adaptive routing cannot infer its topology.')
            if not zone.GetIsRuleArea() and zone.GetNetCode()==pad.GetNetCode() and planner._on_layer(zone,layer) and zone.HitTestFilledArea(layer,anchor):
                raise ValueError('Adaptive routing cannot infer an open endpoint inside connected same-net zone copper.')
        radius,step=planner.api.FromMM(radius),planner.api.FromMM(step)
        if step<1:raise ValueError('Adaptive step is below board coordinate resolution.')
        paths=_search_paths(radius,step,fp,pad,values,pattern,chain,planner.api)
        # Every generated point is within the radius. Cache local obstacle lists
        # once so distant copper does not cost a full board scan per candidate.
        extent=radius+planner.api.FromMM(float(values["via_diameter"])+float(values["width"]))+margin+2
        def local(item):return segment_hits_box(anchor,anchor,item.GetBoundingBox(),extent)
        pads=[item for item in pads if local(item)]
        tracks=[item for item in tracks if local(item)]
        zones=[item for item in zones if local(item)]
        chain_ids={_identity(t) for t in chain}
        same=[t for t in tracks if t.GetNetCode()==pad.GetNetCode() and planner._on_layer(t,layer) and _identity(t) not in chain_ids]
        def track_width(t):return t.GetWidth(layer) if 'VIA' in t.GetClass() else t.GetWidth()
        reason='no valid candidate'
        for checked,points in enumerate(paths[:MAX_CANDIDATES]):
            if time.monotonic()-started>MAX_SEARCH_SECONDS:
                return None,f"Adaptive search reached its {MAX_SEARCH_SECONDS:g}-second time budget after {checked} candidates; reduce radius or increase step."
            native=[planner.api.VECTOR2I(anchor.x+x,anchor.y+y) for x,y in points]
            candidate=planner._candidate(fp,pad,native,values,pattern)
            candidate.start=native[0]
            if chain:candidate.start_via=False
            endpoint_margin=(candidate.via_diameter if candidate.add_via else candidate.width)/2+margin
            if segment_hits_box(candidate.end,candidate.end,pad.GetBoundingBox(),endpoint_margin):
                reason='endpoint still inside pad launch clearance';continue
            if any(_identity(other)!=_identity(pad) and other.GetNetCode()==pad.GetNetCode() and planner._on_layer(other,layer) and any(segment_hits_box(a,b,other.GetBoundingBox(),candidate.width/2) for a,b in planner._segments(candidate)) for other in pads):
                reason='would connect another same-net pad';continue
            # Existing same-net copper is not an obstacle in the general planner,
            # but adaptive escapes must not introduce an accidental new branch.
            segments=planner._segments(candidate)
            if any(segment_hits_box(a,b,zone.GetBoundingBox(),candidate.width/2+margin) for a,b in segments for zone in same_zones):
                reason='same-net zone topology';continue
            if any(segment_hits_box(a,b,t.GetBoundingBox(),candidate.width/2+margin) for a,b in segments for t in same if t.GetClass()!='PCB_TRACK'):
                reason='existing same-net via/arc';continue
            if any(segment_segment_distance(_xy(a),_xy(b),_xy(t.GetStart()),_xy(t.GetEnd())) < (candidate.width+track_width(t))/2+margin for a,b in segments for t in same):
                reason='existing same-net route';continue
            if chain:
                last=chain[-1];a,b=last.GetStart(),last.GetEnd();previous=a if _near(b,anchor) else b
                direction=(anchor.x-previous.x,anchor.y-previous.y)
                if (native[1].x-anchor.x)*direction[0]+(native[1].y-anchor.y)*direction[1]<0:
                    reason='would reverse along existing stub';continue
                if any(segment_segment_distance(_xy(a),_xy(b),_xy(t.GetStart()),_xy(t.GetEnd())) < (candidate.width+t.GetWidth())/2 for a,b in segments for t in chain[:-1]):
                    reason='would cross existing stub';continue
                if any(segment_segment_distance(_xy(a),_xy(b),_xy(last.GetStart()),_xy(last.GetEnd())) < (candidate.width+last.GetWidth())/2 for a,b in segments[1:]):
                    reason='would cross existing stub';continue
            if any(segment_segment_distance(_xy(a),_xy(b),_xy(c),_xy(d)) < (candidate.width+other.width)/2+max(margin,other.clearance) for other in accepted if other.net_code==candidate.net_code for a,b in segments for c,d in planner._segments(other)):
                reason='would branch a generated same-net route';continue
            reason=planner._blocked(candidate,accepted,pads,tracks,zones,outline,margin)
            if not reason:return candidate,''
        return None,f'Adaptive search exhausted {min(len(paths),MAX_CANDIDATES)} candidates within {float(values.get("adaptive_radius",3)):g} mm: {reason}.'
    except (ValueError,RuntimeError) as exc:
        return None,str(exc)
