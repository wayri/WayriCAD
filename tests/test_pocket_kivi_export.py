"""Portable saved-result shape, exact source custody, privacy and publication."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from wayricad_runtime import pocket_kivi_export as export


@pytest.fixture
def saved(tmp_path):
    board = tmp_path / 'project' / 'main.kicad_pcb'
    board.parent.mkdir()
    board.write_bytes(b'(kicad_pcb (version 20240108))\r\n')
    return dict(board_path=board, source_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
                tool='Quick PI', version='3.6.42', source_state='saved')


def pi_bundle(saved):
    return {
        'schema': 'wayricad.pi/v1',
        'geometry': {'source_path': str(saved['board_path']), 'source_sha256': saved['source_sha256'],
                     'net': '/Front outputs/SLOT1', 'net_id': 42,
                     'z_convention': 'Copper midplanes; positive Z down from the top copper surface.'},
        'mesh': {'points_mm': [[0, 0, .035], [2, 0, .035], [0, 1, .035]],
                 'triangles': [[0, 1, 2]], 'triangle_layer': [0]},
        'result': {'potential_V': [3.3, None, 3.2], 'cell_power_W': [.2], 'cell_J_A_mm2': [[.3, .4]]},
        'transient': {'times_s': [0, 1, 1, 2], 'source_V': [3.3, 3.3, None, 3.1]},
    }


def test_portable_pi_keeps_root_shape_all_values_and_hierarchical_names(saved):
    bundle = pi_bundle(saved)
    original = deepcopy(bundle)
    result = export.portable_bundle(bundle, **saved, units={'potential_V': 'V', 'cell_power_W': 'W'},
        coordinate_frame='KiCad PCB XY in mm', z_basis='front-depth')
    assert bundle == original
    assert result['schema'] == bundle['schema']
    for key in ('mesh', 'result', 'transient'):
        assert result[key] == bundle[key]
        assert result[key] is not bundle[key]
    assert result['geometry']['net'] == '/Front outputs/SLOT1'
    assert result['geometry']['net_id'] == 42
    assert result['geometry']['source_path'] == 'main.kicad_pcb'
    assert result['source_path'] == 'main.kicad_pcb' and result['source_sha256'] == saved['source_sha256']
    metadata = result['pocket_kivi_export']
    assert metadata == dict(schema=export.SCHEMA, tool='Quick PI', version='3.6.42', source_state='saved',
                            units={'potential_V': 'V', 'cell_power_W': 'W'},
                            coordinate_frame='KiCad PCB XY in mm', zBasis='front-depth')
    result['mesh']['points_mm'][0][0] = 999
    assert bundle == original


def test_thermal_frames_active_cells_and_unknown_elevation_are_unchanged(saved):
    bundle = {'thermal_network': {'transient': {
        'spatial_index': {'x_centers_mm': [1, 3], 'y_centers_mm': [2], 'cells': [[0, 0], [1, 0]],
                          'active_cells_per_layer': 2, 'layers': [{'id': 'F.Cu', 'z_mm': None}]},
        'frames': [{'time_s': 0, 'temperatures_c': [20, None]}, {'time_s': .25, 'temperatures_c': [21, 22]}],
    }}, 'board_thermal_view': {'top': {'x_centers_mm': [1, 3], 'y_centers_mm': [2], 'values_c': [[20, None]]}}}
    result = json.loads(export.portable_json(bundle, **dict(saved, tool='QuickTherm')))
    for key in bundle:
        assert result[key] == bundle[key]
    assert result['pocket_kivi_export']['units'] is None
    assert result['pocket_kivi_export']['coordinate_frame'] is None
    assert result['pocket_kivi_export']['zBasis'] is None
    assert 'mesh' not in result and 'geometry' not in result


def test_si_eye_step_ids_and_null_gaps_are_preserved_without_invented_geometry(saved):
    bundle = {'report': {'net': '/Front outputs/SLOT1', 'source': '/Front outputs/SLOT1',
                         'input': '/Front outputs/SLOT1', 'output': '/Rear inputs/SLOT2', 'source_hash': 'model-hash',
                         'eye': {'time_ui': [-1, 0, 1], 'traces_v': [[0, None, 1], [1, .5, 0]]},
                         'step': {'time_ns': [0, 0, .2], 'voltage_v': [0, 1, None]}},
              'board_item_ids': ['00123', '42fb0f77-2a79-4a1f-a82a-4f7c878d7108']}
    result = export.portable_bundle(bundle, **dict(saved, tool='Quick SI'))
    for key in bundle:
        assert result[key] == bundle[key]
    assert 'mesh' not in result and 'geometry' not in result


def test_named_study_and_model_hashes_are_never_board_evidence(saved):
    bundle = {'study_sha256': 'b' * 64, 'geometry_sha256': 'c' * 64, 'source_hash': 'd' * 64,
              'report': {'model_sha256': 'e' * 64}}
    result = export.portable_bundle(bundle, **saved)
    for key in bundle:
        assert result[key] == bundle[key]
    assert result['source_sha256'] == saved['source_sha256']
    with pytest.raises(ValueError, match='changed'):
        export.portable_bundle(bundle, **dict(saved, source_sha256='b' * 64))


@pytest.mark.parametrize('state', ['live', 'unsaved', 'unknown', None])
def test_live_unsaved_or_unknown_source_state_cannot_get_saved_binding(saved, state):
    with pytest.raises(ValueError, match='saved PCB'):
        export.portable_bundle({}, **dict(saved, source_state=state))


@pytest.mark.parametrize('bundle', [dict(source_state='live'), dict(request=dict(unsaved_changes=True)),
    dict(report=dict(source_state='live-unsaved'))])
def test_existing_unsaved_evidence_cannot_be_overridden_by_caller(saved, bundle):
    with pytest.raises(ValueError, match='unsaved'):
        export.portable_bundle(bundle, **saved)


def test_stale_crlf_bytes_and_conflicting_existing_binding_are_rejected(saved):
    board = saved['board_path']
    before = board.read_bytes()
    board.write_bytes(before.replace(b'\r\n', b'\n'))
    with pytest.raises(ValueError, match='changed'):
        export.portable_bundle({}, **saved)
    board.write_bytes(before)
    for bundle in ({'source_sha256': '0' * 64}, {'board_sha256': '0' * 64},
                   {'geometry': {'source_path': str(board), 'source_sha256': '0' * 64}}):
        with pytest.raises(ValueError, match='conflict'):
            export.portable_bundle(bundle, **saved)


def test_foreign_board_cannot_be_rebound(saved, tmp_path):
    other = tmp_path / 'different.kicad_pcb'
    other.write_bytes(saved['board_path'].read_bytes())
    for bundle in ({'board_path': str(other)}, {'geometry': {'source_path': str(other)}}):
        with pytest.raises(ValueError, match='different PCB'):
            export.portable_bundle(bundle, **saved)


def test_path_metadata_is_relative_but_net_names_and_arbitrary_ids_are_exact(saved):
    board = saved['board_path']
    bundle = {'request': {'board_path': str(board), 'net': '/Front outputs/SLOT1',
                           'model_path': 'C:\\Private User\\secret\\device.ibs',
                           'output_path': '/home/private/results/report.json',
                           'root': str(board.parent)},
              'named_nets': {'/Front outputs/SLOT1': {'name': '/Front outputs/SLOT1', 'id': '/exact/identity'}},
              'rows': [{'filename': 'file:///C:/Private%20User/secret/model.ibs'}],
              'input_paths': ['../private/input.json', '//server/private/model.ibs'],
              'citations': [{'source': 'https://example.invalid/public/paper'}]}
    result = export.portable_bundle(bundle, **saved)
    encoded = json.dumps(result)
    assert 'Private User' not in encoded and '/home/private' not in encoded and '//server/private' not in encoded
    assert result['request']['board_path'] == 'main.kicad_pcb'
    assert result['request']['net'] == '/Front outputs/SLOT1'
    assert result['named_nets'] == bundle['named_nets']
    assert result['citations'] == bundle['citations']
    for key in ('model_path', 'output_path'):
        assert result['request'][key].startswith('_external/')
    assert all(path.startswith('_external/') for path in result['input_paths'])


def test_source_root_preserves_project_relative_paths_and_fingerprints(saved, tmp_path):
    board = saved['board_path']
    project = board.with_suffix('.kicad_pro')
    project.write_bytes(b'{"rules":1}')
    absent = board.with_suffix('.kicad_dru')
    fingerprints = {str(board): saved['source_sha256'], str(project): hashlib.sha256(project.read_bytes()).hexdigest(),
                    str(absent): None}
    bundle = {'source_fingerprints': fingerprints, 'report': {'source_fingerprints': fingerprints}}
    result = export.portable_bundle(bundle, **saved, source_root=tmp_path)
    assert result['source_path'] == 'project/main.kicad_pcb'
    expected = {'project/main.kicad_pcb': saved['source_sha256'],
                'project/main.kicad_pro': fingerprints[str(project)], 'project/main.kicad_dru': None}
    assert result['source_fingerprints'] == result['report']['source_fingerprints'] == expected
    project.write_bytes(b'{"rules":2}')
    with pytest.raises(ValueError, match='changed'):
        export.portable_bundle(bundle, **saved, source_root=tmp_path)


def test_previously_absent_rules_appearing_reject_export(saved):
    rules = saved['board_path'].with_suffix('.kicad_dru')
    bundle = {'source_fingerprints': {str(rules): None}}
    rules.write_bytes(b'(version 1)')
    with pytest.raises(ValueError, match='absent'):
        export.portable_bundle(bundle, **saved)


def test_relative_and_absolute_external_paths_share_one_safe_alias(saved):
    model = saved['board_path'].parent.parent / 'external' / 'device.ibs'
    bundle = {'model_path': str(model), 'request': {'model_path': '../external/device.ibs',
                                                   'root': str(saved['board_path'].parent)}}
    result = export.portable_bundle(bundle, **saved)
    assert result['model_path'] == result['request']['model_path']
    assert result['model_path'].startswith('_external/')
    assert result['request']['root'] == '.'


def test_saved_study_file_hash_is_checked_separately(saved):
    study = saved['board_path'].with_suffix('.study.json')
    study.write_bytes(b'{}')
    bundle = {'study_input_path': str(study), 'study_file_sha256': hashlib.sha256(b'{}').hexdigest()}
    result = export.portable_bundle(bundle, **saved)
    assert result['study_input_path'] == 'main.study.json'
    study.write_bytes(b'{"changed":1}')
    with pytest.raises(ValueError, match='changed'):
        export.portable_bundle(bundle, **saved)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf'), object(), {1: 'coerced ID'}])
def test_strict_json_rejects_nonfinite_or_non_json_without_coercion(saved, bad):
    with pytest.raises(ValueError):
        export.portable_json({'values': [bad]}, **saved)


def test_circular_and_excessively_nested_bundles_fail_cleanly(saved):
    circular = {}
    circular['loop'] = circular
    with pytest.raises(ValueError, match='circular'):
        export.portable_bundle(circular, **saved)
    deep = {}
    target = deep
    for _ in range(export.MAX_DEPTH + 1):
        target['next'] = {}
        target = target['next']
    with pytest.raises(ValueError, match='nesting'):
        export.portable_bundle(deep, **saved)


def test_utf8_serialized_size_includes_metadata_and_newline(saved):
    payload = export.portable_json({'values': ['µ', None, 1e-30]}, **saved)
    assert payload.endswith(b'\n') and json.loads(payload)['values'] == ['µ', None, 1e-30]
    with patch.object(export, 'MAX_BYTES', len(payload)):
        assert export.portable_json({'values': ['µ', None, 1e-30]}, **saved) == payload
    with patch.object(export, 'MAX_BYTES', len(payload) - 1), pytest.raises(ValueError, match='64 MiB'):
        export.portable_json({'values': ['µ', None, 1e-30]}, **saved)


def test_source_change_during_conversion_is_detected_before_return(saved):
    original = export._strict_json
    def mutate(value):
        saved['board_path'].write_bytes(b'changed during export')
        return original(value)
    with patch.object(export, '_strict_json', side_effect=mutate), pytest.raises(ValueError, match='changed'):
        export.portable_bundle({}, **saved)


def test_new_json_publication_is_verified_and_never_overwrites_existing_files(saved, tmp_path):
    board_bytes = saved['board_path'].read_bytes()
    destination = tmp_path / 'exports' / 'result.json'
    result = export.export_bundle(pi_bundle(saved), destination, **saved)
    assert result['bytes'] == destination.stat().st_size
    assert result['sha256'] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert json.loads(destination.read_bytes())['source_path'] == 'main.kicad_pcb'
    assert saved['board_path'].read_bytes() == board_bytes
    with pytest.raises(ValueError, match='new .json'):
        export.export_bundle({}, destination, **saved)
    for path in [saved['board_path'], saved['board_path'].with_suffix('.kicad_pro')]:
        with pytest.raises(ValueError):
            export.export_bundle({}, path, **saved)
    settings = tmp_path / 'settings.json'
    settings.write_bytes(b'{"settings":1}')
    with pytest.raises(ValueError):
        export.export_bundle({}, settings, **saved)
    assert settings.read_bytes() == b'{"settings":1}'
    assert {p.name for p in destination.parent.iterdir()} == {'result.json'}


def test_stale_source_never_creates_output_and_publication_source_change_rolls_back(saved, tmp_path):
    destination = tmp_path / 'result.json'
    with pytest.raises(ValueError):
        export.export_bundle({}, destination, **dict(saved, source_sha256='0' * 64))
    assert not destination.exists()
    publish = export.publish_documents
    def mutate(*args, **kwargs):
        publish(*args, **kwargs)
        saved['board_path'].write_bytes(b'changed during publication')
    with patch.object(export, 'publish_documents', side_effect=mutate), pytest.raises(ValueError, match='changed'):
        export.export_bundle({}, destination, **saved)
    assert not destination.exists()


def test_hardlink_destinations_cannot_overwrite_sources(saved, tmp_path):
    destination = tmp_path / 'alias.json'
    try:
        os.link(saved['board_path'], destination)
    except OSError:
        pytest.skip('Filesystem does not support test hardlinks.')
    before = saved['board_path'].read_bytes()
    with pytest.raises(ValueError):
        export.export_bundle({}, destination, **saved)
    assert saved['board_path'].read_bytes() == before


def test_declared_settings_input_is_protected_even_when_not_yet_present(saved, tmp_path):
    destination = tmp_path / 'settings.json'
    with pytest.raises(ValueError, match='overwrite'):
        export.export_bundle({'request': {'settings_path': str(destination)}}, destination, **saved)
    assert not destination.exists()


def test_destination_appearing_during_preparation_is_preserved(saved, tmp_path):
    destination = tmp_path / 'settings.json'
    serialize = export._strict_json
    def appeared(value):
        destination.write_bytes(b'{"settings":1}')
        return serialize(value)
    with patch.object(export, '_strict_json', side_effect=appeared), pytest.raises(ValueError, match='appeared'):
        export.export_bundle({}, destination, **saved)
    assert destination.read_bytes() == b'{"settings":1}'


@pytest.mark.parametrize('kwargs', [dict(tool=''), dict(version=''), dict(units={'temperature': 1}),
    dict(coordinate_frame={}), dict(z_basis=''), dict(source_sha256='model-hash')])
def test_invalid_metadata_does_not_create_evidence(saved, kwargs):
    with pytest.raises(ValueError):
        export.portable_bundle({}, **dict(saved, **kwargs))
