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
const featureRulers=['edge_edge','point_edge','center_center','point_point'].map((measurement_kind,index)=>({
  type:'feature_ruler',measurement_kind,refs:['U1','Other:J2'],
  features:[{kind:'edge',ref:'U1',edge_index:3},{kind:'edge',ref:'Other:J2',edge_index:5}],
  points:[[.25,.25,0],[.25,.25,index+1]],witnesses:[{source:'kernel'}],distance_mm:index+1,
  evidence:'exact CAD curves; geometric volume centroid',nearest_for:['U1'],status:'measured'
}));
const withFeatures=TestScene.loadMeasurements({feature_rulers:featureRulers,
  proximity:[featureRulers[0],exact],measurements:[...featureRulers]});
assert.equal(withFeatures.rulers.length,4);
assert.equal(withFeatures.proximity.size,1);
assert.equal(withFeatures.proximity.values().next().value,exact);
assert.deepEqual(withFeatures.rulers.map(TestScene.rulerPrefix),['Edges','Point→edge','Centers','Points']);
for(let i=0;i<featureRulers.length;i++){
  assert.deepEqual(withFeatures.rulers[i].features,featureRulers[i].features);
  assert.deepEqual(withFeatures.rulers[i].witnesses,featureRulers[i].witnesses);
  assert.equal(withFeatures.rulers[i].evidence,featureRulers[i].evidence);
}
const featureOnly=TestScene.loadMeasurements({feature_rulers:featureRulers,measurements:featureRulers});
assert.equal(featureOnly.proximity.size,0);
const featureOnlyScene=scene();featureOnlyScene.rulers=featureOnly.rulers;
assert.equal(featureOnlyScene.nearestRecord('U1'),null);
assert.match(featureOnlyScene.measurePair('U1','Other:J2').error,/Part gap unavailable/);
const invalidRulers=TestScene.loadMeasurements({feature_rulers:[
  {...featureRulers[0],distance_mm:null},{...featureRulers[0],distance_mm:-1},
  {...featureRulers[0],distance_mm:'3'},{...featureRulers[0],distance_mm:NaN},
  {...featureRulers[0],points:[[0,0,0],[0,0,Infinity]]},
  {...featureRulers[0],measurement_kind:'unknown'}]});
assert.equal(invalidRulers.rulers.length,0);

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
  canvas:{clientWidth:1000,clientHeight:500},pairRefs:[],rulers:[],selectedReference:'U99',hoverHit:null,selected:null,
  section:false,sectionDirection:'Z',report:{rules:{}},center:[0,0,0],project:p=>[p[0]*6+50,100]});
