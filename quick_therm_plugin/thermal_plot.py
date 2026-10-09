"""Top-side saved-board display of lumped QuickTherm component estimates."""
from __future__ import annotations

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import Normalize
from matplotlib.patches import Polygon, Rectangle
from wayricad_runtime.thermal_field import field_available, _draw_field


def default_thermal_mode(view, network=None, side='top'):
    """Prefer solved physical fields; junction fallback has partial support only."""
    network=network or {};bottom=side=='bottom';prefix='Bottom' if bottom else 'Top'
    layers=network.get('layers',[])
    preferred=[row for row in layers if row.get('name','').startswith('B.' if bottom else 'F.')]
    for field in [*preferred,*[row for row in layers if row not in preferred]]:
        if field_available(field):return 'Layer model: '+field['name']
    if field_available(network.get('board_field',{})):return prefix+' board model'
    field=view.get('fields_by_side',{}).get(side,view.get('field',{}))
    if field_available(field):return prefix+'-side contour'
    return prefix+'-side map'


def _field_norm(field, temperature_limits_c):
    """Keep caller-supplied shared scales and expand an otherwise constant field."""
    if temperature_limits_c:return Normalize(*temperature_limits_c)
    values=[float(value) for row in field.get('values_c',[]) for value in row
            if value is not None and np.isfinite(value)]
    low,high=(min(values),max(values)) if values else (0.,1.)
    if low==high:low-=.5;high+=.5
    return Normalize(low,high)


def _board_clip(ax, view):
    """Compound saved outline and drilled voids, suitable for contour clipping."""
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    vertices, codes = [], []
    def add(ring, hole=False):
        if len(ring) < 3:
            return
        area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring, ring[1:]+ring[:1]))
        points = list(reversed(ring)) if (area > 0) == hole else ring
        vertices.extend(points + [points[0]])
        codes.extend([Path.MOVETO] + [Path.LINETO]*(len(points)-1) + [Path.CLOSEPOLY])
    for shape in view.get('outline', []):
        add(shape.get('outer_mm', []))
        for ring in shape.get('holes_mm', []):
            add(ring, True)
    for drill in view.get('drills', []):
        add(drill.get('contour_mm', []), True)
    return PathPatch(Path(vertices, codes), transform=ax.transData) if vertices else None


def _clip_contour(mesh, clip):
    if clip is None:
        return
    if hasattr(mesh, 'set_clip_path'):
        mesh.set_clip_path(clip)
    else:
        for collection in mesh.collections:
            collection.set_clip_path(clip)


def _draw_supported_field(ax, field, view, norm, clip):
    """Apply the saved drill/slot mask to both cell support and smooth overlay."""
    start=len(ax.collections)
    mesh=_draw_field(ax,field,view,norm,0)
    for artist in list(ax.collections)[start:]:
        _clip_contour(artist,clip)
    return mesh


def _field_edges(field, axis):
    """Use solver cell edges, with a midpoint fallback for older reports."""
    edges = field.get(f'{axis}_edges_mm')
    centers = field.get(f'{axis}_centers_mm', [])
    if edges is not None:
        if len(edges) != len(centers)+1 or any(b <= a for a, b in zip(edges, edges[1:])):
            raise ValueError(f'Invalid {axis} thermal field edges.')
        return edges
    if len(centers) > 1:
        mids = [(a+b)/2 for a, b in zip(centers, centers[1:])]
        return [centers[0]-(mids[0]-centers[0]), *mids,
                centers[-1]+(centers[-1]-mids[-1])]
    if centers:
        return [centers[0]-.5, centers[0]+.5]
    return []


def _field_quads(field, z):
    """Return one true cell rectangle and temperature per active field cell."""
    x_edges = _field_edges(field, 'x')
    y_edges = _field_edges(field, 'y')
    quads, values = [], []
    for j, row in enumerate(field.get('values_c', [])):
        for i, value in enumerate(row):
            if value is None:
                continue
            quads.append([(x_edges[i], y_edges[j], z),
                          (x_edges[i+1], y_edges[j], z),
                          (x_edges[i+1], y_edges[j+1], z),
                          (x_edges[i], y_edges[j+1], z)])
            values.append(value)
    return quads, values


