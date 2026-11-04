import unittest
from unittest.mock import patch

from review_comments_plugin import desktop_auth as auth


class DesktopAuthTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1_000., 500.]
        self.patches = [
            patch.object(auth, 'AUTH', auth._Authority()),
            patch.object(auth.time, 'time', side_effect=lambda: self.clock[0]),
            patch.object(auth.time, 'monotonic', side_effect=lambda: self.clock[1]),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_hard_eight_hours_and_shorter_provider_lifetime(self):
        epoch = auth.begin('github', 'https://github.com')
        receipt = auth.install('github', '', 'private-token', epoch=epoch, account='engineer')
        self.assertEqual(receipt, {'expiresAt': 1_000 + auth.TTL, 'account': 'engineer'})
        self.assertEqual(auth.credential('github', ''), 'private-token')
        self.assertEqual(auth.ticket('github', ''), epoch)
        self.clock[0] += auth.TTL - 1
        self.assertTrue(auth.status('github', '')['authenticated'])
        self.clock[1] += auth.TTL
        with self.assertRaises(auth.SignInRequired):
            auth.credential('github', '')
        self.assertFalse(auth.status('github', '')['authenticated'])
        newer = auth.begin('gitlab', 'https://gitlab.com')
        auth.install('gitlab', 'https://gitlab.com', 'short', epoch=newer, expires_in=60)
        self.clock[0] += 60
        with self.assertRaises(auth.SignInRequired):
            auth.assert_ticket('gitlab', 'https://gitlab.com', newer)

    def test_begin_signout_and_late_install_invalidate_epochs(self):
        first = auth.begin('github', '')
        second = auth.begin('github', '')
        with self.assertRaises(auth.SignInRequired):
            auth.install('github', '', 'late-token', epoch=first)
        auth.install('github', '', 'current-token', epoch=second)
        with self.assertRaises(auth.SignInRequired):
            auth.install('github', '', 'duplicate-token', epoch=second)
        auth.sign_out('github', '')
        self.assertFalse(auth.status('github', '')['authenticated'])
        with self.assertRaises(auth.SignInRequired):
            auth.assert_ticket('github', '', second)
        with self.assertRaises(auth.SignInRequired):
            auth.credential('github', '')
        old = auth.begin('github', '')
        new = auth.begin('github', '')
        auth.cancel('github', '', old)
        auth.install('github', '', 'new-token', epoch=new)
        self.assertEqual(auth.credential('github', ''), 'new-token')
        auth.cancel('github', '', new)
        self.assertFalse(auth.status('github', '')['authenticated'])

    def test_provider_origin_isolation_and_invalid_lifetime(self):
        one = auth.begin('gitlab', 'https://gitlab.example')
        two = auth.begin('gitlab', 'https://gitlab.com')
        with self.assertRaises(ValueError):
            auth.install('gitlab', 'https://gitlab.example', 'token', epoch=one, expires_in=float('nan'))
        auth.install('gitlab', 'https://gitlab.example', 'one', epoch=one)
        auth.install('gitlab', 'https://gitlab.com', 'two', epoch=two)
        self.assertEqual(auth.credential('gitlab', 'https://gitlab.example/'), 'one')
        self.assertEqual(auth.credential('gitlab', 'https://gitlab.com'), 'two')
        auth.sign_out('gitlab', 'https://gitlab.example')
        self.assertEqual(auth.credential('gitlab', 'https://gitlab.com'), 'two')
        with self.assertRaises(ValueError):
            auth.begin('gitlab', 'http://gitlab.example')

    def test_device_flow_scopes_polling_verify_and_receipt(self):
        calls, waits, shown = [], [], []
        responses = [
            {'device_code': 'device-secret', 'user_code': 'ABCD-EFGH',
             'verification_uri': 'https://github.com/login/device', 'expires_in': 900, 'interval': 5},
            {'error': 'authorization_pending'}, {'error': 'slow_down', 'interval': 10},
            {'access_token': 'access-secret', 'token_type': 'bearer', 'expires_in': 3600},
            {'login': 'engineer'},
        ]
        def request(url, *, form=None, token=None):
            calls.append((url, form, token))
            return responses.pop(0)
        with patch.object(auth, '_request_json', side_effect=request), patch.object(
                auth, '_pause', side_effect=lambda seconds, *_: waits.append(seconds)):
            receipt = auth.sign_in('github', '', progress=shown.append, cancelled=lambda: False)
        self.assertEqual(shown, [{'user_code': 'ABCD-EFGH',
                                  'verification_uri': 'https://github.com/login/device', 'epoch': 1}])
        self.assertEqual(waits, [5, 5, 10])
        self.assertEqual(calls[0][1]['scope'], 'public_repo write:discussion')
        self.assertEqual(calls[-1][2], 'access-secret')
        self.assertEqual(receipt['expiresAt'], self.clock[0] + 3600)
        self.assertEqual(auth.credential('github', ''), 'access-secret')

    def test_cancellation_and_unsafe_uri_never_install(self):
        device = {'device_code': 'd', 'user_code': 'u',
                  'verification_uri': 'https://attacker.example/device', 'expires_in': 300}
        with patch.object(auth, '_request_json', return_value=device):
            with self.assertRaisesRegex(auth.SignInRequired, 'unsafe'):
                auth.sign_in('gitlab', 'https://gitlab.com', progress=lambda _: None,
                             cancelled=lambda: False)
        self.assertFalse(auth.status('gitlab', 'https://gitlab.com')['authenticated'])
        with patch.object(auth, '_request_json') as request:
            with self.assertRaisesRegex(auth.SignInRequired, 'cancelled'):
                auth.sign_in('github', '', progress=lambda _: None, cancelled=lambda: True)
            request.assert_not_called()

    def test_gitlab_device_flow_uses_origin_and_api_scope(self):
        calls = []
        replies = [
            {'device_code': 'device', 'user_code': '1234ABCD',
             'verification_uri': 'https://gitlab.example/oauth/device',
             'expires_in': 300, 'interval': 5},
            {'access_token': 'gitlab-token', 'token_type': 'Bearer', 'expires_in': 7200},
            {'username': 'reviewer'},
        ]
        def request(url, *, form=None, token=None):
            calls.append((url, form, token))
            return replies.pop(0)
        with patch.object(auth, '_request_json', side_effect=request), patch.object(
                auth, '_pause'), patch.dict(auth.os.environ,
                {'WAYRICAD_REVIEW_GITLAB_CLIENT_ID': 'public-client'}):
            auth.sign_in('gitlab', 'https://gitlab.example', progress=lambda _: None,
                         cancelled=lambda: False)
        self.assertEqual(calls[0][0], 'https://gitlab.example/oauth/authorize_device')
        self.assertEqual(calls[0][1], {'client_id': 'public-client', 'scope': 'api'})
        self.assertEqual(calls[1][0], 'https://gitlab.example/oauth/token')
        self.assertEqual(calls[2], ('https://gitlab.example/api/v4/user', None, 'gitlab-token'))
        self.assertEqual(auth.status('gitlab', 'https://gitlab.example')['account'], 'reviewer')

    def test_signout_during_polling_rejects_late_token(self):
        replies = [
            {'device_code': 'device', 'user_code': '1234ABCD',
             'verification_uri': 'https://github.com/login/device',
             'expires_in': 300, 'interval': 5},
            {'access_token': 'late-token', 'token_type': 'bearer'},
        ]
        with patch.object(auth, '_request_json', side_effect=lambda *_args, **_kwargs: replies.pop(0)), patch.object(
                auth, '_pause', side_effect=lambda *_args: auth.sign_out('github', '')):
            with self.assertRaises(auth.SignInRequired):
                auth.sign_in('github', '', progress=lambda _: None, cancelled=lambda: False)
        self.assertFalse(auth.status('github', '')['authenticated'])

    def test_hostile_token_never_reaches_user_request_or_diagnostics(self):
        secret = 'secret\r\nX-Leak: value'
        replies = [
            {'device_code': 'device', 'user_code': '1234ABCD',
             'verification_uri': 'https://github.com/login/device',
             'expires_in': 300, 'interval': 5},
            {'access_token': secret, 'token_type': 'bearer'},
        ]
        with patch.object(auth, '_request_json', side_effect=lambda *_args, **_kwargs: replies.pop(0)) as request, patch.object(
                auth, '_pause'):
            with self.assertRaises(auth.SignInRequired) as caught:
                auth.sign_in('github', '', progress=lambda _: None, cancelled=lambda: False)
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(request.call_count, 2)
        self.assertFalse(auth.status('github', '')['authenticated'])

    def test_self_hosted_requires_public_client_id(self):
        with patch.dict(auth.os.environ, {}, clear=True):
            with self.assertRaisesRegex(auth.SignInRequired, 'client ID'):
                auth.sign_in('gitlab', 'https://gitlab.example', progress=lambda _: None,
                             cancelled=lambda: False)


if __name__ == '__main__':
    unittest.main()
