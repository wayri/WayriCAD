"""Opt-in CLI preview/apply against real saved KiCad variant fixtures."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from test_variant_destination import PACKAGE, m, sch, sx, sections


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_CLI') == '1', 'Opt-in native KiCad CLI workflow')
class NativeCliTests(unittest.TestCase):
    def test_named_variant_import_plan_applies_with_backup_and_source_preservation(self):
        cli = importlib.import_module(PACKAGE + '.cli')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = importlib.import_module('test_variant_destination').NativeDestinationTests()
            source, _ = fixture.fixture(root / 'source')
            target, _ = fixture.fixture(root / 'target')
            source.variant_mode = 'merge'; source.destination_variant = 'Build'
            before = sections.fingerprint(root / 'source')
            target_default = sch.discover(m.SourceSpec(target.project, 'Before', variant='<Default>'), sch.new_uuid())
            original_value = sx.propval(target_default.symbols[0].node, 'Value')
            setup = root / 'setup.json'
            options = m.Options([source], str(root / 'unused'), saved_sources_confirmed=True,
                                acknowledge_outline_change=True)
            setup.write_text(json.dumps(options.to_dict()))
            plan = root / 'plan.json'
            arguments = ['import-preview', '--config', str(setup), '--target', target.project,
                         '--candidate', str(root / 'candidate'), '--output', str(plan)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(arguments), 0, errors.getvalue())
            self.assertEqual(sections.fingerprint(root / 'source'), before)
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(['apply', str(plan), '--apply', '--yes', '--editors-closed']),
                                 0, errors.getvalue())
            applied = json.loads(output.getvalue())
            self.assertEqual(sections.fingerprint(root / 'source'), before)
            current = sch.discover(m.SourceSpec(target.project, 'After', variant='<Default>'), sch.new_uuid())
            self.assertEqual(sx.propval(next(r for r in current.symbols if r.old_ref == 'R1').node, 'Value'),
                             original_value)
            fixture.check_states(Path(target.project), 'Build')
            backup = Path(applied['backup_directory'])
            receipt = json.loads((backup / 'transaction.json').read_text())
            self.assertTrue(receipt['completed'])
            self.assertEqual(sections.fingerprint(backup / 'project'), receipt['target_hashes'])
