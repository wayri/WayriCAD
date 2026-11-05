import test from 'node:test';
import assert from 'node:assert/strict';
import { canonicalScope, validateAnchor, validateDocument, validateComments,
  projectWorld, screenToWorld, createReviewBridge, mountReviewBridge } from '../review_comments_plugin/web/bridge.mjs';

const scope = { repository:'example/board', ref:'a'.repeat(40), file:'board.kicad_pcb' };
const documentPayload = (extra={}) => ({ source:'(kicad_pcb (version 20241229))', path:'board.kicad_pcb',
  source_sha256:'b'.repeat(64), scope, ...extra });
const marker = (extra={}) => ({ comment_id:'12', anchor:{...scope,kind:'position',position:{x:20,y:15}},
  x:20,y:15,severity:'warning',state:'open',label:'Check clearance', ...extra });
const comments = (extra={}) => ({scope,status:'synced',markers:[marker()],...extra});

class Element extends EventTarget {
  constructor(document, tag='div') { super(); this.ownerDocument=document; this.tagName=tag; this.children=[]; this.style={}; this.attributes={}; this.value=''; this.checked=false; this.captured=new Set(); }
  append(...values) { for(const value of values) { value.parentNode?.removeChild?.(value); value.parentNode=this; this.children.push(value); } }
  replaceChildren(...values) { this.children.forEach(value=>{value.parentNode=null;}); this.children=[]; this.append(...values); }
  removeChild(value) { this.children=this.children.filter(child=>child!==value); value.parentNode=null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(key,value) { this.attributes[key]=String(value); }
  getAttribute(key) { return this.attributes[key]; }
  getBoundingClientRect() { return {left:10,top:20,width:800,height:500}; }
  querySelectorAll(tag) { return this.children.flatMap(child=>[...(tag==='*'||child.tagName===tag?[child]:[]),...(child.querySelectorAll?.(tag)||[])]); }
  querySelector(selector) {
    assert.equal(selector,'[role="toolbar"][aria-label="Drawing viewer controls"]');
    return this.querySelectorAll('*').find(child=>child.getAttribute?.('role')==='toolbar'&&child.getAttribute('aria-label')==='Drawing viewer controls')||null;
  }
  setPointerCapture(id) { this.captured.add(id); }
  hasPointerCapture(id) { return this.captured.has(id); }
  releasePointerCapture(id) { this.captured.delete(id); }
}
const dom = { createElement(tag) { return new Element(this,tag); }, createElementNS(ns,tag) { return new Element(this,tag); }, createTextNode(value) { return {textContent:String(value)}; } };
const event = (name, values={}) => Object.assign(new Event(name,{cancelable:true}),values);
const emit = (target,name,detail) => target.dispatchEvent(event(name,{detail}));

function camera() {
  return { width:800,height:500,zoom:4,flipped:false,calls:[],
    center:{x:40,y:30,set(x,y){this.x=x;this.y=y;}},
    world_to_screen(p) { this.calls.push(['world',p]); return {x:(p.x-this.center.x)*this.zoom*(this.flipped?-1:1)+400,y:(p.y-this.center.y)*this.zoom+250}; },
    screen_to_world(p) { this.calls.push(['screen',p]); return {x:this.center.x+(p.x-400)/this.zoom*(this.flipped?-1:1),y:this.center.y+(p.y-250)/this.zoom}; },
  };
}
class Viewer extends EventTarget {
  constructor(host,options) {
    super();this.host=host;this.options=options;this.stage=new Element(dom);this.surface=new Element(dom);
    this.toolbar=new Element(dom);this.toolbar.setAttribute('role','toolbar');this.toolbar.setAttribute('aria-label','Drawing viewer controls');
    this.unrelatedToolbar=new Element(dom);this.unrelatedToolbar.setAttribute('role','toolbar');this.unrelatedToolbar.setAttribute('aria-label','Renderer diagnostics');
    this.surface.append(this.toolbar,this.unrelatedToolbar,this.stage);host.append(this.surface);
    this.fitCount=0;this.layers=['F.Cu','B.Cu','Edge.Cuts'];this.theme=options.theme;this.themeCalls=[];
  }
  async loadSource(source,{path,view}) { this.source=source;this.path=path;this.kind=view==='manufacturing'?'manufacturing':source.includes('(kicad_sch')?'schematic':'pcb';return this.setView(view); }
  async showManufacturing() { return this.setView('manufacturing'); }
  async setView(view) {
    this.view=view;
    this.renderer=view==='3d'?{projectAnchor:({position})=>({x:position.x+10,y:position.y+20,visible:true}),setSelection(value){this.selection=value;},setAnchor(value){this.anchor=value;}}:
      {viewport:{camera:camera()},visibleLayers:new Set(['F.Cu','Edge.Cuts']),draw(){},requestDraw(){},resize(){}};
    emit(this,'ready',{view,path:this.path});return true;
  }
  fit() { this.fitCount++; }
  setTheme(theme) {
    assert.ok(['light','dark'].includes(theme));this.theme=theme;this.themeCalls.push(theme);
    if(this.view==='3d')this.renderer?.setTheme?.(theme==='dark');
    else if(this.renderer){this.renderer.dark=theme==='dark';this.renderer.draw();}
  }
  getLayers() { return [...this.layers]; }
  setLayers(value) { this.layerChoice=value;this.renderer.visibleLayers=new Set(value);this.renderer.draw(); }
  dispose() { this.disposed=true; }
}
function fixture(options={}) {
  const page={...dom,documentElement:new Element(dom,'html')};
  const ids=['viewer','status','layers','layers-toggle','documents','overlay','view-pcb','view-schematic','view-3d','fit','comment-menu','comment-label','mode-pan','mode-pin','mode-region'];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element(page,id==='overlay'?'svg':'div')]));
  const messages=[],cancelled=[];
  const bridge=createReviewBridge({ViewerClass:Viewer,elements,document:page,
    postMessage:value=>messages.push(value),raf:()=>1,cancelRaf:id=>cancelled.push(id),...options});
  return {bridge,elements,messages,cancelled,page};
}

