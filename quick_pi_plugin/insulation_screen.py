"""Bounded post-solve planar spacing screen with explicit engineering assumptions.

No standards table, material group or physical creepage path is inferred.
"""
from __future__ import annotations
from copy import deepcopy
from itertools import combinations
import math
import re

SCHEMA = 'wayricad.pi-insulation-screen/v1'
MAX_NETS = 32
MAX_POLYGONS = 4096
MAX_VERTICES = 200000
MAX_SAMPLES = 2000000


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(ord(c) < 32 for c in value):
        raise ValueError(name+' must be explicit nonempty text, at most 2,000 characters.')
    return value


def _number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError(name+' must be finite and '+('positive.' if positive else 'nonnegative.'))
    return float(value)


def _signed(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name+' must be finite.')
    return float(value)


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get('schema') != SCHEMA:
        raise ValueError('Insulation policy needs schema='+SCHEMA+'.')
    allowed = {'schema','rule_citation','material','environment','minimum_clearance_mm',
               'minimum_creepage_mm','voltage_limit_V','voltage_reference','reviewed_creepage'}
    if set(policy)-allowed:
        raise ValueError('Unsupported insulation policy fields.')
    output = deepcopy(policy)
    for key in ('rule_citation','material','environment'):
        _text(output.get(key), key)
    for key in ('minimum_clearance_mm','minimum_creepage_mm','voltage_limit_V'):
        output[key] = _number(output.get(key), key, positive=True)
    reference = output.get('voltage_reference')
    if not isinstance(reference, dict) or reference.get('reviewed') is not True:
        raise ValueError('Explicitly review the common voltage domain or conservative voltage envelope.')
    if reference.get('mode') == 'common-domain':
        if set(reference)-{'mode','reviewed','domain','net_offsets_V'}:
            raise ValueError('Unsupported common-domain voltage fields.')
        _text(reference.get('domain'), 'Common voltage domain')
        if not isinstance(reference.get('net_offsets_V'), dict):
            raise ValueError('Supply explicit offsets in volts for every screened net.')
        for net, offset in reference['net_offsets_V'].items():
            _text(net, 'Voltage-domain net');_signed(offset, 'Voltage-domain offset')
    elif reference.get('mode') == 'conservative-envelope':
        if set(reference)-{'mode','reviewed','citation','maximum_voltage_difference_V'}:
            raise ValueError('Unsupported conservative-envelope voltage fields.')
        _text(reference.get('citation'), 'Conservative voltage envelope evidence')
        _number(reference.get('maximum_voltage_difference_V'), 'Maximum inter-net voltage')
    else:
        raise ValueError('Choose common-domain or conservative-envelope voltage_reference mode.')
    measurements = output.setdefault('reviewed_creepage', [])
    if not isinstance(measurements, list) or len(measurements) > MAX_NETS*(MAX_NETS-1)//2:
        raise ValueError('Reviewed creepage measurements exceed the pair budget.')
    seen = set()
    for record in measurements:
        if not isinstance(record, dict) or set(record) != {'net_a','net_b','length_mm','evidence','reviewed'} or record.get('reviewed') is not True:
            raise ValueError('Each reviewed creepage needs net_a/net_b, length_mm, evidence and reviewed=true.')
        a,b = _text(record['net_a'],'Creepage net'),_text(record['net_b'],'Creepage net')
        pair = tuple(sorted((a,b)))
        if a == b or pair in seen:
            raise ValueError('Reviewed creepage net pairs must be distinct and unique.')
        seen.add(pair)
        _number(record['length_mm'], 'Reviewed creepage length', positive=True)
        _text(record['evidence'], 'Reviewed creepage surface/path evidence, including slots and obstacles')
    return output


