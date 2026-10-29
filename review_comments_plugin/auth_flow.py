"""Explicit CLI connection planning; never transfer credentials or auto-retry login."""
from __future__ import annotations

import os
import subprocess
from urllib.parse import urlsplit

from .model import host, run
from .providers import login_status

TOKEN_OVERRIDES = ('GITLAB_TOKEN', 'GITLAB_ACCESS_TOKEN', 'OAUTH_TOKEN', 'CI_JOB_TOKEN')


def connect_plan(provider, origin):
    """Inspect an existing session before the user's explicit Connect action."""
    receipt = login_status(provider, origin)
    if receipt['authenticated']:
        return dict(action='connected')
    if receipt['category'] == 'no-session':
        return dict(action='sign-in')
    if receipt['category'] != 'http-401':
        return dict(action='blocked', category=receipt['category'])
    if provider != 'gitlab':
        return dict(action='sign-in')
    if any(os.getenv(name) for name in TOKEN_OVERRIDES):
        return dict(action='blocked', category='inherited-credential-rejected')
    hostname = urlsplit(host(origin)).netloc
    try:
        diagnostic = run(['glab', 'auth', 'status', '--hostname', hostname], timeout=25)
    except subprocess.CalledProcessError as error:
        from .providers import _cli_failure
        if _cli_failure(error) == 'network-or-tls':
            return dict(action='blocked', category='network-or-tls')
        parts = [part.decode('utf-8', errors='replace') if isinstance(part, bytes) else part
                 for part in (error.stdout or '', error.stderr or '')]
        diagnostic = '\n'.join(parts)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return dict(action='blocked', category='credential-state-unavailable')
    lowered = diagnostic.lower()
    # Only explicit CLI status identifies a stored rejected session. Unknown
    # messages do not authorize credential removal.
    if any(value in lowered for value in ('not logged', 'no token', 'no credentials', 'no accounts')):
        return dict(action='sign-in')
    if 'keyring' in lowered or ('token' in lowered and 'config' in lowered):
        return dict(action='repair-rejected')
    return dict(action='blocked', category='credential-state-unconfirmed')


def clear_rejected_gitlab_login(origin, *, cancelled=None):
    """Replace only a confirmed rejected CLI host session after explicit user action."""
    if any(os.getenv(name) for name in TOKEN_OVERRIDES):
        raise RuntimeError('An inherited credential was rejected; its source must be corrected outside Review. Stored credentials were not changed.')
    current = login_status('gitlab', origin)
    if cancelled is not None and cancelled():
        raise RuntimeError('Connection cancelled; stored credentials were not changed.')
    if current['authenticated']:
        return False
    if current['category'] != 'http-401':
        raise RuntimeError('Connection state changed; stored credentials were not changed.')
    hostname = urlsplit(host(origin)).netloc
    try:
        run(['glab', 'auth', 'logout', '--hostname', hostname], timeout=25)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise RuntimeError('The rejected CLI connection could not be cleared. No automatic sign-in retry was started.') from None
    return True
