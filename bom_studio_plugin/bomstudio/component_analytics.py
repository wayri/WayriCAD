"""Component-family and saved-PCB area analytics; never a thermal solve."""
from collections import defaultdict
from decimal import Decimal
import math
from pathlib import Path
from .footprints import load_tree
from .sexpr import properties

D = Decimal


def classification(part):
    value = part['type'].strip().casefold()
    groups = {
        'Resistors': {'r', 'resistor', 'resistors', 'resistor network', 'variable resistor'},
        'Capacitors': {'c', 'capacitor', 'capacitors'},
        'Inductors': {'l', 'inductor', 'inductors'},
        'Other passives': {'transformer', 'ferrite bead', 'passive', 'passives'},
        'Actives': {'u', 'ic', 'q', 'd', 'integrated circuit', 'transistor', 'diode', 'led', 'active', 'actives'},
    }
    kind = next((key for key, names in groups.items() if value in names), 'Other / unclassified')
    return ('Passives' if kind in ('Resistors', 'Capacitors', 'Inductors', 'Other passives') else kind), kind


def _xy(node):
    if node is None:
        raise ValueError('Missing geometry coordinates')
    result = tuple(float(node.val(i)) for i in (1, 2))
    if not all(math.isfinite(v) and abs(v) <= 1e6 for v in result):
        raise ValueError('Invalid geometry coordinates')
    return result


def _polygon_area(points):
    if len(points) > 1000:
        raise ValueError('Courtyard exceeds polygon budget')
    if len(points) > 2 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3 or len(set(points)) != len(points):
        raise ValueError('Invalid courtyard polygon')
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    edges = list(zip(points, points[1:]+points[:1]))
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges):
            if j <= i+1 or (i == 0 and j == len(edges)-1):
                continue
            if max(min(a[0],b[0]),min(c[0],d[0])) <= min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1])) <= min(max(a[1],b[1]),max(c[1],d[1])):
                if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0:
                    raise ValueError('Self-intersecting courtyard')
    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in edges))/2
    if area <= 0:
        raise ValueError('Empty courtyard')
    return area


def courtyard_area(fp, layer):
    shapes = []
    lines = []
    for tag in ('fp_rect', 'fp_poly', 'fp_line', 'fp_arc', 'fp_circle'):
        for shape in fp.nodes(tag):
            if shape.get('layer') != layer:
                continue
            if tag == 'fp_rect':
                a,b = _xy(shape.one('start')), _xy(shape.one('end'))
                shapes.append(abs((b[0]-a[0])*(b[1]-a[1])))
            elif tag == 'fp_poly':
                shapes.append(_polygon_area([_xy(p) for p in shape.one('pts').nodes('xy')]))
            elif tag == 'fp_line':
                lines.append((_xy(shape.one('start')), _xy(shape.one('end'))))
            else:
                raise ValueError('Curved courtyard area is not supported')
    if lines:
        if len(lines) > 1000:
            raise ValueError('Courtyard exceeds polygon budget')
        first,last = lines.pop(0);points = [first,last]
        while lines:
            found = next(((i,b if a==last else a) for i,(a,b) in enumerate(lines) if a==last or b==last), None)
            if found is None:
                raise ValueError('Disconnected/multiple courtyard loops')
            i,last = found;lines.pop(i);points.append(last)
        if last != first:
            raise ValueError('Open courtyard')
        shapes.append(_polygon_area(points))
    if len(shapes) != 1 or shapes[0] <= 0:
        raise ValueError('One closed courtyard required; no bounding-box substitution')
    return D(str(shapes[0]))


def _oval(w,h):
    small,big = min(w,h),max(w,h)
    return math.pi*small*small/4+(big-small)*small


