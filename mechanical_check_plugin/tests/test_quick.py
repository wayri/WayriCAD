import sys, unittest
import hashlib
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wayricad_mechanical.quick import screen
from wayricad_mechanical.config import validate
from wayricad_mechanical.findings import finish
from wayricad_mechanical.runtime import discover
from wayricad_mechanical.runner import run

def part(ref, bounds, side='top', dnp=False):
    return dict(ref=ref,bounds_2d=bounds,side=side,dnp=dnp)

class QuickTests(unittest.TestCase):
    def test_same_side_only_and_dnp_filter(self):
        board=dict(thickness=1.6,components=[part('A',[0,0,2,2]),part('B',[1,1,3,3]),part('C',[0,0,2,2],'bottom'),part('D',[0,0,2,2],dnp=True)])
        result=screen(board,validate({'mode':'quick2d'}))
        self.assertEqual([f['refs'] for f in result['findings']],[['A','B']])
        self.assertEqual(len(result['bodies']),3)
        self.assertEqual(finish(result,validate({}))['status'],'incomplete')

    def test_clearance_and_no_false_solid_pass(self):
        board=dict(thickness=1.6,components=[part('A',[0,0,1,1]),part('B',[1.2,0,2,1])])
        result=screen(board,validate({'xy_clearance_mm':.25}))
        self.assertAlmostEqual(result['findings'][0]['measured'],.2)
        self.assertEqual(result['findings'][0]['severity'],'warning')
        board['components'][1]['bounds_2d']=[2,0,3,1]
        result=screen(board,validate({}))
        self.assertFalse(result['findings'])
        self.assertEqual(finish(result,validate({}))['status'],'incomplete')

    def test_bad_envelope_and_mode(self):
        result=screen(dict(thickness=1.6,components=[part('A',[0,0,0,1])]),validate({}))
        self.assertEqual(len(result['coverage']['gaps']),2)
        with self.assertRaises(ValueError):validate({'mode':'fake'})

    @unittest.skipUnless(discover()['kicad_python'], 'KiCad extraction runtime required')
    def test_native_pipeline_without_freecad_or_step_export(self):
        board=Path(__file__).resolve().parent/'fixtures/validation-fixture.kicad_pcb'
        before=hashlib.sha256(board.read_bytes()).hexdigest()
        runtime=discover()
        runtime.update(freecad_python=None,kicad_cli=None)
        with patch('wayricad_mechanical.runner.discover',return_value=runtime):
            result=run(board,validate({'mode':'quick2d'}))
        self.assertEqual(result['status'],'incomplete')
        self.assertEqual(len(result['bodies']),6)
        self.assertEqual(result['board']['model_map'],{})
        self.assertEqual(before,hashlib.sha256(board.read_bytes()).hexdigest())
