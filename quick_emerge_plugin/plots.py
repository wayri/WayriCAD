"""Native-window figures; geometry and results remain distinct views."""
import math

import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from .model import metrics, validate_config
from .inspection import scale_limits
from .field_display import plane_sampling_label, angular_sampling_label


def _plate(ax, x, y, width, length, z, color, alpha=1):
    vertices = [[(x, y, z), (x+width, y, z), (x+width, y+length, z), (x, y+length, z)]]
    ax.add_collection3d(Poly3DCollection(vertices, facecolors=color, edgecolors=color, alpha=alpha))


def geometry(figure, raw, options=None):
    options = options or {}
    c = validate_config(raw)
    if c.get('advanced', {}).get('study', 'driven') not in ('driven', 'optimization'):
        return advanced_geometry(figure, c, options)
    if c['mode'] == 'pcb_region':
        raise ValueError('Rule-area previews require the reviewed clipped polygons, not template dimensions.')
    figure.clear()
    ax = figure.add_subplot(111, projection='3d', computed_zorder=False)
    sx, sy, th = c['substrate_x_mm'], c['substrate_y_mm'], c['thickness_mm']
    if options.get('copper', True):
        _plate(ax, -sx/2, -sy/2, sx, sy, -th, '#b78a44')
    if options.get('show_context', True):
        _plate(ax, -sx/2, -sy/2, sx, sy, -th/2, '#22886b', 0.3)
    if c['mode'] == 'patch':
        w, length, feed, slot, inset = (c[k] for k in (
            'patch_width_mm', 'patch_length_mm', 'feed_width_mm', 'inset_width_mm', 'inset_length_mm'))
        offset = c['advanced']['patch_offset_y_mm']
        if options.get('copper', True):
            _plate(ax, -w/2, -length/2+inset+offset, w, length-inset, 0, '#d9a951')
            for x in (-w/2, feed/2+slot):
                _plate(ax, x, -length/2+offset, w/2-feed/2-slot, inset, 0, '#d9a951')
            _plate(ax, -feed/2, -length/2+offset, feed, inset, 0, '#d9a951')
        extension = c['advanced']['patch_feed_extension_mm']
        if extension and options.get('copper', True):
            _plate(ax, -feed/2, -length/2-extension+offset, feed, extension, 0, '#d9a951')
        ports = [(0, -length/2-extension+offset)]
    else:
        length, width = c['line_length_mm'], c['line_width_mm']
        if options.get('copper', True):
            _plate(ax, -length/2, -width/2, length, width, 0, '#d9a951')
        ports = [(-length/2, 0), (length/2, 0)]
    for i, (x, y) in enumerate(ports if options.get('ports', True) else [], 1):
        ax.plot([x, x], [y, y], [-th, 0], color='#d94770', linewidth=5)
        ax.text(x, y, th, f'P{i}  {c["z0_ohm"]:g} Ω', color='#b52d54')
    ax.set(xlim=(-sx*.6, sx*.6), ylim=(-sy*.6, sy*.6), zlim=(-th*3, th*5),
           xlabel='X [mm]', ylabel='Y [mm]', zlabel='Z [mm]',
           title='Template preview • PEC copper\nPCB context only; no board copper imported')
    ax.set_box_aspect((sx, sy, max(sx, sy)*0.28))
    ax.view_init(elev=28, azim=-55)
    figure.subplots_adjust(left=.06, right=.94, bottom=.16, top=.84)


