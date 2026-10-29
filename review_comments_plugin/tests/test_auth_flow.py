"""Repair only a rejected CLI host after an explicit Connect action."""
import subprocess
from unittest.mock import patch

import pytest

from review_comments_plugin.auth_flow import connect_plan, clear_rejected_gitlab_login, TOKEN_OVERRIDES

HOST = 'https://gitlab.example.org'


@pytest.fixture(autouse=True)
def no_inherited_credentials(monkeypatch):
    for key in TOKEN_OVERRIDES:
        monkeypatch.delenv(key, raising=False)


def test_valid_session_needs_neither_repair_nor_browser():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=True)), \
            patch('review_comments_plugin.auth_flow.run') as run:
        assert connect_plan('gitlab', HOST) == dict(action='connected')
    run.assert_not_called()


@pytest.mark.parametrize('category', ['http-403', 'network-or-tls', 'timeout', 'malformed-json', 'cli-unavailable'])
def test_non401_never_reads_or_changes_credential_state(category):
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category=category)), \
            patch('review_comments_plugin.auth_flow.run') as run:
        assert connect_plan('gitlab', HOST) == dict(action='blocked', category=category)
    run.assert_not_called()


def test_first_connection_with_no_stored_token_can_open_browser_without_logout():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run', side_effect=subprocess.CalledProcessError(
                1, ['glab'], stderr='Not logged in; no credentials in keyring.')) as run:
        assert connect_plan('gitlab', HOST) == dict(action='sign-in')
    assert run.call_args.args[0] == ['glab', 'auth', 'status', '--hostname', 'gitlab.example.org']


def test_confirmed_keyring_401_selects_host_limited_repair():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run', side_effect=subprocess.CalledProcessError(
                1, ['glab'], stderr='HTTP 401: rejected token from Windows keyring.')):
        assert connect_plan('gitlab', HOST) == dict(action='repair-rejected')


def test_unknown_status_does_not_authorize_removal():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run', return_value='Unrecognized CLI status'):
        assert connect_plan('gitlab', HOST)['action'] == 'blocked'


def test_rejected_environment_token_does_not_clear_stored_session(monkeypatch):
    monkeypatch.setenv('GITLAB_TOKEN', 'example-only-not-a-credential')
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run') as run:
        assert connect_plan('gitlab', HOST)['category'] == 'inherited-credential-rejected'
        with pytest.raises(RuntimeError, match='outside Review'):
            clear_rejected_gitlab_login(HOST)
    run.assert_not_called()


def test_repair_rechecks_and_only_logs_out_exact_host():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run', return_value='') as run:
        assert clear_rejected_gitlab_login(HOST) is True
    assert run.call_args.args[0] == ['glab', 'auth', 'logout', '--hostname', 'gitlab.example.org']


def test_cancel_before_mutation_and_concurrent_valid_login_are_preserved():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run') as run:
        with pytest.raises(RuntimeError, match='cancelled'):
            clear_rejected_gitlab_login(HOST, cancelled=lambda: True)
    run.assert_not_called()
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=True)), \
            patch('review_comments_plugin.auth_flow.run') as run:
        assert clear_rejected_gitlab_login(HOST) is False
    run.assert_not_called()


def test_github_never_uses_gitlab_logout():
    with patch('review_comments_plugin.auth_flow.login_status', return_value=dict(authenticated=False, category='http-401')), \
            patch('review_comments_plugin.auth_flow.run') as run:
        assert connect_plan('github', 'https://github.com') == dict(action='sign-in')
    run.assert_not_called()


@pytest.mark.parametrize('provider,diagnostic', [
    ('github', 'To get started with GitHub CLI, please run:  gh auth login'),
    ('gitlab', 'No accounts configured. Please authenticate using `glab auth login`.'),
    ('gitlab', 'You are not logged into any GitLab hosts.'),
])
def test_missing_cli_session_opens_sign_in_without_credential_mutation(provider, diagnostic):
    with patch('review_comments_plugin.providers.run', side_effect=subprocess.CalledProcessError(
            1, [provider], stderr=diagnostic)), patch('review_comments_plugin.auth_flow.run') as run:
        assert connect_plan(provider, HOST) == dict(action='sign-in')
    run.assert_not_called()
