import copy
import pytest
from trace_impedance_plugin.protocol_validation import screen_protocols


def data(differential=False,target=50,review=False):
    discovery={'profiles':[{'id':'rf','title':'RF','target_ohm':target,'differential':differential}],
               'matches':[{'net':'RF_OUT','profile_id':'rf','confidence':.95,'review_required':review,
                           'differential':differential,'mate':'RF_N' if differential else None}]}
    extraction={'coverage':{'complete':True},'nets':[{'net':'RF_OUT','status':'ok','pads':['U1.1','J1.1'],'sections':[
        {'kind':'track','section_id':'track:0','status':'ok','impedance_ohm':50.,'layer':'F.Cu'}]}]}
    return discovery,extraction


def test_matching_section_is_only_a_screen_and_input_is_unchanged():
    d,e=data();before=copy.deepcopy((d,e));result=screen_protocols(d,e)
    assert result['findings'][0]['status']=='within_screening_target'
    assert result['protocol_compliance']=='not_evaluated'
    assert (d,e)==before


@pytest.mark.parametrize('z,suggestion',[(80,'Increase width'),(30,'Reduce width')])
def test_outside_target_has_directional_correction_and_section_id(z,suggestion):
    d,e=data();e['nets'][0]['sections'][0]['impedance_ohm']=z
    row=screen_protocols(d,e)['findings'][0]
    assert row['status']=='outside_target'
    issue=next(i for i in row['issues'] if i['code']=='Z0_OUTSIDE_TARGET')
    assert suggestion in issue['suggestion'] and issue['section_id']=='track:0'


def test_differential_never_substitutes_twice_single_ended_impedance():
    d,e=data(differential=True,target=100)
    row=screen_protocols(d,e)['findings'][0]
    assert row['status']=='unresolved'
    assert row['checks'][0]['measured_ohm'] is None
    assert any(i['code']=='COUPLED_Z_UNRESOLVED' for i in row['issues'])


def test_missing_target_and_ambiguous_fuzzy_identity_never_pass():
    for target,review in ((None,False),(50,True)):
        d,e=data(target=target,review=review)
        assert screen_protocols(d,e)['findings'][0]['status']!='within_screening_target'


def test_partial_cancelled_budget_and_unknown_fields_never_pass():
    d,e=data();e['coverage']['complete']=False;e['nets'][0]['status']='partial'
    e['nets'][0]['sections'][0].update(status='partial',impedance_ohm=None)
    result=screen_protocols(d,e)
    assert result['status']=='incomplete'
    assert result['findings'][0]['status']=='unresolved'


@pytest.mark.parametrize('targets',[{'rf':0},{'rf':True},{'rf':float('nan')},{'typo':50}])
def test_bad_or_unused_target_overrides_rejected(targets):
    with pytest.raises(ValueError):screen_protocols(*data(),targets=targets)