test('document and anchor payloads are data-only, bounded and immutable-scope',()=>{
  assert.equal(validateDocument(documentPayload()).view,'pcb');
  assert.throws(()=>validateDocument(documentPayload({src:'https://foreign.example/board'})),/fields/);
  assert.throws(()=>validateDocument(documentPayload({source:'<script>alert(1)</script>'})),/type/);
  assert.throws(()=>validateDocument(documentPayload({source_sha256:'short'})),/SHA256/);
  assert.throws(()=>validateDocument(documentPayload({path:'main.kicad_sch'})),/type/);
  assert.throws(()=>validateDocument(documentPayload({view:'schematic'})),/View/);
  assert.throws(()=>validateAnchor({...scope,position:{x:NaN,y:1}},scope),/coordinate/);
  assert.throws(()=>validateAnchor({...scope,area:{x:1,y:2,width:0,height:1}},scope),/positive/);
  assert.throws(()=>validateAnchor({...scope,ref:'c'.repeat(40),position:{x:1,y:2}},scope),/another/);
});

test('local Gerber pins retain separate artifact coordinates and reject cross-artifact authority',async()=>{
  const artifact={type:'gerber',file:'fab/top.gbr',sha256:'b'.repeat(64)};
  const payload=documentPayload({source:'%FSLAX46Y46*%\n%MOMM*%\nM02*',path:'fab/top.gbr',view:'manufacturing',artifact,
    documents:[{id:'fab/top.gbr',label:'Top Gerber',kind:'manufacturing'}],current_document_id:'fab/top.gbr'});
  assert.equal(validateDocument(payload).kind,'manufacturing');
  assert.throws(()=>validateDocument({...payload,path:'../private.gbr'}),/type/);
  assert.throws(()=>validateDocument({...payload,artifact:{...artifact,sha256:'c'.repeat(64)}}),/identity/);
  const {bridge,messages}=fixture();assert.equal(await bridge.setDocument(payload),true);
  bridge.setComments(comments({markers:[],path:payload.path,source_sha256:payload.source_sha256}));
  bridge.setMode('pin');
  const stage=bridge.viewer.stage;
  stage.dispatchEvent(event('pointerdown',{button:0,pointerId:1,clientX:410,clientY:270}));
  stage.dispatchEvent(event('pointerup',{pointerId:1,clientX:410,clientY:270}));
  const target=messages.find(value=>value.type==='draftAnchor').anchor;
  assert.deepEqual(target.context,{...artifact,position:{x:40,y:30}});
  assert.equal(target.position,undefined);assert.equal(target.file,'board.kicad_pcb');
  assert.equal(bridge.setDraft(target),true);
  assert.equal(bridge.setComments(comments({markers:[marker({anchor:target,x:40,y:30})],path:payload.path,source_sha256:payload.source_sha256})),1);
  assert.throws(()=>bridge.setComments(comments({markers:[marker({anchor:{...target,context:{...target.context,file:'fab/bottom.gbr'}},x:40,y:30})]})),/another manufacturing/);
  assert.equal(bridge.authorized,false);
  assert.equal(await bridge.setDocument({...payload,scope:null,artifact:null}),true);
  bridge.setComments(comments({markers:[],path:payload.path,source_sha256:payload.source_sha256}));
  assert.equal(bridge.authorized,false);
  bridge.dispose();
});

