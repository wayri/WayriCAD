"""Shared native plots and a self-contained Quick PI HTML/JSON report."""
from __future__ import annotations
import base64
from html import escape
import io
import json
import math
from pathlib import Path
from wayricad_runtime.report_ui import enhance_report, provenance, publish_report, report_paths

METRICS={
    'voltage':('Potential','V','viridis'),
    'drop':('Voltage drop','mV','magma'),
    'resistance':('DC drop / current ΔV/I','mΩ','magma'),
    'density':('Current density','A/mm²','inferno'),
    'flow':('Current flow','A/mm','viridis'),
    'loss':('Copper loss density','W/mm²','inferno'),
    'risk':('Adiabatic pulse energy / limit','ratio','YlOrRd'),
}
FIELD_STYLES={'smooth':'Smooth gradient','cells':'Solver cells'}


def terminal_ids(request):
    """All requested load pads, including legacy two-terminal studies."""
    values=[request.get('source_terminal',request.get('source')),
            request.get('sink_terminal',request.get('sink')),*request.get('source_terminals',[])]
    for row in request.get('sinks',[]):values.extend(row.get('terminals',[row.get('terminal')]))
    return {value for value in values if value is not None}


def metric_name(bundle,metric):
    if bundle.get('physical_return') and metric in ('voltage','drop'):return 'Ground rise above source ground'
    if metric=='resistance' and len(bundle.get('result',{}).get('sinks',bundle.get('request',{}).get('sinks',[])))>1:
        return 'DC drop / total demand ΔV/I'
    return METRICS[metric][0]


def feasibility_text(result):
    """Readable load/source limits without implying an attainable overloaded state."""
    feasibility=result.get('feasibility',{})
    if not feasibility:return ''
    limit=feasibility.get('source_current_limit_A')
    text=feasibility.get('status','Unknown')+' · Source current budget: '+('unlimited' if limit is None else _number(limit,'A'))
    if feasibility.get('source_current_headroom_A') is not None:
        text+=' · Headroom: '+_number(feasibility['source_current_headroom_A'],'A')
    if feasibility.get('source_current_limit_exceeded'):
        text+='\nRequested-load diagnostic only: the current-limited source cannot sustain these loads at the set voltage.'
    text+='\n'+str(feasibility.get('notice',''))
    if feasibility.get('violations'):text+='\n'+'\n'.join(str(item) for item in feasibility['violations'])
    return text.strip()


def sink_results_text(result):
    lines=[]
    for row in result.get('sinks',[]):
        limits=[]
        for key,label in [('min_voltage_V','min'),('max_voltage_V','max')]:
            if row.get(key) is not None:limits.append(label+' '+_number(row[key],'V'))
        lines.append(str(row.get('label') or row.get('id','Sink'))+': '+_number(row.get('current_A'),'A')+
                     ' · '+_number(row.get('voltage_V'),'V')+' · drop '+_number(row.get('voltage_drop_V'),'mV',1000)+
                     (' · '+', '.join(limits) if limits else ' · no voltage bounds')+
                     (' · LIMIT VIOLATION' if row.get('within_voltage_limits') is False else ''))
    return '\n'.join(lines)


def layer_rows(bundle):
    geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
    return geometry.get('layers',[])


def cell_values(mesh,result,metric):
    import numpy as np
    triangles=np.asarray(mesh['triangles'],dtype=int)
    if metric in ('voltage','drop','resistance'):
        values=np.asarray([float('nan') if value is None else value for value in result['potential_V']])
        values=values[triangles].mean(axis=1)
        if metric=='voltage':return values
        drop=(values-float(result['source_voltage_V']) if result.get('physical_return') else float(result['source_voltage_V'])-values)*1000
        demand=abs(float(result['sink_current_A'])) if result.get('physical_return') else float(result['sink_current_A'])
        return drop/demand if metric=='resistance' else drop
    if metric in ('density','flow'):
        key='cell_J_A_mm2' if metric=='density' else 'cell_sheet_current_A_mm'
        vectors=np.asarray([v if v is not None else [float('nan'),float('nan')] for v in result[key]])
        return np.linalg.norm(vectors,axis=1)
    if metric=='loss':
        points=np.asarray(mesh['points_mm'])[:,:2][triangles]
        area=abs((points[:,1,0]-points[:,0,0])*(points[:,2,1]-points[:,0,1])-(points[:,2,0]-points[:,0,0])*(points[:,1,1]-points[:,0,1]))/2
        power=np.asarray([float('nan') if value is None else value for value in result['cell_power_W']])
        return power/area
    if metric=='risk':
        return np.asarray([float('nan') if row.get('energy_ratio') is None else row['energy_ratio'] for row in result['cell_thermal']])
    raise ValueError('Unknown result metric: '+str(metric))


def _nodal_values(result,metric):
    import numpy as np
    values=np.asarray([np.nan if value is None else value for value in result['potential_V']],dtype=float)
    if metric!='voltage':
        values=(values-float(result['source_voltage_V']) if result.get('physical_return') else float(result['source_voltage_V'])-values)*1000
        if metric=='resistance':values=values/abs(float(result['sink_current_A']))
    return values


def gradient_surface(mesh,result,metric,indices):
    """Display vertices on existing triangles only; no inferred copper links.

    Potential-derived metrics use the linear FEM nodal field. Cell metrics
    use area-weighted corner colors, separately for each layer and thickness.
    This projection is for display only: cell probes and peaks stay unchanged.
    """
    import numpy as np
    triangles=np.asarray(mesh['triangles'],dtype=int)
    indices=np.asarray(indices,dtype=int)
    values=cell_values(mesh,result,metric)
    indices=indices[np.isfinite(values[indices])]
    selected=triangles[indices]
    points=np.asarray(mesh['points_mm'],dtype=float)[selected,:2]
    if metric in ('voltage','drop','resistance'):
        colors=_nodal_values(result,metric)[selected]
    else:
        colors=np.empty(selected.shape,dtype=float)
        areas=np.abs((points[:,1,0]-points[:,0,0])*(points[:,2,1]-points[:,0,1])-
                     (points[:,2,0]-points[:,0,0])*(points[:,1,1]-points[:,0,1]))/2
        layers=np.asarray([str(value) for value in mesh['triangle_layer']])[indices]
        thickness=np.asarray(mesh['triangle_thickness_mm'],dtype=float)[indices]
        # Distinct material regions get duplicate display vertices at their
        # interface. Coincident XY nodes never establish new connectivity.
        for layer in np.unique(layers):
            for depth in np.unique(thickness[layers==layer]):
                group=np.flatnonzero((layers==layer)&(thickness==depth))
                nodes,inverse=np.unique(selected[group],return_inverse=True)
                inverse=inverse.ravel()
                weights=np.repeat(areas[group],3)
                total=np.bincount(inverse,weights=weights,minlength=len(nodes))
                weighted=np.bincount(inverse,weights=np.repeat(values[indices[group]],3)*weights,minlength=len(nodes))
                colors[group]=(weighted/total)[inverse].reshape(-1,3)
    # Duplicate corners allow thickness/material discontinuities while retaining
    # the exact solved support, including holes and unavailable triangles.
    return points.reshape(-1,2),np.arange(len(indices)*3).reshape(-1,3),colors.reshape(-1)


def field_note(metric,style):
    if style=='cells':return 'Solver cell values'
    return 'Linear nodal field' if metric in ('voltage','drop','resistance') else 'Cell values interpolated for display; probes and peaks use solver cells'


def via_markers(mesh,result,geometry,layer,metric):
    """Worst solved barrel segment at each XY, restricted to its actual span."""
    if metric not in ('density','risk'):return []
    layers=geometry.get('layers',[])
    order={str(row['id']):float(row.get('z_mm',index)) for index,row in enumerate(layers)}
    records={row['id']:row for row in result.get('vias',[])}
    groups={}
    for barrel in mesh.get('vias',[]):
        a,b,selected=(order.get(str(value)) for value in (barrel.get('top_layer'),barrel.get('bottom_layer'),layer))
        if a is None or b is None or (layer!='all' and (selected is None or not min(a,b)<=selected<=max(a,b))):continue
        solved=records.get(barrel['id'])
        if solved is None or 'x_mm' not in barrel or 'y_mm' not in barrel:continue
        value=solved.get('current_density_A_mm2') if metric=='density' else solved.get('thermal',{}).get('energy_ratio')
        if value is None or not math.isfinite(float(value)):continue
        from .barrel import drill_dimensions
        dimensions=drill_dimensions(barrel)
        key=(float(barrel['x_mm']),float(barrel['y_mm']),dimensions,float(barrel.get('drill_angle_deg',0.)))
        radius=float(barrel['drill_mm'])/2;outer=radius+float(barrel['plating_mm'])
        marker=groups.setdefault(key,{'x_mm':key[0],'y_mm':key[1],'drill_radius_mm':radius,
            'drill_mm':float(barrel['drill_mm']),'drill_size_mm':list(dimensions),'drill_angle_deg':key[3],
            'plating_mm':float(barrel['plating_mm']),'outer_radius_mm':outer,'value':float(value),'segments':[]})
        marker['value']=max(marker['value'],float(value));marker['outer_radius_mm']=max(marker['outer_radius_mm'],outer)
        marker['plating_mm']=max(marker['plating_mm'],float(barrel['plating_mm']))
        marker['segments'].append(barrel['id'])
    return list(groups.values())


