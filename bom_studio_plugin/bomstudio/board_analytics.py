"""Read-only saved-PCB copper inventory, in mm and mm².

Areas use polygon unions per copper layer, never sums of overlapping zones.
Curves are tessellated at 128 segments per circle; these are geometric estimates,
not connectivity, current capacity, solder-contact or thermal measurements.
"""
from collections import defaultdict
from collections import OrderedDict
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from threading import Lock

from .sexpr import properties

_CACHE = OrderedDict()
_CACHE_LOCK = Lock()


def prepare_geometry():
    """Initialize optional native geometry on the host thread before HTTP workers."""
    try:
        from shapely.geometry import Point
        from shapely import affinity, ops, strtree, validation
        # Initialize GEOS as well as loading its Python extension.
        Point(0,0).buffer(1).area
        return True
    except ImportError:
        return False


def _number(value):
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e6:
        raise ValueError('Invalid PCB dimension')
    return value


def _xy(node):
    if node is None:
        raise ValueError('Missing coordinates')
    return _number(node.val(1)), _number(node.val(2))


def _arc(node):
    """Sample the circular arc through start, mid and end, retaining endpoints."""
    a, b, c = (_xy(node.one(key)) for key in ('start', 'mid', 'end'))
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax*(by-cy) + bx*(cy-ay) + cx*(ay-by))
    if abs(d) < 1e-12:
        raise ValueError('Degenerate arc')
    aa, bb, cc = ax*ax+ay*ay, bx*bx+by*by, cx*cx+cy*cy
    ox = (aa*(by-cy)+bb*(cy-ay)+cc*(ay-by))/d
    oy = (aa*(cx-bx)+bb*(ax-cx)+cc*(bx-ax))/d
    start, mid, end = (math.atan2(y-oy, x-ox) for x,y in (a,b,c))
    sweep = (end-start) % (2*math.pi)
    if (mid-start) % (2*math.pi) > sweep:
        sweep -= 2*math.pi
    count = max(2, math.ceil(abs(sweep)*128/(2*math.pi)))
    radius = math.hypot(ax-ox, ay-oy)
    return [a] + [(ox+radius*math.cos(start+sweep*i/count),
                   oy+radius*math.sin(start+sweep*i/count)) for i in range(1,count)] + [c]