test('GitLab authority preserves exact explicit-port scope like Python model.scope',()=>{
  const plain={...scope,provider:'gitlab',host:'https://gitlab.example'};
  const explicit={...plain,host:'https://gitlab.example:443/'};
  assert.equal(canonicalScope(explicit).host,'https://gitlab.example:443');
  assert.throws(()=>validateAnchor({...explicit,position:{x:1,y:2}},plain),/another/);
  assert.throws(()=>canonicalScope({...plain,host:'https://user:secret@gitlab.example'}),/origin/);
});

test('cached or foreign comments cannot authorize markers; malformed coordinates fail closed',()=>{
  const doc=validateDocument(documentPayload());
  assert.deepEqual(validateComments(comments({status:'cached / unverified'}),doc),[]);
  assert.deepEqual(validateComments(comments({scope:{...scope,ref:'c'.repeat(40)}}),doc),[]);
  assert.throws(()=>validateComments(comments({markers:[marker({x:99})]}),doc),/differs/);
  assert.throws(()=>validateComments(comments({markers:[marker({anchor:{...scope,uuid:'object'},x:Infinity})]}),doc),/coordinate/);
  assert.throws(()=>validateComments(comments({markers:Array(1001).fill(marker())}),doc),/oversized/);
});

test('camera adapter uses renderer mappings including flipped camera and explicit 3D client rect',()=>{
  const c=camera(),viewer={view:'pcb',renderer:{viewport:{camera:c}}};
  c.flipped=true;
  const position={x:20,y:15},p=projectWorld(viewer,position,{left:10,top:20});
  assert.deepEqual(screenToWorld(viewer,p.x,p.y),position);
  assert.deepEqual(c.calls.map(call=>call[0]),['world','screen']);
  const three={view:'3d',renderer:{projectAnchor:()=>({x:120,y:230,visible:true})}};
  assert.deepEqual(projectWorld(three,position,{left:10,top:20}),{x:110,y:210});
  assert.throws(()=>screenToWorld(three,1,2),/no verified/);
  three.renderer.projectAnchor=()=>null;
  assert.equal(projectWorld(three,position,{left:0,top:0}),null);
  assert.equal(projectWorld({view:'pcb',renderer:{}},position,{}),null);
});

test('default load fits drawing, exposes real saved layers and sends document identity',async()=>{
  const {bridge,elements,messages}=fixture();
  assert.equal(messages.length,0); // Readiness belongs to mount, after global API installation.
  assert.equal(await bridge.setDocument(documentPayload()),true);
  assert.ok(bridge.viewer.fitCount>0);
  assert.equal(elements.layers.querySelectorAll('input').length,3);
  const check=elements.layers.querySelectorAll('input')[1];check.checked=true;check.dispatchEvent(event('change'));
  assert.deepEqual(bridge.viewer.layerChoice,['F.Cu','B.Cu','Edge.Cuts']);
  const ready=messages.find(value=>value.type==='documentReady');
  assert.equal(ready.path,'board.kicad_pcb');assert.equal(ready.source_sha256,'b'.repeat(64));
  assert.equal(bridge.setComments(comments()),1);
  assert.equal(elements.overlay.children.length,1);
  bridge.dispose();
});

