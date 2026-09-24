"""wx must not see the already-parsed BOM launcher switches."""
import sys
import http.client
from pathlib import Path
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import entrypoint
from bomstudio.server import Server
from bomstudio.desktop_wx import _initialize_bridge, _set_window_icon
from bomstudio.startup import load_with_progress


class LaunchArguments(unittest.TestCase):
    def test_long_project_load_shows_indeterminate_window_and_returns_value(self):
        calls = []
        def show(done):
            calls.append('loading')
            self.assertFalse(done.is_set())
            self.assertTrue(done.wait(2))
        with patch('bomstudio.startup._show_loading', side_effect=show):
            result = load_with_progress(lambda: threading.Event().wait(.07) or 'workspace', threshold=.001)
        self.assertEqual(result, 'workspace')
        self.assertEqual(calls, ['loading'])

    def test_project_load_error_reaches_existing_startup_handler(self):
        def fail():
            raise ValueError('Unreadable schematic')
        with self.assertRaisesRegex(ValueError, 'Unreadable schematic'):
            load_with_progress(fail, threshold=.01)

    def test_desktop_receives_project_but_wx_sees_no_launcher_switches(self):
        app = SimpleNamespace(ui_mode=None)
        server = SimpleNamespace(server_close=Mock())

        def run(_server, on_ready):
            self.assertIs(_server, server)
            self.assertEqual(sys.argv, ['desktop_entrypoint.py'])

        with (patch.object(sys, 'argv', ['desktop_entrypoint.py', 'C:/Projects/Example/board.kicad_pro', '--ui', 'desktop']),
              patch('bomstudio.server.Application', return_value=app) as application,
              patch('bomstudio.server.Server', return_value=server),
              patch('bomstudio.desktop.run', side_effect=run)):
            self.assertEqual(entrypoint.main(), 0)
        application.assert_called_once_with('C:/Projects/Example/board.kicad_pro', False,
                                            auto_link=True, analytics_demo=False,
                                            engineering_demo=False)
        server.server_close.assert_called_once()

    def test_local_page_serves_packaged_favicon(self):
        app = SimpleNamespace(link=SimpleNamespace(close=Mock()), token='test')
        server = Server(app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            connection.request('GET', '/favicon.ico')
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Content-Type'), 'image/x-icon')
            self.assertEqual(response.read(), (Path(__file__).resolve().parents[1] / 'resources' / 'icon.ico').read_bytes())
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_preferred_wx_window_uses_packaged_taskbar_icon(self):
        icon = SimpleNamespace(IsOk=lambda: True)
        wx = SimpleNamespace(Icon=Mock(return_value=icon), BITMAP_TYPE_ICO=7)
        window = SimpleNamespace(SetIcon=Mock())
        with patch('bomstudio.desktop_wx.sys.platform', 'win32'):
            self.assertTrue(_set_window_icon(window, wx))
        self.assertEqual(Path(wx.Icon.call_args.args[0]).name, 'icon.ico')
        window.SetIcon.assert_called_once_with(icon)

    def test_bad_icon_does_not_abort_window_creation(self):
        wx = SimpleNamespace(Icon=Mock(side_effect=OSError('bad icon')), BITMAP_TYPE_ICO=7)
        self.assertFalse(_set_window_icon(SimpleNamespace(SetIcon=Mock()), wx))

    def test_loading_strip_clears_when_workspace_connects_without_host_callback(self):
        window = SimpleNamespace(ready=False, view=SimpleNamespace(RunScriptAsync=Mock()),
                                 loading=SimpleNamespace(Hide=Mock()), Layout=Mock())
        _initialize_bridge(window)
        self.assertTrue(window.ready)
        window.loading.Hide.assert_called_once_with()
        window.Layout.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
