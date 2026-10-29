"""Saved numerical inspection preserves values without invoking a producer solver."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from wayricad_runtime.project_results import save_result, load_result
from wayricad_runtime.project_results_ui import (MAX_PLOT_SAMPLES, binding_text, frame_grid,
                                                plot_specs, probe_sample)

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
    spec = next(row for row in plot_specs(bundle) if row['label'].endswith('potential_V'))
    for index in (0, bundle['result']['potential_V'].index(None)):
        value = probe_sample(spec, spec['x'][index], spec['y'][index])
        assert value['value'] == bundle['result']['potential_V'][index]


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
