"""Footprint-owned rule areas, staged in native board syntax.
Only exact straight-line courtyard loops are copied. Native KiCad owns transforms
once applied; no timer, fake move observer, or background board rewrite is used.
"""
import hashlib, math, uuid
from .board import BoardContext, _point, _equal, _signed_area, _intersect, _normal
from .sexpr import scalar, quote


def local_courtyard(context,reference):
    fp=context.footprint(reference)
    side='B' if fp.layer=='B.Cu' else 'F'
    accepted=(side+'.CrtYd',side+'.Courtyard')
    edges=[];polygons=[]
    for n in fp.node.children:
        if not n.is_list or scalar(n.first('layer')) not in accepted:continue
        h=n.head()
        if h in ('fp_text','property'):continue
        if h=='fp_line':edges.append((_point(n.first('start')),_point(n.first('end'))))
        elif h=='fp_rect':
            a=_point(n.first('start'));b=_point(n.first('end'));polygons.append([a,(b[0],a[1]),b,(a[0],b[1])])
        elif h=='fp_poly':
            pts=n.first('pts');polygons.append([_point(p) for p in pts.find('xy')] if pts else [])
        else:raise ValueError('Exact attached-area copying does not support '+h+'. Use an existing native rule area; no bounding-box substitute is made.')
    if polygons and edges or len(polygons)>1:raise ValueError('Multiple/mixed courtyard loops need a native rule area')
    if polygons:poly=polygons[0]
    elif edges:
        a,b=edges.pop(0);poly=[a,b]
        while edges:
            matches=[(i,y if _equal(x,poly[-1]) else x) for i,(x,y) in enumerate(edges) if _equal(x,poly[-1]) or _equal(y,poly[-1])]
            if len(matches)!=1:raise ValueError('Open, branched or multiple courtyard loops')
            i,p=matches[0];edges.pop(i);poly.append(p)
        if not _equal(poly[-1],poly[0]):raise ValueError('Open courtyard')
    else:raise ValueError('No supported courtyard on the footprint side')
    if len(poly)>1 and _equal(poly[-1],poly[0]):poly=poly[:-1]
    if len(poly)<3 or abs(_signed_area(poly))<1e-10:raise ValueError('Degenerate courtyard')
    for i,a in enumerate(poly):
        b=poly[(i+1)%len(poly)]
        if _equal(a,b):raise ValueError('Zero-length courtyard edge')
        for j in range(i+1,len(poly)):
            if j==i+1 or (i==0 and j==len(poly)-1):continue
            if _intersect(a,b,poly[j],poly[(j+1)%len(poly)]):raise ValueError('Courtyard self-intersects')
    return poly


def world_polygon(fp,poly):
    a=math.radians(fp.rotation);cs,sn=math.cos(a),math.sin(a)
    # Board-file child coordinates already describe that footprint's current side.
    return [(fp.x+x*cs+y*sn,fp.y-x*sn+y*cs) for x,y in poly]


def attached_areas(context):
    out=[]
    for fp in context.footprints:
        for n in fp.node.find('zone'):
            if n.first('keepout') is None:continue
            name=scalar(n.first('name'))
            if name:out.append(dict(name=name,rule_area=True,node=n,owner=fp.reference,owner_uuid=fp.uid,footprint=fp))
    return out


def all_areas(context):return context.areas+attached_areas(context)


def area_polygon(area):
    polys=area['node'].find('polygon')
    if len(polys)!=1:raise ValueError('Preview requires one polygon without holes')
    pts=polys[0].first('pts')
    if not pts or any(p.head()!='xy' for p in pts.children[1:]):raise ValueError('Curved area requires native geometry')
    poly=[_point(p) for p in pts.find('xy')]
    if 'footprint' in area:poly=world_polygon(area['footprint'],poly)
    return poly


def _local_polygon(area):
    n=area['node'].first('polygon');pts=n.first('pts') if n else None
    if not pts:return []
    return [_point(p) for p in pts.find('xy')]


def equivalent_outline(a,b,tol=2e-7):
    """Order- and winding-independent; footprint flips are reflected natively.
    Used on the current saved courtyard and area, never on bounding boxes.
    """
    if len(a)!=len(b):return False
    for seq in (b,list(reversed(b))):
        for start in range(len(seq)):
            if all(math.hypot(p[0]-seq[(start+i)%len(seq)][0],p[1]-seq[(start+i)%len(seq)][1])<=tol for i,p in enumerate(a)):return True
    return False


