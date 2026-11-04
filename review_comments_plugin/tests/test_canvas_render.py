import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from review_comments_plugin.canvas_render import _resolve_cli, _run, render_saved_canvas


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="80mm" viewBox="0 0 100 80"/>'


class CanvasRenderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cli = self.root / 'kicad-cli'
        self.cli.write_bytes(b'cli')

    def _render_with(self, output=None):
        def run(command, timeout, cancelled):
            target = Path(command[command.index('--output') + 1])
            if target.suffix != '.svg':
                target = target / ('Main-Child.svg' if '--pages' in command else 'page.svg')
            target.write_bytes(SVG)
            if output is not None:
                output(command)
        return patch('review_comments_plugin.canvas_render._run', side_effect=run)

    def test_board_is_private_revision_bound_snapshot(self):
        board = self.root / 'board.kicad_pcb'
        board.write_text('(kicad_pcb (version 20260206))', encoding='utf-8')
        sha = hashlib.sha256(board.read_bytes()).hexdigest()
        captured = []
        with self._render_with(captured.append):
            result = render_saved_canvas(board, cli=self.cli, layers=['F.Cu', 'Edge.Cuts'],
                                         expected_sha256=sha)
        self.assertEqual(result.svg, SVG)
        self.assertEqual(result.view_box, (0., 0., 100., 80.))
        self.assertEqual(result.source_sha256, sha)
        self.assertEqual(result.layers, ('F.Cu', 'Edge.Cuts'))
        self.assertEqual(result.coordinate_system, 'kicad-document-mm')
        self.assertIn('--mode-single', captured[0])
        self.assertIn('--exclude-drawing-sheet', captured[0])
        self.assertNotEqual(Path(captured[0][-1]), board)
        self.assertEqual(board.read_text(encoding='utf-8'), '(kicad_pcb (version 20260206))')
        self.assertFalse(any(self.root.glob('*.svg')))

    def test_cli_writes_adjacent_preferences_only_inside_private_snapshot(self):
        board = self.root / 'board.kicad_pcb'
        board.write_text('board', encoding='utf-8')
        project = board.with_suffix('.kicad_pro')
        project.write_text('{}', encoding='utf-8')
        preferences = board.with_suffix('.kicad_prl')
        preferences.write_text('preserve existing preferences', encoding='utf-8')
        def fake_cli(command, timeout, cancelled):
            private = Path(command[-1])
            self.assertNotEqual(private, board)
            self.assertEqual(private.read_bytes(), board.read_bytes())
            self.assertEqual(private.with_suffix('.kicad_pro').read_bytes(), project.read_bytes())
            private.with_suffix('.kicad_prl').write_text('CLI preference write', encoding='utf-8')
            Path(command[command.index('--output') + 1]).write_bytes(SVG)
        with patch('review_comments_plugin.canvas_render._run', side_effect=fake_cli):
            render_saved_canvas(board, cli=self.cli)
        self.assertEqual(preferences.read_text(encoding='utf-8'), 'preserve existing preferences')

    def test_originating_editor_cli_overrides_inherited_cli(self):
        client = Mock()
        client.get_kicad_binary_path.return_value = str(self.cli)
        with patch.dict(os.environ, {'KICAD_API_SOCKET': 'origin.sock', 'KICAD_API_TOKEN': 'token',
                                      'KICAD_CLI': str(self.root / 'unrelated-cli')}), \
             patch('wayricad_runtime.context.connect', return_value=client) as connect:
            self.assertEqual(_resolve_cli(None), self.cli)
        connect.assert_called_once_with()
        client.close.assert_called_once_with()
        with patch.dict(os.environ, {'KICAD_API_SOCKET': 'origin.sock', 'KICAD_API_TOKEN': 'token',
                                      'KICAD_CLI': str(self.cli)}), \
             patch('wayricad_runtime.context.connect', side_effect=RuntimeError('origin unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'origin unavailable'):
                _resolve_cli(None)

    def test_rejects_stale_expected_hash_and_mid_render_change(self):
        board = self.root / 'board.kicad_pcb'
        board.write_text('old', encoding='utf-8')
        with patch('review_comments_plugin.canvas_render._run') as runner:
            with self.assertRaisesRegex(ValueError, 'changed'):
                render_saved_canvas(board, cli=self.cli, expected_sha256='0' * 64)
            runner.assert_not_called()
        with self._render_with(lambda _: board.write_text('new', encoding='utf-8')):
            with self.assertRaisesRegex(ValueError, 'changed during rendering'):
                render_saved_canvas(board, cli=self.cli)

    def test_schematic_page_keeps_child_file_identity(self):
        root = self.root / 'Main.kicad_sch'
        child = self.root / 'Child.kicad_sch'
        root.write_text('(kicad_sch (sheet (property "Sheetfile" "Child.kicad_sch") '
                        '(property "Sheetname" "Child") '
                        '(instances (project "Main" (path "/abc" (page "2"))))))', encoding='utf-8')
        child.write_text('(kicad_sch)', encoding='utf-8')
        captured = []
        with self._render_with(captured.append):
            result = render_saved_canvas(root, cli=self.cli, sheet='2')
        self.assertEqual(result.source_path, str(child))
        self.assertEqual(result.root_path, str(root))
        self.assertEqual(result.source_sha256, hashlib.sha256(child.read_bytes()).hexdigest())
        self.assertEqual(result.sheet, '2')
        self.assertEqual(captured[0][captured[0].index('--pages') + 1], '2')

    def test_rejects_ambiguous_schematic_export(self):
        root = self.root / 'Main.kicad_sch'
        root.write_text('(kicad_sch)', encoding='utf-8')
        def emit_two(command, timeout, cancelled):
            directory = Path(command[command.index('--output') + 1])
            (directory / 'first.svg').write_bytes(SVG)
            (directory / 'second.svg').write_bytes(SVG)
        with patch('review_comments_plugin.canvas_render._run', side_effect=emit_two):
            with self.assertRaisesRegex(ValueError, 'uniquely'):
                render_saved_canvas(root, cli=self.cli)

    def test_multi_page_schematic_picks_exact_root_file(self):
        root = self.root / 'Main.kicad_sch'
        root.write_text('(kicad_sch)', encoding='utf-8')
        def emit_pages(command, timeout, cancelled):
            directory = Path(command[command.index('--output') + 1])
            (directory / 'Main.svg').write_bytes(SVG)
            (directory / 'Main-Child.svg').write_bytes(SVG)
        with patch('review_comments_plugin.canvas_render._run', side_effect=emit_pages):
            result = render_saved_canvas(root, cli=self.cli)
        self.assertEqual(result.source_path, str(root))
        self.assertIsNone(result.sheet)

    def test_rejects_unsafe_svg_and_invalid_layer(self):
        board = self.root / 'board.kicad_pcb'
        board.write_text('board', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'layer'):
            render_saved_canvas(board, cli=self.cli, layers=['F.Cu;delete'])
        def emit_bad(command, timeout, cancelled):
            Path(command[command.index('--output') + 1]).write_bytes(
                b'<!DOCTYPE svg [<!ENTITY x "bad">]><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
        with patch('review_comments_plugin.canvas_render._run', side_effect=emit_bad):
            with self.assertRaisesRegex(ValueError, 'unsupported XML entity'):
                render_saved_canvas(board, cli=self.cli)

    def test_cancel_terminates_only_owned_cli_process(self):
        process = Mock()
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired('cli', .05), (b'', b'')]
        cancelled = iter((False, True))
        with patch('review_comments_plugin.canvas_render.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(InterruptedError, 'cancelled'):
                _run(['kicad-cli', 'pcb', 'export', 'svg'], 1, lambda: next(cancelled))
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)

    @unittest.skipUnless(os.environ.get('WAYRICAD_REVIEW_NATIVE_TEST_CLI'), 'native KiCad CLI not selected')
    def test_native_saved_fixture_smoke(self):
        repository = Path(__file__).resolve().parents[2]
        cli = os.environ['WAYRICAD_REVIEW_NATIVE_TEST_CLI']
        board = repository / 'docs/examples/pocket-kivi/example.kicad_pcb'
        pcb = render_saved_canvas(board, cli=cli, layers=['F.Cu'])
        schematic = repository / 'bom_studio_plugin/examples/vendor_splitting/BOM_Demo.kicad_sch'
        self.assertEqual(pcb.kind, 'pcb')
        self.assertEqual(pcb.view_box[:2], (0., 0.))
        board_paths = [item.attrib.get('d', '') for item in ET.fromstring(pcb.svg).iter()]
        self.assertTrue(any('M5.0000 5.0000 L25.0000 5.0000' in item for item in board_paths))
        version = subprocess.run([cli, '--version'], capture_output=True, text=True,
                                 check=True).stdout.strip()
        root_page = render_saved_canvas(schematic, cli=cli)
        self.assertEqual(root_page.source_path, str(schematic))
        if version.startswith('10.0.'):
            # KiCad 10.0.6 accepted --pages 2 but exported the root sheet.
            with self.assertRaisesRegex(ValueError, 'requested saved schematic page'):
                render_saved_canvas(schematic, cli=cli, sheet='2')
            page = render_saved_canvas(schematic.with_name('Channel.kicad_sch'), cli=cli)
        else:
            page = render_saved_canvas(schematic, cli=cli, sheet='2')
            self.assertEqual(page.source_path, str(schematic.with_name('Channel.kicad_sch')))
        self.assertEqual(page.view_box[:2], (0., 0.))
        rectangles = [item.attrib for item in ET.fromstring(page.svg).iter()
                      if item.tag.rsplit('}', 1)[-1] == 'rect']
        self.assertTrue(any(float(rect.get('x', -1)) < 50 < float(rect.get('x', -1)) + float(rect.get('width', 0))
                            and float(rect.get('y', -1)) < 50 < float(rect.get('y', -1)) + float(rect.get('height', 0))
                            for rect in rectangles))
        newer = os.environ.get('WAYRICAD_REVIEW_NATIVE_NEWER_BOARD')
        if newer:
            candidate = render_saved_canvas(newer, cli=cli, layers=['F.Cu'])
            self.assertEqual(candidate.kind, 'pcb')
            self.assertEqual(candidate.source_path, str(Path(newer).resolve()))


if __name__ == '__main__':
    unittest.main()