test('layer names, labels and provider text remain text nodes instead of executable markup',async()=>{
  const {bridge,elements}=fixture();
  bridge.viewer.layers=['<img src=x onerror=alert(1)>'];
  await bridge.setDocument(documentPayload());
  assert.equal(elements.layers.children[0].children[1].textContent,'<img src=x onerror=alert(1)>');
  bridge.setComments(comments({markers:[marker({label:'<script>bad()</script>'})]}));
  assert.equal(elements.overlay.children[0].getAttribute('aria-label'),'<script>bad()</script>');
  assert.equal(elements.overlay.querySelectorAll('script').length,0);
  bridge.dispose();
});

test('overlay follows camera changes and comment focus centers the renderer world point',async()=>{
  const {bridge,elements}=fixture();await bridge.setDocument(documentPayload());bridge.setComments(comments());
  const c=bridge.viewer.renderer.viewport.camera;
  const before=elements.overlay.querySelectorAll('circle')[0].getAttribute('cx');
  c.center.x+=10;bridge.viewer.renderer.draw();
  assert.notEqual(elements.overlay.querySelectorAll('circle')[0].getAttribute('cx'),before);
  assert.equal(bridge.focusComment('12'),true);
  assert.deepEqual({x:c.center.x,y:c.center.y},{x:20,y:15});
  assert.equal(elements.overlay.querySelectorAll('circle')[0].getAttribute('cx'),'400');
  assert.equal(bridge.focusComment('missing'),false);
  bridge.dispose();
});

test('pins and regional polygons focus only current threads and stale detached pins cannot act',async()=>{
  const {bridge,elements,messages}=fixture();await bridge.setDocument(documentPayload());
  bridge.setComments(comments({markers:[marker({anchor:{...scope,area:{x:10,y:5,width:20,height:20}},x:20,y:15,region:[10,5,20,20]})]}));
  assert.equal(elements.overlay.querySelectorAll('polygon').length,1);
  const old=elements.overlay.children[0];old.dispatchEvent(event('click'));
  assert.equal(messages.filter(value=>value.type==='focusThread').length,1);
  bridge.setComments(comments({status:'offline / stale'}));
  assert.equal(elements.overlay.children.length,0);assert.equal(bridge.focusComment('12'),false);
  old.dispatchEvent(event('click'));
  assert.equal(messages.filter(value=>value.type==='focusThread').length,1);
  bridge.dispose();
});

test('point and region pointer drafts send scoped world coordinates without publication',async()=>{
  const {bridge,messages}=fixture();await bridge.setDocument(documentPayload());bridge.setComments(comments());
  const stage=bridge.viewer.stage;
  bridge.setMode('pin');
  stage.dispatchEvent(event('pointerdown',{button:0,pointerId:1,clientX:410,clientY:270}));
  stage.dispatchEvent(event('pointerup',{pointerId:1,clientX:410,clientY:270}));
  assert.deepEqual(messages.find(value=>value.type==='draftAnchor').anchor.position,{x:40,y:30});
  const click=event('click');stage.dispatchEvent(click);assert.equal(click.defaultPrevented,true);
  bridge.setMode('region');
  stage.dispatchEvent(event('pointerdown',{button:0,pointerId:2,clientX:450,clientY:310}));
  stage.dispatchEvent(event('pointerup',{pointerId:2,clientX:410,clientY:270}));
  const last=messages.filter(value=>value.type==='draftAnchor').at(-1);
  assert.deepEqual(last.anchor.area,{x:40,y:30,width:10,height:10});
  assert.equal(last.anchor.ref,scope.ref);
  assert.ok(messages.every(value=>!['publish','post','writeDesign'].includes(value.type)));
  bridge.dispose();
});

test('stale provider state blocks drafts even after a pointer gesture has started',async()=>{
  const {bridge,messages}=fixture();await bridge.setDocument(documentPayload());bridge.setComments(comments());
  bridge.setMode('pin');bridge.viewer.stage.dispatchEvent(event('pointerdown',{button:0,pointerId:1,clientX:410,clientY:270}));
  bridge.setComments(comments({status:'offline / stale'}));
  bridge.viewer.stage.dispatchEvent(event('pointerup',{pointerId:1,clientX:410,clientY:270}));
  assert.equal(messages.filter(value=>value.type==='draftAnchor').length,0);
  assert.throws(()=>bridge.setMode('region'),/Refresh/);
  bridge.dispose();
});