def analyze_tree(tree):
    """Inventory one parsed board; unsupported geometry invalidates affected areas."""
    layer_node = tree.one('layers')
    layers = [n.val() for n in layer_node.children if n.val().endswith('.Cu')] if layer_node else []
    if not layers:
        layers = ['F.Cu', 'B.Cu']
    nets = {n.val(): n.val(2) for n in tree.nodes('net')}
    warnings = set()
    result = {'status':'known', 'source':{}, 'summary':{}, 'layers':[], 'nets':[],
              'components':[], 'net_layers':[], 'zones':[], 'warnings':[]}
    try:
        from shapely.geometry import Point, Polygon, LineString, box
        from shapely.affinity import rotate, translate
        from shapely.ops import unary_union, polygonize
        from shapely.strtree import STRtree
        from shapely.validation import explain_validity
    except ImportError:
        result.update(status='unavailable', warnings=['Copper area analytics require Shapely; rerun runtime setup.'])
        return result
    shapes = defaultdict(list); fills = defaultdict(list); boundaries = defaultdict(list)
    counts = defaultdict(lambda: defaultdict(float))
    bad = set(); bad_pad = set(); bad_fill = set(); bad_boundary = set(); bad_length = set(); holes = []
    net_pad_counts=defaultdict(int); net_zone_counts=defaultdict(int)
    layer_holes = defaultdict(list)
    hole_count = 0

    def net_name(node):
        net = node.one('net')
        if net is None:
            return '(unconnected)'
        return net.val(2) or nets.get(net.val(), net.val() if not net.val().isdigit() else '(net '+net.val()+')') or '(unconnected)'

    def polygon(node):
        pts = node.one('pts')
        if pts is None or any(n.tag != 'xy' for n in pts.children):
            raise ValueError('Unsupported polygon contour')
        points=[_xy(n) for n in pts.nodes('xy')]
        p = Polygon(points)
        if not p.is_valid and explain_validity(p).startswith('Ring Self-intersection') and len(set(points))<len(points):
            # Saved zone holes use repeated vertices and zero-width bridges.
            # Remove zero-width bridges only when authored signed area is conserved.
            repaired=p.buffer(0)
            if math.isclose(repaired.area,p.area,rel_tol=1e-9,abs_tol=1e-8): p=repaired
        if not p.is_valid or p.is_empty:
            raise ValueError('Invalid or bridged polygon contour')
        return p

    def positive(value):
        n = _number(value)
        if n <= 0:
            raise ValueError('Nonpositive dimension')
        return n

    def oval(w, h):
        r = min(w,h)/2
        if abs(w-h) < 1e-12:
            return Point(0,0).buffer(r, quad_segs=32)
        points = [(-(w-h)/2,0), ((w-h)/2,0)] if w > h else [(0,-(h-w)/2), (0,(h-w)/2)]
        return LineString(points).buffer(r, quad_segs=32)

    def pad_shape(pad):
        w,h = _xy(pad.one('size')); positive(w); positive(h)
        shape = pad.val(3)
        if shape == 'rect':
            p = box(-w/2,-h/2,w/2,h/2)
        elif shape == 'circle' and abs(w-h)<1e-9:
            p = oval(w,h)
        elif shape == 'oval':
            p = oval(w,h)
        elif shape == 'roundrect' and not (pad.one('chamfer') or pad.one('chamfer_ratio')):
            ratio = _number(pad.get('roundrect_rratio'))
            if not 0 <= ratio <= .5:
                raise ValueError('Invalid rounded pad radius')
            r = ratio*min(w,h)
            if r == 0:
                p = box(-w/2,-h/2,w/2,h/2)
            elif abs(w-2*r)<1e-12 or abs(h-2*r)<1e-12:
                p = oval(w,h)
            else:
                p = box(-w/2+r,-h/2+r,w/2-r,h/2-r).buffer(r,quad_segs=32)
        else:
            raise ValueError('Unsupported pad shape: '+shape)
        return p

    def drill_shape(pad):
        drill = pad.one('drill')
        if drill is None:
            return None
        if drill.val() == 'oval':
            w,h = positive(drill.val(2)),positive(drill.val(3))
        else:
            w=h=positive(drill.val())
        p = oval(w,h)
        if drill.one('offset'):
            p = translate(p,*_xy(drill.one('offset')))
        return p

    def apply_pad(p, pad, fp):
        # KiCad pad angles are absolute; pad centres are footprint-local.
        x,y = _xy(pad.one('at'))
        fa = _number(fp.one('at').val(3) or 0) if fp.one('at') else 0
        angle = _number(pad.one('at').val(3) or 0)
        fx,fy = _xy(fp.one('at')) if fp.one('at') else (0,0)
        a = math.radians(fa)
        return translate(rotate(p,-angle,origin=(0,0)),
                         fx+x*math.cos(a)+y*math.sin(a), fy-x*math.sin(a)+y*math.cos(a))

    for fp in tree.nodes('footprint'):
        props = properties(fp)
        ref = props.get('Reference',('',))[0] or next((n.val(2) for n in fp.nodes('fp_text') if n.val()=='reference'),'')
        value = props.get('Value',('',))[0] or next((n.val(2) for n in fp.nodes('fp_text') if n.val()=='value'),'')
        rec = {'reference':ref,'value':value,'side':fp.get('layer'),'pad_count':0,
               'pad_area_mm2':0.0,'placement_pad_area_mm2':0.0,'pad_area_by_layer':{},'issues':[]}
        pad_sums = defaultdict(float); invalid_layers = set()
        for pad in fp.nodes('pad'):
            ln = pad.one('layers')
            names = [a.value for a in ln.atoms[1:]] if ln else []
            on = [l for l in layers if l in names or '*.Cu' in names or ('F&B.Cu' in names and l in ('F.Cu','B.Cu'))]
            if pad.val(2)=='np_thru_hole':
                on=[]
            net = net_name(pad)
            rec['pad_count'] += bool(on)
            net_pad_counts[net] += bool(on)
            for layer in on:
                counts[layer,net]['pad_count'] += 1
            try:
                hole = drill_shape(pad)
                if hole is not None:
                    placed_hole=apply_pad(hole,pad,fp)
                    holes.append(placed_hole); hole_count += 1
                    for layer in layers: layer_holes[layer].append(placed_hole)
                if not on:
                    continue
                if pad.one('padstack') or pad.one('remove_unused_layers'):
                    raise ValueError('Layer-specific or unused-layer pad stack requires native copper evaluation')
                p = pad_shape(pad)
                if hole is not None:
                    p = p.difference(hole)
                area = p.area
                for layer in on:
                    pad_sums[layer] += area
                    counts[layer,net]['pad_area_mm2'] += area
                    shapes[layer,net].append(apply_pad(p,pad,fp))
            except (ValueError,TypeError,AttributeError) as exc:
                rec['issues'].append(str(exc)); warnings.add('Unsupported pad geometry; affected copper and pad areas are unknown.')
                invalid_layers.update(on); bad.update((layer,net) for layer in on)
                bad_pad.update((layer,net) for layer in on)
        rec['pad_area_by_layer'] = {l:None if l in invalid_layers else pad_sums[l] for l in layers if l in pad_sums or l in invalid_layers}
        rec['placement_pad_area_mm2'] = rec['pad_area_by_layer'].get(rec['side'],0.0)
        # Contact is one placement-side land sum; do not multiply THT faces by layer count.
        rec['pad_area_mm2'] = rec['placement_pad_area_mm2']
        result['components'].append(rec)

    for tag in ('segment','arc'):
        for track in tree.nodes(tag):
            key = track.get('layer'),net_name(track)
            counts[key]['track_count'] += 1
            try:
                points = _arc(track) if tag=='arc' else [_xy(track.one('start')),_xy(track.one('end'))]
                line = LineString(points); width=positive(track.get('width'))
                counts[key]['track_length_mm'] += line.length
                shapes[key].append(line.buffer(width/2,quad_segs=32))
            except (ValueError,TypeError,AttributeError) as exc:
                bad.add(key); bad_length.add(key); warnings.add(str(exc))

    # Graphical copper is not an electrical net. Do not silently omit it from totals.
    for parent,prefix in [(tree,'gr')] + [(fp,'fp') for fp in tree.nodes('footprint')]:
        for tag in ('line','arc','rect','poly','circle','curve','text','text_box'):
            for graphic in parent.nodes(prefix+'_'+tag):
                layer=graphic.get('layer')
                if layer in layers:
                    bad.add((layer,'(graphic copper)'))
                    counts[layer,'(graphic copper)']
                    warnings.add('Graphical copper is present; its affected total copper areas remain unknown.')

    vias = []
    for via in tree.nodes('via'):
        net = net_name(via); vias.append(net)
        ln = via.one('layers'); ends = [a.value for a in ln.atoms[1:]] if ln else []
        try:
            if len(ends)!=2 or any(l not in layers for l in ends):
                raise ValueError('Unknown via layer span')
            a,b = sorted(layers.index(l) for l in ends); on=layers[a:b+1]
            x,y=_xy(via.one('at')); size=positive(via.get('size')); drill=positive(via.get('drill'))
            if drill >= size:
                raise ValueError('Via drill must be smaller than copper diameter')
            hole=Point(x,y).buffer(drill/2,quad_segs=32); hole_count += 1
            if len(on)==len(layers): holes.append(hole)
            for layer in on: layer_holes[layer].append(hole)
            p=Point(x,y).buffer(size/2,quad_segs=32).difference(hole)
            for layer in on:
                counts[layer,net]['via_count']+=1; shapes[layer,net].append(p)
            if via.one('padstack') or via.one('remove_unused_layers'):
                bad.update((l,net) for l in on)
                warnings.add('Layer-specific via annuli require native copper evaluation.')
        except (ValueError,TypeError,AttributeError) as exc:
            bad.update((l,net) for l in layers); warnings.add(str(exc))

    zone_count=0; zone_work=[]
    for zone in tree.nodes('zone'):
        if zone.one('keepout'):
            continue
        on=[zone.get('layer')] if zone.one('layer') else [a.value for a in zone.one('layers').atoms[1:]] if zone.one('layers') else []
        on=[l for l in on if l in layers]
        if not on:
            continue
        net=zone.get('net_name') or net_name(zone); zone_count+=1; net_zone_counts[net]+=1
        zone_boundary=[]; zone_fill=defaultdict(list); invalid_boundary=False; invalid_fill=set()
        for layer in on:
            counts[layer,net]['zone_count']+=1
        for contour in zone.nodes('polygon'):
            try:
                p=polygon(contour)
                zone_boundary.append(p)
                for layer in on: boundaries[layer,net].append(p)
            except (ValueError,TypeError,AttributeError) as exc:
                bad_boundary.update((l,net) for l in on); warnings.add(str(exc))
                invalid_boundary=True
        populated=set()
        for fill in zone.nodes('filled_polygon'):
            layer=fill.get('layer') or (on[0] if len(on)==1 else '')
            if layer not in on:
                bad_fill.update((l,net) for l in on); invalid_fill.update(on); continue
            populated.add(layer)
            try:
                p=polygon(fill); fills[layer,net].append(p); shapes[layer,net].append(p); zone_fill[layer].append(p)
            except (ValueError,TypeError,AttributeError) as exc:
                bad_fill.add((layer,net)); bad.add((layer,net)); warnings.add(str(exc))
                invalid_fill.add(layer)
        for layer in set(on)-populated:
            bad_fill.add((layer,net)); bad.add((layer,net))
            warnings.add('Zone has no saved fill polygons; refill and save in KiCad. Boundary area is not filled copper area.')
            invalid_fill.add(layer)
        for layer in on:
            zone_work.append(({'name':zone.get('name') or 'Zone '+str(zone_count),
                               'id':zone.get('uuid') or zone.get('tstamp'),'net':net,'layer':layer,
                               'boundary_area_mm2':None if invalid_boundary else float(unary_union(zone_boundary).area),
                               'filled_polygon_count':len(zone_fill[layer])},zone_fill[layer],layer in invalid_fill))

    # Edge loops are XOR-combined so nested cutouts remove substrate area.
    edge_lines=[]; edge_polys=[]; board=None; edge_bad=False
    if any(g.get('layer')=='Edge.Cuts' for fp in tree.nodes('footprint') for g in fp.children):
        edge_bad=True; warnings.add('Footprint-local Edge.Cuts requires native outline evaluation.')
    for tag in ('gr_line','gr_arc','gr_rect','gr_poly','gr_circle','gr_curve'):
        for edge in tree.nodes(tag):
            if edge.get('layer')!='Edge.Cuts': continue
            try:
                if tag in ('gr_line','gr_arc'):
                    pts=_arc(edge) if tag=='gr_arc' else [_xy(edge.one('start')),_xy(edge.one('end'))]
                    edge_lines.append(LineString(pts))
                elif tag=='gr_rect':
                    a,b=_xy(edge.one('start')),_xy(edge.one('end')); edge_polys.append(box(min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])))
                elif tag=='gr_circle':
                    c,e=_xy(edge.one('center')),_xy(edge.one('end')); edge_polys.append(Point(c).buffer(math.dist(c,e),quad_segs=32))
                elif tag=='gr_poly': edge_polys.append(polygon(edge))
                else: raise ValueError('Bezier Edge.Cuts area is unsupported')
            except (ValueError,TypeError,AttributeError) as exc:
                edge_bad=True; warnings.add(str(exc))
    if edge_lines:
        merged=unary_union(edge_lines); loops=list(polygonize(merged))
        used=unary_union([p.boundary for p in loops]) if loops else LineString()
        if merged.difference(used).length>1e-6:
            edge_bad=True; warnings.add('Open Edge.Cuts; board area is unknown.')
        # polygonize includes holes in enclosing faces; use unique exterior rings.
        edge_polys.extend(Polygon(p.exterior) for p in loops)
    if edge_polys and not edge_bad:
        board=edge_polys[0]
        for p in edge_polys[1:]: board=board.symmetric_difference(p)
        if holes: board=board.difference(unary_union(holes))
    else:
        warnings.add('Closed supported Edge.Cuts required for board area and copper coverage.')
    hole_indexes={l:STRtree(layer_holes[l]) for l in layers}
    for rec,polys,invalid in zone_work:
        p=unary_union(polys) if polys else Polygon()
        hits=hole_indexes[rec['layer']].query(p,predicate='intersects') if not p.is_empty else []
        if len(hits): p=p.difference(unary_union([layer_holes[rec['layer']][i] for i in hits]))
        rec['filled_zone_area_mm2']=None if invalid else float(p.area)
        rec['status']='unknown fill' if invalid else 'saved fill'
        result['zones'].append(rec)

    unions = {}

    def area(groups, keys, invalid, remove_holes=False):
        if any(key in invalid for key in keys): return None
        objects=[]
        for key in keys:
            cache_key=id(groups),key,remove_holes
            if cache_key not in unions:
                p=unary_union(groups[key]) if groups[key] else Polygon()
                if remove_holes and not p.is_empty:
                    hits=hole_indexes[key[0]].query(p,predicate='intersects')
                    if len(hits): p=p.difference(unary_union([layer_holes[key[0]][i] for i in hits]))
                unions[cache_key]=p
            objects.append(unions[cache_key])
        p=unary_union(objects) if objects else Polygon()
        return float(p.area)

    all_keys=set(counts)|set(shapes)|set(fills)
    for layer in layers:
        keys=[k for k in all_keys if k[0]==layer]
        rec={'layer':layer}
        for metric in ('track_count','track_length_mm','pad_count','pad_area_mm2','via_count','zone_count'):
            rec[metric]=sum(counts[k][metric] for k in keys)
        if any(k in bad_pad for k in keys): rec['pad_area_mm2']=None
        if any(k in bad_length for k in keys): rec['track_length_mm']=None
        rec['filled_zone_area_mm2']=area(fills,keys,bad_fill,True)
        rec['zone_boundary_area_mm2']=area(boundaries,keys,bad_boundary)
        rec['copper_area_mm2']=area(shapes,keys,bad,True)
        rec['coverage_percent']=100*rec['copper_area_mm2']/board.area if board is not None and board.area>0 and rec['copper_area_mm2'] is not None else None
        result['layers'].append(rec)
    for net in sorted({k[1] for k in all_keys}|set(vias)):
        keys=[k for k in all_keys if k[1]==net]; rec={'net':net,'layers':[l for l in layers if (l,net) in keys]}
        for metric in ('track_count','track_length_mm','pad_count','pad_area_mm2','zone_count'):
            rec[metric]=sum(counts[k][metric] for k in keys)
        rec['pad_count']=net_pad_counts[net]; rec['zone_count']=net_zone_counts[net]
        if any(k in bad_pad for k in keys): rec['pad_area_mm2']=None
        if any(k in bad_length for k in keys): rec['track_length_mm']=None
        rec['via_count']=vias.count(net); rec['transition_count']=rec['via_count']
        for key,groups,invalid in [('filled_zone_area_mm2',fills,bad_fill),('copper_area_mm2',shapes,bad)]:
            values=[area(groups,[(l,net)],invalid,True) for l in layers]
            rec[key]=sum(values) if all(v is not None for v in values) else None
        result['nets'].append(rec)
        for layer in rec['layers']:
            key=layer,net
            row={'net':net,'layer':layer,**dict(counts[key])}
            for metric in ('track_count','track_length_mm','pad_count','pad_area_mm2','via_count','zone_count'):
                row.setdefault(metric,0)
            if key in bad_pad: row['pad_area_mm2']=None
            if key in bad_length: row['track_length_mm']=None
            row['filled_zone_area_mm2']=area(fills,[key],bad_fill,True)
            row['copper_area_mm2']=area(shapes,[key],bad,True)
            row['coverage_percent']=100*row['copper_area_mm2']/board.area if board is not None and board.area>0 and row['copper_area_mm2'] is not None else None
            result['net_layers'].append(row)
    summary={'board_area_mm2':float(board.area) if board is not None else None,'layer_count':len(layers),
             'footprint_count':len(result['components']),'pad_count':sum(r['pad_count'] for r in result['components']),
             'via_count':len(vias),'transition_count':len(vias),'hole_count':hole_count,'zone_count':zone_count,
             'track_length_mm':None if bad_length else sum(r['track_length_mm'] for r in result['layers'])}
    for metric in ('filled_zone_area_mm2','copper_area_mm2'):
        values=[r[metric] for r in result['layers']]
        summary[metric]=sum(values) if all(v is not None for v in values) else None
        summary['known_'+metric]=sum(v for v in values if v is not None)
    summary['unknown_copper_layers']=sum(r['copper_area_mm2'] is None for r in result['layers'])
    summary['unknown_fill_layers']=sum(r['filled_zone_area_mm2'] is None for r in result['layers'])
    result.update(summary=summary, warnings=sorted(warnings), status='partial' if warnings else 'known')
    result['components'].sort(key=lambda r:r['reference'])
    return result