def result_scale(bundle, metric, layer=None):
    """Finite solved range; None means that no quantity is available."""
    import numpy as np
    mesh=bundle.get('mesh',{});result=bundle.get('result',{})
    if not mesh.get('triangles') or not result:return None
    values=cell_values(mesh,result,metric)
    if layer is not None:
        indices=np.flatnonzero([str(value)==str(layer) for value in mesh['triangle_layer']])
    else:indices=np.arange(len(values))
    if metric in ('voltage','drop','resistance'):
        selected=np.asarray(mesh['triangles'],dtype=int)[indices[np.isfinite(values[indices])]]
        values=_nodal_values(result,metric)[selected].ravel()
    else:values=values[indices]
    finite=values[np.isfinite(values)].tolist()
    geometry=bundle.get('geometry') or mesh.get('geometry',{})
    for row in geometry.get('layers',[]):
        if layer is None or str(row['id'])==str(layer):
            finite.extend(marker['value'] for marker in via_markers(mesh,result,geometry,row['id'],metric))
    if not finite:return None
    low,high=min(finite),max(finite)
    if metric=='risk':low,high=0.,max(1.,high)
    if low==high:
        margin=max(abs(low)*.01,1e-12);low-=margin;high+=margin
    return float(low),float(high)


def validate_scale(low, high):
    low,high=float(low),float(high)
    if not math.isfinite(low) or not math.isfinite(high) or low>=high:
        raise ValueError('Scale limits must be finite, with minimum below maximum.')
    return low,high


def inspection_record(bundle, kind, identifier, metric='density'):
    """Resolve an actual cell/barrel record without inventing a PCB object ID."""
    mesh=bundle.get('mesh',{});result=bundle.get('result',{})
    if not result:return None
    geometry=bundle.get('geometry') or mesh.get('geometry',{})
    names={str(row['id']):row.get('name',str(row['id'])) for row in geometry.get('layers',[])}
    if kind=='sheet':
        index=int(identifier)
        if not 0<=index<len(mesh.get('triangles',[])):return None
        value=float(cell_values(mesh,result,metric)[index])
        vector=result['cell_J_A_mm2'][index]
        power=result['cell_power_W'][index]
        return {'kind':kind,'id':index,'layer':mesh['triangle_layer'][index],
                'layer_name':names.get(str(mesh['triangle_layer'][index]),str(mesh['triangle_layer'][index])),
                'location_mm':result['cell_centroid_mm'][index], 'metric':metric,
                'value':value if math.isfinite(value) else None,'unit':METRICS[metric][1],
                'current_density_A_mm2':math.hypot(*vector) if vector is not None else None,
                'power_W':power,'thermal':result['cell_thermal'][index], 'source_ids':[]}
    if kind!='via':return None
    solved=next((row for row in result.get('vias',[]) if str(row['id'])==str(identifier)),None)
    barrel=next((row for row in mesh.get('vias',[]) if str(row['id'])==str(identifier)),None)
    if solved is None or barrel is None:return None
    # A generated barrel segment ID is not itself a KiCad UUID. Resolve it
    # against the extracted saved object identity rather than splitting text.
    sources=[str(row['id']) for row in geometry.get('vias',[])
             if str(identifier)==str(row['id']) or str(identifier).startswith(str(row['id'])+':')]
    quantity='risk' if metric=='risk' else 'density'
    value=solved.get('thermal',{}).get('energy_ratio') if quantity=='risk' else solved.get('current_density_A_mm2')
    span=[barrel.get('top_layer'),barrel.get('bottom_layer')]
    return {'kind':'via','id':identifier,'layer':span,
            'layer_name':' → '.join(names.get(str(value),str(value)) for value in span),
            'location_mm':[barrel['x_mm'],barrel['y_mm']], 'metric':quantity,'value':value,
            'unit':METRICS[quantity][1], 'source_ids':sources,
            **{key:solved.get(key) for key in ('current_density_A_mm2','current_A','resistance_ohm','power_W','thermal')}}


def probe_result(bundle, layer, x, y, metric='density'):
    """Inspect a barrel annulus or containing triangle, never nearby empty space."""
    import numpy as np
    mesh=bundle.get('mesh',{});result=bundle.get('result',{})
    if not result:return None
    geometry=bundle.get('geometry') or mesh.get('geometry',{})
    order={str(row['id']):float(row.get('z_mm',index)) for index,row in enumerate(geometry.get('layers',[]))}
    candidates=[]
    for barrel in mesh.get('vias',[]):
        span=[order.get(str(barrel.get(key))) for key in ('top_layer','bottom_layer')]
        selected=order.get(str(layer))
        if selected is None or None in span or not min(span)<=selected<=max(span):continue
        from .barrel import drill_wall_distance
        distance=drill_wall_distance((x,y),barrel)
        if distance < -1e-10:return None  # the entire capsule void has no copper field
        if distance<=barrel['plating_mm']+1e-10:
            record=inspection_record(bundle,'via',barrel['id'],metric)
            if record:candidates.append(record)
    if candidates:return max(candidates,key=lambda row:row.get('value') if row.get('value') is not None else -math.inf)
    points=np.asarray(mesh.get('points_mm',[]),dtype=float)
    triangles=np.asarray(mesh.get('triangles',[]),dtype=int)
    if not len(triangles):return None
    indices=np.flatnonzero([str(value)==str(layer) for value in mesh['triangle_layer']])
    vertices=points[triangles[indices],:2]
    if not len(vertices):return None
    a=vertices[:,0];b=vertices[:,1];c=vertices[:,2];p=np.asarray([x,y])
    cross=lambda u,v:u[:,0]*v[:,1]-u[:,1]*v[:,0]
    signs=np.stack([cross(b-a,p-a),cross(c-b,p-b),cross(a-c,p-c)],axis=1)
    hits=np.flatnonzero(np.all(signs>=-1e-10,axis=1)|np.all(signs<=1e-10,axis=1))
    if not len(hits):return None
    return inspection_record(bundle,'sheet',int(indices[hits[0]]),metric)


def _polygon_patch(polygon):
    from matplotlib.path import Path as MplPath
    from matplotlib.patches import PathPatch
    vertices=[];codes=[]
    for i,ring in enumerate([polygon['outer'],*polygon.get('holes',[])]):
        ring=[tuple(p[:2]) for p in ring]
        if not ring:continue
        area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:]+ring[:1]))
        if (area>0)!=(i==0):ring.reverse()
        vertices.extend(ring+[ring[0]])
        codes.extend([MplPath.MOVETO]+[MplPath.LINETO]*(len(ring)-1)+[MplPath.CLOSEPOLY])
    return PathPatch(MplPath(vertices,codes),facecolor='#cbdedc',edgecolor='#477f79',linewidth=.45)


