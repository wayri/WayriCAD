/* Offline WebGL scene. No remote scripts, no network calls. */
class ConflictScene {
  constructor(canvas,report) {
    this.canvas=canvas;this.report=report;this.gl=canvas.getContext('webgl',{antialias:true,alpha:false,preserveDrawingBuffer:true});
    this.yaw=-1;this.pitch=.75;this.zoom=1;this.center=[0,0,0];this.span=100;this.selected=null;this.isolate=true;this.ghost=true;this.section=false;
    if(!this.gl){canvas.style.display='none';canvas.after(Object.assign(document.createElement('p'),{textContent:'WebGL is unavailable. Open this report in a browser with hardware acceleration to inspect 3D geometry.'}));return;}
    const g=this.gl;
    const vertex=`attribute vec3 p;attribute vec3 n;uniform mat4 m;varying vec3 normal;varying vec3 pos;void main(){normal=n;pos=p;gl_Position=m*vec4(p,1.);gl_PointSize=7.;}`;
    const fragment=`precision highp float;varying vec3 normal;varying vec3 pos;uniform vec4 color;uniform vec3 eye;uniform float unlit;uniform float cut;uniform float cutY;void main(){if(cut>0.5&&pos.y<cutY)discard;vec3 N=normalize(normal);if(!gl_FrontFacing)N=-N;vec3 L=normalize(vec3(.2,-.4,1.));vec3 V=normalize(eye-pos);float d=max(dot(N,L),0.);float f=max(dot(N,normalize(vec3(-.8,.3,.3))),0.);float s=pow(max(dot(N,normalize(L+V)),0.),40.)*.3;vec3 shaded=color.rgb*(.30+.64*d+.25*f)+vec3(s);gl_FragColor=vec4(mix(shaded,color.rgb,unlit),color.a);}`;
    const shader=(type,source)=>{const s=g.createShader(type);g.shaderSource(s,source);g.compileShader(s);if(!g.getShaderParameter(s,g.COMPILE_STATUS))throw Error(g.getShaderInfoLog(s));return s};
    this.program=g.createProgram();g.attachShader(this.program,shader(g.VERTEX_SHADER,vertex));g.attachShader(this.program,shader(g.FRAGMENT_SHADER,fragment));g.linkProgram(this.program);if(!g.getProgramParameter(this.program,g.LINK_STATUS))throw Error(g.getProgramInfoLog(this.program));g.useProgram(this.program);
    this.attributes=['p','n'].map(n=>g.getAttribLocation(this.program,n));this.uniforms={};for(const n of ['m','color','eye','unlit','cut','cutY'])this.uniforms[n]=g.getUniformLocation(this.program,n);
    this.cache=new Map();this.bodies=report.bodies.map(b=>({...b,buffer:this.buffer(b.mesh)}));
    let drag=null;
    canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY,e.button===2||e.shiftKey];canvas.setPointerCapture(e.pointerId)};
    canvas.onpointerup=()=>drag=null;canvas.oncontextmenu=e=>e.preventDefault();
    canvas.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag[0],dy=e.clientY-drag[1];if(drag[2]){const a=this.span/canvas.clientHeight/this.zoom;this.center[0]+=(-Math.sin(this.yaw)*dx+Math.cos(this.yaw)*Math.sin(this.pitch)*dy)*a;this.center[1]+=(Math.cos(this.yaw)*dx+Math.sin(this.yaw)*Math.sin(this.pitch)*dy)*a;this.center[2]+=Math.cos(this.pitch)*dy*a;}else{this.yaw-=dx*.008;this.pitch=Math.max(-1.5,Math.min(1.5,this.pitch+dy*.008));}drag=[e.clientX,e.clientY,drag[2]];this.draw()};
    canvas.onwheel=e=>{e.preventDefault();this.zoom=Math.max(.1,Math.min(30,this.zoom*Math.exp(-e.deltaY*.001)));this.draw()};
    new ResizeObserver(()=>this.draw()).observe(canvas);this.fit();
  }
  buffer(mesh){
    if(!mesh||!mesh.faces.length)return null;
    const values=[];for(const face of mesh.faces){const [a,b,c]=face.map(i=>mesh.vertices[i]),u=b.map((x,i)=>x-a[i]),v=c.map((x,i)=>x-a[i]);let n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],len=Math.hypot(...n);if(len<1e-12)continue;n=n.map(x=>x/len);for(const p of [a,b,c])values.push(...p,...n);}
    const g=this.gl,buffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,buffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(values),g.STATIC_DRAW);return {buffer,count:values.length/6};
  }
  fit(refs){
    if(!this.gl)return;const bodies=this.bodies.filter(b=>!refs||refs.includes(b.ref));if(!bodies.length)return;
    const low=[0,1,2].map(i=>Math.min(...bodies.map(b=>b.bounds[i]))),high=[0,1,2].map(i=>Math.max(...bodies.map(b=>b.bounds[i+3])));
    this.center=low.map((x,i)=>(x+high[i])/2);this.span=Math.max(4,Math.hypot(...high.map((x,i)=>x-low[i])));this.zoom=1;this.draw();
  }
  select(issue){this.selected=issue;if(!this.gl)return;if(issue&&!this.cache.has(issue.id))this.cache.set(issue.id,this.buffer(issue.conflict_mesh));if(issue?.points?.length&&!this.cache.has(issue.id+'points')){const g=this.gl,buffer=g.createBuffer(),data=[];for(const p of issue.points[0])data.push(...p,0,0,1);g.bindBuffer(g.ARRAY_BUFFER,buffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STATIC_DRAW);this.cache.set(issue.id+'points',{buffer,count:2});}this.fit(issue?issue.refs:null);}
  focus(){const b=this.selected?.conflict_bounds;if(b){this.center=[0,1,2].map(i=>(b[i]+b[i+3])/2);this.span=Math.max(2,Math.hypot(...[0,1,2].map(i=>b[i+3]-b[i])));this.zoom=1.4;this.draw()}else if(this.selected?.points?.length){const ps=this.selected.points[0];this.center=[0,1,2].map(i=>(ps[0][i]+ps[1][i])/2);this.span=Math.max(3,Math.hypot(...ps[0].map((v,i)=>v-ps[1][i]))*4);this.zoom=1.4;this.draw();}}
  view(top){this.yaw=top?-Math.PI/2:-1;this.pitch=top?Math.PI/2-.0001:.75;this.draw()}
  draw(){
    if(!this.gl)return;const g=this.gl,c=this.canvas,dpr=window.devicePixelRatio||1;c.width=Math.max(1,c.clientWidth*dpr);c.height=Math.max(1,c.clientHeight*dpr);g.viewport(0,0,c.width,c.height);g.clearColor(.91,.94,.965,1);g.clear(g.COLOR_BUFFER_BIT|g.DEPTH_BUFFER_BIT);g.enable(g.DEPTH_TEST);g.depthFunc(g.LEQUAL);g.enable(g.BLEND);g.blendFunc(g.SRC_ALPHA,g.ONE_MINUS_SRC_ALPHA);g.useProgram(this.program);
    const distance=this.span*1.8/this.zoom,eye=this.center.map((v,i)=>v+distance*[Math.cos(this.yaw)*Math.cos(this.pitch),Math.sin(this.yaw)*Math.cos(this.pitch),Math.sin(this.pitch)][i]);
    const norm=a=>{const n=Math.hypot(...a);return a.map(v=>v/n)},cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
    const z=norm(eye.map((v,i)=>v-this.center[i])),x=norm(cross([0,0,1],z)),y=cross(z,x),view=[x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1];
    const n=Math.max(.001,distance/1000),far=Math.max(10000,distance*100),f=1/Math.tan(18*Math.PI/180),projection=[f/(c.width/c.height),0,0,0,0,f,0,0,0,0,(far+n)/(n-far),-1,0,0,2*far*n/(n-far),0],m=new Float32Array(16);
    for(let col=0;col<4;col++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)m[col*4+row]+=projection[k*4+row]*view[col*4+k];
    g.uniformMatrix4fv(this.uniforms.m,false,m);g.uniform3fv(this.uniforms.eye,eye);g.uniform1f(this.uniforms.unlit,0);g.uniform1f(this.uniforms.cut,0);g.uniform1f(this.uniforms.cutY,this.center[1]);
    const render=(buffer,color,mode=g.TRIANGLES)=>{if(!buffer)return;g.bindBuffer(g.ARRAY_BUFFER,buffer.buffer);for(let i=0;i<2;i++){g.enableVertexAttribArray(this.attributes[i]);g.vertexAttribPointer(this.attributes[i],3,g.FLOAT,false,24,i*12)}g.uniform4fv(this.uniforms.color,color);g.drawArrays(mode,0,buffer.count)};
    for(const b of this.bodies){if(b.kind==='board')continue;if(this.selected&&this.isolate&&!this.selected.refs.includes(b.ref))continue;render(b.buffer,b.kind.includes('allowance')||b.kind.includes('envelope')?[.94,.65,.22,1]:[.64,.68,.74,1]);}
    g.depthMask(!this.ghost);g.uniform1f(this.uniforms.cut,this.section?1:0);for(const b of this.bodies)if(b.kind==='board')render(b.buffer,[.17,.48,.39,this.ghost ? 0.24 : 1]);g.depthMask(true);g.uniform1f(this.uniforms.cut,0);
    if(this.selected){g.disable(g.DEPTH_TEST);g.uniform1f(this.uniforms.unlit,1);render(this.cache.get(this.selected.id),[.96,.12,.1,.95]);const points=this.cache.get(this.selected.id+'points');render(points,[.96,.12,.1,1],g.LINES);render(points,[.96,.12,.1,1],g.POINTS);g.enable(g.DEPTH_TEST);}
  }
}
