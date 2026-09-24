"""Read-only scope preview and priority trace, NOT a substitute KiCad DRC engine.
Unknowns are explicit and propagate: unsupported conditions never become false.
An offline candidate is not called the native/effective winner. Native reports
remain the authoritative geometry/constraint evidence.
"""
from dataclasses import dataclass, field
import ast, fnmatch, math, operator, re
from .sexpr import scalar
from .board import _point, _signed_area
from .expressions import parse_expression
from .catalog import CATALOG, PROPERTY_TYPES
from .model import numeric, FLOOR_KEYS
from .linked_areas import all_areas, area_polygon, world_polygon, local_courtyard

@dataclass
class Item:
    uid: str
    kind: str
    reference: str=''
    net: str=''
    layers: tuple=()
    points: list=field(default_factory=list)
    radius: float=0.0
    geometry: str='unknown'
    properties: dict=field(default_factory=dict)
    netclasses: object=None
    component_classes: object=None
    fields: dict=field(default_factory=dict)
    @property
    def label(self):
        return ' / '.join(s for s in (self.kind,self.reference,self.properties.get('Pad_Number',''),self.net,self.uid[:8]) if s)


def _net(node,netmap,text=''):
    n=node.first('net')
    if not n:return ''
    if len(n.children)>2:return n.children[2].value
    if len(n.children)>1 and text[n.children[1].start:n.children[1].start+1] in ('"', "'"):
        return n.children[1].value
    return netmap.get(scalar(n),'')


def _layers(node,context):
    n=node.first('layers')
    vals=n.atoms()[1:] if n else [scalar(node.first('layer'))]
    out=[]
    for v in vals:
        if v=='*.Cu':out.extend(l for l in context.layers if l.endswith('.Cu'))
        elif v=='F&B.Cu':out.extend(['F.Cu','B.Cu'])
        elif v:out.append(v)
    if node.head()=='via' and len(out)==2:
        copper=[l for l in context.layers if l.endswith('.Cu')]
        if all(l in copper for l in out):
            a,b=sorted(copper.index(l) for l in out);out=copper[a:b+1]
    return tuple(dict.fromkeys(out))


def _class_membership(net,project):
    if not net:return ()
    ns=project.get('net_settings') or {}
    matches=[]
    for row in ns.get('netclass_patterns') or []:
        if isinstance(row,dict) and fnmatch.fnmatchcase(net,row.get('pattern','')):
            matches.append(row.get('netclass',''))
    assignments=ns.get('netclass_assignments') or {}
    assignment=assignments.get(net) if isinstance(assignments,dict) else None
    if isinstance(assignment,str):matches.append(assignment)
    elif isinstance(assignment,list):matches.extend(assignment)
    # Saved rules may not contain schematic-computed membership; lack of matches
    # is unknown instead of inventing Default membership for native evaluation.
    return tuple(dict.fromkeys(x for x in matches if x)) or None


