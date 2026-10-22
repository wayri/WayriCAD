"""Scoped read-only MCP tool boundary tests (native worker mocked)."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from silkscreen_label_plugin.mcp_server import ReadOnlyTools, create_server


class MCPToolsTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / '.tmp-tests'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.board = self.root / 'review.kicad_pcb'
        self.board.write_text('(kicad_pcb)', encoding='utf-8')
        self.calls = []

        def worker(request):
            self.calls.append(request)
            return {'status': 'PREVIEW' if request['operation'] == 'preview' else 'AUDIT',
                    'result': 'synthetic'}
        self.tools = ReadOnlyTools(self.root, timeout=4, worker=worker)

    def test_settings_and_preview_preserve_cli_settings_contract(self):
        settings = self.tools.settings()
        self.assertFalse(settings['writes_board'])
        self.assertFalse(settings['can_apply'])
        self.assertIn('leaders', settings['settings'])
        response = self.tools.preview_board('review.kicad_pcb', {'min_width': 0.6, 'problem_only': True})
        self.assertEqual(response['status'], 'PREVIEW')
        self.assertFalse(response['writes_board'])
        self.assertFalse(response['can_apply'])
        self.assertEqual(self.calls[0]['settings'], {'min_width': 0.6, 'problem_only': True})

    def test_audit_is_read_only_and_selects_only_supported_operation(self):
        response = self.tools.audit_generated(str(self.board))
        self.assertEqual(response['status'], 'AUDIT')
        self.assertFalse(response['writes_board'])
        self.assertFalse(response['can_apply'])
        self.assertEqual(self.calls[0]['operation'], 'audit-generated')
        self.assertNotIn('apply', self.calls[0])

    def test_rejects_outside_paths_and_companion_symlink_escape(self):
        outside = Path(self.temp.name).parent / 'outside.kicad_pcb'
        outside.write_text('(kicad_pcb)', encoding='utf-8')
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        response = self.tools.preview_board(str(outside))
        self.assertEqual(response['status'], 'ERROR')
        self.assertEqual(self.calls, [])

        # Simulate a .pro/.dru symlink resolving outside without relying on
        # Windows privilege settings for creating a real symlink.
        real_resolve = Path.resolve
        def guarded_resolve(path, *args, **kwargs):
            if path == self.board.with_suffix('.kicad_pro'):
                return outside
            return real_resolve(path, *args, **kwargs)
        with patch.object(Path, 'resolve', guarded_resolve):
            response = self.tools.audit_generated(str(self.board))
        self.assertEqual(response['status'], 'ERROR')
        self.assertIn('outside', response['error'])
        self.assertEqual(self.calls, [])

    def test_rejects_non_json_and_oversized_settings(self):
        for settings in ([1, 2], {'bad': float('nan')}, {'x': 'a' * (64 * 1024)}):
            response = self.tools.preview_board(str(self.board), settings)
            self.assertEqual(response['status'], 'ERROR')
            self.assertFalse(response['writes_board'])
        self.assertEqual(self.calls, [])

    def test_native_timeout_returns_structured_error(self):
        tools = ReadOnlyTools(self.root, timeout=.02)
        with patch.object(tools, '_run_native_worker', side_effect=__import__('subprocess').TimeoutExpired('worker', .02)):
            response = tools.preview_board(str(self.board), {})
        self.assertEqual(response['status'], 'ERROR')
        self.assertIn('timed out', response['error'])

    def test_sdk_is_optional_and_registration_exposes_only_read_tools(self):
        registered = []
        class FakeServer:
            def __init__(self, *_args, **_kwargs): pass
            def tool(self):
                def register(function):
                    registered.append(function.__name__)
                    return function
                return register
        fake_module = types.ModuleType('mcp.server')
        fake_module.MCPServer = FakeServer
        with patch.dict('sys.modules', {'mcp': types.ModuleType('mcp'), 'mcp.server': fake_module}):
            server = create_server(self.root, worker=lambda request: {'status': 'PREVIEW'})
        self.assertIsInstance(server, FakeServer)
        self.assertEqual(set(registered), {'get_settings', 'preview_board', 'audit_generated'})
        self.assertNotIn('apply', registered)
        with patch.dict('sys.modules', {'mcp': None, 'mcp.server': None}):
            with self.assertRaisesRegex(RuntimeError, 'pip install "mcp>=2,<3"'):
                create_server(self.root)


if __name__ == '__main__':
    unittest.main()
