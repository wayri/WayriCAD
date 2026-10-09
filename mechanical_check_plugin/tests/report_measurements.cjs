const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=path.join(__dirname,'../src/wayricad_mechanical/report_scene.js');
vm.runInThisContext(fs.readFileSync(source,'utf8')+';globalThis.TestScene=ConflictScene');
const template=fs.readFileSync(path.join(__dirname,'../src/wayricad_mechanical/report_template.html'),'utf8');
const scripts=[...template.matchAll(/<script(?:[^>]*)>([\s\S]*?)<\/script>/g)];
assert.ok(scripts.length>=3);
new vm.Script(scripts.at(-1)[1]);
for(const id of ['mode-select','mode-parts','mode-points','part-a','part-b','measure-parts','clear-measurements','clear-probes','bottom','side','outline-note'])
  assert.match(template,new RegExp('id="'+id+'"'));
assert.match(template,/Show refs/);

const triangle=(z=0)=>({vertices:[[0,0,z],[1,0,z],[0,1,z]],faces:[[0,1,2]]});
const body=(ref,z=0,kind='component')=>({ref,kind,mesh:triangle(z),bounds:[0,0,z,1,1,z]});
function scene(records=[]){
  const s=Object.create(TestScene.prototype);
  Object.assign(s,{report:{rules:{}},center:[0,0,0],sectionDirection:'Z',section:false,isolate:false,ghost:true,
    selected:null,mode:'select',pairRefs:[],rulers:[],probes:[],proximity:new Map(records.map(r=>[[...r.refs].sort().join('\u0000'),r])),
    bodies:[body('U1'),body('Other:J2',2,'comparison_component')],draw(){},measureBuffers:new Map(),metrics:{triangleTests:0,boxTests:0,frames:0}});
  return s;
}
const exact={refs:['U1','Other:J2'],distance_mm:2,points:[[.25,.25,0],[.25,.25,2]],evidence:'exact STEP surfaces',unit:'mm',nearest_for:['U1','Other:J2']};
const loaded=TestScene.loadMeasurements({proximity:[exact],measurements:[{...exact,type:'point_ruler',distance_mm:0}],point_rulers:[{type:'point_ruler',refs:['U1','Other:J2'],distance_mm:3,points:[[0,0,0],[0,0,3]]}]});
assert.equal(loaded.proximity.size,1);
assert.equal(loaded.proximity.values().next().value.distance_mm,2);
assert.equal(loaded.rulers.length,1);
assert.equal(loaded.rulers[0].kind,'points');
const mixed=TestScene.loadMeasurements({proximity:[{...exact,evidence:'2D footprint envelopes',distance_mm:0.5}],measurements:[exact]});
assert.equal(mixed.proximity.values().next().value.evidence,'exact STEP surfaces');

// Saved Edge.Cuts loops remain line segments, including separate closed holes.
const outline={status:'available',bounds:[0,0,0,4,6,0],polylines:[
  {points:[[0,0,0],[4,0,0],[4,6,0],[0,6,0]],closed:true,hole:false},
  {points:[[1,1,0],[2,1,0],[2,2,0],[1,2,0]],closed:true,hole:true}]};
const loops=TestScene.outlineSegments(outline);
assert.equal(loops.length,2);assert.equal(loops[0].segments.length,4);
assert.deepEqual(loops[0].segments.at(-1),[[0,6,0],[0,0,0]]);
assert.equal(loops[1].hole,true);
assert.deepEqual(TestScene.outlineSegments({status:'unavailable',polylines:[]} ),[]);
const outlineScene=Object.create(TestScene.prototype);
Object.assign(outlineScene,{gl:{},report:{board_outline:outline},bodies:[{ref:'Enclosure',kind:'enclosure',bounds:[-100,-100,-5,100,100,5]}],draw(){}});
outlineScene.fit();assert.deepEqual(outlineScene.center,[2,3,0]);

// Crowded numeric labels use distinct boxes; reference labels are bounded,
// deterministic, and disappear for a fully clipped part.
const crowd=Array.from({length:8},(_,i)=>({kind:'ruler',text:(i+1).toFixed(3)+' mm',anchor:[320,210],priority:3,color:'#1459bd'}));
const arranged=TestScene.layoutLabels(crowd,640,480);
assert.equal(arranged.length,8);
assert.deepEqual(arranged,TestScene.layoutLabels(crowd,640,480));
for(let i=0;i<arranged.length;i++)for(let j=i+1;j<arranged.length;j++){
  const a=arranged[i].box,b=arranged[j].box;
  assert.ok(a.x+a.w+4<=b.x||b.x+b.w+4<=a.x||a.y+a.h+4<=b.y||b.y+b.h+4<=a.y);
}
const mixedLabels=TestScene.layoutLabels([crowd[0],{kind:'ref',text:'U1',anchor:[320,210],priority:1,color:'#345'}],640,480);
assert.equal(mixedLabels.length,2);
assert.notDeepEqual(mixedLabels[0].box,mixedLabels[1].box);
const labels=Object.create(TestScene.prototype);
Object.assign(labels,{showReferenceLabels:true,bodies:Array.from({length:100},(_,i)=>({ref:'U'+i,kind:'component',bounds:[i,0,0,i+1,1,0]})),
  canvas:{clientWidth:1000,clientHeight:500},pairRefs:[],selectedReference:'U99',hoverHit:null,selected:null,
  section:false,sectionDirection:'Z',report:{rules:{}},center:[0,0,0],project:p=>[p[0]*6+50,100]});
