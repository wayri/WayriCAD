"""Local fallback lifecycle, request authentication, and failure cleanup."""
import http.client
import threading
import unittest
from unittest.mock import patch
from bomstudio import desktop
from bomstudio.server import Application, Server


class LocalFallback(unittest.TestCase):
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
