"""Area extraction is batch-scoped; previews retain conservative semantics."""
import copy
from unittest.mock import patch

import pytest

from conftest import BOARD
from protocol_constraint_composer_plugin import studio_bridge, studio_model
from protocol_constraint_composer_plugin.constraint_studio import inspection
from protocol_constraint_composer_plugin.constraint_studio.board import BoardContext
from protocol_constraint_composer_plugin.constraint_studio.model import Rule
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace


def item(x=100, geometry='circle'):
    return inspection.Item('pad', 'Pad', layers=('F.Cu',), points=[(x, 100)],
                           radius=.1, geometry=geometry, properties={'Type': 'Pad'})


@pytest.mark.parametrize('count', [1, 80, 800])
def test_area_extraction_occurs_once_independent_of_item_count(count):
    context = BoardContext.load(BOARD)
    rule = Rule('area', "A.enclosedByArea('EXISTING_ESCAPE')")
    with patch.object(inspection, 'all_areas', wraps=inspection.all_areas) as extract:
        matches = inspection.rule_matches(rule, [item()] * count, context)
    assert all(match.value is True for match in matches)
    extract.assert_called_once_with(context)


@pytest.mark.parametrize('expression', [
    "A.enclosedByArea('EXISTING_ESCAPE')",
    "A.enclosedByArea('missing')",
    "A.enclosedByArea([])",
    "A.enclosedByArea({})",
    "A.enclosedByArea()",
    "A.enclosedByArea('EXISTING_ESCAPE', 'extra')",
    "A.enclosedByArea('EXISTING_ESCAPE') == 0",
    "B.enclosedByArea('EXISTING_ESCAPE')",
    "A.enclosedByArea('EXISTING_ESCAPE') || A.fromTo('a', 'b')",
])
def test_batch_matches_single_item_values_and_diagnostics(expression):
    context = BoardContext.load(BOARD)
    rule = Rule('area', expression)
    items = [item(), item(110), item(geometry='unknown')]
    expected = [inspection.rule_match(rule, row, context=context) for row in items]
    assert inspection.rule_matches(rule, items, context) == expected


@pytest.mark.parametrize('change', ['duplicate', 'copper-zone', 'unsupported-polygon'])
def test_ambiguous_and_unsupported_areas_keep_unknown_reasons(change):
    context = BoardContext.load(BOARD)
    if change == 'duplicate':
        context.areas.append(copy.deepcopy(context.areas[0]))
    elif change == 'copper-zone':
        context.areas[0]['rule_area'] = False
    else:
        context.areas[0]['node'].children = [node for node in context.areas[0]['node'].children
                                              if node.head() != 'polygon']
    rule = Rule('area', "A.enclosedByArea('EXISTING_ESCAPE')")
    expected = inspection.rule_match(rule, item(), context=context)
    assert expected.value is None
    assert inspection.rule_matches(rule, [item(), item()], context) == [expected, expected]


def test_unused_area_lookup_is_lazy_for_disabled_layer_and_ordinary_rules():
    context = BoardContext.load(BOARD)
    rules = [Rule('disabled', "A.enclosedByArea('EXISTING_ESCAPE')", enabled=False),
             Rule('layer', "A.enclosedByArea('EXISTING_ESCAPE')", layer='B.Cu'),
             Rule('ordinary', "A.Type == 'Pad'")]
    with patch.object(inspection, 'all_areas', side_effect=AssertionError('Unused area scan')):
        for rule in rules:
            inspection.rule_matches(rule, [item(), item()], context)


def test_new_batches_see_renamed_areas_and_replaced_context_with_same_items():
    context = BoardContext.load(BOARD)
    items = [item()]
    rule = Rule('area', "A.enclosedByArea('EXISTING_ESCAPE')")
    assert inspection.rule_matches(rule, items, context)[0].value is True
    context.areas[0]['name'] = 'RENAMED'
    assert inspection.rule_matches(rule, items, context)[0].value is None
    replacement = BoardContext.load(BOARD.replace('(xy 98 98)', '(xy 108 98)')
                                   .replace('(xy 102 98)', '(xy 112 98)')
                                   .replace('(xy 102 102)', '(xy 112 102)')
                                   .replace('(xy 98 102)', '(xy 108 102)'))
    assert inspection.rule_matches(rule, items, replacement)[0].value is False


def test_new_batch_sees_attached_area_added_to_same_context():
    context = BoardContext.load(BOARD)
    items = [item()]
    rule = Rule('area', "A.enclosedByArea('ATTACHED')")
    assert inspection.rule_matches(rule, items, context)[0].value is None
    local = BoardContext.load(BOARD.replace('EXISTING_ESCAPE', 'ATTACHED')
                             .replace('(xy 98 98)', '(xy -2 -2)')
                             .replace('(xy 102 98)', '(xy 2 -2)')
                             .replace('(xy 102 102)', '(xy 2 2)')
                             .replace('(xy 98 102)', '(xy -2 2)'))
    context.footprints[0].node.children.append(local.areas[0]['node'])
    assert inspection.rule_matches(rule, items, context)[0].value is True


def test_visual_and_native_scope_entrypoints_extract_areas_once():
    workspace = Workspace(board_text=BOARD, context=BoardContext.load(BOARD))
    workspace.document.append(Rule('area', "A.enclosedByArea('EXISTING_ESCAPE')"))
    items = inspection.items_from_board(workspace.context, workspace.project)
    expected = [inspection.rule_match(workspace.document.rules[0], row, context=workspace.context)
                for row in items]
    with patch.object(inspection, 'all_areas', wraps=inspection.all_areas) as extract:
        actual = studio_model.inspect_scope(workspace, {'rule': 0})
    extract.assert_called_once_with(workspace.context)
    assert [row['value'] for row in actual['matches']] == [match.value for match in expected]
    with patch.object(inspection, 'all_areas', wraps=inspection.all_areas) as extract:
        actual = studio_bridge.scope_preview(workspace, 0, items=iter(items))
    extract.assert_called_once_with(workspace.context)
    assert [(value, reasons) for _, value, reasons in actual] == [(match.value, match.reasons) for match in expected]
