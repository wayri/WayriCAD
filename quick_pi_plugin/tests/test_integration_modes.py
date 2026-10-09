"""Contracts at the boundary between upstream and added analysis modes."""
import numpy as np
import pytest
from quick_pi_plugin import service
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip, combine


@pytest.mark.parametrize('payload',[
    {'action':'solve','load_resistance_ohm':10,'sinks':[{'terminal':'P1','current_A':1}]},
    {'action':'sweep','sinks':[{'terminal':'P1','current_A':1}]},
    {'action':'sweep','source_current_limit':2},
    {'action':'sweep','sink_min_voltage':1},
])
def test_unsupported_mode_combinations_fail_before_board_io(payload):
    with pytest.raises(ValueError,match='require|do not evaluate'):service.execute(payload)


def test_voltage_driven_load_preserves_added_source_and_sink_limits():
    mesh,source,sink=strip();mesh['terminal_nodes']={'source':source,'sink':sink}
    request={'source_terminal':'source','sink_terminal':'sink','source_voltage':3.3,
             'load_resistance_ohm':10,'sink_current':1.,'source_current_limit':.1,'sink_min_voltage':3.31}
    output={'mesh':mesh,'result':solve(mesh,source,sink,source_voltage=3.3),
            'geometry':{'terminals':[{'id':'source','label':'J1.1'},{'id':'sink','label':'U1.1'}]}}
    result=service._operating_result(output,request,request,True,False)['result']
    assert result['operating_mode']=='voltage_driven_resistive_load'
    assert result['source_current_A']==pytest.approx(3.3/(10+1.724e-8*.01/(.001*.000035)))
    assert result['feasibility']['source_current_limit_exceeded']
    assert result['sinks'][0]['min_voltage_V']==3.31
    assert not result['sinks'][0]['within_voltage_limits']


def test_forward_drop_is_included_in_sink_limits_and_power_balance():
    a,source,ta=strip();b,sb,tb=strip(z=1);mesh,n=combine(a,b)
    mesh['series_domains']=[{'net':'A','start':0,'end':n},{'net':'B','start':n,'end':len(mesh['points_mm'])}]
    mesh['lumped_branches']=[{'id':'D1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
        'resistance_ohm':0.,'fixed_drop_v':1.,'from_domain':0,'to_domain':1}]
    result=solve(mesh,source,source_voltage=3.3,sinks=[{'nodes':[i+n for i in tb],'current_A':1,'min_voltage_V':3}])
    assert result['sinks'][0]['voltage_V']<2.3
    assert not result['sinks'][0]['within_voltage_limits']
    assert result['energy_relative_error']<1e-8


def test_opposite_shared_contours_use_identical_subdivision_vertices():
    from quick_pi_plugin.mesh import _conforming_contours
    polygons=[{'outer':[[0,0],[1,0],[1,1],[0,1]],'holes':[]},
              {'outer':[[1,0],[2,0],[2,1],[1,1]],'holes':[]}]
    refined=_conforming_contours(polygons,maximum_edge=.4)
    shared=[{tuple(p) for p in row['outer'] if p[0]==1} for row in refined]
    assert shared[0]==shared[1] and len(shared[0])==4
    corners=[[0,-.1],[1,-.1],[1,.2],[0,.2]]
    refined=_conforming_contours([{'outer':corners,'holes':[]}],maximum_edge=.2)
    assert set(map(tuple,corners)).issubset(set(map(tuple,refined[0]['outer'])))


def test_gmsh_middle_unloaded_contact_does_not_disconnect_continuous_copper():
    pytest.importorskip('gmsh')
    from quick_pi_plugin.mesh import triangulate_gmsh
    polygons=[{'outer':[[x,0],[x+1,0],[x+1,1],[x,1]],'holes':[]} for x in range(3)]
    points,triangles,_=triangulate_gmsh(polygons,.4)
    mesh={'points_mm':points.tolist(),'triangles':triangles.tolist(),
          'triangle_layer':[0]*len(triangles),'triangle_thickness_mm':[.035]*len(triangles)}
    source=np.flatnonzero(points[:,0]==0).tolist();sink=np.flatnonzero(points[:,0]==3).tolist()
    result=solve(mesh,source,sink)
    expected=1.724e-8*.003/(.001*.000035)
    assert result['drop_over_current_ohm']==pytest.approx(expected,rel=1e-8)
    assert result['energy_relative_error']<1e-8
