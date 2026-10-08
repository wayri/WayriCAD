"""CLI workflow coverage, unchanged-source discovery and explicit write gates."""
import contextlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_sections as sections_fixture

PACKAGE = sections_fixture.PACKAGE

cli = importlib.import_module(PACKAGE + '.cli')


class CliWorkflowTests(unittest.TestCase):
    def run_cli(self, argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = cli.main(argv)
        return status, output.getvalue(), errors.getvalue()

    def test_discovery_and_variant_listing_leave_saved_files_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            spec, sheet_path = sections_fixture.SectionTests().fixture(root)
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            status, output, errors = self.run_cli(['detect', str(root / 'child.kicad_sch')])
            self.assertEqual(status, 0, errors)
            self.assertEqual(json.loads(output)[0]['kind'], 'sheet')
            status, output, errors = self.run_cli(['sheets', spec.project])
            self.assertEqual(status, 0, errors)
            self.assertIn(sheet_path, output)
            status, output, errors = self.run_cli(['variants', spec.project])
            self.assertEqual(status, 0, errors)
            self.assertIn('<Default>', output)
            self.assertEqual(before, {path.name: path.read_bytes() for path in root.iterdir()})

    def test_apply_acknowledgements_are_required_before_reading_plan(self):
        for args in ([], ['--apply'], ['--apply', '--yes']):
            status, output, errors = self.run_cli(['apply', 'missing.json', *args])
            self.assertEqual(status, 2)
            self.assertEqual(output, '')
            self.assertIn('requires --apply --yes' if '--yes' not in args else '--editors-closed', errors)

    def test_copy_writes_require_apply_and_yes(self):
        for command in ('section-apply', 'repair-apply', 'fields-apply', 'dependencies-apply'):
            status, _, errors = self.run_cli([command, 'missing.json', '--destination', 'new-copy'])
            self.assertEqual(status, 2)
            self.assertIn('requires --apply --yes', errors)

    def test_apply_checks_materialized_originals_before_backend_dispatch(self):
        workspace = importlib.import_module(PACKAGE + '.workspace')
        insertion = importlib.import_module(PACKAGE + '.insertion')
        with mock.patch.object(cli, '_read', return_value={'selection_originals': ['guard']}), \
                mock.patch.object(workspace, 'check_originals', side_effect=cli.MergeError('Original source changed')), \
                mock.patch.object(insertion, 'apply_import') as apply:
            status, _, errors = self.run_cli(['apply', 'plan.json', '--apply', '--yes', '--editors-closed'])
            self.assertEqual(status, 2)
            self.assertIn('Original source changed', errors)
            apply.assert_not_called()

    def test_update_arguments_dispatch_all_layout_retention_options(self):
        linked = importlib.import_module(PACKAGE + '.linked_updates')
        with mock.patch.object(linked, 'preview_update', return_value={'report': {}}) as preview:
            status, _, errors = self.run_cli(['update-preview', '--target', 'target.kicad_pro',
                '--candidate', 'review', '--link', 'one', '--link', 'two', '--retain-layout',
                '--layout-only', '--acknowledge-major'])
            self.assertEqual(status, 0, errors)
            self.assertEqual(preview.call_args.args[:3], ('target.kicad_pro', ['one', 'two'], 'review'))
            self.assertTrue(preview.call_args.kwargs['retain_destination_layout'])
            self.assertTrue(preview.call_args.kwargs['layout_only'])
            self.assertTrue(preview.call_args.kwargs['acknowledge_major'])

    def test_plan_export_does_not_modify_candidate_or_replace_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); candidate = root / 'candidate'; candidate.mkdir()
            with self.assertRaises(cli.MergeError):
                cli._emit({'candidate_directory': str(candidate)}, candidate / 'plan.json')
            path = root / 'plan.json'; path.write_text('existing')
            with self.assertRaises(FileExistsError):
                cli._emit({}, path)
            self.assertEqual(path.read_text(), 'existing')

    def test_every_saved_file_command_has_help(self):
        parser = cli._parser()
        subcommands = next(action for action in parser._actions if isinstance(action, cli.argparse._SubParsersAction)).choices
        self.assertEqual(len(subcommands), 26)
        for name in subcommands:
            with self.subTest(command=name), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    cli.main([name, '--help'])
                self.assertEqual(result.exception.code, 0)

    def test_field_apply_refuses_changed_source_before_materialization(self):
        repair = importlib.import_module(PACKAGE + '.repair')
        plan = {'cli_operation': 'fields', 'hashes': {'source': {'file': 'old'}},
                'file_hashes': {}, 'specs': [], 'changes': []}
        with mock.patch.object(cli, '_read', return_value=plan), \
                mock.patch.object(repair, 'fingerprint', return_value={'file': 'new'}), \
                mock.patch.object(cli, '_field_sources') as sources:
            status, _, errors = self.run_cli(['fields-apply', 'plan.json', '--destination', 'copy', '--apply', '--yes'])
            self.assertEqual(status, 2)
            self.assertIn('Source changed', errors)
            sources.assert_not_called()

    def test_field_preview_keeps_identity_and_rejects_structural_edits(self):
        fields = importlib.import_module(PACKAGE + '.bom_fields')
        row = {'identity': ['Source', '/root', 'symbol'], 'fields': {'Value': '10k', 'Reference': 'R1'}}
        from types import SimpleNamespace
        options = SimpleNamespace(sources=[])
        for edits, expected in (({'Value': '22k'}, 0), ({'Footprint': 'New:Part'}, 2)):
            with self.subTest(edits=edits), \
                    mock.patch.object(cli, '_options', return_value=(options, {})), \
                    mock.patch.object(cli, '_field_sources', return_value=[]), \
                    mock.patch.object(fields, 'inventory', return_value=[row]), \
                    mock.patch.object(cli, '_read', return_value={'identities': [row['identity']], 'edits': edits}):
                status, output, errors = self.run_cli(['fields-preview', '--config', 'setup.json', '--edits', 'edits.json'])
                self.assertEqual(status, expected, errors)
                if expected == 0:
                    change = json.loads(output)['changes'][0]
                    self.assertEqual(change['identity'], row['identity'])
                    self.assertEqual(change['before']['Value'], '10k')
                    self.assertEqual(change['after']['Value'], '22k')
                else:
                    self.assertIn('structural fields', errors)

    def test_legacy_config_keeps_analysis_and_merge_dispatch(self):
        with mock.patch.object(cli, '_new_project', return_value={'report': {}}) as run:
            self.assertEqual(self.run_cli(['--config', 'setup.json', '--analyse'])[0], 0)
            self.assertTrue(run.call_args.args[1])
            self.assertEqual(self.run_cli(['--config', 'setup.json'])[0], 0)
            self.assertFalse(run.call_args.args[1])

    def test_existing_target_setup_cannot_be_used_to_create_new_project(self):
        with mock.patch.object(cli, '_options', return_value=(None, {'import_into_existing': True})):
            # Supply the source runtime override expected before scope dispatch.
            status, _, errors = self.run_cli(['create', '--config', 'setup.json', '--apply', '--yes'])
            self.assertEqual(status, 2)
            self.assertIn('use import-preview', errors)


if __name__ == '__main__':
    unittest.main()
