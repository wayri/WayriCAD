"""Process-memory OAuth device authority for Review's desktop provider calls.

No credential, refresh token, device code or browser session is persisted here.
The returned epoch is a cancellation ticket, not an authorization token.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model import host as valid_host


TTL = 8 * 60 * 60
GITHUB_CLIENT_ID = 'Ov23li8RsSVZk2dHptN1'
GITLAB_CLIENT_ID = 'ea3496457b4d3a71d846ef9749af37559d2a71cf5efdb2a049ea8da164e0005c'
_MAX_RESPONSE = 64 * 1024
_MAX_DEVICE_SECONDS = 30 * 60
_BEARER = re.compile(r'[A-Za-z0-9._~+/-]+={0,2}\Z')


class SignInRequired(RuntimeError):
    """A credential or current sign-in ticket is unavailable."""


def _valid_token(token: str) -> bool:
    return isinstance(token, str) and 0 < len(token) <= 8192 and _BEARER.fullmatch(token) is not None


def _key(provider: str, origin: str) -> tuple[str, str]:
    if provider == 'github':
        if origin not in ('', None, 'https://github.com', 'https://github.com/'):
            raise ValueError('GitHub Review uses https://github.com.')
        return 'github', 'https://github.com'
    if provider == 'gitlab':
        return 'gitlab', valid_host(origin)
    raise ValueError('Choose GitHub or GitLab for Review sign-in.')


class _Authority:
    def __init__(self):
        self._lock = threading.RLock()
        self._states: dict[tuple[str, str], dict] = {}

    def begin(self, provider: str, origin: str) -> int:
        key = _key(provider, origin)
        with self._lock:
            old = self._states.get(key, {})
            epoch = old.get('epoch', 0) + 1
            self._states[key] = {'epoch': epoch, 'pending': True}
            return epoch

    def install(self, provider: str, origin: str, token: str, *, epoch: int,
                expires_in: int | float | None = None, account: str = '') -> dict:
        key = _key(provider, origin)
        if not _valid_token(token):
            raise ValueError('Provider returned an invalid access token.')
        if not isinstance(epoch, int) or isinstance(epoch, bool):
            raise SignInRequired('This sign-in has been cancelled or replaced.')
        if expires_in is None:
            lifetime = TTL
        elif isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)) or not math.isfinite(expires_in) or expires_in <= 0:
            raise ValueError('Provider returned an invalid token lifetime.')
        else:
            lifetime = min(TTL, float(expires_in))
        if not isinstance(account, str) or len(account) > 200:
            raise ValueError('Provider returned an invalid account name.')
        with self._lock:
            state = self._states.get(key)
            if not state or state['epoch'] != epoch or not state.get('pending'):
                raise SignInRequired('This sign-in has been cancelled or replaced.')
            wall, mono = time.time(), time.monotonic()
            state.update(token=token, expires_wall=wall + lifetime,
                         expires_mono=mono + lifetime, account=account, pending=False)
            return {'expiresAt': state['expires_wall'], 'account': account}

    def _valid(self, key: tuple[str, str]) -> dict:
        state = self._states.get(key)
        if not state or 'token' not in state:
            raise SignInRequired('Sign in to Review to continue.')
        if time.time() >= state['expires_wall'] or time.monotonic() >= state['expires_mono']:
            self._states[key] = {'epoch': state['epoch'] + 1, 'pending': False}
            raise SignInRequired('Review sign-in expired. Sign in again.')
        return state

    def credential(self, provider: str, origin: str) -> str:
        with self._lock:
            return self._valid(_key(provider, origin))['token']

    def status(self, provider: str, origin: str) -> dict:
        with self._lock:
            try:
                state = self._valid(_key(provider, origin))
            except SignInRequired:
                return {'authenticated': False}
            return {'authenticated': True, 'expiresAt': state['expires_wall'],
                    'account': state['account']}

    def sign_out(self, provider: str, origin: str) -> None:
        key = _key(provider, origin)
        with self._lock:
            old = self._states.get(key, {})
            self._states[key] = {'epoch': old.get('epoch', 0) + 1, 'pending': False}

    def cancel(self, provider: str, origin: str, epoch: int) -> None:
        """Invalidate only the specified flow; preserve any newer sign-in."""
        key = _key(provider, origin)
        with self._lock:
            state = self._states.get(key)
            if state and state['epoch'] == epoch:
                self._states[key] = {'epoch': epoch + 1, 'pending': False}

    def ticket(self, provider: str, origin: str) -> int:
        with self._lock:
            return self._valid(_key(provider, origin))['epoch']

    def assert_ticket(self, provider: str, origin: str, epoch: int) -> None:
        with self._lock:
            if self._valid(_key(provider, origin))['epoch'] != epoch:
                raise SignInRequired('Review sign-in changed. Refresh and try again.')


AUTH = _Authority()


def begin(provider, origin):
    return AUTH.begin(provider, origin)


def install(provider, origin, token, *, epoch, expires_in=None, account=''):
    return AUTH.install(provider, origin, token, epoch=epoch, expires_in=expires_in, account=account)


def credential(provider, origin):
    return AUTH.credential(provider, origin)


def status(provider, origin):
    return AUTH.status(provider, origin)


def sign_out(provider, origin):
    return AUTH.sign_out(provider, origin)


def cancel(provider, origin, epoch):
    return AUTH.cancel(provider, origin, epoch)


def ticket(provider, origin):
    return AUTH.ticket(provider, origin)


def assert_ticket(provider, origin, epoch):
    return AUTH.assert_ticket(provider, origin, epoch)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _request_json(url: str, *, form: dict | None = None, token: str | None = None) -> dict:
    """Bounded HTTPS request; transport errors never echo response/token data."""
    if urlsplit(url).scheme != 'https':
        raise ValueError('OAuth requires HTTPS.')
    if token is not None and not _valid_token(token):
        raise SignInRequired('Provider returned an invalid access token.')
    headers = {'Accept': 'application/json', 'User-Agent': 'WayriCAD-Review'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = urlencode(form).encode('ascii') if form is not None else None
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    try:
        request = Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    except (ValueError, TypeError):
        raise SignInRequired('Provider sign-in request could not be prepared.') from None
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=15)
    except HTTPError as error:
        if error.code not in (400, 401, 403):
            raise SignInRequired(f'Provider sign-in request failed (HTTP {error.code}).') from None
        response = error
    except (URLError, TimeoutError, OSError):
        raise SignInRequired('Provider sign-in network request failed.') from None
    try:
        with response:
            data = response.read(_MAX_RESPONSE + 1)
        if len(data) > _MAX_RESPONSE:
            raise SignInRequired('Provider sign-in response was too large.')
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (UnicodeError, ValueError):
        raise SignInRequired('Provider returned an invalid sign-in response.') from None


def _positive(value, label: str, maximum: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or value > maximum:
        raise SignInRequired('Provider returned an invalid ' + label + '.')
    return float(value)


def _check_cancel(key: tuple[str, str], epoch: int, cancelled) -> None:
    if cancelled and cancelled():
        AUTH.cancel(*key, epoch)
        raise SignInRequired('Review sign-in was cancelled.')
    with AUTH._lock:
        state = AUTH._states.get(key)
        if not state or state['epoch'] != epoch or not state.get('pending'):
            raise SignInRequired('Review sign-in was cancelled or replaced.')


def _pause(seconds: float, key: tuple[str, str], epoch: int, cancelled, deadline: float) -> None:
    until = min(time.monotonic() + seconds, deadline)
    while time.monotonic() < until:
        _check_cancel(key, epoch, cancelled)
        time.sleep(min(0.25, until - time.monotonic()))


def sign_in(provider: str, origin: str, *, progress, cancelled,
            private: bool = False, client_id: str | None = None) -> dict:
    """Run OAuth device flow and install only a verified, current access token.

    The caller presents ``progress({user_code, verification_uri})``. It owns
    browser opening and UI cancellation; this function performs no CLI fallback.
    """
    key = _key(provider, origin)
    if not callable(progress) or not callable(cancelled):
        raise ValueError('Review sign-in needs progress and cancellation callbacks.')
    if client_id is None:
        client_id = (GITHUB_CLIENT_ID if provider == 'github' else
                     GITLAB_CLIENT_ID if key[1] == 'https://gitlab.com' else
                     os.environ.get('WAYRICAD_REVIEW_GITLAB_CLIENT_ID'))
    if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 256:
        raise SignInRequired('Configure a public OAuth device-flow client ID for this GitLab host.')
    epoch = AUTH.begin(*key)
    _check_cancel(key, epoch, cancelled)
    if provider == 'github':
        form = {'client_id': client_id, 'scope': ('repo' if private else 'public_repo') + ' write:discussion'}
        device_url = 'https://github.com/login/device/code'
        token_url = 'https://github.com/login/oauth/access_token'
        user_url = 'https://api.github.com/user'
    else:
        form = {'client_id': client_id, 'scope': 'api'}
        device_url = key[1] + '/oauth/authorize_device'
        token_url = key[1] + '/oauth/token'
        user_url = key[1] + '/api/v4/user'
    device = _request_json(device_url, form=form)
    _check_cancel(key, epoch, cancelled)
    code, user_code, verification = (device.get(name) for name in
                                     ('device_code', 'user_code', 'verification_uri'))
    parsed_verification = urlsplit(verification) if isinstance(verification, str) else None
    expected_path = '/login/device' if provider == 'github' else '/oauth/device'
    if (not all(isinstance(v, str) and v and len(v) <= 512 for v in (code, user_code, verification)) or
            parsed_verification.scheme != 'https' or
            f'{parsed_verification.scheme}://{parsed_verification.netloc}' != key[1] or
            parsed_verification.username or parsed_verification.password or
            parsed_verification.path != expected_path or parsed_verification.query or
            parsed_verification.fragment):
        raise SignInRequired('Provider returned an unsafe device verification link.')
    lifetime = _positive(device.get('expires_in'), 'device-code lifetime', _MAX_DEVICE_SECONDS)
    interval = _positive(device.get('interval', 5), 'polling interval', 300)
    deadline = time.monotonic() + lifetime
    progress({'user_code': user_code, 'verification_uri': verification, 'epoch': epoch})
    while True:
        _pause(interval, key, epoch, cancelled, deadline)
        _check_cancel(key, epoch, cancelled)
        if time.monotonic() >= deadline:
            raise SignInRequired('Device code expired. Start sign-in again.')
        result = _request_json(token_url, form={
            'client_id': client_id, 'device_code': code,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'})
        _check_cancel(key, epoch, cancelled)
        error = result.get('error')
        if error == 'authorization_pending':
            continue
        if error == 'slow_down':
            interval = max(interval + 5, _positive(result.get('interval', interval + 5), 'polling interval', 300))
            continue
        if error in ('access_denied', 'expired_token', 'device_flow_disabled'):
            raise SignInRequired('Device sign-in was denied, expired or disabled by the provider.')
        if error:
            raise SignInRequired('Provider rejected device sign-in. Check the OAuth application and permissions.')
        token = result.get('access_token')
        if not _valid_token(token):
            raise SignInRequired('Provider did not return an access token.')
        if str(result.get('token_type', 'bearer')).lower() != 'bearer':
            raise SignInRequired('Provider returned an unsupported token type.')
        user = _request_json(user_url, token=token)
        _check_cancel(key, epoch, cancelled)
        account = user.get('login' if provider == 'github' else 'username')
        if not isinstance(account, str) or not account or len(account) > 200:
            raise SignInRequired('Provider could not verify the signed-in account.')
        receipt = AUTH.install(*key, token, epoch=epoch,
                               expires_in=result.get('expires_in'), account=account)
        if cancelled():
            AUTH.cancel(*key, epoch)
            raise SignInRequired('Review sign-in was cancelled.')
        return receipt
