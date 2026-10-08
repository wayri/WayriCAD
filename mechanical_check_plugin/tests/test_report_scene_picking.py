"""Exercise offline report picking against actual triangle and section logic."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is needed for report JavaScript checks')
class ReportScenePickingTests(unittest.TestCase):
    def test_exact_visible_hits_and_isolation(self):
        source=Path(__file__).parents[1]/'src'/'wayricad_mechanical'/'report_scene.js'
        script = """
const fs=require('fs'),vm=require('vm'),assert=require('assert');
vm.runInThisContext(fs.readFileSync(SOURCE,'utf8')+';globalThis.Scene=ConflictScene;');
const scene=Object.create(Scene.prototype);
Object.assign(scene,{report:{rules:{}},center:[0,0,1],sectionDirection:'Z',section:false,isolate:true,selected:null});
const mesh={vertices:[[0,0,0],[1,0,0],[0,1,0],[0,0,2],[1,0,2],[0,1,2]],faces:[[0,1,2],[3,4,5]]};
scene.bodies=[{ref:'U1',kind:'component',mesh}];
let hit=scene.pickRay([.25,.25,-1],[0,0,1]);assert.equal(hit.position[2],0);
scene.section=true;hit=scene.pickRay([.25,.25,-1],[0,0,1]);assert.equal(hit.position[2],2);
scene.selected={refs:['U2']};assert.equal(scene.pickRay([.25,.25,-1],[0,0,1]),null);
scene.bodies[0].kind='comparison_board';assert.equal(scene.pickRay([.25,.25,-1],[0,0,1]).reference,'U1');
assert.equal(scene.pickRay([2,2,-1],[0,0,1]),null);
""".replace('SOURCE',json.dumps(str(source)))
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