def _draw_3d(figure,view,selected_id,network,azim,elev,probes=None):
    """Illustrative saved-board extrusion, not imported 3D component models."""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    ax=figure.add_subplot(111,projection='3d')
    thickness=view.get('board_thickness_mm') or 1.6
    for shape in view.get('outline',[]):
        outer=shape.get('outer_mm',[])
        if len(outer)<3:continue
        for z in (0,thickness):
            ax.plot([p[0] for p in outer]+[outer[0][0]],
                    [p[1] for p in outer]+[outer[0][1]],zs=z,color='#315e68',linewidth=1.8)
        for p in outer:ax.plot([p[0],p[0]],[p[1],p[1]],[0,thickness],color='#62939c',linewidth=.7)
        ax.add_collection3d(Poly3DCollection([[(p[0],p[1],thickness) for p in outer]],
                                            facecolor='#b7d5c7',alpha=.20,edgecolor='none'))
    field=(network or {}).get('board_field',{})
    if (network or {}).get('layers'):
        field=network['layers'][0]
    if field.get('values_c'):
        quads, values = _field_quads(field, thickness+.02)
        if quads:
            lo=min(values);hi=max(values)
            colors=[colormaps['inferno'](.5 if hi==lo else (value-lo)/(hi-lo))
                    for value in values]
            ax.add_collection3d(Poly3DCollection(quads,facecolors=colors,edgecolor='none',alpha=.55))
    voids = [hole for shape in view.get('outline', []) for hole in shape.get('holes_mm', [])]
    voids.extend(drill['contour_mm'] for drill in view.get('drills', []))
    if voids:
        ax.add_collection3d(Poly3DCollection(
            [[(p[0], p[1], thickness+.05) for p in ring] for ring in voids],
            facecolor='#091720', edgecolor='#88a6b0', linewidth=.25))
    solved=[item['junction_c'] for item in view.get('components',[]) if item.get('junction_c') is not None]
    low=min(solved) if solved else 0;high=max(solved) if solved else 1
    for item in view.get('components',[]):
        if not item.get('position_mm'):continue
        x,y=item['position_mm'];top=item.get('top_side',True)
        z=thickness+.8 if top else -.8
        value=item.get('junction_c')
        color='#758591' if value is None else colormaps['inferno'](.5 if high==low else (value-low)/(high-low))
        ax.scatter([x],[y],[z],color=[color],s=145 if item['id']==selected_id else (70 if item.get('in_scope') else 0),
                   edgecolor='#00d3b1' if item['id']==selected_id else 'white',depthshade=False)
        box = item.get('bbox_mm')
        if box:
            corners=[(box[0],box[1],z),(box[2],box[1],z),(box[2],box[3],z),(box[0],box[3],z)]
            ax.add_collection3d(Poly3DCollection([corners],facecolor=color,edgecolor='#294352',alpha=.6,linewidth=.4))
        if item.get('in_scope') or item['id']==selected_id:
            ax.text(x,y,z+.25,item['reference'],fontsize=8)
        ax.plot([x,x],[y,y],[thickness if top else 0,z],color='#576d70',linewidth=.7)
    bbox=view.get('bbox_mm')
    if bbox:
        x0,y0,x1,y1=bbox;ax.set_xlim(x0,x1);ax.set_ylim(y1,y0)
        ax.set_box_aspect((max(x1-x0,1),max(y1-y0,1),max(thickness*5,4)),zoom=.9)
    for probe in probes or []:
        x,y=probe['x_mm'],probe['y_mm'];z=thickness+.12 if probe.get('side')!='bottom' else -.12
        ax.scatter([x],[y],[z],color='#00d3b1',marker='+',s=90,depthshade=False)
        value=probe.get('temperature_c');label=probe['label']+(' unknown' if value is None else f' {value:.2f} °C')
        ax.text(x,y,z,label,fontsize=8)
    ax.set_zlim(-1.2,thickness+1.5);ax.set_zticks([0, thickness])
    ax.set_xlabel('X mm');ax.set_ylabel('Y mm');ax.set_zlabel('Board Z mm')
    ax.view_init(elev=elev,azim=azim)
    ax.set_title('Saved board 3D overview · marker heights illustrative')
    figure.tight_layout();return ax


