from copy import deepcopy
import pytest
from quick_pi_plugin.board_plane import study_from_mesh


def bundle():
    return {'mesh':{'points_mm':[[0,0,0],[10,0,0],[10,10,0],[0,10,0]],
        'triangles':[[0,1,2],[0,2,3]],'triangle_layer':[0,0],
        'triangle_thickness_mm':[.035,.035],'vias':[],
        'terminal_nodes':{'a':[0,3],'b':[1,2]}}}


def test_plane_adapter_retains_actual_mesh_and_explicit_pad_groups():
    original=bundle();before=deepcopy(original)
    study=study_from_mesh(original,['a'],['b'],{'epsr':4.2})
    assert study['vertices_mm']==[[0,0],[10,0],[10,10],[0,10]]
    assert study['ports'][0]['nodes']==[0,3]
    assert study['ports'][0]['weights']==[.5,.5]
    assert study['copper_thickness_mm']==.035
    assert original==before


@pytest.mark.parametrize('change',['layers','vias','stub','thickness','nonplanar','missingport'])
def test_plane_adapter_rejects_unmodelled_topology(change):
    data=bundle();mesh=data['mesh']
    if change=='layers':mesh['triangle_layer']=[0,2]
    elif change=='vias':mesh['vias']=[{'id':'v'}]
    elif change=='stub':mesh['geometry']={'vias':[{'id':'stub','contacts':[0]}]}
    elif change=='thickness':mesh['triangle_thickness_mm']=[.035,.07]
    elif change=='nonplanar':mesh['points_mm'][2][2]=1
    else:mesh['terminal_nodes'].pop('a')
    with pytest.raises(ValueError):study_from_mesh(data,['a'],['b'],{})
