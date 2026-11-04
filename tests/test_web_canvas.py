"""Native host controls and data bridge validation, without creating a WebView."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
wx = pytest.importorskip('wx')

from review_comments_plugin.web_canvas import WebDesignCanvas
from review_comments_plugin.web_documents import ReviewDocuments


SCOPE = dict(repository='example/board', ref='a'*40, file='board.kicad_pcb')
_APP = None


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP = wx.GetApp() or wx.App(False)
    return _APP


class Browser(wx.Panel):
    """A real native child window with a recording, non-executing JS boundary."""
    def __init__(self, parent, url):
        super().__init__(parent)
        self.url, self.scripts, self.destroy_count = url, [], 0

    def GetCurrentURL(self):
        return self.url

    def RunScript(self, script):
        self.scripts.append(script)
        return True

    def Destroy(self):
        self.destroy_count += 1
        return super().Destroy()


class Owner:
    def __init__(self, frame, path):
        self.closed = self.busy = False
        self.board_path = path
        self.compose = wx.TextCtrl(frame)
        self.target = None
        self.targets, self.focused, self.pending = [], [], []
        self.session = SimpleNamespace(path=path, digest=hashlib.sha256(path.read_bytes()).hexdigest(),
            scope=dict(SCOPE), status='synced', rows=[dict(id='7', body='Review point',
                anchors=[dict(SCOPE, position=dict(x=10, y=20))])],
            publish=Mock(side_effect=AssertionError('Host drafts must never publish.')),
            locate=Mock(side_effect=AssertionError('Independent navigation must not call KiCad.')))

    def set_target(self, target):
        self.target = deepcopy(target)
        self.targets.append(self.target)

    def focus_thread(self, row):
        self.focused.append(row['id'])

    def task(self, operation, complete, message, on_error=None):
        self.busy = True
        self.pending.append((operation, complete, on_error))
        return True

    def finish(self):
        operation, complete, failed = self.pending.pop(0)
        self.busy = False
        try:
            result = operation()
        except Exception as error:
            if failed is None:
                raise
            failed(str(error))
        else:
            complete(result)


@pytest.fixture
def panel(app, tmp_path, monkeypatch):
    monkeypatch.delenv('WAYRICAD_REVIEW_VIEWER_ROOT', raising=False)
    path = (tmp_path/'board.kicad_pcb').resolve()
    path.write_text('(kicad_pcb (version 20241229))', encoding='utf-8')
    path.with_suffix('.kicad_sch').write_text('(kicad_sch (version 20250114))', encoding='utf-8')
    frame = wx.Frame(None)
    owner = Owner(frame, path)
    # Suppress automatic backend construction even if a future test environment
    # supplies bundled assets. No actual browser, server or network is used.
    with patch.object(WebDesignCanvas, 'start_viewer'):
        canvas = WebDesignCanvas(frame, owner)
    host = SimpleNamespace(url='http://127.0.0.1:49231/secret/index.html', close=Mock())
    browser = Browser(canvas.view_area, host.url)
    canvas.host, canvas.browser = host, browser
    canvas.view_layout.Add(browser, 1, wx.EXPAND)
    canvas.documents = ReviewDocuments(path)
    canvas.ready = True
    canvas.apply_document('board.kicad_pcb', canvas.documents.load('board.kicad_pcb'))
    canvas.sync_review()
    browser.scripts.clear()
    yield canvas, owner, path, browser, host
    owner.closed = True
    canvas.close()
    frame.Destroy()
    app.Yield()


def message(canvas, value):
    raw = value if isinstance(value, str) else json.dumps(value)
    canvas.message(SimpleNamespace(GetString=lambda: raw, GetEventObject=lambda: canvas.browser))


def scoped(canvas, kind, **extra):
    return dict(type=kind, path=canvas.document_id, source_sha256=canvas.digest, **extra)


def calls(browser, method):
    prefix = 'window.wayricadReview.'+method+'('
    return [json.loads(script[len(prefix):-2]) for script in browser.scripts if script.startswith(prefix)]


@pytest.mark.parametrize('url', ['https://foreign.example/index.html', 'about:blank',
    'file:///tmp/index.html', 'http://127.0.0.1:49231/secret/index.html?forged=1'])
def test_only_exact_current_host_url_can_send_events(panel, url):
    canvas, owner, path, browser, host = panel
    browser.url = url
    message(canvas, scoped(canvas, 'draftAnchor', anchor=dict(position=dict(x=1, y=2))))
    assert owner.targets == [] and browser.scripts == []


def test_messages_from_destroyed_or_replaced_browser_cannot_reactivate_host(panel):
    canvas, owner, path, browser, host = panel
    canvas.ready = False
    canvas.message(SimpleNamespace(GetString=lambda: '{"type":"ready"}', GetEventObject=lambda: object()))
    assert not canvas.ready and browser.scripts == []


@pytest.mark.parametrize('change', [dict(path='other.kicad_pcb'), dict(source_sha256='c'*64),
                                  dict(path='../board.kicad_pcb'), dict(source_sha256=None)])
def test_old_or_foreign_source_identity_cannot_draft(panel, change):
    canvas, owner, path, browser, host = panel
    payload = scoped(canvas, 'draftAnchor', anchor=dict(position=dict(x=1, y=2)))
    payload.update(change)
    message(canvas, payload)
    assert owner.targets == []
    assert 'older or different' in canvas.status.GetLabel()
    assert calls(browser, 'setComments')[-1]['status'] == 'stale'


def test_forged_draft_scope_is_rebased_to_current_authoritative_session_without_writes(panel):
    canvas, owner, path, browser, host = panel
    before = path.read_bytes()
    forged = dict(repository='attacker/project', ref='f'*40, file='secret.kicad_pcb',
                  uuid='untrusted-object', kind='arbitrary', position=dict(x=12.5, y=-4))
    message(canvas, scoped(canvas, 'draftAnchor', anchor=forged))
    assert owner.target == dict(SCOPE, kind='position', position=dict(x=12.5, y=-4))
    message(canvas, scoped(canvas, 'draftAnchor', anchor=dict(forged, area=dict(x=1,y=2,width=3,height=4))))
    assert owner.target == dict(SCOPE, kind='region', area=dict(x=1.,y=2.,width=3.,height=4.))
    assert path.read_bytes() == before
    owner.session.publish.assert_not_called()
    owner.session.locate.assert_not_called()


@pytest.mark.parametrize('state', ['offline / stale', 'cached / unverified', 'publication pending'])
def test_provider_must_be_synced_even_for_current_source_draft_messages(panel, state):
    canvas, owner, path, browser, host = panel
    owner.session.status = state
    message(canvas, scoped(canvas, 'draftAnchor', anchor=dict(position=dict(x=1,y=2))))
    assert owner.targets == [] and not canvas.can_anchor(quiet=True)


@pytest.mark.parametrize('change', ['path', 'digest'])
def test_session_identity_must_match_current_document_before_authorizing_drafts(panel, change):
    canvas, owner, path, browser, host = panel
    setattr(owner.session, change, path.with_name('other.kicad_pcb') if change == 'path' else 'f'*64)
    message(canvas, scoped(canvas, 'draftAnchor', anchor=dict(position=dict(x=1,y=2))))
    assert owner.targets == [] and not canvas.can_anchor(quiet=True)


@pytest.mark.parametrize('target', [dict(position=dict(x=math.nan,y=2)), dict(position=dict(x=True,y=2)),
    dict(area=dict(x=0,y=0,width=0,height=4)), dict(area=['bad']), {}, None])
def test_malformed_or_nonfinite_draft_coordinates_never_reach_composer(panel, target):
    canvas, owner, path, browser, host = panel
    message(canvas, scoped(canvas, 'draftAnchor', anchor=target))
    assert owner.targets == []


def test_changed_file_disables_marker_events_and_clears_frontend_authority(panel):
    canvas, owner, path, browser, host = panel
    path.write_text('changed saved source', encoding='utf-8')
    message(canvas, scoped(canvas, 'draftAnchor', anchor=dict(position=dict(x=1,y=2))))
    assert owner.targets == [] and canvas.markers == []
    assert 'changed' in canvas.status.GetLabel()
    assert calls(browser, 'setComments')[-1]['status'] == 'stale'


def test_request_document_uses_catalog_allowlist_and_keeps_independent_preview_unbound(panel):
    canvas, owner, path, browser, host = panel
    message(canvas, scoped(canvas, 'requestDocument', id='../secret.kicad_pcb'))
    assert canvas.path == path
    assert 'not registered' in canvas.status.GetLabel()
    message(canvas, scoped(canvas, 'requestDocument', id='board.kicad_sch'))
    assert canvas.path == path.with_suffix('.kicad_sch')
    assert canvas.pending['scope'] is None
    assert not canvas.can_anchor(quiet=True)
    owner.session.publish.assert_not_called()


def test_scope_promotion_after_connect_sends_exact_document_identity_without_reload(panel):
    canvas, owner, path, browser, host = panel
    session = owner.session
    owner.session = None
    canvas.apply_document('board.kicad_pcb', canvas.documents.load('board.kicad_pcb'))
    assert canvas.pending['scope'] is None
    browser.scripts.clear()
    owner.session = session
    canvas.sync_review()
    payload = calls(browser, 'setComments')[-1]
    assert payload['scope'] == SCOPE and payload['status'] == 'synced'
    assert payload['path'] == 'board.kicad_pcb' and payload['source_sha256'] == canvas.digest
    assert len(payload['markers']) == 1
    assert calls(browser, 'setDocument') == []


def test_marker_click_and_message_focus_are_bidirectional_without_native_selection(panel):
    canvas, owner, path, browser, host = panel
    message(canvas, scoped(canvas, 'focusThread', comment_id='unknown'))
    assert owner.focused == []
    message(canvas, scoped(canvas, 'focusThread', comment_id='7'))
    assert owner.focused == ['7'] and canvas.selected_id == '7'
    assert canvas.focus_comment('7')
    assert calls(browser, 'focusComment') == ['7']
    owner.session.locate.assert_not_called()


def test_draft_preview_requires_matching_scope_source_and_provider(panel):
    canvas, owner, path, browser, host = panel
    owner.target = dict(SCOPE, kind='position', position=dict(x=12.5, y=7))
    canvas.sync_draft()
    assert calls(browser, 'setDraft')[-1] == owner.target
    owner.target = dict(owner.target, file='other.kicad_pcb')
    canvas.sync_draft()
    assert calls(browser, 'setDraft')[-1] is None
    owner.target = dict(SCOPE, kind='region', area=dict(x=1,y=2,width=3,height=4))
    owner.session.status = 'stale'
    canvas.sync_draft()
    assert calls(browser, 'setDraft')[-1] is None
    owner.session.status = 'synced'
    path.write_text('changed source', encoding='utf-8')
    canvas.sync_draft()
    assert calls(browser, 'setDraft')[-1] is None
    owner.session.publish.assert_not_called()


def test_saved_uuid_only_comments_and_drafts_resolve_in_current_document(panel):
    canvas, owner, path, browser, host = panel
    path.write_text('(kicad_pcb (footprint "Demo" (layer "F.Cu") (at 15 22) (uuid "saved-part")))', encoding='utf-8')
    owner.session.digest = hashlib.sha256(path.read_bytes()).hexdigest()
    target = dict(SCOPE, kind='footprint', uuid='saved-part', reference='U1')
    owner.session.rows = [dict(id='8', body='Check U1', anchors=[target])]
    canvas.apply_document('board.kicad_pcb', canvas.documents.load('board.kicad_pcb'))
    canvas.sync_review()
    marker = calls(browser, 'setComments')[-1]['markers'][0]
    assert marker['x'] == 15 and marker['y'] == 22
    owner.target = target
    canvas.sync_draft()
    assert calls(browser, 'setDraft')[-1]['position'] == dict(x=15., y=22.)
    assert 'position' not in target  # Preview does not rewrite the publication anchor.
    owner.session.publish.assert_not_called()


def test_javascript_invocation_keeps_user_strings_as_json_data_and_rejects_nan(panel):
    canvas, owner, path, browser, host = panel
    data = dict(source='\"}); window.pwned=true; //\u2028</script>', path='board.kicad_pcb')
    canvas._call('setDocument', data)
    assert calls(browser, 'setDocument') == [data]
    assert browser.scripts[-1].startswith('window.wayricadReview.setDocument({')
    assert '\\u2028' in browser.scripts[-1]
    before = len(browser.scripts)
    with pytest.raises(ValueError):
        canvas._call('setDocument', dict(x=math.nan))
    assert len(browser.scripts) == before


def test_oversized_invalid_and_unknown_messages_never_execute_requested_code(panel):
    canvas, owner, path, browser, host = panel
    for raw in ('x'*(256*1024+1), '[]', 'null', '{broken', '{"type":"eval","code":"alert(1)"}'):
        message(canvas, raw)
    message(canvas, scoped(canvas, 'RunScript', code='alert(1)'))
    assert owner.targets == []
    assert all(script.startswith('window.wayricadReview.setComments(') for script in browser.scripts)


def test_deeply_nested_json_cannot_escape_native_event_handler(panel):
    canvas, owner, path, browser, host = panel
    message(canvas, '['*2000+'0'+']'*2000)
    assert owner.targets == []


def test_close_owns_browser_and_loopback_host_exactly_once_and_revokes_messages(panel):
    canvas, owner, path, browser, host = panel
    canvas.close()
    canvas.close()
    assert browser.destroy_count == 1
    host.close.assert_called_once()
    assert canvas.browser is None and canvas.host is None and not canvas.ready
    message(canvas, scoped(canvas, 'draftAnchor', anchor=dict(position=dict(x=1,y=2))))
    assert owner.targets == []


def test_closed_or_superseded_canvas_ignores_pending_load_completion(panel):
    canvas, owner, path, browser, host = panel
    previous = canvas.pending
    canvas.load(path.with_suffix('.kicad_sch'))
    canvas.close()
    owner.finish()
    assert canvas.pending is previous
    assert canvas.path == path


def test_editor_launch_automatically_opens_its_saved_design(app, tmp_path, monkeypatch):
    from review_comments_plugin.conversation_ui import ConversationPane
    monkeypatch.delenv('WAYRICAD_REVIEW_VIEWER_ROOT', raising=False)
    path = (tmp_path/'origin.kicad_pcb').resolve()
    path.write_text('(kicad_pcb (version 20241229))', encoding='utf-8')
    with patch.object(WebDesignCanvas, 'start_viewer'), patch.object(WebDesignCanvas, 'load') as load:
        window = ConversationPane(board_path=path, settings={})
        try:
            app.Yield()
            load.assert_called_once_with(path)
        finally:
            window.closed = True
            window.timer.Stop()
            window.Destroy()
            app.Yield()
