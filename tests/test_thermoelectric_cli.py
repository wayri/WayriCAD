from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime.thermoelectric_study import cli


def request():
    return dict(schema_version=1,grid=dict(edges_mm=dict(x=[0,1,2,3],y=[0,1],z=[0,1])),
                materials={'m':dict(thermal_conductivity_w_mk=10,resistivity_ohm_m=.001)},
                material_ids=['m']*3,fixed_voltage_v={'0':.1,'2':0},fixed_temperature_c={'0':20,'2':20})


class CrossToolCLITests(unittest.TestCase):
    def test_all_four_tools_share_request_identity(self):
        from heater_designer_plugin.thermal3d import main as heater
        from quick_pi_plugin.cli import main as pi
        from quick_therm_plugin.cli import main as therm
        from signal_integrity_advisor_plugin.cli import main as si
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'study.json';source.write_text(json.dumps(request()),encoding='utf-8')
            hashes=[]
            for main,prefix in [(heater,[]),(pi,['--thermoelectric-3d']),(therm,['--thermoelectric-3d']),(si,['thermal-3d'])]:
                target=Path(folder)/f'output-{len(hashes)}.json'
                with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
                    self.assertEqual(main([*prefix,str(source),'--output',str(target)]),0)
                report=json.loads(target.read_text(encoding='utf-8'))
                hashes.append(report['request_sha256'])
                self.assertTrue(report['result']['converged'])
            self.assertEqual(len(set(hashes)),1)

    def test_bad_output_rejected_before_solver(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'study.json';source.write_text(json.dumps(request()),encoding='utf-8')
            with patch('wayricad_runtime.thermoelectric_study.run_study') as solve,redirect_stderr(StringIO()):
                self.assertEqual(cli([str(source),'--output',str(source)]),2)
                solve.assert_not_called()
            self.assertEqual(json.loads(source.read_text()),request())
