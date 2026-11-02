"""Saved numerical inspection preserves values without invoking a producer solver."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from wayricad_runtime.project_results import save_result, load_result
from wayricad_runtime.project_results_ui import (MAX_PLOT_SAMPLES, binding_text, frame_grid,
                                                plot_specs, probe_sample, _saved_field_image)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'docs/examples/pocket-kivi'


def sample(name):
    return json.loads((EXAMPLES / (name + '.pocket-kivi.json')).read_bytes())


@pytest.mark.parametrize('name,plugin', [('quick-pi','quick-pi'), ('quick-si','quick-si'),
    ('quick-therm','quick-therm'), ('quick-therm-transient','quick-therm')])
def test_library_roundtrip_actual_complete_samples_keeps_values(tmp_path, name, plugin):
    bundle = sample(name)
    original = deepcopy(bundle)
    receipt = save_result(tmp_path, plugin, bundle, version='3.6.42')
    loaded = load_result(tmp_path, receipt['path'], plugin=plugin)
    assert loaded['bundle'] == original
    assert bundle == original
    assert loaded['receipt']['source_state'] == 'unverified'
    assert plot_specs(loaded['bundle'])


def test_pi_probes_read_exact_stored_node_and_null():
    bundle = sample('quick-pi')
    specs = [row for row in plot_specs(bundle) if 'potential_V' in row['label']]
    for index in (0, bundle['result']['potential_V'].index(None)):
        point = bundle['mesh']['points_mm'][index]
        spec = next(row for row in specs if any(x == point[0] and y == point[1]
                         for x, y in zip(row['x'], row['y'])))
        value = probe_sample(spec, point[0], point[1])
        assert value['value'] == bundle['result']['potential_V'][index]


def test_saved_pi_mesh_draws_only_supported_layer_triangles_with_gradient():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import TriMesh
    from matplotlib.figure import Figure

    bundle = sample('quick-pi')
    specs = [row for row in plot_specs(bundle) if row['kind'] == 'mesh']
    assert {row['label'].split(' / ')[-1] for row in specs} == {'potential_V', 'cell_power_W'}
    for spec in specs:
        figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
        image, probe = _saved_field_image(axis, spec)
        canvas.draw()
        assert isinstance(image, TriMesh)
        assert image._triangulation.triangles.shape[0] == len(spec['triangles'])
        assert probe is spec
        expected = len(spec['triangles'])*3 if spec['cell_values'] is not None else len(spec['vertices'])
        assert image.get_array().size == expected
    assert any(row['kind'] == 'points' and any(value is None for value in row['values'])
               for row in plot_specs(bundle))


def test_saved_pi_does_not_triangulate_raw_points_or_bridge_elevations():
    data = {'mesh': {'points_mm': [[0,0,0],[1,0,0],[0,1,0],
                                   [0,0,1],[1,0,1],[0,1,1]],
                     'triangles': [[0,1,2],[3,4,5],[0,1,4]],
                     'triangle_layer': [0,1,0]},
            'result': {'potential_V': [0,1,2,3,4,5]}}
    specs = plot_specs(data)
    mesh = [row for row in specs if row['kind'] == 'mesh']
    assert len(mesh) == 2
    assert [len(row['triangles']) for row in mesh] == [1,1]
    assert {row['z'] for row in mesh} == {0,1}
    raw = {'mesh': {'points_mm': data['mesh']['points_mm']}, 'result': data['result']}
    assert all(row['kind'] == 'points' for row in plot_specs(raw))
    mismatch = deepcopy(data)
    mismatch['result']['cell_layer'] = [1,0,0]
    assert all(row['kind'] == 'points' for row in plot_specs(mismatch))


def test_saved_thermal_draw_uses_native_field_support_and_keeps_unknowns():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import QuadMesh, TriMesh
    from matplotlib.figure import Figure

    steady = sample('quick-therm')
    layer = next(row for row in plot_specs(steady) if row['kind'] == 'grid' and
                 row['field'].get('value_location') == 'finite_volume_cell')
    figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
    image, probe = _saved_field_image(axis, layer)
    canvas.draw()
    assert isinstance(image, (QuadMesh, TriMesh))
    assert any(isinstance(item, QuadMesh) for item in axis.collections)
    assert all(item.get_clip_path() is not None for item in axis.collections)
    assert frame_grid(probe) == layer['values']
    transient = sample('quick-therm-transient')
    frame_spec = next(row for row in plot_specs(transient) if row['kind'] == 'frames')
    figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
    image, probe = _saved_field_image(axis, frame_spec, 2)
    canvas.draw()
    assert image is not None and probe['values'] == frame_grid(frame_spec, 2)
    assert any(value is None for row in probe['values'] for value in row)


def test_saved_thermal_sparse_points_do_not_gain_cell_area():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import PathCollection, QuadMesh, TriMesh
    from matplotlib.figure import Figure

    data = {'field': {'x_centers_mm': [0,1], 'y_centers_mm': [0,1],
                      'values_c': [[20,None],[None,None]]}}
    spec = next(row for row in plot_specs(data) if row['kind'] == 'grid')
    figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
    image, _ = _saved_field_image(axis, spec)
    canvas.draw()
    assert isinstance(image, PathCollection)
    assert not any(isinstance(item, (QuadMesh, TriMesh)) for item in axis.collections)


def test_saved_thermal_cell_and_gradient_share_native_scale_across_frames():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    spec = dict(kind='frames', x=[0,1], y=[0,1], cells=[[0,0],[1,0],[0,1],[1,1]],
                layer=0, count=4, unit='°C',
                field=dict(value_location='finite_volume_cell',
                           x_edges_mm=[-.5,.5,1.5], y_edges_mm=[-.5,.5,1.5]),
                frames=[dict(time_s=0, temperatures_c=[20,20,20,20]),
                        dict(time_s=1, temperatures_c=[20,40,20,40])])
    for frame in (0,1):
        figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
        image, _ = _saved_field_image(axis, spec, frame)
        canvas.draw()
        assert len(axis.collections) == 2  # Physical cells and smooth known quad.
        assert all(artist.norm is image.norm for artist in axis.collections)
        assert all(artist.get_clim() == (20,40) for artist in axis.collections)
    spec['frames'] = [spec['frames'][0]]
    figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
    image, _ = _saved_field_image(axis, spec)
    canvas.draw()
    assert image.get_clim() == (19.5,20.5)


def test_saved_drill_needs_outer_outline_for_clip():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    spec = dict(kind='grid', x=[0,1], y=[0,1], values=[[20,30],[20,30]], unit='°C',
                field=dict(value_location='finite_volume_cell',
                           x_edges_mm=[-.5,.5,1.5], y_edges_mm=[-.5,.5,1.5]),
                drills=[dict(contour_mm=[[.2,.2],[.8,.2],[.8,.8],[.2,.8]])])
    figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
    _saved_field_image(axis, spec)
    canvas.draw()
    assert all(artist.get_clip_path() is None for artist in axis.collections)
    spec['outline'] = [dict(outer_mm=[[-.5,-.5],[1.5,-.5],[1.5,1.5],[-.5,1.5]])]
    figure = Figure(); canvas = FigureCanvasAgg(figure); axis = figure.add_subplot()
    _saved_field_image(axis, spec)
    canvas.draw()
    assert all(artist.get_clip_path() is not None for artist in axis.collections)


def test_emerge_original_network_and_field_samples_have_readonly_plots():
    data={'frequencies_hz':[1e9,2e9],'s_parameters':{'S11':[[.3,.4],[0,0]]},
          'field':{'x_mm':[1,2],'y_mm':[3],'norm_e_v_m':[[4,None]]}}
    before=deepcopy(data);specs=plot_specs(data)
    network=next(row for row in specs if row['kind']=='line' and row['unit']=='|S|')
    assert network['values']==[.5,0]
    field=next(row for row in specs if row['kind']=='grid')
    assert frame_grid(field)==[[4,None]] and data==before


def test_thermal_frame_indexing_retains_null_cutout_and_actual_frames():
    bundle = sample('quick-therm-transient')
    network = bundle['thermal_network']['transient']
    specs = [row for row in plot_specs(bundle) if row['kind'] == 'frames']
    assert len(specs) == 2
    for layer, spec in enumerate(specs):
        for index in (0, 2):
            grid = frame_grid(spec, index)
            for cell, (x, y) in enumerate(spec['cells']):
                expected = network['frames'][index]['temperatures_c'][layer*spec['count']+cell]
                assert grid[y][x] == expected
            assert any(value is None for row in grid for value in row)


def test_times_inherited_by_explicit_transient_branches_without_recomputation():
    data = {'transient': {'times_s':[0, .25, .5], 'loads':[{'voltage_V':[3.3,None,3.2]}]}}
    specs = plot_specs(data)
    spec = next(row for row in specs if row['label'].endswith('voltage_V'))
    assert spec['x'] is data['transient']['times_s']
    assert spec['values'] is data['transient']['loads'][0]['voltage_V']
    assert probe_sample(spec, .25)['value'] is None


def test_plot_budget_is_explicit_and_does_not_truncate_saved_arrays():
    values = [1.] * (MAX_PLOT_SAMPLES+1)
    data = {'times_s':values,'voltage_V':values}
    specs = plot_specs(data)
    assert specs[0]['kind'] == 'unavailable'
    assert 'budget exceeded' in specs[0]['reason']
    assert len(data['voltage_V']) == MAX_PLOT_SAMPLES+1


def test_malformed_frame_indices_are_rejected_before_native_plotting():
    spec = dict(kind='frames',x=[0],y=[0],cells=[[-1,0]],layer=0,count=1,
                frames=[dict(time_s=0,temperatures_c=[20])])
    with pytest.raises(ValueError, match='outside'):
        frame_grid(spec)
    spec['cells']=[[0,0]]
    spec['frames'][0]['temperatures_c']=[]
    with pytest.raises(ValueError, match='shorter'):
        frame_grid(spec)


def test_stale_and_unverified_banner_never_enables_editor_actions():
    for state in ('stale', 'unverified'):
        text = binding_text({'source_state':state})
        assert 'read-only' in text and 'disabled' in text and state.capitalize() in text


def test_pi_elevations_are_separate_and_coincident_conflicts_never_choose_first():
    data={'mesh':{'points_mm':[[1,2,.02],[1,2,1.5],[1,2,.02]]},
          'result':{'potential_V':[3.3,2.8,3.2]}}
    specs=plot_specs(data)
    assert len(specs)==2 and specs[0]['z']==.02 and specs[1]['z']==1.5
    assert specs[0]['values']==[3.3,3.2] and specs[1]['values']==[2.8]
    conflict=probe_sample(specs[0],1,2)
    assert conflict['ambiguous'] is True and conflict['value'] is None
    assert probe_sample(specs[1],1,2)['value']==2.8


def test_unsupported_volume_is_explicit_and_full_data_remains():
    data={'mesh':{'nodes_mm':[[1,2,3]],'tetrahedra':[[0,1,2,3]]},'result':{'potential_V':[3.3]}}
    specs=plot_specs(data)
    assert specs[0]['kind']=='unavailable' and '3D reconstruction is unavailable' in specs[0]['reason']
    assert data['result']['potential_V']==[3.3]
