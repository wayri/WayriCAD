"""GitHub transport boundary. A future GitLab provider can use the same renderer."""
import hashlib
import hmac
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .git import VizError, safe_path

MAX_ARCHIVE = 50 * 1024 * 1024
MAX_EXPANDED = 250 * 1024 * 1024


def repository_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise VizError('Repository must be owner/name on github.com.')
    if any(part in ('.', '..') for part in value.split('/')):
        raise VizError('Invalid repository name.')
    return value


def api(path, token=None, payload=None, method=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'WayriCAD-Visual-Diff',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request('https://api.github.com' + path, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise VizError('GitHub response exceeds limit.')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise VizError(f'GitHub API returned {exc.code}. Check repository/ref and rate limits.') from exc


def public_commit(repo, ref):
    repository_name(repo)
    if not isinstance(ref, str) or not ref or len(ref) > 250:
        raise VizError('A valid Git ref is required.')
    # Deliberately unauthenticated: this boundary cannot expose private repositories.
    info = api('/repos/' + repo)
    if info.get('private', True):
        raise VizError('This preview server currently supports public repositories only.')
    return api('/repos/' + repo + '/commits/' + urllib.parse.quote(ref, safe=''))['sha']


def extract_archive(raw, destination):
    """Reject archive traversal, symlinks, decompression bombs and path collisions."""
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 20000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise VizError('Repository archive exceeds extraction limits.')
        seen = set()
        prefix = None
        for member in members:
            parts = member.filename.split('/', 1)
            if len(parts) != 2:
                raise VizError('Invalid GitHub archive structure.')
            if prefix is None:
                prefix = parts[0]
            if parts[0] != prefix:
                raise VizError('Archive has multiple roots.')
            if member.is_dir():
                continue
            name = parts[1]
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise VizError(f'Archive symlink is unsupported: {name}')
            target = safe_path(destination, name)
            key = str(target).casefold()
            if key in seen:
                raise VizError(f'Colliding archive path: {name}')
            seen.add(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            blob = archive.read(member)
            if blob.startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise VizError('Git LFS assets are not supported in this preview.')
            target.write_bytes(blob)


def download_snapshot(repo, sha, destination):
    repository_name(repo)
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise VizError('A resolved commit SHA is required.')
    request = urllib.request.Request(f'https://codeload.github.com/{repo}/zip/{sha}',
                                     headers={'User-Agent': 'WayriCAD-Visual-Diff'})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise VizError('Repository download exceeds 50 MiB.')
    extract_archive(raw, destination)


def verify_webhook(secret, body, signature):
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(secret and signature and hmac.compare_digest(expected, signature))


def installation_token(app_id, private_key, installation_id):
    """Only the server sees App credentials; optional dependency for deployed Apps."""
    import base64
    import time
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:
        raise VizError('Install the github extra to enable GitHub App authentication.') from exc
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=')
    now = int(time.time())
    parts = [encode(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()),
             encode(json.dumps({'iat': now - 60, 'exp': now + 540, 'iss': str(app_id)}).encode())]
    signing = b'.'.join(parts)
    key = serialization.load_pem_private_key(Path(private_key).read_bytes(), password=None)
    token = (signing + b'.' + encode(key.sign(signing, padding.PKCS1v15(), hashes.SHA256()))).decode()
    return api(f'/app/installations/{int(installation_id)}/access_tokens', token, {})['token']
