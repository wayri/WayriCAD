import http.client
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from review_comments_plugin.web_assets import required_paths
from review_comments_plugin.web_host import ReviewWebHost, _route


class ReviewWebHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.viewer = self.root / 'viewer'
        self.web = self.root / 'web'
        for name in required_paths(linked_models=True):
            target = self.viewer / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(('source:' + name).encode('utf-8'))
        self.web.mkdir()
        for name in ('index.html', 'bridge.mjs', 'style.css'):
            (self.web / name).write_bytes(('web:' + name).encode('utf-8'))

    def _request(self, host, method, route, *, headers=None):
        address = urlsplit(host.url)
        connection = http.client.HTTPConnection('127.0.0.1', address.port, timeout=3)
        try:
            connection.request(method, route, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_exact_get_head_and_memory_snapshot(self):
        with ReviewWebHost(self.viewer, self.web) as host:
            address = urlsplit(host.url)
            self.assertEqual(address.hostname, '127.0.0.1')
            token = address.path.split('/')[1]
            status, headers, body = self._request(host, 'GET', address.path)
            self.assertEqual((status, body), (200, b'web:index.html'))
            self.assertEqual(headers['Content-Type'], 'text/html; charset=utf-8')
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            asset = f'/{token}/vendor/web-library/kicad-viewer.mjs'
            status, headers, body = self._request(host, 'GET', asset)
            self.assertEqual((status, body), (200, b'source:web-library/kicad-viewer.mjs'))
            self.assertEqual(headers['Content-Type'], 'text/javascript; charset=utf-8')
            (self.viewer / 'web-library/kicad-viewer.mjs').write_bytes(b'changed after start')
            self.assertEqual(self._request(host, 'GET', asset)[2], body)
            status, headers, body = self._request(host, 'HEAD', asset)
            self.assertEqual(status, 200)
            self.assertEqual(body, b'')
            self.assertEqual(headers['Content-Length'], str(len(b'source:web-library/kicad-viewer.mjs')))
            host.close()  # Idempotent with context-manager shutdown.

    def test_rejects_wrong_host_path_method_and_unknown_asset(self):
        with ReviewWebHost(self.viewer, self.web) as host:
            address = urlsplit(host.url)
            token = address.path.split('/')[1]
            self.assertEqual(self._request(host, 'GET', address.path,
                                           headers={'Host': 'attacker.test'})[0], 403)
            for route in ('/index.html', f'/{token}/../index.html',
                          f'/{token}/%2e%2e/index.html', f'/{token}/vendor/private.txt',
                          f'/{token}/index.html?source=secret'):
                self.assertEqual(self._request(host, 'GET', route)[0], 404, route)
            self.assertEqual(self._request(host, 'POST', address.path)[0], 405)

    def test_missing_asset_prevents_start(self):
        (self.viewer / 'extension/pcb-renderer.js').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            ReviewWebHost(self.viewer, self.web)

    def test_route_rejects_encoded_traversal_and_query_without_socket(self):
        self.assertEqual(_route('/token/vendor/extension/owned-canvas.js', 'token'),
                         'vendor/extension/owned-canvas.js')
        for target in ('/bad/index.html', '/token/../index.html',
                       '/token/%2e%2e/index.html', '/token/index.html?x=1',
                       '/token/vendor/%5csecret', '/token//index.html'):
            self.assertIsNone(_route(target, 'token'), target)


if __name__ == '__main__':
    unittest.main()
