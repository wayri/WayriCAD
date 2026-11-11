"""Build a self-contained, original-sample hover viewer (Plotly 6.3.1)."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build(folder):
    import numpy as np
    import plotly.graph_objects as go
    from tools.antenna_viewer_html import write_viewer
    from quick_emerge_plugin.radiation_pattern import prepare_radiation, radiation_cut
    receipt = json.loads((folder / 'provenance.json').read_bytes())
    raw = (folder / receipt['samples_file']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt['samples_sha256']:
        raise ValueError('Numerical sample hash mismatch')
    data = json.loads(gzip.decompress(raw))
    figures = []

    def add(identifier, title, figure, caption):
        figure.update_layout(template='plotly_white', margin=dict(l=65, r=45, t=35, b=65),
                             font=dict(size=14), hoverlabel=dict(font_size=14))
        figures.append((identifier, title, figure, caption))

    freq = np.asarray(data['frequencies_hz']) / 1e9
    pairs = np.asarray(data['s_parameters']['S11'])
    gamma = pairs[:, 0] + 1j*pairs[:, 1]
    for identifier, title, values, unit in [
        ('s11', 'S11 magnitude', 20*np.log10(np.abs(gamma)), 'dB'),
        ('phase', 'S11 phase', np.angle(gamma, deg=True), 'degree')]:
        figure = go.Figure(go.Scatter(x=freq.tolist(), y=values.tolist(), mode='lines+markers',
            customdata=pairs.tolist(), name='S11',
            hovertemplate='f=%{x:.4f} GHz<br>value=%{y:.6g} '+unit+
                          '<br>Re S11=%{customdata[0]:.7f}<br>Im S11=%{customdata[1]:.7f}<extra></extra>'))
        figure.update_xaxes(title='Frequency [GHz]')
        figure.update_yaxes(title=title+' ['+unit+']')
        add(identifier, title, figure, '21 actual FEM frequency samples; connecting lines add no new solves.')

    figure = go.Figure(go.Scatter(x=pairs[:, 0].tolist(), y=pairs[:, 1].tolist(),
        customdata=freq.tolist(), mode='lines+markers', name='S11',
        hovertemplate='f=%{customdata:.4f} GHz<br>Re Gamma=%{x:.7f}<br>Im Gamma=%{y:.7f}<extra></extra>'))
    angle = np.linspace(0, 2*np.pi, 361)
    figure.add_trace(go.Scatter(x=np.cos(angle).tolist(), y=np.sin(angle).tolist(),
                               mode='lines', line=dict(color='#999'), hoverinfo='skip', name='Unit circle'))
    figure.update_xaxes(title='Re Gamma [dimensionless]', range=[-1.1, 1.1])
    figure.update_yaxes(title='Im Gamma [dimensionless]', scaleanchor='x', scaleratio=1, range=[-1.1, 1.1])
    add('reflection', 'Complex reflection plane', figure, '50 ohm reference. This is a Gamma plane, not a tuned matching network.')

    field = data['field']
    x, y, e = field['x_mm'], field['y_mm'], field['norm_e_v_m']
    figure = go.Figure(go.Heatmap(x=x, y=y, z=e, colorscale='Inferno', zsmooth=False,
        colorbar=dict(title='|E| [V/m]'), hoverongaps=False,
        hovertemplate='X=%{x:.4f} mm<br>Y=%{y:.4f} mm<br>Z=2 mm<br>f=2.45 GHz<br>|E|=%{z:.7g} V/m<extra></extra>'))
    figure.update_xaxes(title='X [mm]')
    figure.update_yaxes(title='Y [mm]', scaleanchor='x', scaleratio=1)
    add('field', 'E-field plane: Z = 2 mm, 2.45 GHz', figure,
        '161 x 161 original samples. Hover selects a sampled grid cell; no smoothed data are substituted.')
    xm, ym = np.meshgrid(x, y)
    figure = go.Figure(go.Surface(x=xm.tolist(), y=ym.tolist(), z=np.full(xm.shape, 2.).tolist(),
        surfacecolor=e, colorscale='Inferno', colorbar=dict(title='|E| [V/m]'),
        customdata=e, hovertemplate='X=%{x:.4f} mm<br>Y=%{y:.4f} mm<br>Z=%{z} mm<br>|E|=%{customdata:.7g} V/m<extra></extra>'))
    figure.update_layout(scene=dict(xaxis_title='X [mm]', yaxis_title='Y [mm]', zaxis_title='Z [mm]',
                                    aspectmode='data'))
    add('field3d', '3D sampled field plane', figure, 'One Z plane, not a volume solve. Rotate/zoom and probe original vertices.')

    samples = prepare_radiation(data['radiation'])
    cut = radiation_cut(samples, 'XZ cut')
    figure = go.Figure(go.Scatterpolar(theta=np.degrees(cut['angles_rad']).tolist(),
        r=cut['relative_e'].tolist(), mode='lines+markers',
        hovertemplate='Cut angle=%{theta:.3f} degree<br>relative |E|=%{r:.7f}<extra></extra>'))
    figure.update_layout(polar=dict(radialaxis=dict(title='Relative |E|', range=[0, 1.05],
                                                  tickvals=[0, .25, .5, .75, 1]),
                                    angularaxis=dict(direction='clockwise', rotation=90)))
    add('polar', 'XZ radiation cut at 2.45 GHz', figure, 'Relative |E| / global stored-sample maximum; not dBi or efficiency.')
    theta, phi = np.meshgrid(samples.theta, samples.phi, indexing='ij')
    r = samples.relative
    custom = np.stack((np.degrees(theta), np.degrees(phi), r, samples.magnitude), axis=-1)
    probe_text = [[f'theta={point[0]:.3f} degree<br>phi={point[1]:.3f} degree'
                   f'<br>relative |E|={point[2]:.7f}<br>stored norm={point[3]:.7g}'
                   for point in row] for row in custom]
    figure = go.Figure(go.Surface(x=(r*np.sin(theta)*np.cos(phi)).tolist(),
        y=(r*np.sin(theta)*np.sin(phi)).tolist(), z=(r*np.cos(theta)).tolist(),
        surfacecolor=r.tolist(), customdata=custom.tolist(), colorscale='Viridis',
        colorbar=dict(title='Relative |E|'),
        hoverinfo='skip'))
    # A pickable vertex trace avoids Surface hover interpolation/customdata limits.
    figure.add_trace(go.Scatter3d(x=(r*np.sin(theta)*np.cos(phi)).ravel().tolist(),
        y=(r*np.sin(theta)*np.sin(phi)).ravel().tolist(), z=(r*np.cos(theta)).ravel().tolist(),
        mode='markers', marker=dict(size=2, color=r.ravel().tolist(), colorscale='Viridis', opacity=.35),
        text=[value for row in probe_text for value in row], hovertemplate='%{text}<extra></extra>',
        name='Original angular samples', showlegend=False))
    figure.update_layout(scene=dict(xaxis_title='X [relative radius]', yaxis_title='Y [relative radius]',
                                    zaxis_title='Z [relative radius]', aspectmode='cube'))
    add('radiation3d', '3D radiation with angular probes', figure,
        'Axes are normalized field-radius coordinates, not physical distance. 91 x 181 original directions, 2-degree sampling.')

    pol = data['radiation']['boresight_polarization']
    ex, ey = complex(*pol['ex_ri']), complex(*pol['ey_ri'])
    phase = np.linspace(0, 2*np.pi, 361)
    scale = np.sqrt(abs(ex)**2 + abs(ey)**2)
    figure = go.Figure(go.Scatter(x=((ex*np.exp(1j*phase)).real/scale).tolist(),
        y=((ey*np.exp(1j*phase)).real/scale).tolist(), customdata=np.degrees(phase).tolist(),
        mode='lines', hovertemplate='phase=%{customdata:.2f} degree<br>normalized Ex=%{x:.7g}'+
                                    '<br>normalized Ey=%{y:.7g}<extra></extra>'))
    figure.update_xaxes(title='Re(Ex exp(j phase)) / sqrt(S0)', range=[-1.05, 1.05])
    figure.update_yaxes(title='Re(Ey exp(j phase)) / sqrt(S0)', scaleanchor='x', scaleratio=1, range=[-1.05, 1.05])
    add('polarization', 'Boresight polarization ellipse', figure,
        f"AR={pol['axial_ratio_db']:.3f} dB at +Z, 2.45 GHz. Derived ellipse phases are not extra FEM solves. No RHCP/LHCP mapping.")

    path = folder / 'interactive-results.html'
    write_viewer(path,figures,'Yang WLAN antenna: original-sample results',
        'Quick EMerge 4.7.0 / EMerge 3.0.0b9 / SuperLU. 21 frequencies, 9,240 tetrahedra, 161 x 161 field samples. '
        'Generated 2026-11-10. Matching target failed; no mesh/boundary convergence, gain or flight qualification.',
        receipt['samples_sha256'])
    print(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, default=ROOT / 'examples/quick_emerge/research_antennas/images/dense')
    build(parser.parse_args().folder)
