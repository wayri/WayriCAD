"""Native card feed, reply composer and lossless conversation transitions."""
from types import SimpleNamespace
from unittest.mock import patch, Mock

import pytest
wx = pytest.importorskip('wx')

from review_comments_plugin.conversation_ui import ConversationPane, MessageCard, short_time

BASE = dict(repository='example/board', ref='a' * 40, file='board.kicad_pcb')


def fake_session(kind='issue', rows=None, draft=None):
    return SimpleNamespace(scope=BASE, rows=rows or [], participants=['alice', 'bob'],
        synced_at='2026-10-29T00:00:00Z', status='synced', cache_warning=None,
        provider=SimpleNamespace(kind=kind, provider='github', number=7,
            web_url='https://github.com/example/board/' + ('discussions/' if kind == 'discussion' else 'issues/') + '7'),
        draft=Mock(side_effect=lambda *args: draft if not args else None),
        publish=Mock(return_value='DC_new' if kind == 'discussion' else '91'))


def message(identifier='1', author='alice', body='Check J2 pin 1', **extra):
    return dict(id=identifier, author=author, body=body, updatedAt='2026-10-29T00:00:00Z',
                anchors=[dict(BASE, reference='J2', uuid='example-j2')], url='https://github.com/example/board/issues/7', **extra)


@pytest.fixture(scope='module')
def app():
    return wx.GetApp() or wx.App(False)


@pytest.fixture
def pane(app):
    window = ConversationPane(settings={})
    window.session = fake_session(rows=[message(), message('2', 'bob', 'Confirmed the mating-side view.', parentId='1')])
    window.refresh = lambda *args: None
    yield window
    window.closed = True
    if window.resize_call:
        window.resize_call.Stop()
    window.Destroy()
    app.Yield()


def test_individual_message_cards_replace_table_and_details(pane):
    pane.populate()
    assert len(pane.cards) == 2
    assert all(isinstance(card, MessageCard) for card in pane.cards)
    assert not hasattr(pane, 'comments') and not hasattr(pane, 'detail')
    assert pane.tabs.GetPageText(0) == 'Comments'
    assert pane.tabs.GetPageText(1) == 'Discussions'
    assert any(child.GetLabel() == 'Reply' for child in pane.cards[0].GetChildren())


def test_inline_reply_banner_and_real_discussion_reply_target(pane):
    pane.session = fake_session('discussion', [message('DC_parent')])
    pane.begin_reply(pane.session.rows[0])
    assert pane.reply_banner.IsShown() and 'alice' in pane.reply_label.GetLabel()
    pane.compose.SetValue('Use the top-side orientation.')
    captured = []
    pane.task = lambda operation, completed, *args, **kwargs: captured.append((operation, completed))
    pane.post()
    captured[0][0]()
    args, kwargs = pane.session.publish.call_args
    assert kwargs['reply_to'] == 'DC_parent'
    assert not args[0].startswith('> Reply')
    captured[0][1]('DC_new')
    assert pane.compose.GetValue() == '' and not pane.reply_banner.IsShown()


def test_conversation_transition_failure_keeps_outgoing_draft_and_tab(pane):
    outgoing = pane.session
    outgoing.draft.side_effect = OSError('disk full')
    pane.compose.SetValue('Do not lose this draft')
    pane.tabs.ChangeSelection(1)
    def task(operation, completed, *args, **kwargs):
        try:
            completed(operation())
        except OSError as error:
            kwargs['on_error'](str(error))
        return True
    pane.task = task
    pane.connect(dict(BASE, provider='github', kind='issue', number=7, discussionNumber=8))
    assert pane.session is outgoing and pane.tabs.GetSelection() == 0
    assert pane.compose.GetValue() == 'Do not lose this draft'
    assert pane.compose.IsEnabled() and pane.send.IsEnabled()


def test_transition_blocks_editing_until_destination_draft_is_loaded(pane):
    outgoing = pane.session
    pane.compose.SetValue('Outgoing draft')
    captured = []
    pane.task = lambda operation, completed, *args, **kwargs: captured.append((operation, completed)) or True
    pane.connect(dict(BASE, provider='github', kind='issue', number=7))
    assert not pane.compose.IsEnabled() and not pane.send.IsEnabled()
    destination = fake_session(draft=dict(text='Destination draft', anchor=BASE, attachments=[]))
    captured[0][1](destination)
    assert pane.session is destination
    assert pane.compose.GetValue() == 'Destination draft'
    assert pane.compose.IsEnabled() and pane.send.IsEnabled()


def test_next_draft_typed_during_publication_is_not_erased(pane):
    pane.compose.SetValue('First message')
    captured = []
    pane.task = lambda operation, completed, *args, **kwargs: captured.append(completed)
    pane.post()
    pane.compose.SetValue('Next message typed while the request runs')
    captured[0]('91')
    assert pane.compose.GetValue() == 'Next message typed while the request runs'


