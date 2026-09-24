"""KiCad 10 saved-board net names and visual snapshot refresh boundaries."""
import json

from conftest import BOARD, PROJECT
from protocol_constraint_composer_plugin.constraint_studio.board import BoardContext
from protocol_constraint_composer_plugin.constraint_studio.inspection import items_from_board
from protocol_constraint_composer_plugin.constraint_studio.routing_profiles import selected_nets
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace
from protocol_constraint_composer_plugin.studio_model import snapshot


def named_net_board():
    return (BOARD.replace('(net 0 "") (net 1 "BGA_D0") (net 2 "BGA_D1")', '')
            .replace('(net 1 "BGA_D0")', '(net "CAN_P")')
            .replace('(net 2 "BGA_D1")', '(net "CAN_N")'))


def test_kicad_10_embedded_net_names_are_selectable_and_visible(tmp_path):
    board = tmp_path / 'pair.kicad_pcb'
    board.write_text(named_net_board(), encoding='utf-8')
    board.with_suffix('.kicad_pro').write_text(json.dumps(PROJECT), encoding='utf-8')
    workspace = Workspace.load(board)
    assert set(workspace.context.nets) == {'CAN_P', 'CAN_N'}
    assert {item.net for item in items_from_board(workspace.context, workspace.project) if item.kind == 'Pad'} == {'CAN_P', 'CAN_N'}
    assert {'CAN_P', 'CAN_N'} <= set(snapshot(workspace)['nets'])
    assert selected_nets(workspace, {'name': 'CAN', 'type': 'differential', 'nets': ['CAN_N', 'CAN_P']}) == ['CAN_N', 'CAN_P']


def test_saved_board_change_is_reported_until_reloaded(tmp_path):
    board = tmp_path / 'pair.kicad_pcb'
    board.write_text(named_net_board(), encoding='utf-8')
    workspace = Workspace.load(board)
    first = snapshot(workspace)
    assert first['source_board_changed'] is False
    board.write_text(named_net_board().replace('CAN_N', 'CAN_M'), encoding='utf-8')
    stale = snapshot(workspace)
    assert stale['source_board_changed'] is True
    assert stale['board_revision'] == first['board_revision']
    assert 'CAN_N' in stale['nets']
    fresh = snapshot(Workspace.load(board))
    assert fresh['source_board_changed'] is False
    assert fresh['board_revision'] != first['board_revision']
    assert 'CAN_M' in fresh['nets'] and 'CAN_N' not in fresh['nets']


def test_numeric_net_ids_still_resolve_through_top_level_table():
    context = BoardContext.load(BOARD)
    nets = {item.net for item in items_from_board(context, PROJECT) if item.kind == 'Pad'}
    assert nets == {'BGA_D0', 'BGA_D1'}
