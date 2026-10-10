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
            if value is None or not np.isfinite(value):
                continue
            quads.append([(x_edges[i], y_edges[j], z),
                          (x_edges[i+1], y_edges[j], z),
                          (x_edges[i+1], y_edges[j+1], z),
                          (x_edges[i], y_edges[j+1], z)])
            values.append(value)
    return quads, values


def _component_label(item, value):
    kind='Body' if item.get('temperature_kind')=='body' else 'Tj'
    return item['reference']+(f' {kind}≈{value:.1f}°C' if value is not None else ' '+kind+' unknown')


def _install_component_hover(ax, targets, selected_id, three_d=False):
    """Keep one reusable hover label; component markers and fields stay intact."""
    ax._thermal_targets=targets;ax._thermal_selected_id=selected_id
    ax._thermal_hover_id=None;ax._thermal_hover_3d=three_d
    if three_d:
        label=ax.text(0,0,0,'',fontsize=8,zorder=1e6,
                      bbox={'facecolor':'white','alpha':.95,'edgecolor':'none','pad':2})
    else:
        label=ax.annotate('',(0,0),xytext=(9,9),textcoords='offset points',
                          fontsize=8,zorder=10,annotation_clip=True,
                          bbox={'facecolor':'white','alpha':.95,'edgecolor':'none','pad':2})
    label.set_visible(False);label.set_gid('quicktherm-component-hover')
    ax._thermal_hover_label=label


def update_component_hover(ax, event=None):
    """Label only the footprint/marker under the pointer, without rebuilding maps.

    Marker proximity is measured in display pixels so it follows pan, zoom and
    3D rotation. Planar views also accept a hit inside the saved footprint box.
    """
    label=getattr(ax,'_thermal_hover_label',None)
    if label is None:return None
    hit=component_at_event(ax,event)
    identifier=hit['id'] if hit and hit['id']!=ax._thermal_selected_id else None
    if identifier==ax._thermal_hover_id:return identifier
    ax._thermal_hover_id=identifier;label.set_visible(identifier is not None)
    if identifier is not None:
        label.set_text(hit['label'])
        if ax._thermal_hover_3d:label.set_position_3d(hit['position'])
        else:
            label.xy=hit['position'][:2]
            right=event.x>ax.bbox.x0+ax.bbox.width/2;top=event.y>ax.bbox.y0+ax.bbox.height/2
            label.set_position((-9 if right else 9,-9 if top else 9))
            label.set_horizontalalignment('right' if right else 'left')
            label.set_verticalalignment('top' if top else 'bottom')
    ax.figure.canvas.draw_idle()
    return identifier


def component_at_event(ax, event=None):
    """Pick current projected footprint bounds or a marker within 14 pixels.

    Return the hover target (id, reference, side, junction_c and world position)
    without changing the view or labels. Projection is recalculated after orbit,
    zoom and pan, so callers can use this for selection as well as hover.
    """
    targets=getattr(ax,'_thermal_targets',[])
    if event is None or event.inaxes is not ax or not targets:
        return None
    positions=np.asarray([row['position'] for row in targets],dtype=float)
    if getattr(ax,'_thermal_hover_3d',False):
        from matplotlib.path import Path
        from mpl_toolkits.mplot3d import proj3d
        projection=ax.get_proj()
        x,y,depth=proj3d.proj_transform(*positions.T,projection)
        pixels=ax.transData.transform(np.column_stack((x,y)))
        inside=[]
        for row in targets:
            box=row.get('bbox')
            if not box:
                inside.append(False);continue
            z=row['position'][2]
            corners=np.asarray([(box[0],box[1],z),(box[2],box[1],z),
                                (box[2],box[3],z),(box[0],box[3],z)])
            px,py,_=proj3d.proj_transform(*corners.T,projection)
            polygon=ax.transData.transform(np.column_stack((px,py)))
            inside.append(Path(polygon).contains_point((event.x,event.y)))
        inside=np.asarray(inside)
    else:
        pixels=ax.transData.transform(positions[:,:2]);depth=np.zeros(len(targets))
        inside=np.asarray([bool(row.get('bbox') and event.xdata is not None and event.ydata is not None and
                           row['bbox'][0]<=event.xdata<=row['bbox'][2] and row['bbox'][1]<=event.ydata<=row['bbox'][3])
                           for row in targets])
    distances=((pixels-[event.x,event.y])**2).sum(axis=1)
    candidates=np.flatnonzero(inside | (distances<=14**2))
    return targets[min(candidates,key=lambda i:(distances[i],depth[i]))] if len(candidates) else None


