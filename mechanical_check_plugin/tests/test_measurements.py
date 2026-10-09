"""Distances are measured surfaces/envelopes, never fabricated from failures."""
import copy
import hashlib
import json
import math
import random
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wayricad_mechanical.config import validate
from wayricad_mechanical.findings import bbox_distance, candidate_pairs
from wayricad_mechanical.measurement_service import MeasurementSession, fingerprint
from wayricad_mechanical.proximity import PairMeasurements, envelope_measure, exact_measure, nearest_parts
from wayricad_mechanical.quick import screen
from wayricad_mechanical.runtime import Cancelled, discover, run_process


def body(ref, x=0, y=0, side='top', kind='component'):
    z = 1.6 if side == 'top' else 0
    return dict(ref=ref, kind=kind, side=side, bounds=[x, y, z, x+1, y+1, z])


class ProximityTests(unittest.TestCase):
    def test_nearest_matches_bruteforce_random_and_dense(self):
        rng = random.Random(78)
        for spread in (2, 100):
            bodies = [body(str(i), rng.uniform(0, spread), rng.uniform(0, spread)) for i in range(120)]
            cache = PairMeasurements(envelope_measure)
            records = nearest_parts(bodies, cache)
            nearest = {ref: r for r in records for ref in r.get('nearest_for', [])}
            for b in bodies:
                expected = min(bbox_distance(b['bounds'], c['bounds']) for c in bodies if c is not b)
                self.assertAlmostEqual(nearest[b['ref']]['distance_mm'], expected)
                self.assertAlmostEqual(math.dist(*nearest[b['ref']]['points']), expected)

    def test_sparse_search_reduces_kernel_work(self):
        bodies = [body(str(i), 0, i*10) for i in range(400)]
        cache = PairMeasurements(envelope_measure)
        nearest_parts(bodies, cache)
        self.assertLess(cache.stats['distance_queries'], 4*len(bodies))
        self.assertLess(cache.stats['bbox_tests'], 50*len(bodies))
        self.assertEqual(len(list(candidate_pairs(bodies, .5))), 0)

    def test_side_and_kind_exclusions(self):
        bodies = [body('A'), body('B', x=20), body('Under', side='bottom'), body('PCB', kind='board')]
        records = nearest_parts(bodies, PairMeasurements(envelope_measure), same_side=True)
        self.assertEqual(records[0]['refs'], ['A', 'B'])
        self.assertEqual(records[0]['nearest_for'], ['A', 'B'])
        self.assertEqual(len(records), 1)

    def test_failure_cannot_claim_nearest(self):
        def measurement(a, b):
            if 'B' in (a['ref'], b['ref']):
                raise RuntimeError('kernel failed')
            return envelope_measure(a, b)
        cache = PairMeasurements(measurement)
        records = nearest_parts([body('A'), body('B', x=2), body('C', x=9)], cache)
        self.assertTrue(cache.errors)
        self.assertFalse(any(r.get('nearest_for') for r in records))
        self.assertTrue(all(r['distance_mm'] > 0 for r in records))

    def test_distance_requires_finite_value_and_witness(self):
        for result in [(float('nan'), [], None), (-1, [], None), (0, [], None), (1, [([0,0,0],[float('inf'),0,0])], None)]:
            class Shape:
                def distToShape(self, other):
                    return result
            with self.assertRaises(ValueError):
                exact_measure(dict(ref='A',shape=Shape()),dict(ref='B',shape=Shape()))

    def test_sweep_all_axes_matches_bruteforce(self):
        rng = random.Random(123)
        for axis in range(3):
            bodies = []
            for i in range(120):
                low = [rng.uniform(-2, 2) for _ in range(3)]
                low[axis] *= 50
                bodies.append(dict(ref=str(i), bounds=low+[v+rng.uniform(.1,10) for v in low]))
            expected = {frozenset((a['ref'],b['ref'])) for i,a in enumerate(bodies) for b in bodies[i+1:] if bbox_distance(a['bounds'],b['bounds']) <= 2}
            actual = {frozenset((a['ref'],b['ref'])) for a,b in candidate_pairs(bodies,2)}
            self.assertEqual(expected, actual)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)/'source.kicad_pcb'
        self.source.write_text('source',encoding='utf-8')
        self.report = dict(rules={'mode':'quick2d'}, bodies=[body('A'),body('B',x=5),body('C',x=20)], proximity=[])
        self.session = MeasurementSession()
        self.addCleanup(self.session.close)
        self.session.bind(self.report,None,{}, {str(self.source):fingerprint(self.source)})

    def test_arbitrary_pair_immutable_cache_and_stale_source(self):
        self.report['bodies'][0]['bounds'][0] = -1000
        record = self.session.measure(self.report,'A','C')
        self.assertEqual(record['distance_mm'],19)
        self.assertEqual(record['evidence'],'2D footprint envelopes')
        record['distance_mm'] = 999
        self.assertEqual(self.session.measure(self.report,'C','A')['distance_mm'],19)
        self.source.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'source changed'):
            self.session.measure(self.report,'C','A')

    def test_cancel_close_and_unknown_pair(self):
        event = threading.Event(); event.set()
        with self.assertRaises(Cancelled): self.session.measure(self.report,'A','B',event)
        with self.assertRaisesRegex(ValueError,'no usable'): self.session.measure(self.report,'A','Missing')
        root = self.session._root
        self.session.close()
        self.assertFalse(root.exists())
        with self.assertRaises(Cancelled): self.session.measure(self.report,'A','B')

    def test_close_does_not_wait_for_inflight_query_and_cleans_afterward(self):
        entered, release = threading.Event(), threading.Event()
        root = self.session._root
        outcomes = []
        def slow_measure(a, b):
            entered.set()
            release.wait(5)
            return envelope_measure(a,b)
        def query():
            try:
                self.session.measure(self.report,'A','B')
            except Cancelled:
                outcomes.append('cancelled')
        with patch('wayricad_mechanical.measurement_service.envelope_measure',side_effect=slow_measure):
            thread = threading.Thread(target=query)
            thread.start()
            self.assertTrue(entered.wait(2))
            started = time.monotonic()
            self.session.close()
            self.assertLess(time.monotonic()-started,.5)
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes,['cancelled'])
        self.assertFalse(root.exists())

    def test_imported_report_known_pair_only(self):
        report = dict(proximity=[envelope_measure(body('A'),body('B',x=4))])
        self.assertEqual(self.session.measure(report,'B','A')['distance_mm'],3)
        with self.assertRaisesRegex(RuntimeError,'Run Mechanical Check again'):
            self.session.measure(report,'A','C')


