"""Read saved board context and stage a conservative linear-courtyard rule area.
Never mutates a live pcbnew board. Geometry support is deliberately fail-closed.
"""
from dataclasses import dataclass, field
import hashlib, math, re, uuid
from .sexpr import parse, scalar, quote

@dataclass
class Footprint:
    reference: str
    value: str = ''
    library: str = ''
    layer: str = ''
    x: float = 0
    y: float = 0
    rotation: float = 0
    uid: str = ''
    node: object = None

@dataclass
class BoardContext:
    text: str = ''
    footprints: list = field(default_factory=list)
    areas: list = field(default_factory=list)
    nets: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    root: object = None
    @classmethod
    def load(cls,text):
        roots=parse(text)
        if len(roots)!=1 or roots[0].head()!='kicad_pcb':raise ValueError('Not a KiCad board')
        root=roots[0]; c=cls(text=text,root=root)
        for n in root.children:
            h=n.head()
            if h=='footprint':
                at=n.first('at'); av=at.atoms()[1:] if at else []
                props={x.children[1].value:x.children[2].value for x in n.find('property') if len(x.children)>=3}
                # Reference/value fallback for older board syntax.
                for x in n.find('fp_text'):
                    if len(x.children)>2:props.setdefault(x.children[1].value.capitalize(),x.children[2].value)
                c.footprints.append(Footprint(props.get('Reference','?'),props.get('Value',''),scalar(n),scalar(n.first('layer')),
                    float(av[0]) if av else 0,float(av[1]) if len(av)>1 else 0,float(av[2]) if len(av)>2 else 0,
                    scalar(n.first('uuid')),n))
            elif h=='zone':
                name=scalar(n.first('name'))
                if name:c.areas.append({'name':name,'rule_area':n.first('keepout') is not None,'node':n})
            elif h=='net' and len(n.children)>2:c.nets.append(n.children[2].value)
            elif h=='layers':
                c.layers=[x.children[1].value for x in n.children[1:] if x.is_list and len(x.children)>1]
            elif h=='group':c.groups.append(scalar(n))
        # KiCad 10 can save the net name directly on each pad/track without
        # emitting a top-level (net ID "name") table. These are still real
        # board nets and must remain selectable for exact-net routing profiles.
        seen_nets=set(c.nets)
        for owner in root.children:
            sources = owner.find('pad') if owner.head()=='footprint' else [owner] if owner.head() in ('segment','arc','via','zone') else []
            for source in sources:
                net = source.first('net')
                if net and len(net.children)==2 and text[net.children[1].start] in ('"', "'"):
                    name=net.children[1].value
                    if name and name not in seen_nets:
                        c.nets.append(name);seen_nets.add(name)
        c.footprints.sort(key=lambda x: natural_key(x.reference))
        return c
    def footprint(self,reference):
        matches=[f for f in self.footprints if f.reference==reference]
        if len(matches)!=1:raise ValueError(f'Expected one footprint {reference!r}; found {len(matches)}')
        return matches[0]
    def fingerprint(self,reference):
        f=self.footprint(reference)
        pieces=[f.reference,f.layer,str(f.x),str(f.y),str(f.rotation),f.uid]
        for n in f.node.children:
            if n.is_list and scalar(n.first('layer')) in ('F.CrtYd','B.CrtYd','F.Courtyard','B.Courtyard'):
                pieces.append(repr(_normal(n)))
        return hashlib.sha256('\n'.join(pieces).encode()).hexdigest()

    def area_fingerprint(self,name):
        matches=[a for a in self.areas if a['name']==name]
        if len(matches)!=1:raise ValueError('Area is missing or name is ambiguous: '+name)
        a=matches[0];n=a['node']
        relevant=[x for x in n.children if x.is_list and x.head() in ('polygon','layer','layers','keepout','name')]
        return hashlib.sha256(repr([_normal(x) for x in relevant]).encode()).hexdigest()


def _normal(node):
    if node.is_list:return tuple(_normal(x) for x in node.children)
    try:
        if re.fullmatch(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?',node.value):return float(node.value)
    except ValueError:pass
    return node.value

def natural_key(s):return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',s)]

def _point(n):
    if n is None or len(n.children)<3:raise ValueError('Missing courtyard coordinate')
    return (float(n.children[1].value),float(n.children[2].value))

def _equal(a,b,tol=1e-6):return math.hypot(a[0]-b[0],a[1]-b[1])<=tol

def _signed_area(poly):return sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(poly,poly[1:]+poly[:1]))/2

def _cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def _intersect(a,b,c,d):
    # Includes collinear overlap: malformed contours must not be quietly accepted.
    eps=1e-10
    if max(a[0],b[0])+eps<min(c[0],d[0]) or max(c[0],d[0])+eps<min(a[0],b[0]):return False
    if max(a[1],b[1])+eps<min(c[1],d[1]) or max(c[1],d[1])+eps<min(a[1],b[1]):return False
    return _cross(a,b,c)*_cross(a,b,d)<=eps and _cross(c,d,a)*_cross(c,d,b)<=eps