def _supported_3d_cells(field):
    """Finite-volume cells have area; sampled fields require four known corners."""
    from wayricad_runtime.thermal_field import _cell_edges, _field_values
    values=_field_values(field)
    if values.ndim!=2:return []
    edges=_cell_edges(field,values)
    if edges is not None:
        quads,temperatures=_field_quads(field,0.)
        return [(quad[0][0],quad[0][1],quad[2][0],quad[2][1],float(value))
                for quad,value in zip(quads,temperatures)]
    # Point samples do not support the extrapolated half-cell margins, isolated
    # samples or a quad with one unknown corner. Match the planar field contract.
    xs,ys=field.get('x_centers_mm',[]),field.get('y_centers_mm',[])
    if values.shape!=(len(ys),len(xs)):return []
    cells=[]
    for j in range(len(ys)-1):
        for i in range(len(xs)-1):
            quad=values[j:j+2,i:i+2]
            if quad.count()==4:
                cells.append((xs[i],ys[j],xs[i+1],ys[j+1],float(quad.mean())))
    return cells


def _clipped_field_faces(field,z,tiles):
    """Clip supported thermal areas to exact board contours, including drills."""
    from .thermal_mesh import clip_rectangle
    if not tiles:return [],[]
    bounds=np.asarray([(min(p[0] for p in tile),min(p[1] for p in tile),
                        max(p[0] for p in tile),max(p[1] for p in tile)) for tile in tiles])
    faces=[];values=[]
    for x0,y0,x1,y1,value in _supported_3d_cells(field):
        candidates=np.flatnonzero((bounds[:,0]<x1)&(bounds[:,2]>x0)&
                                  (bounds[:,1]<y1)&(bounds[:,3]>y0))
        for index in candidates:
            clipped=clip_rectangle(tiles[index],(x0,y0,x1,y1))
            if clipped:
                faces.append([(x,y,z) for x,y in clipped]);values.append(value)
    return faces,values


def _field_planes(view,network,thickness):
    """World Z uses bottom=0; solver layer Z is saved depth below the top."""
    planes=[]
    if network.get('layers'):
        layers=network['layers']
        for index,field in enumerate(layers):
            side='top' if index==0 else 'bottom' if index==len(layers)-1 else 'internal'
            depth=field.get('z_mm')
            # Legacy results lacking layer depth can be shown on an explicitly
            # identified exterior face, never at an invented interior depth.
            z=thickness-float(depth) if depth is not None else (0. if side=='bottom' else thickness)
            source=' imported CalculiX surface field' if 'CalculiX' in network.get('model','') else ' layer model'
            planes.append({'field':field,'z_mm':z,'side':side,
                           'source':field.get('name','Unnamed layer')+source})
    elif network.get('board_field'):
        planes.append({'field':network['board_field'],'z_mm':thickness/2,'side':'midplane',
                       'source':'thin-sheet board midplane model (one shared field)'})
    else:
        for side,z in (('top',thickness),('bottom',0.)):
            field=view.get('fields_by_side',{}).get(side,{})
            if not field and side=='top':field=view.get('field',{})
            planes.append({'field':field,'z_mm':z,'side':side,
                           'source':side+' partial junction interpolation (not board temperature)'})
    return planes


def fit_thermal_3d(ax):
    """Fit complete saved geometry for the current camera without changing units.

    A fixed Matplotlib zoom crops long or tall boards at some orbit angles.
    Project the complete bounds and reduce display zoom until all corners fit.
    Call after restoring limits/camera when implementing a native Fit action.
    """
    from mpl_toolkits.mplot3d import proj3d
    aspect=getattr(ax,'_thermal_fit_aspect',None)
    if aspect is None:return
    ax.apply_aspect()
    limits=[ax.get_xlim(),ax.get_ylim(),ax.get_zlim()]
    corners=np.asarray([(x,y,z) for x in limits[0] for y in limits[1] for z in limits[2]])
    zoom=1.7 if getattr(ax,'_thermal_viewport',False) else .92
    for _ in range(4):
        ax.set_box_aspect(aspect,zoom=zoom)
        x,y,_=proj3d.proj_transform(*corners.T,ax.get_proj())
        pixels=ax.transData.transform(np.column_stack((x,y)))
        center=np.asarray([ax.bbox.x0+ax.bbox.width/2,ax.bbox.y0+ax.bbox.height/2])
        extent=np.max(np.abs(pixels-center),axis=0)
        ratio=min((ax.bbox.width*.46)/max(extent[0],1.),
                  (ax.bbox.height*.46)/max(extent[1],1.))
        if ratio>=1.:break
        zoom*=ratio*.98