def test_post_success_cache_failure_is_reported_without_escaping(pane):
    pane.compose.SetValue('First message')
    captured = []
    pane.task = lambda operation, completed, *args, **kwargs: captured.append(completed)
    pane.post()
    pane.session.draft.side_effect = OSError('disk full')
    captured[0]('91')
    assert 'Message was sent' in pane.status.GetLabel()


def test_feed_only_constructs_eighty_cards_at_a_time(pane):
    pane.session.rows = [message(str(i), body='Trace review ' + str(i)) for i in range(200)]
    pane.populate()
    assert len(pane.cards) == 80 and pane.cards[0].row['id'] == '120'
    pane.page_messages(40)
    assert len(pane.cards) == 80 and pane.cards[0].row['id'] == '40'
    pane.page_messages(None)
    assert len(pane.cards) == 80 and pane.cards[-1].row['id'] == '199'


def test_search_and_refresh_preserve_composer(pane):
    pane.compose.SetValue('Unsent engineering note')
    pane.search.SetValue('mating')
    pane.populate(force=True)
    assert len(pane.cards) == 1 and pane.cards[0].row['author'] == 'bob'
    assert pane.compose.GetValue() == 'Unsent engineering note'


def test_attachment_chips_are_removable_without_json_or_url_in_composer(pane):
    receipt = dict(markdown='![Screenshot](https://gitlab.example.org/image.png)',
                   attachment=dict(url='https://gitlab.example.org/image.png', width=10, height=10))
    pane.attachment_received(receipt)
    assert pane.compose.GetValue() == ''
    assert len(pane.pending_attachments) == 1
    assert pane.attachments_label.IsShown()
    pane.remove_attachment(0)
    assert pane.pending_attachments == [] and not pane.attachments_label.IsShown()


def test_gitlab_does_not_silently_substitute_issues_for_github_discussions(pane):
    outgoing = pane.session
    pane.tabs.ChangeSelection(1)
    pane.connect(dict(BASE, provider='gitlab', host='https://gitlab.example.org', kind='issue', number=7))
    assert pane.session is outgoing and pane.tabs.GetSelection() == 0
    assert 'GitHub Discussions' in pane.status.GetLabel()


def test_message_text_is_not_executed_as_html(pane):
    pane.session.rows = [message(body='<script>throw new Error("unsafe")</script>')]
    pane.populate()
    assert '<script>' in pane.cards[0].body.GetLabel()


def test_timestamps_survive_wx_windows_locale_initialization(app):
    value = short_time('2026-10-29T06:45:00Z')
    assert '29' in value and ':' in value and '·' in value


def test_workspace_has_guided_workflow_resizable_composer_and_drop_target(pane):
    from review_comments_plugin.composer_ui import ReviewDropTarget
    assert pane.sidebar.IsShown()
    pane.toggle_workflow()
    assert not pane.sidebar.IsShown()
    assert pane.splitter.IsSplit()
    assert isinstance(pane.compose.GetDropTarget(), ReviewDropTarget)
    assert {'bold', 'italic', 'link', 'table', 'codeblock', 'tasks'} <= pane.composer.format_buttons.keys()


def test_rich_composer_preserves_markdown_and_local_preview(pane):
    pane.compose.SetValue('Check J2')
    pane.compose.SetSelection(0, 5)
    pane.composer.format('bold')
    assert pane.compose.GetValue() == '**Check** J2'
    pane.composer.toggle_preview()
    assert pane.composer.book.GetSelection() == 1
    pane.composer.toggle_preview()
    assert pane.compose.GetValue() == '**Check** J2'


def test_formatting_multiline_unicode_uses_native_offsets(pane):
    pane.compose.SetValue('😀 first\nsecond')
    start = pane.composer.native_offset(len('😀 first\n'))
    pane.compose.SetSelection(start, pane.compose.GetLastPosition())
    pane.composer.format('italic')
    assert pane.compose.GetValue() == '😀 first\n*second*'


def test_file_drop_routes_to_attachment_flow_without_auto_posting(pane):
    target = pane.compose.GetDropTarget()
    target.GetData = lambda: True
    target.data = SimpleNamespace(GetReceivedFormat=lambda: wx.DataFormat(wx.DF_FILENAME))
    target.files = SimpleNamespace(GetFilenames=lambda: ['example.png'])
    pane.attach_files = Mock()
    assert target.OnData(0, 0, wx.DragCopy) == wx.DragCopy
    pane.attach_files.assert_called_once_with(['example.png'])
    pane.session.publish.assert_not_called()