def courtyard_polygon(context,reference):
    """One simple, straight-line FRONT courtyard; centreline boundary, not a bbox.
    Back-side, arcs/circles, holes and multiple islands intentionally require a
    user-drawn native area. A manufacturing clearance offset is never invented.
    """
    f=context.footprint(reference)
    if f.layer!='F.Cu':raise ValueError('Automatic courtyard copying currently supports front-side footprints only. Use a native named rule area for back-side parts.')
    edges=[]; polygons=[]
    for n in f.node.children:
        if not n.is_list or scalar(n.first('layer')) not in ('F.CrtYd','F.Courtyard'):continue
        h=n.head()
        if h in ('fp_text','property'):continue
        if h=='fp_line':edges.append((_point(n.first('start')),_point(n.first('end'))))
        elif h=='fp_rect':
            a=_point(n.first('start'));b=_point(n.first('end'))
            polygons.append([a,(b[0],a[1]),b,(a[0],b[1])])
        elif h=='fp_poly':
            pts=n.first('pts');polygons.append([_point(p) for p in pts.find('xy')] if pts else [])
        else:raise ValueError(f'Courtyard contains {h}; only lines, rectangles, and simple polygons are supported. Draw an exact native rule area instead.')
    if polygons and edges:raise ValueError('Mixed/multiple courtyard contours are not automatically copied')
    if len(polygons)>1:raise ValueError('Multiple courtyard contours are not automatically copied')
    if polygons:poly=polygons[0]
    elif edges:
        a,b=edges.pop(0);poly=[a,b]
        while edges:
            matching=[(i,y if _equal(x,poly[-1]) else x) for i,(x,y) in enumerate(edges) if _equal(x,poly[-1]) or _equal(y,poly[-1])]
            if len(matching)!=1:raise ValueError('Courtyard is open, branched, duplicated, or has multiple loops')
            i,p=matching[0];edges.pop(i);poly.append(p)
        if not _equal(poly[-1],poly[0]):raise ValueError('Courtyard is not closed')
    else:raise ValueError('No supported front courtyard was found')
    if len(poly)>1 and _equal(poly[-1],poly[0]):poly=poly[:-1]
    if len(poly)<3 or abs(_signed_area(poly))<1e-10:raise ValueError('Degenerate courtyard')
    for i,a in enumerate(poly):
        b=poly[(i+1)%len(poly)]
        if _equal(a,b):raise ValueError('Courtyard contains a zero-length edge')
        for j in range(i+1,len(poly)):
            if j==i+1 or (i==0 and j==len(poly)-1):continue
            if _intersect(a,b,poly[j],poly[(j+1)%len(poly)]):raise ValueError('Courtyard self-intersects')
    # KiCad board coordinates are +Y down; positive footprint angles are CCW.
    rad=math.radians(f.rotation);cs=math.cos(rad);sn=math.sin(rad)
    return [(f.x+x*cs+y*sn,f.y-x*sn+y*cs) for x,y in poly]


def stage_courtyard_area(context,reference,name,layers=('F.Cu',),area_uuid=None):
    if not name.strip():raise ValueError('Area name is required')
    if any(a['name']==name for a in context.areas):raise ValueError('Area name already exists; do not overwrite unrelated area geometry')
    allowed={'F.Cu','B.Cu'}|{f'In{i}.Cu' for i in range(1,31)}
    if not layers or any(x not in allowed for x in layers):raise ValueError('Choose explicit copper layers')
    if context.layers and any(x not in context.layers for x in layers):raise ValueError('Area includes a layer not enabled in this board')
    polygon=courtyard_polygon(context,reference)
    layer_text='(layer '+quote(layers[0])+')' if len(layers)==1 else '(layers '+' '.join(quote(x) for x in layers)+')'
    area='\n  (zone (net 0) (net_name "") '+layer_text+'\n'
    area_uuid=area_uuid or str(uuid.uuid4())
    area+='    (uuid '+quote(area_uuid)+') (name '+quote(name)+')\n'
    area+='    (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.01)\n'
    area+='    (keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour allowed) (footprints allowed))\n'
    area+='    (fill (thermal_gap 0.3) (thermal_bridge_width 0.3))\n'
    area+='    (polygon (pts '+' '.join(f'(xy {x:.9f} {y:.9f})' for x,y in polygon)+'))\n  )\n'
    text=context.text[:context.root.end-1]+area+context.text[context.root.end-1:]
    guard={'reference':reference,'name':name,'fingerprint':context.fingerprint(reference),'layers':list(layers),
           'rule_names':[],'polygon':polygon,'mode':'front-linear-courtyard-snapshot','area_uuid':area_uuid,
           'area_fingerprint':BoardContext.load(text).area_fingerprint(name)}
    return text,guard


def refresh_copied_area(context,guard):
    """Explicit rebuild of one previously managed area; never guesses a new owner."""
    matches=[a for a in context.areas if a['name']==guard['name']]
    if len(matches)!=1:raise ValueError('Managed area missing/ambiguous; recreate it explicitly')
    node=matches[0]['node'];uid=scalar(node.first('uuid'))
    if guard.get('area_uuid') and uid!=guard['area_uuid']:
        raise ValueError('Area identity changed; refusing to replace another area with the same name')
    if not matches[0]['rule_area']:raise ValueError('Area is no longer a keepout/rule area')
    without=context.text[:node.start]+context.text[node.end:]
    text,new=stage_courtyard_area(BoardContext.load(without),guard['reference'],guard['name'],tuple(guard['layers']),uid)
    new['rule_names']=list(guard.get('rule_names',[]))
    return text,new