def _board_axes(figure):
    """A full-frame, millimetre viewport which refits with the canvas aspect."""
    from matplotlib.axes import Axes

    class BoardAxes(Axes):
        def _fitted_limits(self):
            x0,y0,x1,y1=self._wayricad_bounds
            width,height=max(x1-x0,1e-6),max(y1-y0,1e-6)
            position=self.get_position(original=True)
            ratio=(self.figure.bbox.width*position.width)/(self.figure.bbox.height*position.height)
            # A small border is enough for copper edges; unused space follows
            # the viewport aspect, never an independent X/Y stretch.
            width*=1.06;height*=1.06
            width=max(width,height*ratio);height=max(height,width/ratio)
            cx,cy=(x0+x1)/2,(y0+y1)/2
            return ((cx-width/2,cx+width/2),(cy+height/2,cy-height/2))

        def _wayricad_fit(self):
            home=self._fitted_limits()
            self.set_xlim(*home[0]);self.set_ylim(*home[1])
            self._wayricad_home=home

        def apply_aspect(self,position=None):
            if hasattr(self,'_wayricad_bounds'):
                home=self._fitted_limits();old=getattr(self,'_wayricad_home',home)
                xlim,ylim=self.get_xlim(),self.get_ylim()
                zoom=max(abs((xlim[1]-xlim[0])/(old[0][1]-old[0][0])),
                         abs((ylim[1]-ylim[0])/(old[1][1]-old[1][0])))
                # During resize retain the user's centre and zoom relative to
                # Fit; changing the field or panning does not reset navigation.
                cx,cy=sum(xlim)/2,sum(ylim)/2
                width=(home[0][1]-home[0][0])*zoom
                height=(home[1][0]-home[1][1])*zoom
                self.set_xlim(cx-width/2,cx+width/2,emit=False)
                self.set_ylim(cy+height/2,cy-height/2,emit=False)
                self._wayricad_home=home
                if hasattr(self,'_wayricad_scale_bar'):
                    line,label=self._wayricad_scale_bar
                    target=width*.12;power=10**math.floor(math.log10(target))
                    length=max(value*power for value in (1.,2.,5.,10.) if value*power<=target)
                    right=.97;left=right-length/width
                    line.set_data([left,left,right,right],[.044,.035,.035,.044])
                    label.set_position(((left+right)/2,.052));label.set_text(f'{length:g} mm')
            super().apply_aspect(position)

    ax=figure.add_axes([.008,.008,.984,.984],axes_class=BoardAxes)
    figure.set_facecolor('#edf1f3');ax.set_facecolor('#edf1f3')
    ax.set_aspect('equal',adjustable='datalim');ax.set_axis_off()
    return ax


def _fit_board_view(ax):
    import numpy as np
    if not np.isfinite(ax.dataLim.extents).all():return
    ax._wayricad_bounds=tuple(ax.dataLim.extents)
    ax._wayricad_fit()
    line,=ax.plot([],[],transform=ax.transAxes,color='#53636a',linewidth=1.,clip_on=False)
    label=ax.text(0,0,'',transform=ax.transAxes,ha='center',va='bottom',fontsize=8,color='#53636a')
    ax._wayricad_scale_bar=(line,label)


def _draw_board_context(ax,scene,layer,layer_name='',visible_nets=None):
    """Saved non-copper contours stay readable over an opaque solved plane."""
    from matplotlib import patheffects
    names={str(key):name for key,name in scene.get('layers',{}).items()}
    name=names.get(str(layer),layer_name)
    side='B.' if name=='B.Cu' else 'F.' if name=='F.Cu' or layer is None else None
    graphics={side+suffix for suffix in ('SilkS','Silkscreen','Fab','CrtYd','Courtyard')} if side else set()
    for row in scene.get('primitives',[]):
        role=row.get('role');on_layer=layer=='all' or str(row.get('layer'))==str(layer)
        if role=='drill' and visible_nets is not None and row.get('net') and row.get('net') not in visible_nets:continue
        visible=(role=='outline' or role=='drill' and on_layer or
                 role=='reference' and (on_layer or layer is None and names.get(str(row.get('layer')))=='F.Cu') or
                 role in ('drawing','footprint') and names.get(str(row.get('layer'))) in graphics)
        if not visible:continue
        if row.get('kind')=='polygon' and len(row.get('points',[]))>=3:
            artist=_polygon_patch({'outer':row['points'],'holes':row.get('holes',[])})
            artist.set_facecolor('none');artist.set_edgecolor('#34434d')
            artist.set_linewidth(.9 if role=='outline' else .5)
            ax.add_patch(artist)
        elif row.get('kind')=='text':
            artist=ax.text(*row['center'],row['text'],fontsize=6.5,color='#23333e',clip_on=True)
        else:continue
        artist.set_zorder(8);artist.set_alpha(.9)
        artist.set_gid('board-context:'+role+':'+str(row.get('uuid','')))
        artist.set_path_effects([patheffects.withStroke(linewidth=1.8,foreground='#f3f6f7')])


