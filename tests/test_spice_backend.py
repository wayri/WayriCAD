import unittest
from unittest.mock import patch
import subprocess
import tempfile
from pathlib import Path
import json
from wayricad_runtime.spice_backend import _request,simulate,discover_library

DECK='Test\nV1 p 0 1\nR1 p 0 10\n.end\n'
class SpiceBackendTests(unittest.TestCase):
    def test_commands_and_bounds(self):
        r=_request(DECK,'ac',['frequency','v(p)'],10,10000,1,10)
        self.assertEqual(r['command'],'ac dec 10 10 10000')
        for fragment in ('.control\nquit\n.endc','.include secret','.shell calc','B1 p 0 V=1'):
            with self.assertRaises(ValueError):_request('Test\n'+fragment+'\n.end','op',['p'],100,None,1,None)
        with self.assertRaises(ValueError):_request(DECK,'ac',['p'],1,1e100,1,100)
        with self.assertRaises(ValueError):_request(DECK,'op',['p;quit'],1,None,1,None)
    def test_missing_library_is_actionable(self):
        with patch.dict('os.environ',{'WAYRICAD_KICAD_NGSPICE':'/does/not/exist/ngspice.dll'}):
            with self.assertRaisesRegex(RuntimeError,'WAYRICAD_KICAD_NGSPICE'):discover_library()
    def test_native_crash_and_timeout_are_contained(self):
        with patch('wayricad_runtime.spice_backend.discover_library',return_value='dummy'),patch('wayricad_runtime.runtime_setup.native_python',return_value='python'):
            with patch('wayricad_runtime.spice_backend.subprocess.run',return_value=subprocess.CompletedProcess([], -11)):
                with self.assertRaisesRegex(RuntimeError,'without results'):simulate(DECK,vectors=['p'])
            with patch('wayricad_runtime.spice_backend.subprocess.run',side_effect=subprocess.TimeoutExpired([],1)):
                with self.assertRaises(TimeoutError):simulate(DECK,vectors=['p'])
    def test_worker_error_propagates(self):
        def fake(command,**kwargs):
            Path(command[-1]).write_text(json.dumps({'error':'singular generated circuit'}))
            return subprocess.CompletedProcess(command,2)
        with patch('wayricad_runtime.spice_backend.discover_library',return_value='dummy'),patch('wayricad_runtime.runtime_setup.native_python',return_value='python'),patch('wayricad_runtime.spice_backend.subprocess.run',side_effect=fake):
            with self.assertRaisesRegex(RuntimeError,'singular generated circuit'):simulate(DECK,vectors=['p'])
    def test_active_library_and_numeric_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            for version in ('9.0','10.0'):
                lib=root/'KiCad'/version/'bin/ngspice.dll';lib.parent.mkdir(parents=True);lib.touch()
            with patch.dict('os.environ',{'ProgramFiles':str(root),'WAYRICAD_KICAD_NGSPICE':'','WAYRICAD_KICAD_PYTHON':''}),patch('wayricad_runtime.spice_backend.sys.platform','win32'):
                with patch('wayricad_runtime.runtime_setup.native_python',return_value=root/'KiCad/9.0/bin/python.exe'):
                    self.assertEqual(discover_library(),root/'KiCad/9.0/bin/ngspice.dll')
                with patch('wayricad_runtime.runtime_setup.native_python',side_effect=RuntimeError('absent')):
                    self.assertEqual(discover_library(),root/'KiCad/10.0/bin/ngspice.dll')
                with patch.dict('os.environ',{'WAYRICAD_KICAD_NGSPICE':str(root/'KiCad/9.0/bin/ngspice.dll')}):
                    self.assertEqual(discover_library(),root/'KiCad/9.0/bin/ngspice.dll')
    def test_extreme_sweep_and_directive_title_rejected(self):
        with self.assertRaises(ValueError):_request(DECK,'ac',['p'],1e-300,1e300,1,10)
        with self.assertRaises(ValueError):_request('.control\nquit\n.end','op',['p'],1,None,1,None)
    def test_transient_bounds_and_no_arbitrary_command(self):
        r=_request(DECK,'tran',['time','v(p)'],100,None,1,None,.001,.1)
        self.assertEqual(r['command'],'tran 0.001 0.1 0 0.001 uic')
        with self.assertRaises(ValueError):_request(DECK,'tran',['time'],100,None,1,None,1e-9,1.)
if __name__=='__main__':unittest.main()