def stage_attached_area(context,reference,name='',layers=()):
    fp=context.footprint(reference)
    if not fp.uid:raise ValueError('Footprint UUID is required for a persistent component binding')
    name=name.strip() or 'CS_'+reference+'_'+fp.uid.replace('-','')[:8]+'_ESCAPE'
    if any(a['name']==name for a in all_areas(context)):raise ValueError('Rule-area name must be unique across board and footprint areas')
    if any(ch in name for ch in '\r\n\x00'):raise ValueError('Area name must be single-line')
    layers=tuple(layers) or (fp.layer,)
    if any(not l.endswith('.Cu') or (context.layers and l not in context.layers) for l in layers):raise ValueError('Select enabled copper layers')
    poly=local_courtyard(context,reference);uid=str(uuid.uuid4())
    ls='(layer '+quote(layers[0])+')' if len(layers)==1 else '(layers '+' '.join(quote(l) for l in layers)+')'
    # Stored inside the footprint in its local coordinate system. It is a native
    # rule area with all base keepout prohibitions disabled; custom rules do the work.
    zone='\n    (zone (net 0) (net_name "") '+ls+'\n'
    zone+='      (uuid '+quote(uid)+') (name '+quote(name)+')\n'
    zone+='      (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.01)\n'
    zone+='      (keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour allowed) (footprints allowed))\n'
    zone+='      (fill (thermal_gap 0.3) (thermal_bridge_width 0.3))\n'
    zone+='      (polygon (pts '+' '.join(f'(xy {x:.9f} {y:.9f})' for x,y in poly)+'))\n    )\n'
    text=context.text[:fp.node.end-1]+zone+context.text[fp.node.end-1:]
    guard=dict(mode='footprint-owned-linear-courtyard',reference=reference,owner_uuid=fp.uid,name=name,area_uuid=uid,layers=list(layers),owner_layer=fp.layer,rule_names=[])
    return text,guard


def check_attached_guard(context,guard):
    fps=[f for f in context.footprints if f.uid==guard.get('owner_uuid')]
    if len(fps)!=1:return False,'Attached-area owner is missing or ambiguous after a footprint replacement'
    fp=fps[0];matches=[a for a in all_areas(context) if a['name']==guard['name']]
    if len(matches)!=1:return False,'Attached area missing or duplicated (for example, after copying the footprint)'
    area=matches[0]
    if area.get('owner_uuid')!=fp.uid or scalar(area['node'].first('uuid'))!=guard['area_uuid']:
        return False,'Attached area identity or parent changed'
    n=area['node'];ls=n.first('layers');actual=set(ls.atoms()[1:] if ls else [scalar(n.first('layer'))])
    expected=set(guard.get('layers',[]))
    if guard.get('owner_layer') and fp.layer!=guard['owner_layer']:
        expected={('B.Cu' if l=='F.Cu' else 'F.Cu' if l=='B.Cu' else l) for l in expected}
    if actual!=expected:return False,'Attached-area layers changed independently of the footprint; review and recreate it'
    keep=n.first('keepout')
    if not keep or any(scalar(keep.first(k))!='allowed' for k in ('tracks','vias','pads','copperpour','footprints')):
        return False,'Managed area keepout settings changed; this can prohibit routing independently of the custom rules'
    try:
        if not equivalent_outline(local_courtyard(context,fp.reference),_local_polygon(area)):
            return False,'Courtyard outline changed without updating the attached area; rebuild it'
    except ValueError as e:return False,str(e)
    return True,'Native footprint-owned area; position/rotation are not frozen. Validate native move/flip behavior on your KiCad build.'


def rebuild_attached_area(context,guard):
    fps=[f for f in context.footprints if f.uid==guard.get('owner_uuid')]
    if len(fps)!=1:raise ValueError('Cannot find the original footprint UUID')
    fp=fps[0]
    areas=[a for a in attached_areas(context) if a.get('owner_uuid')==fp.uid and scalar(a['node'].first('uuid'))==guard['area_uuid']]
    if len(areas)!=1:raise ValueError('Managed attached area identity changed; recreate it explicitly')
    area=areas[0];node=area['node']
    ls=node.first('layers');layers=tuple(ls.atoms()[1:]) if ls else (scalar(node.first('layer')),)
    text=context.text[:node.start]+context.text[node.end:]
    text,new=stage_attached_area(BoardContext.load(text),fp.reference,guard['name'],layers)
    new['rule_names']=guard.get('rule_names',[])[:]
    return text,new
