"""Two-point voltage measurements within one solved 2.5D potential reference."""
from __future__ import annotations

import math


def sample_point(bundle, layer, x_mm, y_mm, *, check_source=True, location_cache=None):
    """Evaluate a containing P1 triangle's solved nodal potential in volts.

    Barycentric interpolation is the finite-element field, not a display gradient
    or nearest-cell guess. Empty space, drill voids and unknown nodes stay unknown.
    Barrel interiors and full-volume models need a separate 3D point locator.
    """
    import numpy as np
    if layer is None or str(layer)=='all':raise ValueError('Choose one physical copper layer for each probe.')
    coordinates=(float(x_mm),float(y_mm))
    if not all(math.isfinite(value) for value in coordinates):raise ValueError('Probe coordinates must be finite millimetres.')
    if not isinstance(bundle,dict):raise ValueError('Choose one solved PI result object.')
    mesh=bundle.get('mesh',{});result=bundle.get('result',{})
    if not isinstance(mesh,dict) or not isinstance(result,dict):raise ValueError('Solved mesh and result must be objects.')
    row=dict(layer=layer,x_mm=coordinates[0],y_mm=coordinates[1],potential_V=None,status='UNKNOWN',element=None)
    if not result or 'potential_V' not in result or not mesh.get('triangles') or mesh.get('tetrahedra'):
        row['notice']='No solved 2.5D triangular potential field is available.';return row
    from wayricad_runtime.report_ui import checked_sources
    if check_source:checked_sources(bundle)
    key=(str(layer),*coordinates)
    cached=None
    if location_cache is not None:
        if location_cache.get('mesh') is not mesh:
            location_cache.clear();location_cache['mesh']=mesh
        cached=location_cache.get(key)
    if cached is not None:
        element,nodes,weights=cached
        return _evaluate(row,result,element,nodes,weights)
    points=np.asarray(mesh.get('points_mm',[]),dtype=float)
    triangles=np.asarray(mesh['triangles'],dtype=int)
    layers=mesh.get('triangle_layer',[])
    if len(layers)!=len(triangles) or triangles.ndim!=2 or triangles.shape[1]!=3:
        raise ValueError('Solved triangle/layer inventory is inconsistent.')
    if points.ndim!=2 or points.shape[1]<2 or not np.isfinite(points[:,:2]).all() or (triangles<0).any() or (triangles>=len(points)).any():
        raise ValueError('Solved triangle coordinates or node indices are invalid.')
    indices=np.flatnonzero([str(value)==str(layer) for value in layers])
    if not len(indices):row['notice']='No solved triangles on this layer.';return row
    vertices=points[triangles[indices],:2]
    a,b,c=vertices[:,0],vertices[:,1],vertices[:,2]
    cross=lambda u,v:u[:,0]*v[:,1]-u[:,1]*v[:,0]
    denominator=cross(b-a,c-a)
    usable=np.isfinite(denominator)&(abs(denominator)>1e-20)
    weights=np.full((len(indices),3),float('nan'))
    p=np.asarray(coordinates)
    weights[usable,1]=cross(p-a,c-a)[usable]/denominator[usable]
    weights[usable,2]=cross(b-a,p-a)[usable]/denominator[usable]
    weights[:,0]=1-weights[:,1]-weights[:,2]
    hits=np.flatnonzero(usable & np.all(weights>=-1e-10,axis=1) & np.all(weights<=1+1e-10,axis=1))
    if not len(hits):row['notice']='Point is outside solved sheet copper, or inside an unmeshed/drill void.';return row
    hit=int(hits[0]);element=int(indices[hit]);nodes=triangles[element]
    weights=weights[hit].tolist();nodes=nodes.tolist()
    if location_cache is not None:
        if len(location_cache)>128:
            location_cache.clear();location_cache['mesh']=mesh
        location_cache[key]=(element,nodes,weights)
    return _evaluate(row,result,element,nodes,weights)


def _evaluate(row,result,element,nodes,weights):
    raw=result['potential_V']
    if max(nodes)>=len(raw):raise ValueError('Solved nodal potential inventory is inconsistent.')
    values=[raw[int(node)] for node in nodes]
    if any(value is None or isinstance(value,bool) or not math.isfinite(float(value)) for value in values):
        row['notice']='Containing element has unknown nodal potential.';return row
    value=sum(w*float(v) for w,v in zip(weights,values))
    if not math.isfinite(value):raise ValueError('Probe potential exceeds the finite calculation range.')
    row.update(status='SAMPLED',potential_V=value,element=element,
               notice='Solved P1 nodal potential evaluated within the containing triangle.')
    return row