test('selected objects relay only data; foreign source events are ignored',async()=>{
  const {bridge,messages}=fixture();await bridge.setDocument(documentPayload());
  emit(bridge.viewer,'select',{path:'foreign.kicad_pcb',item:{uuid:'foreign'}});
  emit(bridge.viewer,'select',{path:'board.kicad_pcb',item:{uuid:'pad-1',reference:'U1',kind:'pad',callback:()=>{},remoteUrl:'https://untrusted'}});
  const selected=messages.filter(value=>value.type==='objectSelected');
  assert.equal(selected.length,1);assert.deepEqual(selected[0].item,{uuid:'pad-1',reference:'U1',kind:'pad'});
  bridge.dispose();
});

test('project document choices and mismatched view tabs ask the host instead of inventing files',async()=>{
  const {bridge,elements,messages}=fixture();
  await bridge.setDocument(documentPayload({documents:[{id:'board',label:'PCB',kind:'pcb'},{id:'root',label:'Schematic',kind:'schematic'}],current_document_id:'board'}));
  elements.documents.value='root';elements.documents.dispatchEvent(event('change'));
  assert.equal(messages.find(value=>value.type==='requestDocument').id,'root');
  elements.documents.value='not-authorized';elements.documents.dispatchEvent(event('change'));
  assert.equal(messages.filter(value=>value.type==='requestDocument').length,1);
  assert.equal(await bridge.setView('schematic'),false);
  assert.equal(messages.find(value=>value.type==='requestView').view,'schematic');
  assert.equal(bridge.viewer.view,'pcb');bridge.dispose();
});

test('3D view projects existing comments, keeps material preview independent, and refuses inverse drafting',async()=>{
  const {bridge,elements,cancelled}=fixture();await bridge.setDocument(documentPayload());bridge.setComments(comments());
  assert.equal(await bridge.setView('3d'),true);
  assert.equal(elements.layers.children.length,0);
  assert.equal(elements.overlay.querySelectorAll('circle')[0].getAttribute('cx'),'20');
  assert.throws(()=>bridge.setMode('pin'),/PCB view/);
  assert.equal(bridge.focusComment('12'),true);
  assert.ok(bridge.viewer.renderer.anchor);
  await bridge.setView('pcb');assert.ok(cancelled.length>0);
  bridge.dispose();
});

test('wx messages use the distinct registered native handler and JSON data',async()=>{
  const seen=[];globalThis.wayricadHost={postMessage:(...args)=>seen.push(args)};
  globalThis.wx={postMessage:()=>assert.fail('Legacy wx channel must not be used.')};
  try {
    const {bridge}=fixture({postMessage:undefined});
    await bridge.setDocument(documentPayload());
    assert.equal(seen[0].length,1);assert.equal(JSON.parse(seen[0][0]).type,'documentReady');bridge.dispose();
  } finally { delete globalThis.wayricadHost;delete globalThis.wx; }
});

test('failed or malformed new documents clear old content and marker authority',async()=>{
  const {bridge,elements,messages}=fixture();await bridge.setDocument(documentPayload());bridge.setComments(comments());
  assert.equal(await bridge.setDocument(documentPayload({source:'not a KiCad source'})),false);
  assert.equal(bridge.authorized,false);assert.equal(bridge.viewer.renderer,null);
  assert.equal(elements.overlay.children.length,0);assert.equal(bridge.focusComment('12'),false);
  assert.ok(messages.some(value=>value.type==='error'));
  assert.equal(await bridge.setDocument(documentPayload()),true);
  bridge.viewer.loadSource=async()=>{throw Error('Renderer failed');};
  assert.equal(await bridge.setDocument(documentPayload()),false);
  assert.equal(bridge.viewer.renderer,null);bridge.dispose();
});