def items_from_board(context,project):
    if not context.root:return []
    netmap={scalar(n):n.children[2].value for n in context.root.find('net') if len(n.children)>2}
    out=[]
    for fp in context.footprints:
        fields={n.children[1].value:n.children[2].value for n in fp.node.find('property') if len(n.children)>2}
        props=dict(Type='Footprint',Reference=fp.reference,Value=fp.value,Layer=fp.layer,Library_Link=fp.library,
            Position_X=fp.x,Position_Y=fp.y,Orientation=fp.rotation)
        item=Item(fp.uid,'Footprint',fp.reference,layers=(fp.layer,),points=[(fp.x,fp.y)],properties=props,fields=fields)
        out.append(item)
        for pad in fp.node.find('pad'):
            uid=scalar(pad.first('uuid'));net=_net(pad,netmap,context.text);lay=_layers(pad,context)
            at=pad.first('at');xy=_point(at) if at else (0,0);center=world_polygon(fp,[xy])[0]
            size=pad.first('size');sx,sy=_point(size) if size else (0,0)
            shape=pad.children[3].value if len(pad.children)>3 else ''
            pnum=scalar(pad);ptype=pad.children[2].value if len(pad.children)>2 else ''
            p=dict(Type='Pad',Reference=fp.reference,Pad_Number=pnum,Pad_Type={'smd':'SMD','thru_hole':'Through-hole','np_thru_hole':'NPTH, mechanical'}.get(ptype,ptype),
                Pad_Shape=shape,NetName=net,Position_X=center[0],Position_Y=center[1],Size_X=sx,Size_Y=sy)
            points=[center];radius=0;geom='unknown'
            if shape=='circle' and abs(sx-sy)<1e-9:geom='circle';radius=sx/2
            elif shape in ('rect','roundrect','oval'):
                # Rectangle envelope is an enclosure certificate, not an exact
                # pad shape. A negative test on a rounded pad remains unknown.
                angle=float(at.children[3].value) if at and len(at.children)>3 else 0
                a=math.radians(angle);ca,sa=math.cos(a),math.sin(a)
                points=[(center[0]+x*ca+y*sa,center[1]-x*sa+y*ca) for x,y in [(-sx/2,-sy/2),(sx/2,-sy/2),(sx/2,sy/2),(-sx/2,sy/2)]]
                geom=('polygon' if shape=='rect' else 'envelope') if abs(fp.rotation)<1e-9 and abs(angle)<1e-9 and fp.layer=='F.Cu' else 'unknown'
                # Rotated/back-side non-circular pad orientation needs a native
                # geometry adapter; do not certify the drawn envelope offline.
            item=Item(uid,'Pad',fp.reference,net,lay,points,radius,geom,p,_class_membership(net,project),None,fields)
            out.append(item)
    for node in context.root.children:
        h=node.head()
        if h not in ('segment','arc','via'):continue
        net=_net(node,netmap,context.text);lay=_layers(node,context);uid=scalar(node.first('uuid'))
        if h=='via':
            pos=_point(node.first('at'));r=float(scalar(node.first('size'),'0'))/2
            p=dict(Type='Via',NetName=net,Diameter=2*r,Hole=float(scalar(node.first('drill'),'0')),Position_X=pos[0],Position_Y=pos[1])
            out.append(Item(uid,'Via',net=net,layers=lay,points=[pos],radius=r,geometry='circle',properties=p,netclasses=_class_membership(net,project)))
        else:
            points=[_point(node.first('start')),_point(node.first('end'))]
            width=float(scalar(node.first('width'),'0'));p=dict(Type='Track',NetName=net,Layer=lay[0] if lay else '',Width=width)
            out.append(Item(uid,'Track',net=net,layers=lay,points=points,radius=width/2,geometry='capsule' if h=='segment' else 'unknown',properties=p,netclasses=_class_membership(net,project)))
    return out


@dataclass
class Match:
    value: object  # True / False / None
    reasons: list=field(default_factory=list)
    @property
    def label(self):return 'match' if self.value is True else 'no match' if self.value is False else 'native evaluation required'


def _join(op,matches):
    vals=[m.value for m in matches];reasons=[r for m in matches for r in m.reasons]
    if op=='and':v=False if False in vals else None if None in vals else True
    else:v=True if True in vals else None if None in vals else False
    return Match(v,list(dict.fromkeys(reasons)))


