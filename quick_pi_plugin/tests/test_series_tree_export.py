"""Power-tree exports preserve saved designs and reject stale evidence."""
import hashlib
import json

import pytest

from quick_pi_plugin.series_power_tree_ui import tree_export_context, save_tree_data


def context(tmp_path):
    board = tmp_path / 'board.kicad_pcb'
    board.write_bytes(b'saved copper')
    sha = hashlib.sha256(board.read_bytes()).hexdigest()
    return board, sha


def test_current_tree_exports_json(tmp_path):
    board, sha = context(tmp_path)
    sources, guard = tree_export_context(board, sha)
    output = tmp_path / 'tree.json'
    save_tree_data(output, {'nodes': [{'label': 'Q1 || Q2'}]}, sources=sources, source_guard=guard)
    assert json.loads(output.read_text())['nodes'][0]['label'] == 'Q1 || Q2'
    assert board.read_bytes() == b'saved copper'


def test_open_rejects_stale_or_missing_context(tmp_path):
    board, sha = context(tmp_path)
    with pytest.raises(ValueError): tree_export_context(board, None)
    board.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Saved PCB changed'): tree_export_context(board, sha)


@pytest.mark.parametrize('changed', ['pcb', 'project', 'rules', 'study'])
def test_save_rejects_changed_inputs_preserves_existing_output(tmp_path, changed):
    board, sha = context(tmp_path)
    study = tmp_path / 'simulation.json'
    study.write_bytes(b'original study')
    paths = {'pcb': board, 'project': board.with_suffix('.kicad_pro'),
             'rules': board.with_suffix('.kicad_dru'), 'study': study}
    sources, guard = tree_export_context(board, sha, sources=[study])
    paths[changed].write_bytes(b'changed input')
    output = tmp_path / 'tree.json'; output.write_bytes(b'previous report')
    with pytest.raises(ValueError, match='changed'):
        save_tree_data(output, {'nodes': []}, sources=sources, source_guard=guard)
    assert output.read_bytes() == b'previous report'


def test_save_refuses_design_and_declared_study(tmp_path):
    board, sha = context(tmp_path)
    study = tmp_path / 'simulation.json'; study.write_bytes(b'study')
    sources, guard = tree_export_context(board, sha, sources=[study])
    for path in (board, board.with_suffix('.kicad_pro'), board.with_suffix('.kicad_dru'), study):
        with pytest.raises(ValueError):
            save_tree_data(path, {}, sources=sources, source_guard=guard)
    assert study.read_bytes() == b'study'
    assert board.read_bytes() == b'saved copper'


def test_mid_publication_staleness_rolls_back(tmp_path):
    board, sha = context(tmp_path)
    sources, guard = tree_export_context(board, sha)
    output = tmp_path / 'tree.json'; output.write_bytes(b'previous report')
    calls = 0
    def changing_guard():
        nonlocal calls
        calls += 1
        if calls == 3: board.write_bytes(b'new source')
        guard()
    with pytest.raises(ValueError, match='changed'):
        save_tree_data(output, {'nodes': []}, sources=sources, source_guard=changing_guard)
    assert output.read_bytes() == b'previous report'