def response(figure, result, options=None):
    from .network import from_result
    network=from_result(result); analysis=network.analyze()
    quantity=(options or {}).get('network_quantity','Magnitude')
    figure.clear();ax=figure.add_subplot(111);f=network.frequencies_hz/1e9
    if quantity in ('Magnitude','Phase','Group delay'):
        key,scale,unit={'Magnitude':('magnitude_db',1,'dB'),'Phase':('phase_rad',180/np.pi,'deg'),'Group delay':('group_delay_s',1e9,'ns')}[quantity]
        values=analysis[key]
        for i in range(network.port_count):
            for j in range(network.port_count):ax.plot(f,values[:,i,j]*scale,'o-',markersize=3,label=f'S{i+1}{j+1}')
        ax.set_ylabel(quantity+' ['+unit+']')
    elif quantity=='Impedance':
        values=analysis['input_impedance_ohm']
        for i in range(network.port_count):
            ax.plot(f,values[:,i].real,'o-',markersize=3,label=f'Port {i+1} real');ax.plot(f,values[:,i].imag,'o--',markersize=3,label=f'Port {i+1} imaginary')
        ax.set_ylabel('Input impedance [ohm]')
    else:
        ax.plot(f,analysis['largest_singular_value'],'o-',markersize=3,label='Largest singular value')
        ax.plot(f,analysis['reciprocity_error'],'o-',markersize=3,label='Reciprocity error');ax.axhline(1,color='#87949d',linewidth=.8)
        ax.set_ylabel('Sample diagnostics [unitless]')
    ax.set_xlabel('Frequency [GHz]');ax.grid(alpha=.18);ax.legend(frameon=False,fontsize=8)
    spacing=np.diff(network.frequencies_hz)
    sampling=f'{len(f)} stored frequency samples'
    if len(spacing):sampling+=f' · max Δf {np.max(spacing)/1e6:.5g} MHz'
    ax.set_title(result.get('network_view_label','Original network samples')+' | '+quantity+'\n'+sampling,loc='left',fontsize=10)
    figure.tight_layout(pad=1.5)


def smith(figure, result):
    figure.clear()
    ax = figure.add_subplot(111)
    # Constant resistance/reactance circles transformed from normalized impedance.
    for r in (0, .2, .5, 1, 2, 5):
        x = np.linspace(-50, 50, 1500)
        gamma = (r+1j*x-1)/(r+1j*x+1)
        ax.plot(gamma.real, gamma.imag, color='#c6d0d5', linewidth=.6)
    for x in (-5, -2, -1, -.5, -.2, .2, .5, 1, 2, 5):
        z = np.linspace(0, 50, 500)+1j*x
        gamma = (z-1)/(z+1)
        ax.plot(gamma.real, gamma.imag, color='#c6d0d5', linewidth=.6)
    angle = np.linspace(0, 2*np.pi, 400)
    ax.plot(np.cos(angle), np.sin(angle), color='#667984', linewidth=1)
    values = np.array([complex(*v) for v in result['s_parameters']['S11']])
    ax.plot(values.real, values.imag, 'o-', color='#177e77', picker=6)
    ax.axhline(0, color='gray', linewidth=.5)
    reference=float(np.asarray(result.get('reference_impedance_ohm',result['config']['z0_ohm'])).reshape(-1)[0])
    ax.set(xlabel='Re Γ', ylabel='Im Γ', title=f'S11 • reference {reference:g} Ω • {len(values)} stored frequency samples\nClick an original sample to probe')
    ax.set_aspect('equal', adjustable='datalim')
    ax.grid(alpha=.15)
    figure.tight_layout()


def _field_style(values, options, default_cmap):
    from matplotlib import colormaps
    from matplotlib.colors import Normalize, LogNorm
    options = options or {}
    mode = options.get('scale', 'linear')
    data = np.ma.masked_invalid(np.asarray(values, dtype=float))
    if mode == 'log':
        data = np.ma.masked_less_equal(data, 0)
    try:
        lo, hi = scale_limits(data.compressed(), mode, options.get('minimum'), options.get('maximum'))
    except ValueError:
        if data.count() == 0:
            return data, None, colormaps[options.get('cmap', default_cmap)]
        raise
    norm = (LogNorm if mode == 'log' else Normalize)(vmin=lo, vmax=hi, clip=False)
    return data, norm, colormaps[options.get('cmap', default_cmap)]


def _field_values(field):
    return [[np.nan if v is None else v for v in row] for row in field.get('display_values', field.get('temperature_k', field.get('norm_e_v_m'))) ]


