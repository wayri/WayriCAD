"""Portable exporter contracts: custody, bounded topology and optional launch."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime import blender_export as export
from wayricad_runtime import tool_cli


def scene():
    return {'schema': export.SCHEMA, 'tool': 'therm', 'title': 'Example', 'notes': [],
            'objects': [{'name': 'Computed field', 'vertices_mm': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                         'faces': [[0, 1, 2]], 'field': {'name': 'temperature', 'unit': 'degC',
                         'values': [None], 'frames': [{'time_s': 0, 'values': [20]},
                                                      {'time_s': .1, 'values': [35]}]}}]}


class BlenderExportTests(unittest.TestCase):
    def test_unknown_and_computed_frames_are_preserved(self):
        data = scene()
        result = export.validate_scene(data)
        self.assertEqual(result['faces'], 1)
        self.assertEqual(result['scalar_values'], 3)
        self.assertEqual(data['objects'][0]['field']['values'], [None])
        self.assertEqual(result['stored_times'], 2)

    def test_invalid_topology_frames_and_nonfinite_are_rejected(self):
        cases = []
        for face in ([0, 1, 9], [0, 0, 1], [0, 1, True]):
            data = scene();data['objects'][0]['faces'] = [face];cases.append(data)
        for values in ([1, 2], [float('nan')], [True]):
            data = scene();data['objects'][0]['field']['values'] = values;cases.append(data)
        data = scene();data['objects'][0]['field']['frames'][1]['time_s'] = 0;cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):export.validate_scene(data)

    def test_trace_event_duplicates_retained_but_backwards_times_rejected(self):
        data = {'schema': export.SCHEMA, 'objects': [], 'traces': [
            {'name': 'Load step', 'unit': 'A', 'time_s': [0, 1, 1, 2], 'values': [0, 0, 1, 1]}]}
        self.assertEqual(export.validate_scene(data)['traces'], 1)
        data['traces'][0]['time_s'][-1] = .5
        with self.assertRaises(ValueError):export.validate_scene(data)

    def test_export_is_new_data_bundle_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw);source = root / 'result.json';source.write_text('{"fixture":1}')
            before = source.read_bytes();target = root / 'export'
            with patch('wayricad_runtime.blender_adapters.normalize', return_value=scene()):
                result = export.export_result(source, target)
                self.assertEqual(result['counts']['faces'], 1)
                with self.assertRaises(ValueError):export.export_result(source, target)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual({p.name for p in target.iterdir()}, {'scene.json', 'blender_import.py', 'README.md', 'manifest.json'})
            manifest = json.loads((target / 'manifest.json').read_text())
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), digest)

    def test_stale_saved_board_fails_before_creating_destination(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw);board = root / 'board.kicad_pcb';board.write_text('changed')
            bundle = {'board_path': str(board), 'source_sha256': hashlib.sha256(b'old').hexdigest()}
            with self.assertRaisesRegex(ValueError, 'changed'):
                export.export_bundle(bundle, root / 'export')
            self.assertFalse((root / 'export').exists())

    def test_duplicate_input_keys_and_json_nonfinite_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / 'result.json'
            for payload in ('{"x":1,"x":2}', '{"x":NaN}', '[]'):
                source.write_text(payload)
                with self.assertRaises(ValueError):export.load_result(source)

    def test_nested_study_fingerprints_are_checked(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw);source = root / 'board.kicad_pcb';source.write_text('new')
            bundle = {'cases': [{'bundle': {'source_fingerprints': {
                str(source): hashlib.sha256(b'old').hexdigest()}}}]}
            with self.assertRaisesRegex(ValueError, 'changed'):
                export.export_bundle(bundle, root / 'export')
            self.assertFalse((root / 'export').exists())

    def test_result_file_change_cannot_publish_a_completed_bundle(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw);source = root / 'result.json';source.write_text('{}')
            def changed(*args, **kwargs):
                source.write_text('{"changed":true}')
                return scene()
            with patch('wayricad_runtime.blender_adapters.normalize', side_effect=changed):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    export.export_result(source, root / 'export')
            self.assertFalse((root / 'export').exists())

    def test_changed_importer_cannot_be_launched(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / 'export'
            with patch('wayricad_runtime.blender_adapters.normalize', return_value=scene()):
                export.export_bundle({}, target)
            (target / 'blender_import.py').write_text('changed')
            with patch.object(export.subprocess, 'Popen') as launch:
                with self.assertRaisesRegex(ValueError, 'changed'):export.run_blender(target)
                launch.assert_not_called()

    def test_cli_exports_without_launch_and_rejects_interactive_render(self):
        with patch('wayricad_runtime.blender_export.export_result', return_value={'directory': 'new'}) as write, \
             patch('wayricad_runtime.blender_export.run_blender') as launch:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(tool_cli.main(['blender', 'result.json', '--output', 'new']), 0)
            launch.assert_not_called();write.assert_called_once()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(tool_cli.main(['blender', 'result.json', '--output', 'new', '--render', 'new.png']), 2)


if __name__ == '__main__':unittest.main()
