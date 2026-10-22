"""Conservative centering of existing straight-track pad/via contacts.

This is not a gap router: a track's existing end capsule must already touch
one unambiguous native copper shape on the same net and copper layer.
"""
import math
import time
from collections import defaultdict


def _routing_guard(points,api):
    """Reuse refinement's repeated-excursion test without proposing cleanup."""
    from .geometry import MAX_VERTICES,_collapse,_simple,_sub,_dot,_cross,_octilinear,_single_excursions
    if len(points)>MAX_VERTICES or len(set(points))!=len(points):return False
    values=[(api.ToMM(x),api.ToMM(y)) for x,y in points]
    if any(_cross(_sub(b,a),_sub(c,b))==0 and _dot(_sub(b,a),_sub(c,b))<0
           for a,b,c in zip(values,values[1:],values[2:])):return False
    collapsed=_collapse(values)
    if not _simple(collapsed):return False
    for start in range(len(collapsed)-4):
        for size in range(5,min(9,len(collapsed)-start)+1):
            window=collapsed[start:start+size];chord=_sub(window[-1],window[0])
            if (_octilinear(window[0],window[-1])
                    and all(_dot(_sub(b,a),chord)>=0 for a,b in zip(window,window[1:]))
                    and not _single_excursions(window,[window[0],window[-1]])):return False
    return True


def _shape(item,layer,api):
    return item.GetEffectiveShape(layer)


def _center(item,layer,api):
    """Return a proven copper anchor; unusual/offset pad stacks stay untouched."""
    if item.IsLocked() or item.GetParentGroup() is not None:return None
    if isinstance(item,api.PAD):
        parent=item.GetParent()
        if parent.IsLocked() or parent.GetParentGroup() is not None:return None
        if item.GetShape(layer) not in (api.PAD_SHAPE_CIRCLE,api.PAD_SHAPE_RECT,
                                       api.PAD_SHAPE_OVAL,api.PAD_SHAPE_ROUNDRECT):return None
        offset=item.GetOffset(layer)
        if offset.x or offset.y:return None
    position=item.GetPosition()
    return position.x,position.y


