"""Provider boundary, authoritative anchors, stale guards and immutable source checks."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from review_comments_plugin.model import anchor, host, markdown, note, read_markers, saved_context
from review_comments_plugin.providers import Provider, NoRedirect, login_command, verify_login, login_status
from review_comments_plugin.session import ReviewSession, atomic_json

BASE = dict(repository='example/board', ref='a' * 40, file='board.kicad_pcb')


def test_browser_login_uses_official_cli_and_explicit_gitlab_host():
    command = login_command('gitlab', 'https://gitlab.example.org')
    assert command[:3] == ['glab', 'auth', 'login']
    assert '--web' in command
    for option in ('--hostname', '--api-host', '--container-registry-domains'):
        assert command[command.index(option) + 1] == 'gitlab.example.org'
    assert command[command.index('--api-protocol') + 1] == 'https'
    assert not any('token' in part or 'secret' in part for part in command)


def test_browser_login_rejects_gitlab_host_credentials():
    with pytest.raises(ValueError):
        login_command('gitlab', 'https://name:secret@gitlab.com')


def test_login_confirmation_requires_actual_provider_account_response():
    with patch('review_comments_plugin.providers.run', return_value='{"id": 42, "private_email": "never-returned"}') as run:
        assert verify_login('gitlab', 'https://gitlab.example.org') is True
        assert run.call_args.args[0] == ['glab', 'api', 'user', '--hostname', 'gitlab.example.org']


@pytest.mark.parametrize('response', ['{}', '[]', 'not-json', '{"id":true}'])
def test_failed_login_cannot_report_connected(response):
    with patch('review_comments_plugin.providers.run', return_value=response):
        with pytest.raises(RuntimeError, match='CLI session check failed'):
            verify_login('gitlab', 'https://gitlab.com')


@pytest.mark.parametrize('error, category', [
    (FileNotFoundError('private local path'), 'cli-unavailable'),
    (subprocess.TimeoutExpired(['glab'], 25), 'timeout'),
    (subprocess.CalledProcessError(1, ['glab'], stderr=b'HTTP 401: private diagnostic'), 'http-401'),
    (subprocess.CalledProcessError(1, ['glab'], stderr=b'HTTP 403: private diagnostic'), 'http-403'),
    (subprocess.CalledProcessError(1, ['glab'], stderr=b'lookup gitlab.com: no such host'), 'network-or-tls'),
    (subprocess.CalledProcessError(1, ['glab'], stderr=b'private diagnostic'), 'cli-rejected'),
])
def test_login_failure_categories_never_return_diagnostics(error, category):
    with patch('review_comments_plugin.providers.run', side_effect=error):
        result = login_status('gitlab', 'https://gitlab.com')
    assert result == dict(authenticated=False, category=category)
    assert 'private' not in json.dumps(result)


def test_login_accepts_utf8_bom_but_not_coloured_or_nonaccount_output():
    with patch('review_comments_plugin.providers.run', return_value='\ufeff{"id":42}'):
        assert login_status('gitlab', 'https://gitlab.com')['authenticated']
    with patch('review_comments_plugin.providers.run', return_value='\x1b[32m{"id":42}'):
        assert login_status('gitlab', 'https://gitlab.com') == dict(authenticated=False, category='malformed-json', ansi_present=True, bom_present=False)


def test_cli_check_login_is_read_only_and_diagnostic_is_secret_free(capsys):
    from review_comments_plugin.cli import main
    with patch('review_comments_plugin.providers.login_status', return_value=dict(authenticated=False, category='http-401')):
        assert main(['check-login', '--diagnose']) == 2
    assert json.loads(capsys.readouterr().out) == dict(authenticated=False, category='http-401')


def test_cli_open_does_not_require_settings_or_start_sign_in():
    from review_comments_plugin.cli import main
    with patch('review_comments_plugin.cli.open_workspace', return_value=0) as launch:
        assert main(['open']) == 0
    assert launch.call_args.args[0].settings is None


def test_native_desktop_fallback_preserves_existing_auth_without_token_arguments(monkeypatch):
    import sys
    from review_comments_plugin.cli import main
    monkeypatch.setitem(sys.modules, 'wx', None)
    monkeypatch.setenv('GITLAB_ACCESS_TOKEN', 'example-only-not-a-credential')
    with patch('wayricad_runtime.runtime_setup.native_python', return_value=Path('native-python')), \
            patch('review_comments_plugin.cli.subprocess.run', return_value=SimpleNamespace(returncode=0)) as execute:
        assert main(['open']) == 0
    assert execute.call_args.kwargs['env']['GITLAB_ACCESS_TOKEN'] == 'example-only-not-a-credential'
    assert 'example-only-not-a-credential' not in json.dumps(execute.call_args.args[0])
    assert execute.call_args.kwargs['stdin'] is subprocess.DEVNULL


def test_cli_saved_source_inspection_has_no_provider_access(tmp_path, capsys):
    from review_comments_plugin.cli import main
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, stdin=subprocess.DEVNULL,
                              capture_output=True, check=True)
    git('init', '--quiet')
    board = tmp_path / 'example.kicad_pcb'
    board.write_bytes(b'(kicad_pcb (version 20240108))\n')
    git('add', board.name)
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    with patch('review_comments_plugin.providers.credential', side_effect=AssertionError('No authentication expected')):
        assert main(['inspect-source', str(board)]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['file'] == board.name and len(result['source_sha256']) == 64
        board.write_bytes(b'changed')
        assert main(['inspect-source', str(board)]) == 2


def test_cli_missing_settings_is_actionable(capsys):
    from review_comments_plugin.cli import main
    assert main(['sync']) == 2
    assert '--settings' in capsys.readouterr().err


@pytest.mark.parametrize('bad', ['http://gitlab.com', 'https://name:secret@gitlab.com', 'https://gitlab.com/path',
    'https://gitlab.com?token=x', 'https://gitlab.com/#fragment', 'https://gitlab.com\\evil', 'https://git lab.com'])
def test_host_rejects_credential_or_url_confusion(bad):
    with pytest.raises(ValueError):
        host(bad)


@pytest.mark.parametrize('change', [dict(ref='main'), dict(file='../board.kicad_pcb'), dict(file='C:/board.kicad_pcb'),
    dict(file='//server/board.kicad_pcb'), dict(file='board.txt'), dict(repository='a/../b'), dict(provider='other'),
    dict(area=dict(x=0, y=0, width=-1, height=2)), dict(position=dict(x=float('nan'), y=2))])
def test_anchor_rejects_bad_scope_or_geometry(change):
    with pytest.raises(ValueError):
        anchor(dict(BASE, **change))


def test_kiview_marker_roundtrip_and_foreign_scope_rejection():
    value = note('Check C1 — µF', dict(BASE, uuid='123', reference='C1', position=dict(x=1, y=2)))
    body = markdown(value)
    assert read_markers(body, BASE)[0]['anchor']['reference'] == 'C1'
    assert read_markers(body, dict(BASE, ref='b' * 40)) == []
    assert read_markers('<!-- kicad-review:v1 broken -->', BASE) == []
    assert 'root' not in read_markers(body, BASE)[0]['anchor']
    with pytest.raises(ValueError):
        note('Injected <!-- kicad-review:v1 abc -->', BASE)


def test_same_repository_different_gitlab_origin_never_matches():
    a = dict(BASE, provider='gitlab', host='https://gitlab.example.org')
    b = dict(a, host='https://other.example.org')
    assert read_markers(markdown(note('Review', a)), b) == []


def test_native_git_saved_context_is_read_only(tmp_path):
    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True).stdout.strip()
    git('init', '--quiet')
    file = tmp_path / 'board.kicad_pcb'
    content = b'(kicad_pcb (version 20240108))\n'
    file.write_bytes(content)
    git('add', 'board.kicad_pcb')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    target = dict(BASE, ref=git('rev-parse', 'HEAD'))
    path, digest = saved_context(tmp_path, target)
    assert path == file and len(digest) == 64
    assert file.read_bytes() == content
    # A normal Windows checkout can materialize Git's LF blob as CRLF.
    file.write_bytes(content.replace(b'\n', b'\r\n'))
    crlf_path, crlf_digest = saved_context(tmp_path, target)
    assert crlf_path == file and crlf_digest != digest
    file.write_bytes(content + b'changed')
    with pytest.raises(ValueError, match='differs'):
        saved_context(tmp_path, target)


def transport_fixture(provider='github', pages=None):
    calls = []
    def transport(method, url, headers, data):
        calls.append((method, url, headers, data))
        if method == 'POST':
            return 201, {}, dict(id=91, body=json.loads(data)['body'])
        if '/comments?' in url or '/notes?' in url:
            page = int(url.split('page=')[-1])
            return 200, {}, (pages or {}).get(page, [])
        return 200, {}, dict(id=1, body='Conversation', author={'username': 'alice'}, user={'login': 'alice'})
    settings = dict(BASE, number=7, kind='issue')
    if provider == 'gitlab':
        settings.update(provider='gitlab', host='https://gitlab.example.org', repository='group/sub/board')
    return Provider(settings, transport=transport, tokens=lambda *_: 'secret-not-logged'), calls


@pytest.mark.parametrize('provider', ['github', 'gitlab'])
def test_provider_endpoint_pagination_and_publication(provider):
    rows = [dict(id=i + 2, body='x', user=dict(login='b')) for i in range(100)]
    client, calls = transport_fixture(provider, {1: rows, 2: [dict(id=500, body='Last', user=dict(login='c'))]})
    snapshot = client.snapshot()
    assert len(snapshot) == 102 and snapshot[-1]['body'] == 'Last'
    assert all('https://' in c[1] for c in calls)
    if provider == 'gitlab':
        assert 'group%2Fsub%2Fboard' in calls[0][1]
        assert '/-/issues/7#note_500' in snapshot[-1]['url']
    else:
        assert calls[0][2]['Authorization'] == 'Bearer secret-not-logged'
    assert client.publish('Hello') == '91'
    assert len([c for c in calls if c[0] == 'POST']) == 1


def test_no_redirect_even_same_origin():
    with pytest.raises(ValueError, match='redirected'):
        NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example.org')


def test_failed_page_is_never_partial_snapshot():
    client, calls = transport_fixture(pages={1: [dict(id=i + 2, body='x') for i in range(100)]})
    first = client.transport
    def fail(method, url, headers, data):
        if url.endswith('page=2'):
            raise RuntimeError('offline')
        return first(method, url, headers, data)
    client.transport = fail
    with pytest.raises(RuntimeError):
        client.snapshot()


def test_write_ambiguity_never_retries_or_exposes_tokens():
    client, calls = transport_fixture()
    def fail(*args):
        raise RuntimeError('secret-not-logged')
    client.transport = fail
    with pytest.raises(RuntimeError, match='not confirmed') as error:
        client.publish('Hello')
    assert 'secret-not-logged' not in str(error.value)


def test_gitlab_uses_cli_not_nonexistent_auth_token_command():
    client = Provider(dict(BASE, provider='gitlab', host='https://gitlab.example.org', number=1))
    with patch('review_comments_plugin.providers.subprocess.run', return_value=SimpleNamespace(stdout=b'[]')) as run:
        client._call('GET', '/projects/group%2Frepo/boards')
    args = run.call_args.args[0]
    assert args[:2] == ['glab', 'api']
    assert '--hostname' in args and 'gitlab.example.org' in args


@pytest.fixture
def session(tmp_path):
    file = tmp_path / 'board.kicad_pcb'
    file.write_bytes(b'fixture')
    import hashlib
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    client, _ = transport_fixture()
    with patch('review_comments_plugin.session.saved_context', return_value=(file, digest)):
        return ReviewSession(dict(BASE, root=str(tmp_path), number=7), provider=client, cache_dir=tmp_path / 'cache')


def test_cache_is_never_navigation_or_publication_authority(session):
    session.refresh()
    session.cached()
    assert session.status == 'cached / unverified'
    with pytest.raises(ValueError, match='cached'):
        session.publish('Hello', BASE)
    with pytest.raises(ValueError, match='cache'):
        session.locate('1', selector=lambda *a, **kw: None)


def test_source_change_rejects_publication_without_call(session):
    session.refresh()
    session.path.write_bytes(b'changed')
    with patch.object(session.provider, 'publish') as publish:
        with pytest.raises(ValueError, match='changed'):
            session.publish('Hello', BASE)
    publish.assert_not_called()


def test_remote_anchor_selection_and_bytes_unchanged(session):
    body = markdown(note('Review object', dict(BASE, uuid='abc')))
    with patch.object(session.provider, 'snapshot', return_value=[dict(id='5', body=body, author='b')]):
        before = session.path.read_bytes()
        session.refresh()
        with patch('review_comments_plugin.session.unchanged') as check:
            def selector(path, ids, **kwargs):
                assert ids == ['abc'] and kwargs['expected_sha256'] == session.digest
                return dict(count=1, focus='requested')
            assert session.locate('5', selector=selector)['count'] == 1
        assert check.call_count == 4
        assert session.path.read_bytes() == before


def test_deletion_replaces_complete_cache_and_removes_anchor(session):
    body = markdown(note('Review', dict(BASE, uuid='abc')))
    with patch.object(session.provider, 'snapshot', return_value=[dict(id='5', body=body, author='a')]):
        session.refresh()
    with patch.object(session.provider, 'snapshot', return_value=[]):
        session.refresh()
    assert session.rows == []
    assert json.loads(session.cache_path.read_text())['rows'] == []
    with pytest.raises(ValueError, match='no unique'):
        session.locate('5')


def test_foreign_markers_unlocated_and_plain_comments_visible(session):
    body = markdown(note('Foreign', dict(BASE, file='other.kicad_pcb', uuid='abc')))
    with patch.object(session.provider, 'snapshot', return_value=[dict(id='5', body=body, author='a')]):
        session.refresh()
    assert len(session.rows) == 1 and session.rows[0]['anchors'] == []


def test_failed_refresh_keeps_cache_but_marks_stale_and_backs_off(session):
    session.refresh()
    before = session.cache_path.read_bytes()
    with patch.object(session.provider, 'snapshot', side_effect=RuntimeError('offline')):
        with pytest.raises(RuntimeError):
            session.refresh()
    assert session.status == 'offline / stale' and session.interval_seconds == 16
    assert session.cache_path.read_bytes() == before


def test_reply_deleted_during_preflight_is_rejected(session):
    session.rows = [dict(id='5')]
    session.status = 'synced'
    with patch.object(session.provider, 'snapshot', return_value=[]), patch.object(session.provider, 'publish') as publish:
        with pytest.raises(ValueError, match='removed remotely'):
            session.publish('Reply', BASE, reply_to='5')
        publish.assert_not_called()


def test_gitlab_upload_and_github_browser_fallback():
    github, _ = transport_fixture()
    with pytest.raises(ValueError, match='browser editor'):
        github.upload_png(b'anything')
    gitlab, _ = transport_fixture('gitlab')
    with pytest.raises(ValueError, match='PNG'):
        gitlab.upload_png(b'not a png')


def test_atomic_cache_staging_is_removed(tmp_path):
    target = tmp_path / 'cache.json'
    atomic_json(target, dict(rows=[]))
    atomic_json(target, dict(rows=[1]))
    assert json.loads(target.read_text()) == dict(rows=[1])
    assert sorted(p.name for p in tmp_path.iterdir()) == ['cache.json']


@pytest.mark.parametrize('raw', ['broken json', '{"scope":null,"rows":[]}', '[]'])
def test_corrupt_cache_never_prevents_remote_recovery(session, raw):
    session.cache_path.parent.mkdir(parents=True, exist_ok=True)
    session.cache_path.write_text(raw)
    assert session.cached() == []
    session.refresh()
    assert session.status == 'synced' and session.rows


def test_unwritable_cache_does_not_make_provider_unavailable(session):
    with patch('review_comments_plugin.session.atomic_json', side_effect=OSError('disk full')):
        session.refresh()
    assert session.status == 'synced' and session.rows
    assert session.cache_warning


def test_pending_draft_is_distinct_from_remote_cache(session):
    session.draft('unsent', dict(BASE, uuid='one'))
    assert session.draft()['text'] == 'unsent'
    session.refresh()
    assert session.draft()['text'] == 'unsent'
    assert all('unsent' not in r['body'] for r in session.rows)


@pytest.mark.parametrize('bad', [[], {'anchor': []}, {'anchor': {'repository': None}}, {'anchor': None}])
def test_malformed_remote_marker_does_not_poison_refresh(bad):
    import base64
    data = base64.urlsafe_b64encode(json.dumps(bad).encode()).decode().rstrip('=')
    assert read_markers('<!-- kicad-review:v1 ' + data + ' -->', BASE) == []


def test_invalid_cache_timestamp_cannot_block_fresh_provider(session):
    session.refresh()
    value = json.loads(session.cache_path.read_text())
    value['syncedAt'] = {}
    session.cache_path.write_text(json.dumps(value))
    assert session.cached() == []
    session.refresh()
    assert session.status == 'synced'


def test_confirmed_gitlab_upload_receipt_is_carried_by_shared_marker():
    import struct, re
    client, _ = transport_fixture('gitlab')
    def transport(method, url, headers, data):
        if method == 'GET':
            return 200, {}, dict(id=123)
        name = re.search(b'filename="([^"]+)"', data).group(1).decode()
        return 201, {}, dict(url='/uploads/' + 'a' * 32 + '/' + name)
    client.transport = transport
    # Header fixture tests transport receipt/dimensions, not PNG decoder correctness.
    data = b'\x89PNG\r\n\x1a\n' + b'12345678' + struct.pack('>II', 30, 20)
    receipt = client.upload_png(data)
    value = note('Review screenshot', client.scope, attachments=[receipt['attachment']])
    parsed = read_markers(markdown(value), client.scope)[0]
    assert parsed['attachments'][0]['projectId'] == 123
    assert parsed['attachments'][0]['width'] == 30
    foreign = dict(receipt['attachment'], host='https://other.example.org')
    with pytest.raises(ValueError):
        note('Review screenshot', client.scope, attachments=[foreign])


@pytest.mark.parametrize('reply_to', [[], {}, 10])
def test_malformed_reply_metadata_never_blocks_sync(session, reply_to):
    value = note('Review', BASE)
    value['replyTo'] = reply_to
    body = markdown(value)
    with patch.object(session.provider, 'snapshot', return_value=[dict(id='5', body=body, author='a')]):
        session.refresh()
    assert session.status == 'synced' and not session.rows[0].get('parentId')


def test_discussion_session_preserves_native_thread_and_opaque_ids(session):
    session.provider.kind = 'discussion'
    forged = note('Review', BASE)
    forged['replyTo'] = 'DC_other'
    rows = [dict(id='DC_parent', body=markdown(forged), author='alice'),
            dict(id='DC_child', body='Native reply', author='bob', parentId='DC_parent'),
            dict(id='DC_other', body='Another comment', author='alice')]
    with patch.object(session.provider, 'snapshot', return_value=rows), patch.object(session.provider, 'publish', return_value='DC_new') as publish:
        session.refresh()
        assert 'parentId' not in session.rows[0]
        assert session.rows[1]['parentId'] == 'DC_parent'
        session.cached()
        assert session.status == 'cached / unverified' and len(session.rows) == 3
        session.refresh()
        assert session.publish('Reply', BASE, reply_to='DC_child') == 'DC_new'
        assert publish.call_args.kwargs['reply_to'] == 'DC_child'
        parsed = read_markers(publish.call_args.args[0], BASE)[0]
        assert parsed['threadType'] == 'discussion'


def test_discussion_factory_never_uses_gitlab_host_field(tmp_path):
    path = tmp_path / 'board.kicad_pcb'
    path.write_bytes(b'fixture')
    provider = type('Discussion', (), {'kind': 'discussion', 'number': 7})()
    with patch('review_comments_plugin.session.saved_context', return_value=(path, 'a' * 64)), patch('review_comments_plugin.session.DiscussionProvider', return_value=provider) as factory:
        session = ReviewSession(dict(BASE, root=str(tmp_path), number=7, kind='discussion', host='https://gitlab.com'), cache_dir=tmp_path)
    assert session.provider is provider and 'host' not in factory.call_args.args[0]
