"""Analytical polygon distances and explicit insulation-screen unknowns."""
from copy import deepcopy
import math
import pytest
from quick_pi_plugin.insulation_screen import SCHEMA, screen

DIGEST='a'*64


def rectangle(x0,y0,x1,y1):
    return {'outer':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],'holes':[]}


def case(net,polygon,voltage,layer=0,tolerance=0.):
    return {'name':net,'status':'COMPLETED','source_sha256':DIGEST,
            'electrical':{'request':{'net':net},'result':{'potential_V':voltage},
                'mesh':{'points_mm':[[0.,0.,0.] for _ in voltage]},
                'geometry':{'net':net,'source_sha256':DIGEST,'curve_tolerance_mm':tolerance,
                            'layers':[{'id':layer,'polygons':[polygon]}]}}}


def batch():
    return {'source_sha256':DIGEST,'batch':{'source_sha256':DIGEST,'cases':[
        case('LOW',rectangle(0,0,1,1),[0.,.1]),
        case('HIGH',rectangle(4,0,5,1),[12.,11.9])]}}


def policy():
    return {'schema':SCHEMA,'rule_citation':'Reviewed project rule X, clause 2 (example only)',
        'material':'Explicit test laminate assumptions','environment':'Explicit test environment',
        'minimum_clearance_mm':2.,'minimum_creepage_mm':4.,'voltage_limit_V':50.,
        'voltage_reference':{'mode':'common-domain','reviewed':True,'domain':'Reviewed same DC reference',
                             'net_offsets_V':{'LOW':0.,'HIGH':0.}}}


def measurement(length=5.):
    return {'net_a':'LOW','net_b':'HIGH','length_mm':length,'reviewed':True,
            'evidence':'Reviewed surface route A-B, measured around slot and obstacle boundaries.'}


def test_actual_polygon_clearance_and_voltage_extrema_leave_creepage_unknown():
    inputs=batch();rules=policy();before=deepcopy(inputs);rules_before=deepcopy(rules)
    result=screen(inputs,rules);pair=result['pairs'][0]
    assert pair['clearance_mm']==3.
    assert pair['clearance_lower_bound_mm']==3.
    assert pair['maximum_voltage_difference_V']==12.
    assert pair['closest_points_mm']==[[4.,0.],[1.,0.]]
    assert pair['clearance_status']=='MEETS_ENTERED_LIMIT'
    assert pair['creepage_mm'] is None and pair['creepage_status']=='UNKNOWN'
    assert result['status']=='UNKNOWN'
    assert inputs==before and rules==rules_before


def test_curve_tolerance_is_subtracted_before_limit_comparison():
    inputs=batch()
    for row in inputs['batch']['cases']:row['electrical']['geometry']['curve_tolerance_mm']=.2
    rules=policy();rules['minimum_clearance_mm']=2.7
    pair=screen(inputs,rules)['pairs'][0]
    assert pair['clearance_mm']==3.
    assert pair['clearance_lower_bound_mm']==pytest.approx(2.6)
    assert pair['clearance_status']=='BELOW_ENTERED_LIMIT'
    assert pair['status']=='REVIEW_REQUIRED'


def test_surface_measurement_is_separate_from_planar_gap():
    rules=policy();rules['reviewed_creepage']=[measurement()]
    result=screen(batch(),rules);pair=result['pairs'][0]
    assert pair['creepage_mm']==5. and pair['clearance_mm']==3.
    assert pair['creepage_status']=='MEETS_ENTERED_LIMIT'
    assert result['status']=='SCREENED'
    rules['reviewed_creepage'][0]['length_mm']=3.
    assert screen(batch(),rules)['pairs'][0]['creepage_status']=='BELOW_ENTERED_LIMIT'


def test_holes_are_respected_and_polygon_overlap_is_zero():
    inputs=batch()
    outer=rectangle(0,0,10,10);outer['holes']=[[[2,2],[8,2],[8,8],[2,8]]]
    inputs['batch']['cases'][0]['electrical']['geometry']['layers'][0]['polygons']=[outer]
    inputs['batch']['cases'][1]['electrical']['geometry']['layers'][0]['polygons']=[rectangle(4,4,6,6)]
    assert screen(inputs,policy())['pairs'][0]['clearance_mm']==2.
    inputs['batch']['cases'][1]['electrical']['geometry']['layers'][0]['polygons']=[rectangle(0,0,1,1)]
    assert screen(inputs,policy())['pairs'][0]['clearance_mm']==0.