assert.equal(labels.referenceLabelItems().length,80);
assert.equal(labels.referenceLabelItems()[0].text,'U99');
labels.section=true;labels.center=[0,0,1];assert.equal(labels.referenceLabelItems().length,0);
labels.section=false;labels.showReferenceLabels=false;assert.equal(labels.referenceLabelItems().length,0);
const s=scene([exact]);
assert.equal(s.nearestRecord('U1'),exact);
assert.equal(s.nearestRecord('Other:J2'),exact);
assert.equal(s.measurePair('U1','Other:J2').distance_mm,2);
assert.equal(s.rulers[0].evidence,'exact STEP surfaces');
assert.match(s.measurePair('U1','U9').error,/Part gap unavailable/);
assert.equal(s.rulers.length,1);
const fallback=scene([{...exact,nearest_for:undefined}]);
assert.equal(fallback.nearestRecord('U1').distance_mm,2);
fallback.hoverHit={reference:'U1',position:[.25,.25,0]};
fallback.readout={textContent:''};fallback.updateReadout();
assert.match(fallback.readout.textContent,/Nearest known measured pair/);
s.clearMeasurements();assert.equal(s.rulers.length,0);

s.setMode('points');
s.clickHit({reference:'U1',position:[0,0,0]});
assert.ok(s.pendingPoint);
s.clickHit({reference:'Other:J2',position:[0,3,4]});
assert.equal(s.rulers[0].distance_mm,5);
assert.equal(s.rulers[0].evidence,'picked tessellated surface points');

s.setMode('parts');
s.clickHit({reference:'U1',position:[0,0,0]});
s.clickHit({reference:'Other:J2',position:[0,0,2]});
assert.deepEqual(s.pairRefs,['U1','Other:J2']);
assert.equal(s.rulers.at(-1).distance_mm,2);
s.clickHit({reference:'U1',position:[0,0,0]});
assert.deepEqual(s.pairRefs,['U1']);

// Section clipping and isolation must be shared by ruler picks and ordinary picks.
s.setMode('select');s.section=true;s.center=[0,0,1];
assert.equal(s.pickRay([.25,.25,-1],[0,0,1]).reference,'Other:J2');
s.isolate=true;s.selected={refs:['U1']};
assert.equal(s.pickRay([.25,.25,-1],[0,0,1]),null);
s.section=false;assert.equal(s.pickRay([.25,.25,-1],[0,0,1]).reference,'U1');
s.selected=null;s.isolate=false;s.setMode('parts');s.setPartFilter('other');
assert.equal(s.pickRay([.25,.25,-1],[0,0,1]).reference,'Other:J2');

// Spatial index should test a small neighborhood rather than every triangle.
const vertices=[],faces=[],size=100;
for(let x=0;x<size;x++)for(let y=0;y<size;y++){
  const n=vertices.length;vertices.push([x,y,0],[x+1,y,0],[x,y+1,0],[x+1,y+1,0]);
  faces.push([n,n+1,n+2],[n+1,n+3,n+2]);
}
const large=scene();large.bodies=[{ref:'Ubig',kind:'component',mesh:{vertices,faces},bounds:[0,0,0,100,100,0]}];
assert.equal(large.pickRay([.2,.2,5],[0,0,-1]).reference,'Ubig');
assert.ok(large.metrics.triangleTests<250,`BVH tested ${large.metrics.triangleTests} of ${faces.length} triangles`);
assert.ok(large.metrics.boxTests<100);

// Repeated events share a frame; unchanged CSS size must not reset the canvas.
global.window={devicePixelRatio:1};
let queue=[],widthWrites=0,heightWrites=0;
global.requestAnimationFrame=callback=>{queue.push(callback);return queue.length};
const canvas={clientWidth:640,clientHeight:480,_w:640,_h:480};
Object.defineProperties(canvas,{width:{get(){return this._w},set(v){widthWrites++;this._w=v}},height:{get(){return this._h},set(v){heightWrites++;this._h=v}}});
const gl=new Proxy({},{get:(target,key)=>typeof key==='string'&&key===key.toUpperCase()?1:()=>{}});
const frame=Object.create(TestScene.prototype);
Object.assign(frame,{gl,canvas,report:{rules:{}},center:[0,0,0],span:10,zoom:1,yaw:-1,pitch:.75,
  sectionDirection:'Z',section:false,bodies:[],outlineBuffers:[],selected:null,ghost:true,probes:[],rulers:[],
  cache:new Map(),measureBuffers:new Map(),attributes:[0,1],uniforms:{},metrics:{frames:0}});
frame.draw();frame.draw();frame.draw();assert.equal(queue.length,1);
queue.shift()();assert.equal(frame.metrics.frames,1);
assert.equal(widthWrites,0);assert.equal(heightWrites,0);
frame.draw();queue.shift()();assert.equal(widthWrites,0);
canvas.clientWidth=800;frame.draw();queue.shift()();assert.equal(widthWrites,1);
console.log(`report measurement behavior passed; BVH tested ${large.metrics.triangleTests}/${faces.length} triangles`);
