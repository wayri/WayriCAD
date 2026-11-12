import test from 'node:test';
import assert from 'node:assert/strict';
import {createReviewBridge, projectWorld, screenToWorld, overlaysRegistered} from '../web/bridge.mjs';

const rect={left:10,top:20,width:800,height:500};
const state={center:{x:40,y:30},zoom:4,flipped:false};
const scope={repository:'example/board',ref:'a'.repeat(40),file:'board.kicad_pcb'};
const payload=(extra={})=>({path:'board.kicad_pcb',source:'(kicad_pcb)',source_sha256:'b'.repeat(64),scope,...extra});
const comments=()=>({scope,status:'synced',path:scope.file,source_sha256:'b'.repeat(64),
  markers:[{comment_id:'1',anchor:{...scope,kind:'position',position:{x:20,y:15}},x:20,y:15}]});

class Element extends EventTarget {
  constructor(){super();this.children=[];this.style={};this.attributes={};}
  append(...items){for(const item of items){item.remove?.();item.parent=this;this.children.push(item);}}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(item=>item!==this);this.parent=null;}
  replaceChildren(...items){for(const item of this.children)item.parent=null;this.children=[];this.append(...items);}
  setAttribute(key,value){this.attributes[key]=value;}
  getBoundingClientRect(){return rect;}
  querySelector(){return null;}
  querySelectorAll(tag){return this.children.flatMap(item=>[...(item.tag===tag?[item]:[]),...(item.querySelectorAll?.(tag)||[])]);}
}
const dom={createElement(tag){const e=new Element();e.tag=tag;return e;},createElementNS(_ns,tag){return this.createElement(tag);},createTextNode(text){return {textContent:text};},documentElement:new Element()};
const emit=(target,type,detail)=>target.dispatchEvent(Object.assign(new Event(type),{detail}));
class PublicViewer extends EventTarget {
  constructor(){super();this.stage=new Element();this.surface=new Element();this.camera=structuredClone(state);this.fitCount=0;this.explode=0;}
  async loadSource(source,{path,view,signal}){if(signal.aborted)return false;this.source=source;this.path=path;this.kind=view;this.view=view;return true;}
  async setView(view,{signal}={}){if(signal?.aborted)return false;this.view=view;return true;}
  getCamera(){return this.view==='3d'?null:structuredClone(this.camera);}
  setCamera(value){this.camera=structuredClone(value);emit(this,'camerachange',{path:this.path,view:this.view,camera:value});}
  getLayers(){return ['F.Cu','B.Cu'];}
  getLayerState(){return {visible:['F.Cu']};}
  setTheme(){}
  fit(){this.fitCount++;}
  getExplode(){return this.explode;}
  selectObject(uuid){this.selected=uuid;return true;}
  getSelectionPosition(){return {x:25,y:17,layer:'F.Cu'};}
  dispose(){this.disposed=true;}
}
function fixture(ViewerClass=PublicViewer){
  const ids=['viewer','overlay','status','documents','layers','layers-toggle','view-pcb','view-schematic','view-3d','view-manufacturing','mode-pan','mode-pin','mode-region','fit'];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  const messages=[];
  const api=createReviewBridge({ViewerClass,elements,document:dom,postMessage:value=>messages.push(value),raf:()=>1,cancelRaf:()=>{}});
  return {api,elements,messages};
}

test('public copied camera projects/unprojects exactly, including flip and resize',()=>{
  for(const flipped of [false,true])for(const size of [rect,{...rect,width:390,height:650}]){
    const viewer={view:'pcb',getCamera:()=>({...state,flipped})};
    const at=projectWorld(viewer,{x:20,y:15},size);
    assert.deepEqual(screenToWorld(viewer,at.x,at.y,size),{x:20,y:15});
    assert.equal(at.x,size.width/2+(flipped?80:-80));
  }
  assert.equal(projectWorld({view:'pcb',getCamera:()=>null},{x:1,y:1},rect),null);
});

test('exploded or unknown 3D registration never projects guessed anchors',()=>{
  let explode=0;
  const viewer={view:'3d',getExplode:()=>explode,renderer:{projectAnchor:()=>({x:30,y:40,visible:true})}};
  assert.deepEqual(projectWorld(viewer,{x:1,y:1},rect),{x:20,y:20});
  for(const value of [1,40,NaN,undefined]){explode=value;assert.equal(overlaysRegistered(viewer),false);assert.equal(projectWorld(viewer,{x:1,y:1},rect),null);}
});

test('public camera events repaint and comment focus preserves zoom/flip',async()=>{
  const {api,elements}=fixture();await api.setDocument(payload());api.setComments(comments());
  assert.equal(api.viewer.fitCount,0,'upstream already fits/restores each source-bound camera');
  assert.equal(elements.overlay.children.length,1);
  api.viewer.setCamera({...state,zoom:9,flipped:true});
  assert.equal(elements.overlay.children[0].children[0].attributes.cx,'580');
  api.focusComment('1');
  assert.deepEqual(api.viewer.camera,{center:{x:20,y:15},zoom:9,flipped:true});
  api.dispose();
});

test('saved UUID selection uses public selection position, not a reference guess',async()=>{
  const {api}=fixture();await api.setDocument(payload());const value=comments();value.markers[0].anchor.uuid='saved-uuid';api.setComments(value);
  api.focusComment('1');assert.equal(api.viewer.selected,'saved-uuid');assert.deepEqual(api.viewer.camera.center,{x:25,y:17});api.dispose();
});

test('same-view navigation does not remount or refit the public camera',async()=>{
  const {api}=fixture();await api.setDocument(payload());api.viewer.setView=()=>{throw Error('unexpected remount');};
  assert.equal(await api.setView('pcb'),true);assert.equal(api.viewer.fitCount,0);api.dispose();
});

test('source replacement revokes authority until its actual load completes',async()=>{
  let release;
  class Delayed extends PublicViewer{async loadSource(source,options){if(source.includes('pending'))await new Promise(resolve=>{release=resolve;});return super.loadSource(source,options);}}
  const {api,elements}=fixture(Delayed);await api.setDocument(payload());api.setComments(comments());
  const stale=api.setDocument(payload({source:'(kicad_pcb (name pending))'}));
  assert.equal(api.setComments(comments()),0);assert.equal(api.authorized,false);assert.equal(elements.overlay.children.length,0);
  assert.equal(await api.setDocument(payload({source:'(kicad_pcb (name newer))'})),true);release();assert.equal(await stale,false);
  assert.equal(api.viewer.source,'(kicad_pcb (name newer))');api.dispose();
});

test('replacing a source aborts pending 3D navigation and ignores its completion',async()=>{
  let release;
  class Delayed extends PublicViewer{async setView(view,options){await new Promise(resolve=>{release=resolve;});return super.setView(view,options);}}
  const {api}=fixture(Delayed);await api.setDocument(payload());const stale=api.setView('3d');
  await api.setDocument(payload({source:'(kicad_pcb (name newer))'}));release();assert.equal(await stale,false);assert.equal(api.viewer.view,'pcb');api.dispose();
});

test('choosing the current PCB cancels an in-flight 3D switch',async()=>{
  let release;
  class Delayed extends PublicViewer{async setView(view,options){await new Promise(resolve=>{release=resolve;});return super.setView(view,options);}}
  const {api}=fixture(Delayed);await api.setDocument(payload());const stale=api.setView('3d');
  assert.equal(await api.setView('pcb'),true);release();assert.equal(await stale,false);assert.equal(api.viewer.view,'pcb');api.dispose();
});
