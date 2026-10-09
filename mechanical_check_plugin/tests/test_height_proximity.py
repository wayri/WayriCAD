"""PCB-face height policy and independent soft-gap warning references."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from wayricad_mechanical.config import validate
from wayricad_mechanical.findings import maximum_height_findings
from wayricad_mechanical.quick import screen
from wayricad_mechanical.report import export
from wayricad_mechanical.runtime import discover


class HeightPolicyTests(unittest.TestCase):
    def test_both_faces_include_opposite_side_protrusion_and_standoff(self):
        rules=validate({'top_height_mm':2,'bottom_height_mm':.5})
        body=dict(ref='J1',side='top',bounds=[0,0,-1,2,3,4.6])
        issues=list(maximum_height_findings(body,1.6,rules))
        self.assertEqual({issue['side'] for issue in issues},{'top','bottom'})
        self.assertEqual(len({issue['id'] for issue in issues}),2)
        top,bottom=issues
        self.assertAlmostEqual(top['measured'],3);self.assertAlmostEqual(top['excess_mm'],1)
        self.assertAlmostEqual(bottom['measured'],1);self.assertAlmostEqual(bottom['excess_mm'],.5)
        self.assertEqual(top['limit_point'],[1,1.5,3.6])
        self.assertEqual(bottom['limit_point'],[1,1.5,-.5])
        self.assertIn('not a closest-surface',top['marker_evidence'])
        self.assertIn('conservative',top['evidence'])
        self.assertEqual(issues,list(maximum_height_findings(dict(body,side='bottom'),1.6,rules)))

    def test_threshold_and_numerical_tolerance_are_not_violations(self):
        rules=validate({'top_height_mm':2,'bottom_height_mm':.5})
        body=dict(ref='A',bounds=[0,0,-.5,1,1,3.6])
        self.assertFalse(list(maximum_height_findings(body,1.6,rules)))
        body['bounds'][5]+=5e-8
        self.assertFalse(list(maximum_height_findings(body,1.6,rules)))
        body['bounds'][5]+=2e-7
        self.assertEqual(len(list(maximum_height_findings(body,1.6,rules))),1)
        self.assertEqual(len(list(maximum_height_findings(body,1.6,validate({'top_height_mm':0,'bottom_height_mm':0})))),2)

    def test_limits_validate_and_old_rules_leave_optional_warning_off(self):
        self.assertEqual(validate({})['proximity_warning_mm'],0)
        for key in ('top_height_mm','bottom_height_mm','proximity_warning_mm'):
            for value in (-1,float('nan'),float('inf'),True,'1',None):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate({key:value})

    def test_height_csv_preserves_side_and_excess(self):
        issue=next(maximum_height_findings(dict(ref='J1',bounds=[0,0,0,1,1,5]),1.6,validate({'top_height_mm':2})))
        with tempfile.TemporaryDirectory() as directory:
            result=export(dict(project_name='Height fixture',completed_at='2026-10-10T00:00:00Z',findings=[issue]),directory)
            with open(result['csv'],encoding='utf-8-sig',newline='') as stream:row=next(csv.DictReader(stream))
        self.assertEqual(row['side'],'top');self.assertAlmostEqual(float(row['excess_mm']),1.4)

    def test_quick_2d_warnings_are_same_side_envelopes_and_never_heights(self):
        def component(ref,x,side='top'):
            return dict(ref=ref,side=side,bounds_2d=[x,0,x+1,1],dnp=False)
        board=dict(thickness=1.6,components=[component('A',0),component('B',1.4),component('C',.9),component('D',1.4,'bottom')])
        rules=validate({'xy_clearance_mm':.25,'proximity_warning_mm':.5,'top_height_mm':0,'bottom_height_mm':0})
        findings=screen(board,rules)['findings']
        warning=next(issue for issue in findings if issue['rule']=='screen.proximity_warning')
        self.assertEqual(warning['refs'],['A','B']);self.assertAlmostEqual(warning['measured'],.4)
        self.assertIn('bounding-box',warning['evidence']);self.assertEqual(len(warning['points'][0]),2)
        self.assertFalse(any('D' in issue['refs'] or issue['rule'].startswith('height.') for issue in findings))
        for threshold in (0,.4):
            self.assertFalse(any(issue['rule']=='screen.proximity_warning' for issue in screen(board,dict(rules,proximity_warning_mm=threshold))['findings']))


@unittest.skipUnless(discover()['freecad_python'],'FreeCAD required for actual solid proximity checks')
class SolidHeightProximityTests(unittest.TestCase):
    def test_actual_step_heights_soft_gap_boundary_and_error_precedence(self):
        code=r'''
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import FreeCAD as App,Part,Import
from wayricad_mechanical.config import validate
from wayricad_mechanical.solid_worker import analyze
root=Path(sys.argv[2]);doc=App.newDocument('HeightFixture')
shapes=[('A',0,0,1.6,1),('B',1.4,0,1.6,1),('C',.9,0,1.6,1),('T',5,3,-1,5.6),('H',8,3,-.5,4.1)]
model_map={};components=[];objects=[]
for i,(ref,x,y,z,height) in enumerate(shapes):
 token=f'TDV{i:06d}M000';obj=doc.addObject('Part::Feature',token);obj.Label=token
 obj.Shape=Part.makeBox(1,1,height,App.Vector(x,y,z));objects.append(obj)
 model_map[token]=ref;components.append(dict(ref=ref,side='top',smd=False))
pcb=doc.addObject('Part::Feature','Height_PCB');pcb.Label='Height_PCB'
pcb.Shape=Part.makeBox(20,10,1.6,App.Vector(-2,-2,0));objects.append(pcb)
step=root/'fixture.step';Import.export(objects,str(step));App.closeDocument(doc.Name)
before=hashlib.sha256(step.read_bytes()).hexdigest()
board=dict(model_map=model_map,components=components,gaps=[],thickness=1.6,mounts=[],pads=[])
results=[]
for warning,clearance in ((.5,.25),(.4,.25),(0,.25),(.5,.5)):
 config=validate(dict(top_height_mm=2,bottom_height_mm=.5,proximity_warning_mm=warning,
                     clearance_mm=clearance,xy_clearance_mm=0,z_clearance_mm=0,nozzle_radius_mm=0))
 result=analyze(dict(config=config,board=board,step=str(step)))
 results.append(result['findings'])
assert hashlib.sha256(step.read_bytes()).hexdigest()==before
(root/'answer.json').write_text(json.dumps(results))
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);script=root/'check.py';script.write_text(code,encoding='utf-8')
            completed=subprocess.run([discover()['freecad_python'],str(script),str(ROOT/'src'),str(root)],capture_output=True,text=True,timeout=90)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            results=json.loads((root/'answer.json').read_text())
        heights=[issue for issue in results[0] if issue['rule']=='height.maximum']
        self.assertEqual({(tuple(issue['refs']),issue['side']) for issue in heights},{(('T',),'top'),(('T',),'bottom')})
        warnings=[issue for issue in results[0] if issue['rule']=='solid.proximity_warning']
        self.assertEqual(len(warnings),1);self.assertEqual(warnings[0]['refs'],['A','B'])
        self.assertAlmostEqual(warnings[0]['measured'],.4,places=6)
        self.assertEqual(warnings[0]['evidence'],'exact STEP surfaces')
        self.assertEqual(len(warnings[0]['points'][0]),2)
        self.assertTrue(any(issue['rule']=='solid.collision' and issue['refs']==['A','C'] for issue in results[0]))
        for findings in results[1:]:self.assertFalse(any(issue['rule']=='solid.proximity_warning' for issue in findings))
        self.assertTrue(any(issue['rule']=='solid.clearance' and issue['refs']==['A','B'] for issue in results[3]))


if __name__=='__main__':unittest.main()