@unittest.skipUnless(discover()['freecad_python'], 'FreeCAD required')
class NativeMeasurementTests(unittest.TestCase):
    @unittest.skipUnless(all(discover().values()), 'KiCad and FreeCAD required')
    def test_full_pipeline_live_session_queries_and_private_export(self):
        from wayricad_mechanical.config import load
        from wayricad_mechanical.runner import run
        from wayricad_mechanical.report import export
        with tempfile.TemporaryDirectory() as temp:
            session = MeasurementSession()
            self.addCleanup(session.close)
            source = ROOT/'tests/fixtures/validation-fixture.kicad_pcb'
            before = fingerprint(source)
            report = run(source,load(ROOT/'tests/fixtures/fixture-rules.json'),measurement_session=session)
            self.assertEqual(before,fingerprint(source))
            self.assertTrue(session._manifest)
            with patch('wayricad_mechanical.measurement_service.run_process',wraps=run_process) as worker:
                result = session.measure(report,'PCB','C3')
                cached = session.measure(report,'C3','PCB')
            self.assertEqual(worker.call_count,1)
            self.assertEqual(result,cached)
            self.assertEqual(result['evidence'],'exact STEP surfaces')
            self.assertTrue(math.isfinite(result['distance_mm']))
            self.assertAlmostEqual(math.dist(*result['points']),result['distance_mm'],places=6)
            exported = export(report,temp)
            for extension in ('html','json'):
                text = Path(exported[extension]).read_text(encoding='utf-8')
                self.assertNotIn('_measurement_session',text)
                self.assertNotIn(str(session._root),text)
            session.close()
            self.assertFalse(session._root.exists())

    def test_actual_kernel_contact_overlap_transform_and_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Execute this focused fixture in the same isolated FreeCAD runtime as production.
            script = root/'verify.py'
            script.write_text('''import json,sys,math
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import FreeCAD as App
import Part
import Import
from wayricad_mechanical.config import validate
from wayricad_mechanical.proximity import PairMeasurements,exact_measure,nearest_parts
from wayricad_mechanical.solid_worker import analyze,box,save_measurement_shapes
from wayricad_mechanical.measurement_worker import measure
def body(ref,shape):return dict(ref=ref,shape=shape,bounds=box(shape),kind='component',side='top')
a=body('A',Part.makeBox(1,2,3))
contact=body('Contact',Part.makeBox(1,2,3,App.Vector(1,0,0)))
overlap=body('Overlap',Part.makeBox(1,2,3,App.Vector(.5,0,0)))
far=body('Far',Part.makeBox(1,2,3,App.Vector(10,0,0)))
assert exact_measure(a,contact)['distance_mm']==0
assert a['shape'].common(contact['shape']).Volume==0
assert exact_measure(a,overlap)['distance_mm']==0
assert abs(a['shape'].common(overlap['shape']).Volume-3)<1e-7
assert abs(exact_measure(a,far)['distance_mm']-9)<1e-7
rot=Part.makeBox(1,2,3)
rot.Placement=App.Placement(App.Vector(10,4,-4),App.Rotation(App.Vector(0,0,1),90))
b=body('RotatedBottom',rot)
cache=PairMeasurements(exact_measure)
bodies=[a,contact,overlap,far,b]
records=nearest_parts(bodies,cache)
for first in bodies:
 expected=min(exact_measure(first,second)['distance_mm'] for second in bodies if second is not first)
 record=next(r for r in records if first['ref'] in r.get('nearest_for',[]))
 assert abs(record['distance_mm']-expected)<1e-7
directory=Path(sys.argv[2])/'solids'
save_measurement_shapes(bodies,directory)
manifest=json.loads((directory/'manifest.json').read_text())
request=dict(refs=['A','RotatedBottom'],files=[str(directory/manifest[r]['file']) for r in ['A','RotatedBottom']],evidence=['exact STEP surfaces']*2)
result=measure(request)
assert abs(result['distance_mm']-exact_measure(a,b)['distance_mm'])<1e-7
assert abs(math.dist(*result['points'])-result['distance_mm'])<1e-7
# Independent XY/Z allowance needs a diagonal broad-phase radius; max(XY,Z)
# would discard this pair before its conservative envelope check.
doc=App.newDocument('AxisFixture')
objects=[]
for label,shape in [('TDV000001M000',Part.makeBox(1,1,1)),('TDV000002M000',Part.makeBox(1,1,1,App.Vector(1.8,0,1.8)))]:
 obj=doc.addObject('Part::Feature',label); obj.Label=label; obj.Shape=shape; objects.append(obj)
step=Path(sys.argv[2])/'axis.step'
Import.export(objects,str(step)); App.closeDocument(doc.Name)
board=dict(gaps=[],model_map={'TDV000001M000':'A','TDV000002M000':'B'},components=[dict(ref='A',side='top',smd=False),dict(ref='B',side='top',smd=False)],thickness=1.6,mounts=[],pads=[])
report=analyze(dict(board=board,config=validate(dict(clearance_mm=.1,xy_clearance_mm=1,z_clearance_mm=1)),step=str(step)))
assert any(f['rule']=='envelope.axis_clearance' for f in report['findings']),report
print(json.dumps(dict(stats=cache.stats,measurement=result)))
''', encoding='utf-8')
            run_process([discover()['freecad_python'], script, ROOT/'src',root],root/'native.log',timeout=60)
            self.assertIn('exact STEP surfaces',(root/'native.log').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()