def near_field(figure, result, options=None):
    options = options or {}
    figure.clear()
    field = result.get('thermal', result.get('field'))
    ax = figure.add_subplot(111)
    if options.get('field', True):
        values, norm, cmap = _field_style(_field_values(field), options, 'inferno')
        if norm is None:
            ax.text(.5, .5, 'No plottable field data', ha='center', transform=ax.transAxes)
        else:
            image = ax.pcolormesh(field['x_mm'], field['y_mm'], values, shading='nearest', cmap=cmap, norm=norm)
            figure.colorbar(image, ax=ax, label=f"{field.get('display_quantity', 'Temperature' if 'temperature_k' in field else '|E|')} [{field.get('display_unit', 'K' if 'temperature_k' in field else 'V/m')}]")
    if options.get('mesh', False):
        for x in field['x_mm']:
            ax.axvline(x, color='white', alpha=.35, linewidth=.5)
        for y in field['y_mm']:
            ax.axhline(y, color='white', alpha=.35, linewidth=.5)
        ax.text(.02, .98, 'sample grid', transform=ax.transAxes, va='top')
    context=f"{field['time_s']:g} s" if 'temperature_k' in field else f"{field['frequency_hz']/1e9:g} GHz"
    ax.set(xlabel='X [mm]', ylabel='Y [mm]',
           title=f'Field plane Z={field["z_mm"]:g} mm • {context}\n'+plane_sampling_label(field))
    ax.set_aspect('equal')
    if result['config'].get('mode', 'patch') == 'pcb_region' and options.get('show_context', True):
        for shape in result['region']['substrate']['outline']:
            for ring in [shape['outer_mm']]+shape.get('holes_mm', []):
                points = np.array(ring+[ring[0]])
                ax.plot(points[:, 0], points[:, 1], color='#aaaaaa', linewidth=1, linestyle='--')
    figure.tight_layout()


def near_field3d(figure, result, options=None):
    from matplotlib.cm import ScalarMappable
    options = options or {}
    is_region = result['config'].get('mode', 'patch') == 'pcb_region'
    if is_region:
        from .region_view import geometry as region_geometry
        region_geometry(figure, result['region'], options)
    else:
        geometry(figure, result['config'], options)
    ax = figure.axes[0]
    field = result.get('thermal', result.get('field'))
    x, y = np.meshgrid(field['x_mm'], field['y_mm'])
    z = np.full(x.shape, field['z_mm'], dtype=float)
    if options.get('field', True):
        values, norm, cmap = _field_style(_field_values(field), options, 'inferno')
        if norm is None:
            ax.text2D(.5, .5, 'No plottable field data', ha='center', transform=ax.transAxes)
        else:
            # Retain every original cell, including dense planes. Vectorized
            # construction avoids a hidden 65-node decimation and the broad
            # averaging that previously erased narrow peaks and small holes.
            mask=np.ma.getmaskarray(values)
            valid=~(mask[:-1,:-1]|mask[:-1,1:]|mask[1:,1:]|mask[1:,:-1])
            xyz=np.stack((x,y,z),axis=-1)
            faces=np.stack((xyz[:-1,:-1],xyz[:-1,1:],xyz[1:,1:],xyz[1:,:-1]),axis=-2)[valid]
            samples=np.asarray(values.filled(np.nan))
            means=(samples[:-1,:-1]+samples[:-1,1:]+samples[1:,1:]+samples[1:,:-1])/4
            colors=cmap(norm(means[valid]))
            ax.add_collection3d(Poly3DCollection(faces,facecolors=colors,edgecolors='none',alpha=1.))
            figure.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=.65, label=f"{field.get('display_quantity', '|E|')} [{field.get('display_unit', 'V/m')}]")
    if options.get('mesh', False):
        ax.plot_wireframe(x, y, z, color='#dddddd', linewidth=.5,rstride=1,cstride=1)
        ax.text2D(.02, .98, 'sample grid', transform=ax.transAxes, va='top')
    thickness = result['region']['substrate']['thickness_mm'] if is_region else validate_config(result['config'])['thickness_mm']
    ax.set_zlim(-thickness*3, max(field['z_mm']*1.5, thickness*5))
    scope = 'Saved rule-area copper; exterior board omitted' if is_region else 'Template geometry; PCB context only'
    context=f"{field['time_s']:g} s" if 'temperature_k' in field else f"{field['frequency_hz']/1e9:g} GHz"
    ax.set_title(f'Solver field plane • {context} • Z={field["z_mm"]:g} mm\n'+plane_sampling_label(field)+'\n'+scope,fontsize=10)
    figure.subplots_adjust(left=.06, right=.94, bottom=.16, top=.84)


