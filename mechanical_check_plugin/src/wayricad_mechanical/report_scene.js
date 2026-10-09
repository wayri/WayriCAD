/* Self-contained offline WebGL scene; geometry queries never modify the saved boards. */
const vecSub=(a,b)=>a.map((v,i)=>v-b[i]);
const vecDot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const vecCross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const vecLength=a=>Math.hypot(...a);
const pairKey=(a,b)=>[a,b].sort().join('\u0000');
const validPoint=p=>Array.isArray(p)&&p.length===3&&p.every(Number.isFinite);
const boardKind=k=>k==='board'||k==='comparison_board';
const solidKind=k=>k==='component'||k==='comparison_component';

class ConflictScene {
  constructor(canvas,report){
    this.canvas=canvas;this.report=report;this.gl=canvas.getContext('webgl',{antialias:true,alpha:false,preserveDrawingBuffer:true});
    this.yaw=-1;this.pitch=.75;this.zoom=1;this.center=[0,0,0];this.span=100;
    this.selected=null;this.isolate=false;this.ghost=true;this.section=false;this.sectionDirection='Y';this.showReferenceLabels=true;
    this.selectedReference=null;this.pairRefs=[];this.mode='select';this.probes=[];this.pendingPoint=null;this.hoverHit=null;this.hoverWitness=null;
    const measurements=ConflictScene.loadMeasurements(report);this.rulers=measurements.rulers;this.proximity=measurements.proximity;
    this.proximityByRef=new Map();
    for(const record of this.proximity.values())for(const ref of record.refs){if(!this.proximityByRef.has(ref))this.proximityByRef.set(ref,[]);this.proximityByRef.get(ref).push(record)}
    this.measureBuffers=new Map();this.metrics={triangleTests:0,boxTests:0,frames:0};
    if(!this.gl){canvas.style.display='none';canvas.after(Object.assign(document.createElement('p'),{textContent:'WebGL is unavailable. Open this offline report in a browser with hardware acceleration to inspect 3D geometry.'}));return}
    const g=this.gl;
    const vertex=`attribute vec3 p;attribute vec3 n;uniform mat4 m;varying vec3 normal;varying vec3 pos;void main(){normal=n;pos=p;gl_Position=m*vec4(p,1.);gl_PointSize=8.;}`;
    const fragment=`precision highp float;varying vec3 normal;varying vec3 pos;uniform vec4 color;uniform vec3 eye;uniform float unlit;uniform float cut;uniform vec3 cutNormal;uniform float cutOffset;void main(){if(cut>0.5&&dot(pos,cutNormal)<cutOffset)discard;vec3 N=normalize(normal);if(!gl_FrontFacing)N=-N;vec3 L=normalize(vec3(.2,-.4,1.));vec3 V=normalize(eye-pos);float d=max(dot(N,L),0.);float f=max(dot(N,normalize(vec3(-.8,.3,.3))),0.);float s=pow(max(dot(N,normalize(L+V)),0.),40.)*.3;vec3 shaded=color.rgb*(.30+.64*d+.25*f)+vec3(s);gl_FragColor=vec4(mix(shaded,color.rgb,unlit),color.a);}`;
    const shader=(type,source)=>{const s=g.createShader(type);g.shaderSource(s,source);g.compileShader(s);if(!g.getShaderParameter(s,g.COMPILE_STATUS))throw Error(g.getShaderInfoLog(s));return s};
    const vs=shader(g.VERTEX_SHADER,vertex),fs=shader(g.FRAGMENT_SHADER,fragment);
    this.program=g.createProgram();g.attachShader(this.program,vs);g.attachShader(this.program,fs);g.linkProgram(this.program);
    if(!g.getProgramParameter(this.program,g.LINK_STATUS))throw Error(g.getProgramInfoLog(this.program));
    g.detachShader(this.program,vs);g.detachShader(this.program,fs);g.deleteShader(vs);g.deleteShader(fs);
    this.attributes=['p','n'].map(n=>g.getAttribLocation(this.program,n));
    this.uniforms={};for(const n of ['m','color','eye','unlit','cut','cutNormal','cutOffset'])this.uniforms[n]=g.getUniformLocation(this.program,n);
    this.cache=new Map();this.bodies=(report.bodies||[]).map(b=>({...b,buffer:this.buffer(b.mesh)}));
    this.bodiesByRef=new Map();for(const body of this.bodies){if(!this.bodiesByRef.has(body.ref))this.bodiesByRef.set(body.ref,[]);this.bodiesByRef.get(body.ref).push(body)}
    this.outlineBuffers=ConflictScene.outlineSegments(report.board_outline).map(polyline=>({hole:polyline.hole,buffer:this.segmentBuffer(polyline.segments)}));
    this.grid=this.makeGrid();
    this.readout=document.createElement('p');this.readout.className='scene-readout';this.readout.setAttribute('role','status');this.readout.setAttribute('aria-live','polite');this.readout.textContent='Hover for surface XYZ and known closest approach. Drag to orbit; Shift-drag to pan.';
    this.probeList=document.createElement('p');this.probeList.className='probe-list';
    this.overlay=document.createElementNS('http://www.w3.org/2000/svg','svg');this.overlay.setAttribute('class','scene-overlay');this.overlay.setAttribute('aria-hidden','true');
    const wrap=document.createElement('div');wrap.className='scene-viewport';canvas.parentNode.insertBefore(wrap,canvas);wrap.append(canvas,this.overlay);
    wrap.after(this.readout,this.probeList);
    this.onResize=()=>this.draw();this.resizeObserver=new ResizeObserver(this.onResize);this.resizeObserver.observe(canvas);
    this.onPointerDown=e=>{this.drag={x:e.clientX,y:e.clientY,start:[e.clientX,e.clientY],pan:e.button===2||e.shiftKey,moved:false};canvas.setPointerCapture(e.pointerId)};
    this.onPointerUp=e=>{const drag=this.drag;this.drag=null;if(drag&&!drag.moved&&e.button===0)this.clickHit(this.pick(e.clientX,e.clientY),e.ctrlKey)};
    this.onPointerMove=e=>{const drag=this.drag;if(!drag){const now=performance.now();if(now-this.lastHover<60)return;this.lastHover=now;this.hoverHit=this.pick(e.clientX,e.clientY);this.hoverWitness=this.hoverHit?this.nearestRecord(this.hoverHit.reference):null;canvas.style.cursor=this.hoverHit?'crosshair':'default';this.updateReadout();this.draw();return}
      const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(e.clientX-drag.start[0],e.clientY-drag.start[1])>4)drag.moved=true;
      if(drag.pan){const a=this.span/Math.max(1,canvas.clientHeight)/this.zoom;this.center[0]+=(-Math.sin(this.yaw)*dx+Math.cos(this.yaw)*Math.sin(this.pitch)*dy)*a;this.center[1]+=(Math.cos(this.yaw)*dx+Math.sin(this.yaw)*Math.sin(this.pitch)*dy)*a;this.center[2]+=Math.cos(this.pitch)*dy*a}
      else{this.yaw-=dx*.008;this.pitch=Math.max(-1.55,Math.min(1.55,this.pitch+dy*.008))}
      drag.x=e.clientX;drag.y=e.clientY;this.draw()};
    this.onWheel=e=>{e.preventDefault();this.zoom=Math.max(.1,Math.min(30,this.zoom*Math.exp(-e.deltaY*.001)));this.draw()};
    this.onContextMenu=e=>e.preventDefault();
    for(const [name,listener] of [['pointerdown',this.onPointerDown],['pointerup',this.onPointerUp],['pointermove',this.onPointerMove],['wheel',this.onWheel],['contextmenu',this.onContextMenu]])canvas.addEventListener(name,listener);
    this.fit();
  }
  static loadMeasurements(report){
    const rulers=(Array.isArray(report.point_rulers)?report.point_rulers:[]).filter(r=>r.points?.length===2&&r.points.every(validPoint)).map(r=>({...r,kind:'points'}));
    const proximity=new Map();
    for(const record of [...(Array.isArray(report.proximity)?report.proximity:[]),...(Array.isArray(report.measurements)?report.measurements:[])]){
      if(record.type==='point_ruler'||!Array.isArray(record.refs)||record.refs.length!==2||!Number.isFinite(Number(record.distance_mm)))continue;
      const key=pairKey(...record.refs),previous=proximity.get(key);
      const quality=r=>String(r.evidence||'').toLowerCase().includes('exact step')?2:1;
      if(!previous||quality(record)>quality(previous)||(quality(record)===quality(previous)&&Number(record.distance_mm)<Number(previous.distance_mm)))proximity.set(key,record);
    }
    return {rulers,proximity};
  }
  static outlineSegments(outline){
    if(outline?.status!=='available'||!Array.isArray(outline.polylines))return [];
    const result=[];
    for(const polyline of outline.polylines){
      const points=polyline?.points;
      if(!Array.isArray(points)||points.length<2||!points.every(validPoint))continue;
      const segments=[];for(let i=0;i<points.length-1;i++)segments.push([points[i],points[i+1]]);
      if(polyline.closed&&points.length>=3)segments.push([points.at(-1),points[0]]);
      result.push({hole:!!polyline.hole,segments});
    }
    return result;
  }
  destroy(){
    if(this.frameId)cancelAnimationFrame(this.frameId);
    this.resizeObserver?.disconnect();
    const canvas=this.canvas;for(const [name,listener] of [['pointerdown',this.onPointerDown],['pointerup',this.onPointerUp],['pointermove',this.onPointerMove],['wheel',this.onWheel],['contextmenu',this.onContextMenu]])canvas.removeEventListener(name,listener);
    if(this.gl){for(const b of this.bodies)if(b.buffer)this.gl.deleteBuffer(b.buffer.buffer);for(const b of this.outlineBuffers)if(b.buffer)this.gl.deleteBuffer(b.buffer.buffer);for(const entry of this.cache.values())if(entry)this.gl.deleteBuffer(entry.buffer);for(const entry of this.measureBuffers.values())this.gl.deleteBuffer(entry.buffer);if(this.markerBuffer)this.gl.deleteBuffer(this.markerBuffer);if(this.grid)this.gl.deleteBuffer(this.grid.buffer);this.gl.deleteProgram(this.program)}
    this.overlay?.remove();this.readout?.remove();this.probeList?.remove();
  }
  setMode(mode){if(!['select','parts','points'].includes(mode))return;this.mode=mode;this.pendingPoint=null;this.pairRefs=[];this.lastPairResult=null;this.updateReadout();this.draw()}
  setPartFilter(query){this.partFilter=String(query||'').trim().toLowerCase()}
  eligibleBodies(){return (this.bodies||[]).filter(b=>solidKind(b.kind)&&b.mesh?.faces?.length)}
  visibleBody(body){if(this.selected&&this.isolate&&!this.selected.refs?.includes(body.ref)&&!boardKind(body.kind))return false;return true}
  sectionPlane(){const dir=this.sectionDirection,raw=dir==='Custom'?(this.report.rules?.section_normal||[0,1,0]):dir==='X'?[1,0,0]:dir==='Z'?[0,0,1]:[0,1,0],len=vecLength(raw)||1,normal=raw.map(v=>v/len),origin=this.selected?.section_origin||this.center;return {normal,offset:vecDot(normal,origin)}}
  nearestRecord(ref){
    let best=null,fallback=null;
    for(const record of this.proximityByRef?.get(ref)||this.proximity.values()){
      if(!record.refs.includes(ref))continue;
      const other=record.refs.find(r=>r!==ref);
      const bodies=this.bodiesByRef?.get(other)||this.bodies.filter(b=>b.ref===other);
      if(!other||!bodies.some(b=>this.visibleBody(b)))continue;
      if(!fallback||Number(record.distance_mm)<Number(fallback.distance_mm))fallback=record;
      if(record.nearest_for?.includes(ref)&&(!best||Number(record.distance_mm)<Number(best.distance_mm)))best=record;
    }
    return best||fallback;
  }
  measurePair(a,b){
    if(!a||!b||a===b)return this.announceMeasurement({error:'Choose two different parts.'});
    const record=this.proximity.get(pairKey(a,b));
    if(!record)return this.announceMeasurement({error:'Part gap unavailable in this offline report. Run Mechanical Check, measure these two parts and export a new report.'});
    const ruler={...record,kind:'parts',label:`${a} ↔ ${b}`};
    this.rulers.push(ruler);this.pairRefs=[a,b];this.draw();return this.announceMeasurement(ruler);
  }
  announceMeasurement(result){
    this.lastPairResult=result;
    if(this.canvas?.dispatchEvent&&typeof CustomEvent!=='undefined')this.canvas.dispatchEvent(new CustomEvent('wayricad-measure',{detail:result}));
    return result;
  }
  clickHit(hit,ctrlKey=false){
    if(!hit)return;
    if(this.mode==='points'){
      if(!this.pendingPoint){this.pendingPoint=hit;this.updateReadout();this.draw();return}
      const a=this.pendingPoint,b=hit;this.pendingPoint=null;
      this.rulers.push({kind:'points',refs:[a.reference,b.reference],points:[a.position,b.position],distance_mm:vecLength(vecSub(a.position,b.position)),unit:'mm',evidence:'picked tessellated surface points',label:`${a.reference} ↔ ${b.reference}`});
    }else if(this.mode==='parts'){
      if(this.pairRefs.length===2)this.pairRefs=[];
      if(!this.pairRefs.includes(hit.reference))this.pairRefs=this.pairRefs.concat(hit.reference);
      if(this.pairRefs.length===2)this.lastPairResult=this.measurePair(...this.pairRefs);
    }else if(ctrlKey){
      if(this.probes.length<256)this.probes.push(hit);
      this.probeList.textContent=this.probes.map((p,i)=>`P${i+1} ${p.reference}: ${p.position.map(v=>v.toFixed(3)).join(', ')} mm`).join(' | ');
    }else{
      this.selectedReference=hit.reference;this.canvas?.dispatchEvent(new CustomEvent('wayricad-select',{detail:hit}));
    }
    this.updateReadout(hit);this.draw();
  }
  clearMeasurements(){this.rulers=[];this.pendingPoint=null;this.pairRefs=[];this.lastPairResult=null;if(this.gl)for(const entry of this.measureBuffers.values())this.gl.deleteBuffer(entry.buffer);this.measureBuffers.clear();this.draw();this.updateReadout()}
  clearProbes(){this.probes=[];if(this.probeList)this.probeList.textContent='';this.draw()}
  updateReadout(hit=this.hoverHit){
    if(!this.readout)return;
    const point=hit?`${hit.reference} · X/Y/Z ${hit.position.map(v=>v.toFixed(3)).join(', ')} mm`:'No visible triangle under cursor';
    const record=hit?this.nearestRecord(hit.reference):null;
    const certified=record?.nearest_for?.includes(hit?.reference);
    const neighbor=record?` · ${certified?'Nearest part':'Nearest known measured pair'}: ${record.refs.find(r=>r!==hit.reference)} ${Number(record.distance_mm).toFixed(4)} mm (${record.evidence||'reported'})`:'';
    const prompt=this.mode==='points'?(this.pendingPoint?' · Pick second surface point':' · Pick first surface point'):this.mode==='parts'?(this.pairRefs.length===1?` · Pick part after ${this.pairRefs[0]}`:' · Pick two parts'):' · Ctrl-click to pin';
    this.readout.textContent=point+neighbor+prompt+(this.lastPairResult?.error?` · ${this.lastPairResult.error}`:'');
  }
  pick(clientX,clientY){
    if(!this.camera)return null;const r=this.canvas.getBoundingClientRect(),nx=2*(clientX-r.left)/r.width-1,ny=1-2*(clientY-r.top)/r.height,c=this.camera,t=Math.tan(18*Math.PI/180),ratio=r.width/r.height;
    const direction=c.z.map((v,i)=>-v+c.x[i]*nx*t*ratio+c.y[i]*ny*t),len=vecLength(direction);
    return this.pickRay(c.eye,direction.map(v=>v/len));
  }
  static boxHit(bounds,origin,dir,limit=Infinity){
    let near=0,far=limit;
    for(let i=0;i<3;i++){if(Math.abs(dir[i])<1e-15){if(origin[i]<bounds[i]||origin[i]>bounds[i+3])return false}
      else{const a=(bounds[i]-origin[i])/dir[i],b=(bounds[i+3]-origin[i])/dir[i];near=Math.max(near,Math.min(a,b));far=Math.min(far,Math.max(a,b));if(near>far)return false}}
    return true;
  }
  static buildTree(mesh){
    const faces=mesh.faces,vertices=mesh.vertices,ids=[];
    for(let i=0;i<faces.length;i++)if(faces[i]?.length===3&&faces[i].every(k=>validPoint(vertices[k])))ids.push(i);
    const boundOf=list=>{const bounds=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];for(const id of list)for(const k of faces[id])for(let i=0;i<3;i++){bounds[i]=Math.min(bounds[i],vertices[k][i]);bounds[i+3]=Math.max(bounds[i+3],vertices[k][i])}return bounds};
    const build=list=>{const bounds=boundOf(list);if(list.length<=16)return {bounds,ids:list};
      const axis=[0,1,2].sort((a,b)=>(bounds[b+3]-bounds[b])-(bounds[a+3]-bounds[a]))[0];
      list.sort((a,b)=>faces[a].reduce((s,k)=>s+vertices[k][axis],0)-faces[b].reduce((s,k)=>s+vertices[k][axis],0));
      const mid=list.length>>1;return {bounds,left:build(list.slice(0,mid)),right:build(list.slice(mid))}};
    return ids.length?build(ids):null;
  }
  pickRay(origin,direction){
    this.metrics ||= {triangleTests:0,boxTests:0,frames:0};this.metrics.triangleTests=0;this.metrics.boxTests=0;
    const plane=this.sectionPlane();let nearest=null,distance=Infinity;
    for(const body of this.bodies||[]){
      if(!this.visibleBody(body)||!body.mesh?.faces?.length)continue;
      if((this.mode==='parts'||this.ghost)&&boardKind(body.kind))continue;
      if(this.mode==='parts'&&!solidKind(body.kind))continue;
      if(this.partFilter&&solidKind(body.kind)&&!body.ref.toLowerCase().includes(this.partFilter))continue;
      if(body.bounds){this.metrics.boxTests++;if(!ConflictScene.boxHit(body.bounds,origin,direction,distance))continue}
      if(!body.pickTree)body.pickTree=ConflictScene.buildTree(body.mesh);
      if(!body.pickTree)continue;const stack=[body.pickTree],mesh=body.mesh;
      while(stack.length){
        const node=stack.pop();this.metrics.boxTests++;if(!ConflictScene.boxHit(node.bounds,origin,direction,distance))continue;
        if(!node.ids){stack.push(node.left,node.right);continue}
        for(const id of node.ids){
          this.metrics.triangleTests++;const [a,b,c]=mesh.faces[id].map(i=>mesh.vertices[i]),u=vecSub(b,a),v=vecSub(c,a),p=vecCross(direction,v),det=vecDot(u,p);
          if(Math.abs(det)<1e-12)continue;const q=vecSub(origin,a),bu=vecDot(q,p)/det;if(bu<0||bu>1)continue;
          const t=vecCross(q,u),bv=vecDot(direction,t)/det;if(bv<0||bu+bv>1)continue;
          const d=vecDot(v,t)/det;if(d<0||d>=distance)continue;
          const point=origin.map((value,i)=>value+d*direction[i]);
          if(this.section&&vecDot(point,plane.normal)<plane.offset-1e-9)continue;
          distance=d;nearest={reference:body.ref,position:point,distance:d};
        }
      }
    }
    return nearest;
  }
  buffer(mesh){
    if(!mesh?.faces?.length)return null;
    const values=[];for(const face of mesh.faces){const [a,b,c]=face.map(i=>mesh.vertices[i]);if(!validPoint(a)||!validPoint(b)||!validPoint(c))continue;
      const u=vecSub(b,a),v=vecSub(c,a);let n=vecCross(u,v),len=vecLength(n);if(len<1e-12)continue;n=n.map(x=>x/len);for(const p of [a,b,c])values.push(...p,...n)}
    if(!values.length)return null;const g=this.gl,buffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,buffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(values),g.STATIC_DRAW);return {buffer,count:values.length/6};
  }
  segmentBuffer(segments){
    if(!segments.length)return null;
    const data=segments.flatMap(([a,b])=>[...a,0,0,1,...b,0,0,1]);
    const g=this.gl,buffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,buffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STATIC_DRAW);
    return {buffer,count:data.length/6};
  }
  outlineBounds(){
    const outline=this.report.board_outline,b=outline?.bounds;
    return outline?.status==='available'&&Array.isArray(b)&&b.length===6&&b.every(Number.isFinite)?b:null;
  }
  makeGrid(){
    const boxes=this.bodies.filter(b=>b.bounds?.length===6&&boardKind(b.kind));
    const outline=this.outlineBounds();if(outline)boxes.push({bounds:outline});
    if(!boxes.length)return null;
    const lo=[0,1,2].map(i=>Math.min(...boxes.map(b=>b.bounds[i]))),hi=[0,1,2].map(i=>Math.max(...boxes.map(b=>b.bounds[i+3])));
    const span=Math.max(hi[0]-lo[0],hi[1]-lo[1],1),base=Math.pow(10,Math.floor(Math.log10(span/10)));
    const step=[1,2,5,10].map(v=>v*base).find(v=>v>=span/10)||base,z=lo[2]-.2,data=[];
    const add=(a,b)=>{data.push(...a,0,0,1,...b,0,0,1)};
    for(let x=Math.ceil(lo[0]/step)*step;x<=hi[0]+1e-6;x+=step)add([x,lo[1],z],[x,hi[1],z]);
    for(let y=Math.ceil(lo[1]/step)*step;y<=hi[1]+1e-6;y+=step)add([lo[0],y,z],[hi[0],y,z]);
    if(!data.length)return null;const g=this.gl,buffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,buffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STATIC_DRAW);return {buffer,count:data.length/6};
  }
  fit(refs){
    if(!this.gl)return;const outline=this.outlineBounds();
    let bodies=refs?this.bodies.filter(b=>b.bounds?.length===6&&refs.includes(b.ref)):[];
    if(!refs&&outline)bodies=[{bounds:outline}];
    else if(!refs){bodies=this.bodies.filter(b=>b.bounds?.length===6&&boardKind(b.kind));if(!bodies.length)bodies=this.bodies.filter(b=>b.bounds?.length===6)}
    if(!bodies.length)return;const low=[0,1,2].map(i=>Math.min(...bodies.map(b=>b.bounds[i]))),high=[0,1,2].map(i=>Math.max(...bodies.map(b=>b.bounds[i+3])));
    this.center=low.map((x,i)=>(x+high[i])/2);this.span=Math.max(4,vecLength(vecSub(high,low)));this.zoom=1;this.draw();
  }
  select(issue){
    this.selected=issue;if(!this.gl)return;
    if(issue?.conflict_mesh&&!this.cache.has(issue.id))this.cache.set(issue.id,this.buffer(issue.conflict_mesh));
    if(issue?.points?.length&&!this.cache.has(issue.id+'points'))this.cache.set(issue.id+'points',this.lineBuffer(issue.points[0]));
    this.fit(issue?.refs);
  }
  focus(){
    const b=this.selected?.conflict_bounds;if(b){this.center=[0,1,2].map(i=>(b[i]+b[i+3])/2);this.span=Math.max(2,vecLength([0,1,2].map(i=>b[i+3]-b[i])));this.zoom=1.4;this.draw()}
    else if(this.selected?.points?.length){const ps=this.selected.points[0];this.center=[0,1,2].map(i=>(ps[0][i]+ps[1][i])/2);this.span=Math.max(3,vecLength(vecSub(ps[0],ps[1]))*4);this.zoom=1.4;this.draw()}
  }
  view(direction){
    const v=direction===true?'top':direction===false?'iso':direction;
    if(v==='top'){this.yaw=-Math.PI/2;this.pitch=Math.PI/2-.0001}
    else if(v==='bottom'){this.yaw=-Math.PI/2;this.pitch=-Math.PI/2+.0001}
    else if(v==='side'){this.yaw=-Math.PI/2;this.pitch=0}
    else{this.yaw=-1;this.pitch=.75}
    this.draw();
  }
  lineBuffer(points){
    if(!Array.isArray(points)||points.length!==2||!points.every(validPoint))return null;
    const g=this.gl,buffer=g.createBuffer(),data=points.flatMap(p=>[...p,0,0,1]);
    g.bindBuffer(g.ARRAY_BUFFER,buffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STATIC_DRAW);return {buffer,count:2};
  }
  measurementBuffer(points){
    const key=JSON.stringify(points);
    if(!this.measureBuffers.has(key))this.measureBuffers.set(key,this.lineBuffer(points));
    return this.measureBuffers.get(key);
  }
  draw(){if(!this.gl||this.frameId)return;this.frameId=requestAnimationFrame(()=>{this.frameId=0;this.renderFrame()})}
  renderFrame(){
    if(!this.gl)return;const g=this.gl,c=this.canvas,dpr=window.devicePixelRatio||1,w=Math.max(1,Math.round(c.clientWidth*dpr)),h=Math.max(1,Math.round(c.clientHeight*dpr));
    if(c.width!==w)c.width=w;if(c.height!==h)c.height=h;
    g.viewport(0,0,w,h);g.clearColor(.91,.94,.965,1);g.clear(g.COLOR_BUFFER_BIT|g.DEPTH_BUFFER_BIT);
    g.enable(g.DEPTH_TEST);g.depthFunc(g.LEQUAL);g.enable(g.BLEND);g.blendFunc(g.SRC_ALPHA,g.ONE_MINUS_SRC_ALPHA);g.useProgram(this.program);
    const distance=this.span*1.8/this.zoom,eye=this.center.map((v,i)=>v+distance*[Math.cos(this.yaw)*Math.cos(this.pitch),Math.sin(this.yaw)*Math.cos(this.pitch),Math.sin(this.pitch)][i]);
    const norm=a=>{const n=vecLength(a)||1;return a.map(v=>v/n)};
    const z=norm(vecSub(eye,this.center)),x=norm(vecCross([0,0,1],z)),y=vecCross(z,x);
    const view=[x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-vecDot(x,eye),-vecDot(y,eye),-vecDot(z,eye),1];
    const near=Math.max(.001,distance/1000),far=Math.max(10000,distance*100),f=1/Math.tan(18*Math.PI/180);
    const projection=[f/(w/h),0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0],m=new Float32Array(16);
    for(let col=0;col<4;col++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)m[col*4+row]+=projection[k*4+row]*view[col*4+k];
    this.camera={eye,x,y,z,m};
    g.uniformMatrix4fv(this.uniforms.m,false,m);g.uniform3fv(this.uniforms.eye,eye);g.uniform1f(this.uniforms.unlit,0);
    const plane=this.sectionPlane();g.uniform3fv(this.uniforms.cutNormal,plane.normal);g.uniform1f(this.uniforms.cutOffset,plane.offset);g.uniform1f(this.uniforms.cut,this.section?1:0);
    const render=(entry,color,mode=g.TRIANGLES)=>{if(!entry)return;g.bindBuffer(g.ARRAY_BUFFER,entry.buffer);for(let i=0;i<2;i++){g.enableVertexAttribArray(this.attributes[i]);g.vertexAttribPointer(this.attributes[i],3,g.FLOAT,false,24,i*12)}g.uniform4fv(this.uniforms.color,color);g.drawArrays(mode,0,entry.count)};
    g.uniform1f(this.uniforms.cut,0);g.uniform1f(this.uniforms.unlit,1);render(this.grid,[.62,.72,.78,.5],g.LINES);g.uniform1f(this.uniforms.unlit,0);g.uniform1f(this.uniforms.cut,this.section?1:0);
    g.uniform1f(this.uniforms.unlit,1);for(const polyline of this.outlineBuffers)render(polyline.buffer,polyline.hole?[.23,.39,.58,1]:[.04,.42,.43,1],g.LINES);g.uniform1f(this.uniforms.unlit,0);
    for(const body of this.bodies){
      if(boardKind(body.kind)||!this.visibleBody(body))continue;
      const chosen=this.pairRefs.includes(body.ref)||body.ref===this.selectedReference;
      render(body.buffer,chosen?[.05,.85,.72,1]:body.kind.includes('allowance')||body.kind.includes('envelope')?[.94,.65,.22,1]:body.kind==='comparison_component'?[.86,.56,.29,1]:[.64,.68,.74,1]);
    }
    g.depthMask(!this.ghost);
    for(const body of this.bodies)if(boardKind(body.kind))render(body.buffer,body.kind==='board'?[.17,.48,.39,this.ghost?0.24:1]:[.23,.43,.73,this.ghost?0.24:1]);
    g.depthMask(true);g.uniform1f(this.uniforms.cut,0);g.disable(g.DEPTH_TEST);g.uniform1f(this.uniforms.unlit,1);
    if(this.selected){render(this.cache.get(this.selected.id),[.96,.12,.1,.95]);const points=this.cache.get(this.selected.id+'points');render(points,[.96,.12,.1,1],g.LINES);render(points,[.96,.12,.1,1],g.POINTS)}
    const lines=[];
    for(const ruler of this.rulers)if(Array.isArray(ruler.points)&&ruler.points.length===2&&ruler.points.every(validPoint))lines.push(ruler);
    if(this.hoverWitness?.points?.length===2&&this.hoverWitness.points.every(validPoint))lines.push({...this.hoverWitness,hover:true});
    for(const ruler of lines){const entry=this.measurementBuffer(ruler.points);render(entry,ruler.hover?[.94,.2,.28,1]:[.08,.38,.9,1],g.LINES);render(entry,ruler.hover?[.94,.2,.28,1]:[.08,.38,.9,1],g.POINTS)}
    const markers=[...this.probes,...(this.pendingPoint?[this.pendingPoint]:[]),...(this.hoverHit?[this.hoverHit]:[])];
    if(markers.length){if(!this.markerBuffer)this.markerBuffer=g.createBuffer();const data=markers.flatMap(hit=>[...hit.position,0,0,1]);g.bindBuffer(g.ARRAY_BUFFER,this.markerBuffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STREAM_DRAW);render({buffer:this.markerBuffer,count:markers.length},[.03,.75,.62,1],g.POINTS)}
    g.enable(g.DEPTH_TEST);this.drawOverlay(lines);this.metrics.frames++;
  }
  project(point){
    const m=this.camera?.m;if(!m)return null;const v=[...point,1],p=[0,0,0,0];
    for(let row=0;row<4;row++)for(let col=0;col<4;col++)p[row]+=m[col*4+row]*v[col];
    if(p[3]<=0)return null;return [(p[0]/p[3]+1)*this.canvas.clientWidth/2,(1-p[1]/p[3])*this.canvas.clientHeight/2];
  }
  referenceLabelItems(){
    if(!this.showReferenceLabels)return [];
    const plane=this.sectionPlane(),seen=new Set(),items=[];
    const bodies=this.bodies.filter(b=>solidKind(b.kind)&&this.visibleBody(b)&&b.bounds?.length===6);
    bodies.sort((a,b)=>{
      const pa=Number(this.pairRefs.includes(a.ref)||a.ref===this.selectedReference||a.ref===this.hoverHit?.reference),pb=Number(this.pairRefs.includes(b.ref)||b.ref===this.selectedReference||b.ref===this.hoverHit?.reference);
      return pb-pa||a.ref.localeCompare(b.ref,undefined,{numeric:true});
    });
    for(const body of bodies){
      if(seen.has(body.ref))continue;seen.add(body.ref);
      if(this.section){const max=plane.normal.reduce((sum,n,i)=>sum+n*(n>=0?body.bounds[i+3]:body.bounds[i]),0);if(max<plane.offset-1e-9)continue}
      const center=[0,1,2].map(i=>(body.bounds[i]+body.bounds[i+3])/2),anchor=this.project(center);
      if(!anchor||anchor[0]<0||anchor[0]>this.canvas.clientWidth||anchor[1]<0||anchor[1]>this.canvas.clientHeight)continue;
      const selected=this.pairRefs.includes(body.ref)||body.ref===this.selectedReference||body.ref===this.hoverHit?.reference;
      items.push({kind:'ref',text:body.ref,anchor,priority:selected?2:1,color:selected?'#087f86':'#344f60'});
      if(items.length>=80)break;
    }
    return items;
  }
  static layoutLabels(items,width,height,scaleWidth=158){
    const placed=[],occupied=[{x:7,y:height-62,w:scaleWidth,h:56}];
    const offsets=r=>r===0?[[0,0]]:[[0,-r],[r,0],[0,r],[-r,0],[r*.707,-r*.707],[r*.707,r*.707],[-r*.707,r*.707],[-r*.707,-r*.707]];
    const overlaps=(a,b)=>a.x<b.x+b.w+4&&a.x+a.w+4>b.x&&a.y<b.y+b.h+4&&a.y+a.h+4>b.y;
    const sorted=items.map((item,index)=>({...item,index})).sort((a,b)=>b.priority-a.priority||a.index-b.index);
    for(const item of sorted){
      const w=Math.max(24,item.text.length*(item.kind==='ruler'?7.3:7)+10),h=21;
      const radii=item.kind==='ruler'?[0,20,40,60,80,105,130,160,190]:[15,30,45,60,78,98];
      let box=null;
      for(const radius of radii){for(const [dx,dy] of offsets(radius)){
        const candidate={x:item.anchor[0]+dx-w/2,y:item.anchor[1]+dy-h/2,w,h};
        if(candidate.x<4||candidate.y<4||candidate.x+w>width-4||candidate.y+h>height-4)continue;
        if(occupied.some(other=>overlaps(candidate,other)))continue;
        box=candidate;break;
      }if(box)break}
      if(!box)continue;occupied.push(box);placed.push({...item,box});
    }
    return placed;
  }
  drawOverlay(lines){
    if(!this.overlay)return;
    this.overlay.replaceChildren();this.overlay.setAttribute('viewBox',`0 0 ${this.canvas.clientWidth} ${this.canvas.clientHeight}`);
    const ns='http://www.w3.org/2000/svg',shape=(tag,attrs)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));this.overlay.append(n);return n};
    const scale=Math.pow(10,Math.floor(Math.log10(Math.max(.001,this.span/8)))),unit=[1,2,5,10].map(n=>n*scale).find(n=>n>=this.span/8)||scale;
    const start=this.project(this.center),end=this.project([this.center[0]+unit,this.center[1],this.center[2]]);
    const scalePx=start&&end?Math.hypot(end[0]-start[0],end[1]-start[1]):0;
    const scaleVisible=scalePx>10&&scalePx<this.canvas.clientWidth*.8;
    if(scaleVisible){
      shape('line',{x1:18,y1:this.canvas.clientHeight-24,x2:18+scalePx,y2:this.canvas.clientHeight-24,stroke:'#294556','stroke-width':3});
      const caption=shape('text',{x:18,y:this.canvas.clientHeight-31,fill:'#294556','font-size':12});caption.textContent=`${unit} mm`;
    }
    const labels=[];
    for(const ruler of lines){const a=this.project(ruler.points[0]),b=this.project(ruler.points[1]);if(!a||!b)continue;
      const dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1,tx=-dy/len*7,ty=dx/len*7,color=ruler.hover?'#da3241':'#1459bd';
      for(const p of [a,b])shape('line',{x1:p[0]-tx,y1:p[1]-ty,x2:p[0]+tx,y2:p[1]+ty,stroke:color,'stroke-width':2});
      labels.push({kind:'ruler',text:`${ruler.kind==='points'?'Points':'Gap'} ${Number(ruler.distance_mm).toFixed(3)} mm`,anchor:[(a[0]+b[0])/2,(a[1]+b[1])/2],priority:ruler.hover?4:3,color});
    }
    labels.push(...this.referenceLabelItems());
    for(const label of ConflictScene.layoutLabels(labels,this.canvas.clientWidth,this.canvas.clientHeight,scaleVisible?Math.max(158,scalePx+32):158)){
      const b=label.box,fill=label.kind==='ruler'?'#fff':'#f7fbfc';
      if(label.kind==='ruler'&&Math.hypot(b.x+b.w/2-label.anchor[0],b.y+b.h/2-label.anchor[1])>25)shape('line',{x1:label.anchor[0],y1:label.anchor[1],x2:b.x+b.w/2,y2:b.y+b.h/2,stroke:label.color,'stroke-width':1,opacity:.7});
      shape('rect',{x:b.x,y:b.y,width:b.w,height:b.h,rx:4,fill,stroke:label.color,'stroke-width':1,opacity:.96});
      const node=shape('text',{x:b.x+5,y:b.y+15,fill:label.color,'font-size':label.kind==='ruler'?13:12,'font-weight':label.kind==='ruler'?700:600});
      node.textContent=label.text;
    }
  }
}
