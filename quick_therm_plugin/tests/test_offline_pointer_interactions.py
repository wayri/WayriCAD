"""Offline pointer lifecycle prevents stale probes and stuck camera drags."""
import shutil
import subprocess
import unittest

from quick_therm_plugin.thermal_interactive import interactive_board_html


class OfflinePointerTests(unittest.TestCase):
    def test_pointer_cancel_leave_outside_and_right_pan(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is needed for offline JavaScript event checks")
        html = interactive_board_html({"bbox_mm": [0, 0, 10, 10], "components": []})
        handlers = html.split("function clearCursor()", 1)[1].split("draw();table();})();", 1)[0]
        script = "function clearCursor()" + handlers
        harness = r'''
const assert=require('assert');
let drag=null,removed=0,hoverCleared=0,captured=null,released=null;
const svg={setPointerCapture(id){captured=id},releasePointerCapture(id){released=id},getScreenCTM(){return {inverse(){return {}}}}};
const readout={};
const nodes={'thermal-cursor':{remove(){removed++}},'thermal-clear-probes':{},'thermal-probe-mode':{checked:false}};
const document={getElementById(id){return nodes[id]}};
class DOMPoint {constructor(x,y){this.x=x;this.y=y}matrixTransform(){return this}}
function clearHoverLabel(){hoverCleared++}
function sample(){return null}
function unproject(point){return point}
function scheduleDraw(){}
function draw(){}
let probes=[];
'''
        assertions = r'''
svg.onpointerdown({clientX:10,clientY:20,pointerId:7});
assert.equal(captured,7);assert(drag);
svg.onpointerup({clientX:10,clientY:20,pointerId:7});assert.equal(released,7);
svg.onpointercancel();assert.equal(drag,null);assert.equal(removed,1);
svg.onpointerleave();assert.equal(removed,2);assert.equal(hoverCleared,1);
svg.onpointermove({clientX:100,clientY:100,buttons:0});
assert.equal(removed,3);assert(readout.textContent.includes('Outside saved board'));
let prevented=false;svg.oncontextmenu({preventDefault(){prevented=true}});assert(prevented);
'''
        result = subprocess.run([node, "-e", harness + script + assertions],
                                stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inline_data_preserves_unknown_and_escapes_script_closure(self):
        html = interactive_board_html({"components": [
            {"reference": "</script><img src=x>", "junction_c": None}]})
        self.assertNotIn("</script><img src=x>", html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn('"junction_c":null', html)
