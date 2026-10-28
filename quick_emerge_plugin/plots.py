"""Native-window figures; geometry and results remain distinct views."""
import math

import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from .model import metrics, validate_config
from .inspection import scale_limits


def _plate(ax, x, y, width, length, z, color, alpha=1):
    vertices = [[(x, y, z), (x+width, y, z), (x+width, y+length, z), (x, y+length, z)]]
    ax.add_collection3d(Poly3DCollection(vertices, facecolors=color, edgecolors=color, alpha=alpha))


def geometry(figure, raw, options=None):
    options = options or {}
    c = validate_config(raw)
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
        if options.get('copper', True):
            _plate(ax, -w/2, -length/2+inset, w, length-inset, 0, '#d9a951')
            for x in (-w/2, feed/2+slot):
                _plate(ax, x, -length/2, w/2-feed/2-slot, inset, 0, '#d9a951')
            _plate(ax, -feed/2, -length/2, feed, inset, 0, '#d9a951')
        ports = [(0, -length/2)]
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


def response(figure, result):
    figure.clear()
    f = np.asarray(result['frequencies_hz'])/1e9
    s11 = [complex(*v) for v in result['s_parameters']['S11']]
    m = metrics(result['frequencies_hz'], s11, result['config']['z0_ohm'])
    ax, vswr = figure.subplots(2, 1, sharex=True)
    for name, values in result['s_parameters'].items():
        db = [20*math.log10(abs(complex(*v))) if any(v) else -np.inf for v in values]
        ax.plot(f, db, 'o-', label=name)
    ax.set(ylabel='|S| [dB]', title=f'Sampled minimum |S11|: {m["resonance_hz"]/1e9:.6g} GHz • no convergence claim')
    ax.axhline(-10, color='gray', linestyle='--', linewidth=0.8)
    ax.grid(alpha=.25)
    ax.legend()
    vswr.plot(f, [np.nan if v is None else v for v in m['vswr']], 'o-', color='#197f72')
    vswr.set(xlabel='Frequency [GHz]', ylabel='VSWR (passive only)')
    vswr.grid(alpha=.25)
    figure.tight_layout()


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
    ax.set(xlabel='Re Γ', ylabel='Im Γ', title=f'S11 • reference {result["config"]["z0_ohm"]:g} Ω • click a sample to probe')
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
    return [[np.nan if v is None else v for v in row] for row in field['norm_e_v_m']]


def near_field(figure, result, options=None):
    options = options or {}
    figure.clear()
    field = result['field']
    ax = figure.add_subplot(111)
    if options.get('field', True):
        values, norm, cmap = _field_style(_field_values(field), options, 'inferno')
        if norm is None:
            ax.text(.5, .5, 'No plottable field data', ha='center', transform=ax.transAxes)
        else:
            image = ax.pcolormesh(field['x_mm'], field['y_mm'], values, shading='nearest', cmap=cmap, norm=norm)
            figure.colorbar(image, ax=ax, label='|E| [V/m] • solver excitation')
    if options.get('mesh', False):
        for x in field['x_mm']:
            ax.axvline(x, color='white', alpha=.35, linewidth=.5)
        for y in field['y_mm']:
            ax.axhline(y, color='white', alpha=.35, linewidth=.5)
        ax.text(.02, .98, 'sample grid', transform=ax.transAxes, va='top')
    ax.set(xlabel='X [mm]', ylabel='Y [mm]',
           title=f'Field plane Z={field["z_mm"]:g} mm • {field["frequency_hz"]/1e9:g} GHz')
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
    field = result['field']
    x, y = np.meshgrid(field['x_mm'], field['y_mm'])
    z = np.full(x.shape, field['z_mm'], dtype=float)
    if options.get('field', True):
        values, norm, cmap = _field_style(_field_values(field), options, 'inferno')
        if norm is None:
            ax.text2D(.5, .5, 'No plottable field data', ha='center', transform=ax.transAxes)
        else:
            # A cell is omitted if any of its original corner samples is unknown.
            mask = np.ma.getmaskarray(values)
            faces = []
            colors = []
            # Reduce display cells on dense grids; inspection retains every original sample.
            x_indices = np.linspace(0, x.shape[1] - 1, min(x.shape[1], 65), dtype=int)
            y_indices = np.linspace(0, x.shape[0] - 1, min(x.shape[0], 65), dtype=int)
            for iy, jy in zip(y_indices, y_indices[1:]):
                for ix, jx in zip(x_indices, x_indices[1:]):
                    block = values[iy:jy+1, ix:jx+1]
                    if mask[iy:jy+1, ix:jx+1].any():
                        continue
                    corners = [(iy, ix), (iy, jx), (jy, jx), (jy, ix)]
                    faces.append([(x[j, i], y[j, i], z[j, i]) for j, i in corners])
                    colors.append(cmap(norm(float(np.mean(block)))))
            ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolors='none', alpha=.85))
            figure.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=.65, label='|E| [V/m]')
    if options.get('mesh', False):
        ax.plot_wireframe(x, y, z, color='#dddddd', linewidth=.5)
        ax.text2D(.02, .98, 'sample grid', transform=ax.transAxes, va='top')
    thickness = result['region']['substrate']['thickness_mm'] if is_region else validate_config(result['config'])['thickness_mm']
    ax.set_zlim(-thickness*3, max(field['z_mm']*1.5, thickness*5))
    scope = 'Saved rule-area copper; exterior board omitted' if is_region else 'Template geometry; PCB context only'
    ax.set_title(f'Solver field plane • {field["frequency_hz"]/1e9:g} GHz • Z={field["z_mm"]:g} mm\n{scope}')
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
                            facecolors=cmap(norm(colors)), shade=False, linewidth=0, antialiased=True)
            figure.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=.65, label='Relative |E| (normalized 0–1)')
    if options.get('mesh', False):
        ax.plot_wireframe(radius*np.sin(t)*np.cos(p), radius*np.sin(t)*np.sin(p), radius*np.cos(t), linewidth=.5)
        ax.text2D(.02, .98, 'sample grid', transform=ax.transAxes, va='top')
    ax.set(xlabel='X', ylabel='Y', zlabel='Z', title=f'Relative far-field |E| • {field["frequency_hz"]/1e9:g} GHz\nNormalized radius; not gain, efficiency or physical distance')
    ax.set_box_aspect((1, 1, 1))
    figure.subplots_adjust(left=.06, right=.94, bottom=.18, top=.83)