def draw_view(figure,bundle,view='Results',layer=None,metric='drop',color_limits=None,inspection=None,
              show_context=True,show_copper=True,show_overlay=True,field_style=None,board_view=False,
              visible_nets=None):
    """Draw actual geometry; board_view uses a native viewport without chart chrome.

    Native color meaning is available in ``ax._wayricad_color_scale`` for an
    inspector legend. Scientific report plots remain the default.
    """
    import numpy as np
    from matplotlib.collections import PolyCollection,PatchCollection
    from matplotlib.patches import Circle
    geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
    field_style=field_style or bundle.get('view_settings',{}).get('field_style','smooth')
    if field_style not in FIELD_STYLES:raise ValueError('Unknown field style: '+str(field_style))
    rows=geometry.get('layers',[])
    if layer is None and rows:layer=rows[0]['id']
    combined=layer=='all'
    selected=({'id':'all','name':'All copper layers (projected)',
               'polygons':[polygon for row in rows for polygon in row.get('polygons',[])]}
              if combined and rows else next((row for row in rows if str(row['id'])==str(layer)),None))
    figure.clear()
    if board_view:ax=_board_axes(figure)
    else:
        figure.set_facecolor('white');ax=figure.add_subplot(111);ax.set_facecolor('#ffffff')
        ax.set_aspect('equal',adjustable='box');ax.set_xlabel('X (mm)');ax.set_ylabel('Y (mm)')
    ax._wayricad_color_scale=None;ax._wayricad_color_mappable=None
    ax.grid(False)
    # Keep exact patch paths/colors but avoid thousands of independent Axes
    # artists on dense boards. Separate z orders preserve drill/annulus layering.
    batch_patches=len(geometry.get('vias',[]))>=250
    pending={}
    def add_geometry_patch(patch):
        if batch_patches:pending.setdefault(patch.get_zorder(),[]).append(patch)
        else:ax.add_patch(patch)
    def flush_geometry_patches():
        for zorder,patches in pending.items():
            collection=PatchCollection(patches,match_original=True,zorder=zorder)
            collection.set_gid('pi-geometry-'+str(zorder))
            collection._wayricad_patch_gids=[patch.get_gid() for patch in patches]
            ax.add_collection(collection)
        pending.clear()
    scene=bundle.get('board_scene',{})
    if visible_nets is None:
        visible_nets=bundle.get('view_settings',{}).get('visible_nets')
    if visible_nets is None:
        visible_nets=geometry.get('nets') or [geometry.get('net') or bundle.get('request',{}).get('net')]
        visible_nets=[net for net in visible_nets if net] or None
    if bundle.get('view_settings',{}).get('isolate_nets') is False:visible_nets=None
    if show_context and scene:
        from wayricad_runtime.board_render import draw_matplotlib
        if not show_copper:
            scene=dict(scene,primitives=[row for row in scene.get('primitives',[]) if row.get('role') not in ('track','pad','via','zone')])
        draw_matplotlib(ax,scene,visible_layers=None if combined or layer is None else [layer],
                        visible_nets=visible_nets,highlight_ids=(inspection or {}).get('source_ids',[]),alpha=.35)
    if not selected:
        if not board_view:ax.set_aspect('auto')
        ax.text(.5,.5,'Choose a net and preview its copper.',ha='center',va='center',transform=ax.transAxes)
        if board_view:
            if show_context and scene:_draw_board_context(ax,scene,layer,visible_nets=visible_nets)
            ax.autoscale_view();ax.invert_yaxis();_fit_board_view(ax)
        else:figure.tight_layout()
        return ax
    if show_copper:
        for polygon in selected.get('polygons',[]):add_geometry_patch(_polygon_patch(polygon))
    flush_geometry_patches()  # Copper backgrounds must remain behind the field.
    if view=='Results' and not show_overlay:view='Net'
    mesh=bundle.get('mesh');result=bundle.get('result');image=None
    markers=via_markers(mesh or {},result or {},geometry,layer,metric) if view=='Results' else []
    via_values=[row['value'] for row in markers]
    title=f"{geometry.get('net',bundle.get('request',{}).get('net',''))} · {selected['name']}"
    if view in ('Mesh','Results') and mesh:
        points=np.asarray(mesh['points_mm'],dtype=float)
        triangles=np.asarray(mesh['triangles'],dtype=int)
        mask=np.asarray([combined or str(value)==str(layer) for value in mesh['triangle_layer']])
        selected_triangles=triangles[mask]
        if len(selected_triangles):
            polygons=points[selected_triangles,:2]
            if view=='Mesh':
                ax.add_collection(PolyCollection(polygons,facecolors='#edf5f3',edgecolors='#487e78',linewidths=.25,rasterized=True))
                title+=f' · {len(selected_triangles):,} triangles'
            elif result:
                values=cell_values(mesh,result,metric)[mask]
                finite=np.isfinite(values)
                if finite.any():
                    _,unit,cmap=METRICS[metric]
                    if field_style=='smooth':
                        from matplotlib.tri import Triangulation
                        from matplotlib.collections import TriMesh
                        xy,faces,colors=gradient_surface(mesh,result,metric,np.flatnonzero(mask))
                        image=TriMesh(Triangulation(xy[:,0],xy[:,1],faces),array=colors,cmap=cmap,edgecolors='none',rasterized=True)
                    else:image=PolyCollection(polygons[finite],array=values[finite],cmap=cmap,edgecolors='none',rasterized=True)
                    image.set_clim(*result_scale(bundle,metric,None if combined else layer))
                    if color_limits is not None:image.set_clim(*validate_scale(*color_limits))
                    ax.add_collection(image)
                    if not board_view:figure.colorbar(image,ax=ax,pad=.025,label=f'{metric_name(bundle,metric)} ({unit})')
                    if metric=='flow':
                        vectors=np.asarray([v if v is not None else [np.nan,np.nan] for v in result['cell_sheet_current_A_mm']])[mask]
                        centers=polygons.mean(axis=1);valid=np.flatnonzero(finite)
                        step=max(1,len(valid)//350);indices=valid[::step]
                        norms=np.linalg.norm(vectors[indices],axis=1);nonzero=norms>0;indices=indices[nonzero];norms=norms[nonzero]
                        ax.quiver(centers[indices,0],centers[indices,1],vectors[indices,0]/norms,vectors[indices,1]/norms,
                                  color='#163831',angles='xy',scale=30,width=.0025)
                elif not via_values:
                    message='Set a pulse duration to compute the adiabatic screen.' if metric=='risk' else 'No connected solution on this layer.'
                    ax.text(.02,.98,message,va='top',transform=ax.transAxes,bbox={'facecolor':'white','edgecolor':'none'})
                title+=' · '+metric_name(bundle,metric)+'\n'+field_note(metric,field_style)
            else:ax.text(.02,.98,'Run the analysis to see electrical results.',va='top',transform=ax.transAxes)
    if image is None and via_values:
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize
        image=ScalarMappable(norm=Normalize(0,max(1.,max(via_values))) if metric=='risk' else Normalize(min(via_values),max(via_values)),cmap=METRICS[metric][2])
        if color_limits is not None:image.set_clim(*validate_scale(*color_limits))
        if not board_view:figure.colorbar(image,ax=ax,pad=.025,label=f'{metric_name(bundle,metric)} ({METRICS[metric][1]})')
    elif view=='Results' and result and image is None:
        ax.text(.02,.98,'No available solved '+METRICS[metric][0].lower()+' on this layer.',va='top',transform=ax.transAxes,
                bbox={'facecolor':'white','edgecolor':'none','alpha':.9})
    for via in geometry.get('vias',[]) if show_copper else []:
        if not combined and not any(str(v)==str(layer) for v in via.get('layers',[])):continue
        if 'x_mm' not in via:continue
        center=(via['x_mm'],via['y_mm'])
        face='none'
        from .barrel import drill_dimensions,drill_contour
        dimensions=drill_dimensions(via)
        if dimensions[0]==dimensions[1]:
            add_geometry_patch(Circle(center,via.get('diameter_mm',.5)/2,facecolor=face,edgecolor='#355b67',linewidth=.6))
            add_geometry_patch(Circle(center,via.get('drill_mm',.3)/2,facecolor=ax.get_facecolor(),edgecolor='#355b67',linewidth=.3))
        else:
            # Actual extracted land outlines can be rectangular/custom. A
            # circle based on the minor dimension invents a different contact.
            for polygon in via.get('polygons',{}).get(str(layer),[]):
                patch=_polygon_patch(polygon);patch.set_facecolor('none');patch.set_edgecolor('#355b67')
                add_geometry_patch(patch)
            patch=_polygon_patch({'outer':drill_contour(via,circumscribed=True)})
            patch.set_facecolor(ax.get_facecolor());patch.set_edgecolor('#355b67');patch.set_linewidth(.3)
            add_geometry_patch(patch)
    for marker in markers:
        center=(marker['x_mm'],marker['y_mm']);color=image.cmap(image.norm(marker['value']))
        dimensions=marker['drill_size_mm']
        if dimensions[0]==dimensions[1]:
            patch=Circle(center,marker['outer_radius_mm'],facecolor=color,edgecolor=color,linewidth=1.5,zorder=5)
            hole=Circle(center,marker['drill_radius_mm'],facecolor=ax.get_facecolor(),edgecolor=color,linewidth=.6,zorder=6)
        else:
            from matplotlib.patches import Polygon
            from .barrel import drill_contour
            patch=Polygon(drill_contour(marker,marker['plating_mm']),facecolor=color,edgecolor=color,linewidth=1.5,zorder=5)
            hole=Polygon(drill_contour(marker,circumscribed=True),facecolor=ax.get_facecolor(),edgecolor=color,linewidth=.6,zorder=6)
        patch.set_gid('via-barrel:'+','.join(marker['segments']));add_geometry_patch(patch)
        hole.set_gid('via-drill:'+','.join(marker['segments']));add_geometry_patch(hole)
    flush_geometry_patches()
    request=bundle.get('request',{})
    if mesh and request.get('series'):
        points=np.asarray(mesh['points_mm'],dtype=float)
        for branch in mesh.get('lumped_branches',[]):
            endpoints=[]
            for key in ('top_nodes','bottom_nodes'):
                indices=branch.get(key,[])
                if not indices:break
                endpoints.append(points[indices,:2].mean(axis=0))
            if len(endpoints)==2:
                start,end=endpoints
                ax.plot([start[0],end[0]],[start[1],end[1]],'--',color='#70439e',linewidth=1)
                ax.annotate(str(branch.get('id','Component')), (start+end)/2,fontsize=8,color='#70439e',
                            bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':2})
    sources=set(request.get('source_terminals',[]))
    source=request.get('source_terminal',request.get('source'))
    if source is not None:sources.add(source)
    chosen=terminal_ids(request)
    for terminal in geometry.get('terminals',[]):
        if terminal.get('id') not in chosen and terminal.get('label') not in chosen:continue
        polygons=([polygon for values in terminal.get('polygons',{}).values() for polygon in values] if combined else terminal.get('polygons',{}).get(str(layer),terminal.get('polygons',{}).get(layer,[])))
        if not polygons:continue
        ring=np.asarray(polygons[0]['outer'])[:,:2];center=ring.mean(axis=0)
        is_source=terminal['id'] in sources or terminal.get('label') in sources
        ax.plot(*center,marker='o' if is_source else 's',markersize=4.5 if board_view else 6,color='#13854c' if is_source else '#b94535',markeredgecolor='white')
        label=('Source' if is_source else 'Sink') if board_view else ('Source: ' if is_source else 'Sink: ')+terminal.get('label',terminal['id'])
        offset=7 if not board_view or center[0]<sum(ax.dataLim.intervalx)/2 else -7
        ax.annotate(label,center,xytext=(offset,7),ha='left' if offset>0 else 'right',textcoords='offset points',fontsize=8,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':2})
    if board_view and show_context and scene:_draw_board_context(ax,scene,layer,selected['name'],visible_nets)
    if inspection and inspection.get('source_ids') and bundle.get('board_scene'):
        from wayricad_runtime.board_render import draw_matplotlib
        scene=bundle['board_scene'];wanted=set(inspection['source_ids'])
        selected_scene=dict(scene,primitives=[row for row in scene.get('primitives',[]) if row.get('uuid') in wanted and row.get('role') in ('track','pad','via') and (visible_nets is None or row.get('net') in visible_nets)])
        for artist in draw_matplotlib(ax,selected_scene,visible_layers=None if combined else [layer],highlight_ids=wanted,alpha=1.):
            artist.set_zorder(9)
            if hasattr(artist,'set_facecolor'):artist.set_facecolor('none');artist.set_linewidth(1.8)
    if inspection and inspection.get('location_mm'):
        span=inspection.get('layer');span=span if isinstance(span,list) else [span]
        if combined or any(str(value)==str(layer) for value in span):
            x,y=inspection['location_mm'][:2]
            ax.plot(x,y,marker='+',markersize=15,markeredgewidth=2,color='#06a7a0',zorder=10)
            ax.annotate(f"{inspection['kind']} {str(inspection['id'])[:16]}",(x,y),xytext=(8,-14),textcoords='offset points',fontsize=8,
                        bbox={'facecolor':'white','edgecolor':'#06a7a0','alpha':.9,'pad':2})
    if combined:title+='\nProjected layer fields overlap; values are not summed. Choose a layer for unambiguous inspection.'
    if view=='Results' and result and result.get('feasibility',{}).get('source_current_limit_exceeded'):
        title+='\nINFEASIBLE · requested-load diagnostic; source current limit exceeded'
    elif view=='Results' and result and result.get('feasibility',{}).get('feasible') is False:
        title+='\nINFEASIBLE · requested load/voltage limits violated'
    if bundle.get('view_settings',{}).get('isolate_nets',True):
        # Context is clipped to the studied copper rather than forcing a tiny
        # result into the full-board extent. This changes only the camera.
        support=[point for polygon in selected.get('polygons',[]) for point in polygon.get('outer',[])]
        wanted=set((inspection or {}).get('source_ids',[]))
        support.extend(point for row in bundle.get('board_scene',{}).get('primitives',[])
                       if row.get('uuid') in wanted and (combined or str(row.get('layer'))==str(layer))
                       and (visible_nets is None or row.get('net') in visible_nets)
                       for point in row.get('points',[]))
        if support:
            xy=np.asarray(support,dtype=float)[:,:2]
            ax.dataLim.set_points(np.array([xy.min(axis=0),xy.max(axis=0)]))
    ax.autoscale_view();ax.invert_yaxis()
    if image is not None:
        ax._wayricad_color_mappable=image
        ax._wayricad_color_scale={'metric':metric,'label':metric_name(bundle,metric),
                                 'unit':METRICS[metric][1],'cmap':image.cmap.name,
                                 'limits':image.get_clim(),'note':field_note(metric,field_style)}
    if board_view:
        _fit_board_view(ax)
    else:
        ax.set_title(title,loc='left',fontsize=10)
        ax._wayricad_home=(ax.get_xlim(),ax.get_ylim())
        ax.set_anchor('C')
        figure.subplots_adjust(left=.08,right=.90,bottom=.12,top=.94)
    return ax


def _number(value,unit='',scale=1.):
    return 'Unknown' if value is None else f'{float(value)*scale:.6g} {unit}'.strip()



def _review_html(document,bundle):
    result=bundle.get('result',{});diagnostic=bundle.get('return_path',{});sweep=bundle.get('sweep',{})
    if result:
        feasibility=result.get('feasibility',{})
        status='INFEASIBLE' if feasibility.get('feasible') is False or result.get('negative_sink_voltage') else 'COMPUTED · REVIEW REQUIRED'
        summary=[('Model','2.5D DC conduction; explicit lumped branches only'),('Net',bundle.get('request',{}).get('net',bundle.get('geometry',{}).get('net','Unknown'))),('Sink current',_number(result.get('total_sink_current_A',result.get('sink_current_A')),'A')),('Copper / component loss',_number(result.get('total_power_W'),'W')),('Mesh refinement','Evidence included' if bundle.get('convergence') else 'Not verified'),('Floating triangles',result.get('floating_triangles','Unknown'))]
        reference=bundle.get('return_voltage_reference') or bundle.get('request',{}).get('return_voltage_reference')
        if isinstance(reference,dict):
            summary.extend([('Potential gauge','Auxiliary raw solver potential; apply the declared offset'),('Source-ground zero terminal',reference.get('zero_terminal','Unknown')),('Add to raw potential',_number(reference.get('add_to_raw_potential_V'),'V')),('Load-ground rise',_number(reference.get('load_ground_voltage_V'),'V'))])
        notice='Numerical completion is separate from supply feasibility, mesh convergence and physical qualification. I²R losses do not establish a coupled thermal solution.'
        if bundle.get('return_conduction_notice'):notice+=' '+str(bundle['return_conduction_notice'])
    elif sweep:
        status='INFEASIBLE POINTS' if any(row.get('negative_sink_voltage') for row in sweep.get('rows',[])) else 'COMPUTED · REVIEW REQUIRED'
        summary=[('Model','Fixed-temperature DC current sweep'),('Computed operating points',len(sweep.get('rows',[])))]
        notice='Each point is an imposed DC load; these curves do not represent transient or electrothermal feedback.'
    else:
        status='INCOMPLETE' if diagnostic.get('unknown_count',0) else 'REVIEW REQUIRED'
        summary=[('Model','Return-path geometry review'),('Warnings',diagnostic.get('warning_count','Unknown')),('Unknowns',diagnostic.get('unknown_count','Unknown'))]
        notice='Missing return-path evidence remains unresolved. Geometric coverage does not prove high-frequency return current or impedance.'
    return enhance_report(document,status=status,summary=summary,notice=notice,provenance=provenance(bundle))

def _static_report_plan(bundle):
    """Bound raster rendering work without sampling numerical/interactive data."""
    options=bundle.get('report_options',{})
    if not isinstance(options,dict) or set(options)-{'extended_snapshots'}:
        raise ValueError('report_options supports only extended_snapshots (boolean).')
    extended=options.get('extended_snapshots',False)
    if not isinstance(extended,bool):raise ValueError('extended_snapshots must be boolean.')
    mesh=bundle.get('mesh',{})
    geometry=bundle.get('geometry') or mesh.get('geometry',{})
    large=len(mesh.get('triangles',[]))>100000 or len(geometry.get('vias',[]))>=250
    primary=('drop','density','loss')
    metrics=primary if large and not extended else primary+tuple(key for key in METRICS if key not in primary)
    style='cells' if large else bundle.get('view_settings',{}).get('field_style','smooth')
    return metrics,style,large


def _report_snapshot(bundle,layer,metric,style):
    """Dispose of native renderer and Figure reference cycles between maps."""
    import gc
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure=Figure(figsize=(8.8,5.2),dpi=110);FigureCanvasAgg(figure)
    stream=io.BytesIO()
    try:
        settings=bundle.get('view_settings',{});mode=settings.get('scale_mode',0)
        manual=settings.get('manual',{})
        limits=result_scale(bundle,metric) if mode==1 else tuple(manual['limits']) if mode==2 and manual.get('metric')==metric else None
        draw_view(figure,bundle,'Results',layer,metric,limits,field_style=style)
        figure.savefig(stream,format='png',dpi=110,facecolor='white')
        scale_note=(' · all-layer scale' if mode==1 else ' · manual scale' if limits is not None else '')
        diagnostic=' · requested-load diagnostic (source current limit exceeded)' if bundle['result'].get('feasibility',{}).get('source_current_limit_exceeded') else ''
        return '<figure><figcaption>'+escape(metric_name(bundle,metric)+scale_note+diagnostic)+'</figcaption><p>'+escape(field_note(metric,style))+'</p><img alt="'+escape(metric_name(bundle,metric))+'" src="data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')+'"></figure>'
    finally:
        stream.close();figure.clear()
        del figure
        gc.collect()


def _linked_evidence(bundle,reference):
    """Small batch-child descriptor; authoritative arrays remain in the parent."""
    if (not isinstance(reference,dict) or set(reference)-{'json','json_pointer','sign_transforms'} or
            not isinstance(reference.get('json'),str) or not reference['json'] or
            not isinstance(reference.get('json_pointer'),str) or not reference['json_pointer'].startswith('/')):
        raise ValueError('Evidence reference requires a JSON filename and exact JSON pointer.')
    result=bundle.get('result',{})
    geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
    request=bundle.get('request',{})
    return {'schema':'wayricad.pi-report-reference/v1',
        'evidence_reference':reference,'model':bundle.get('model'),
        'physical_return':bool(bundle.get('physical_return')),
        'summary':{key:value for key,value in result.items() if value is None or isinstance(value,(str,int,float,bool))},
        'source_custody':{'bundle':provenance(bundle),
            'request':{key:request[key] for key in ('board_path','source_path','source_sha256','study_input_path','study_file_sha256') if key in request},
            'geometry':{key:geometry[key] for key in ('source_path','source_sha256','geometry_sha256','net') if key in geometry}},
        'notice':'This descriptor is not a standalone numerical result. Resolve the JSON pointer in the linked complete parent batch JSON. '
                 'Physical return maps apply only the declared sign transforms to raw potentials/currents; geometry and positive losses are unchanged.'}


def write_report(path,bundle,layer=None,*,evidence_reference=None):
    """Export current-layer maps plus all numeric mesh/results as paired JSON."""
    path,json_path=report_paths(path)
    result=bundle.get('result')
    if not result:raise ValueError('Run the analysis before exporting results.')
    linked=_linked_evidence(bundle,evidence_reference) if evidence_reference is not None else None
    rows=layer_rows(bundle)
    if layer is None and rows:layer=rows[0]['id']
    selected='All copper layers (projected; overlapping fields are not summed)' if layer=='all' else next((row['name'] for row in rows if str(row['id'])==str(layer)),str(layer))
    ordered_metrics,style,large=_static_report_plan(bundle)
    images=[_report_snapshot(bundle,layer,metric,style) for metric in ordered_metrics]
    scope='Board + package' if result.get('package_contacts') else 'Circuit' if bundle.get('request',{}).get('series') else 'Copper'
    multisink=len(result.get('sinks',bundle.get('request',{}).get('sinks',[])))>1
    ratio_name=scope+(' apparent ΔV/I' if result.get('contains_forward_drop') else ' resistance ΔV/I')
    values=[('Worst drop / total demand ΔV/I' if multisink else ratio_name,_number(result.get('drop_over_current_ohm'),'mΩ',1000)),
            ('Worst sink voltage drop' if multisink else 'Voltage drop',_number(result.get('voltage_drop_V'),'mV',1000)),
            ('Total loss',_number(result.get('total_power_W'),'W')),
            ('Peak copper-sheet current density',_number(result.get('max_current_density_A_mm2'),'A/mm²')),
            ('Source voltage',_number(result.get('source_voltage_V'),'V')),
            ('Total requested sink current' if multisink else 'Sink current',_number(result.get('total_sink_current_A',result.get('sink_current_A')),'A')),
            ('Requested-load source V/I',_number(result.get('V_over_I_ohm'),'Ω')),
            ('Current balance error',_number(result.get('current_balance_error_A'),'A')),
            ('Energy relative error',_number(result.get('energy_relative_error'))),
            ('Floating triangles',str(result.get('floating_triangles',0)))]
    for key,label in [('planar_power_W','Copper sheet loss'),('via_power_W','Via barrel loss'),('conductor_power_W','Conductor loss'),('component_power_W','Component loss'),('package_power_W','Package contact loss')]:
        if key in result:values.append((label,_number(result[key],'W')))
    table=''.join('<tr><th>'+escape(name)+'</th><td>'+escape(value)+'</td></tr>' for name,value in values)
    assumptions=result.get('thermal_assumptions',{})
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WayriCAD Quick PI</title><style>body{font:15px system-ui,sans-serif;margin:32px auto;max-width:1080px;padding:0 20px;color:#172a2b;background:#fff}h1{font-size:26px}p{line-height:1.5}table{border-collapse:collapse}th,td{text-align:left;padding:7px 20px 7px 0;border-bottom:1px solid #e0e6e5}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:18px}figure{margin:0;border:1px solid #e0e6e5;border-radius:5px;padding:12px}figcaption{font-weight:600}img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f6;padding:14px}</style><h1>WayriCAD Quick PI</h1>'''
    html+='<p>2.5D DC copper conduction · plotted layer '+escape(selected)+'. '
    if linked:
        html+='Complete mesh and numerical arrays are in <a href="'+escape(evidence_reference['json'],quote=True)+'">the parent batch JSON</a>, JSON pointer <code>'+escape(evidence_reference['json_pointer'])+'</code>. <a href="'+escape(json_path.name)+'">Paired evidence descriptor and sign convention</a>; this child JSON is not a standalone numerical result.</p>'
    else:
        html+='All layer mesh and numerical data are in <a href="'+escape(json_path.name)+'">the paired JSON report</a>.</p>'
    if large:
        html+='<p>Large-board static rendering uses every solved cell on this layer (Solver cells style), with all copper and drill contours retained. No cells are sampled. Three primary static maps are generated by default; set report_options.extended_snapshots=true in the result bundle to render all seven. Complete numerical JSON and the three interactive fields are retained.</p>'
    auxiliary=bundle.get('auxiliary_reversed_current_result_reference')
    if auxiliary:
        html+='<p>Original reversed-current solver evidence: <a href="'+escape(auxiliary['json'],quote=True)+'">complete parent batch JSON</a>, JSON pointer <code>'+escape(auxiliary['json_pointer'])+'</code>.</p>'
    if result.get('feasibility'):
        html+='<h2>Source and load feasibility</h2><pre>'+escape(feasibility_text(result))+'</pre>'
    from .sankey import sankey_section
    html+=sankey_section(bundle)
    from .mesh_sizing import sizing_html
    html+=sizing_html(bundle.get('mesh',{}))
    if bundle.get('terminal_units'):
        html+='<h2>Ideal equipotential pad units</h2><pre>'+escape(json.dumps(bundle['terminal_units'],indent=2,ensure_ascii=False))+'</pre>'
    if result.get('sinks'):
        html+='<h2>Constant-current sinks</h2><table><tr><th>Sink</th><th>Demand A</th><th>Voltage V</th><th>Drop mV</th><th>Min V</th><th>Max V</th><th>Voltage limits</th></tr>'
        for sink in result['sinks']:
            cells=[str(sink.get('label') or sink.get('id','Sink')),_number(sink.get('current_A')),_number(sink.get('voltage_V')),
                   _number(sink.get('voltage_drop_V'),scale=1000),_number(sink.get('min_voltage_V')) if sink.get('min_voltage_V') is not None else 'Unbounded',
                   _number(sink.get('max_voltage_V')) if sink.get('max_voltage_V') is not None else 'Unbounded',
                   'Violation' if sink.get('within_voltage_limits') is False else 'Within limits']
            html+='<tr>'+''.join('<td>'+escape(cell)+'</td>' for cell in cells)+'</tr>'
        html+='</table>'
    if bundle.get('convergence'):
        from .convergence import html_section
        html+=html_section(bundle['convergence'])
    else:
        html+='<p><strong>Mesh convergence not verified.</strong> Run a fixed-input refinement study before relying on terminal drop. Localized current-density and pulse-risk peaks need separate verification.</p>'
    if multisink:
        html+='<p>The DC drop / total demand map divides each source-to-cell drop by total requested sink current. Worst drop / total demand is a diagnostic normalization, not a physical two-terminal resistance or AC impedance.</p>'
        resistance_note='Worst drop / total demand uses the largest sink drop divided by total requested current.'
    else:
        html+='<p>The DC transfer-resistance map divides the source-to-cell potential drop by the specified sink current. It is not an AC impedance map.</p>'
        resistance_note=scope+' resistance uses the solved voltage drop divided by load current.'
    if result.get('contains_forward_drop'):
        resistance_note=scope+' ΔV/I is an apparent operating-point ratio at the specified load current, not resistance.'
    html+= '<h2>Interactive field probes</h2>'+interactive_fields(bundle,layer)
    html+='<table>'+table+'</table><p>'+resistance_note+' Source V/I is the operating point, not copper resistance. Gray copper has no connected result. Dashed component links represent explicit lumped branches, not physical copper.</p><h2>Three primary result plots</h2><section>'+''.join(images[:3])+'</section>'
    if images[3:]:
        html+='<details><summary>Additional potential, resistance, flow and pulse-risk plots</summary><section>'+''.join(images[3:])+'</section></details>'
    if result.get('negative_sink_voltage'):
        html+='<p><strong>Operating-point warning:</strong> The requested current makes sink voltage negative; check source voltage and load. The imposed-current path may be infeasible.</p>'
    if result.get('analytics'):
        from .analytics import details_text
        html+='<h2>Copper thickness, layer losses and hotspots</h2><pre>'+escape(details_text(result))+'</pre>'
    if result.get('package_contacts'):
        from .package_contacts import details_text as package_text
        html+='<h2>Explicit package contacts</h2><pre>'+escape(package_text(result))+'</pre>'
        html+='<p>One axial path per declared pad face; positive current flows from package to board. Parallel sharing is solved, with source and sink voltage limits at package endpoints. Sheet, barrel and package losses are separately conserved. No 3D package field or solder-interface resistance is inferred.</p>'
    if result.get('components'):
        html+='<h2>Explicit component branches</h2><p>Fixed and diode forward drops are evaluated at the specified DC load current. Before/after voltages follow the selected path. Inductance is reported as an input; this is not an AC or transient solve.</p>'
        html+='<table><tr><th>Component</th><th>Model</th><th>Current</th><th>Before</th><th>Drop</th><th>After</th><th>Power</th></tr>'
        for component in result['components']:
            values=[str(component.get('id','')),
                    str(component.get('model','RL')),
                    _number(component.get('current_A'),'A'),
                    _number(component.get('voltage_before_V'),'V'),
                    _number(component.get('voltage_drop_V'),'V'),
                    _number(component.get('voltage_after_V'),'V'),
                    _number(component.get('power_W'),'W')]
            html+='<tr>'+''.join('<td>'+escape(value)+'</td>' for value in values)+'</tr>'
        html+='</table><pre>'+escape(json.dumps(result['components'],indent=2))+'</pre>'
    if result.get('vias'):
        html+='<h2>Via barrels</h2><p>Positive current follows the recorded top-to-bottom barrel direction. The current-density and pulse-risk maps also color via annuli.</p><table><tr><th>Barrel</th><th>Current A</th><th>R mΩ</th><th>J A/mm²</th><th>Loss W</th><th>Pulse energy / limit</th></tr>'
        for via in result['vias']:
            values=[via['id'],_number(via.get('current_A')),_number(via.get('resistance_ohm'),scale=1000),
                    _number(via.get('current_density_A_mm2')),_number(via.get('power_W')),_number(via.get('thermal',{}).get('energy_ratio'))]
            html+='<tr>'+''.join('<td>'+escape(value)+'</td>' for value in values)+'</tr>'
        html+='</table>'
    html+='<h2>Assumptions and inputs</h2><p>'+escape(assumptions.get('notice','DC conduction approximation; not an AC or thermal field solve.'))+'</p><pre>'+escape(json.dumps({'request':bundle.get('request',{}),'material':result.get('material',{}),'thermal':assumptions,'geometry_warnings':bundle.get('geometry',{}).get('warnings',[]),'mesh_report':bundle.get('mesh',{}).get('mesh_report',[])},indent=2))+'</pre></html>'
    document=_review_html(html,bundle)
    if linked:
        from wayricad_runtime.report_ui import checked_sources,publish_documents
        sources=checked_sources(bundle)  # Validate full original custody, not the descriptor.
        publish_documents({json_path:json.dumps(linked,indent=2,ensure_ascii=False,allow_nan=False)+'\n',
                           path:document},sources=sources)
        return {'html':str(path),'json':str(json_path)}
    return publish_report(path,document,bundle)


def write_sweep_report(path,bundle):
    """Export a standalone voltage/current chart and exact JSON sweep rows."""
    sweep=bundle.get('sweep')
    if not sweep or not sweep.get('rows'):
        raise ValueError('Run a current sweep before exporting its report.')
    path,json_path=report_paths(path)
    rows=sweep['rows'];width=820;height=300;pad=42
    xmax=max(row['current_A'] for row in rows);xmin=min(row['current_A'] for row in rows)
    values=[row['path_drop_V'] for row in rows]+[row['sink_voltage_V'] for row in rows]
    ymin=min(values);ymax=max(values)
    if ymax==ymin:ymax=ymin+1
    x=lambda value:pad+(value-xmin)/(xmax-xmin if xmax!=xmin else 1.)*(width-2*pad)
    y=lambda value:height-pad-(value-ymin)/(ymax-ymin)*(height-2*pad)
    lines=[]
    for key,color in (('path_drop_V','#b45134'),('sink_voltage_V','#17657c')):
        points=' '.join(f"{x(row['current_A']):.2f},{y(row[key]):.2f}" for row in rows)
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}"/>')
    table=''.join('<tr><td>'+_number(row['current_A'],'A')+'</td><td>'+_number(row['path_drop_V'],'V')+
                  '</td><td>'+_number(row['sink_voltage_V'],'V')+'</td><td>'+('Review supply' if row['negative_sink_voltage'] else 'Positive')+'</td></tr>' for row in rows)
    html=('<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD Quick PI current sweep</title>'
          '<style>body{font:15px system-ui,sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#183038}'
          'table{border-collapse:collapse}th,td{padding:7px 18px 7px 0;border-bottom:1px solid #ddd;text-align:left}</style>'
          '<h1>Quick PI · DC current sweep</h1><p>Fixed-temperature path geometry; diode Vf varies with DC current. '
          'No transient or electrothermal feedback is calculated. '
          '<a href="'+escape(json_path.name)+'">Complete JSON evidence</a>.</p>'
          f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Path drop and sink voltage versus current" style="width:100%;height:auto;background:#f6f9f8">'
          f'<path d="M {pad} {pad} V {height-pad} H {width-pad}" fill="none" stroke="#556"/>'
          +''.join(lines)+'</svg><p><span style="color:#b45134">■</span> Path drop · '
          '<span style="color:#17657c">■</span> Sink voltage</p>'
          '<table><tr><th>Current</th><th>Path drop</th><th>Sink voltage</th><th>Status</th></tr>'+table+'</table></html>')
    from wayricad_runtime.interactive_plots import interactive_plot
    samples=[[row['current_A'],row[key],row[key],key] for key in ('path_drop_V','sink_voltage_V') for row in rows]
    html=html.replace('</html>',interactive_plot('DC current sweep',samples,'V',x_unit='A',y_unit='V',connect=True)+'</html>')
    return publish_report(path,_review_html(html,bundle),bundle)


def write_diagnostic_report(path, bundle):
    """Export return-path findings without remote assets."""
    result = bundle.get('return_path')
    if not result:
        raise ValueError('No return-path result is available.')
    path,json_path=report_paths(path)
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD Return-path review</title>'
            '<style>body{font:15px system-ui,sans-serif;max-width:1050px;margin:32px auto;padding:0 20px;color:#173039}'
            'table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style>'
            '<h1>WayriCAD Return-path review</h1><p>Read-only saved-board analysis. '
            '<a href="' + escape(json_path.name) + '">Complete JSON evidence</a>.</p>')
    from wayricad_runtime.return_path import html_details
    html+=html_details(result)
    html += '<p>' + escape(result['basis']) + '</p>'
    html += '<p>' + str(result['warning_count']) + ' warnings · ' + str(result['unknown_count']) + ' unknowns</p>'
    html += '<table><tr><th>Level</th><th>Code</th><th>Layer</th><th>Position mm</th><th>Detail</th></tr>'
    for row in result['findings']:
        position = ', '.join(f'{value:.4g}' for value in row['position_mm']) if row['position_mm'] else '—'
        html += '<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in (
            row['level'], row['code'], row['layer'], position, row['detail'])) + '</tr>'
    return publish_report(path,_review_html(html+'</table></html>',bundle),bundle)


