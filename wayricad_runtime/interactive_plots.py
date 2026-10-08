"""Offline sampled-value plots. Probes report cells/samples, never invented interpolation."""
from __future__ import annotations
import json
from html import escape
import math
import uuid


def interactive_plot(title, rows, unit='', three_d=False, polygons=None, x_unit='mm', y_unit='mm', connect=False):
    """Build an offline canvas viewport from [x,y,value,label,z] sample rows.

    Optional polygons correspond one-to-one to rows and restrict field probes
    to their actual cells. Unknown values remain visible but cannot be probed.
    Three-dimensional views orbit/pan/zoom in display space only.
    """
    ident='plot-'+uuid.uuid4().hex
    clean=[]
    for row in rows:
        values=list(row)
        for index in (0,1,2,4):
            if index<len(values) and isinstance(values[index],(int,float)) and not math.isfinite(values[index]):values[index]=None
        clean.append(values)
    data=json.dumps({'rows':clean,'polygons':polygons,'unit':unit,'three':three_d,'xunit':x_unit,'yunit':y_unit,'connect':connect},allow_nan=False).replace('<','\\u003c')
    return ('<figure id="'+ident+'" class="interactive-analysis"><figcaption>'+escape(title)+'</figcaption>'
        '<p>Hover for exact sampled values; click to pin a probe. Drag to '+('orbit; Shift-drag to pan' if three_d else 'pan')+'; wheel to zoom. Display movement does not change the PCB or simulation.</p>'
        '<button type="button" data-fit>Fit</button> <button type="button" data-clear>Clear probes</button>'
        '<canvas style="width:100%;height:420px;display:block;background:#f5f8fa;touch-action:none;cursor:crosshair" aria-label="'+escape(title)+'"></canvas>'
        '<output style="display:block;min-height:1.5em" aria-live="polite">No probe</output><ol data-probes></ol>'
        '<script>(()=>{const host=document.getElementById("'+ident+'"),data='+data+';'+_SCRIPT+'})();</script></figure>')