def _convex(poly):
    if len(poly)<3:return False
    signs=[]
    for i,a in enumerate(poly):
        b,c=poly[(i+1)%len(poly)],poly[(i+2)%len(poly)]
        cross=(b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
        if abs(cross)>1e-9:signs.append(cross>0)
    return bool(signs) and len(set(signs))==1


def enclosed(item,area):
    if not area.get('rule_area'):return Match(None,['Copper-zone fill must be evaluated by KiCad'])
    try:poly=area_polygon(area)
    except ValueError as e:return Match(None,[str(e)])
    if not _convex(poly):return Match(None,['Non-convex area needs native geometry evaluation'])
    if item.geometry not in ('circle','capsule','polygon','envelope'):return Match(None,['Unsupported item shape or arc'])
    n=area['node'];ls=n.first('layers');layers=ls.atoms()[1:] if ls else [scalar(n.first('layer'))]
    if not set(layers).intersection(item.layers):return Match(False,['No shared area/item layer'])
    orientation=1 if _signed_area(poly)>0 else -1
    for a,b in zip(poly,poly[1:]+poly[:1]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<1e-12:return Match(None,['Degenerate area edge'])
        for p in item.points:
            distance=orientation*(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/length-item.radius
            if distance < -1e-7:
                return Match(None,['Rounded shape envelope crosses boundary']) if item.geometry=='envelope' else Match(False,['Item copper extends outside the area'])
            if abs(distance)<=1e-7:return Match(None,['Boundary contact within numerical tolerance; use KiCad'])
    return Match(True,['Conservative convex-area enclosure certificate; native DRC still required'])


def evaluate(expression,a,b=None,context=None):
    """Evaluate a documented subset on saved items. Never executes input strings."""
    try:tree=parse_expression(expression)
    except ValueError as e:return Match(None,[str(e)])
    def obj(name):return a if name=='A' else b if name=='B' else None
    def value(text):
        text=text.strip()
        if text=='null':return None,True
        if text[:1] in ('\'', '"'):
            try:return ast.literal_eval(text),True
            except (SyntaxError,ValueError):return None,False
        m=re.fullmatch(r'([AB])\.([\w%\-]+)',text)
        if m:
            item=obj(m[1])
            if item and m[2] in item.properties:return item.properties[m[2]],True
            return None,False
        try:return numeric(text),True
        except ValueError:return None,False
    def leaf(text):
        if not text:return Match(True)
        fun=re.fullmatch(r'(A|B|AB)\.(\w+)\((.*?)\)(?:\s*(==|!=)\s*(.+))?',text)
        if fun:
            receiver,name,args,comparison,rhs=fun.groups();item=obj(receiver)
            try:argv=ast.literal_eval('['+args+']')
            except (SyntaxError,ValueError):return Match(None,['Unsupported function arguments'])
            if not item:return Match(None,['Select both items for an A/B pair check' if receiver=='B' else 'AB function requires native pair semantics'])
            if comparison and name!='getField':return Match(None,['Explicit function-result comparison requires native evaluation'])
            if name=='enclosedByArea' and len(argv)==1 and context:
                areas=[x for x in all_areas(context) if x['name']==argv[0]]
                return enclosed(item,areas[0]) if len(areas)==1 else Match(None,['Area missing or ambiguous'])
            if name=='existsOnLayer' and len(argv)==1:
                return Match(any(fnmatch.fnmatchcase(l,argv[0]) for l in item.layers))
            if name in ('hasNetclass','hasExactNetclass') and len(argv)==1:
                if item.netclasses is None:return Match(None,['Netclass membership may be schematic/composite; native engine required'])
                if name=='hasExactNetclass':return Match(None,['Exact composite-netclass formatting requires native engine'])
                if argv[0] in item.netclasses:return Match(True,['Saved pattern/assignment membership'])
                return Match(None,['Unlisted schematic netclass membership is not excluded by saved patterns'])
            if name=='memberOfFootprint' and len(argv)==1:
                pattern=argv[0]
                if '${' in pattern or ':' in pattern:return Match(None,['Library/class footprint patterns require native evaluation'])
                # memberOfFootprint means a footprint child, not the footprint itself.
                return Match(item.kind!='Footprint' and bool(item.reference) and fnmatch.fnmatchcase(item.reference,pattern))
            if name=='getField' and len(argv)==1 and comparison:
                if item.kind!='Footprint':return Match(None,['getField is a footprint-only native function'])
                other,ok=value(rhs)
                if not ok:return Match(None,['Unsupported field comparison'])
                if argv[0] not in item.fields:return Match(None,['Missing field null/empty semantics require native evaluation'])
                return Match((item.fields[argv[0]]==other)==(comparison=='=='))
            return Match(None,[name+' needs native geometry, connectivity, or class evaluation'])
        comp=re.fullmatch(r'(.+?)\s*(==|!=|<=|>=|<|>)\s*(.+)',text)
        if comp:
            left,op,right=comp.groups();lv,lok=value(left);rv,rok=value(right)
            if not lok or not rok:return Match(None,['Unsupported/unavailable property in '+text])
            if isinstance(lv,str) and isinstance(rv,str):
                if any(x in rv for x in ('*','?','${')):return Match(None,['Native wildcard/variable comparison semantics required'])
            # Physical item properties above are stored in mm. Bare condition
            # constants use KiCad internal distance units (nm), not mm.
            prop=left.split('.')[-1].strip()
            if PROPERTY_TYPES.get(prop)=='dimension' and re.fullmatch(r'[+\-]?\d+(?:\.\d*)?',right.strip()):rv*=1e-6
            ops={'==':operator.eq,'!=':operator.ne,'<':operator.lt,'<=':operator.le,'>':operator.gt,'>=':operator.ge}
            try:return Match(bool(ops[op](lv,rv)))
            except (TypeError,ValueError):return Match(None,['Incompatible property types'])
        v,ok=value(text)
        return Match(v) if ok and isinstance(v,bool) else Match(None,['Unsupported condition: '+text])
    def walk(node):
        if node.op=='leaf':return leaf(node.text)
        if node.op=='not':
            r=walk(node.children[0]);return Match(None if r.value is None else not r.value,r.reasons)
        return _join(node.op,[walk(c) for c in node.children])
    return walk(tree)


def rule_match(rule,a,b=None,context=None,pair=False):
    if not rule.enabled:return Match(False,['Disabled rule'])
    if pair and b is None:return Match(None,['Select both objects for a pair constraint'])
    layer=rule.layer
    if layer and layer!='Any':
        layers=set(a.layers)
        if b:layers &= set(b.layers)
        if layer=='outer':ok=bool(layers & {'F.Cu','B.Cu'})
        elif layer=='inner':ok=any(l.startswith('In') and l.endswith('.Cu') for l in layers)
        else:ok=layer in layers
        if not ok:return Match(False,['Layer clause does not match'])
    result=evaluate(rule.condition,a,b,context)
    if pair and b:return _join('or',[result,evaluate(rule.condition,b,a,context)])
    return result


def priority_trace(document,kind,a,b=None,context=None,floors=None):
    """Highest first; each row keeps reasons and source. No false native winner."""
    rows=[];blocked=False;candidate=None
    for index in range(len(document.rules)-1,-1,-1):
        r=document.rules[index]
        matching=[c for c in r.constraints if c.kind==kind]
        if not matching:continue
        m=rule_match(r,a,b,context,pair=CATALOG.get(kind).pair if kind in CATALOG else False)
        status=m.label
        if m.value is None and candidate is None:blocked=True
        if m.value is True:
            if candidate is None:
                candidate=index;status='candidate — higher unknown rule' if blocked else 'offline candidate (not native winner)'
            else:status='lower-priority match'
        rows.append(dict(index=index,priority=len(document.rules)-index,rule=r.name,status=status,match=m.value,
            constraints=[c.emit() for c in matching],severity=r.severity or 'inherit',reasons=m.reasons))
    floor=(floors or {}).get(FLOOR_KEYS.get(kind,''))
    return dict(kind=kind,authority='offline-subset-preview',candidate=candidate,indeterminate=blocked,
        manufacturing_floor_mm=floor,rows=rows,
        warning='Not the native effective constraint: implicit defaults, pad/footprint overrides, router context and unsupported expressions may affect the result. Use KiCad clearance/constraint resolution and native DRC.')


def read_drc_report(data):
    """Import KiCad JSON records; do not turn rule names into invented engine queries."""
    if not isinstance(data,dict):raise ValueError('Expected a native KiCad JSON report')
    sections=('violations','unconnected_items','schematic_parity')
    if not any(s in data for s in sections):raise ValueError('No native DRC report sections found')
    result=[]
    for section in sections:
        records=data.get(section,[])
        if not isinstance(records,list):raise ValueError('Invalid native report section')
        for r in records:
            if not isinstance(r,dict):continue
            items=r.get('items',[])
            result.append(dict(section=section,type=r.get('type',''),severity=r.get('severity',''),description=r.get('description',''),
                items=items,uuids=[x.get('uuid','') for x in items if isinstance(x,dict) and x.get('uuid')],
                rule=r.get('rule',r.get('rule_name','')),native_record=r))
    return result
