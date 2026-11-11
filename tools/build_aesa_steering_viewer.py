"""Build an offline, original-sample ideal AESA beam-shaping comparison."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def build(output):
    import numpy as np
    from plotly.offline import get_plotlyjs
    from quick_emerge_plugin.research_antennas import example_config
    from quick_emerge_plugin.research_studies import solve_rectangular_array_factor
    output.mkdir(parents=True,exist_ok=True)
    states={}; results={}
    for taper in ('uniform','binomial'):
        for angle in (0,30,60):
            config=example_config('verho-2023-aesa-4x4')
            config['advanced'].update(scan_theta_deg=angle,scan_phi_deg=0,research_array_taper=taper)
            result=solve_rectangular_array_factor(np,config,{'backend':'closed-form ideal array factor','version':1})
            key=f'{taper}-{angle}'; results[key]=result
            radiation=result['radiation']
            theta,phi=np.meshgrid(radiation['theta_rad'],radiation['phi_rad'],indexing='ij')
            radius=np.asarray(radiation['norm_e']); radius=radius/radius.max()
            coordinates=[radius*np.sin(theta)*np.cos(phi),radius*np.sin(theta)*np.sin(phi),radius*np.cos(theta)]
            custom=np.stack([np.degrees(theta),np.degrees(phi),radius,20*np.log10(np.maximum(radius,1e-12))],axis=-1)
            hover='theta=%{customdata[0]:.1f} deg<br>phi=%{customdata[1]:.1f} deg<br>relative E=%{customdata[2]:.6f}<br>relative field=%{customdata[3]:.2f} dB<extra></extra>'
            traces=[dict(type='surface',x=coordinates[0].tolist(),y=coordinates[1].tolist(),z=coordinates[2].tolist(),
                         surfacecolor=radius.tolist(),colorscale='Viridis',cmin=0,cmax=1,
                         colorbar=dict(title=dict(text='Relative E')),hoverinfo='skip',showscale=True),
                    dict(type='scatter3d',mode='markers',x=coordinates[0].ravel().tolist(),y=coordinates[1].ravel().tolist(),
                         z=coordinates[2].ravel().tolist(),customdata=custom.reshape(-1,4).tolist(),
                         marker=dict(size=2,opacity=.35,color=radius.ravel().tolist(),colorscale='Viridis',cmin=0,cmax=1),hovertemplate=hover,showlegend=False)]
            factor=result['array_factor']
            states[key]=dict(traces=traces,cut=dict(x=factor['theta_deg'],y=(20*np.log10(np.maximum(factor['normalized_magnitude'],1e-6))).tolist()),
                             amplitudes=np.asarray(factor['element_amplitudes']).reshape(4,4).tolist(),
                             peak=factor['predicted_peak_theta_deg'],phase=factor['progressive_phase_x_deg'])
    packed=gzip.compress(json.dumps(results,allow_nan=False).encode(),mtime=0)
    (output/'array-results.json.gz').write_bytes(packed)
    digest=hashlib.sha256(packed).hexdigest()
    receipt=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),samples_sha256=digest,
                 model='Ideal 4x4 isotropic array, 3 GHz, 40 mm pitch; no coupling or gain prediction',
                 source_code_sha256=hashlib.sha256((ROOT/'quick_emerge_plugin/research_studies.py').read_bytes()).hexdigest(),
                 cases=list(states),binomial_scope='Analytical design extension, not the paper excitation')
    (output/'provenance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    document='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AESA 3D beam steering and shaping</title><style>
*{box-sizing:border-box}body{margin:0;font:15px system-ui;color:#24323b;background:#fff}main{max-width:1440px;margin:auto;padding:20px}
h1{font-size:26px}h2{font-size:19px}p{line-height:1.5}header{border-bottom:1px solid #ccd6dc;padding-bottom:14px}
.controls{display:flex;gap:24px;align-items:center;flex-wrap:wrap;padding:16px 0}label{display:flex;gap:10px;align-items:center}select{padding:7px}
#lobes{height:650px}.detail{display:grid;grid-template-columns:2fr 1fr;gap:16px}#cut,#weights{height:350px}code{overflow-wrap:anywhere}
@media(max-width:700px){main{padding:12px}#lobes{height:480px}.detail{grid-template-columns:1fr}.controls{gap:12px}}
</style><main><header><h1>AESA 3D beam steering and shaping</h1>
<p>Ideal 4 × 4 isotropic-element array · 3 GHz · 40 mm pitch · φ = 0° steering plane.
The mirror rear beam is inherent in this planar isotropic model, not a prediction of a ground-backed antenna.
No full-wave coupling, element polarization, active feed losses, realized gain or measured validation is supplied.</p>
<p>Binomial weighting is a design extension: lower sidelobes and a broader main beam, not a second published-paper reproduction.
Every state is independently calculated, not a rotation of one lobe. Drag to orbit, wheel to zoom, and hover to probe original angles.</p></header>
<div class="controls"><label>Steering θ <select id="steering"><option value="0">0° broadside</option><option value="30" selected>30°</option><option value="60">60°</option></select></label>
<label>Beam shaping <select id="taper"><option value="uniform">Uniform amplitude</option><option value="binomial">Binomial amplitude</option></select></label>
<button id="animate" type="button">Play steering</button><button id="reset" type="button">Reset camera</button></div>
<p id="status" aria-live="polite"></p><div id="lobes"></div>
<div class="detail"><section><h2>Steering-plane field cut</h2><div id="cut"></div></section><section><h2>Element amplitude weights</h2><div id="weights"></div></section></div>
<p>Full sphere: 91 × 181 original angular samples, 2° spacing. Radius and colour are normalized E, not distance or dBi.
The cut floor is −120 dB for display; no smoothing or fabricated field samples.</p>
<p>Model provenance: <a href="https://doi.org/10.3390/s23031324">Verho et al. source study</a> (see the repository source audit for the exact scan-law scope).</p>
<p>Created UTC: CREATED. Numeric source SHA-256: <code>DIGEST</code>. <a href="array-results.json.gz">Download all six calculated states</a>.</p>
</main><script>PLOTLY</script><script>
const states=STATES;const theta=document.getElementById('steering'),taper=document.getElementById('taper');let timer=null;
const options={responsive:true,displaylogo:false,scrollZoom:true,plotGlPixelRatio:1};
const scene={xaxis:{title:{text:'X [relative E]'},range:[-1.05,1.05]},yaxis:{title:{text:'Y [relative E]'},range:[-1.05,1.05]},zaxis:{title:{text:'Z [relative E]'},range:[-1.05,1.05]},aspectmode:'cube'};
async function draw(){const s=states[taper.value+'-'+theta.value];
document.getElementById('status').textContent='Target θ = '+theta.value+'°, φ = 0°; sampled steering-plane peak θ = '+s.peak.toFixed(3)+'°; X phase step = '+s.phase.toFixed(3)+'°. '+(taper.value==='binomial'?'Binomial design extension.':'Uniform source scan-law case.');
await Plotly.react('lobes',s.traces,{margin:{l:10,r:70,t:10,b:10},scene,uirevision:'camera',showlegend:false},options);
await Plotly.react('cut',[{type:'scatter',mode:'lines',x:s.cut.x,y:s.cut.y,hovertemplate:'theta=%{x:.3f} deg<br>relative field=%{y:.3f} dB<extra></extra>'}],{margin:{l:60,r:20,t:10,b:50},xaxis:{title:{text:'θ in φ = 0° cut [deg]'},range:[-90,90]},yaxis:{title:{text:'Relative field [dB]'},range:[-60,1]}},options);
await Plotly.react('weights',[{type:'heatmap',z:s.amplitudes,x:[1,2,3,4],y:[1,2,3,4],zmin:0,zmax:1,colorscale:'Blues',colorbar:{title:{text:'Amplitude'}},hovertemplate:'Column=%{x}<br>Row=%{y}<br>Amplitude=%{z:.6f}<extra></extra>'}],{margin:{l:45,r:40,t:10,b:50},xaxis:{title:{text:'X element'},dtick:1},yaxis:{title:{text:'Y element'},dtick:1,scaleanchor:'x'}},options);
window.currentAesaState=taper.value+'-'+theta.value;}
theta.onchange=draw;taper.onchange=draw;document.getElementById('reset').onclick=()=>Plotly.relayout('lobes',{'scene.camera':{eye:{x:1.25,y:1.25,z:1.25}}});
document.getElementById('animate').onclick=function(){if(timer){clearInterval(timer);timer=null;this.textContent='Play steering';return;}this.textContent='Pause steering';timer=setInterval(()=>{theta.selectedIndex=(theta.selectedIndex+1)%3;draw();},2000);};
document.addEventListener('visibilitychange',()=>{if(document.hidden&&timer){clearInterval(timer);timer=null;document.getElementById('animate').textContent='Play steering';}});draw();
</script></html>'''
    # Embed once for an offline viewer; escape script terminators in JSON and JS.
    document=document.replace('CREATED',receipt['created_at_utc']).replace('DIGEST',digest)
    document=document.replace('PLOTLY',get_plotlyjs().replace('</script','<\\/script'))
    document=document.replace('STATES',json.dumps(states,allow_nan=False).replace('</','<\\/'))
    (output/'interactive-steering.html').write_text(document,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'examples/quick_emerge/research_antennas/images/aesa-vnext')
    build(parser.parse_args().output)
