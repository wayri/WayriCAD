"""Lazy native lifetime checks; real browser acceptance is a separate gate."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

wx=pytest.importorskip('wx')
from review_comments_plugin.web_canvas import WebDesignCanvas


@pytest.fixture(scope='module')
def app():
    return wx.GetApp() or wx.App(False)


@pytest.fixture
def canvas(app,monkeypatch):
    monkeypatch.delenv('WAYRICAD_REVIEW_VIEWER_ROOT',raising=False)
    frame=wx.Frame(None)
    value=WebDesignCanvas(frame,SimpleNamespace(closed=False,review_theme='light'))
    sizer=wx.BoxSizer(wx.VERTICAL);sizer.Add(value,1,wx.EXPAND);frame.SetSizer(sizer)
    yield frame,value
    value.close()
    frame.Destroy();app.Yield()


def test_hidden_construction_never_starts_listener_or_browser(canvas,app):
    frame,value=canvas
    with patch('review_comments_plugin.web_host.ReviewWebHost') as host:
        app.Yield();value._start_pending_viewer()
    host.assert_not_called()
    assert not frame.IsShown() and value.browser is None and value.host is None
    assert value._pending_viewer_root.name=='kicad-webview'


def test_first_actual_parent_show_starts_pending_viewer(canvas,app):
    frame,value=canvas
    with patch.object(value,'start_viewer') as start:
        frame.Show();app.Yield();value._start_pending_viewer()
        assert start.called
        assert all(call.args[0]==value._pending_viewer_root for call in start.call_args_list)


def test_closed_and_owner_closed_guards_prevent_queued_browser_start(canvas,app):
    frame,value=canvas
    value.owner.closed=True
    with patch.object(value,'start_viewer') as start:
        frame.Show();app.Yield();value._start_pending_viewer()
        start.assert_not_called()
    value.owner.closed=False
    value.close()
    with patch.object(value,'start_viewer') as start:
        value._start_pending_viewer();app.Yield();start.assert_not_called()


def test_initialization_error_remains_visible_and_is_not_silenced(canvas,app):
    frame,value=canvas
    with patch.object(value,'start_viewer',side_effect=RuntimeError('fixture init failed')):
        frame.Show();app.Yield();value._start_pending_viewer()
    assert 'fixture init failed' in value.status.GetLabel()
    assert not value._viewer_starting


def test_hidden_override_is_retained_without_initializing(canvas,app,tmp_path):
    _frame,value=canvas
    assert value.start_viewer(tmp_path) is False
    assert value._pending_viewer_root==tmp_path
    assert value.browser is None and value.host is None