def test_common_domain_offsets_and_reviewed_envelope_are_explicit_alternatives():
    rules=policy();rules['voltage_reference']['net_offsets_V']['LOW']=-100.
    pair=screen(batch(),rules)['pairs'][0]
    assert pair['maximum_voltage_difference_V']==112.
    assert pair['clearance_status']=='UNKNOWN'
    rules['voltage_reference']={'mode':'conservative-envelope','reviewed':True,
        'maximum_voltage_difference_V':25.,'citation':'Reviewed DC plus transient worst-case envelope'}
    assert screen(batch(),rules)['pairs'][0]['maximum_voltage_difference_V']==25.


@pytest.mark.parametrize('mutation', ['null_sample','missing_tolerance','bad_polygon','incomplete_geometry','missing_geometry','no_common_layer'])
def test_incomplete_geometry_or_samples_never_report_clearance_success(mutation):
    inputs=batch();electrical=inputs['batch']['cases'][0]['electrical'];geometry=electrical['geometry']
    if mutation=='null_sample':electrical['result']['potential_V'][0]=None
    elif mutation=='missing_tolerance':geometry.pop('curve_tolerance_mm')
    elif mutation=='bad_polygon':geometry['layers'][0]['polygons'][0]['outer']=[[0,0],[1,1],[0,1],[1,0]]
    elif mutation=='incomplete_geometry':geometry['incomplete']=True
    elif mutation=='missing_geometry':electrical.pop('geometry');electrical['source_sha256']=DIGEST
    elif mutation=='no_common_layer':geometry['layers'][0]['id']=31
    pair=screen(inputs,policy())['pairs'][0]
    assert pair['clearance_status']=='UNKNOWN'
    assert pair['status']=='UNKNOWN'


@pytest.mark.parametrize('field,value', [('minimum_clearance_mm',float('nan')),('minimum_creepage_mm',-1.),
    ('voltage_limit_V',0.),('material',''),('rule_citation','')])
def test_invalid_rule_inputs_are_rejected(field,value):
    rules=policy();rules[field]=value
    with pytest.raises(ValueError):screen(batch(),rules)


def test_foreign_source_and_duplicate_net_are_rejected():
    inputs=batch();inputs['batch']['cases'][0]['electrical']['geometry']['source_sha256']='b'*64
    with pytest.raises(ValueError,match='same original source'):screen(inputs,policy())
    inputs=batch();inputs['batch']['cases'][1]=deepcopy(inputs['batch']['cases'][0])
    with pytest.raises(ValueError,match='distinct net'):screen(inputs,policy())


def test_failed_cases_are_excluded_and_leave_overall_screen_unknown():
    inputs=batch();inputs['batch']['cases'].append({'name':'FAILED RAIL','status':'FAILED'})
    rules=policy();rules['reviewed_creepage']=[measurement()]
    result=screen(inputs,rules)
    assert result['status']=='UNKNOWN'
    assert result['excluded_cases']==['FAILED RAIL']
    inputs['batch']['cases'][0]['status']='FAILED'
    with pytest.raises(ValueError,match='At least two'):screen(inputs,rules)


def test_reviewed_reference_and_path_evidence_are_required():
    rules=policy();rules['voltage_reference']['reviewed']=False
    with pytest.raises(ValueError,match='Explicitly review'):screen(batch(),rules)
    rules=policy();rules['reviewed_creepage']=[measurement()];rules['reviewed_creepage'][0]['evidence']=''
    with pytest.raises(ValueError,match='surface/path evidence'):screen(batch(),rules)
    rules=policy();rules['voltage_reference']['net_offsets_V'].pop('LOW')
    assert screen(batch(),rules)['pairs'][0]['clearance_status']=='UNKNOWN'


def test_nonfinite_geometry_and_coordinate_budget_are_unknown(monkeypatch):
    from quick_pi_plugin import insulation_screen as module
    inputs=batch();inputs['batch']['cases'][0]['electrical']['geometry']['layers'][0]['polygons'][0]['outer'][0][0]=math.inf
    assert screen(inputs,policy())['pairs'][0]['clearance_status']=='UNKNOWN'
    monkeypatch.setattr(module,'MAX_VERTICES',3)
    assert screen(batch(),policy())['pairs'][0]['clearance_status']=='UNKNOWN'


def test_truncated_potentials_cannot_establish_complete_voltage_envelope():
    value=batch();rules=policy();rules['reviewed_creepage']=[measurement()]
    value['batch']['cases'][1]['electrical']['result']['potential_V']=[0.]
    result=screen(value,rules)
    assert result['status']=='UNKNOWN'
    assert result['pairs'][0]['maximum_voltage_difference_V'] is None
    assert any('one potential per mesh node' in issue for issue in result['pairs'][0]['issues'])
