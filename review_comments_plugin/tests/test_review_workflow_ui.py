"""Native thread navigation, combined filters, composer state and narrow layout."""
from unittest.mock import Mock

import pytest
wx = pytest.importorskip('wx')

from review_comments_plugin.tests.test_conversation_ui import app, pane, fake_session, message


def test_focusing_nested_reply_keeps_whole_thread_and_retains_pending_reply(pane):
    rows=[message('1'),message('2','bob',parentId='1'),message('3','alice',parentId='2'),message('4','bob')]
    pane.session=fake_session('discussion',rows)
    pane.compose.SetValue('Unsent message')
    pane.begin_reply(rows[1])
    pane.focus_thread(rows[2])
    assert pane.thread_root=='1' and pane.thread_banner.IsShown()
    assert [card.row['id'] for card in pane.cards]==['1','2','3']
    assert 'alice' in pane.thread_label.GetLabel()
    assert pane.compose.GetValue()=='Unsent message' and pane.reply_to=='2'
    pane.clear_thread()
    assert pane.thread_root is None and not pane.thread_banner.IsShown()
    assert [card.row['id'] for card in pane.cards]==['1','2','3','4']
    assert pane.reply_to=='2' and pane.compose.GetValue()=='Unsent message'
    pane.session.publish.assert_not_called()


def test_thread_scoped_search_people_and_anchor_filters_combine(pane):
    rows=[message('1'),message('2','bob','Expected polarity',parentId='1'),message('3','bob','Expected polarity outside')]
    rows[0]['anchors']=[]
    pane.session=fake_session(rows=rows)
    pane.populate()
    pane.focus_thread(rows[0])
    pane.search.ChangeValue('polarity')
    pane.author_filter.SetSelection(pane._author_names.index('bob')+1)
    pane.anchored_filter.SetValue(True)
    pane.filters_changed()
    assert [card.row['id'] for card in pane.cards]==['2']
    assert 'matches in this thread' in pane.status.GetLabel()
    pane.clear_filters()
    assert pane.thread_root=='1' and [card.row['id'] for card in pane.cards]==['1','2']
    assert not pane.clear_filter_button.IsEnabled()


def test_no_matches_explains_filters_instead_of_claiming_empty_provider(pane):
    pane.populate()
    pane.compose.SetValue('Keep this draft')
    pane.search.ChangeValue('no matching term')
    pane.filters_changed()
    labels=[child.GetLabel() for child in pane.feed.GetChildren()]
    assert 'No matching messages' in labels and 'Clear filters' in labels
    assert pane.compose.GetValue()=='Keep this draft'
    pane.clear_filters()
    assert len(pane.cards)==2


def test_deleted_thread_root_returns_to_feed_without_discarding_draft(pane):
    pane.populate()
    pane.focus_thread(pane.session.rows[0])
    pane.compose.SetValue('Draft remains')
    pane.session.rows=[message('4','bob','New surviving message')]
    pane.populate()
    assert pane.thread_root is None and not pane.thread_banner.IsShown()
    assert [card.row['id'] for card in pane.cards]==['4']
    assert pane.compose.GetValue()=='Draft remains'


def test_person_filter_survives_refresh_and_resets_if_author_is_removed(pane):
    pane.populate()
    pane.author_filter.SetSelection(pane._author_names.index('bob')+1)
    pane.filters_changed()
    pane.session.rows.append(message('3','carol'))
    pane.populate()
    assert pane.author_filter.GetStringSelection()=='bob'
    assert [card.row['author'] for card in pane.cards]==['bob']
    pane.session.rows=[message('4','carol')]
    pane.populate()
    assert pane.author_filter.GetSelection()==0 and len(pane.cards)==1


def key(code,ctrl=False,shift=False):
    event=Mock()
    event.GetKeyCode.return_value=code
    event.ControlDown.return_value=ctrl
    event.ShiftDown.return_value=shift
    return event


def test_escape_unwinds_preview_reply_thread_then_filters_without_losing_text(pane):
    pane.populate();pane.compose.SetValue('Draft')
    pane.focus_thread(pane.session.rows[0]);pane.begin_reply(pane.session.rows[0])
    pane.search.ChangeValue('Check');pane.populate()
    pane.shortcuts(key(ord('P'),True,True))
    assert pane.composer.book.GetSelection()==1
    pane.shortcuts(key(wx.WXK_ESCAPE))
    assert pane.composer.book.GetSelection()==0 and pane.reply_to=='1'
    pane.shortcuts(key(wx.WXK_ESCAPE))
    assert pane.reply_to is None and pane.thread_root=='1'
    pane.shortcuts(key(wx.WXK_ESCAPE))
    assert pane.thread_root is None and pane.search.GetValue()=='Check'
    pane.shortcuts(key(wx.WXK_ESCAPE))
    assert pane.search.GetValue()=='' and pane.compose.GetValue()=='Draft'
    pane.session.publish.assert_not_called()


def test_compact_formats_expand_and_switch_back_from_preview(pane):
    composer=pane.composer
    assert not composer.extra_formats.IsShown()
    composer.toggle_formats()
    assert composer.extra_formats.IsShown() and composer.more_button.active
    pane.compose.SetValue('first\nsecond');pane.compose.SelectAll()
    composer.toggle_preview();composer.format('numbered')
    assert composer.book.GetSelection()==0 and pane.compose.GetValue()=='1. first\n2. second'
    assert composer.write_button.active and not composer.preview_button.active
    composer.toggle_formats()
    assert not composer.extra_formats.IsShown()


def test_send_state_exposes_destination_reply_and_generated_text_budget(pane):
    pane.populate();pane.compose.SetValue('Review')
    pane.pending_attachments=[dict(url='https://gitlab.example.org/uploads/image.png')]
    row=pane.session.rows[0];pane.begin_reply(row)
    expected=len('Review\n\n![Screenshot](https://gitlab.example.org/uploads/image.png)')+len('> Reply to '+row['author']+' ('+row['url']+')\n\n')
    assert pane.send.GetLabel()=='Send reply'
    assert pane.composer.hint.GetLabel().startswith(str(expected)+' / 4000 published')
    assert 'Conversation #7' in pane.composer.mode_label.GetLabel()
    pane.cancel_reply()
    assert pane.send.GetLabel()=='Send message' and 'New message' in pane.composer.mode_label.GetLabel()
    assert pane.compose.GetValue()=='Review'


def test_card_actions_wrap_at_narrow_native_width_and_sidebar_yields_space(pane,app):
    row=message(body='Read ![Screenshot](https://example.com/image.png)')
    row['anchors'][0]['reference']='U123 · long component reference for review'
    pane.session=fake_session(rows=[row])
    pane.Show();pane.SetSize((660,800));pane.populate(force=True)
    app.Yield();pane.wrap_cards();pane.Layout();app.Yield()
    assert not pane.sidebar.IsShown()
    card=pane.cards[0]
    buttons=[child for child in card.GetChildren() if hasattr(child,'primary')]
    assert len({button.GetPosition().y for button in buttons})>1
    for button in buttons:
        assert button.GetPosition().x>=0
        assert button.GetPosition().x+button.GetSize().width<=card.GetClientSize().width+2
    assert pane.compose.GetValue()==''