_SCRIPT=r'''
const canvas=host.querySelector('canvas'),ctx=canvas.getContext('2d'),out=host.querySelector('output'),list=host.querySelector('[data-probes]');
let yaw=.35,pitch=.5,zoom=1,pan=[0,0],drag=null,points=[],saved=[],hover=null;
const finite=data.rows.filter(r=>Number.isFinite(r[0])&&Number.isFinite(r[1]));
const xs=finite.map(r=>r[0]),ys=finite.map(r=>r[1]),zs=finite.map(r=>Number.isFinite(r[4])?r[4]:0);
const extent=a=>a.length?[a.reduce((x,y)=>Math.min(x,y)),a.reduce((x,y)=>Math.max(x,y))]:[0,1];const ex=extent(xs),ey=extent(ys),ez=extent(zs),bounds=[...ex,...ey,...ez];
const center=[(bounds[0]+bounds[1])/2,(bounds[2]+bounds[3])/2,(bounds[4]+bounds[5])/2];
function project(r){let x=r[0]-center[0],y=r[1]-center[1],z=(r[4]||0)-center[2];if(data.three){let a=x*Math.cos(yaw)-y*Math.sin(yaw),b=x*Math.sin(yaw)+y*Math.cos(yaw);x=a;y=b*Math.cos(pitch)-z*Math.sin(pitch);}const s=Math.min(canvas.width/(bounds[1]-bounds[0]||1),canvas.height/(bounds[3]-bounds[2]||1))*.8*zoom;return [canvas.width/2+x*s+pan[0],canvas.height/2+y*s+pan[1]];}
function value(r){return Number.isFinite(r[2])?r[2].toPrecision(7)+' '+data.unit:'Unknown';}
function describe(r){return (r[3]||'Sample')+' | X '+r[0].toPrecision(6)+' '+data.xunit+', Y '+r[1].toPrecision(6)+' '+data.yunit+(data.three?', Z '+(r[4]||0).toPrecision(6):'')+' | '+value(r);}
function draw(){canvas.width=Math.max(300,canvas.clientWidth);canvas.height=420;ctx.clearRect(0,0,canvas.width,canvas.height);points=[];ctx.fillStyle='#334';ctx.font='12px sans-serif';ctx.fillText('X ('+data.xunit+')',10,canvas.height-10);ctx.fillText('Y ('+data.yunit+')',10,18);let values=data.rows.filter(r=>Number.isFinite(r[2])).map(r=>r[2]),range=extent(values),lo=range[0],hi=range[1];data.rows.forEach((r,i)=>{if(!Number.isFinite(r[0])||!Number.isFinite(r[1]))return;let p=project(r),poly=data.polygons&&data.polygons[i];points.push({p,r,i,poly:poly&&poly.map(v=>project([v[0],v[1],0,'',r[4]]))});ctx.fillStyle=Number.isFinite(r[2])?'hsl('+(240-240*(r[2]-lo)/(hi-lo||1))+',75%,48%)':'#a0a8ad';if(poly){ctx.beginPath();poly.forEach((v,j)=>{let q=project([v[0],v[1],0,'',r[4]]);j?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.closePath();ctx.fill();}else{ctx.beginPath();ctx.arc(...p,4,0,Math.PI*2);ctx.fill();}});if(data.connect){ctx.strokeStyle='#147f94';ctx.lineWidth=1.5;ctx.beginPath();let previous=null;data.rows.forEach(r=>{if(!Number.isFinite(r[0])||!Number.isFinite(r[1])||!Number.isFinite(r[2])){previous=null;return;}let p=project(r);if(previous&&previous[3]===r[3])ctx.lineTo(...p);else ctx.moveTo(...p);previous=r;});ctx.stroke();}saved.forEach((r,i)=>{let p=project(r);ctx.strokeStyle='#111';ctx.strokeRect(p[0]-6,p[1]-6,12,12);ctx.fillStyle='#111';ctx.fillText('P'+(i+1),p[0]+8,p[1]-8);});if(hover){ctx.strokeStyle='#333';ctx.beginPath();ctx.moveTo(hover[0],0);ctx.lineTo(hover[0],canvas.height);ctx.moveTo(0,hover[1]);ctx.lineTo(canvas.width,hover[1]);ctx.stroke();}}
function inside(p,poly){let c=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){let a=poly[i],b=poly[j];if(((a[1]>p[1])!=(b[1]>p[1]))&&(p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]))c=!c;}return c;}
function pick(p){if(data.polygons)return points.find(q=>q.poly&&inside(p,q.poly))||null;let best=null,d=12;points.forEach(q=>{let dd=Math.hypot(q.p[0]-p[0],q.p[1]-p[1]);if(dd<d){d=dd;best=q;}});return best;}
function pos(e){let b=canvas.getBoundingClientRect();return [(e.clientX-b.left)*canvas.width/b.width,(e.clientY-b.top)*canvas.height/b.height];}
canvas.onpointerdown=e=>{drag={p:pos(e),start:pos(e),moved:false};canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{let p=pos(e);hover=p;if(drag){let dx=p[0]-drag.p[0],dy=p[1]-drag.p[1];if(Math.hypot(p[0]-drag.start[0],p[1]-drag.start[1])>4)drag.moved=true;if(data.three&&!e.shiftKey){yaw+=dx*.008;pitch+=dy*.008;}else{pan[0]+=dx;pan[1]+=dy;}drag.p=p;}let q=pick(p);out.textContent=q?describe(q.r):'No solved cell/sample at cursor';draw();};
canvas.onpointerup=e=>{if(drag&&!drag.moved){let q=pick(pos(e));if(q&&Number.isFinite(q.r[2])){saved.push(q.r);let item=document.createElement('li');item.textContent='P'+saved.length+': '+describe(q.r);list.append(item);}}drag=null;draw();};
canvas.onpointercancel=()=>{drag=null;};canvas.onpointerleave=()=>{hover=null;draw();};canvas.onwheel=e=>{e.preventDefault();zoom=Math.min(30,Math.max(.05,zoom*Math.exp(-e.deltaY*.001)));draw();};
host.querySelector('[data-fit]').onclick=()=>{zoom=1;pan=[0,0];yaw=.35;pitch=.5;draw();};host.querySelector('[data-clear]').onclick=()=>{saved=[];list.textContent='';draw();};new ResizeObserver(draw).observe(canvas);draw();
'''
