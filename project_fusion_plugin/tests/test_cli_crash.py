import importlib
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_cli_crash_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
module=importlib.import_module(PACKAGE+'.netlist')

class CrashDiagnosticsTests(unittest.TestCase):
    def test_windows_access_violation_is_actionable_and_remains_failure(self):
        for code in (3221225477,-1073741819):
            cli=module.KiCadCLI.__new__(module.KiCadCLI);cli.path=Path('kicad-cli.exe');cli.commands=[]
            with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=code,stdout='',stderr='')):
                with self.assertRaisesRegex(module.MergeError,'access violation 0xC0000005'):
                    cli.run(['version'])
            self.assertEqual(cli.commands[-1]['returncode'],code)

if __name__=='__main__':unittest.main()
