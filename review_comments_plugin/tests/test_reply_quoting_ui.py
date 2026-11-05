"""Explicit quoted replies preserve drafts and immediate-parent attribution."""
from review_comments_plugin.tests.test_conversation_ui import app, pane, fake_session, message
from review_comments_plugin.conversation_ui import reply_header


def test_reply_header_names_immediate_parent_even_for_nested_reply(pane):
    rows = [message('1', 'alice'), message('2', 'bob', parentId='1'), message('3', 'carol', parentId='2')]
    pane.session = fake_session(rows=rows)
    pane.populate()
    assert reply_header(rows[2], rows) == 'carol → bob · reply to #2'
    assert any('carol → bob' in child.GetLabel() for child in pane.cards[2].GetChildren())


def test_deleted_or_duplicate_parent_is_not_misattributed():
    row = message('3', 'carol', parentId='2')
    assert reply_header(row, []) == 'carol → unavailable comment #2'
    assert reply_header(row, [message('2','alice'), message('2','bob')]) == 'carol → unavailable comment #2'


def test_filtered_reply_refreshes_recipient_after_parent_author_changes(pane):
    pane.search.SetValue('Confirmed')
    pane.populate()
    assert len(pane.cards) == 1
    assert 'bob → alice' in pane.cards[0].row['replyLabel']
    pane.session.rows[0]['author'] = 'renamed-author'
    pane.populate()
    assert 'bob → renamed-author' in pane.cards[0].row['replyLabel']


def test_quote_origin_keeps_draft_is_undoable_and_does_not_publish(pane):
    pane.compose.SetValue('My existing note Δ')
    pane.quote_reply(pane.session.rows[0])
    assert pane.reply_to == '1'
    assert pane.compose.GetValue() == 'My existing note Δ\n\n> alice wrote:\n> Check J2 pin 1\n\n'
    assert pane.reply_banner.IsShown()
    pane.session.publish.assert_not_called()
    assert pane.compose.CanUndo()
    pane.compose.Undo()
    assert pane.compose.GetValue() == 'My existing note Δ'


def test_quote_removed_comment_or_over_limit_preserves_draft_and_reply_target(pane):
    removed = message('99')
    pane.compose.SetValue('Keep me')
    pane.quote_reply(removed)
    assert pane.compose.GetValue() == 'Keep me' and pane.reply_to is None
    pane.compose.SetValue('x'*15999)
    pane.quote_reply(pane.session.rows[0])
    assert pane.compose.GetValue() == 'x'*15999 and pane.reply_to is None
    pane.session.publish.assert_not_called()


def test_quote_uses_current_text_and_strips_hidden_context(pane):
    stale = pane.session.rows[0]
    pane.session.rows[0] = message('1',body='Updated\n\n<!-- wayricad-status:v1 hidden -->')
    pane.quote_reply(stale)
    assert 'Updated' in pane.compose.GetValue()
    assert 'wayricad-status' not in pane.compose.GetValue()


def test_reply_banner_hides_metadata(pane):
    row = message('1',body='Visible\n<!-- wayricad-context:v1 hidden -->')
    pane.begin_reply(row)
    assert 'wayricad-context' not in pane.reply_label.GetToolTipText()
