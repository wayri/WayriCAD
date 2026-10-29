"""Exact clipped copper and enclosure display; never substitute a bounding box."""
import numpy as np
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from mpl_toolkits.mplot3d import art3d


def _path(shape):
    vertices, codes = [], []
    for i, raw in enumerate([shape['outer_mm']]+shape.get('holes_mm', [])):
        ring = [list(point) for point in raw]
        area = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(ring, ring[1:]+ring[:1]))
        if (area > 0) != (i == 0):
            ring.reverse()
        vertices.extend(ring+[ring[0]])
        codes.extend([Path.MOVETO]+[Path.LINETO]*(len(ring)-1)+[Path.CLOSEPOLY])
    return Path(vertices, codes)


def _rings(shapes):
    return [ring for shape in shapes for ring in [shape['outer_mm']]+shape.get('holes_mm', [])]


def _bounds(region):
    points = [p for shape in region['substrate']['outline'] for p in shape['outer_mm']]
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def board_context(figure, native_listing, options=None):
    """Show saved outline geometry before a copper extraction is reviewed.

    This accepts collect_regions' listing, not a manufactured substrate/port
    plan. Rule areas are drawn as supplied, including holes and concavities.
    """
    options = options or {}
    shapes = native_listing.get('board_outline', [])
    points = [point for shape in shapes for point in shape['outer_mm']]
    if not points:
        raise ValueError('The saved board has no outline to display.')
    figure.clear()
    axes = figure.add_subplot(111)
    for index, shape in enumerate(shapes):
        patch = PathPatch(_path(shape), facecolor='none', edgecolor='#687d8a',
                          linewidth=1.8, label='Board edge' if index == 0 else None)
        patch.set_gid('saved-board-outline'); axes.add_patch(patch)
    areas = native_listing.get('areas', [])
    unsupported = []
    visible = 0
    for area in areas:
        name = area.get('name') or area.get('id') or 'Unnamed enclosure'
        outlines = area.get('outline', [])
        if not outlines:
            unsupported.append(name)
            continue
        for shape in outlines:
            patch = PathPatch(_path(shape), facecolor='none', edgecolor='#148b88',
                linewidth=1.5, linestyle='--', label='Rule-area enclosure' if visible == 0 else None)
            patch.set_gid('saved-rule-area-outline'); axes.add_patch(patch); visible += 1
            points.extend(shape['outer_mm'])
        # Anchor the name to an actual contour vertex, not an invented center
        # that could lie outside a concave area or in a board cutout.
        axes.annotate(name, outlines[0]['outer_mm'][0], xytext=(6,6),
                      textcoords='offset points', fontsize=8, color='#148b88')
    x0,y0 = np.min(points,axis=0); x1,y1 = np.max(points,axis=0)
    margin=max(float(x1-x0),float(y1-y0))*.12 or 1.
    axes.set(xlim=(x0-margin,x1+margin),ylim=(y0-margin,y1+margin),
             xlabel='Board X [mm]',ylabel='Board Y [mm]')
    axes.set_title('Saved board outlines\nChoose enclosure and nets, review material, then Preview copper',fontsize=10,pad=12)
    axes.set_aspect('equal'); axes.grid(alpha=.15)
    axes.legend(loc='upper right',fontsize=8,frameon=False)
    notice='Outlines only · copper has not been extracted'
    if not areas: notice+='\nNo saved rule areas. Add an enclosure in KiCad, save, then reload.'
    if unsupported: notice+='\nUnavailable enclosure geometry: '+', '.join(unsupported)
    axes.text(.01,.01,notice,transform=axes.transAxes,fontsize=8,color='#617583',va='bottom',wrap=True)
    figure.tight_layout(pad=1.5)


def geometry(figure, region, options=None):
    options = options or {}
    figure.clear()
    axes = figure.add_subplot(111, projection='3d', computed_zorder=False)
    thickness = region['substrate']['thickness_mm']
    def plate(shape, z, color, alpha):
        patch = PathPatch(_path(shape), facecolor=color, edgecolor=color, alpha=alpha)
        axes.add_patch(patch)
        art3d.pathpatch_2d_to_3d(patch, z=z)
    if options.get('show_context', True):
        for shape in region['substrate']['outline']:
            plate(shape, -thickness/2, '#28876c', .3)
    if options.get('copper', True):
        for row in region['copper']:
            for shape in row['polygons']:
                plate(shape, 0 if row['layer'] == 'F.Cu' else -thickness,
                      '#e4b65d' if row['layer'] == 'F.Cu' else '#698cad', .9)
    if options.get('ports', True):
        for port in region['ports']:
            a, b = np.array(port['a_mm']), np.array(port['b_mm'])
            x, y = (a+b)/2
            axes.plot([x, x], [y, y], [-thickness, 0], color='#f25379', linewidth=4)
            axes.text(x, y, thickness*.5, f'P{port["number"]}', color='#f25379')
    x0, y0, x1, y1 = _bounds(region)
    margin = max(x1-x0, y1-y0)*.08
    axes.set(xlim=(x0-margin, x1+margin), ylim=(y0-margin, y1+margin), zlim=(-thickness*2, thickness*3),
             xlabel='Board X [mm]', ylabel='Board Y [mm]', zlabel='Z [mm]',
             title=f'Saved copper • {region["area"].get("name") or region["area"]["id"]}\nPolygon crop; exterior board and components omitted')
    axes.view_init(elev=28, azim=-55)
    figure.subplots_adjust(left=.06, right=.94, bottom=.16, top=.84)


def enclosure(figure, region, options=None):
    options = options or {}
    figure.clear()
    axes = figure.add_subplot(111)
    if options.get('show_context', True):
        for ring in _rings(region.get('board_outline', [])):
            points = np.array(ring+[ring[0]])
            axes.plot(points[:, 0], points[:, 1], color='#7c8995', linewidth=1, alpha=.5)
    for shape in region['substrate']['outline']:
        axes.add_patch(PathPatch(_path(shape), facecolor='#27856b', edgecolor='#22b78f', alpha=.25))
    if options.get('copper', True):
        for row in sorted(region['copper'], key=lambda row: row['layer'] == 'F.Cu'):
            for shape in row['polygons']:
                axes.add_patch(PathPatch(_path(shape), facecolor='#dfb456' if row['layer'] == 'F.Cu' else '#5487ac', alpha=.7))
    if options.get('ports', True):
        for port in region['ports']:
            points = np.array([port['a_mm'], port['b_mm']])
            axes.plot(points[:, 0], points[:, 1], color='#e33963', linewidth=3)
            center = points.mean(axis=0)
            axes.annotate(f'P{port["number"]}', center, xytext=(6, 6), textcoords='offset points', color='#bc1f4c')
    x0, y0, x1, y1 = _bounds(region)
    margin = max(x1-x0, y1-y0)*.18
    axes.set(xlim=(x0-margin, x1+margin), ylim=(y0-margin, y1+margin), xlabel='Board X [mm]', ylabel='Board Y [mm]',
             title=f'Rule-area enclosure • {region["area"].get("name") or region["area"]["id"]}\nOnly clipped copper enters the solver; pink edges are ideal ports')
    axes.set_aspect('equal')
    axes.grid(alpha=.2)
    figure.tight_layout()