def test_paste_html_is_converted_to_markdown_not_executed(pane):
    class Clipboard:
        def Open(self): return True
        def Close(self): pass
        def IsSupported(self, kind): return kind.GetType() != wx.DF_BITMAP
        def GetData(self, value):
            if isinstance(value, wx.HTMLDataObject):
                value.SetHTML('<p><strong>J2</strong> orientation</p><script>bad()</script>')
                return True
            return False
    with patch.object(wx, 'TheClipboard', Clipboard()):
        pane.composer.paste()
    assert '**J2**' in pane.compose.GetValue()
    assert 'bad()' not in pane.compose.GetValue()


def test_inserting_from_preview_returns_to_editor_and_preserves_selection(pane):
    pane.compose.SetValue('Check J2')
    pane.compose.SetSelection(6, 8)
    pane.composer.toggle_preview()
    assert pane.composer.book.GetSelection() == 1
    pane.composer.insert_text('J3')
    assert pane.composer.book.GetSelection() == 0
    assert pane.compose.GetValue() == 'Check J3'
    pane.session.publish.assert_not_called()


def test_overlong_message_is_kept_local_without_provider_request(pane):
    pane.compose.SetValue('x'*4001)
    pane.task = Mock()
    pane.post()
    assert pane.compose.GetValue() == 'x'*4001
    pane.task.assert_not_called()
    assert '4,000' in pane.status.GetLabel()


def test_guided_setup_retains_values_across_steps_and_has_cancel(pane):
    from review_comments_plugin.settings_ui import ReviewSetup
    dialog = ReviewSetup(pane, dict(BASE, provider='github', number=7))
    try:
        assert dialog.book.GetPageCount() == 3
        dialog.fields['repository'].SetValue('example/edited')
        dialog.go(2)
        assert dialog.next.GetLabel() == 'Connect review'
        dialog.go(0)
        assert dialog.fields['repository'].GetValue() == 'example/edited'
        assert not dialog.back.IsEnabled()
    finally:
        dialog.Destroy()


def test_image_files_decode_preview_and_queue_without_publishing(pane, tmp_path, app):
    paths = []
    for name in ('one.png', 'two.png'):
        path = tmp_path/name
        bitmap = wx.Bitmap(20, 10)
        assert bitmap.SaveFile(str(path), wx.BITMAP_TYPE_PNG)
        paths.append(str(path))
    pane.session.provider.provider = 'gitlab'
    pane.session.provider.upload_png = Mock(side_effect=lambda data: dict(attachment=dict(
        url='https://gitlab.example.org/uploads/'+str(len(pane.pending_attachments))+'.png', width=20, height=10)))
    pane.task = lambda operation, complete, *args, **kwargs: complete(operation()) or True
    with patch.object(wx.Dialog, 'ShowModal', return_value=wx.ID_OK):
        pane.attach_files(paths)
        app.Yield()
    assert len(pane.pending_attachments) == 2
    assert len(pane._thumbnails) == 2
    pane.session.publish.assert_not_called()


def test_cancelled_image_preview_never_uploads_or_posts(pane):
    pane.session.provider.provider = 'gitlab'
    pane.task = Mock()
    with patch.object(wx.Dialog, 'ShowModal', return_value=wx.ID_CANCEL):
        pane.attach_bitmap(wx.Bitmap(10, 10))
    assert pane.pending_attachments == []
    pane.task.assert_not_called()
    pane.session.publish.assert_not_called()


def test_cached_reply_without_url_is_readable_but_cannot_publish(pane):
    pane.session.status = 'cached / unverified'
    pane.session.rows[0].pop('url')
    pane.begin_reply(pane.session.rows[0])
    pane.compose.SetValue('Keep this draft')
    pane.post()
    assert pane.compose.GetValue() == 'Keep this draft'
    assert 'unverified' in pane.status.GetLabel()
    pane.session.publish.assert_not_called()


@pytest.mark.parametrize('succeeds', [True, False])
def test_terminal_fallback_copies_only_on_action_and_reports_failure(pane, succeeds):
    from review_comments_plugin.settings_ui import ReviewSetup
    values = []
    class Clipboard:
        def Open(self): return True
        def Close(self): pass
        def SetData(self, data):
            values.append(data.GetText())
            return succeeds
    dialog = ReviewSetup(pane, dict(provider='gitlab', host='https://gitlab.example.org'))
    try:
        assert values == []
        with patch.object(wx, 'TheClipboard', Clipboard()):
            dialog.copy_login()
        assert "'glab' 'auth' 'login'" in values[0]
        assert "'--web'" in values[0] and 'token' not in values[0]
        assert ('Copied' in dialog.login_status.GetValue()) is succeeds
    finally:
        dialog.Destroy()
