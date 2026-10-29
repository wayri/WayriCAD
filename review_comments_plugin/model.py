"""Portable KiView v1 anchors. Neither annotations nor caches edit a design file."""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import urlsplit
import uuid
from datetime import datetime, timezone

MARKER = re.compile(r'<!-- kicad-review:v1 ([A-Za-z0-9_-]{1,32000}) -->')


def run(args, *, cwd=None, timeout=15):
    """Run fixed argument arrays without a shell, keeping helpers hidden on Windows."""
    return subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8',
                          timeout=timeout, check=True,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()


def host(value):
    """Accept a configured HTTPS origin only, never credentials, paths or query data."""
    if not isinstance(value, str):
        raise ValueError('Invalid provider origin.')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or re.search(r'[\s\\\x00-\x1f]', value)):
        raise ValueError('Use an HTTPS server origin, such as https://gitlab.com.')
    return 'https://' + parsed.netloc.lower()


def scope(value):
    """Validate provider, project, immutable revision and repository-relative design path."""
    if not isinstance(value, dict):
        raise ValueError('Invalid review scope.')
    provider = value.get('provider', 'github')
    if provider not in ('github', 'gitlab'):
        raise ValueError('Choose GitHub or GitLab.')
    repository = value.get('repository', '')
    if not isinstance(repository, str):
        raise ValueError('Invalid repository.')
    parts = repository.split('/')
    if (len(parts) < 2 or (provider == 'github' and len(parts) != 2)
            or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', p) or p in ('.', '..') for p in parts)):
        raise ValueError('Use owner/repository or group/project, including GitLab subgroups.')
    revision = value.get('ref', '')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-fA-F0-9]{40}', revision):
        raise ValueError('A full immutable 40-character commit ID is required.')
    file = value.get('file', '')
    if (not isinstance(file, str) or len(file) > 500 or '\\' in file or ':' in file
            or any(ord(c) < 32 for c in file) or file.startswith('/')
            or any(p in ('', '.', '..') for p in file.split('/'))
            or PurePosixPath(file).suffix.lower() not in ('.kicad_pcb', '.kicad_sch')):
        raise ValueError('Choose a repository-relative KiCad board or schematic path.')
    result = dict(repository=repository, ref=revision.lower(), file=file)
    if provider == 'gitlab':
        result.update(provider=provider, host=host(value.get('host', 'https://gitlab.com')))
    return result


def anchor(value):
    result = scope(value)
    for key, limit in (('uuid', 200), ('objectId', 200), ('reference', 100),
                       ('netName', 500), ('kind', 80), ('variant', 100)):
        if key in value:
            text = value[key]
            if not isinstance(text, str) or not text.strip() or len(text) > limit or any(ord(c) < 32 for c in text):
                raise ValueError('Invalid anchor ' + key)
            result[key] = text.strip()
    for key, fields in (('position', ('x', 'y')), ('area', ('x', 'y', 'width', 'height'))):
        if key in value:
            box = value[key]
            if not isinstance(box, dict) or any(isinstance(box.get(f), bool) or not isinstance(box.get(f), (int, float))
                    or not math.isfinite(box[f]) or abs(box[f]) > 1e6 for f in fields):
                raise ValueError('Invalid anchor ' + key)
            if key == 'area' and (box['width'] <= 0 or box['height'] <= 0):
                raise ValueError('A region must have positive dimensions in mm.')
            result[key] = {f: box[f] for f in fields}
    return result


def attachment(value, target):
    """Validate confirmed GitLab image metadata against the shared KiView schema."""
    target = scope(target)
    if not isinstance(value, dict) or target.get('provider') != 'gitlab':
        raise ValueError('Native uploads require a GitLab attachment receipt.')
    if (value.get('provider') != 'gitlab' or value.get('host') != target['host']
            or value.get('repository') != target['repository'] or value.get('mime') != 'image/png'
            or type(value.get('projectId')) is not int or value['projectId'] <= 0
            or any(type(value.get(f)) is not int or not 1 <= value[f] <= 1024 for f in ('width', 'height'))):
        raise ValueError('Invalid screenshot attachment receipt.')
    prefix = target['host'] + '/' + target['repository'] + '/uploads/'
    url = value.get('url', '')
    if not isinstance(url, str) or not url.startswith(prefix) or not re.fullmatch(r'[a-f0-9]{32}/kicad-review-[a-f0-9]{20}\.png', url[len(prefix):]):
        raise ValueError('Screenshot URL belongs to another provider/project or is malformed.')
    return {key: value[key] for key in ('provider', 'host', 'repository', 'projectId', 'mime', 'url', 'width', 'height')}


def note(text, target, *, reply_to=None, attachments=()):
    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or '<!-- kicad-review:' in text:
        raise ValueError('Write between 1 and 4,000 characters.')
    now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    result = dict(id=str(uuid.uuid4()), text=text.strip(), createdAt=now, updatedAt=now,
                  severity='info', state='open', tags=[], mentions=[], remoteRefs=[], anchor=anchor(target))
    if reply_to:
        result['replyTo'] = str(reply_to)
    if attachments:
        if len(attachments) > 4:
            raise ValueError('At most four screenshot attachments are supported.')
        result['attachments'] = [attachment(value, target) for value in attachments]
    return result


def markdown(value):
    """Publish the same base64url JSON marker consumed by Pocket KiView."""
    target = anchor(value['anchor'])
    if not value.get('text') or len(value['text']) > 4000:
        raise ValueError('Invalid review text.')
    payload = dict(value, anchor=target)
    payload.pop('capture', None)
    data = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).decode().rstrip('=')
    if len(data) > 32000:
        raise ValueError('Review metadata exceeds the shared marker limit.')
    return value['text'] + '\n\n<!-- kicad-review:v1 ' + data + ' -->'


def read_markers(body, expected):
    """Read anchors only from provider text and only for this exact file/revision scope."""
    if not isinstance(body, str) or len(body.encode()) > 1024 * 1024:
        raise ValueError('Provider comment exceeds 1 MiB.')
    expected = scope(expected)
    result = []
    for match in list(MARKER.finditer(body))[:100]:
        try:
            data = json.loads(base64.b64decode(match[1] + '=' * (-len(match[1]) % 4), altchars=b'-_', validate=True))
            target = anchor(data['anchor'])
            if scope(target) == expected and isinstance(data.get('id'), str) and isinstance(data.get('text'), str):
                result.append(dict(data, anchor=target))
        except (ValueError, KeyError, TypeError, RecursionError):
            continue
    return result


def saved_context(root, target):
    """Match Git text apart from LF/CRLF checkout conversion; hash exact saved bytes."""
    target = scope(target)
    root = Path(root).resolve(strict=True)
    raw_path = root / target['file']
    path = raw_path.resolve(strict=True)
    if not path.is_relative_to(root) or any(p.is_symlink() for p in [raw_path, *raw_path.parents] if p != root and p.is_relative_to(root)):
        raise ValueError('Design path must remain inside the selected Git worktree.')
    data = path.read_bytes()
    try:
        expected = subprocess.run(['git', 'show', target['ref'] + ':' + target['file']], cwd=root,
                                  stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=True,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Git could not read the chosen design revision. Install Git and check the worktree, commit and repository-relative file path.') from None
    if data != expected and data.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n'):
        raise ValueError('Saved design differs from the selected commit. Commit or choose the matching revision first.')
    return path, hashlib.sha256(data).hexdigest()


def unchanged(path, digest):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise ValueError('Saved design changed. Reopen review settings for the new revision.')
