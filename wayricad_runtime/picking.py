"""Dependency-free geometric picking in scene coordinates."""
import math


def segment_distance(point, start, end):
    """Return Euclidean point-to-segment distance in the input coordinate units."""
    delta=[b-a for a,b in zip(start,end)]
    length=sum(value*value for value in delta)
    fraction=max(0.,min(1.,sum((p-a)*d for p,a,d in zip(point,start,delta))/length)) if length else 0.
    return math.sqrt(sum((p-a-fraction*d)**2 for p,a,d in zip(point,start,delta)))


def triangle_hit(origin, direction, vertices):
    """Intersect a forward ray with a triangle; return distance or None."""
    a,b,c=vertices
    sub=lambda u,v:[x-y for x,y in zip(u,v)]
    dot=lambda u,v:sum(x*y for x,y in zip(u,v))
    cross=lambda u,v:[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    u,v=sub(b,a),sub(c,a);p=cross(direction,v);det=dot(u,p)
    if abs(det)<1e-12:return None
    t=sub(origin,a);x=dot(t,p)/det
    if x<0 or x>1:return None
    q=cross(t,u);y=dot(direction,q)/det
    if y<0 or x+y>1:return None
    distance=dot(v,q)/det
    return distance if distance>=0 else None


def ray_box(origin, direction, bounds):
    """Return whether a forward ray intersects an axis-aligned bounding box."""
    near,far=0.,math.inf
    for index,(position,delta) in enumerate(zip(origin,direction)):
        low,high=bounds[index],bounds[index+3]
        if abs(delta)<1e-15:
            if not low<=position<=high:return False
        else:
            a,b=sorted(((low-position)/delta,(high-position)/delta))
            near=max(near,a);far=min(far,b)
            if near>far:return False
    return True


def pick_meshes(origin, direction, bodies, accept_hit=None):
    """Pick the closest exact triangle; optionally reject clipped surface hits.

    accept_hit receives scene coordinates and is applied to every intersection,
    so a clipped front face cannot hide a retained face farther along the ray.
    """
    nearest=None;distance=math.inf
    for body in bodies:
        mesh=body.get('mesh')
        if not mesh or not ray_box(origin,direction,body['bounds']):continue
        for face in mesh['faces']:
            value=triangle_hit(origin,direction,[mesh['vertices'][i] for i in face])
            if value is not None and value<distance:
                position=[a+value*d for a,d in zip(origin,direction)]
                if accept_hit is not None and not accept_hit(position):continue
                distance=value;nearest={'reference':body['ref'],'position':position,'distance':value}
    return nearest