def pad_areas(fp, copper_layer):
    areas=[];boxes=[]
    pads=fp.nodes('pad')
    if len(pads)>4096:
        raise ValueError('Footprint exceeds pad geometry budget')
    for pad in pads:
        layers = pad.one('layers')
        layer_names = [atom.value for atom in layers.atoms[1:]] if layers else []
        if not pad.val() or pad.val(2) == 'np_thru_hole' or not ({copper_layer,'*.Cu','F&B.Cu'} & set(layer_names)):
            continue
        w,h = _xy(pad.one('size'));x,y = _xy(pad.one('at'))
        if w <= 0 or h <= 0:
            raise ValueError('Invalid pad dimensions')
        shape=pad.val(3)
        if shape=='rect':area=w*h
        elif shape=='circle' and abs(w-h)<1e-9:area=math.pi*w*w/4
        elif shape=='oval':area=_oval(w,h)
        elif shape=='roundrect':
            ratio=float(pad.get('roundrect_rratio'))
            if not math.isfinite(ratio) or not 0<=ratio<=.5:raise ValueError('Invalid rounded-pad radius')
            if pad.one('chamfer') or pad.one('chamfer_ratio'):raise ValueError('Chamfered pad is unsupported')
            area=w*h-(4-math.pi)*(ratio*min(w,h))**2
        else:raise ValueError('Unsupported pad shape: '+shape)
        drill=pad.one('drill')
        if drill:
            # Offsets require a geometric intersection, not unconditional subtraction.
            if drill.one('offset'):raise ValueError('Offset drill area is unsupported')
            if drill.val(1)=='oval':dw,dh=float(drill.val(2)),float(drill.val(3))
            else:dw=dh=float(drill.val(1))
            if not all(math.isfinite(v) and v>=0 for v in (dw,dh)):raise ValueError('Invalid drill')
            if shape not in ('circle','oval','rect') or dw>w or dh>h:raise ValueError('Unsupported drill containment')
            if dw != dh and shape != 'rect':raise ValueError('Slotted drill containment is unsupported for curved lands')
            area-=_oval(dw,dh)
        if area <= 0:raise ValueError('Nonpositive pad copper area')
        angle=float(pad.one('at').val(3) or 0)
        if not math.isfinite(angle):raise ValueError('Invalid pad angle')
        # Orientation-independent bounds avoid assuming local/global pad angles.
        # This deliberately reports unknown for some disjoint closely spaced pads.
        bw=bh=w if shape=='circle' else math.hypot(w,h)
        box=(x-bw/2,y-bh/2,x+bw/2,y+bh/2)
        if any(min(box[2],b[2])-max(box[0],b[0])>1e-9 and min(box[3],b[3])-max(box[1],b[1])>1e-9 for b in boxes):
            raise ValueError('Potentially overlapping pad faces; union area not certified')
        boxes.append(box);areas.append(D(str(area)))
    if not areas:raise ValueError('No numbered copper pads on placement side')
    return sum(areas,D(0))


def board_geometry(ws, rows):
    path=Path(ws.state.get('health_settings',{}).get('board_path') or ws.project.pro_path.with_suffix('.kicad_pcb')).expanduser()
    if not path.is_absolute():path=ws.project.pro_path.parent/path
    context={'path':str(path),'sha256':None,'status':'unavailable','notes':[
        'Saved PCB only; unsaved PCB edits are not included.',
        'Footprint area is placement-side courtyard area, not package body or union board occupancy.',
        'Pad contact proxy is nominal numbered copper land area on the placement side minus supported drill openings; not wetted solder, pin contact or heat-transfer area.',
        'Overlapping pad bounds, custom pads, curved/multiple courtyards and unsupported drills remain unknown.']}
    result={r['id']:{'footprint_area_mm2':None,'pad_area_mm2':None,'issues':[]} for r in rows}
    try:
        tree,digest=load_tree(path)
        if tree.tag!='kicad_pcb':raise ValueError('Not a KiCad PCB')
        context.update(status='read',sha256=digest)
        index=defaultdict(list)
        for fp in tree.nodes('footprint'):
            props=properties(fp);ref=props.get('Reference',('',))[0] or next((x.val(2) for x in fp.nodes('fp_text') if x.val()=='reference'),'')
            index[ref].append(fp)
        for row in rows:
            rec=result[row['id']];found=index[row['ref']]
            if len(found)!=1:
                rec['issues'].append('Missing or ambiguous PCB reference');continue
            fp=found[0]
            if fp.val()!=row['fields'].get('Footprint','') or (fp.get('path') and fp.get('path').strip('/')!=row['id'].strip('/')):
                rec['issues'].append('PCB footprint identity does not match schematic');continue
            side=fp.get('layer')
            if side not in ('F.Cu','B.Cu'):
                rec['issues'].append('Placement side unknown');continue
            rec['match']='reference, footprint identifier'+(' and UUID path' if fp.get('path') else '; PCB UUID path absent')
            for key,action in [('footprint_area_mm2',lambda:courtyard_area(fp,side[0]+'.CrtYd')),('pad_area_mm2',lambda:pad_areas(fp,side))]:
                try:rec[key]=action()
                except (ValueError,TypeError,AttributeError,OverflowError) as exc:rec['issues'].append(str(exc))
    except (OSError,ValueError,UnicodeError) as exc:context['error']=str(exc)
    return result,context


