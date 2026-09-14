import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_app import validate_output, write_copy, digest
from native_runner import child_environment


class SavedCopyTests(unittest.TestCase):
    def test_never_overwrites_input_or_existing_output(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source.kicad_pcb'
            source.write_text('source')
            for output in (source, source.parent / '.' / source.name):
                with self.assertRaises(ValueError):
                    validate_output(source, output)
            other = Path(td) / 'existing.kicad_pcb'
            other.write_text('keep')
            with self.assertRaises(ValueError):
                validate_output(source, other)
            self.assertEqual(other.read_text(), 'keep')
            with self.assertRaises(ValueError):
                validate_output(source, Path(td) / 'bad.txt')

    def test_source_changes_block_copy_before_serialization(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source.kicad_pcb'
            source.write_text('source')
            stamp = digest(source)
            source.write_text('new user content')
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace(SaveBoard=lambda *_: self.fail('Must not serialize'))}):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    write_copy(None, source, Path(td) / 'copy.kicad_pcb', stamp)
            self.assertEqual(source.read_text(), 'new user content')

    def test_copy_and_output_race_preserve_user_files(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source.kicad_pcb'
            source.write_text('source')
            output = Path(td) / 'copy.kicad_pcb'
            def save(path, _board):
                Path(path).write_text('balanced')
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace(SaveBoard=save)}):
                write_copy(None, source, output, digest(source))
            self.assertEqual(output.read_text(), 'balanced')
            self.assertEqual(source.read_text(), 'source')
            race_output = Path(td) / 'race.kicad_pcb'
            def racing_save(path, _board):
                save(path, _board)
                race_output.write_text('another process')
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace(SaveBoard=racing_save)}):
                with self.assertRaisesRegex(ValueError, 'now exists'):
                    write_copy(None, source, race_output, digest(source))
            self.assertEqual(race_output.read_text(), 'another process')

    def test_native_child_does_not_inherit_incompatible_python_paths(self):
        with patch.dict('os.environ', {'PYTHONHOME': 'other', 'PYTHONPATH': 'other', 'VIRTUAL_ENV': 'other'}):
            env = child_environment()
        self.assertFalse({'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'} & env.keys())
        self.assertEqual(env['WAYRICAD_COPPER_NO_REGISTER'], '1')

    def test_source_change_during_serialization_creates_no_output(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source.kicad_pcb'
            source.write_text('source')
            output = Path(td) / 'copy.kicad_pcb'
            def changed_source(path, _board):
                Path(path).write_text('balanced')
                source.write_text('new source')
            with patch.dict(sys.modules, {'pcbnew': SimpleNamespace(SaveBoard=changed_source)}):
                with self.assertRaisesRegex(ValueError, 'changed while saving'):
                    write_copy(None, source, output, digest(source))
            self.assertFalse(output.exists())
            self.assertEqual(source.read_text(), 'new source')


if __name__ == '__main__':
    unittest.main()