def _draw_3d(figure,view,selected_id,network,azim,elev,probes=None,
             temperature_limits_c=None,viewport=False):
    """Saved board, actual placed STEP meshes and reviewed part temperatures."""
    from matplotlib.cm import ScalarMappable
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from .thermal_mesh import board_tiles
    network=network or {};ax=figure.add_subplot(111,projection='3d')
    saved_thickness=view.get('board_thickness_mm')
    thickness=float(saved_thickness) if saved_thickness is not None and np.isfinite(saved_thickness) and saved_thickness>0 else 0.
    planes=_field_planes(view,network,thickness)
    available=[plane for plane in planes if field_available(plane['field'])]
    has_model=bool(network.get('layers') or network.get('board_field'))
    temperatures=[float(value) for plane in available for row in plane['field'].get('values_c',[])
                  for value in row if value is not None and np.isfinite(value)]
    modeled={row['reference']:row for row in network.get('components',[])}
    models=view.get('component_models',{}).get('components',{})
    temperatures.extend(float(row['component_temperature_c']) for row in modeled.values()
                        if row.get('component_temperature_c') is not None)
    if not temperatures and not has_model:
        temperatures=[float(part['junction_c']) for part in view.get('components',[])
                      if part.get('junction_c') is not None and np.isfinite(part['junction_c'])]
    norm=_field_norm({'values_c':[temperatures]},temperature_limits_c)
    solid_faces=[];solid_colors=[]
    def add_surface(artist,faces,colors):
        if models:
            solid_faces.extend(faces)
            solid_colors.extend(colors if not isinstance(colors,str) else [colors]*len(faces))
        else:ax.add_collection3d(artist)
    tiles=board_tiles(view)
    # Both faces and the walls use the same saved contours. Holes are open from
    # either camera direction; no background-colored caps simulate a void.
    if tiles and not available:
        surfaces=[[(x,y,z) for x,y in tile] for z in sorted({0.,thickness}) for tile in tiles]
        substrate=Poly3DCollection(surfaces,facecolor='#c6d2d0',edgecolor='none',antialiased=False)
        substrate.set_gid('quicktherm-board-faces');add_surface(substrate,surfaces,'#c6d2d0')
    rings=[ring for shape in view.get('outline',[]) for ring in [shape.get('outer_mm',[]),*shape.get('holes_mm',[])]]
    rings.extend(drill.get('contour_mm',[]) for drill in view.get('drills',[]))
    walls=[]
    for ring in rings:
        if len(ring)<3:continue
        for z in sorted({0.,thickness}):
            ax.plot([p[0] for p in ring]+[ring[0][0]],
                    [p[1] for p in ring]+[ring[0][1]],zs=z,color='#567578',linewidth=.55)
        if thickness:
            walls.extend([[(a[0],a[1],0.),(b[0],b[1],0.),
                           (b[0],b[1],thickness),(a[0],a[1],thickness)]
                          for a,b in zip(ring,ring[1:]+ring[:1])])
    if walls:
        wall_artist=Poly3DCollection(walls,facecolor='#668185',edgecolor='none',antialiased=False)
        wall_artist.set_gid('quicktherm-board-walls');add_surface(wall_artist,walls,'#668185')
    ax._thermal_field_planes=[]
    for plane in planes:
        faces,values=_clipped_field_faces(plane['field'],plane['z_mm'],tiles) if field_available(plane['field']) else ([],[])
        metadata={key:value for key,value in plane.items() if key!='field'}
        metadata.update(available=bool(faces),face_count=len(faces))
        ax._thermal_field_planes.append(metadata)
        if faces:
            mesh=Poly3DCollection(faces,facecolors=colormaps['inferno'](norm(values)),antialiased=False,
                                  edgecolor='none',alpha=1. if plane['side']!='internal' else .5)
            mesh.set_gid('quicktherm-field-'+plane['side']+'-'+plane['source'])
            add_surface(mesh,faces,colormaps['inferno'](norm(values)))
    targets=[];extent_points=[]
    for item in view.get('components',[]):
        position=item.get('position_mm')
        if not position:continue
        x,y=position;top=item.get('side','top' if item.get('top_side',True) else 'bottom')=='top'
        # Marker offset is for reading/picking only, never package height.
        z=thickness+.8 if top else -.8
        model=modeled.get(item['reference'],{})
        value=model.get('component_temperature_c',model.get('junction_c')) if has_model else item.get('junction_c')
        solid=models.get(item['reference'])
        if solid:
            vertices=np.asarray(solid['vertices_mm']);faces=vertices[np.asarray(solid['triangles'],dtype=int)]
            z=float(solid['bounds_mm'][5] if top else solid['bounds_mm'][2])
            x,y=np.mean(vertices,axis=0)[:2]
            fill='#697985' if value is None else colormaps['inferno'](norm(value))
            artist=Poly3DCollection(faces,facecolors=fill,edgecolors='#00d3b1' if item['id']==selected_id else 'none',
                                    linewidths=.25,antialiased=False)
            artist.set_gid('quicktherm-step-'+item['id'])
            # Sort every physical face together. Separate collections sort by
            # average depth and can incorrectly hide a package behind the PCB.
            add_surface(artist,faces,[fill]*len(faces))
            extent_points.extend([solid['bounds_mm'][:3],solid['bounds_mm'][3:]])
        color=('#f7fafc' if value is not None else '#697985') if has_model or available else (
            '#697985' if value is None else colormaps['inferno'](norm(value)))
        current=item['id']==selected_id
        box=item.get('bbox_mm')
        if box and len(box)==4 and not solid:
            corners=[(box[0],box[1],z),(box[2],box[1],z),(box[2],box[3],z),(box[0],box[3],z)]
            bounds_artist,=ax.plot(*np.asarray(corners+[corners[0]]).T,
                                   color='#00ad94' if current else '#547079',
                                   linewidth=1.5 if current else .55,zorder=1e5)
            bounds_artist.set_gid('quicktherm-footprint-'+item['id'])
            extent_points.extend(corners)
        # Line3D markers retain their explicit overlay order, unlike scatter's
        # automatic depth ordering against a whole-board Poly3DCollection.
        # Both sides remain inspectable; these are data markers, not package solids.
        if not solid:
            ax.plot([x],[y],[z],color=color,marker='o',linestyle='none',
                    markersize=11 if current else (7.5 if item.get('in_scope') else 3.5),
                    markeredgecolor='#00d3b1' if current else '#344b56',zorder=1e5)
        text=_component_label({**item,'temperature_kind':model.get('temperature_kind')},value)
        targets.append({'id':item['id'],'reference':item['reference'],'side':'top' if top else 'bottom',
                        'junction_c':value,'position':(x,y,z),'bbox':box,'label':text})
        if current:
            label=ax.text(x,y,z+.12,text,fontsize=8,zorder=1e6,
                          bbox={'facecolor':'white','alpha':.9,'edgecolor':'none','pad':2})
            label.set_gid('quicktherm-component-selected')
        if not solid:ax.plot([x,x],[y,y],[thickness if top else 0.,z],color='#64817e',linewidth=.6,zorder=1e4)
        extent_points.append((x,y,z))
    if solid_faces:
        combined=Poly3DCollection(solid_faces,facecolors=solid_colors,edgecolor='none',antialiased=False,zsort='average')
        combined.set_gid('quicktherm-step-scene');ax.add_collection3d(combined)
    ax._thermal_step_parts=sorted(models)
    for probe in probes or []:
        x,y=probe['x_mm'],probe['y_mm'];z=thickness+.12 if probe.get('side')!='bottom' else -.12
        ax.scatter([x],[y],[z],color='#00d3b1',marker='+',s=90,depthshade=False)
        value=probe.get('temperature_c');label=probe['label']+(' unknown' if value is None else f' {value:.2f} °C')
        ax.text(x,y,z,label,fontsize=8);extent_points.append((x,y,z))
    extent_points.extend((p[0],p[1],z) for ring in rings for p in ring for z in (0.,thickness))
    extent_points.extend((p[0],p[1],plane['z_mm']) for ring in rings for p in ring for plane in planes)
    bbox=view.get('bbox_mm')
    if bbox:
        extent_points.extend([(bbox[0],bbox[1],0.),(bbox[2],bbox[3],thickness)])
    if extent_points:
        points=np.asarray(extent_points);low=points.min(axis=0);high=points.max(axis=0)
        spans=high-low;pad=max(spans[0],spans[1],1.)*.035
        ax.set_xlim(low[0]-pad,high[0]+pad);ax.set_ylim(high[1]+pad,low[1]-pad)
        ax.set_zlim(low[2]-.2,high[2]+.2)
        ax._thermal_fit_aspect=(max(spans[0]+2*pad,1.),max(spans[1]+2*pad,1.),max(spans[2]+.4,.4))
        ax.set_box_aspect(ax._thermal_fit_aspect,zoom=1.16 if viewport else .92)
    else:
        ax.set_box_aspect((1,1,.1))
    ax.view_init(elev=elev,azim=azim)
    ax._thermal_norm=norm
    ax._thermal_viewport=viewport
    ax._thermal_board_z={'top':thickness,'bottom':0.,'midplane':thickness/2}
    ax._thermal_thickness_known=bool(thickness)
    if 'CalculiX' in network.get('model',''):
        meaning='Imported CalculiX board-surface °C · sampled nodal field'
    elif network.get('layers'):
        meaning='Layer model °C · declared layer depths'
    elif network.get('board_field'):
        meaning='Approximate board midplane °C · one shared thin-sheet field'
    elif available:
        meaning='Partial junction interpolation °C · not board temperature'
    else:
        meaning='Estimated component junction °C'
    if temperatures:
        if viewport:
            cax=figure.add_axes([.915,.20,.02,.60])
            label=('Board + component °C' if any(row.get('storage_node') is not None for row in modeled.values()) else
                   'Board-surface estimate °C' if 'CalculiX' in network.get('model','') else
                   'Layer temperature °C' if network.get('layers') else
                   'Board midplane °C' if network.get('board_field') else 'Junction estimate °C')
            figure.colorbar(ScalarMappable(norm=norm,cmap='inferno'),cax=cax,label=label)
        else:
            figure.colorbar(ScalarMappable(norm=norm,cmap='inferno'),ax=ax,
                            label=meaning,pad=.07,fraction=.032,shrink=.72)
    note=(f'{len(models)} actual STEP parts · each RC part has one uniform temperature · gray is unknown' if models else
          'Saved footprint bounds · marker offsets illustrative · blank/gray regions unknown')
    if not thickness:note+=' · board thickness unknown'
    if has_model and not available:note+=' · thermal field unavailable'
    if viewport:
        ax.set_axis_off()
        ax.text2D(.02,.98,meaning,transform=ax.transAxes,va='top',fontsize=9)
        ax.text2D(.02,.02,note,transform=ax.transAxes,fontsize=8,wrap=True)
        figure.subplots_adjust(left=.005,right=.865,bottom=.005,top=.995)
        ax.set_anchor('C')
    else:
        ax.set_xlabel('X mm');ax.set_ylabel('Y mm');ax.set_zlabel('Board Z mm')
        ax.set_title('Saved board 3D overview')
        figure.text(.5,.015,note,ha='center',fontsize=8)
        figure.tight_layout(rect=(0,.045,1,1))
    fit_thermal_3d(ax)
    _install_component_hover(ax,targets,selected_id,three_d=True)
    return ax


