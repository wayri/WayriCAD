"""Desktop authorization at provider and saved-review boundaries."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from review_comments_plugin import desktop_auth, providers, session as sessions


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    clock = [1000., 2000.]
    monkeypatch.setattr(desktop_auth, 'time', SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[1]))
    authority = desktop_auth._Authority()
    monkeypatch.setattr(desktop_auth, 'AUTH', authority)
    board = tmp_path/'board.kicad_pcb'
    board.write_text('(kicad_pcb)', encoding='utf-8')
    monkeypatch.setattr(sessions, 'saved_context', lambda *args: (board, 'd'*64))
    monkeypatch.setattr(sessions, 'unchanged', lambda *args: None)
    settings = dict(repository='example/board', ref='a'*40, file=board.name, root=str(tmp_path), number=1)
    calls = []
    def transport(method, url, headers, data=None):
        calls.append((method, url, headers, data))
        return 200, {}, {'ok':True}
    monkeypatch.setattr(providers, 'request', transport)
    return authority, settings, clock, calls, tmp_path


def install(authority, provider='github', origin='https://github.com'):
    epoch = authority.begin(provider, origin)
    authority.install(provider, origin, 'fixture-token', epoch=epoch, account='reviewer')
    return epoch


def test_desktop_has_no_implicit_cli_fallback(desktop):
    authority, settings, clock, calls, folder = desktop
    with pytest.raises(desktop_auth.SignInRequired):
        sessions.ReviewSession(settings, desktop=True, cache_dir=folder)
    assert calls == []


@pytest.mark.parametrize('provider,origin', [('github','https://github.com'), ('gitlab','https://gitlab.example')])
def test_desktop_requests_use_bearer_and_stop_at_eight_hour_boundary(desktop, provider, origin):
    authority, settings, clock, calls, folder = desktop
    install(authority, provider, origin)
    if provider == 'gitlab':
        settings.update(provider=provider, host=origin)
    review = sessions.ReviewSession(settings, desktop=True, cache_dir=folder)
    review.provider._call('GET', '/user')
    assert calls[-1][2]['Authorization'] == 'Bearer fixture-token'
    assert 'PRIVATE-TOKEN' not in calls[-1][2]
    clock[1] += desktop_auth.TTL
    before = len(calls)
    with pytest.raises(desktop_auth.SignInRequired):
        review.provider._call('POST', '/notes', {'body':'must not send'})
    assert len(calls) == before


def test_late_response_cannot_restore_signed_out_authority(desktop, monkeypatch):
    authority, settings, clock, calls, folder = desktop
    install(authority)
    def late_transport(*args):
        authority.sign_out('github','https://github.com')
        return 200, {}, {'private':'late response'}
    monkeypatch.setattr(providers, 'request', late_transport)
    review = sessions.ReviewSession(settings, desktop=True, cache_dir=folder)
    with pytest.raises(desktop_auth.SignInRequired):
        review.provider._call('GET','/user')


def test_old_session_does_not_inherit_new_signin_and_expiry_keeps_local_draft(desktop):
    authority, settings, clock, calls, folder = desktop
    install(authority)
    backend = Mock(kind='issue', number=1, provider='github')
    review = sessions.ReviewSession(settings, desktop=True, provider=backend, cache_dir=folder)
    review.draft('Unpublished text', review.scope)
    install(authority)  # A newly authorized account/epoch does not reauthorize old work.
    with pytest.raises(desktop_auth.SignInRequired):
        review.refresh()
    backend.snapshot.assert_not_called()
    assert review.status == 'signed out'
    assert review.draft()['text'] == 'Unpublished text'
