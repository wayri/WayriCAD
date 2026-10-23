"""Suite-wide command discovery, argument custody and JSON-only analysis dispatch."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wayricad_runtime import tool_cli,control_cli


class ToolCLITests(unittest.TestCase):
    def test_catalogue_covers_every_registered_plugin(self):
        from extract_pins_plugin.automation import PLUGIN_CAPABILITIES
        self.assertEqual(set(tool_cli.COMMANDS),{row[0] for row in PLUGIN_CAPABILITIES})
        self.assertEqual(len(tool_cli.catalogue()['tools']),24)

    def test_alias_and_fixed_module_dispatch_preserve_literal_arguments(self):
        self.assertEqual(tool_cli.command('coordinator', ['--help']),
                         [str(tool_cli.sys.executable), '-m', 'wayricad_runtime.assistant', '--help'])
        arguments=['screen','a board.kicad_pcb','--net','V;$(ignored)']
        cmd=tool_cli.command('quick-si',arguments,'a python.exe')
        self.assertEqual(cmd,['a python.exe','-m','signal_integrity_advisor_plugin.cli',*arguments])
        self.assertEqual(tool_cli.command('fanout-generator',['settings'])[-2:],['fanout','settings'])
        with self.assertRaises(ValueError):tool_cli.command('os',['-c','anything'])

    def test_dispatch_uses_no_shell_and_retains_backend_exit(self):
        with patch.object(tool_cli.subprocess,'run') as run:
            run.return_value.returncode=4
            self.assertEqual(tool_cli.main(['run','quick-pi','--','--verify']),4)
            self.assertNotIn('shell',run.call_args.kwargs)
            self.assertEqual(run.call_args.args[0][-1],'--verify')

    def test_doctor_reports_runtime_without_loading_plugins(self):
        with patch.object(tool_cli.subprocess,'run') as run:
            run.return_value.returncode=0;run.return_value.stdout='{"python":"3.11","modules":{"pcbnew":true}}'
            self.assertTrue(tool_cli.runtime_check('python')['modules']['pcbnew'])
            self.assertNotIn('import pcbnew',run.call_args.args[0][-1])

    def test_control_preview_writes_new_result_and_keeps_request(self):
        with tempfile.TemporaryDirectory() as raw:
            request=Path(raw)/'params.json';output=Path(raw)/'result.json'
            request.write_text('{"pattern":"R*","replacement":"X*","values":["R1","C1"]}')
            before=request.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                code=control_cli.main(['bulk-label-editor','--request',str(request),'--output',str(output)])
            self.assertEqual(code,0);self.assertEqual(request.read_bytes(),before)
            self.assertEqual(json.loads(output.read_text())['result']['changes'],[{'current':'R1','new':'X1'}])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(control_cli.main(['bulk-label-editor','--request',str(request),'--output',str(output)]),2)

    def test_control_rejects_duplicate_keys_and_source_overwrite(self):
        with tempfile.TemporaryDirectory() as raw:
            request=Path(raw)/'input.json';request.write_text('{"pattern":"x","pattern":"y"}')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(control_cli.main(['bulk-label-editor','--request',str(request)]),2)
                self.assertEqual(control_cli.main(['bulk-label-editor','--request',str(request),'--output',str(request)]),2)

if __name__=='__main__':unittest.main()