def interactive_fields(bundle,layer):
    """Offline cell probes using saved triangles; holes and unknowns stay gaps."""
    import numpy as np
    from wayricad_runtime.interactive_plots import interactive_plot
    mesh=bundle['mesh'];result=bundle['result']
    points=np.asarray(mesh['points_mm'])
    indices=[i for i,v in enumerate(mesh['triangle_layer']) if layer=='all' or str(v)==str(layer)]
    triangles=np.asarray(mesh['triangles'],dtype=int)[indices]
    polygons=points[triangles,:2].tolist()
    centers=points[triangles,:2].mean(axis=1)
    html=''
    for metric in ('drop','density','loss'):
        values=cell_values(mesh,result,metric)
        rows=[[float(x),float(y),float(values[i]),'Layer '+str(mesh['triangle_layer'][i])+' · Cell '+str(i)] for (x,y),i in zip(centers,indices)]
        html+=interactive_plot(metric_name(bundle,metric),rows,METRICS[metric][1],polygons=polygons)
    return html


def write_batch_report(path,bundle):
    """Publish an offline independent-case index plus linked per-case evidence."""
    from tempfile import TemporaryDirectory
    from urllib.parse import quote
    from wayricad_runtime.report_ui import checked_sources, publish_documents
    batch=bundle.get('batch')
    if not isinstance(batch,dict) or not batch.get('cases'):raise ValueError('No batch cases are available to export.')
    output,evidence=report_paths(path)
    output.parent.mkdir(parents=True,exist_ok=True)
    case_folder=output.stem+'-cases'
    documents={};comparison=[];details=[];links=[];shared_sections=[]
    with TemporaryDirectory(prefix='.wayricad-report-',dir=output.parent) as staging:
        for index,case in enumerate(batch['cases']):
            case_links=[];failures=[]
            for kind,key in (('DC','electrical'),('Return conduction','return_conduction'),('Return path','return_path'),('Electrothermal','electrothermal')):
                child=case.get(key)
                if not child:continue
                if 'report_options' in bundle:child={**child,'report_options':bundle['report_options']}
                filename='case-'+str(index+1).zfill(3)+'-'+key+'.html'
                candidate=Path(staging)/filename
                reference={'json':'../'+evidence.name,'json_pointer':'/batch/cases/'+str(index)+'/'+key} if key in ('electrical','return_conduction') else None
                try:
                    if key in ('electrical','return_conduction'):write_report(candidate,child,evidence_reference=reference)
                    elif key=='return_path':write_diagnostic_report(candidate,child)
                    else:
                        from .electrothermal_report import write_report as coupled_report
                        coupled_report(candidate,child)
                    for generated in (candidate,candidate.with_suffix('.json')):
                        documents[output.parent/case_folder/generated.name]=generated.read_bytes()
                except (ValueError,RuntimeError,OSError,KeyError,TypeError,IndexError) as error:
                    failures.append(kind+': '+str(error))
                    fallback=enhance_report('<!doctype html><html lang="en"><meta charset="utf-8"><title>Case report unavailable</title><h1>Case report unavailable</h1><p>'+escape(str(error))+'</p><p><a href="'+escape(candidate.with_suffix('.json').name)+'">'+('Evidence descriptor linking exact parent case JSON' if reference else 'Exact case JSON evidence')+'</a></p></html>',status='REPORT ERROR',notice='The numerical case status has not been upgraded. Correct the report/model inputs and rerun the export.')
                    documents[output.parent/case_folder/candidate.name]=fallback
                    documents[output.parent/case_folder/candidate.with_suffix('.json').name]=json.dumps(_linked_evidence(child,reference) if reference else child,indent=2,ensure_ascii=False,allow_nan=False)
                relative=case_folder+'/'+filename
                case_links.append('<a href="'+escape(quote(relative,safe='/'))+'">'+escape(kind)+'</a>')
                links.append(relative)
            result=(case.get('electrical') or {}).get('result',{});loop=case.get('loop') or {}
            shared=case.get('shared_return',{});shared_loads=shared.get('loads',[])
            if shared_loads:
                loop={'supply_drop_V':max(v['supply_drop_V'] for v in shared_loads),
                    'return_drop_V':max(v['ground_rise_V'] for v in shared_loads),
                    'total_drop_V':max(v['supply_drop_V']+v['ground_rise_V'] for v in shared_loads),
                    'delivered_load_voltage_V':min(v['delivered_load_voltage_V'] for v in shared_loads),
                    'total_loss_W':result.get('total_power_W'),'status':'Shared: '+shared['group']}

            values=[case.get('name','Case '+str(index+1)),case.get('status','UNKNOWN'),_number(loop.get('supply_drop_V',result.get('voltage_drop_V')),'mV',1000),_number(loop.get('return_drop_V'),'mV',1000) if loop else 'Not requested',_number(loop.get('total_drop_V'),'mV',1000) if loop else 'Not requested',_number(loop.get('delivered_load_voltage_V'),'V') if loop else 'Not solved',_number(loop.get('total_loss_W',result.get('total_power_W')),'W'),loop.get('status','Not requested'),case.get('error') or ' — '.join(failures) or 'Review individual evidence']
            comparison.append('<tr>'+''.join('<td>'+escape(str(value))+'</td>' for value in values[:8])+'<td>'+(' · '.join(case_links) or 'No completed result report')+'</td><td>'+escape(str(values[8]))+'</td></tr>')
            inputs=next((v for v in bundle.get('request',{}).get('study',{}).get('cases',[]) if v.get('name')==case.get('name')),None)
            compact={key:case[key] for key in ('name','status','source_sha256','error','error_type','loop','shared_return') if key in case}
            compact['inputs']=inputs or (case.get('electrical') or {}).get('request',{})
            compact['evidence_notice']='Complete mesh and numerical arrays are available in the linked JSON evidence.'
            details.append('<details class="report-evidence"><summary>'+escape(str(values[0]))+' · exact inputs and case status</summary><pre>'+escape(json.dumps(compact,indent=2,ensure_ascii=False,allow_nan=False))+'</pre></details>')
        for index,group in enumerate(batch.get('shared_returns',[])):
            heading='<h3>'+escape(group['name'])+' · '+escape(group['status'])+'</h3>'
            child=group.get('return_conduction')
            if child:
                filename='shared-return-'+str(index+1).zfill(3)+'.html';candidate=Path(staging)/filename
                from .shared_return import physical_report_bundle
                physical=physical_report_bundle(group)
                physical.pop('auxiliary_reversed_current_result',None)
                physical['auxiliary_reversed_current_result_reference']={
                    'json':'../'+evidence.name,
                    'json_pointer':'/batch/shared_returns/'+str(index)+'/return_conduction/result'}
                physical['return_conduction_notice']=physical.get('return_conduction_notice','').replace(
                    'retained in auxiliary_reversed_current_result',
                    'retained in the parent batch JSON at auxiliary_reversed_current_result_reference')
                if 'report_options' in bundle:physical['report_options']=bundle['report_options']
                transforms={key:-1 for key in (
                    '/result/potential_V','/result/cell_J_A_mm2','/result/cell_sheet_current_A_mm',
                    '/result/source_voltage_V','/result/sink_voltage_V','/result/source_current_A',
                    '/result/sink_current_A','/result/total_sink_current_A',
                    '/result/vias/*/current_A','/result/sinks/*/voltage_V','/result/sinks/*/current_A')}
                write_report(candidate,physical,evidence_reference={
                    'json':'../'+evidence.name,
                    'json_pointer':'/batch/shared_returns/'+str(index)+'/return_conduction',
                    'sign_transforms':transforms})
                del physical
                for generated in (candidate,candidate.with_suffix('.json')):
                    documents[output.parent/case_folder/generated.name]=generated.read_bytes()
                relative=case_folder+'/'+filename;links.append(relative)
                heading+='<p><a href="'+escape(quote(relative,safe='/'))+'">Common copper mesh, physical ground rise and return-current evidence</a></p>'
            headings=('Rail','Load ID','Current (A)','Ground rise (V)','Delivered voltage (V)','Load voltage limits')
            body=[]
            for load in group.get('loads',[]):
                values=(load['case'],load['sink'],load['current_A'],load['ground_rise_V'],load['delivered_load_voltage_V'],
                        'PASS' if load['voltage_limits_met'] else 'INFEASIBLE')
                body.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in values)+'</tr>')
            heading+='<table><thead><tr>'+''.join('<th>'+v+'</th>' for v in headings)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table>'
            heading+='<p>Shared return loss (counted once): '+_number(group.get('return_loss_W'),'W')+'. Total supply and return loss: '+_number(group.get('total_loss_W'),'W')+'. Power balance error: '+_number(group.get('power_balance_error_W'),'W')+'.</p>'
            heading+='<p>'+escape(group.get('notice',group.get('error','')))+'</p>'
            shared_sections.append(heading)
    document=('<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD Quick PI DC study</title><h1>WayriCAD Quick PI · DC study comparison</h1><p><a href="'+escape(evidence.name)+'">Complete batch JSON evidence</a></p><h2>Case comparison</h2><table><thead><tr><th>Case</th><th>Status</th><th>Supply drop</th><th>Return drop</th><th>Loop drop</th><th>Minimum delivered voltage</th><th>Case loss (shared return separate)</th><th>Loop status</th><th>Individual reports</th><th>Error / next action</th></tr></thead><tbody>'+''.join(comparison)+'</tbody></table><h2>Shared-return coupling</h2>'+''.join(shared_sections)+'<h2>Case inputs and provenance</h2>'+''.join(details)+'<h2>Assumptions and boundaries</h2><ul>'+''.join('<li>'+escape(str(note))+'</li>' for note in batch.get('notes',batch.get('assumptions',[])))+'</ul></html>')
    from .sankey import sankey_section
    document=document.replace('<h2>Case comparison</h2>',sankey_section(bundle)+'<h2>Case comparison</h2>')
    document=enhance_report(document,status=batch.get('status','UNKNOWN'),summary=[('Cases',len(batch['cases'])),('Failed cases',sum(case.get('status')=='FAILED' for case in batch['cases'])),('Incomplete / review cases',sum(case.get('status') not in ('COMPLETED','FAILED') for case in batch['cases']))],notice='Explicit shared-return groups include common copper impedance at prescribed DC currents and fixed temperature. Other cases remain independent. Inter-net electromagnetic fields and cross-case thermal feedback are not solved.',provenance=provenance(bundle))
    # Escaping the sparse non-ASCII labels keeps large array archives in a
    # one-byte Python string. Avoid copying the entire archive to add a newline.
    documents[evidence]=json.dumps(bundle,separators=(',',':'),ensure_ascii=True,allow_nan=False)
    documents[output]=document
    publish_documents(documents,sources=checked_sources(bundle))
    return {'html':str(output),'json':str(evidence),'case_reports':links}
