import csv
import json
import math
import random
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wayricad_mechanical.config import load, validate, mount_defaults
from wayricad_mechanical.findings import bbox_distance, candidate_pairs, finding, finish
from wayricad_mechanical.extract import resolve_model
from wayricad_mechanical.report import export


class RulesTests(unittest.TestCase):
    def test_nonfinite_and_negative_values_rejected(self):
        for value in [-1,float('nan'),float('inf'),True,'2']:
            with self.subTest(value=value), self.assertRaises(ValueError):validate({'clearance_mm':value})

    def test_unknown_keys_rejected(self):
        with self.assertRaises(ValueError):validate({'clearnce_mm':.1})

    def test_mount_plating_bidirectional_intent(self):
        for plating in ['PTH','NPTH','either']:
            c=load();m=mount_defaults();m['expected_plating']=plating;c['mounts']['H1']=m
            self.assertEqual(validate(c)['mounts']['H1']['expected_plating'],plating)

    def test_invalid_zone_bounds(self):
        with self.assertRaises(ValueError):validate({'keepouts':[{'bounds':[0,0,0,-1,2,3]}]})

    def test_defaults_not_shared(self):
        a,b=load(),load();a['mounts']['H1']=mount_defaults();self.assertFalse(b['mounts'])

    def test_blank_waivers_rejected(self):
        with self.assertRaises(ValueError):validate({'waivers':{'id':' '}})


class GeometryTests(unittest.TestCase):
    def test_sweep_preserves_all_near_pairs(self):
        rng=random.Random(19)
        bodies=[]
        for i in range(150):
            a=[rng.uniform(-10,10) for _ in range(3)]
            bodies.append(dict(ref=str(i),bounds=a+[v+rng.uniform(.1,3) for v in a]))
        expected={frozenset([a['ref'],b['ref']]) for i,a in enumerate(bodies) for b in bodies[i+1:] if bbox_distance(a['bounds'],b['bounds'])<=.75}
        found={frozenset([a['ref'],b['ref']]) for a,b in candidate_pairs(bodies,.75)}
        self.assertEqual(expected,found)

    def test_touch_is_candidate_at_zero_margin(self):
        bodies=[dict(ref='A',bounds=[0,0,0,1,1,1]),dict(ref='B',bounds=[1,0,0,2,1,1])]
        self.assertEqual(len(list(candidate_pairs(bodies,0))),1)

    def test_missing_geometry_never_passes_even_if_waived(self):
        f=finding('x',['U1'],'Missing','Fix')
        c=load();c['waivers'][f['id']]='Reviewed'
        report=dict(findings=[f],coverage={'gaps':['missing STEP']})
        self.assertEqual(finish(report,c)['status'],'incomplete')

    def test_review_required_for_conservative_warnings(self):
        report=dict(findings=[finding('x',['U1'],'Near','Review','conservative',severity='warning')],coverage={'gaps':[]})
        self.assertEqual(finish(report,load())['status'],'review_required')

    def test_vrml_resolves_only_real_step_sibling(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'part.wrl').write_text('vrml')
            self.assertIsNone(resolve_model('${MODELS}/part.wrl',{'MODELS':temp},temp))
            (root/'part.step').write_text('step')
            self.assertEqual(resolve_model('${MODELS}/part.wrl',{'MODELS':temp},temp),root/'part.step')


class ReportTests(unittest.TestCase):
    def test_reports_have_timestamps_and_escaped_payload(self):
        report=dict(project_name='=project </script><script>alert(1)</script>',completed_at='2026-09-14T01:02:03+00:00',
                    findings=[finding('x',['=CMD()'],'</script><script>alert(1)</script>','Fix',severity='warning')])
        report['findings'][0]['waiver']=''
        with tempfile.TemporaryDirectory() as temp:
            paths=export(report,temp);second=export(report,temp)
            self.assertNotEqual(paths['json'],second['json'])
            data=json.loads(Path(paths['json']).read_text(encoding='utf-8'))
            self.assertEqual(data,report)
            markup=Path(paths['html']).read_text(encoding='utf-8')
            self.assertNotIn('<script>alert(1)</script>',markup)
            with open(paths['csv'],encoding='utf-8-sig',newline='') as stream:
                row=next(csv.DictReader(stream));self.assertTrue(row['refs'].startswith("'="))
            datetime.fromisoformat(data['completed_at'])

if __name__=='__main__':unittest.main()