assert.equal(labels.referenceLabelItems().length,1);
assert.equal(labels.referenceLabelItems()[0].text,'U99');
labels.hoverHit={reference:'U1'};labels.rulers=[{refs:['U2','U3']},{refs:['U4','U5']}];labels.selected={refs:['U6']};
assert.deepEqual(new Set(labels.referenceLabelItems().map(item=>item.text)),new Set(['U99','U1','U4','U5','U6']));
labels.activeRuler=labels.rulers[0];
assert.deepEqual(new Set(labels.referenceLabelItems().map(item=>item.text)),new Set(['U99','U1','U2','U3','U6']));
labels.section=true;labels.center=[0,0,1];assert.equal(labels.referenceLabelItems().length,0);
labels.section=false;labels.showReferenceLabels=false;assert.equal(labels.referenceLabelItems().length,0);
const savedFeatures=scene([...withFeatures.proximity.values()]);
savedFeatures.rulers=withFeatures.rulers;savedFeatures.readout={textContent:''};
savedFeatures.project=p=>[p[0]*100+200,p[1]*100+100];
assert.equal(savedFeatures.activeRulerRecord(),withFeatures.rulers.at(-1));
savedFeatures.updateReadout();
assert.match(savedFeatures.readout.textContent,/Points U1 ↔ Other:J2: 4\.0000 mm/);
assert.match(savedFeatures.readout.textContent,/exact CAD curves; geometric volume centroid/);
let featureLabels=savedFeatures.rulerLabelItems([...savedFeatures.rulers,{...exact,hover:true}]);
assert.equal(featureLabels.length,2);
assert.deepEqual(featureLabels.map(label=>label.text),['Points 4.000 mm','Gap 2.000 mm']);
savedFeatures.activeRuler=savedFeatures.rulers[0];
assert.deepEqual(savedFeatures.rulerLabelItems(savedFeatures.rulers).map(label=>label.text),['Edges 1.000 mm']);
savedFeatures.updateReadout();assert.match(savedFeatures.readout.textContent,/Edges U1 ↔ Other:J2/);
assert.equal(savedFeatures.rulers.length,4); // Historical lines remain in the scene.
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
assert.equal(s.activeRulerRecord(),s.rulers[0]);

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
let rulerGeometry=[],overlayLines=[];
frame.rulers=withFeatures.rulers;frame.hoverWitness=exact;
frame.measurementBuffer=points=>{rulerGeometry.push(points);return {buffer:{},count:2}};
frame.drawOverlay=lines=>{overlayLines=lines};
frame.draw();queue.shift()();
assert.equal(rulerGeometry.length,5); // Four historical rulers and the hovered nearest witness still draw.
assert.equal(overlayLines.length,5);
assert.equal(frame.rulerLabelItems(overlayLines).length,2); // Only latest and hover receive text.
// Height/proximity findings stay outside the nearest-gap evidence index.
const topHeight={id:'ht',rule:'height.maximum',refs:['U1'],side:'top',measured:8.7,limit:8,severity:'error',label_position:[.2,.2,1]};
const bottomHeight={...topHeight,id:'hb',side:'bottom',measured:4,limit:3};
const proximityWarning={id:'pw',rule:'solid.proximity_warning',refs:['U1','Other:J2'],measured:.4,limit:1,severity:'warning',evidence:'exact STEP surfaces'};
const alertMap=TestScene.alertIndex({findings:[topHeight,bottomHeight,proximityWarning,{...topHeight,id:'waived',refs:['U9'],waiver:'Reviewed lid opening'}]});
assert.equal(alertMap.get('U1').length,3);assert.equal(alertMap.get('Other:J2').length,1);assert.ok(!alertMap.has('U9'));
assert.equal(TestScene.heightLabel(topHeight),'U1 top +0.7 mm');
assert.equal(TestScene.heightLabel({...topHeight,measured:8}),null);
assert.equal(TestScene.heightLabel({...topHeight,measured:NaN}),null);
const marked=scene([exact]);
Object.assign(marked,{alerts:alertMap,showViolationMarkers:true,canvas:{clientWidth:640,clientHeight:480},
  project:p=>[p[0]*100+200,p[1]*100+100],readout:{textContent:''}});
assert.equal(marked.heightLabelItems().length,2);
assert.deepEqual(marked.heightLabelItems().map(item=>item.text),['U1 bottom +1 mm','U1 top +0.7 mm']);
assert.deepEqual(marked.bodyColor(marked.bodies[0],false),[.94,.23,.18,1]);
assert.deepEqual(marked.bodyColor(marked.bodies[1],false),[.98,.64,.12,1]);
marked.hoverHit={reference:'U1',position:[.2,.2,0]};marked.updateReadout();
assert.match(marked.readout.textContent,/top \+0.7 mm/);assert.match(marked.readout.textContent,/warning below 1 mm/);
assert.equal(marked.nearestRecord('U1'),exact); // Warning/height fields cannot invent a nearest part.
marked.showViolationMarkers=false;assert.equal(marked.heightLabelItems().length,0);
assert.deepEqual(marked.bodyColor(marked.bodies[0],true),[.05,.85,.72,1]);
console.log(`report measurement behavior passed; BVH tested ${large.metrics.triangleTests}/${faces.length} triangles`);
