import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
wx = pytest.importorskip('wx')

from review_comments_plugin.tests.test_conversation_ui import app, pane, fake_session, message
from review_comments_plugin.tests.test_artifact_review import project, SCOPE
from review_comments_plugin.web_documents import ReviewDocuments


def test_bom_fields_are_virtual_read_only_and_cell_context_is_explicit(pane, project):
    pane.values['root'] = str(project)
    pane.session.scope = SCOPE
    pane.session.path = project/'board.kicad_pcb'
    pane.session.settings = dict(root=str(project))
    pane.session.require_authorization = Mock()
    canvas = pane.design_canvas
    canvas.origin_path = pane.session.path
    canvas.documents = ReviewDocuments(pane.session.path)
    canvas.bom_view.load(pane.session.path)
    view = canvas.bom_view
    assert not view.grid.IsEditable()
    assert view.grid.GetNumberRows() == 1
    assert 'MPN' in view.snapshot['columns']
    column = view.snapshot['columns'].index('MPN')
    view.grid.SetGridCursor(0, column)
    assert view.grid.GetCellValue(0, column) == 'EXAMPLE'
    view.comment_cell()
    assert pane.target['context']['field'] == 'MPN' and pane.target['variant'] == '*'
    assert pane.target_label.IsShown()
    pane.session.publish.assert_not_called()
    original = dict(pane.target)
    (project/'board.kicad_pcb').write_text((project/'board.kicad_pcb').read_text().replace('EXAMPLE', 'CHANGED'))
    view.comment_cell()
    assert pane.target == original and 'changed' in view.status.GetLabel().lower()


def test_project_gerber_registration_retains_origin_and_clears_wrong_hash_markers(pane, project):
    pane.values['root'] = str(project)
    pane.session.scope = SCOPE
    pane.session.path = project/'board.kicad_pcb'
    pane.session.digest = hashlib.sha256(pane.session.path.read_bytes()).hexdigest()
    pane.session.settings = dict(root=str(project))
    pane.session.require_authorization = Mock()
    canvas = pane.design_canvas
    canvas.origin_path = pane.session.path
    canvas.documents = ReviewDocuments(pane.session.path)
    canvas.open_gerber(project/'fab/top.gbr')
    assert canvas.pending['view'] == 'manufacturing'
    assert canvas.origin_path == pane.session.path and canvas.can_anchor()
    assert canvas.pending['artifact']['file'] == 'fab/top.gbr'
    assert canvas.pending['scope'] == SCOPE
    (project/'board.kicad_pcb').write_text('(kicad_pcb)')
    assert not canvas.can_anchor(quiet=True)


def test_nested_replies_have_one_visible_left_indent_and_keep_origin_order(pane, app):
    pane.session = fake_session(rows=[message('1'), message('2', parentId='1'), message('3', parentId='2'), message('4')])
    pane.Show()
    pane.populate(force=True)
    pane.Layout()
    app.Yield()
    assert [card.row['id'] for card in pane.cards] == ['1', '2', '3', '4']
    assert pane.cards[1].GetPosition().x == pane.cards[2].GetPosition().x
    assert pane.cards[1].GetPosition().x > pane.cards[0].GetPosition().x
    assert pane.cards[0].GetPosition().x == pane.cards[3].GetPosition().x
