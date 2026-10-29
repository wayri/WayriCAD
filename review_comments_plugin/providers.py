"""Bounded GitHub/GitLab comment APIs. Credentials stay in the provider CLI store."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import struct
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from .model import host, scope, run

MAX_BODY = 8 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Provider redirected the request. Check repository/host settings; credentials were not forwarded.')


def request(method, url, headers, data=None):
    """Send one HTTPS request, with no cross-host redirects or unbounded response reads."""
    if urlsplit(url).scheme != 'https':
        raise ValueError('Provider APIs require HTTPS.')
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(req, timeout=20) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise ValueError('Provider response exceeds 8 MiB; narrow this review thread.')
            return response.status, dict(response.headers), json.loads(body) if body else None
    except HTTPError as exc:
        if exc.code == 304:
            return 304, dict(exc.headers), None
        if exc.code in (401, 403):
            raise RuntimeError('Provider denied access or rate limited this account. Check browser login, permissions and rate limits in Settings.') from None
        raise RuntimeError('Provider request failed (HTTP ' + str(exc.code) + '). No automatic write retry was attempted.') from None
    except (URLError, TimeoutError):
        raise RuntimeError('Provider unavailable. Cached comments are not a current remote snapshot. Refresh before retrying a publication.') from None


def credential(provider, origin):
    """Read a token through gh/glab; never return command output in diagnostics."""
    if provider != 'github':
        raise ValueError('GitLab requests use glab api directly, including its OS keyring.')
    command = ['gh', 'auth', 'token', '--hostname', 'github.com']
    try:
        token = run(command)
        if not token or '\n' in token or '\r' in token:
            raise ValueError('Missing token')
        return token
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError('Install and sign in with ' + ('GitHub CLI (gh)' if provider == 'github' else 'GitLab CLI (glab)') + ' in Settings.') from None


def login_command(provider, origin):
    """Return browser login arguments; callers run this only on explicit user action."""
    if provider == 'github':
        return ['gh', 'auth', 'login', '--hostname', 'github.com', '--web', '--git-protocol', 'https']
    hostname = urlsplit(host(origin)).netloc
    return ['glab', 'auth', 'login', '--hostname', hostname, '--web', '--git-protocol', 'https',
            '--api-host', hostname, '--api-protocol', 'https', '--container-registry-domains', hostname]


def _cli_failure(error):
    """Classify captured diagnostics without returning their potentially private text."""
    if isinstance(error, FileNotFoundError):
        return 'cli-unavailable'
    if isinstance(error, subprocess.TimeoutExpired):
        return 'timeout'
    if isinstance(error, UnicodeError):
        return 'response-encoding'
    if isinstance(error, subprocess.CalledProcessError):
        value = error.stderr or b''
        if isinstance(value, bytes):
            value = value.decode('utf-8', errors='replace')
        lowered = value.lower()
        if re.search(r'\b401\b', lowered):
            return 'http-401'
        if re.search(r'\b403\b', lowered):
            return 'http-403'
        if any(term in lowered for term in ('no such host', 'lookup ', 'connection refused', 'tls handshake', 'certificate', 'network is unreachable')):
            return 'network-or-tls'
        if any(term in lowered for term in ('to get started with github cli, please run:  gh auth login',
                                            'no accounts configured', 'you are not logged into any gitlab hosts',
                                            'please authenticate using `glab auth login`')):
            return 'no-session'
        return 'cli-rejected'
    return 'process-error'


def login_status(provider, origin):
    """Return a secret-free receipt for /user, distinguishing auth from parsing/launch errors."""
    if provider not in ('github', 'gitlab'):
        raise ValueError('Choose GitHub or GitLab.')
    hostname = 'github.com' if provider == 'github' else urlsplit(host(origin)).netloc
    command = ['gh' if provider == 'github' else 'glab', 'api', 'user', '--hostname', hostname]
    try:
        data = run(command, timeout=25)
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        return dict(authenticated=False, category=_cli_failure(error))
    if len(data) > 1024 * 1024:
        return dict(authenticated=False, category='oversized-response')
    try:
        value = json.loads(data.lstrip('\ufeff'))
    except ValueError:
        return dict(authenticated=False, category='malformed-json',
                    ansi_present='\x1b[' in data, bom_present=data.startswith('\ufeff'))
    if not isinstance(value, dict) or type(value.get('id')) is not int:
        return dict(authenticated=False, category='invalid-account-response')
    return dict(authenticated=True, category='verified')


def verify_login(provider, origin):
    """Check the stored CLI session; no credentials or account data leave the CLI boundary."""
    receipt = login_status(provider, origin)
    if not receipt['authenticated']:
        if receipt['category'] == 'no-session':
            raise RuntimeError('No CLI session is configured. Choose Connect with browser in Review settings to sign in.')
        if receipt['category'] == 'http-401':
            raise RuntimeError('CLI session check failed (http-401): the provider rejected the existing CLI credentials. Browser or phone sign-in does not establish this CLI session. No new sign-in or credential transfer was attempted.')
        if receipt['category'] == 'http-403':
            raise RuntimeError('CLI session check failed (http-403): the provider denied this request. Check account access or rate limits; no new sign-in was attempted.')
        raise RuntimeError('CLI session check failed (' + receipt['category'] + '). This is not proof that your existing login failed. If it works in your terminal, compare that process context; do not sign in again or copy tokens.')
    return True


class Provider:
    """One issue/PR (GitHub), issue/MR (GitLab); pages are complete or rejected."""

    def __init__(self, settings, *, transport=request, tokens=credential):
        self.scope = scope(settings)
        self.provider = self.scope.get('provider', 'github')
        self.origin = self.scope.get('host', 'https://github.com')
        self.number = settings.get('number')
        self.kind = settings.get('kind', 'issue')
        if type(self.number) is not int or self.number < 1 or self.kind not in ('issue', 'pull', 'merge_request'):
            raise ValueError('Choose a positive issue/PR/MR number.')
        if (self.provider == 'github' and self.kind == 'merge_request') or (self.provider == 'gitlab' and self.kind == 'pull'):
            raise ValueError('Conversation type does not belong to this provider.')
        self.transport, self.tokens = transport, tokens
        self.repository = self.scope['repository']
        if self.provider == 'github':
            self.api = 'https://api.github.com'
            self.thread = '/repos/' + self.repository + '/issues/' + str(self.number)
            self.comments = self.thread + '/comments'
        else:
            self.api = self.origin + '/api/v4'
            noun = 'merge_requests' if self.kind == 'merge_request' else 'issues'
            self.project = '/projects/' + quote(self.repository, safe='')
            self.thread = self.project + '/' + noun + '/' + str(self.number)
            self.comments = self.thread + '/notes'

    @property
    def web_url(self):
        if self.provider == 'github':
            return self.origin + '/' + self.repository + ('/pull/' if self.kind == 'pull' else '/issues/') + str(self.number)
        return self.origin + '/' + self.repository + '/-/' + ('merge_requests/' if self.kind == 'merge_request' else 'issues/') + str(self.number)

    @property
    def board_url(self):
        return self.origin + '/' + self.repository + ('/projects' if self.provider == 'github' else '/-/boards')

    def _call(self, method, path, payload=None, *, binary=None, content_type=None, etag=None):
        if not path.startswith('/') or path.startswith('//') or '\\' in path:
            raise ValueError('Invalid provider API path.')
        if self.provider == 'gitlab' and self.transport is request and self.tokens is credential:
            # glab exposes no auth-token command. Its API command resolves OAuth/keyring
            # credentials itself, without exporting a token into our process or settings.
            args = ['glab', 'api', '--hostname', urlsplit(self.origin).netloc, '--method', method, path]
            data = binary
            if payload is not None:
                data, content_type = json.dumps(payload).encode(), 'application/json'
            if content_type:
                args.extend(['--header', 'Content-Type: ' + content_type])
            if data is not None:
                args.extend(['--input', '-'])
            try:
                options = {'input': data} if data is not None else {'stdin': subprocess.DEVNULL}
                response = subprocess.run(args, **options, capture_output=True, timeout=20, check=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if len(response.stdout) > MAX_BODY:
                    raise ValueError('GitLab response exceeds 8 MiB.')
                return 200, {}, json.loads(response.stdout)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                raise RuntimeError('GitLab request failed. Check glab browser login, permissions and connectivity in Settings.') from None
        token = self.tokens(self.provider, self.origin)
        headers = {'Accept': 'application/vnd.github+json' if self.provider == 'github' else 'application/json',
                   'User-Agent': 'WayriCAD-Review/0.1'}
        headers['Authorization' if self.provider == 'github' else 'PRIVATE-TOKEN'] = ('Bearer ' + token if self.provider == 'github' else token)
        if etag:
            headers['If-None-Match'] = etag
        data = binary
        if payload is not None:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        if content_type:
            headers['Content-Type'] = content_type
        return self.transport(method, self.api + path, headers, data)

    def _pages(self, path):
        result = []
        for page in range(1, 51):
            separator = '&' if '?' in path else '?'
            _, _, rows = self._call('GET', path + separator + 'per_page=100&page=' + str(page))
            if not isinstance(rows, list):
                raise ValueError('Provider returned an invalid comment collection.')
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise ValueError('Review exceeds 5,000 comments; choose a smaller conversation. Cache was not replaced.')

    def snapshot(self):
        """Fetch root and comments together; never hide a failed page behind old data."""
        _, _, root = self._call('GET', self.thread)
        if not isinstance(root, dict):
            raise ValueError('Invalid provider conversation.')
        rows = [dict(root, _root=True)] + self._pages(self.comments + ('?order_by=created_at&sort=asc' if self.provider == 'gitlab' else ''))
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Provider returned an invalid comment record.')
            if row.get('system'):
                continue
            author = row.get('user', row.get('author', {})) or {}
            if not isinstance(author, dict):
                author = {}
            login = author.get('login', author.get('username', 'unknown'))
            if not isinstance(login, str) or len(login) > 200:
                login = 'unknown'
            body = row.get('body', row.get('description', '')) or ''
            if not isinstance(body, str):
                raise ValueError('Provider returned invalid comment text.')
            identifier = str(row.get('id', ''))
            if not identifier.isdigit():
                raise ValueError('Provider returned an invalid comment identity.')
            normalized.append(dict(id=identifier, root=bool(row.get('_root')), body=body,
                author=login,
                updatedAt=row.get('updated_at', '') if isinstance(row.get('updated_at', ''), str) else '',
                url=self.web_url + ('' if row.get('_root') else ('#issuecomment-' if self.provider == 'github' else '#note_') + identifier)))
        return normalized

    def publish(self, body):
        """One explicit publication. A timeout is ambiguous: refresh, do not auto-retry."""
        if not isinstance(body, str) or not body.strip() or len(body.encode()) > 64000:
            raise ValueError('Comment is empty or exceeds 64 KiB.')
        try:
            _, _, row = self._call('POST', self.comments, {'body': body})
        except Exception:
            raise RuntimeError('Publication was not confirmed. Refresh the provider thread and check for your comment before retrying; the draft has been retained.') from None
        if not isinstance(row, dict) or not str(row.get('id', '')).isdigit() or row.get('body') != body:
            raise RuntimeError('Provider did not confirm this exact comment. Refresh before retrying.')
        return str(row['id'])

    def upload_png(self, data):
        """GitLab has a public upload API; GitHub screenshots use its browser editor."""
        if self.provider != 'gitlab':
            raise ValueError('Paste/upload the screenshot in GitHub’s browser editor, then refresh. No undocumented GitHub upload endpoint is used.')
        if not isinstance(data, bytes) or not data.startswith(b'\x89PNG\r\n\x1a\n') or not 24 <= len(data) <= 4 * 1024 * 1024:
            raise ValueError('Choose a PNG screenshot no larger than 4 MiB.')
        width, height = struct.unpack('>II', data[16:24])
        if not 1 <= width <= 1024 or not 1 <= height <= 1024:
            raise ValueError('Normalize screenshot dimensions to at most 1024 pixels before upload.')
        _, _, project = self._call('GET', self.project)
        project_id = project.get('id') if isinstance(project, dict) else None
        if type(project_id) is not int or project_id <= 0:
            raise ValueError('GitLab did not confirm the target project identity.')
        boundary = 'wayricad' + uuid.uuid4().hex
        name = 'kicad-review-' + uuid.uuid4().hex[:20] + '.png'
        payload = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + name + '"\r\nContent-Type: image/png\r\n\r\n').encode() + data + ('\r\n--' + boundary + '--\r\n').encode()
        _, _, result = self._call('POST', self.project + '/uploads', binary=payload,
                                 content_type='multipart/form-data; boundary=' + boundary)
        url = result.get('url', '') if isinstance(result, dict) else ''
        if not re.fullmatch(r'/uploads/[a-f0-9]{32}/' + re.escape(name), url):
            raise ValueError('GitLab returned an unexpected upload location. Open the provider thread to inspect it.')
        url = self.origin + '/' + self.repository + url
        return dict(markdown='![' + name + '](' + url + ')',
                    attachment=dict(provider='gitlab', host=self.origin, repository=self.repository,
                                    projectId=project_id, mime='image/png', url=url, width=width, height=height))

    def boards(self):
        """GitLab board names; GitHub Projects opens the authoritative provider UI."""
        if self.provider == 'github':
            return {'url': self.board_url, 'boards': [], 'mode': 'provider-browser'}
        rows = self._pages(self.project + '/boards')
        return {'url': self.board_url, 'boards': [{'id': r['id'], 'name': r['name']} for r in rows], 'mode': 'provider-api'}