def _cases(bundle):
    if not isinstance(bundle, dict) or not isinstance(bundle.get('batch'), dict):
        raise ValueError('Supply a completed multi-net batch bundle.')
    batch = bundle['batch'];digest = batch.get('source_sha256')
    if not isinstance(digest, str) or not re.fullmatch('[a-fA-F0-9]{64}', digest) or bundle.get('source_sha256') != digest:
        raise ValueError('Batch needs one consistent original saved-PCB SHA-256.')
    cases = batch.get('cases')
    if not isinstance(cases, list) or not 2 <= len(cases) <= MAX_NETS:
        raise ValueError('Screen 2 to 32 solved distinct nets from one saved source.')
    selected = {};excluded = []
    for case in cases:
        if not isinstance(case, dict):raise ValueError('Invalid batch case.')
        electrical = case.get('electrical', {})
        if case.get('status') != 'COMPLETED' or not isinstance(electrical,dict) or not isinstance(electrical.get('result'),dict):
            excluded.append(str(case.get('name','Unknown case')));continue
        geometry = electrical.get('geometry') or electrical.get('mesh',{}).get('geometry') or {}
        net = electrical.get('request',{}).get('net') or geometry.get('net')
        _text(net, 'Solved net')
        bindings = [case.get('source_sha256')]
        if geometry.get('source_sha256') is not None:bindings.append(geometry['source_sha256'])
        if electrical.get('source_sha256') is not None:bindings.append(electrical['source_sha256'])
        if any(value != digest for value in bindings):
            raise ValueError('Every solved net must retain the same original source SHA-256.')
        if (geometry and geometry.get('net') != net) or net in selected:
            raise ValueError('Select one unambiguous single-net operating point per distinct net.')
        selected[net] = electrical
    if len(selected) < 2:
        raise ValueError('At least two completed distinct solved nets are required.')
    return digest,selected,excluded


def _geometry(geometry):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    if not geometry.get('source_sha256'):
        raise ValueError('Original copper geometry source binding is unavailable.')
    if geometry.get('incomplete') or geometry.get('unsupported') or geometry.get('status') in ('FAILED','INCOMPLETE','UNKNOWN'):
        raise ValueError('Copper geometry is incomplete or unsupported.')
    tolerance = _number(geometry.get('curve_tolerance_mm'), 'Copper curve tolerance')
    layers = geometry.get('layers')
    if not isinstance(layers,list) or not layers or len(layers)>32:
        raise ValueError('Copper layers are missing or outside the supported budget.')
    counts = [0,0];output = {};seen = set()
    def ring(points):
        if not isinstance(points,list) or len(points)<3:
            raise ValueError('Copper polygon ring is incomplete.')
        counts[1] += len(points)
        if counts[1]>MAX_VERTICES:raise ValueError('Copper geometry exceeds the vertex budget.')
        for point in points:
            if not isinstance(point,(list,tuple)) or len(point)!=2:
                raise ValueError('Copper polygon point requires XY millimetres.')
            for coordinate in point:_signed(coordinate,'Copper coordinate')
        return points
    for layer in layers:
        if not isinstance(layer,dict) or type(layer.get('id')) is not int or layer['id'] in seen:
            raise ValueError('Copper layer identities are missing or ambiguous.')
        seen.add(layer['id']);polygons = layer.get('polygons')
        if not isinstance(polygons,list):raise ValueError('Copper polygons are missing.')
        shapes=[]
        for record in polygons:
            counts[0] += 1
            if counts[0]>MAX_POLYGONS:raise ValueError('Copper geometry exceeds the polygon budget.')
            if not isinstance(record,dict) or not isinstance(record.get('holes',[]),list):
                raise ValueError('Invalid copper polygon or holes.')
            shape=Polygon(ring(record.get('outer')), [ring(hole) for hole in record.get('holes',[])])
            if not shape.is_valid or shape.is_empty or shape.area<=0:
                raise ValueError('Invalid copper polygons cannot establish clearance.')
            shapes.append(shape)
        if shapes:
            combined=unary_union(shapes)
            if not combined.is_valid:raise ValueError('Copper union is invalid.')
            output[layer['id']]=combined
    if not output:raise ValueError('No complete copper polygons are available.')
    return output,tolerance


def _potentials(electrical):
    values=electrical['result'].get('potential_V')
    if not isinstance(values,list) or not values or len(values)>MAX_SAMPLES:
        raise ValueError('Complete solved voltage samples are unavailable or exceed the budget.')
    points=electrical.get('mesh',{}).get('points_mm')
    if not isinstance(points,list) or len(points)!=len(values):
        raise ValueError('Complete solved voltage coverage requires one potential per mesh node.')
    # Disconnected or unknown nodes cannot establish an envelope for all copper.
    checked=[_signed(value,'Solved copper potential') for value in values]
    return min(checked),max(checked)


