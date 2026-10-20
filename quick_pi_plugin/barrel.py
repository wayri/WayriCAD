"""Axial area of circular and obround plated barrels, in millimetres.

The finished drill is a circle or capsule. Uniform outward plating of thickness
t adds perimeter*t + pi*t**2 of metal area (the parallel-body area identity).
This is a lumped axial conductor; it does not resolve wall current crowding.
"""
from __future__ import annotations
import math


def drill_dimensions(item):
    """Return validated finished X/Y drill dimensions; legacy drills are round."""
    values=item.get('drill_size_mm',[item.get('drill_mm')]*2)
    if not isinstance(values,(list,tuple)) or len(values)!=2:
        raise ValueError('Barrel drill_size_mm needs two positive dimensions.')
    if any(isinstance(v,bool) for v in values):
        raise ValueError('Barrel drill dimensions must be finite and positive.')
    try:x,y=map(float,values)
    except (TypeError,ValueError) as exc:
        raise ValueError('Barrel drill dimensions must be finite and positive.') from exc
    if not all(math.isfinite(v) and v>0 for v in (x,y)):
        raise ValueError('Barrel drill dimensions must be finite and positive.')
    shape=item.get('drill_shape','circle' if x==y else 'obround')
    if shape not in ('circle','obround') or (shape=='circle' and x!=y):
        raise ValueError('Only circular and obround plated drills are supported.')
    if 'drill_mm' in item and not math.isclose(float(item['drill_mm']),min(x,y),rel_tol=1e-9,abs_tol=1e-12):
        raise ValueError('Barrel minor diameter conflicts with drill dimensions.')
    return x,y


def barrel_area_mm2(item,plating_mm):
    """Return axial metal area for finished drill dimensions and outward plating."""
    x,y=drill_dimensions(item)
    if isinstance(plating_mm,bool):raise ValueError('Barrel plating must be finite and positive.')
    try:t=float(plating_mm)
    except (TypeError,ValueError) as exc:raise ValueError('Barrel plating must be finite and positive.') from exc
    if not math.isfinite(t) or t<=0:raise ValueError('Barrel plating must be finite and positive.')
    return (2*abs(x-y)+math.pi*min(x,y))*t+math.pi*t*t


def drill_wall_distance(point,item):
    """Signed distance from a board-XY point to a rotated capsule drill wall."""
    x,y=drill_dimensions(item)
    angle=-math.radians(float(item.get('drill_angle_deg',0.)))
    dx,dy=float(point[0])-float(item['x_mm']),float(point[1])-float(item['y_mm'])
    local_x=dx*math.cos(angle)+dy*math.sin(angle)
    local_y=-dx*math.sin(angle)+dy*math.cos(angle)
    if x<y:local_x,local_y=local_y,local_x
    return math.hypot(max(abs(local_x)-abs(x-y)/2,0.),local_y)-min(x,y)/2


def drill_contour(item,offset_mm=0.,*,arc_segments=48,circumscribed=False):
    """Display contour for the finished drill or its uniform outward offset.

    KiCad's positive pad angle rotates negatively in board XY. Inscribed outer
    contours and circumscribed void contours avoid painting unsolved void copper.
    Probe decisions use the exact wall-distance function, not this display mesh.
    """
    x,y=drill_dimensions(item);offset=float(offset_mm)
    if not math.isfinite(offset) or offset<0 or not isinstance(arc_segments,int) or arc_segments<4:
        raise ValueError('Drill contour needs a nonnegative finite offset and at least four arc segments.')
    radius=min(x,y)/2+offset;run=abs(x-y)/2
    if circumscribed:radius/=math.cos(math.pi/(2*arc_segments))
    angle=-math.radians(float(item.get('drill_angle_deg',0.)))
    result=[]
    for center,start in ((run,-math.pi/2),(-run,math.pi/2)):
        for index in range(arc_segments+1):
            phase=start+index*math.pi/arc_segments
            a,b=center+radius*math.cos(phase),radius*math.sin(phase)
            if x<y:a,b=b,a
            result.append([float(item['x_mm'])+a*math.cos(angle)-b*math.sin(angle),
                           float(item['y_mm'])+a*math.sin(angle)+b*math.cos(angle)])
    return result
