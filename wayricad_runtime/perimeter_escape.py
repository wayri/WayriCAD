"""Ordered perimeter escapes with straight launches and 45-degree pitch expansion."""
import math


def _basis(footprint, pad):
    rotation = -math.radians(float(footprint.GetOrientationDegrees()))
    position, center = pad.GetPosition(), footprint.GetPosition()
    dx, dy = position.x-center.x, position.y-center.y
    if math.hypot(dx, dy) < 1:
        if len(list(footprint.Pads())) != 1:
            return None
        # A single-pad test point has no package bank or exposed center pad.
        # Use its own long axis as the deterministic straight escape direction.
        single_angle = -math.radians(float(pad.GetOrientationDegrees()))
        if pad.GetSize().y > pad.GetSize().x:
            single_angle += math.pi/2
        dx,dy = math.cos(single_angle),math.sin(single_angle)
    size = pad.GetSize()
    if abs(size.x-size.y) > 1:
        angle = -math.radians(float(pad.GetOrientationDegrees()))
        if size.y > size.x:
            angle += math.pi/2
        if dx*math.cos(angle)+dy*math.sin(angle) < 0:
            angle += math.pi
    else:
        x = dx*math.cos(rotation)+dy*math.sin(rotation)
        y = -dx*math.sin(rotation)+dy*math.cos(rotation)
        angle = rotation + (0 if x >= 0 else math.pi) if abs(x) >= abs(y) else rotation + (math.pi/2 if y >= 0 else -math.pi/2)
    side = int(round((angle-rotation)/(math.pi/2))) % 4
    normal = rotation+side*math.pi/2
    if abs(math.sin(angle-normal)) > 1e-5:
        raise ValueError('Pitch expansion requires pads aligned with a package edge; choose a custom style for angled pads.')
    return side, (math.cos(normal), math.sin(normal)), (-math.sin(normal), math.cos(normal))


def path(footprint, pad, api, settings):
    basis = _basis(footprint, pad)
    if basis is None:
        raise ValueError('A center/exposed pad needs an explicit via-in-pad or custom rule.')
    side, normal, tangent = basis
    if settings['angle_mode'] != 'Pattern' or any(float(settings[k]) != 0 for k in ('angle_offset','offset_x','offset_y')):
        raise ValueError('Pitch expansion uses package-aligned 45-degree bends; clear direction/endpoint overrides.')
    def projection(point, axis):
        return point.x*axis[0]+point.y*axis[1]
    rows = []
    for candidate in footprint.Pads():
        if candidate.GetAttribute() != api.PAD_ATTRIB_SMD:
            continue
        candidate_basis = _basis(footprint, candidate)
        if candidate_basis is None or candidate_basis[0] != side:
            continue
        position = candidate.GetPosition()
        rows.append((projection(position,tangent), projection(position,normal), candidate))
    rows.sort(key=lambda row: (row[0],str(row[2].GetNumber())))
    if max(row[1] for row in rows)-min(row[1] for row in rows) > 2:
        raise ValueError('Multiple pad rows detected on this side; use a BGA/grid style or a separate explicit rule.')
    index = next(i for i,row in enumerate(rows) if str(row[2].m_Uuid.AsString()) == str(pad.m_Uuid.AsString()))
    gaps = [b[0]-a[0] for a,b in zip(rows,rows[1:])]
    if gaps and min(gaps) <= 2:
        raise ValueError('Overlapping or stacked perimeter pads need explicit routing.')
    native_pitch = max(gaps, default=0)
    minimum = api.FromMM(float(settings['width'])+float(settings['clearance']))+2
    if settings['add_vias']:
        minimum = max(minimum,api.FromMM(float(settings['via_diameter'])+float(settings['clearance']))+2)
    requested = api.FromMM(float(settings['spread_pitch']))
    pitch = max(native_pitch, minimum) if not requested else requested
    if len(rows)>1 and (pitch+2 < native_pitch or pitch < minimum):
        raise ValueError('Outer pitch must preserve pad ordering and fit track/via clearance; increase outer pitch or use 0 for automatic.')
    middle = (rows[0][0]+rows[-1][0])/2
    targets = [middle+(i-(len(rows)-1)/2)*pitch for i in range(len(rows))]
    shifts = [target-row[0] for target,row in zip(targets,rows)]
    # All pads first reach a common exterior line. Outer traces bend earlier;
    # inner traces stay straight longer, avoiding compressed diagonal spacing.
    edges = []
    for _,n,candidate in rows:
        size = candidate.GetSize()
        angle = -math.radians(float(candidate.GetOrientationDegrees()))
        nx,ny = normal
        half = (abs(nx*math.cos(angle)+ny*math.sin(angle))*size.x+
                abs(-nx*math.sin(angle)+ny*math.cos(angle))*size.y)/2
        edges.append(n+half)
    launch = api.FromMM(float(settings['launch_length']))
    base = max(edges)+launch
    diagonal_end = base+max(abs(value) for value in shifts)
    front = max(diagonal_end+launch, max(edges)+api.FromMM(float(settings['length'])))
    t,n,_ = rows[index]
    shift = shifts[index]
    coordinates = [(n,t),(diagonal_end-abs(shift),t),(diagonal_end,targets[index]),(front,targets[index])]
    points = []
    for outward,across in coordinates:
        point = api.VECTOR2I(round(normal[0]*outward+tangent[0]*across), round(normal[1]*outward+tangent[1]*across))
        if not points or point.x != points[-1].x or point.y != points[-1].y:
            points.append(point)
        while len(points)>2:
            a,b,c = points[-3:]
            ux,uy,vx,vy = b.x-a.x,b.y-a.y,c.x-b.x,c.y-b.y
            if ux*vx+uy*vy < 0 or abs(ux*vy-uy*vx) > 2*max(math.hypot(ux,uy),math.hypot(vx,vy)):
                break
            points.pop(-2)
    return points
