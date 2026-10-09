"""Real loopback HTTP acceptance: shipped assets, MIME and isolated sessions."""
import http.client
import json
import mimetypes
from pathlib import Path
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from bomstudio.server import Application, Server
from bomstudio.bridge import _check_sdk_version, BridgeUnavailable
from bomstudio.desktop import DesktopUnavailable, run


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
                    expected = ('text/javascript' if path.endswith('.js') else
                                'image/x-icon' if path.endswith('.ico') else 'text/css')
                    self.assertEqual(mime.split(';')[0], expected)
        self.assertEqual(self.get(0, '/not-a-file.js')[0], 404)

    def test_independent_projects_ports_and_authentication(self):
        self.assertNotEqual(self.servers[0].server_port, self.servers[1].server_port)
        self.assertNotEqual(self.apps[0].token, self.apps[1].token)
        self.assertNotEqual(self.apps[0].workspace.project.root, self.apps[1].workspace.project.root)
        for i in range(2):
            self.assertEqual(self.get(i, '/api/state')[0], 200)
            self.assertEqual(self.get(i, '/api/state', self.apps[1-i].token)[0], 401)

    def test_embedded_startup_failure_opens_usable_local_browser(self):
        # Use an unstarted server: the fallback itself must start and own it.
        app = Application(demo=True)
        server = Server(app)
        opened = []
        ready = []

        def browser_open(url, new):
            opened.append(url)
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                conn.request('GET', '/')
                page = conn.getresponse()
                self.assertEqual(page.status, 200)
                self.assertIn(b'BOM', page.read())
                conn.request('GET', '/api/state', headers={'X-Bom-Token': app.token})
                state = conn.getresponse()
                self.assertEqual(state.status, 200)
                payload = json.loads(state.read())
                self.assertEqual(payload['ui_mode'], 'browser')
                self.assertIsNotNone(payload['project'])
                conn.request('POST', '/api/quit', body='{}', headers={
                    'X-Bom-Token': app.token, 'Content-Type': 'application/json'})
                self.assertEqual(conn.getresponse().status, 200)
            finally:
                conn.close()
            return True

        try:
            with patch('bomstudio.desktop._run_embedded', side_effect=DesktopUnavailable('renderer timed out')), \
                 patch('bomstudio.desktop.webbrowser.open', side_effect=browser_open):
                run(server, on_ready=ready.append)
            self.assertEqual(opened, [server.url])
            self.assertEqual(ready, ['browser'])
            self.assertIn('renderer timed out', app.startup_note)
        finally:
            server.server_close()
            import shutil
            shutil.rmtree(app.demo_directory)


class ColdStartHTTPTests(unittest.TestCase):
    def test_page_asset_burst_survives_before_accept_loop_is_scheduled(self):
        # Model a renderer's simultaneous cold requests while the main thread
        # finishes native-window setup. Every connection must reach the local
        # server; dropping a single script leaves whole views unregistered.
        root = Path(__file__).resolve().parents[1]
        paths = re.findall(r'(?:src|href)="(/[^"]+)"',
                           (root / 'web' / 'index.html').read_text(encoding='utf-8'))
        app = Application()
        server = Server(app)
        connected = threading.Barrier(len(paths) + 1)
        worker = threading.Thread(target=server.serve_forever, daemon=True)

        def load(path):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                conn.connect()
                connected.wait(timeout=5)
                conn.request('GET', path)
                response = conn.getresponse()
                return path, response.status, response.read()
            finally:
                conn.close()

        try:
            with ThreadPoolExecutor(max_workers=len(paths)) as pool:
                requests = [pool.submit(load, path) for path in paths]
                try:
                    connected.wait(timeout=5)
                finally:
                    worker.start()
                for request in requests:
                    path, status, body = request.result(timeout=15)
                    with self.subTest(path=path):
                        self.assertEqual(status, 200)
                        self.assertTrue(body)
        finally:
            if worker.is_alive():
                server.shutdown()
                worker.join(5)
            server.server_close()


class SDKRangeTests(unittest.TestCase):
    def test_declared_patch_versions_are_supported(self):
        for version in ('0.8.0', '0.8.1', '0.8.15'):
            with patch('bomstudio.bridge.metadata.version', return_value=version):
                _check_sdk_version()
        for version in ('0.7.9', '0.9.0', '0.8.1rc1'):
            with patch('bomstudio.bridge.metadata.version', return_value=version):
                with self.assertRaises(BridgeUnavailable): _check_sdk_version()
