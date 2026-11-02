"""Execute exported thermal controls and field textures without a browser runtime."""
import json
import re
import shutil
import subprocess
import unittest

from quick_therm_plugin.thermal_interactive import interactive_board_html


VIEW = {'bbox_mm': [0, 0, 6, 4],
        'outline': [{'outer_mm': [[0, 0], [6, 0], [6, 4], [0, 4]],
                     'holes_mm': [[[2.8, 1.8], [3.2, 1.8], [3.2, 2.2], [2.8, 2.2]]]}],
        'drills': [{'contour_mm': [[.2, .2], [.8, .2], [.8, .8], [.2, .8]],
                    'size_mm': [.6, .6], 'kind': 'npth'}],
        'components': [{'reference': 'U1', 'id': 'u1', 'position_mm': [1, 1],
                        'bbox_mm': [.9, .9, 1.1, 1.1], 'side': 'top',
                        'junction_c': 900, 'power_w': 1, 'in_scope': True, 'issues': []}]}
FIELD = {'name': 'F.Cu', 'value_location': 'finite_volume_cell',
         'x_centers_mm': [1, 3, 5], 'y_centers_mm': [1, 3],
         'x_edges_mm': [0, 2, 4, 6], 'y_edges_mm': [0, 2, 4],
         'values_c': [[20, 30, 40], [40, 50, 60]]}


HARNESS = r'''
const assert=require('node:assert/strict');
let canvasCount=0;
const controls={};
class Element {
 constructor(name){this.name=name;this.children=[];this.attributes={};this.style={};this.classList={toggle(){}};this.checked=false;this.value='';this.textContent='';}
 setAttribute(k,v){this.attributes[k]=String(v);if(k==='id')controls[v]=this;}
 appendChild(child){child.parent=this;this.children.push(child);return child;}
 append(child){return this.appendChild(child)}
 replaceChildren(...children){this.children=[];children.forEach(child=>this.appendChild(child));}
 insertBefore(child,other){child.remove();const i=this.children.indexOf(other);child.parent=this;this.children.splice(Math.max(0,i),0,child);}
 remove(){if(this.parent){const i=this.parent.children.indexOf(this);if(i>=0)this.parent.children.splice(i,1);}}
 getContext(){return {createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData:p=>{this.pixels=p.data}};}
 toDataURL(){canvasCount++;return 'data:image/png;base64,test-'+canvasCount;}
}
for(const id of ['thermal-board-data','thermal-board','thermal-readout','thermal-time','thermal-field','thermal-field-style','thermal-overlay','thermal-field-scale','thermal-field-meaning','thermal-play','thermal-scrub','thermal-clock','thermal-speed','thermal-playback','thermal-previous','thermal-next','thermal-clear-probes','thermal-probe-mode','thermal-fit'])controls[id]=new Element(id);
controls['thermal-time'].value='-1';controls['thermal-field'].value='auto';controls['thermal-field-style'].value='smooth';controls['thermal-overlay'].checked=true;controls['thermal-speed'].value='1';
const body=new Element('tbody');
const document={getElementById:id=>controls[id]||null,querySelector:s=>s==='#thermal-part-table tbody'?body:null,querySelectorAll:()=>[],createElement:name=>new Element(name),createElementNS:(_ns,name)=>new Element(name),addEventListener(){}};
let requested=0;
function requestAnimationFrame(){return ++requested}
function cancelAnimationFrame(){}
const performance={now:()=>0};
'''


