"""Bounded connector escapes to a footprint-local envelope; no board writes."""
import heapq
import math
import time


SIDES = ('Nearest edge', 'Top', 'Bottom', 'Left', 'Right')


def envelope(fp, api, layer):
    """Return local bounds from courtyard, otherwise the native body/pad hull."""
    angle=-math.radians(float(fp.GetOrientationDegrees()))
    co,si=math.cos(angle),math.sin(angle);center=fp.GetPosition()
    def local(point):
        x,y=point.x-center.x,point.y-center.y
        return co*x+si*y,-si*x+co*y
    def world(x,y):
        return api.VECTOR2I(round(center.x+co*x-si*y),round(center.y+si*x+co*y))
    polygon=fp.GetCourtyard(layer)
    source='courtyard'
    if polygon.OutlineCount()==0:
        polygon=fp.GetBoundingHull();source='body/pad hull'
    points=[local(polygon.COutline(i).CPoint(j)) for i in range(polygon.OutlineCount()) for j in range(polygon.COutline(i).PointCount())]
    if not points:raise ValueError('Connector has no usable courtyard or body/pad envelope.')
    bounds=(min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
    return bounds,local,world,source


def escape(planner, fp, pad, values, accepted, pads, tracks, zones, outline, margin):
    """Search 8-neighbor local grid; exact segment checks gate every candidate."""
    if values['pair_mode']!='Independent':raise ValueError('Connector edge fanout currently requires independent pins; pair/skew tuning is separate.')
    if values['routing_mode']!='Fixed':raise ValueError('Connector edge uses its own bounded search; choose Fixed routing.')
    layer=planner._layer(pad)
    bounds,local,world,source=envelope(fp,planner.api,layer)
    inset=planner.api.FromMM(float(values['connector_edge_margin']))
    left,top,right,bottom=bounds;left-=inset;top-=inset;right+=inset;bottom+=inset
    sx,sy=local(pad.GetPosition());step=planner.api.FromMM(float(values['adaptive_step']))
    if step<1:raise ValueError('Connector search step is below coordinate resolution.')
    if not left<sx<right or not top<sy<bottom:raise ValueError('Pad lies outside connector envelope; inspect courtyard/body geometry.')
    if planner._has_pad_route(pad):
        raise ValueError('Pad already has connected copper; connector escape will not duplicate it.')
    side=values['connector_exit'];targets={'Left':left,'Right':right,'Top':top,'Bottom':bottom}
    def distance(x,y):
        return min(x-left,right-x,y-top,bottom-y) if side=='Nearest edge' else abs((x if side in ('Left','Right') else y)-targets[side])
    corners=[world(left,top),world(right,top),world(right,bottom),world(left,bottom)]

    override=values.get('connector_clearance','')
    local_margin=margin if override=='' else planner.api.FromMM(float(override))
    if override!='':
        from .connector_review import validate_connector_clearance
        validate_connector_clearance(planner.board,planner.api,local_margin)
    if override!='':
        def enclosed(item):
            b=item.GetBoundingBox()
            return all(left<=x<=right and top<=y<=bottom for x,y in
                       (local(planner.api.VECTOR2I(x,y)) for x,y in
                        ((b.GetLeft(),b.GetTop()),(b.GetRight(),b.GetTop()),
                         (b.GetRight(),b.GetBottom()),(b.GetLeft(),b.GetBottom()))))
        inner=[p for p in pads if enclosed(p) and p.GetAttribute()!=planner.api.PAD_ATTRIB_NPTH]
        outer=[p for p in pads if p not in inner]
        inner_tracks=[t for t in tracks if enclosed(t)];outer_tracks=[t for t in tracks if t not in inner_tracks]
        inner_zones=[z for z in zones if enclosed(z)];outer_zones=[z for z in zones if z not in inner_zones]
    def candidate(path):
        result=planner._candidate(fp,pad,path,values,'Connector edge')
        result.clearance=local_margin
        return result
    def blocked(path,final=False):
        plan=candidate(path);plan.add_via=bool(values['add_vias']) if final else False
        if not final:plan.start_via=False
        if override=='':
            # Passing the original lists keeps the planner's ordered spatial
            # index active for every grid edge on a dense board.
            return planner._blocked(plan,accepted,pads,tracks,zones,outline,margin)
        # Rules cannot relax board edges, NPTH holes or objects outside the envelope.
        reason=planner._blocked(plan,accepted,inner,inner_tracks,inner_zones,outline,local_margin)
        if reason:return reason
        return planner._blocked(plan,[],outer,outer_tracks,outer_zones,outline,margin)
    if blocked([pad.GetPosition(),pad.GetPosition()]):raise ValueError('Pad launch cannot meet reviewed clearance.')
    direct=[(left,sy),(right,sy),(sx,top),(sx,bottom)] if side=='Nearest edge' else \
        [(targets[side],sy)] if side in ('Left','Right') else [(sx,targets[side])]
    for gx,gy in sorted(direct,key=lambda point:math.hypot(point[0]-sx,point[1]-sy)):
        path=[pad.GetPosition(),world(gx,gy)]
        if not blocked(path,True):
            plan=candidate(path);plan.connector_region=corners;plan.connector_boundary=source
            plan.local_clearance=override!='';return plan
    queue=[(distance(sx,sy),0,(0,0))];cost={(0,0):0};parents={};visited=set();started=time.monotonic()
    moves=((0,-1),(0,1),(-1,0),(1,0),(-1,-1),(-1,1),(1,-1),(1,1))
    def pos(key):return sx+key[0]*step,sy+key[1]*step
    def finish(key):
        points=[]
        while True:
            points.append(world(*pos(key)))
            if key not in parents:break
            key=parents[key]
        points.reverse()
        compact=[]
        for point in points:
            while len(compact)>1:
                a,b=compact[-2:];u=(b.x-a.x,b.y-a.y);v=(point.x-b.x,point.y-b.y)
                if u[0]*v[0]+u[1]*v[1]<=0 or abs(u[0]*v[1]-u[1]*v[0])>2*max(math.hypot(*u),math.hypot(*v)):break
                compact.pop()
            compact.append(point)
        return compact
    while queue:
        if len(visited)>=4096 or time.monotonic()-started>3:raise ValueError('Connector search budget reached; adjust layer, width, clearance, side or search step.')
        _,g,key=heapq.heappop(queue)
        if key in visited:continue
        visited.add(key);x,y=pos(key)
        if distance(x,y)<=step:
            goals=[(left,y),(right,y),(x,top),(x,bottom)] if side=='Nearest edge' else [(targets[side],y)] if side in ('Left','Right') else [(x,targets[side])]
            for gx,gy in sorted(goals,key=lambda p:math.hypot(p[0]-x,p[1]-y)):
                path=finish(key)+[world(gx,gy)]
                if not blocked(path,True):
                    plan=candidate(path);plan.connector_region=corners;plan.connector_boundary=source
                    plan.local_clearance=override!='';return plan
        for dx,dy in moves:
            nxt=(key[0]+dx,key[1]+dy);nx,ny=pos(nxt)
            if not left<nx<right or not top<ny<bottom or nxt in visited:continue
            ng=g+step*math.hypot(dx,dy)
            if ng>=cost.get(nxt,float('inf')):continue
            if blocked([world(x,y),world(nx,ny)]):continue
            cost[nxt]=ng;parents[nxt]=key;heapq.heappush(queue,(ng+distance(nx,ny),ng,nxt))
    raise ValueError('No connector-edge path fits the reviewed geometry; inspect obstacles or choose another side/layer.')
