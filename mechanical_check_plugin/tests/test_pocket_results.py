"""Mechanical scene serialization without inventing PCB registration or geometry."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wayricad_mechanical.report import export


@pytest.fixture
def scene(tmp_path):
    board = tmp_path / 'assembly.kicad_pcb'
    board.write_bytes(b'(kicad_pcb (version 20240108))\n')
    return {'project_name': 'Scene fixture', 'completed_at': '2026-10-29T00:00:00Z',
            'version': 'test-producer', 'board_path': str(board),
            'board_sha256': hashlib.sha256(board.read_bytes()).hexdigest(),
            'findings': [{'id': 'gap-1', 'refs': ['J2', 'U1'], 'rule': 'clearance',
                          'summary': 'Review close approach', 'evidence': 'saved scene',
                          'measured': None, 'limit': 1.0, 'unit': 'mm'}],
            'bodies': [{'ref': 'J2', 'mesh': {'vertices': [[0., 0., 0.], [1., 0., 0.], [0., 1., 2.]],
                                            'faces': [[0, 1, 2]]}}]}


def test_saved_scene_pocket_copy_retains_actual_mesh_and_findings(scene, tmp_path):
    result = export(scene, tmp_path / 'reports', pocket_kivi=True)
    value = json.loads(Path(result['pocket_kivi_json']).read_text())
    assert value['bodies'] == scene['bodies'] and value['findings'] == scene['findings']
    assert value['source_path'] == 'assembly.kicad_pcb'
    assert value['source_sha256'] == scene['board_sha256']
    assert value['pocket_kivi_export']['coordinate_frame'] == 'Mechanical scene coordinates'
    assert value['pocket_kivi_export']['zBasis'] is None
    assert value['pocket_kivi_export']['units'] is None
    assert json.loads(Path(result['json']).read_text()) == scene


@pytest.mark.parametrize('kind', ['live editor snapshot', 'IPC snapshot captured at launch'])
def test_live_scene_does_not_claim_saved_pcb_binding(scene, tmp_path, kind):
    scene['source_kind'] = kind
    result = export(scene, tmp_path / 'reports', pocket_kivi=True)
    assert 'pocket_kivi_json' not in result
    assert 'no verified saved-PCB binding' in result['pocket_kivi_unavailable']
    assert json.loads(Path(result['json']).read_text())['bodies'] == scene['bodies']


def test_multiboard_scene_reports_unavailable_binding_honestly(scene, tmp_path):
    scene['comparison_board'] = {'translation_mm': [0, 0, 10], 'rotation_deg': [0, 0, 90]}
    result = export(scene, tmp_path / 'reports', pocket_kivi=True)
    assert 'pocket_kivi_json' not in result and 'Multi-board' in result['pocket_kivi_unavailable']
    assert json.loads(Path(result['json']).read_text())['comparison_board'] == scene['comparison_board']


def test_stale_saved_scene_fails_before_partial_publication(scene, tmp_path):
    Path(scene['board_path']).write_bytes(b'changed')
    destination = tmp_path / 'reports'
    with pytest.raises(ValueError, match='changed'):
        export(scene, destination, pocket_kivi=True)
    assert not destination.exists()


def test_query_ownership_never_enters_exported_files(scene, tmp_path):
    scene['_measurement_session'] = {'private_token': 'do-not-export'}
    result = export(scene, tmp_path / 'reports', pocket_kivi=True)
    assert all('do-not-export' not in Path(result[key]).read_text(encoding='utf-8-sig')
               for key in ('html', 'json', 'csv', 'pocket_kivi_json'))
