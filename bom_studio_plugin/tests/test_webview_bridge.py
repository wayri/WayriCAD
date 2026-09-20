"""Reproduce WebView2 load-event reentry without requiring a display server."""
from types import SimpleNamespace
import unittest
from bomstudio.desktop_wx import _initialize_bridge, _workspace_loaded


class BridgeTests(unittest.TestCase):
    def test_only_initial_workspace_document_initializes_bridge(self):
        expected = 'http://127.0.0.1:12345/#token=test-session'
        scripts, callbacks = [], []
        view = SimpleNamespace(GetCurrentURL=lambda: expected, RunScriptAsync=scripts.append)
        window = SimpleNamespace(ready=False, view=view)
        def event(url, target=''):
            return SimpleNamespace(GetURL=lambda: url, GetTarget=lambda: target)
        for url in ('about:blank', 'http://127.0.0.1:12345/help.html',
                    'http://127.0.0.1:12346/#token=test-session',
                    'http://127.0.0.1:12345/?other=document'):
            _workspace_loaded(window, event(url), expected, callbacks.append)
        _workspace_loaded(window, event(expected, 'child-frame'), expected, callbacks.append)
        view.GetCurrentURL = lambda: 'about:blank'
        _workspace_loaded(window, event(expected), expected, callbacks.append)
        self.assertFalse(window.ready)
        self.assertEqual(scripts, [])
        self.assertEqual(callbacks, [])
        view.GetCurrentURL = lambda: expected.split('#')[0]
        _workspace_loaded(window, event(expected.split('#')[0]), expected, callbacks.append)
        self.assertTrue(window.ready)
        self.assertEqual(len(scripts), 1)
        self.assertEqual(callbacks, ['desktop'])

    def test_reentrant_load_queues_once_without_synchronous_script(self):
        scripts, callbacks = [], []
        window = SimpleNamespace(ready=False)
        def ready(mode): callbacks.append(mode)
        class View:
            def RunScript(self, script):
                raise AssertionError('Synchronous script execution can reenter the load callback')
            def RunScriptAsync(self, script):
                scripts.append(script)
                _initialize_bridge(window, ready)
        window.view=View()
        _initialize_bridge(window, ready)
        _initialize_bridge(window, ready)
        self.assertEqual(len(scripts), 1)
        self.assertIn('window.pywebview', scripts[0])
        self.assertEqual(callbacks, ['desktop'])
        self.assertTrue(window.ready)

    def test_queue_failure_does_not_signal_ready(self):
        class View:
            def RunScriptAsync(self, script):raise RuntimeError('Renderer unavailable')
        calls=[];window=SimpleNamespace(ready=False,view=View())
        with self.assertRaisesRegex(RuntimeError,'Renderer unavailable'):
            _initialize_bridge(window,calls.append)
        self.assertFalse(window.ready)
        self.assertEqual(calls,[])