def board_analysis(workspace):
    """Read the configured saved board and retain its hash as report provenance."""
    path=Path(workspace.state.get('health_settings',{}).get('board_path') or workspace.project.pro_path.with_suffix('.kicad_pcb')).expanduser()
    if not path.is_absolute(): path=workspace.project.pro_path.parent/path
    source={'sha256':None,'status':'unavailable','notes':[
        'Saved PCB only; unsaved editor changes are not included.',
        'Areas are tessellated geometric estimates; circles use 128 segments.',
        'Copper and fill totals across layers sum separate layer faces, not projected board area.',
        'Transitions count physical vias, not inferred route changes or connectivity.',
        'Pad contact area is the placement-side land sum minus drill openings, not measured solder contact.',
        'Zone boundary area includes intended outlines; fill area uses only saved filled polygons.',
        'The saved fill is not regenerated or certified current by this read-only analysis.']}
    try:
        if path.stat().st_size>64*1024*1024: raise ValueError('PCB exceeds 64 MiB read limit')
        raw=path.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
        with _CACHE_LOCK:
            result=deepcopy(_CACHE.get(digest))
        if result is None:
            from .sexpr import parse
            tree=parse(raw.decode('utf-8-sig'))
            if tree.tag!='kicad_pcb': raise ValueError('Not a KiCad PCB')
            result=analyze_tree(tree)
            with _CACHE_LOCK:
                _CACHE[digest]=deepcopy(result)
                _CACHE.move_to_end(digest)
                while len(_CACHE)>2: _CACHE.popitem(last=False)
        source.update(sha256=digest,status='read')
    except (OSError,ValueError,UnicodeError) as exc:
        source['error']=str(exc)
        result={'status':'unavailable','summary':{},'layers':[],'nets':[],'net_layers':[],'zones':[],'components':[],'warnings':[str(exc)]}
    result['source']=source
    return result