def differential_probe(bundle, a, b, *, check_source=True, location_cache=None):
    """Return V(A)-V(B) only within this single result's common potential gauge.

    Each point is ``{layer, x_mm, y_mm}``. Independent case/batch bundles cannot
    be passed as two separate results, preventing arbitrary gauge subtraction.
    """
    if 'cases' in bundle:raise ValueError('Choose one solved case. Independent net/case potentials cannot be subtracted.')
    if check_source:
        from wayricad_runtime.report_ui import checked_sources
        checked_sources(bundle)
    first=sample_point(bundle,**a,check_source=False,location_cache=location_cache);second=sample_point(bundle,**b,check_source=False,location_cache=location_cache)
    known=first['status']==second['status']=='SAMPLED'
    value=first['potential_V']-second['potential_V'] if known else None
    if value is not None and not math.isfinite(value):raise ValueError('Differential voltage exceeds the finite calculation range.')
    return dict(schema='wayricad.pi-differential-probe/v1',status='SAMPLED' if known else 'UNKNOWN',
                a=first,b=second,voltage_a_minus_b_V=value,
                notice='V(A) - V(B), within one solved potential reference. This is a DC field probe, not a transient or AC waveform.')


def saved_probe(bundle, *, check_source=True, location_cache=None):
    """Re-evaluate saved point selections; current changes cannot stale the value."""
    points=bundle.get('differential_probes',{})
    if not all(key in points for key in ('a','b')):return None
    return differential_probe(bundle,points['a'],points['b'],check_source=check_source,location_cache=location_cache)


def _static_reading(reading):
    from html import escape
    if not reading:return '<p>No saved A/B point pair. Choose points in the native workspace or use the saved-result CLI.</p>'
    static='<table><tr><th>Probe</th><th>Layer</th><th>X mm</th><th>Y mm</th><th>Potential V</th></tr>'
    for key in ('a','b'):
        point=reading[key]
        static+='<tr>'+''.join('<td>'+escape(str(value if value is not None else 'Unknown'))+'</td>' for value in (key.upper(),point['layer'],point['x_mm'],point['y_mm'],point['potential_V']))+'</tr>'
    value=reading['voltage_a_minus_b_V']
    return static+'</table><p>Saved probe V(A) - V(B): '+('Unknown' if value is None else f'{value:.10g} V')+'. '+escape(reading['notice'])+'</p>'