test('partially visible 2D regions remain outlined even when their center is offscreen',async()=>{
  const {bridge,elements}=fixture();await bridge.setDocument(documentPayload());
  bridge.setComments(comments({markers:[marker({anchor:{...scope,area:{x:0,y:0,width:2000,height:100}},x:1000,y:50,region:[0,0,2000,100]})]}));
  assert.equal(elements.overlay.querySelectorAll('polygon').length,1);
  assert.equal(elements.overlay.querySelectorAll('circle').length,0);bridge.dispose();
});

test('disposal revokes old detached marker actions and stops 3D overlay animation',async()=>{
  const {bridge,elements,messages,cancelled}=fixture();await bridge.setDocument(documentPayload());bridge.setComments(comments());
  await bridge.setView('3d');const old=elements.overlay.children[0];bridge.dispose();
  old.dispatchEvent(event('click'));assert.equal(messages.filter(value=>value.type==='focusThread').length,0);
  assert.equal(bridge.authorized,false);assert.ok(cancelled.length>0);
  assert.equal(await bridge.setDocument(documentPayload()),false);
});

test('identity-bound provider connection promotes preview scope without reload or camera reset',async()=>{
  const {bridge,elements}=fixture();await bridge.setDocument(documentPayload({scope:null}));
  const renderer=bridge.viewer.renderer,c=renderer.viewport.camera;
  c.zoom=7;c.center.set(12,17);const fits=bridge.viewer.fitCount;
  assert.equal(bridge.setComments(comments()),0);
  assert.equal(bridge.authorized,false);
  assert.equal(bridge.setComments(comments({path:'board.kicad_pcb',source_sha256:'b'.repeat(64)})),1);
  assert.equal(bridge.authorized,true);assert.equal(elements.overlay.children.length,1);
  assert.equal(bridge.viewer.renderer,renderer);assert.equal(c.zoom,7);
  assert.deepEqual({x:c.center.x,y:c.center.y},{x:12,y:17});assert.equal(bridge.viewer.fitCount,fits);
  const nextScope={...scope,ref:'d'.repeat(40)};
  assert.equal(bridge.setComments(comments({scope:nextScope,path:'board.kicad_pcb',source_sha256:'b'.repeat(64),
    markers:[marker({anchor:{...nextScope,position:{x:20,y:15}}})]})),1);
  assert.equal(bridge.focusComment('12'),true);
  bridge.dispose();
});

test('stale document or SHA scope updates clear authority and never promote another preview',async()=>{
  const {bridge,elements}=fixture();await bridge.setDocument(documentPayload({scope:null}));
  for(const identity of [{path:'other.kicad_pcb',source_sha256:'b'.repeat(64)},
                        {path:'board.kicad_pcb',source_sha256:'c'.repeat(64)}]) {
    assert.equal(bridge.setComments(comments(identity)),0);
    assert.equal(bridge.authorized,false);assert.equal(elements.overlay.children.length,0);
    assert.equal(bridge.setComments(comments()),0); // A stale message did not silently promote scope.
  }
  bridge.setComments(comments({path:'board.kicad_pcb',source_sha256:'b'.repeat(64)}));
  assert.equal(bridge.authorized,true);
  bridge.setComments(comments({path:'board.kicad_pcb',source_sha256:'c'.repeat(64)}));
  assert.equal(bridge.authorized,false);assert.equal(elements.overlay.children.length,0);
  bridge.dispose();
});

function mountPage() {
  const ids=['viewer','status','layers','layers-toggle','documents','review-overlay','view-pcb','view-schematic','view-3d','fit','comment-menu','comment-label','mode-pan','mode-pin','mode-region'];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element(dom,id==='review-overlay'?'svg':'div')]));
  return {elements,page:{...dom,getElementById:id=>elements[id]||null}};
}

test('mount installs API before native ready so immediate host document delivery succeeds',async()=>{
  const {page}=mountPage(),messages=[],loads=[],target={};
  const native={postMessage(raw) {
    const value=JSON.parse(raw);messages.push(value);
    if(value.type==='ready') {
      assert.equal(typeof target.wayricadReview?.setDocument,'function');
      assert.equal(target.wayricadHost,native);
      loads.push(target.wayricadReview.setDocument(documentPayload()));
    }
  }};
  target.wayricadHost=native;
  const bridge=await mountReviewBridge({ViewerClass:Viewer,document:page,window:target});
  assert.deepEqual(await Promise.all(loads),[true]);
  assert.equal(messages.filter(value=>value.type==='ready').length,1);
  assert.equal(messages[0].type,'ready');
  assert.ok(messages.some(value=>value.type==='documentReady'&&value.path==='board.kicad_pcb'));
  assert.equal(target.wayricadReview,bridge);assert.notEqual(bridge,native);
  bridge.dispose();
});