def draw_thermal_view(figure, view, mode='Top-side map', selected_id=None,
                      network=None,azim=-60,elev=28,probes=None,
                      temperature_limits_c=None):
    figure.clear()
    if mode=='3D overview':return _draw_3d(figure,view,selected_id,network,azim,elev,probes)
    ax=figure.add_subplot(111)
    components=view.get('components',[])
    field=view.get('field',{})
    if mode=='Temperature chart':
        rows=sorted((item for item in components if item.get('solved')),key=lambda item:item['junction_c'])
        if rows:
            ax.barh([item['reference'] for item in rows],[item['junction_c'] for item in rows],
                    color=['#e07337' if item['id']==selected_id else '#408d9b' for item in rows])
            ax.set_xlabel('Estimated component junction °C')
        else:ax.text(.5,.5,'No solved components',ha='center',transform=ax.transAxes)
        figure.tight_layout();return ax

    layer_name=mode.partition('Layer model: ')[2] if mode.startswith('Layer model: ') else None
    bottom='Bottom' in mode or bool(layer_name and layer_name.startswith('B.'))
    side='bottom' if bottom else 'top'
    clip = _board_clip(ax, view)
    contour='contour' in mode.lower()
    board_model='board model' in mode.lower() or bool(layer_name)
    field=view.get('fields_by_side',{}).get(side,field)
    if not board_model and field_available(field):
        mesh=_draw_supported_field(ax,field,view,_field_norm(field,temperature_limits_c),clip)
        if mesh is not None:
            figure.colorbar(mesh,ax=ax,label='Partial junction interpolation °C (not board temperature)')
        hull=field.get('support_hull_mm',[])
        if len(hull)>=3:
            boundary=Polygon(hull,closed=True,fill=False,linestyle='--',linewidth=1.5,
                             edgecolor='#667b88',zorder=3)
            boundary.set_gid('quicktherm-junction-support-hull')
            ax.add_patch(boundary)
        ax.text(.5,.02,'Partial junction interpolation · dashed boundary is the component anchor hull\n'
                'Blank regions are unknown · Whole-board study… opens physical materials and boundaries',
                ha='center',va='bottom',fontsize=8,transform=ax.transAxes,
                bbox={'facecolor':'white','alpha':.9,'edgecolor':'none'})
    elif contour:
        ax.text(.5,.05,field.get('reason') or 'Contour unavailable',ha='center',va='bottom',
                transform=ax.transAxes,bbox={'facecolor':'white','alpha':.9,'edgecolor':'none'})
    display_layer_name = layer_name
    if board_model:
        model_field=(network or {}).get('board_field',{})
        if (network or {}).get('layers'):
            layers=network['layers']
            model_field=next((row for row in layers if row['name']==layer_name),layers[-1 if bottom else 0])
            display_layer_name = model_field['name']
        if field_available(model_field):
            mesh=_draw_supported_field(ax,model_field,view,_field_norm(model_field,temperature_limits_c),clip)
            if mesh is not None:
                figure.colorbar(mesh,ax=ax,label=('Layer temperature °C' if (network or {}).get('layers') else 'Approximate board midplane °C'))
        else:ax.text(.5,.05,'Run the optional board heat model for this field.',ha='center',va='bottom',
                     transform=ax.transAxes,bbox={'facecolor':'white','alpha':.9,'edgecolor':'none'})
    for outline in view.get('outline',[]):
        outer=outline.get('outer_mm',[])
        if len(outer)>=3:
            ax.add_patch(Polygon(outer,closed=True,fill=False,edgecolor='#315e68',linewidth=2))
        for hole in outline.get('holes_mm',[]):
            if len(hole)>=3:ax.add_patch(Polygon(hole,closed=True,fill=False,edgecolor='#315e68',linewidth=1))
    from matplotlib.collections import LineCollection
    drill_lines = [ring + [ring[0]] for drill in view.get('drills', [])
                   if (ring := drill.get('contour_mm', []))]
    if drill_lines:
        ax.add_collection(LineCollection(drill_lines, colors='#b9d5e0', linewidths=.5, zorder=3))
    bbox=view.get('bbox_mm')
    if bbox and not view.get('outline'):
        x0,y0,x1,y1=bbox
        ax.add_patch(Polygon([[x0,y0],[x1,y0],[x1,y1],[x0,y1]],closed=True,fill=False,
                             linestyle='--',edgecolor='#888'))
    shown=[item for item in components if item.get('side')==side]
    solved=[item for item in shown if item.get('solved') and item.get('position_mm')]
    temps=[item['junction_c'] for item in solved]
    low=min(temps) if temps else None;high=max(temps) if temps else None
    if temperature_limits_c:
        low, high = temperature_limits_c
    modeled={item['reference']:item for item in (network or {}).get('components',[])} if board_model else {}
    for item in shown:
        position=item.get('position_mm')
        if not position:continue
        current=item['id']==selected_id
        value=(modeled.get(item['reference'],{}).get('junction_c') if board_model
               else item.get('junction_c'))
        color=('#f7fafc' if value is not None else '#697985') if board_model else (
            '#697985' if value is None else colormaps['inferno'](
                .5 if high==low else (value-low)/(high-low)))
        box=item.get('bbox_mm')
        if box and len(box)==4:
            ax.add_patch(Rectangle((box[0],box[1]),box[2]-box[0],box[3]-box[1],
                                   fill=False,edgecolor='#315e68',linewidth=.6,alpha=.55,zorder=3))
        ax.scatter(*position,s=195 if current else (95 if item.get('in_scope') else 0),marker='o',
                   facecolor=color,edgecolor='#00d3b1' if current else ('#344b56' if board_model else 'white'),
                   linewidth=2 if current else .8,zorder=4)
        if item.get('in_scope'):
            label=item['reference']+(f" Tj≈{value:.1f}°C" if value is not None else '')
            ax.annotate(label,position,xytext=(5,5),textcoords='offset points',
                        fontsize=8,fontweight='bold' if current else 'normal',zorder=5,
                        bbox={'facecolor':'white','alpha':.8,'edgecolor':'none','pad':1})
    for probe in probes or []:
        if probe.get('side') != side:
            continue
        x,y=probe['x_mm'],probe['y_mm']
        ax.scatter([x],[y],s=120,marker='x',color='#00d3b1',linewidth=2.5,zorder=6)
        value=probe.get('temperature_c')
        label=probe['label']+(f" ≈{value:.1f}°C" if value is not None else ' unknown')
        ax.annotate(label,(x,y),xytext=(7,-10),textcoords='offset points',
                    fontsize=9,color='#074f49',fontweight='bold',zorder=7,
                    bbox={'facecolor':'white','alpha':.82,'edgecolor':'none','pad':1.5})
    if not shown:
        ax.text(.5,.5,'No saved '+side+'-side footprints',ha='center',transform=ax.transAxes)
    if bbox:
        x0,y0,x1,y1=bbox;pad=max(x1-x0,y1-y0)*.05 or 1
        ax.set_xlim((x1+pad,x0-pad) if bottom else (x0-pad,x1+pad));ax.set_ylim(y1+pad,y0-pad)
    else:ax.invert_yaxis()
    ax.set_aspect('equal',adjustable='box');ax.set_xlabel('X mm'+(' · mirrored bottom view' if bottom else ''));ax.set_ylabel('Y mm')
    ax.set_title('Saved PCB '+side+' view · '+((display_layer_name+' copper layer' if display_layer_name else 'approximate board midplane') if board_model else
                 'partial same-side junction interpolation · anchor hull' if contour else 'component estimates with partial junction overlay'))
    figure.tight_layout();return ax


