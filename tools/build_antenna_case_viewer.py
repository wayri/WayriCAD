"""Export actual saved FEM/array results as scaled, probed offline 3D plots."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.antenna_viewer_html import write_viewer


def build(result_path, output, solver_log=None):
    import numpy as np
    import plotly.graph_objects as go
    from quick_emerge_plugin.radiation_pattern import prepare_radiation, radiation_cut
    raw=result_path.read_bytes(); data=json.loads(raw)
    output.mkdir(parents=True,exist_ok=True)
    portable=dict(data)
    if portable.get('source'):
        portable['source']=dict(portable['source'],path='context.kicad_pcb')
    portable['export_note']='Source path redacted to a generic relative filename; raw source binding is unverified.'
    packed=gzip.compress(json.dumps(portable,allow_nan=False).encode('utf-8'),mtime=0)
    digest=hashlib.sha256(packed).hexdigest()
    samples_path=output/'solved-samples.json.gz'
    if samples_path.exists() and hashlib.sha256(samples_path.read_bytes()).hexdigest()!=digest:
        raise ValueError('Different numerical evidence already exists; choose a new output folder.')
    samples_path.write_bytes(packed)
    figures=[]
    def add(key,title,figure,caption): figures.append((key,title,figure,caption))
    freq=np.asarray(data.get('frequencies_hz',[]))/1e9
    for name,pairs in data.get('s_parameters',{}).items():
        if name!='S11': continue
        pairs=np.asarray(pairs); values=pairs[:,0]+1j*pairs[:,1]
        for key,title,ys,unit in [('s11','S11 magnitude',20*np.log10(np.maximum(np.abs(values),1e-30)),'dB'),
                                  ('phase','S11 phase',np.angle(values,deg=True),'degree')]:
            fig=go.Figure(go.Scatter(x=freq.tolist(),y=ys.tolist(),mode='lines+markers',customdata=pairs.tolist(),
                hovertemplate='f=%{x:.6g} GHz<br>value=%{y:.7g} '+unit+'<br>Re=%{customdata[0]:.7g}<br>Im=%{customdata[1]:.7g}<extra></extra>'))
            fig.update_xaxes(title='Frequency [GHz]'); fig.update_yaxes(title=title+' ['+unit+']')
            add(key,title,fig,f'{len(freq)} actual solved samples; connecting lines are not extra solves.')
    field=data.get('field')
    if field:
        x,y=field['x_mm'],field['y_mm']; values=field['norm_e_v_m']; z=field['z_mm']; f=field['frequency_hz']/1e9
        fig=go.Figure(go.Heatmap(x=x,y=y,z=values,zsmooth=False,colorscale='Inferno',colorbar=dict(title='E [V/m]'),
            hovertemplate=f'X=%{{x:.5g}} mm<br>Y=%{{y:.5g}} mm<br>Z={z:g} mm<br>f={f:g} GHz<br>E=%{{z:.7g}} V/m<extra></extra>'))
        fig.update_xaxes(title='X [mm]');fig.update_yaxes(title='Y [mm]',scaleanchor='x',scaleratio=1)
        add('field','Original field slice',fig,f'{len(x)} x {len(y)} samples at Z={z:g} mm, {f:g} GHz; no smoothing of values.')
        volume=field.get('volume')
        if volume:
            zz,yy,xx=np.meshgrid(volume['z_mm'],volume['y_mm'],volume['x_mm'],indexing='ij')
            ev=np.asarray(volume['norm_e_v_m'],float)
            valid=np.isfinite(ev)
            positions=np.column_stack((xx[valid],yy[valid],zz[valid])); color=ev[valid]
            caption=f'{valid.sum()} original finite volume samples at {f:g} GHz; discrete stored planes, no invented volume interpolation.'
        else:
            xx,yy=np.meshgrid(x,y); ev=np.asarray(values,float);valid=np.isfinite(ev)
            positions=np.column_stack((xx[valid],yy[valid],np.full(valid.sum(),z)));color=ev[valid]
            caption=f'One original plane at Z={z:g} mm, {f:g} GHz; not a volume solve.'
        fig=go.Figure(go.Scatter3d(x=positions[:,0].tolist(),y=positions[:,1].tolist(),z=positions[:,2].tolist(),
            mode='markers',marker=dict(size=2,color=color.tolist(),colorscale='Inferno',colorbar=dict(title='E [V/m]')),
            text=[f'E={value:.7g} V/m' for value in color],
            hovertemplate='X=%{x:.5g} mm<br>Y=%{y:.5g} mm<br>Z=%{z:.5g} mm<br>%{text}<extra></extra>',name='Stored field'))
        for sheet in data.get('scene_geometry',{}).get('sheets',[]):
            for ring in [sheet['vertices_mm']]+sheet.get('holes_mm',[]):
                points=np.asarray(ring+[ring[0]],float)
                if points.shape[1]==2:points=np.column_stack((points,np.full(len(points),sheet['vertices_mm'][0][2])))
                fig.add_trace(go.Scatter3d(x=points[:,0].tolist(),y=points[:,1].tolist(),z=points[:,2].tolist(),
                    mode='lines',line=dict(color='#178a8a',width=2),hoverinfo='skip',showlegend=False))
        fig.update_layout(scene=dict(xaxis_title='X [mm]',yaxis_title='Y [mm]',zaxis_title='Z [mm]',aspectmode='data'))
        add('field3d','3D fields registered to source geometry outlines',fig,caption)
    radiation=data.get('radiation')
    if radiation:
        samples=prepare_radiation(radiation); tt,pp=np.meshgrid(samples.theta,samples.phi,indexing='ij');r=samples.relative
        xyz=(r*np.sin(tt)*np.cos(pp),r*np.sin(tt)*np.sin(pp),r*np.cos(tt))
        fig=go.Figure(go.Surface(x=xyz[0].tolist(),y=xyz[1].tolist(),z=xyz[2].tolist(),surfacecolor=r.tolist(),
            colorscale='Viridis',hoverinfo='skip',colorbar=dict(title='Relative E')))
        texts=[f'theta={t:.3f} degree<br>phi={p:.3f} degree<br>relative E={v:.7f}'
               for t,p,v in zip(np.degrees(tt).ravel(),np.degrees(pp).ravel(),r.ravel())]
        fig.add_trace(go.Scatter3d(x=xyz[0].ravel().tolist(),y=xyz[1].ravel().tolist(),z=xyz[2].ravel().tolist(),
            mode='markers',marker=dict(size=2,color=r.ravel().tolist(),colorscale='Viridis',opacity=.35),
            text=texts,hovertemplate='%{text}<extra></extra>',showlegend=False))
        fig.update_layout(scene=dict(xaxis_title='X [relative radius]',yaxis_title='Y [relative radius]',
                                      zaxis_title='Z [relative radius]',aspectmode='cube'))
        add('radiation3d','3D solved radiation / array factor',fig,
            f'{samples.frequency/1e9:g} GHz, {len(samples.theta)} x {len(samples.phi)} original directions. Relative radius is not physical distance, realized gain or efficiency. '+radiation.get('model','Full-wave screening; no convergence claim.'))
        cut=radiation_cut(samples,'XZ cut')
        fig=go.Figure(go.Scatterpolar(theta=np.degrees(cut['angles_rad']).tolist(),r=cut['relative_e'].tolist(),mode='lines+markers',
            hovertemplate='angle=%{theta:.5g} degree<br>relative E=%{r:.7g}<extra></extra>'))
        fig.update_layout(polar=dict(radialaxis=dict(range=[0,1.05],title='Relative E'),angularaxis=dict(rotation=90)))
        add('polar','XZ principal cut',fig,'Original stored directions; no revolved or fabricated 3D pattern.')
        pol=radiation.get('boresight_polarization')
        if pol:
            ex,ey=complex(*pol['ex_ri']),complex(*pol['ey_ri']);phase=np.linspace(0,2*np.pi,361)
            scale=np.sqrt(abs(ex)**2+abs(ey)**2)
            if scale:
                fig=go.Figure(go.Scatter(x=((ex*np.exp(1j*phase)).real/scale).tolist(),y=((ey*np.exp(1j*phase)).real/scale).tolist(),
                    mode='lines',customdata=np.degrees(phase).tolist(),hovertemplate='phase=%{customdata:.3g} degree<br>Ex=%{x:.7g}<br>Ey=%{y:.7g}<extra></extra>'))
                fig.update_xaxes(title='Ex / sqrt(S0)',range=[-1.05,1.05]); fig.update_yaxes(title='Ey / sqrt(S0)',range=[-1.05,1.05],scaleanchor='x',scaleratio=1)
                add('polarization','Saved +Z polarization',fig,'Ellipse from original complex Ex/Ey; derived phases are not additional FEM solves. No full angular polarization map.')
    mesh=data.get('discretization',{}).get('tetrahedra')
    receipt={'source_result_sha256':hashlib.sha256(raw).hexdigest(),'samples_sha256':digest,
             'samples_file':samples_path.name,'exported_at_utc':datetime.now(timezone.utc).isoformat(),
             'publication_comparison':data.get('publication_comparison'), 'source_path_redacted':True}
    if solver_log:
        log=solver_log.read_bytes(); found=re.findall(rb'#tets\s*=\s*([\d,]+)',log)
        if found:mesh=int(found[-1].replace(b',',b''))
        receipt['solver_log_sha256']=hashlib.sha256(log).hexdigest()
    receipt['tetrahedra']=mesh
    (output/'interactive-provenance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    title=data.get('research',{}).get('title','Saved antenna result')
    backend=data.get('backend',{})
    summary=f"{backend.get('backend','Unknown backend')} {backend.get('version','unknown version')}; exported {receipt['exported_at_utc']}. {len(freq)} frequency samples; logged/recorded tetrahedra: {mesh if mesh is not None else 'unavailable'}. Screening only; no mesh convergence, measured gain or physical qualification. Publication status: {data.get('publication_comparison',{}).get('overall','not evaluated')}. Source path redacted; numerical values retained."
    write_viewer(output/'interactive-results.html',figures,title,summary,digest,
                 'radiation3d' if radiation else figures[0][0])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--solver-log',type=Path)
    args=parser.parse_args();build(args.result,args.output,args.solver_log)