def report_html(bundle, layer):
    """Offline two-point probe with one common saved nodal potential reference."""
    import json
    from html import escape
    mesh=bundle.get('mesh',{});result=bundle.get('result',{})
    if not mesh.get('triangles') or 'potential_V' not in result or mesh.get('tetrahedra'):return ''
    # Payload is inert data; board/net text never becomes JavaScript source.
    geometry=bundle.get('geometry') or mesh.get('geometry',{})
    names={str(row['id']):str(row.get('name',row['id'])) for row in geometry.get('layers',[])}
    layers=list(dict.fromkeys(map(str,mesh['triangle_layer'])))
    reading=saved_probe(bundle)
    if len(mesh['triangles'])>20000:
        return '<section><h2>Differential voltage probe</h2>'+_static_reading(reading)+'<p>This dense result retains differential probing in the native workspace and saved-result CLI. The extra browser probe map is omitted above 20,000 triangles to avoid duplicating a large field payload. Existing report maps and exact JSON remain available.</p></section>'
    payload=dict(points=[p[:2] for p in mesh['points_mm']],triangles=mesh['triangles'],
                 layers=list(map(str,mesh['triangle_layer'])),potential=result['potential_V'],
                 selected=bundle.get('differential_probes',{}))
    raw=json.dumps(payload,allow_nan=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    options=''.join('<option value="'+escape(value,quote=True)+'"'+(' selected' if value==str(layer) else '')+'>'+escape(names.get(value,value))+'</option>' for value in layers)
    static=_static_reading(reading)
    return '''<section class="interactive-analysis" id="pi-differential"><h2>Differential voltage probe</h2>
<p>Choose A, then B on solved sheet copper. Readout is V(A) - V(B) within this result's common reference. Different solved layers can be compared; independent case reports cannot. Drill holes and unknown nodes remain unknown. Coordinates are millimetres; potentials use the solved linear finite-element field.</p>
'''+static+'''<label>Layer <select class="diff-layer">'''+options+'''</select></label>
<label>Next point <select class="diff-target"><option value="a">A</option><option value="b">B</option></select></label>
<button type="button" class="diff-clear">Clear probes</button>
<p class="diff-readout" role="status" aria-live="polite">Select A and B.</p>
<canvas width="900" height="450" style="width:100%;max-width:900px;height:auto;background:#f5f9fa" aria-label="Solved copper differential probe map"></canvas>
<script type="application/json" class="diff-data">'''+raw+'''</script>
<script>(()=>{
const root=document.getElementById('pi-differential'),data=JSON.parse(root.querySelector('.diff-data').textContent),canvas=root.querySelector('canvas'),ctx=canvas.getContext('2d'),layer=root.querySelector('.diff-layer'),target=root.querySelector('.diff-target'),readout=root.querySelector('.diff-readout');
let selected=data.selected||{},bounds,scale,ox,oy;
const byLayer=new Map();data.triangles.forEach((tri,i)=>{const k=data.layers[i];if(!byLayer.has(k))byLayer.set(k,[]);byLayer.get(k).push(i);});
const cross=(a,b)=>a[0]*b[1]-a[1]*b[0],sub=(a,b)=>[a[0]-b[0],a[1]-b[1]];
function sample(p){for(const i of byLayer.get(String(p.layer))||[]){const tri=data.triangles[i],v=tri.map(n=>data.points[n]),xs=v.map(a=>a[0]),ys=v.map(a=>a[1]);if(p.x_mm<Math.min(...xs)-1e-10||p.x_mm>Math.max(...xs)+1e-10||p.y_mm<Math.min(...ys)-1e-10||p.y_mm>Math.max(...ys)+1e-10)continue;const d=cross(sub(v[1],v[0]),sub(v[2],v[0]));if(Math.abs(d)<=1e-20)continue;const q=[p.x_mm,p.y_mm],u=cross(sub(q,v[0]),sub(v[2],v[0]))/d,w=cross(sub(v[1],v[0]),sub(q,v[0]))/d,weights=[1-u-w,u,w];if(weights.some(a=>a < -1e-10||a>1+1e-10))continue;const values=tri.map(n=>data.potential[n]);if(values.some(v=>typeof v!=='number'||!Number.isFinite(v)))return null;const value=weights.reduce((sum,w,j)=>sum+w*values[j],0);return Number.isFinite(value)?value:null;}return null;}
function draw(){const indices=byLayer.get(layer.value)||[];let xmin=Infinity,ymin=Infinity,xmax=-Infinity,ymax=-Infinity;indices.forEach(i=>data.triangles[i].forEach(n=>{const p=data.points[n];xmin=Math.min(xmin,p[0]);xmax=Math.max(xmax,p[0]);ymin=Math.min(ymin,p[1]);ymax=Math.max(ymax,p[1]);}));bounds=[xmin,ymin,xmax,ymax];scale=Math.min((canvas.width-40)/Math.max(xmax-xmin,1e-6),(canvas.height-40)/Math.max(ymax-ymin,1e-6));ox=20-xmin*scale;oy=20-ymin*scale;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.beginPath();indices.forEach(i=>{data.triangles[i].forEach((n,j)=>{const p=data.points[n];ctx[j?'lineTo':'moveTo'](ox+p[0]*scale,oy+p[1]*scale);});ctx.closePath();});ctx.fillStyle='#c5ded9';ctx.fill();
for(const key of ['a','b']){const p=selected[key];if(!p||String(p.layer)!==layer.value)continue;const x=ox+p.x_mm*scale,y=oy+p.y_mm*scale;ctx.beginPath();ctx.arc(x,y,7,0,2*Math.PI);ctx.strokeStyle=key==='a'?'#b44d11':'#1765b2';ctx.lineWidth=3;ctx.stroke();ctx.fillStyle=ctx.strokeStyle;ctx.font='bold 15px sans-serif';ctx.fillText(key.toUpperCase(),x+11,y-8);}
const describe=key=>{const p=selected[key];if(!p)return key.toUpperCase()+': not selected';const value=sample(p);return key.toUpperCase()+': layer '+p.layer+'; '+p.x_mm.toPrecision(7)+', '+p.y_mm.toPrecision(7)+' mm; '+(value===null?'Unknown':value.toPrecision(8)+' V');};let text=describe('a')+' | '+describe('b');if(selected.a&&selected.b){const a=sample(selected.a),b=sample(selected.b);text+=' | V(A) - V(B): '+(a===null||b===null||!Number.isFinite(a-b)?'Unknown':(a-b).toPrecision(8)+' V');}readout.textContent=text;}
canvas.addEventListener('click',event=>{const rect=canvas.getBoundingClientRect(),x=(event.clientX-rect.left)*canvas.width/rect.width,y=(event.clientY-rect.top)*canvas.height/rect.height;selected[target.value]={layer:layer.value,x_mm:(x-ox)/scale,y_mm:(y-oy)/scale};target.value=target.value==='a'?'b':'a';draw();});layer.addEventListener('change',draw);root.querySelector('.diff-clear').addEventListener('click',()=>{selected={};target.value='a';draw();});draw();
})();</script></section>'''