test('mount failures report through wayricadHost without announcing an unusable API',async()=>{
  const {page,elements}=mountPage(),messages=[];
  const target={wayricadHost:{postMessage:raw=>messages.push(JSON.parse(raw))}};
  class FailedViewer { constructor(){throw new Error('Renderer import or initialization failed.');} }
  await assert.rejects(mountReviewBridge({ViewerClass:FailedViewer,document:page,window:target}),/initialization/);
  assert.equal(target.wayricadReview,undefined);
  assert.deepEqual(messages,[{type:'error',message:'Renderer import or initialization failed.'}]);
  assert.match(elements.status.textContent,/initialization/);
});

test('missing native handler is visible and disposes a partially mounted renderer',async()=>{
  const {page,elements}=mountPage(),target={};
  await assert.rejects(mountReviewBridge({ViewerClass:Viewer,document:page,window:target}),/handler is unavailable/);
  assert.equal(target.wayricadReview,undefined);
  assert.match(elements.status.textContent,/handler is unavailable/);
});

test('unpublished point and region previews use the real camera without becoming comment actions',async()=>{
  const {bridge,elements,messages}=fixture();
  await bridge.setDocument(documentPayload());bridge.setComments(comments());
  const draft=()=>elements.overlay.children.find(child=>child.getAttribute('data-draft')==='true');
  assert.equal(bridge.setDraft({...scope,position:{x:40,y:30}}),true);
  assert.equal(draft().getAttribute('data-comment-id'),undefined);
  assert.equal(draft().children[0].getAttribute('cx'),'400');
  assert.equal(draft().children[0].getAttribute('cy'),'250');
  bridge.viewer.renderer.viewport.camera.center.set(45,35);bridge.viewer.renderer.draw();
  assert.equal(draft().children[0].getAttribute('cx'),'380');
  assert.equal(bridge.setDraft({...scope,area:{x:30,y:20,width:10,height:15}}),true);
  assert.equal(draft().children[0].tagName,'polygon');
  assert.equal(draft().children[0].getAttribute('fill'),'none');
  const before=messages.length;draft().dispatchEvent(event('click'));
  assert.equal(messages.length,before);
  bridge.setComments(comments());assert.ok(draft());
  await bridge.setView('3d');assert.ok(draft());
  bridge.setDraft(null);assert.equal(draft(),undefined);
  assert.equal(bridge.setDraft({...scope,uuid:'unresolved'}),false);
  assert.equal(draft(),undefined);bridge.dispose();
});

test('draft previews reject foreign authority and clear on stale state, malformed coordinates and document replacement',async()=>{
  const {bridge,elements}=fixture();
  await bridge.setDocument(documentPayload());bridge.setComments(comments());
  const draft=()=>elements.overlay.children.find(child=>child.getAttribute('data-draft')==='true');
  const point={...scope,position:{x:40,y:30}};
  bridge.setDraft(point);
  assert.throws(()=>bridge.setDraft({...point,ref:'f'.repeat(40)}),/another/);
  assert.equal(draft(),undefined);
  bridge.setDraft(point);
  assert.throws(()=>bridge.setDraft({...scope,position:{x:NaN,y:3}}),/coordinate/);
  assert.equal(draft(),undefined);
  bridge.setDraft(point);bridge.setComments(comments({status:'stale'}));
  assert.equal(draft(),undefined);assert.throws(()=>bridge.setDraft(point),/Refresh/);
  bridge.setComments(comments());assert.equal(draft(),undefined);
  bridge.setDraft(point);await bridge.setDocument(documentPayload());
  assert.equal(draft(),undefined);bridge.dispose();
});

