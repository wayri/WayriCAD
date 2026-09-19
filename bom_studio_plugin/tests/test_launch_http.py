"""Real loopback HTTP acceptance: shipped assets, MIME and isolated sessions."""
import http.client
import json
import mimetypes
from pathlib import Path
import re
import threading
import unittest
from unittest.mock import patch
from bomstudio.server import Application, Server
from bomstudio.bridge import _check_sdk_version, BridgeUnavailable


class LaunchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.apps = [Application(demo=True), Application(demo=True)]
        self.servers = [Server(app) for app in self.apps]
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in self.servers]
        for thread in self.threads: thread.start()

    def tearDown(self):
        import shutil
        for server, thread, app in zip(self.servers, self.threads, self.apps):
            server.shutdown(); server.server_close(); thread.join(5)
            shutil.rmtree(app.demo_directory)

    def get(self, index, path, token=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.servers[index].server_port, timeout=10)
        try:
            conn.request('GET', path, headers={'X-Bom-Token':token or self.apps[index].token})
            response = conn.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally: conn.close()

    def test_every_shipped_page_asset_is_served_with_safe_mime(self):
        status, mime, html = self.get(0, '/')
        self.assertEqual(status, 200)
        paths = re.findall(r'(?:src|href)="(/[^"]+)"', html.decode())
        self.assertIn('/workspace.js', paths)
        # User Windows registry/OS MIME associations must not break nosniff.
        with patch.object(mimetypes, 'guess_type', return_value=('text/plain', None)):
            for path in paths:
                with self.subTest(path=path):
                    status, mime, body = self.get(0, path)
                    self.assertEqual(status, 200)
                    self.assertTrue(body)
                    self.assertEqual(mime.split(';')[0], 'text/javascript' if path.endswith('.js') else 'text/css')
        self.assertEqual(self.get(0, '/not-a-file.js')[0], 404)

    def test_independent_projects_ports_and_authentication(self):
        self.assertNotEqual(self.servers[0].server_port, self.servers[1].server_port)
        self.assertNotEqual(self.apps[0].token, self.apps[1].token)
        self.assertNotEqual(self.apps[0].workspace.project.root, self.apps[1].workspace.project.root)
        for i in range(2):
            self.assertEqual(self.get(i, '/api/state')[0], 200)
            self.assertEqual(self.get(i, '/api/state', self.apps[1-i].token)[0], 401)


class SDKRangeTests(unittest.TestCase):
    def test_declared_patch_versions_are_supported(self):
        for version in ('0.8.0', '0.8.1', '0.8.15'):
            with patch('bomstudio.bridge.metadata.version', return_value=version):
                _check_sdk_version()
        for version in ('0.7.9', '0.9.0', '0.8.1rc1'):
            with patch('bomstudio.bridge.metadata.version', return_value=version):
                with self.assertRaises(BridgeUnavailable): _check_sdk_version()
