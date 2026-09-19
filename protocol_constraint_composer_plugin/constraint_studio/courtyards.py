"""Exact line/arc courtyard regions, multiple contours and guarded regeneration.

Native zone outlines retain arc start/mid/end coordinates. Tessellation is used
ONLY for nesting/self-intersection validation and the on-screen overview. Region
boundaries are never replaced by a bounding box or silently expanded.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import math
import uuid
from .board import BoardContext, _point, _equal, _intersect, _signed_area
from .sexpr import scalar, quote
from .expressions import function_test
from .linked_areas import all_areas, world_polygon

TOL = 1e-6  # mm; joining tolerance, not a clearance allowance

@dataclass(frozen=True)
class Edge:
    start: tuple
    end: tuple
    mid: tuple = None

    def reversed(self):
        return Edge(self.end, self.start, self.mid)

    def samples(self, error=0.002):
        if self.mid is None:
            return [self.start, self.end]
        (ax, ay), (bx, by), (cx, cy) = self.start, self.mid, self.end
        d = 2 * (ax*(by-cy)+bx*(cy-ay)+cx*(ay-by))
        if abs(d) < 1e-12:
            raise ValueError('Collinear/degenerate courtyard arc')
        aa, bb, cc = ax*ax+ay*ay, bx*bx+by*by, cx*cx+cy*cy
        ox = (aa*(by-cy)+bb*(cy-ay)+cc*(ay-by))/d
        oy = (aa*(cx-bx)+bb*(ax-cx)+cc*(bx-ax))/d
        r = math.hypot(ax-ox, ay-oy)
        a, b, c = (math.atan2(y-oy, x-ox) for x, y in (self.start, self.mid, self.end))
        sweep = (c-a) % (2*math.pi)
        if (b-a) % (2*math.pi) > sweep + 1e-10:
            sweep -= 2*math.pi
        step = 2*math.acos(max(-1., min(1., 1-min(error, r)/r)))
        n = max(2, math.ceil(abs(sweep)/max(step, 1e-6)))
        if n > 10000:
            raise ValueError('Arc is too large for the selected validation tolerance')
        return [self.start] + [(ox+r*math.cos(a+sweep*i/n), oy+r*math.sin(a+sweep*i/n)) for i in range(1, n)] + [self.end]

    def emit(self):
        def pt(tag, p):
            return f'({tag} {p[0]:.9f} {p[1]:.9f})'
        if self.mid is None:
            return pt('xy', self.start)
        return '(arc '+pt('start', self.start)+' '+pt('mid', self.mid)+' '+pt('end', self.end)+')'


def _finite(p):
    if not all(math.isfinite(x) and abs(x)<1e6 for x in p):
        raise ValueError('Non-finite or excessively large courtyard coordinate')
    return p


def _polygon_edges(points):
    if len(points)>1 and _equal(points[0], points[-1]):
        points=points[:-1]
    return [Edge(a,b) for a,b in zip(points,points[1:]+points[:1])]


def _inside(p, polygon):
    inside=False
    x,y=p
    for a,b in zip(polygon, polygon[1:]+polygon[:1]):
        if (a[1]>y)!=(b[1]>y):
            xi=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if xi>x: inside=not inside
    return inside


def contour_points(edges, error=0.002):
    return [p for e in edges for p in e.samples(error)[:-1]]


def courtyard_contours(context, reference):
    fp=context.footprint(reference)
    side='B' if fp.layer=='B.Cu' else 'F'
    raw=[]
    for n in fp.node.children:
        if not n.is_list or scalar(n.first('layer')) not in (side+'.CrtYd', side+'.Courtyard'):
            continue
        h=n.head()
        if h in ('property','fp_text'): continue
        if h=='fp_line': raw.append(Edge(_point(n.first('start')), _point(n.first('end'))))
        elif h=='fp_arc': raw.append(Edge(_point(n.first('start')), _point(n.first('end')), _point(n.first('mid'))))
        elif h=='fp_circle':
            c=_point(n.first('center'));p=_point(n.first('end'));r=math.dist(c,p)
            if r<TOL: raise ValueError('Zero-radius courtyard circle')
            a=(c[0]+r,c[1]); b=(c[0]-r,c[1])
            raw.extend([Edge(a,b,(c[0],c[1]+r)),Edge(b,a,(c[0],c[1]-r))])
        elif h=='fp_rect':
            a=_point(n.first('start'));b=_point(n.first('end'))
            raw.extend(_polygon_edges([a,(b[0],a[1]),b,(a[0],b[1])]))
        elif h=='fp_poly':
            pts=n.first('pts')
            if not pts:raise ValueError('Empty courtyard polygon')
            raw.extend(_path_edges(pts))
        else:
            raise ValueError('Unsupported courtyard primitive: '+h)
    if not raw: raise ValueError('No courtyard on the component side')
    for e in raw:
        for p in (e.start,e.end)+( (e.mid,) if e.mid is not None else () ): _finite(p)
        if _equal(e.start,e.end): raise ValueError('Zero-length courtyard edge')
    if len(raw)>5000: raise ValueError('Courtyard exceeds 5,000 edges')
    loops=[]
    while raw:
        chain=[raw.pop(0)]
        while not _equal(chain[-1].end,chain[0].start):
            tail=chain[-1].end
            matches=[(i,e if _equal(e.start,tail) else e.reversed()) for i,e in enumerate(raw) if _equal(e.start,tail) or _equal(e.end,tail)]
            if len(matches)!=1: raise ValueError('Open or branched courtyard; no geometry was staged')
            i,e=matches[0]; raw.pop(i);chain.append(e)
        if any(_equal(chain[0].start,e.start) or _equal(chain[0].start,e.end) for e in raw):
            raise ValueError('Touching/branched contour junction')
        loops.append(chain)
    polygons=[contour_points(c) for c in loops]
    for poly in polygons:
        if len(poly)<3 or abs(_signed_area(poly))<1e-8: raise ValueError('Degenerate courtyard contour')
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)]
            for j in range(i+1,len(poly)):
                if j==i+1 or (i==0 and j==len(poly)-1): continue
                if _intersect(a,b,poly[j],poly[(j+1)%len(poly)]): raise ValueError('Self-intersecting courtyard contour')
    for i,p in enumerate(polygons):
        for q in polygons[i+1:]:
            for a,b in zip(p,p[1:]+p[:1]):
                for c,d in zip(q,q[1:]+q[:1]):
                    if _intersect(a,b,c,d): raise ValueError('Courtyard contours touch or intersect')
    parents=[]
    for i,p in enumerate(polygons):
        candidates=[j for j,q in enumerate(polygons) if i!=j and _inside(p[0],q)]
        parents.append(min(candidates,key=lambda j:abs(_signed_area(polygons[j]))) if candidates else None)
    return loops,parents


def _signature(contours):
    """Ordering/winding-independent exact geometry fingerprint (not sample points)."""
    result=[]
    for edges in contours:
        result.append(sorted((tuple(sorted((tuple(round(x,6) for x in e.start),tuple(round(x,6) for x in e.end)))), tuple(round(x,6) for x in e.mid) if e.mid else ()) for e in edges))
    return hashlib.sha256(json.dumps(sorted(result),sort_keys=True).encode()).hexdigest()


def scope_terms(regions, obj='A'):
    """Even/odd contour nesting. A relaxed pair must be inside the same union.
    An item touching a hole is excluded conservatively by intersectsArea().
    """
    def depth(i):
        n=0
        while regions[i]['parent'] is not None:
            i=regions[i]['parent']; n+=1
            if n>len(regions): raise ValueError('Cyclic contour hierarchy')
        return n
    terms=[]
    for i,r in enumerate(regions):
        if depth(i)%2: continue
        term=function_test(obj,'enclosedByArea',[r['name']]).emit()
        holes=[x for x in regions if x['parent']==i]
        for h in holes:
            term += ' && !'+function_test(obj,'intersectsArea',[h['name']]).emit()
        terms.append('('+term+')')
    return terms


def scope_for_regions(regions,obj='A'):
    return ' || '.join(scope_terms(regions,obj))


def pair_scope(regions):
    # Pair clearance exceptions never bridge two disjoint outer islands.
    return ' || '.join(f'({a} && {b})' for a,b in zip(scope_terms(regions,'A'),scope_terms(regions,'B')))


def stage_regions(context, reference, name='', layers=(), auto_sync=False, previous=None):
    fp=context.footprint(reference)
    if not fp.uid: raise ValueError('Footprint UUID is required')
    contours, parents=courtyard_contours(context,reference)
    name=name.strip() or 'CS_'+reference+'_'+fp.uid.replace('-','')[:8]+'_ESCAPE'
    if any(x in name for x in ('\r','\n','\0')) or not name: raise ValueError('Invalid rule area name')
    layers=tuple(layers) or (fp.layer,)
    if any(not l.endswith('.Cu') or l not in context.layers for l in layers): raise ValueError('Choose enabled copper layers')
    taken={a['name'] for a in all_areas(context)}
    if name in taken: raise ValueError('Rule-area name already exists')
    ls='(layer '+quote(layers[0])+')' if len(layers)==1 else '(layers '+' '.join(map(quote,layers))+')'
    zones=[]; regions=[]
    for i,edges in enumerate(contours):
        nm=name if len(contours)==1 else name+'__'+str(i+1)
        if nm in taken: raise ValueError('Rule-area name already exists: '+nm)
        old=(previous or {}).get('regions',[])
        uid=old[i]['uuid'] if i<len(old) else str(uuid.uuid4())
        regions.append({'name':nm,'uuid':uid,'parent':parents[i]})
        zones.append('\n    (zone (net 0) (net_name "") '+ls+' (uuid '+quote(uid)+') (name '+quote(nm)+')\n'
            '      (hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.01)\n'
            '      (keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour allowed) (footprints allowed))\n'
            '      (fill (thermal_gap 0.3) (thermal_bridge_width 0.3))\n'
            '      (polygon (pts '+' '.join(e.emit() for e in edges)+'))\n    )\n')
    guard={'mode':'footprint-owned-contours-v1','name':name,'reference':reference,'owner_uuid':fp.uid,
           'owner_layer':fp.layer,'layers':list(layers),'regions':regions,'source_signature':_signature(contours),
           'auto_sync':bool(auto_sync),'rule_names':[], 'rule_states':[]}
    text=context.text[:fp.node.end-1]+''.join(zones)+context.text[fp.node.end-1:]
    updated=BoardContext.load(text)
    guard['area_signatures']={r['uuid']:_area_signature(next(a for a in all_areas(updated) if scalar(a['node'].first('uuid'))==r['uuid'])) for r in regions}
    return text, guard


def _area_edges(area):
    polys=area['node'].find('polygon')
    if len(polys)!=1: raise ValueError('Managed region must have one contour')
    return _path_edges(polys[0].first('pts'))


def _path_edges(pts):
    tokens=pts.children[1:] if pts else []
    seq=[]
    for n in tokens:
        if n.head()=='xy': seq.append((_point(n),None))
        elif n.head()=='arc': seq.append((_point(n.first('start')),Edge(_point(n.first('start')),_point(n.first('end')),_point(n.first('mid')))))
        else: raise ValueError('Unsupported managed zone outline token')
    edges=[]
    for i,(p,e) in enumerate(seq):
        nxt=seq[(i+1)%len(seq)][0]
        if e:
            edges.append(e)
            if not _equal(e.end,nxt): edges.append(Edge(e.end,nxt))
        elif not _equal(p,nxt): edges.append(Edge(p,nxt))
    return edges


def _area_signature(area):
    return _signature([_area_edges(area)])


def check_regions(context, guard):
    fps=[f for f in context.footprints if f.uid==guard['owner_uuid']]
    if len(fps)!=1: return 'invalid','Owner UUID missing or ambiguous'
    fp=fps[0];areas=all_areas(context)
    expected=set(guard['layers'])
    flipped=fp.layer!=guard['owner_layer']
    if flipped: expected={ {'F.Cu':'B.Cu','B.Cu':'F.Cu'}.get(l,l) for l in expected }
    actual_contours=[]
    for r in guard['regions']:
        matches=[a for a in areas if a['name']==r['name']]
        if len(matches)!=1: return 'invalid','Managed region name missing/duplicated: '+r['name']
        a=matches[0];n=a['node']
        if a.get('owner_uuid')!=fp.uid or scalar(n.first('uuid'))!=r['uuid']: return 'invalid','Region owner/UUID changed'
        ls=n.first('layers');actual=set(ls.atoms()[1:] if ls else [scalar(n.first('layer'))])
        if actual!=expected:return 'invalid','Managed region layers changed independently'
        keep=n.first('keepout')
        if not keep or any(scalar(keep.first(k))!='allowed' for k in ('tracks','vias','pads','copperpour','footprints')):
            return 'invalid','Managed keepout policy changed'
        try: actual_contours.append(_area_edges(a))
        except ValueError as e:return 'invalid',str(e)
    try:
        source,parents=courtyard_contours(context,fp.reference)
        source_ids=[_signature([c]) for c in source];actual_ids=[_signature([c]) for c in actual_contours]
        aligned=[None]*len(actual_ids)
        if sorted(source_ids)==sorted(actual_ids):
            for i,si in enumerate(source_ids):aligned[actual_ids.index(si)]=None if parents[i] is None else actual_ids.index(source_ids[parents[i]])
        if sorted(source_ids)==sorted(actual_ids) and aligned==[r['parent'] for r in guard['regions']]:
            return 'current','Courtyard and footprint-owned region geometry agree'
        # Only regenerate when the area itself still has the shape we last wrote.
        original=guard.get('area_signatures',{})
        if flipped:
            # Do not guess native mirror axes after an independent courtyard edit.
            return 'stale','Footprint flipped and outline differs; explicit rebuild required'
        if any(_signature([e])!=original.get(r['uuid']) for e,r in zip(actual_contours,guard['regions'])):
            return 'invalid','Managed region edited independently; automatic overwrite refused'
        return 'stale','Courtyard changed; saved-snapshot regeneration required'
    except ValueError as e:return 'invalid',str(e)


def rebuild_regions(context, guard):
    state,msg=check_regions(context,guard)
    if state=='invalid':raise ValueError(msg)
    fp=next(f for f in context.footprints if f.uid==guard['owner_uuid'])
    ids={r['uuid'] for r in guard['regions']}
    nodes=[a['node'] for a in all_areas(context) if scalar(a['node'].first('uuid')) in ids]
    text=context.text
    for n in sorted(nodes,key=lambda n:n.start,reverse=True): text=text[:n.start]+text[n.end:]
    layers=guard['layers']
    if fp.layer!=guard['owner_layer']: layers=[{'F.Cu':'B.Cu','B.Cu':'F.Cu'}.get(l,l) for l in layers]
    text,new=stage_regions(BoardContext.load(text),fp.reference,guard['name'],layers,guard.get('auto_sync',False),guard)
    new['rule_names']=guard.get('rule_names',[])[:]
    new['rule_states']=guard.get('rule_states',[])[:]
    return text,new


def sync_workspace(workspace, explicit=False):
    """Transactional saved/staged synchronization. Never edits pcbnew or disk."""
    trial=workspace.clone();changes=[]
    for i,g in enumerate(trial.guards):
        if g.get('mode')!='footprint-owned-contours-v1':continue
        state,msg=check_regions(trial.context,g)
        if state=='current':continue
        if state=='invalid':raise ValueError(msg)
        if not explicit and not g.get('auto_sync'):continue
        rules=[r for r in trial.document.rules if r.name in g.get('rule_names',[])]
        if g.get('rule_states') and [r.state() for r in rules]!=g['rule_states']:
            raise ValueError('Managed component rules were edited; automatic regeneration refused')
        oldA,oldB=scope_for_regions(g['regions'],'A'),scope_for_regions(g['regions'],'B')
        trial.board_text,new=rebuild_regions(trial.context,g);trial.refresh_board_context()
        newA,newB=scope_for_regions(new['regions'],'A'),scope_for_regions(new['regions'],'B')
        for r in rules:
            if r.condition in (pair_scope(g['regions']),f'({oldA}) && ({oldB})'):r.condition=pair_scope(new['regions'])
            elif r.condition==oldA:r.condition=newA
            else:raise ValueError('Managed component scope no longer matches its binding')
        new['rule_states']=[r.state() for r in rules]
        trial.guards[i]=new;changes.append(new['name'])
    workspace.board_text=trial.board_text;workspace.context=trial.context;workspace.guards=trial.guards;workspace.document=trial.document
    return changes
