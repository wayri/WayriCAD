"""Bounded same-layer straight-trace proximity; optional local ideal coupling.

Colour represents edge-gap closeness within an explicit search radius, never
voltage or field intensity. Coupled values reuse the existing qualified local
model, with explicit hypothetical reference/material/edge inputs.
"""
from __future__ import annotations
import math
import time
from collections import defaultdict
from .crosstalk import parallel_overlap, coupled_modes, matched_step, C_MM_NS, LIMITATIONS

LIMITS = dict(max_tracks=200000, max_cells=500000, max_comparisons=200000,
              max_pairs=2000, max_models=32, seconds=15.)
NOTICE = ('Geometric exposure map: colour is edge-gap closeness inside the chosen search radius, '
          'not electromagnetic field, interference voltage or compliance. Only straight tracks on '
          'the same layer are searched. Arcs, vias, pads, zones, broadside and crossing-field coupling '
          'are not solved. Local NEXT requires explicit ideal reference/material/edge inputs; '
          'its isolated matched-end section peaks are not summed into a route waveform.')


def settings_checked(settings=None):
    raw = dict(settings or {})
    if set(raw)-{'radius_mm','nets','layers','model',*LIMITS}:
        raise ValueError('Unknown neighbour-map settings.')
    out = dict(radius_mm=1., nets=[], layers=[], model=None, **LIMITS)
    out.update(raw)
    for key in ('radius_mm','seconds'):
        value = out[key]
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0 < value <= (20 if key=='radius_mm' else 60):
            raise ValueError(key+' must be positive and bounded (radius <=20 mm, time <=60 s).')
    for key in LIMITS.keys()-{'seconds'}:
        if isinstance(out[key],bool) or not isinstance(out[key],int) or not 1 <= out[key] <= LIMITS[key]:
            raise ValueError(key+' exceeds its supported positive budget.')
    for key in ('nets','layers'):
        if not isinstance(out[key],list) or len(out[key])>20000 or any(not isinstance(v,str) or not v for v in out[key]):
            raise ValueError(key+' must list exact nonempty names.')
    model = out['model']
    if model is not None:
        if not isinstance(model,dict) or set(model)!={'height_mm','epsilon_r','copper_mm','rise_ns','swing_v','reference_layer'}:
            raise ValueError('Local model needs height_mm, epsilon_r, copper_mm, rise_ns, swing_v and reference_layer.')
        for key in ('height_mm','epsilon_r','rise_ns','swing_v','copper_mm'):
            value=model[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (key!='copper_mm' and value==0):
                raise ValueError('Invalid local model '+key)
        if model['epsilon_r']<1 or not isinstance(model['reference_layer'],str) or not model['reference_layer']:
            raise ValueError('Explicit reference copper layer and Er >=1 required.')
    return out


def _closest(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0.,min(1.,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return [a[0]+t*dx,a[1]+t*dy]


def closest_segments(a,b,c,d):
    """Exact planar segment closest points, including nonparallel intersection."""
    u=[b[0]-a[0],b[1]-a[1]];v=[d[0]-c[0],d[1]-c[1]]
    cross=lambda p,q:p[0]*q[1]-p[1]*q[0]
    det=cross(u,v)
    if abs(det)>1e-15:
        w=[c[0]-a[0],c[1]-a[1]];s=cross(w,v)/det;t=cross(w,u)/det
        if 0<=s<=1 and 0<=t<=1:
            p=[a[0]+s*u[0],a[1]+s*u[1]]
            return 0.,p,p
    candidates=[(a,_closest(a,c,d)),(b,_closest(b,c,d)),
                (_closest(c,a,b),c),(_closest(d,a,b),d)]
    p,q=min(candidates,key=lambda pair:math.dist(*pair))
    return math.dist(p,q),list(p),list(q)


def _cells(row,cell,padding=0.):
    # Subdivide the line, not its whole bounding box: diagonal tracks retain
    # linear index size. Each sub-box is expanded by the exact search radius.
    a,b=row['start_mm'],row['end_mm'];length=math.dist(a,b)
    count=max(1,math.ceil(length/cell));seen=set()
    for i in range(count):
        p=[a[k]+(b[k]-a[k])*i/count for k in (0,1)]
        q=[a[k]+(b[k]-a[k])*(i+1)/count for k in (0,1)]
        for x in range(math.floor((min(p[0],q[0])-padding)/cell),math.floor((max(p[0],q[0])+padding)/cell)+1):
            for y in range(math.floor((min(p[1],q[1])-padding)/cell),math.floor((max(p[1],q[1])+padding)/cell)+1):
                key=(row['layer'],x,y)
                if key not in seen:
                    seen.add(key);yield key


def map_segments(segments,settings=None,*,cancelled=None,guard=None):
    """Pure geometric engine; returns explicit incomplete coverage on budgets."""
    options=settings_checked(settings);started=time.monotonic();warnings=[]
    if guard:guard()
    def check():
        if cancelled and cancelled():raise InterruptedError('Neighbour-map analysis cancelled.')
        if time.monotonic()-started>options['seconds']:raise _Budget('Time budget reached.')
    rows=[];grid=defaultdict(list);references=0;comparisons=0;visits=0;models=0;pairs=[]
    seen=set();radius=options['radius_mm'];cell=max(1.,2*radius)
    try:
        for source in segments:
            check()
            if len(rows)>=options['max_tracks']:raise _Budget('Track budget reached.')
            if options['layers'] and source['layer'] not in options['layers']:continue
            row=dict(source)
            a,b=row['start_mm'],row['end_mm'];width=row['width_mm']
            if any(not math.isfinite(v) or abs(v)>1e6 for v in [*a,*b,width]) or width<=0 or width>100:
                raise ValueError('Invalid straight-track coordinates or width.')
            if math.dist(a,b)<=1e-9:continue
            index=len(rows);rows.append(row)
            for key in _cells(row,cell,width/2):
                check();references+=1
                if references>options['max_cells']:raise _Budget('Spatial-index reference budget reached.')
                grid[key].append(index)
        for i,a in enumerate(rows):
            check()
            if options['nets'] and a['net'] not in options['nets']:continue
            candidates=set()
            for key in _cells(a,cell,radius+a['width_mm']/2):
                check()
                for j in grid.get(key,()):
                    visits+=1
                    if visits%128==0:check()
                    if visits>options['max_comparisons']*4:raise _Budget('Spatial candidate-visit budget reached.')
                    candidates.add(j)
                    if len(candidates)>options['max_comparisons']:raise _Budget('Dense local candidate budget reached.')
            for j in sorted(candidates):
                if j==i:continue
                b=rows[j]
                if a['net']==b['net']:continue
                key=(min(i,j),max(i,j))
                if key in seen:continue
                check()
                if comparisons>=options['max_comparisons']:raise _Budget('Pair comparison budget reached.')
                comparisons+=1;seen.add(key)
                distance,p,q=closest_segments(a['start_mm'],a['end_mm'],b['start_mm'],b['end_mm'])
                gap=distance-(a['width_mm']+b['width_mm'])/2
                if gap>radius+1e-9:continue
                if len(pairs)>=options['max_pairs']:raise _Budget('Map output pair budget reached; narrow nets/layers/radius.')
                overlap=parallel_overlap(dict(a,kind='track',geometry='straight',offset_mm=0.,item_uuids=[a['id']]),
                                         dict(b,kind='track',geometry='straight',offset_mm=0.,item_uuids=[b['id']]))
                pair=dict(id=len(pairs),a=a,b=b,layer=a['layer'],gap_mm=gap,
                          location_mm=[(p[k]+q[k])/2 for k in (0,1)],
                          parallel_length_mm=overlap['length_mm'] if overlap else 0.,
                          closeness=max(0.,min(1.,1-max(0.,gap)/radius)),
                          next_peak_v=None,coupling=None,coupling_status='UNKNOWN',
                          reason='No explicit local reference/material/edge model supplied.')
                if options['model'] is not None:
                    model=options['model'];pair['reason']='Only positive-gap, parallel equal-width sections support the local model.'
                    if overlap and gap>0 and abs(a['width_mm']-b['width_mm'])<=1e-6:
                        if models>=options['max_models']:
                            pair['reason']='Local coupled-model budget reached; geometric evidence retained.'
                        elif a['layer']==model['reference_layer']:
                            pair['reason']='Signal and reference layers must differ.'
                        else:
                            models+=1
                            try:
                                modes=coupled_modes(a['width_mm'],gap,model['height_mm'],model['epsilon_r'],model['copper_mm'])
                                response=matched_step(modes['z_even_ohm'],modes['z_odd_ohm'],overlap['length_mm']*math.sqrt(model['epsilon_r'])/C_MM_NS,model['rise_ns'],model['swing_v'])
                                pair.update(coupling_status='ASSUMED_REFERENCE',next_peak_v=response['next_peak_v'],
                                            coupling=modes['coupling'],modes=modes,local_response=response,
                                            reason='Hypothetical isolated matched-end section; actual reference continuity and terminal direction are unresolved.')
                                if modes['coupling_numerical_status']=='BELOW_NUMERICAL_FLOOR':
                                    pair.update(coupling_status='BELOW_NUMERICAL_FLOOR',next_peak_v=None,
                                                reason='Coupling is below the local solver numerical floor; no resolved NEXT voltage is claimed.')
                            except ValueError as error:pair['reason']=str(error)
                pairs.append(pair)
    except _Budget as error:warnings.append(str(error))
    check_cancel=cancelled and cancelled()
    if check_cancel:raise InterruptedError('Neighbour-map analysis cancelled.')
    if guard:guard()
    pairs.sort(key=lambda p:(-p['closeness'],-p['parallel_length_mm'],p['a']['id'],p['b']['id']))
    for index,pair in enumerate(pairs):pair['id']=index
    return dict(schema='wayricad.si-neighbours/v1',status='INCOMPLETE' if warnings else 'REVIEW',
                settings=options,pairs=pairs,warnings=warnings,notice=NOTICE,model_limitations=list(LIMITATIONS),
                coverage=dict(indexed_tracks=len(rows),index_references=references,comparisons=comparisons,
                              candidate_visits=visits,local_model_attempts=models,local_models=sum(p['next_peak_v'] is not None for p in pairs),
                              pair_count=len(pairs),complete_search=not warnings),elapsed_seconds=time.monotonic()-started)


class _Budget(Exception):pass


def attach_study(report,study):
    """Link explicit study section evidence by exact saved item UUIDs.

    A merged study run may exceed the mapped track extent: its local section
    peak is retained separately, never attributed to a shorter map segment.
    """
    if not study.get('source_fingerprints') or study['source_fingerprints']!=report.get('source_fingerprints'):
        raise ValueError('Study and neighbour map must have identical saved-source fingerprints.')
    index=defaultdict(list);sections=0
    for pair in study.get('crosstalk',[]):
        for section in pair.get('sections',[]):
            sections+=1
            if sections>16384:raise ValueError('Study exceeds the supported section-link budget.')
            value=section.get('next_peak_v')
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:continue
            a=set(section.get('aggressor_item_uuids',[]));b=set(section.get('victim_item_uuids',[]))
            if len(a)+len(b)>20000:raise ValueError('Study section item budget exceeded.')
            evidence=dict(pair_id=pair['id'],status=section.get('status','UNKNOWN'),next_peak_v=value,
                          section_length_mm=section['length_mm'],reference_geometry=section.get('reference_geometry'),
                          scope='Existing explicit study section; its extent may exceed this map segment. No section peaks are added.')
            for identifier in a:index[identifier].append((b,evidence))
            for identifier in b:index[identifier].append((a,evidence))
    links=0
    for row in report['pairs']:
        matches=[evidence for opposite,evidence in index.get(row['a']['id'],[]) if row['b']['id'] in opposite]
        row['study_sections']=matches[:16];links+=len(row['study_sections'])
        if len(matches)>16:row['study_sections_truncated']=True
        if links>4096:raise ValueError('Study-to-map section link budget exceeded; narrow the map.')
    report['coverage']['linked_study_sections']=links
    return report


def map_board(board,settings=None,*,cancelled=None,guard=None):
    """Read native tracks without modifying board geometry or project files."""
    options=settings_checked(settings);omitted=defaultdict(int);started=time.monotonic()
    enabled={str(board.GetLayerName(layer)) for layer in board.GetEnabledLayers().CuStack()}
    if set(options['layers'])-enabled:raise ValueError('Selected copper layer is not enabled.')
    if options['model'] and options['model']['reference_layer'] not in enabled:
        raise ValueError('Local reference must name an enabled copper layer.')
    def extract():
        for item in board.GetTracks():
            if cancelled and cancelled():raise InterruptedError('Neighbour-map extraction cancelled.')
            if time.monotonic()-started>options['seconds']:raise _Budget('Extraction time budget reached.')
            if item.GetClass()!='PCB_TRACK':omitted[item.GetClass()]+=1;continue
            net=str(item.GetNetname())
            if not net:omitted['unconnected_tracks']+=1;continue
            a,b=item.GetStart(),item.GetEnd()
            yield dict(id=str(item.m_Uuid.AsString()),net=net,layer=str(board.GetLayerName(item.GetLayer())),
                       start_mm=[a.x/1e6,a.y/1e6],end_mm=[b.x/1e6,b.y/1e6],width_mm=item.GetWidth()/1e6)
    result=map_segments(extract(),options,cancelled=cancelled,guard=guard)
    result['coverage']['omitted_geometry']=dict(omitted)
    result['coverage']['omitted_counts_complete']=result['coverage']['complete_search']
    return result
