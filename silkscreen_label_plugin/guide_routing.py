"""Bounded guide routing; callers retain native full-stroke clearance checks."""


def dogleg_paths(start, end, obstacles, margin, limit=32):
    """Yield two-bend paths around local obstacle bounds in native distance units.

    These are candidates, not accepted routes. The native caller still checks
    board boundaries, courtyards, pads, text and the complete guide stroke.
    """
    if margin<0 or limit<1:
        raise ValueError('Guide margin must be nonnegative and limit positive.')
    ax,ay=start;bx,by=end
    xs={(ax+bx)//2};ys={(ay+by)//2}
    for left,top,right,bottom in obstacles:
        xs.update((left-margin-1,right+margin+1))
        ys.update((top-margin-1,bottom+margin+1))
    candidates=[]
    for x in xs:candidates.append((start,(x,ay),(x,by),end))
    for y in ys:candidates.append((start,(ax,y),(bx,y),end))
    unique=set()
    def length(path):
        return sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(path,path[1:]))
    for path in sorted(candidates,key=lambda p:(length(p),p)):
        path=tuple(point for i,point in enumerate(path) if i==0 or point!=path[i-1])
        if len(path)!=4 or len(set(path))!=4 or path in unique:continue
        unique.add(path)
        yield path
        if len(unique)>=limit:return


def visibility_path(start, end, obstacles, margin, segment_clear, *,
                    max_nodes=192, max_checks=12000):
    """Return a bounded mixed-angle route, or None when no route is found.

    Coordinates and margin use the caller's native distance units. Obstacle
    bounds supply detour vertices, not acceptance: ``segment_clear(a, b)`` must
    validate the full stroke, board outline and every native obstacle. Its
    exceptions propagate. Search prefers horizontal, vertical and 45-degree
    segments, while permitting arbitrary clear segments. Node/work exhaustion
    is a failed search, never permission to emit an unchecked segment.
    """
    import heapq
    import math

    if margin < 0 or max_nodes < 2 or max_checks < 1:
        raise ValueError('Guide margin must be nonnegative and budgets positive.')
    start=tuple(start);end=tuple(end)
    if start == end:
        return None
    boxes=sorted(set(tuple(box) for box in obstacles))
    candidates=set()
    for left,top,right,bottom in boxes:
        if left > right or top > bottom:
            raise ValueError('Guide obstacle bounds must be ordered.')
        left-=margin+1;top-=margin+1;right+=margin+1;bottom+=margin+1
        candidates.update(((left,top),(right,top),(right,bottom),(left,bottom)))
    # Endpoint bends let a clear route use 45-degree sections without needing
    # a dense grid. Obstacle corners still permit any number of mixed bends.
    anchors=sorted(candidates | {start,end})
    for origin in (start,end):
        for target in anchors:
            dx=target[0]-origin[0];dy=target[1]-origin[1]
            step=min(abs(dx),abs(dy))
            sx=1 if dx>=0 else -1;sy=1 if dy>=0 else -1
            candidates.add((origin[0]+sx*step,origin[1]+sy*step))
            candidates.add((target[0]-sx*step,target[1]-sy*step))
    candidates.difference_update((start,end))
    # Nearby-to-corridor ranking keeps limited graphs useful for distant labels
    # and does not depend on native item iteration order.
    def rank(point):
        return (math.dist(start,point)+math.dist(point,end),point)
    points=[start,end]+sorted(candidates,key=rank)[:max_nodes-2]
    distances={0:0.0};previous={};queue=[(0.0,0)];settled=set();checks=0
    visibility={}
    while queue:
        distance,index=heapq.heappop(queue)
        if index in settled:
            continue
        if index == 1:
            route=[end]
            while index:
                index=previous[index];route.append(points[index])
            return tuple(reversed(route))
        settled.add(index)
        for neighbor,point in enumerate(points):
            if neighbor in settled or neighbor == index:
                continue
            key=tuple(sorted((index,neighbor)))
            if key not in visibility:
                if checks >= max_checks:
                    return None
                checks+=1
                visibility[key]=bool(segment_clear(points[index],point))
            if not visibility[key]:
                continue
            dx=abs(point[0]-points[index][0]);dy=abs(point[1]-points[index][1])
            penalty=1.0 if not dx or not dy or dx==dy else 1.02
            candidate=distance+math.hypot(dx,dy)*penalty
            if candidate < distances.get(neighbor,float('inf')):
                distances[neighbor]=candidate;previous[neighbor]=index
                heapq.heappush(queue,(candidate,neighbor))
    return None