def histogram(values):
    values=sorted(values)
    if not values:return []
    lo,hi=values[0],values[-1]
    if lo==hi:return [{'lower':lo,'upper':hi,'count':len(values),'upper_inclusive':True}]
    width=(hi-lo)/8;counts=[0]*8
    for value in values:counts[min(7,int((value-lo)/width))]+=1
    return [{'lower':lo+i*width,'upper':lo+(i+1)*width,'count':n,'upper_inclusive':i==7} for i,n in enumerate(counts)]


def summarize(parts, geometry):
    buckets=defaultdict(list)
    for part in parts:
        family,kind=classification(part)
        part['component_family']=family;part['component_kind']=kind
        part['geometry']=geometry.get(part['id'],{'footprint_area_mm2':None,'pad_area_mm2':None,'issues':[]})
        buckets['family',family].append(part);buckets['type',kind].append(part)
        if kind in ('Resistors','Capacitors','Inductors'):buckets['rollup','RLC combined'].append(part)
    output=[]
    for (level,label),ps in sorted(buckets.items()):
        physical=[p for p in ps if p['physical_eligible']];priced=[p for p in ps if p['price_eligible']]
        rec={'level':level,'label':label,'ids':[p['id'] for p in ps],'references':[p['reference'] for p in ps],'physical_components':len(physical),'pricing_components':len(priced),'costs':{},'histograms':{}}
        for currency in sorted({p['cost']['currency'] for p in priced}):
            population=[p for p in priced if p['cost']['currency']==currency]
            values=[p['cost']['unit_price'] for p in population if p['cost']['unit_price'] is not None]
            rec['costs'][currency]={'known_total':sum(values,D(0)) if values else None,'known':len(values),'eligible':len(population),'complete':len(values)==len(population)}
            rec['histograms']['Unit cost '+currency]=histogram(values)
        for metric,unit in [('mass','g'),('power','W')]:
            values=[p[metric]['value'] for p in physical if p.get(metric) and p[metric]['status']=='known']
            rec[metric]={'known_total':sum(values,D(0)) if values else None,'known':len(values),'eligible':len(physical),'complete':bool(physical) and len(values)==len(physical)}
            rec['histograms'][('Mass' if metric=='mass' else 'Dissipation')+' ('+unit+')']=histogram(values)
        for area in ('footprint_area_mm2','pad_area_mm2'):
            known=[p for p in physical if p['geometry'].get(area) is not None]
            paired=[p for p in known if p.get('power') and p['power']['status']=='known']
            a=sum((p['geometry'][area] for p in paired),D(0));power=sum((p['power']['value'] for p in paired),D(0))
            rec[area]={'known_total':sum((p['geometry'][area] for p in known),D(0)) if known else None,'known':len(known),'eligible':len(physical),
                       'paired_components':len(paired),'paired_area_mm2':a if paired else None,'paired_power_W':power if paired else None,'paired_W_per_mm2':power/a if a else None}
            label='Courtyard' if area=='footprint_area_mm2' else 'Pad copper'
            rec['histograms'][label+' power density (W/mm²)']=histogram([p['power']['value']/p['geometry'][area] for p in paired if p['geometry'][area]>0])
        output.append(rec)
    insights=[]
    families=[g for g in output if g['level']=='family']
    known=[g for g in families if g['power']['known_total'] is not None]
    if known:
        largest=max(known,key=lambda g:g['power']['known_total'])
        insights.append(largest['label']+' has the largest known dissipation subtotal ('+str(largest['power']['known_total'])+' W); unknown observations may change this ranking.')
    for currency in sorted({c for g in families for c in g['costs']}):
        known=[g for g in families if g['costs'].get(currency,{}).get('known_total') is not None]
        if known:
            largest=max(known,key=lambda g:g['costs'][currency]['known_total'])
            insights.append(largest['label']+' has the largest known '+currency+' cost subtotal. Currencies are not implicitly combined.')
    return {'groups':output,'insights':insights,'limits':['Family and type tables are alternative breakdowns; RLC combined is an overlapping rollup, never an additional population.',
        'Type fields take precedence; reference-prefix classifications remain heuristic. Diodes and LEDs are grouped with actives by declared convention.',
        'Power/area is arithmetic over matched known components, not a thermal simulation, heat-flux boundary condition or cooling capability.']}
