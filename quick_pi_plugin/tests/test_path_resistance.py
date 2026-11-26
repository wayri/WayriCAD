"""Analytical finite-element checks for DC resistance versus routed distance."""
import math

import pytest

from quick_pi_plugin.path_resistance import _position, resistance_profiles
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip


def coupon(nx=10,ny=2,current=2):
    mesh,left,right=strip(nx=nx,ny=ny,z=0)
    result=solve(mesh,left,right,sink_current=current)
    pads={'s':dict(position_mm=[0,.5],layers=[0],net='rail'),
          't':dict(position_mm=[10,.5],layers=[0],net='rail')}
    # The first saved track is stored against the walking direction.
    tracks=[dict(id='a',net='rail',layer=0,start_mm=[3,.5],end_mm=[0,.5],length_mm=3),
            dict(id='b',net='rail',layer=0,start_mm=[3,.5],end_mm=[10,.5],length_mm=7)]
    return dict(mesh=mesh,result=result,path_geometry=dict(tracks=tracks,pads=pads),
                geometry=dict(net='rail',terminals=[dict(id='s',label='J1.1'),dict(id='t',label='U1.2')]),
                terminal_units=dict(source_terminals=['s'],loads=[dict(terminals=['t'])]),
                request=dict(net='rail'))


@pytest.mark.parametrize('nx,ny,current',[(2,1,1),(20,5,3)])
def test_uniform_strip_matches_analytical_resistance_at_each_sample(nx,ny,current):
    study=resistance_profiles(coupon(nx,ny,current))
    assert study['status']=='SAMPLED'
    profile=study['profiles'][0]
    assert profile['label']=='J1.1 → U1.2'
    for row in profile['samples']:
        expected=1.724e-8*row['distance_mm']*1e-3/(1e-3*35e-6)
        assert row['resistance_ohm']==pytest.approx(expected,abs=1e-12)
        assert row['distance_mm']==pytest.approx(row['x_mm'])
    assert profile['samples'][-1]['distance_mm']==10


def test_parallel_load_normalization_uses_total_source_current_and_missing_fields_are_unknown():
    data=coupon()
    # An additional 2 A load is colocated at the source. The reviewed strip still carries 2 A.
    data['result']['source_current_A']+=2
    profile=resistance_profiles(data)['profiles'][0]
    assert profile['samples'][-1]['resistance_ohm']==pytest.approx(data['result']['drop_over_current_ohm']/2)
    data['result']['potential_V']=[None if 3<x<7 else v for (x,y,z),v in
                                   zip(data['mesh']['points_mm'],data['result']['potential_V'])]
    study=resistance_profiles(data)
    assert study['status']=='PARTIAL'
    assert next(r for r in study['profiles'][0]['samples'] if r['x_mm']==5)['resistance_ohm'] is None


def test_net_and_layer_ownership_or_track_continuity_required():
    data=coupon()
    data['geometry']['nets']=['rail','other']
    data['mesh']['display_net_domains']=[dict(first_cell=0,end_cell=len(data['mesh']['triangles']),net='other')]
    assert resistance_profiles(data)['status']=='UNAVAILABLE'
    data['path_geometry']['tracks'].pop()
    profile=resistance_profiles(data)['profiles'][0]
    assert profile['status']=='UNAVAILABLE' and not profile['samples'] and profile['length_mm'] is None


def test_arc_uses_saved_sweep_not_its_chord_and_old_arc_interior_is_unknown():
    arc=dict(kind='arc',length_mm=math.pi,mid_mm=[0,1])
    for a,b in [((-1,0),(1,0)),((1,0),(-1,0))]:
        assert _position(arc,a,b,.5)==pytest.approx((0,1))
    del arc['mid_mm']
    assert _position(arc,(-1,0),(1,0),.5) is None


def test_grouped_source_shortest_physical_route_includes_late_pad():
    data=coupon()
    pads=data['path_geometry']['pads']
    # Many disconnected physical pins on the same electrode precede the routed pad.
    for i in range(2100):
        pads[f'extra{i}']=dict(position_mm=[-1,i],layers=[0],net='rail')
    data['terminal_units']['source_terminals']=[*(f'extra{i}' for i in range(2100)),'s']
    study=resistance_profiles(data)
    assert study['status']=='SAMPLED'
    assert study['profiles'][0]['from_pad']=='s' and study['profiles'][0]['to_pad']=='t'