def repairs_via_finding(finding,changes,board,api,maximum):
    """Recognize only the native warning repaired by an exact via-centre move.

    The caller must additionally prove this finding disappeared in the native
    candidate report. Other warnings on affected routing remain blockers.
    """
    from .refiner import uid,point
    if finding.get('type')!='track_not_centered_on_via':return False
    identities={item.get('uuid') for item in finding.get('items',[])}
    if len(identities)!=2 or len(finding.get('items',[]))!=2:return False
    vias={uid(item):item for item in board.GetTracks() if isinstance(item,api.PCB_VIA)}
    for change in changes:
        if len(change.originals)!=1 or len(change.before)!=2 or len(change.after)!=2:continue
        track=change.originals[0];key=uid(track)
        if key not in identities or type(track) is not api.PCB_TRACK:continue
        if list(map(tuple,change.before))!=[point(track),point(track,True)]:continue
        via=vias.get(next(iter(identities-{key})))
        if via is None or via.GetNetCode()!=track.GetNetCode() or not via.IsOnLayer(track.GetLayer()):continue
        if not via.FlashLayer(track.GetLayer()) or _center(via,track.GetLayer(),api) is None:continue
        center=tuple(via.GetPosition())
        for before,after in zip(change.before,change.after):
            shift=math.dist(before,after)
            if (tuple(after)==center and 0<shift<=api.FromMM(maximum)
                    and _shape(via,track.GetLayer(),api).Collide(api.VECTOR2I(*before),(track.GetWidth()+1)//2)):
                return True
    return False


def propose_contacts(board,api,result,eligible,anchors,tracks,progress=None):
    """Append endpoint-only Change objects, without writing native geometry.

    Shared scope/protection checks are performed by refiner.propose. Junctions,
    interior contacts and ambiguous terminal contacts are deliberately skipped.
    Native detached connectivity and DRC remain mandatory before Apply.
    """
    from .refiner import Change,uid,point
    maximum=api.FromMM(result.settings['max_center_shift'])
    deadline=time.monotonic()+30
    adjacency=defaultdict(list);guarded={}
    for item in board.GetTracks():
        if isinstance(item,api.PCB_VIA):continue
        for end in (False,True):adjacency[(item.GetNetCode(),item.GetLayer(),point(item,end))].append(item)
    def chain_guard(first):
        if uid(first) in guarded:return guarded[uid(first)]
        from .geometry import MAX_VERTICES
        chain=[first];points=[point(first),point(first,True)];seen={uid(first)};safe=True
        for front in (True,False):
            while safe:
                current=chain[0] if front else chain[-1];position=points[0] if front else points[-1]
                neighbours=adjacency[(first.GetNetCode(),first.GetLayer(),position)]
                if len(neighbours)==1:break
                if len(neighbours)!=2:safe=False;break
                other=next(item for item in neighbours if uid(item)!=uid(current))
                if uid(other) in seen or type(other) is not api.PCB_TRACK:
                    safe=False;break
                seen.add(uid(other))
                if len(seen)>=MAX_VERTICES or time.monotonic()>deadline:safe=False;break
                next_point=point(other,True) if point(other)==position else point(other)
                if front:chain.insert(0,other);points.insert(0,next_point)
                else:chain.append(other);points.append(next_point)
        safe=safe and _routing_guard(points,api)
        for item in chain:guarded[uid(item)]=safe
        return safe
    for index,track in enumerate(sorted(eligible,key=uid)):
        if progress and progress(f'Inspecting contacts {index+1}/{len(eligible)}') is False:
            raise ValueError('Preview cancelled; board unchanged.')
        if time.monotonic()>deadline:
            result.skipped.append(('Search budget','30-second contact inspection budget reached; remaining routing unchanged.'));break
        before=[point(track),point(track,True)];after=list(before)
        width=track.GetWidth();net=track.GetNetCode();layer=track.GetLayer()
        if before[0]==before[1]:continue
        if not chain_guard(track):
            result.skipped.append((track.GetNetname(),'Tuning, loop, arc, branch or bounded chain inspection preserved'));continue
        radius=(width+1)//2
        notices=set()
        for end,position in enumerate(before):
            vector=api.VECTOR2I(*position)
            bounds=(position[0]-radius,position[1]-radius,position[0]+radius,position[1]+radius)
            contacts=[item for item in anchors.query(net,layer,bounds)
                      if item.IsOnLayer(layer) and item.FlashLayer(layer)
                      and _shape(item,layer,api).Collide(vector,radius)]
            if not contacts:continue
            if len(contacts)!=1:
                notices.add('Ambiguous overlapping pad/via contacts preserved');continue
            target=contacts[0];center=_center(target,layer,api)
            if center is None:
                notices.add('Locked, grouped, offset or unsupported terminal shape preserved');continue
            distance=math.dist(position,center)
            if distance<1:continue
            if distance>maximum:
                notices.add('Contact offset exceeds maximum center shift');continue
            if center==before[1-end]:
                notices.add('Zero-length replacement preserved');continue
            # A shared endpoint is a topology anchor, even if another segment
            # is unselected or curved. Do not detach a branch to center it.
            neighbours=tracks.query(net,layer,bounds)
            if any(uid(other)!=uid(track) and not isinstance(other,api.PCB_VIA)
                   and other.IsOnLayer(layer) and _shape(other,layer,api).Collide(vector,radius)
                   for other in neighbours):
                notices.add('Shared track/arc junction preserved');continue
            after[end]=center
        if after==before:
            result.skipped.extend((track.GetNetname(),notice) for notice in sorted(notices));continue
        if after[0]==after[1]:
            result.skipped.append((track.GetNetname(),'Zero-length replacement preserved'));continue
        # Preserve mid-segment contacts and reject any new lateral junction.
        # Only copper inside unchanged endpoint capsules may meet other tracks.
        unsafe=False
        all_bounds=(min(p[0] for p in before+after)-radius,min(p[1] for p in before+after)-radius,
                    max(p[0] for p in before+after)+radius,max(p[1] for p in before+after)+radius)
        for other in tracks.query(net,layer,all_bounds):
            if uid(other)==uid(track) or isinstance(other,api.PCB_VIA) or not other.IsOnLayer(layer):continue
            shape=_shape(other,layer,api)
            for segment in (before,after):
                start,finish=segment;dx,dy=finish[0]-start[0],finish[1]-start[1]
                length=math.hypot(dx,dy)
                trim=(width+other.GetWidth())/2+2
                head=trim if before[0]==after[0] else 0
                tail=trim if before[1]==after[1] else 0
                if length<=head+tail:
                    unsafe=True;break
                a=api.VECTOR2I(round(start[0]+dx*head/length),round(start[1]+dy*head/length))
                b=api.VECTOR2I(round(finish[0]-dx*tail/length),round(finish[1]-dy*tail/length))
                if shape.Collide(api.SEG(a,b),radius):unsafe=True;break
            if unsafe:break
        # Pad/via interior contacts are immutable too. The endpoint target
        # itself is allowed, but a third terminal must not be swept or detached.
        for terminal in anchors.query(net,layer,all_bounds):
            if not terminal.IsOnLayer(layer) or not terminal.FlashLayer(layer):continue
            shape=_shape(terminal,layer,api)
            endpoint_contact=any(shape.Collide(api.VECTOR2I(*p),radius) for p in before)
            if endpoint_contact:continue
            if any(shape.Collide(api.SEG(api.VECTOR2I(*a),api.VECTOR2I(*b)),radius)
                   for a,b in (before,after)):
                unsafe=True;break
        if unsafe:
            result.skipped.append((track.GetNetname(),'Interior or new lateral copper contact preserved'));continue
        result.changes.append(Change([track],before,after,track.GetNetname(),layer,width))