def screen(bundle, policy):
    """Compare same-layer copper spacing with entered limits; never certify a PCB."""
    from shapely.errors import ShapelyError
    policy=validate_policy(policy);digest,cases,excluded=_cases(bundle)
    reference=policy['voltage_reference'];prepared={};voltage={};issues={}
    for net,electrical in cases.items():
        issues[net]=[]
        try:prepared[net]=_geometry(electrical.get('geometry') or electrical.get('mesh',{}).get('geometry') or {})
        except (ValueError,TypeError,KeyError,ShapelyError) as error:issues[net].append(str(error))
        try:
            voltage[net]=_potentials(electrical)
            if reference['mode']=='common-domain':
                if net not in reference['net_offsets_V']:raise ValueError('No reviewed common-domain offset for '+net+'.')
                offset=reference['net_offsets_V'][net]
                voltage[net]=tuple(_signed(value+offset,'Referenced voltage') for value in voltage[net])
        except (ValueError,TypeError) as error:issues[net].append(str(error));voltage.pop(net,None)
    from shapely.ops import nearest_points
    measurements={tuple(sorted((m['net_a'],m['net_b']))):m for m in policy['reviewed_creepage']}
    if any(set(pair)-set(cases) for pair in measurements):raise ValueError('Reviewed creepage references an unscreened net.')
    pairs=[]
    for a,b in combinations(sorted(cases),2):
        row={'net_a':a,'net_b':b,'status':'UNKNOWN','clearance_status':'UNKNOWN','creepage_status':'UNKNOWN',
             'clearance_mm':None,'clearance_lower_bound_mm':None,'creepage_mm':None,
             'maximum_voltage_difference_V':None,'closest_points_mm':None,'layer_id':None,
             'issues':list(issues[a])+list(issues[b])}
        if a in voltage and b in voltage:
            va,vb=voltage[a],voltage[b]
            delta=(reference['maximum_voltage_difference_V'] if reference['mode']=='conservative-envelope'
                   else max(abs(va[0]-vb[1]),abs(va[1]-vb[0])))
            row['maximum_voltage_difference_V']=_number(delta,'Inter-net voltage')
            if delta>policy['voltage_limit_V']:row['issues'].append('Voltage exceeds the entered rule applicability limit.')
        if a in prepared and b in prepared:
            la,ta=prepared[a];lb,tb=prepared[b];closest=None
            for layer in sorted(set(la)&set(lb)):
                distance=float(la[layer].distance(lb[layer]))
                _number(distance,'Planar polygon distance')
                if closest is None or distance<closest[0]:
                    p,q=nearest_points(la[layer],lb[layer]);closest=(distance,layer,[list(p.coords[0]),list(q.coords[0])])
            if closest:
                distance,layer,points=closest
                row.update(clearance_mm=distance,clearance_lower_bound_mm=max(0.,distance-ta-tb),
                           layer_id=layer,closest_points_mm=points)
            else:row['issues'].append('No common copper layer; 3D air distances are not screened.')
        measurement=measurements.get((a,b))
        if measurement:
            row['creepage_mm']=float(measurement['length_mm']);row['creepage_evidence']=measurement['evidence']
        else:row['issues'].append('Creepage UNKNOWN: supply a reviewed surface path/measurement accounting for slots and obstacles.')
        applicable=(row['maximum_voltage_difference_V'] is not None and row['maximum_voltage_difference_V']<=policy['voltage_limit_V'])
        geometry_valid=(a in prepared and b in prepared and a in voltage and b in voltage)
        if applicable and geometry_valid and row['clearance_lower_bound_mm'] is not None:
            row['clearance_status']=('BELOW_ENTERED_LIMIT' if row['clearance_lower_bound_mm']<policy['minimum_clearance_mm'] else 'MEETS_ENTERED_LIMIT')
        if applicable and geometry_valid and measurement:
            row['creepage_status']=('BELOW_ENTERED_LIMIT' if row['creepage_mm']<policy['minimum_creepage_mm'] else 'MEETS_ENTERED_LIMIT')
        statuses=(row['clearance_status'],row['creepage_status'])
        row['status']=('REVIEW_REQUIRED' if 'BELOW_ENTERED_LIMIT' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'SCREENED')
        pairs.append(row)
    status=('REVIEW_REQUIRED' if any(p['status']=='REVIEW_REQUIRED' for p in pairs) else
            'UNKNOWN' if excluded or any(p['status']=='UNKNOWN' for p in pairs) else 'SCREENED')
    return {'schema':SCHEMA,'status':status,'source_sha256':digest,'policy':policy,'pairs':pairs,
            'excluded_cases':excluded,'potential_envelopes_V':{net:list(value) for net,value in voltage.items()},
            'notice':'Engineering screen only; no insulation certification. Same-layer polygon spacing is not physical creepage. '
                     'Board thickness, inter-layer paths, coatings, transients and unscreened nets require separate review. '
                     'Clearance lower bounds subtract both declared curve tolerances; closest points belong to extracted polygons.'}
