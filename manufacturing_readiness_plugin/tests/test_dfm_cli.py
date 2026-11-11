from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import unittest
from unittest.mock import patch
from manufacturing_readiness_plugin import dfm_cli


class CLITests(unittest.TestCase):
    def run_cli(self, args):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error): code = dfm_cli.main(args)
        return code, output.getvalue(), error.getvalue()

    def test_vendor_search_is_headless_and_scoped(self):
        code, output, error = self.run_cli(['vendors', '--query', 'OSH Park', '--layers', '6'])
        self.assertEqual((code, error), (0, ''))
        rows = json.loads(output)
        self.assertTrue(rows)
        self.assertTrue(all(6 in row['process']['layers'] for row in rows))

    def test_preview_unknown_profile_reports_actionable_error(self):
        code, _, error = self.run_cli(['preview', '--profile', 'does-not-exist', '--context', '{}'])
        self.assertEqual(code, 2); self.assertIn('Unknown profile', json.loads(error)['error'])

    def test_audit_requires_explicit_quote_confirmation(self):
        with patch.object(dfm_cli, 'audit_snapshot') as audit:
            code, _, error = self.run_cli(['audit', 'board.kicad_pcb', '--profile', 'lion-mii-1oz',
                '--context', '{"board_type":"rigid","layers":2,"copper_oz":1,"copper_basis":"vendor_order_option"}'])
            self.assertEqual(code, 2); audit.assert_not_called()
            self.assertIn('confirm-process', error)

    def test_duplicate_context_keys_rejected(self):
        code, _, error = self.run_cli(['preview', '--profile', 'lion-mii-1oz', '--context', '{"layers":2,"layers":4}'])
        self.assertEqual(code, 2); self.assertIn('duplicate', error.lower())