class SavedFieldGradientTests(unittest.TestCase):
    def run_document(self, view, network, assertions):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is needed to exercise exported thermal controls')
        html = interactive_board_html(view, network)
        payload = re.search(r'<script type="application/json" id="thermal-board-data">(.*?)</script>', html, re.S).group(1)
        script = re.findall(r'<script>(.*?)</script>', html, re.S)[0]
        script = script.replace('draw();table();})();',
                                'draw();table();globalThis.thermalTest={draw,field,fieldScale,sample,project,setSide:value=>{side=value},cache:()=>fieldCache};})();')
        code = HARNESS + '\ncontrols["thermal-board-data"].textContent=' + json.dumps(payload) + ';\n' + script + '\n' + assertions
        completed = subprocess.run([node, '-'], input=code,
                                   capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_smooth_texture_palette_scale_camera_cache_and_raw_probe(self):
        self.run_document(VIEW, {'board_field': FIELD}, r'''
const image=controls['thermal-board'].children.flatMap(x=>x.children).find(x=>x.name==='image');
assert(image,'continuous field is rendered as an image');assert.equal(image.parent.attributes.mask,'url(#thermal-board-mask)');
assert.equal(image.attributes['preserveAspectRatio'],'none');assert.match(image.attributes.transform,/^matrix\(/);
assert.deepEqual(thermalTest.fieldScale(thermalTest.field()),[20,60],'hotter component cannot change board field scale');
const colors=new Set(),raster=thermalTest.cache().raster;
for(let i=0;i<raster.pixels.length;i+=4)if(raster.pixels[i+3])colors.add(Array.from(raster.pixels.slice(i,i+3)).join(','));
assert(colors.size>100,'smooth image contains colors between raw cell values');
assert.equal(thermalTest.sample([1.5,1.5]).t,20,'probe remains the raw saved cell value');
assert.equal(thermalTest.sample([3,2]),null,'cutout is not probed');assert.equal(thermalTest.sample([.5,.5]),null,'drill is not probed');
const first=canvasCount;thermalTest.draw();thermalTest.setSide('3d');thermalTest.draw();assert.equal(canvasCount,first,'camera changes reuse one texture');
controls['thermal-field-style'].value='cells';controls['thermal-field-style'].onchange();assert.equal(canvasCount,first+1);assert.match(controls['thermal-field-scale'].textContent,/Solver cells/);
const flat=new Set(),pixels=thermalTest.cache().raster.pixels;for(let i=0;i<pixels.length;i+=4)if(pixels[i+3])flat.add(Array.from(pixels.slice(i,i+3)).join(','));assert.equal(flat.size,5,'raw cell display remains available');
''')

    def test_unknown_cells_and_point_support_remain_unpainted(self):
        partial = {**FIELD, 'values_c': [[20, None, 40], [None, None, None]]}
        self.run_document(VIEW, {'board_field': partial}, r'''
const raster=thermalTest.cache().raster;
const alphaAt=(x,y)=>raster.pixels[(Math.floor(y/raster.bounds[3]*raster.height)*raster.width+Math.floor(x/raster.bounds[2]*raster.width))*4+3];
assert.equal(alphaAt(3,1),0);assert.equal(thermalTest.sample([3,1]),null);assert(alphaAt(1,1)>0);
''')
        point = {'x_centers_mm': [1, 5], 'y_centers_mm': [1, 3], 'values_c': [[30, None], [40, 50]]}
        self.run_document(VIEW, {'board_field': point}, r'''
assert.equal(thermalTest.cache().raster,null,'incomplete point quad has no invented area');
assert.equal(thermalTest.sample([2,1.5]),null);assert.match(controls['thermal-field-scale'].textContent,/No supported continuous field/);
''')

    def test_computed_frames_and_layer_selection_keep_fixed_transient_scale(self):
        bottom = {**FIELD, 'name': 'B.Cu', 'values_c': [[120, 130, 140], [140, 150, 160]]}
        network = {'layers': [FIELD, bottom], 'transient': {
            'frames': [{'time_s': 0, 'temperatures_c': [0, 10, 20, 30, 40, 50, 100, 110, 120, 130, 140, 150]},
                       {'time_s': 1, 'temperatures_c': [20, 30, 40, 50, 60, 70, 120, 130, 140, 150, 160, 170]}],
            'components': [], 'spatial_index': {'active_cells_per_layer': 6,
                'layers': [{'name': 'F.Cu'}, {'name': 'B.Cu'}],
                'x_centers_mm': [1, 3, 5], 'y_centers_mm': [1, 3],
                'cells': [[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]]}}}
        self.run_document(VIEW, network, r'''
assert.deepEqual(thermalTest.fieldScale(thermalTest.field()),[0,170]);const start=canvasCount;
controls['thermal-time'].value='1';controls['thermal-time'].onchange();assert.equal(canvasCount,start+1);assert.deepEqual(thermalTest.fieldScale(thermalTest.field()),[0,170]);assert.equal(thermalTest.sample([1.5,1.5]).t,20);
controls['thermal-field'].value='layer:1';controls['thermal-field'].onchange();assert.equal(thermalTest.sample([1.5,1.5]).t,120);assert.deepEqual(thermalTest.fieldScale(thermalTest.field()),[0,170]);
controls['thermal-time'].value='-1';controls['thermal-time'].onchange();assert.deepEqual(thermalTest.fieldScale(thermalTest.field()),[120,160]);
''')

    def test_constant_steady_field_uses_native_expanded_range(self):
        constant = {**FIELD, 'values_c': [[35, 35, 35], [35, 35, 35]]}
        self.run_document(VIEW, {'board_field': constant}, r'''
assert.deepEqual(thermalTest.fieldScale(thermalTest.field()),[34.5,35.5]);
controls['thermal-overlay'].checked=false;controls['thermal-overlay'].onchange();assert.equal(thermalTest.cache(),null);assert.match(controls['thermal-field-scale'].textContent,/overlay hidden/);
''')


if __name__ == '__main__':
    unittest.main()