test('host toolbar replaces only the pinned library controls and layers start collapsed',async()=>{
  const {bridge,elements}=fixture();
  assert.equal(bridge.viewer.toolbar.style.display,'none');
  assert.equal(bridge.viewer.unrelatedToolbar.style.display,undefined);
  assert.equal(elements.layers.hidden,true);assert.equal(elements['layers-toggle'].disabled,true);
  await bridge.setDocument(documentPayload());
  const renderer=bridge.viewer.renderer,c=renderer.viewport.camera,fits=bridge.viewer.fitCount;
  c.center.set(14,19);c.zoom=8;
  assert.equal(elements.layers.hidden,true);
  assert.equal(elements['layers-toggle'].getAttribute('aria-expanded'),'false');
  elements['layers-toggle'].dispatchEvent(event('click'));
  assert.equal(elements.layers.hidden,false);
  assert.equal(elements['layers-toggle'].getAttribute('aria-expanded'),'true');
  const check=elements.layers.querySelectorAll('input')[1];check.checked=true;check.dispatchEvent(event('change'));
  assert.deepEqual(bridge.viewer.layerChoice,['F.Cu','B.Cu','Edge.Cuts']);
  assert.equal(bridge.viewer.renderer,renderer);assert.equal(c.zoom,8);
  assert.deepEqual({x:c.center.x,y:c.center.y},{x:14,y:19});assert.equal(bridge.viewer.fitCount,fits);
  elements['layers-toggle'].dispatchEvent(event('click'));assert.equal(elements.layers.hidden,true);
  await bridge.setView('3d');assert.equal(elements.layers.hidden,true);assert.equal(elements['layers-toggle'].disabled,true);
  bridge.dispose();
});

test('compact comment menu closes after selection and reflects the authorized draft mode',async()=>{
  const {bridge,elements}=fixture();await bridge.setDocument(documentPayload());
  assert.equal(elements['mode-pin'].disabled,true);
  bridge.setComments(comments());assert.equal(elements['mode-pin'].disabled,false);
  elements['comment-menu'].open=true;elements['mode-pin'].dispatchEvent(event('click'));
  assert.equal(elements['comment-menu'].open,false);
  assert.equal(elements['comment-label'].textContent,'Place pin…');
  assert.equal(elements['mode-pin'].getAttribute('aria-pressed'),'true');
  elements['mode-pan'].dispatchEvent(event('click'));assert.equal(elements['comment-label'].textContent,'Add comment');
  await bridge.setView('3d');assert.equal(elements['mode-pin'].disabled,true);assert.equal(elements['mode-region'].disabled,true);
  bridge.dispose();
});

test('one host theme API updates library and host chrome without reload or camera changes',async()=>{
  const {bridge,page,elements}=fixture();
  assert.equal(bridge.setTheme('dark'),true);
  assert.equal(page.documentElement.getAttribute('data-theme'),'dark');
  await bridge.setDocument(documentPayload());bridge.setComments(comments());
  const renderer=bridge.viewer.renderer,c=renderer.viewport.camera,fits=bridge.viewer.fitCount;
  c.zoom=9;c.center.set(17,23);bridge.setDraft({...scope,position:{x:40,y:30}});
  assert.equal(renderer.dark,true);assert.equal(bridge.viewer.theme,'dark');
  assert.equal(bridge.setTheme('light'),true);
  assert.equal(renderer.dark,false);assert.equal(page.documentElement.getAttribute('data-theme'),'light');
  assert.equal(bridge.viewer.renderer,renderer);assert.equal(c.zoom,9);
  assert.deepEqual({x:c.center.x,y:c.center.y},{x:17,y:23});assert.equal(bridge.viewer.fitCount,fits);
  assert.equal(bridge.authorized,true);assert.ok(elements.overlay.children.find(child=>child.getAttribute('data-draft')==='true'));
  assert.throws(()=>bridge.setTheme('system'),/Theme/);assert.equal(bridge.viewer.theme,'light');
  bridge.setTheme('dark');await bridge.setView('3d');assert.equal(bridge.viewer.theme,'dark');
  await bridge.setView('pcb');assert.equal(bridge.viewer.renderer.dark,true);
  await bridge.setDocument(documentPayload());assert.equal(bridge.viewer.renderer.dark,true);
  assert.equal(page.documentElement.getAttribute('data-theme'),'dark');
  bridge.dispose();assert.equal(bridge.setTheme('light'),false);
});
