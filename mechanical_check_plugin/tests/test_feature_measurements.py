"""Feature rulers keep CAD curves, volume centroids and picked points distinct."""
import copy
import json
import math
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wayricad_mechanical.feature_geometry import measurement_kind, selector
from wayricad_mechanical.measurement_service import MeasurementSession, fingerprint
from wayricad_mechanical.runtime import Cancelled, discover, run_process


class FeatureValidationTests(unittest.TestCase):
    def test_selector_rejects_invalid_and_nonfinite_geometry(self):
        for value in ({}, dict(kind='edge', ref='A', edge_index=-1),
                      dict(kind='edge', ref='A', edge_index=True),
                      dict(kind='point', ref='A', position=[0, 1]),
                      dict(kind='point', ref='A', position='123'),
                      dict(kind='point', ref='A', position=[0, True, 2]),
                      dict(kind='point', ref='A', position=[0, '1', 2]),
                      dict(kind='point', ref='A', position=[0, 1, float('nan')])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                selector(value)
        with self.assertRaises(ValueError):
            measurement_kind([dict(kind='edge'), dict(kind='center')])
        self.assertEqual(selector(dict(kind='point', ref='A', position=(1, 2.5, -3)))['position'], [1, 2.5, -3])

    def test_imported_feature_rejects_invalid_distance_witnesses_and_identity(self):
        features = [dict(kind='center', ref='A'), dict(kind='center', ref='B')]
        record = dict(type='feature_ruler', measurement_kind='center_center', features=features,
                      refs=['A', 'B'], points=[[1, 2, 3], [4, 6, 3]], distance_mm=5,
                      evidence='geometric volume centroids', unit='mm', status='measured')
        session = MeasurementSession()
        self.addCleanup(session.close)
        changes = [dict(distance_mm=value) for value in (None, -1, float('nan'), float('inf'), True, '5', 6)]
        changes += [dict(points=value) for value in (None, [], [[1,2,3]], ['123', [4,6,3]],
                    [[1,2,float('nan')],[4,6,3]], [[1,True,3],[4,6,3]], [[1,'2',3],[4,6,3]])]
        changes += [dict(refs=['A','C']), dict(unit='in'), dict(measurement_kind='edge_edge'),
                    dict(evidence=None), dict(feature_evidence='invalid')]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                session.measure_features(dict(feature_rulers=[dict(record, **changed)]), *features)

    def test_imported_feature_replay_is_separate_from_part_gap(self):
        features = [dict(kind='center', ref='A'), dict(kind='center', ref='B')]
        record = dict(type='feature_ruler', measurement_kind='center_center', features=features,
                      refs=['A', 'B'], points=[[1, 2, 3], [4, 6, 3]], distance_mm=5,
                      evidence='geometric volume centroids', unit='mm', status='measured')
        report = dict(feature_rulers=[record], measurements=[record])
        session = MeasurementSession()
        self.addCleanup(session.close)
        reverse = session.measure_features(report, *reversed(features))
        self.assertEqual(reverse['points'], list(reversed(record['points'])))
        self.assertEqual(reverse['features'], list(reversed(features)))
        reverse['distance_mm'] = 999
        self.assertEqual(session.measure_features(report, *features)['distance_mm'], 5)
        with self.assertRaisesRegex(RuntimeError, 'Live query geometry'):
            session.measure(report, 'A', 'B')
        with self.assertRaisesRegex(RuntimeError, 'Live feature geometry'):
            session.measure_features(report, features[0], dict(kind='center', ref='C'))


FIXTURE_SCRIPT = '''import json,sys,math
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import FreeCAD as App
import Part
from wayricad_mechanical.feature_geometry import inspect_shape,measure_features
from wayricad_mechanical.solid_worker import box,save_measurement_shapes
from wayricad_mechanical.measurement_worker import measure
root=Path(sys.argv[2])
def body(ref,shape): return dict(ref=ref,shape=shape,bounds=box(shape),kind='component',side='top')
a=Part.makeBox(2,4,6)
b=Part.makeBox(2,4,6)
b.Placement=App.Placement(App.Vector(10,20,-5),App.Rotation(App.Vector(0,0,1),90))
# Unequal disjoint volumes: centroid x=(1*0.5+8*11)/9, never bounding-box midpoint.
c=Part.makeCompound([Part.makeBox(1,1,1),Part.makeBox(2,2,2,App.Vector(10,0,0))])
c.Placement=App.Placement(App.Vector(3,5,7),App.Rotation(App.Vector(0,0,1),90))
cylinder=Part.makeCylinder(5,2)
bodies=[body('A',a),body('B',b),body('C',c),body('Circle',cylinder)]
save_measurement_shapes(bodies,root/'solids')
assert bodies[0]['inspection']['status']=='available',bodies[0]['inspection']
assert bodies[0]['inspection']['dimensions_mm']==[2,4,6]
assert bodies[0]['inspection']['center_mm']==[1,2,3]
assert all(abs(x-y)<1e-7 for x,y in zip(bodies[1]['inspection']['center_mm'],[8,21,-2]))
assert all(abs(x-y)<1e-7 for x,y in zip(bodies[1]['inspection']['dimensions_mm'],[4,2,6]))
assert all(abs(x-y)<1e-7 for x,y in zip(bodies[2]['inspection']['center_mm'],[3-8.5/9,5+88.5/9,7+8.5/9]))
assert abs(bodies[2]['inspection']['volume_mm3']-9)<1e-7
manifest=json.loads((root/'solids/manifest.json').read_text())
for body_item in bodies:
 shape=Part.Shape();shape.read(str(root/'solids'/manifest[body_item['ref']]['file']))
 assert len(shape.Edges)==body_item['inspection']['edge_count']
 for item,edge in zip(body_item['inspection']['edges'],shape.Edges):
  assert abs(item['length_mm']-edge.Length)<1e-7
  assert math.dist(item['points'][0],list(edge.valueAt(edge.FirstParameter)))<1e-7
circle=next(item for item in bodies[3]['inspection']['edges'] if item['curve']=='Circle')
z=circle['points'][0][2]
edge=dict(kind='edge',ref='Circle',edge_index=circle['index'])
point=dict(kind='point',ref='Circle',position=[0,0,z+3])
def query(first,second):
 refs=[first['ref'],second['ref']]
 return measure(dict(operation='features',features=[first,second],refs=refs,files=[str(root/'solids'/manifest[r]['file']) for r in refs],evidence=['exact STEP surfaces']*2))
# Opposite parallel vertical box edges have an independent sqrt(2^2+4^2) gap.
vertical=[item for item in bodies[0]['inspection']['edges'] if abs(item['length_mm']-6)<1e-7]
left=next(item for item in vertical if abs(item['points'][0][0])+abs(item['points'][0][1])<1e-7)
right=next(item for item in vertical if abs(item['points'][0][0]-2)+abs(item['points'][0][1]-4)<1e-7)
record=query(dict(kind='edge',ref='A',edge_index=left['index']),dict(kind='edge',ref='A',edge_index=right['index']))
assert abs(record['distance_mm']-math.sqrt(20))<1e-7
assert query(edge,edge)['distance_mm']==0
try: query(edge,dict(edge,edge_index=999999))
except ValueError: pass
else: raise AssertionError('Invalid BREP edge index accepted')
record=query(point,edge)
assert abs(record['distance_mm']-math.sqrt(34))<1e-7
assert abs(math.dist(*record['points'])-record['distance_mm'])<1e-7
assert 'exact CAD edge curve' in record['evidence']
# Circular edges at z=0 and z=2 retain their analytic, curved geometry.
circles=[item for item in bodies[3]['inspection']['edges'] if item['curve']=='Circle']
record=query(edge,dict(kind='edge',ref='Circle',edge_index=circles[1]['index']))
assert abs(record['distance_mm']-2)<1e-7
# General curved B-spline also uses the curve kernel rather than display segments.
curve=Part.BSplineCurve();curve.interpolate([App.Vector(0,0,0),App.Vector(1,3,0),App.Vector(4,2,0)])
spline=curve.toShape();raised=spline.copy();raised.translate(App.Vector(0,0,7))
record=measure_features([dict(kind='edge',ref='X',edge_index=0),dict(kind='edge',ref='Y',edge_index=0)],
 [Part.makeCompound([spline]),Part.makeCompound([raised])],['exact STEP surfaces']*2)
assert abs(record['distance_mm']-7)<1e-7
limited=inspect_shape(cylinder,[2])
assert len(limited['edges'])==len(cylinder.Edges)
assert any(item['status']=='unavailable' and item['reason'] for item in limited['edges'])
duplicates=[body('D',a),body('D',b)]
save_measurement_shapes(duplicates,root/'duplicates')
assert all(item['inspection']['status']=='unavailable' for item in duplicates)
(root/'fixture.json').write_text(json.dumps(dict(rules=dict(mode='exact3d'),bodies=[{k:v for k,v in item.items() if k!='shape'} for item in bodies],proximity=[],edge=edge,point=point)))
print('Native analytical feature checks passed; FreeCAD '+'.'.join(App.Version()[:3]))
'''


@unittest.skipUnless(discover()['freecad_python'], 'FreeCAD required')
class NativeFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.runtime = discover()
        script = cls.root / 'fixture.py'
        script.write_text(FIXTURE_SCRIPT, encoding='utf-8')
        run_process([cls.runtime['freecad_python'], script, ROOT/'src', cls.root], cls.root/'fixture.log', timeout=60)
        cls.original = json.loads((cls.root/'fixture.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.source = self.root/'source.kicad_pcb'
        self.source.write_text('immutable source', encoding='utf-8')
        self.before = fingerprint(self.source)
        self.report = copy.deepcopy(self.original)
        self.session = MeasurementSession()
        self.addCleanup(self.session.close)
        self.session.bind(self.report, self.root/'solids', self.runtime, {str(self.source): self.before})

    def test_actual_curve_measurement_cache_and_immutability(self):
        point, edge = self.report['point'], self.report['edge']
        with patch('wayricad_mechanical.measurement_service.run_process', wraps=run_process) as worker:
            first = self.session.measure_features(self.report, point, edge)
            self.assertEqual(first['measurement_kind'], 'point_edge')
            self.assertAlmostEqual(first['distance_mm'], math.sqrt(34))
            first['points'][0][0] = 999
            cached = self.session.measure_features(self.report, point, edge)
            self.assertNotEqual(cached['points'][0][0], 999)
            self.assertEqual(worker.call_count, 1)
        self.assertEqual(fingerprint(self.source), self.before)
        self.assertFalse(self.session._records)
        # Integrity is checked even when a successful feature reading is cached.
        entry = self.session._manifest['Circle']
        (self.session._root/'solids'/entry['file']).write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'source changed'):
            self.session.measure_features(self.report, point, edge)

    def test_centers_points_and_ordered_witnesses(self):
        result = self.session.measure_features(self.report, dict(kind='center', ref='A'), dict(kind='center', ref='B'))
        self.assertAlmostEqual(result['distance_mm'], math.sqrt(435))
        self.assertEqual(result['measurement_kind'], 'center_center')
        self.assertIn('not mass', result['evidence'])
        for got, expected in zip(result['points'], ([1,2,3], [8,21,-2])):
            for value, wanted in zip(got, expected): self.assertAlmostEqual(value, wanted)
        points = [dict(kind='point', ref='A', position=[1,2,3]), dict(kind='point', ref='B', position=[4,6,3])]
        result = self.session.measure_features(self.report, *points)
        self.assertEqual(result['distance_mm'], 5)
        self.assertEqual(result['measurement_kind'], 'point_point')
        self.assertIn('display approximation', result['evidence'])

    def test_missing_old_2d_cancelled_and_stale_inputs_rejected(self):
        point, edge = self.report['point'], self.report['edge']
        for bad in (dict(edge, ref='Missing'), dict(edge, edge_index=9999)):
            with self.assertRaises(ValueError): self.session.measure_features(self.report, point, bad)
        event = threading.Event(); event.set()
        with self.assertRaises(Cancelled): self.session.measure_features(self.report, point, edge, event)
        self.session._inspection['Circle'] = {}
        with self.assertRaisesRegex(ValueError, 'inspection'): self.session.measure_features(self.report, point, edge)
        self.session._mode = 'quick2d'
        with self.assertRaisesRegex(ValueError, 'Exact 3D'): self.session.measure_features(self.report, point, edge)
        self.source.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'source changed'): self.session.measure_features(self.report, point, edge)

    def test_sources_and_cache_rechecked_after_real_kernel_worker(self):
        original = run_process
        for change in ('source', 'cache', 'cancel'):
            with self.subTest(change=change):
                self.source.write_text('immutable source', encoding='utf-8')
                self.session.bind(self.report, self.root/'solids', self.runtime, {str(self.source): self.before})
                event = threading.Event()
                def changed(*args, **kwargs):
                    original(*args, **kwargs)
                    if change == 'source': self.source.write_text('changed', encoding='utf-8')
                    elif change == 'cache':
                        entry = self.session._manifest['Circle']
                        (self.session._root/'solids'/entry['file']).write_text('changed', encoding='utf-8')
                    else: event.set()
                with patch('wayricad_mechanical.measurement_service.run_process', side_effect=changed):
                    with self.assertRaises(Cancelled if change == 'cancel' else RuntimeError):
                        self.session.measure_features(self.report, self.report['point'], self.report['edge'], event)
                self.assertFalse(self.session._feature_records)

    def test_close_during_worker_discards_result_and_cleans_geometry(self):
        root = self.session._root
        def closed(*args, **kwargs):
            run_process(*args, **kwargs)
            self.session.close()
        with patch('wayricad_mechanical.measurement_service.run_process', side_effect=closed):
            with self.assertRaises(Cancelled):
                self.session.measure_features(self.report, self.report['point'], self.report['edge'])
        self.assertFalse(root.exists())
        self.assertFalse(self.session._feature_records)


if __name__ == '__main__': unittest.main()