def draw_temperature_comparison(figure, bundle):
    """Plot known junction/case temperatures and explicit per-part limits.

    Board-site temperature is a separate quantity and never substituted for a
    missing package case temperature. Unknown values do not become zero.
    """
    figure.clear()
    ax = figure.add_subplot(111)
    network = bundle.get('thermal_network') or {}
    rows = network.get('components') or bundle.get('quick_therm', {}).get('components', [])
    rows = sorted(rows, key=lambda row: row['reference'])
    positions = np.arange(len(rows))
    for key, label, marker, color in (
            ('junction_c', 'Estimated junction', 'o', '#c95638'),
            ('case_c', 'Package case (when solved)', 's', '#286f9c'),
            ('board_site_c', 'Board contact site (not package case)', '^', '#3d927d')):
        known = [(i, row[key]) for i, row in enumerate(rows) if row.get(key) is not None]
        if known:
            ax.scatter([value for _, value in known], [i for i, _ in known],
                       marker=marker, color=color, label=label, zorder=3)
    limits = {row['reference']: row for row in (bundle.get('temperature_limits') or {}).get('rows', [])}
    for i, row in enumerate(rows):
        limit = limits.get(row['reference'], {})
        for key, label, color in (('minimum_c', 'Minimum limit', '#438eb1'),
                                  ('maximum_c', 'Maximum limit', '#b94b58')):
            if limit.get(key) is not None:
                ax.plot([limit[key], limit[key]], [i-.3, i+.3], color=color,
                        linewidth=2, label=label if label not in ax.get_legend_handles_labels()[1] else None)
    ax.set_yticks(positions, [row['reference'] for row in rows])
    ax.set_xlabel('Temperature °C'); ax.set_ylabel('Component'); ax.grid(axis='x', alpha=.2)
    ax.set_title('Board-model component temperatures' if network else 'Independent component temperatures')
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc='best', fontsize=8)
    else:
        ax.text(.5, .5, 'No computed temperatures', ha='center', transform=ax.transAxes)
    if not any(row.get('case_c') is not None for row in rows):
        figure.text(.5, .015, 'Package case temperatures are unknown; board contact temperature is not case temperature.',
                    ha='center', fontsize=8)
    figure.tight_layout(rect=(0, .045, 1, 1))
    return ax
