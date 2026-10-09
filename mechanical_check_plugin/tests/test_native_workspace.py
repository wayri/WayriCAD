"""Exercise each native GUI in a fresh KiCad Python process."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mechanical_check_plugin/src'))
from wayricad_mechanical.runtime import discover


class NativeWorkspaceTests(unittest.TestCase):
    def check_mode(self,mode):
        runtime=discover()
        if not runtime['kicad_python']:self.skipTest('KiCad Python required')
        if mode=='exact3d' and not all(runtime.values()):self.skipTest('KiCad and FreeCAD required')
        with tempfile.TemporaryDirectory() as output:
            result=subprocess.run([runtime['kicad_python'],str(ROOT/'tools/check_mechanical_workspace.py'),
                                   '--mode',mode,'--output-dir',output],cwd=ROOT,
                                  capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertTrue((Path(output)/f'{mode}-checks.json').is_file())

    def test_2d_workspace_labels_export_and_3d_setup_actions(self):self.check_mode('quick2d')

    def test_actual_step_3d_workspace_and_surface_picks(self):self.check_mode('exact3d')