def radiation(figure, result, options=None):
    from matplotlib.cm import ScalarMappable
    options = options or {}
    figure.clear()
    if 'radiation' not in result:
        ax = figure.add_subplot(111)
        ax.text(.5, .5, 'Radiation surface is available for the patch model.', ha='center', transform=ax.transAxes)
        ax.set_axis_off()
        return
    field = result['radiation']
    t, p = np.meshgrid(field['theta_rad'], field['phi_rad'], indexing='ij')
    values = np.asarray(field['norm_e'], dtype=float)
    peak = values.max()
    if peak <= 0 or not np.isfinite(values).all():
        raise ValueError('Radiation field is empty or non-finite.')
    radius = values/peak
    ax = figure.add_subplot(111, projection='3d')
    if options.get('field', True):
        colors, norm, cmap = _field_style(radius, options, 'viridis')
        if norm is None:
            ax.text2D(.5, .5, 'No plottable radiation data', ha='center', transform=ax.transAxes)
        else:
            ax.plot_surface(radius*np.sin(t)*np.cos(p), radius*np.sin(t)*np.sin(p), radius*np.cos(t),
                            facecolors=cmap(norm(colors)),shade=False,linewidth=0,antialiased=True,
                            rcount=radius.shape[0],ccount=radius.shape[1])
            figure.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=.65, label='Relative |E| (normalized 0–1)')
    if options.get('mesh', False):
        ax.plot_wireframe(radius*np.sin(t)*np.cos(p), radius*np.sin(t)*np.sin(p), radius*np.cos(t),linewidth=.5,rstride=1,cstride=1)
        ax.text2D(.02, .98, 'sample grid', transform=ax.transAxes, va='top')
    ax.set(xlabel='X', ylabel='Y', zlabel='Z', title=f'Relative far-field |E| • {field.get("frequency_hz", 0)/1e9:g} GHz\n'+angular_sampling_label(field)+'\nNormalized radius; not gain, efficiency or physical distance')
    ax.set_box_aspect((1, 1, 1))
    figure.subplots_adjust(left=.06, right=.94, bottom=.18, top=.83)


def advanced_geometry(figure, config, options=None):
    """Software fallback for explicit templates; imported surfaces need solved mesh."""
    c=validate_config(config); study=c['advanced']['study']; figure.clear()
    ax=figure.add_subplot(111,projection='3d')
    sx,sy,th=c['substrate_x_mm'],c['substrate_y_mm'],c['thickness_mm']
    if study=='scattering':
        if c['advanced']['step_path']:
            ax.text2D(.1,.5,'Imported geometry is meshed in the solver; no template substitution.',transform=ax.transAxes)
        else:
            r=c['advanced']['scatter_radius_mm'];u,v=np.meshgrid(np.linspace(0,2*np.pi,49),np.linspace(0,np.pi,25))
            ax.plot_surface(r*np.cos(u)*np.sin(v),r*np.sin(u)*np.sin(v),r*np.cos(v),color='#c99c52')
            ax.set(xlim=(-r,r),ylim=(-r,r),zlim=(-r,r));ax.set_box_aspect((1,1,1))
    else:
        _plate(ax,-sx/2,-sy/2,sx,sy,-th/2,'#2a897d',.35)
        if study=='periodic':_plate(ax,-c['patch_width_mm']/2,-c['patch_length_mm']/2,c['patch_width_mm'],c['patch_length_mm'],0,'#c99c52')
        ax.set(xlim=(-sx*.6,sx*.6),ylim=(-sy*.6,sy*.6),zlim=(-th*2,th*2))
        ax.set_box_aspect((sx,sy,max(sx,sy)*.12))
    ax.set(xlabel='X [mm]',ylabel='Y [mm]',zlabel='Z [mm]',title=study.capitalize()+' geometry | explicit study model')
    figure.subplots_adjust(left=.03,right=.98,bottom=.08,top=.9)
