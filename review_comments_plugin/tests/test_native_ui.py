"""Hidden native wx construction/interactions; no live editor or provider is substituted."""
from types import SimpleNamespace
from unittest.mock import patch
import io

import pytest
wx = pytest.importorskip('wx')

from review_comments_plugin.ui import ReviewPane, Settings
from review_comments_plugin.model import note, markdown

BASE = dict(repository='example/board', ref='a' * 40, file='board.kicad_pcb')


@pytest.fixture(scope='module')
def app():
    return wx.GetApp() or wx.App(False)


@pytest.fixture
def pane(app):
    window = ReviewPane(settings={})
    window.session = SimpleNamespace(scope=BASE, rows=[], participants=['alice', 'bob'],
        synced_at='2026-10-29T00:00:00Z', status='synced', cache_warning=None,
        provider=SimpleNamespace(provider='github', web_url='https://github.com/example/board/issues/7'),
        draft=lambda *a: None)
    yield window
    window.closed = True
    window.Destroy()
    app.Yield()


def test_resizable_pane_and_scrollable_settings(pane):
    pane.SetSize((430, 470))
    pane.Layout()
    assert pane.GetMinSize().width == 420
    with Settings(pane, dict(BASE, number=7)) as settings:
        assert settings.fields['ref'].GetValue() == BASE['ref']
        settings.fields['provider'].SetValue('github')
        assert settings.read()['number'] == 7


def test_participant_filter_cross_select_text_and_location(pane):
    rows = [dict(id='1', author='alice', body='Check U1', updatedAt='now', anchors=[dict(BASE, uuid='one')]),
            dict(id='2', author='bob', body='Check R1', updatedAt='now', anchors=[])]
    pane.session.rows = rows
    pane.populate()
    pane.participants.SetStringSelection('alice')
    pane.populate()
    assert pane.comments.GetItemCount() == 1
    pane.comments.Select(0)
    pane.selected(None)
    assert 'Check U1' in pane.detail.GetValue()
    assert 'Location available' in pane.detail.GetValue()
    pane.compose.SetValue('unpublished text survives refresh')
    pane.populate()
    assert pane.compose.GetValue() == 'unpublished text survives refresh'


def test_pending_publication_does_not_erase_next_draft(pane):
    callbacks = []
    pane.compose.SetValue('first draft')
    pane.task = lambda operation, completed, *args, **kwargs: callbacks.append(completed)
    pane.refresh = lambda *args: None
    pane.post()
    assert len(callbacks) == 1
    pane.compose.SetValue('next draft typed while request is pending')
    callbacks[0]('91')
    assert pane.compose.GetValue() == 'next draft typed while request is pending'


def test_cached_url_is_not_used_for_browser_navigation(pane):
    pane.session.rows = [dict(id='5', author='alice', body='Cached text', updatedAt='now', root=False,
                             url='file:///untrusted/cache-link', anchors=[])]
    pane.populate()
    pane.comments.Select(0)
    with patch('review_comments_plugin.ui.webbrowser.open') as open_url:
        pane.open_provider()
    assert open_url.call_args.args[0] == 'https://github.com/example/board/issues/7#issuecomment-5'


def test_png_clipboard_encoding_is_native_supported(app):
    image = wx.Image(30, 20)
    image.SetRGB(wx.Rect(0, 0, 30, 20), 40, 120, 160)
    stream = io.BytesIO()
    assert image.SaveFile(stream, wx.BITMAP_TYPE_PNG)
    assert stream.getvalue().startswith(b'\x89PNG\r\n\x1a\n')


def test_multiple_author_highlights_keep_all_comments(pane):
    pane.session.rows = [dict(id=str(i), author=author, body='Review', updatedAt='now', anchors=[])
                         for i, author in enumerate(['alice', 'bob', 'charlie'])]
    pane.highlighted_authors = {'alice', 'bob'}
    pane.populate()
    assert pane.comments.GetItemCount() == 3
    assert pane.comments.GetItemBackgroundColour(0).IsOk()
    assert pane.comments.GetItemBackgroundColour(1).IsOk()