def visibility_path_between(starts, ends, obstacles, margin, segment_clear, *,
                            max_nodes=256, max_checks=16000):
    """Find one checked route between any accessible label/body exits.

    Keep actual obstacle corners instead of supplemental angle vertices. One
    multi-source graph shares visibility checks across all endpoint choices,
    avoiding a separate expensive search for each pair. Bounds only generate
    candidates; the caller's complete stroke checker remains authoritative.
    """
    import heapq
    import math

    starts=sorted(set(tuple(p) for p in starts));ends=sorted(set(tuple(p) for p in ends))
    anchors=list(dict.fromkeys(starts+ends))
    if margin<0 or max_nodes<max(2,len(anchors)) or max_checks<1:
        raise ValueError('Guide margin must be nonnegative and budgets positive.')
    if not starts or not ends:return None
    boxes=sorted(set(tuple(box) for box in obstacles),
                 key=lambda b:(-(b[2]-b[0])*(b[3]-b[1]),b))
    outer=[]
    for left,top,right,bottom in boxes:
        if left>right or top>bottom:raise ValueError('Guide obstacle bounds must be ordered.')
        # Corners inside a larger reserved rectangle cannot aid routing.
        # Native acceptance still checks every original obstacle.
        if any(a<=left and b<=top and c>=right and d>=bottom for a,b,c,d in outer):continue
        outer.append((left,top,right,bottom))
    corners=set()
    for left,top,right,bottom in outer:
        left-=margin+1;top-=margin+1;right+=margin+1;bottom+=margin+1
        corners.update(((left,top),(right,top),(right,bottom),(left,bottom)))
    corners.difference_update(anchors)
    slots=max_nodes-len(anchors)
    if len(corners)>slots:
        def rank(point):return (min(math.dist(p,point) for p in starts)+
                                min(math.dist(point,p) for p in ends),point)
        corners=sorted(corners,key=rank)[:slots]
    points=anchors+sorted(corners)
    goals={points.index(point) for point in ends}
    distances={points.index(point):0. for point in starts}
    previous={index:None for index in distances}
    queue=[(0.,index) for index in distances];heapq.heapify(queue)
    settled=set();visibility={};checks=0
    while queue:
        distance,index=heapq.heappop(queue)
        if index in settled:continue
        if index in goals and previous[index] is not None:
            route=[]
            while index is not None:
                route.append(points[index]);index=previous[index]
            return tuple(reversed(route)) if len(route)>1 else None
        settled.add(index)
        for neighbor,point in enumerate(points):
            if neighbor in settled or neighbor==index:continue
            key=tuple(sorted((index,neighbor)))
            if key not in visibility:
                if checks>=max_checks:return None
                checks+=1;visibility[key]=bool(segment_clear(points[index],point))
            if not visibility[key]:continue
            dx=abs(point[0]-points[index][0]);dy=abs(point[1]-points[index][1])
            penalty=1. if not dx or not dy or dx==dy else 1.02
            candidate=distance+math.hypot(dx,dy)*penalty
            if candidate<distances.get(neighbor,float('inf')):
                distances[neighbor]=candidate;previous[neighbor]=index
                heapq.heappush(queue,(candidate,neighbor))
    return None