def draw_thermal_view(figure, view, mode='Top-side map', selected_id=None,
                      network=None,azim=-60,elev=28,probes=None,
                      temperature_limits_c=None,viewport=False):
    figure.clear()
    if mode=='3D overview':return _draw_3d(figure,view,selected_id,network,azim,elev,probes,temperature_limits_c,viewport)
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
    targets=[]
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
        text=_component_label(item,value)
        targets.append({'id':item['id'],'reference':item['reference'],'side':side,'junction_c':value,
                        'position':position,'bbox':box,'label':text})
        if current:
            label=ax.annotate(text,position,xytext=(5,5),textcoords='offset points',
                        fontsize=8,fontweight='bold' if current else 'normal',zorder=5,
                        bbox={'facecolor':'white','alpha':.8,'edgecolor':'none','pad':1})
            label.set_gid('quicktherm-component-selected')
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
    ax.set_aspect('equal',adjustable='box')
    title='Saved PCB '+side+' view · '+((display_layer_name+' copper layer' if display_layer_name else 'approximate board midplane') if board_model else (
          'partial same-side junction interpolation · anchor hull' if contour else 'component estimates with partial junction overlay'))
    if viewport:
        ax.set_axis_off();ax.set_title(title,fontsize=9,pad=3)
        figure.subplots_adjust(left=.015,right=.89,bottom=.015,top=.965)
    else:
        ax.set_xlabel('X mm'+(' · mirrored bottom view' if bottom else ''));ax.set_ylabel('Y mm')
        ax.set_title(title)
    _install_component_hover(ax,targets,selected_id)
    if not viewport:figure.tight_layout()
    return ax


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
