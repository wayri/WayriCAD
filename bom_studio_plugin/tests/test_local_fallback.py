"""Local fallback lifecycle, request authentication, and failure cleanup."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
from bomstudio import desktop
from bomstudio.server import Application, Server, Handler


class LocalFallback(unittest.TestCase):
    def test_quit_sends_reply_before_host_shutdown(self):
        server = Server(Application())
        response_started = threading.Event()
        allow_response = threading.Event()
        shutdown_requested = threading.Event()
        original_respond = Handler.respond
        original_shutdown = server.shutdown
        received = []

        def respond(handler, *args, **kwargs):
            response_started.set()
            if not allow_response.wait(5):
                raise RuntimeError('Test did not release the HTTP reply')
            return original_respond(handler, *args, **kwargs)

        def shutdown():
            shutdown_requested.set()
            original_shutdown()

        def quit_client():
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                conn.request('POST', '/api/quit', '{}', {
                    'X-Bom-Token': server.app.token,
                    'Content-Type': 'application/json',
                })
                response = conn.getresponse()
                received.append((response.status, json.loads(response.read())))
            finally:
                conn.close()

        worker = threading.Thread(target=server.serve_forever, daemon=True)
        client = threading.Thread(target=quit_client, daemon=True)
        worker.start()
        try:
            with patch.object(Handler, 'respond', respond), patch.object(server, 'shutdown', shutdown):
                client.start()
                self.assertTrue(response_started.wait(5))
                self.assertFalse(shutdown_requested.wait(.2), 'Host shut down before its HTTP reply')
                allow_response.set()
                client.join(10)
                self.assertEqual(received, [(200, {'ok': True})])
                self.assertTrue(shutdown_requested.wait(5))
        finally:
            allow_response.set()
            client.join(10)
            original_shutdown()
            worker.join(5)
            server.server_close()

    def test_loopback_startup_never_resolves_dns(self):
        with patch('socket.getfqdn',side_effect=AssertionError('Unexpected reverse DNS')):
            server=Server(Application())
            try:
                self.assertEqual(server.server_name,'127.0.0.1')
                self.assertGreater(server.server_port,0)
                self.assertEqual(server.socket.getsockname(),('127.0.0.1',server.server_port))
                self.assertEqual(server.origin,f'http://127.0.0.1:{server.server_port}')
            finally:server.server_close()

    def test_fallback_serves_local_page_and_quits(self):
        server=Server(Application())
        modes=[]
        def open_page(url,new):
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            self.assertIn('#token=',url)
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            client.request('GET','/')
            response=client.getresponse()
            self.assertEqual(response.status,200)
            self.assertIn(b'WayriCAD',response.read())
            client.request('GET','/api/state')
            response=client.getresponse()
            self.assertEqual(response.status,401)
            response.read();client.close()
            threading.Thread(target=server.shutdown,daemon=True).start()
            return True
        with patch.object(desktop.webbrowser,'open',side_effect=open_page):
            desktop.run_local_browser(server,modes.append,'No WebView')
        self.assertEqual(modes,['browser'])
        self.assertEqual(server.socket.fileno(),-1)

    def test_failed_browser_closes_service(self):
        server=Server(Application())
        with patch.object(desktop.webbrowser,'open',return_value=False):
            with self.assertRaises(desktop.DesktopUnavailable):
                desktop.run_local_browser(server)
        self.assertEqual(server.socket.fileno(),-1)
