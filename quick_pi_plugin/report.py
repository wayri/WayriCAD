"""Shared native plots and a self-contained Quick PI HTML/JSON report."""
from __future__ import annotations
import base64
from html import escape
import io
import json
import math
from pathlib import Path

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
    return {value for value in [request.get('source_terminal',request.get('source')),
                               request.get('sink_terminal',request.get('sink')),
                               *(row.get('terminal') for row in request.get('sinks',[]))] if value is not None}


def metric_name(bundle,metric):
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
        drop=(float(result['source_voltage_V'])-values)*1000
        return drop/float(result['sink_current_A']) if metric=='resistance' else drop
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
        values=(float(result['source_voltage_V'])-values)*1000
        if metric=='resistance':values=values/float(result['sink_current_A'])
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
        if None in (a,b,selected) or not min(a,b)<=selected<=max(a,b):continue
        solved=records.get(barrel['id'])
        if solved is None or 'x_mm' not in barrel or 'y_mm' not in barrel:continue
        value=solved.get('current_density_A_mm2') if metric=='density' else solved.get('thermal',{}).get('energy_ratio')
        if value is None or not math.isfinite(float(value)):continue
        key=(float(barrel['x_mm']),float(barrel['y_mm']))
        radius=float(barrel['drill_mm'])/2;outer=radius+float(barrel['plating_mm'])
        marker=groups.setdefault(key,{'x_mm':key[0],'y_mm':key[1],'drill_radius_mm':radius,
                                     'outer_radius_mm':outer,'value':float(value),'segments':[]})
        marker['value']=max(marker['value'],float(value));marker['outer_radius_mm']=max(marker['outer_radius_mm'],outer)
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
        radius=math.hypot(x-barrel['x_mm'],y-barrel['y_mm'])
        inner=barrel['drill_mm']/2;outer=inner+barrel['plating_mm']
        if radius<inner-1e-10:return None  # a white drill hole has no copper field
        if radius<=outer+1e-10:
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


def _draw_board_context(ax,scene,layer,layer_name=''):
    """Saved non-copper contours stay readable over an opaque solved plane."""
    from matplotlib import patheffects
    names={str(key):name for key,name in scene.get('layers',{}).items()}
    name=names.get(str(layer),layer_name)
    side='B.' if name=='B.Cu' else 'F.' if name=='F.Cu' or layer is None else None
    graphics={side+suffix for suffix in ('SilkS','Silkscreen','Fab','CrtYd','Courtyard')} if side else set()
    for row in scene.get('primitives',[]):
        role=row.get('role');on_layer=str(row.get('layer'))==str(layer)
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
              show_context=True,show_copper=True,show_overlay=True,field_style=None,board_view=False):
    """Draw actual geometry; board_view uses a native viewport without chart chrome.

    Native color meaning is available in ``ax._wayricad_color_scale`` for an
    inspector legend. Scientific report plots remain the default.
    """
    import numpy as np
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Circle
    geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
    field_style=field_style or bundle.get('view_settings',{}).get('field_style','smooth')
    if field_style not in FIELD_STYLES:raise ValueError('Unknown field style: '+str(field_style))
    rows=geometry.get('layers',[])
    if layer is None and rows:layer=rows[0]['id']
    selected=next((row for row in rows if str(row['id'])==str(layer)),None)
    figure.clear()
    if board_view:ax=_board_axes(figure)
    else:
        figure.set_facecolor('white');ax=figure.add_subplot(111);ax.set_facecolor('#ffffff')
        ax.set_aspect('equal',adjustable='box');ax.set_xlabel('X (mm)');ax.set_ylabel('Y (mm)')
    ax._wayricad_color_scale=None;ax._wayricad_color_mappable=None
    ax.grid(False)
    scene=bundle.get('board_scene',{})
    if show_context and scene:
        from wayricad_runtime.board_render import draw_matplotlib
        if not show_copper:
            scene=dict(scene,primitives=[row for row in scene.get('primitives',[]) if row.get('role') not in ('track','pad','via','zone')])
        draw_matplotlib(ax,scene,visible_layers=[layer] if layer is not None else None,
                        highlight_ids=(inspection or {}).get('source_ids',[]),alpha=.35)
    if not selected:
        if not board_view:ax.set_aspect('auto')
        ax.text(.5,.5,'Choose a net and preview its copper.',ha='center',va='center',transform=ax.transAxes)
        if board_view:
            if show_context and scene:_draw_board_context(ax,scene,layer)
            ax.autoscale_view();ax.invert_yaxis();_fit_board_view(ax)
        else:figure.tight_layout()
        return ax
    if show_copper:
        for polygon in selected.get('polygons',[]):ax.add_patch(_polygon_patch(polygon))
    if view=='Results' and not show_overlay:view='Net'
    mesh=bundle.get('mesh');result=bundle.get('result');image=None
    markers=via_markers(mesh or {},result or {},geometry,layer,metric) if view=='Results' else []
    via_values=[row['value'] for row in markers]
    title=f"{geometry.get('net',bundle.get('request',{}).get('net',''))} · {selected['name']}"
    if view in ('Mesh','Results') and mesh:
        points=np.asarray(mesh['points_mm'],dtype=float)
        triangles=np.asarray(mesh['triangles'],dtype=int)
        mask=np.asarray([str(value)==str(layer) for value in mesh['triangle_layer']])
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
                    image.set_clim(*result_scale(bundle,metric,layer))
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
        if not any(str(v)==str(layer) for v in via.get('layers',[])):continue
        if 'x_mm' not in via:continue
        center=(via['x_mm'],via['y_mm'])
        face='none'
        ax.add_patch(Circle(center,via.get('diameter_mm',.5)/2,facecolor=face,edgecolor='#355b67',linewidth=.6))
        ax.add_patch(Circle(center,via.get('drill_mm',.3)/2,facecolor=ax.get_facecolor(),edgecolor='#355b67',linewidth=.3))
    for marker in markers:
        center=(marker['x_mm'],marker['y_mm']);color=image.cmap(image.norm(marker['value']))
        patch=Circle(center,marker['outer_radius_mm'],facecolor=color,edgecolor=color,linewidth=1.5,zorder=5)
        patch.set_gid('via-barrel:'+','.join(marker['segments']));ax.add_patch(patch)
        ax.add_patch(Circle(center,marker['drill_radius_mm'],facecolor=ax.get_facecolor(),edgecolor=color,linewidth=.6,zorder=6))
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
    source=request.get('source_terminal',request.get('source'));chosen=terminal_ids(request)
    for terminal in geometry.get('terminals',[]):
        if terminal.get('id') not in chosen and terminal.get('label') not in chosen:continue
        polygons=terminal.get('polygons',{}).get(str(layer),terminal.get('polygons',{}).get(layer,[]))
        if not polygons:continue
        ring=np.asarray(polygons[0]['outer'])[:,:2];center=ring.mean(axis=0)
        is_source=terminal['id']==source or terminal.get('label')==source
        ax.plot(*center,marker='o' if is_source else 's',markersize=4.5 if board_view else 6,color='#13854c' if is_source else '#b94535',markeredgecolor='white')
        label=('Source' if is_source else 'Sink') if board_view else ('Source: ' if is_source else 'Sink: ')+terminal.get('label',terminal['id'])
        offset=7 if not board_view or center[0]<sum(ax.dataLim.intervalx)/2 else -7
        ax.annotate(label,center,xytext=(offset,7),ha='left' if offset>0 else 'right',textcoords='offset points',fontsize=8,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':2})
    if board_view and show_context and scene:_draw_board_context(ax,scene,layer,selected['name'])
    if inspection and inspection.get('source_ids') and bundle.get('board_scene'):
        from wayricad_runtime.board_render import draw_matplotlib
        scene=bundle['board_scene'];wanted=set(inspection['source_ids'])
        selected_scene=dict(scene,primitives=[row for row in scene.get('primitives',[]) if row.get('uuid') in wanted and row.get('role') in ('track','pad','via')])
        for artist in draw_matplotlib(ax,selected_scene,visible_layers=[layer],highlight_ids=wanted,alpha=1.):
            artist.set_zorder(9)
            if hasattr(artist,'set_facecolor'):artist.set_facecolor('none');artist.set_linewidth(1.8)
    if inspection and inspection.get('location_mm'):
        span=inspection.get('layer');span=span if isinstance(span,list) else [span]
        if any(str(value)==str(layer) for value in span):
            x,y=inspection['location_mm'][:2]
            ax.plot(x,y,marker='+',markersize=15,markeredgewidth=2,color='#06a7a0',zorder=10)
            ax.annotate(f"{inspection['kind']} {str(inspection['id'])[:16]}",(x,y),xytext=(8,-14),textcoords='offset points',fontsize=8,
                        bbox={'facecolor':'white','edgecolor':'#06a7a0','alpha':.9,'pad':2})
    if view=='Results' and result and result.get('feasibility',{}).get('source_current_limit_exceeded'):
        title+='\nINFEASIBLE · requested-load diagnostic; source current limit exceeded'
    elif view=='Results' and result and result.get('feasibility',{}).get('feasible') is False:
        title+='\nINFEASIBLE · requested load/voltage limits violated'
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


def write_report(path,bundle,layer=None):
    """Export current-layer maps plus all numeric mesh/results as paired JSON."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    path=Path(path).with_suffix('.html');path.parent.mkdir(parents=True,exist_ok=True)
    result=bundle.get('result')
    if not result:raise ValueError('Run the analysis before exporting results.')
    rows=layer_rows(bundle)
    if layer is None and rows:layer=rows[0]['id']
    selected=next((row['name'] for row in rows if str(row['id'])==str(layer)),str(layer))
    images=[]
    primary_metrics=("drop","density","loss")
    ordered_metrics=primary_metrics+tuple(metric for metric in METRICS if metric not in primary_metrics)
    for metric in ordered_metrics:
        figure=Figure(figsize=(8.8,5.2),dpi=110);FigureCanvasAgg(figure)
        settings=bundle.get('view_settings',{});mode=settings.get('scale_mode',0)
        manual=settings.get('manual',{})
        limits=result_scale(bundle,metric) if mode==1 else tuple(manual['limits']) if mode==2 and manual.get('metric')==metric else None
        draw_view(figure,bundle,'Results',layer,metric,limits)
        stream=io.BytesIO();figure.savefig(stream,format='png',dpi=110,facecolor='white')
        scale_note=(' · all-layer scale' if mode==1 else ' · manual scale' if limits is not None else '')
        diagnostic=' · requested-load diagnostic (source current limit exceeded)' if result.get('feasibility',{}).get('source_current_limit_exceeded') else ''
        style=settings.get('field_style','smooth')
        images.append('<figure><figcaption>'+escape(metric_name(bundle,metric)+scale_note+diagnostic)+'</figcaption><p>'+escape(field_note(metric,style))+'</p><img alt="'+escape(metric_name(bundle,metric))+'" src="data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')+'"></figure>')
        figure.clear()
    scope='Circuit' if bundle.get('request',{}).get('series') else 'Copper'
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
    for key,label in [('planar_power_W','Copper sheet loss'),('via_power_W','Via barrel loss'),('conductor_power_W','Conductor loss'),('component_power_W','Component loss')]:
        if key in result:values.append((label,_number(result[key],'W')))
    table=''.join('<tr><th>'+escape(name)+'</th><td>'+escape(value)+'</td></tr>' for name,value in values)
    assumptions=result.get('thermal_assumptions',{})
    json_path=path.with_suffix('.json')
    json_path.write_text(json.dumps(bundle,indent=2,allow_nan=False),encoding='utf-8')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WayriCAD Quick PI</title><style>body{font:15px system-ui,sans-serif;margin:32px auto;max-width:1080px;padding:0 20px;color:#172a2b;background:#fff}h1{font-size:26px}p{line-height:1.5}table{border-collapse:collapse}th,td{text-align:left;padding:7px 20px 7px 0;border-bottom:1px solid #e0e6e5}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:18px}figure{margin:0;border:1px solid #e0e6e5;border-radius:5px;padding:12px}figcaption{font-weight:600}img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f6;padding:14px}</style><h1>WayriCAD Quick PI</h1>'''
    html+='<p>2.5D DC copper conduction · plotted layer '+escape(selected)+'. All layer mesh and numerical data are in <a href="'+escape(json_path.name)+'">the paired JSON report</a>.</p>'
    if result.get('feasibility'):
        html+='<h2>Source and load feasibility</h2><pre>'+escape(feasibility_text(result))+'</pre>'
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
    html+='<table>'+table+'</table><p>'+resistance_note+' Source V/I is the operating point, not copper resistance. Gray copper has no connected result. Dashed component links represent explicit lumped branches, not physical copper.</p><h2>Three primary result plots</h2><section>'+''.join(images[:3])+'</section><details><summary>Additional potential, resistance, flow and pulse-risk plots</summary><section>'+''.join(images[3:])+'</section></details>'
    if result.get('negative_sink_voltage'):
        html+='<p><strong>Operating-point warning:</strong> The requested current makes sink voltage negative; check source voltage and load. The imposed-current path may be infeasible.</p>'
    if result.get('analytics'):
        from .analytics import details_text
        html+='<h2>Copper thickness, layer losses and hotspots</h2><pre>'+escape(details_text(result))+'</pre>'
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
    path.write_text(html,encoding='utf-8')
    return {'html':str(path),'json':str(json_path)}


def write_sweep_report(path,bundle):
    """Export a standalone voltage/current chart and exact JSON sweep rows."""
    sweep=bundle.get('sweep')
    if not sweep or not sweep.get('rows'):
        raise ValueError('Run a current sweep before exporting its report.')
    path=Path(path).with_suffix('.html');path.parent.mkdir(parents=True,exist_ok=True)
    json_path=path.with_suffix('.json')
    json_path.write_text(json.dumps(bundle,indent=2,allow_nan=False),encoding='utf-8')
    rows=sweep['rows'];width=820;height=300;pad=42
    xmax=max(row['current_A'] for row in rows);xmin=min(row['current_A'] for row in rows)
    values=[row['path_drop_V'] for row in rows]+[row['sink_voltage_V'] for row in rows]
    ymin=min(values);ymax=max(values)
    if ymax==ymin:ymax=ymin+1
    x=lambda value:pad+(value-xmin)/(xmax-xmin)*(width-2*pad)
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
    path.write_text(html,encoding='utf-8')
    return {'html':str(path),'json':str(json_path)}


def write_diagnostic_report(path, bundle):
    """Export return-path findings without remote assets."""
    result = bundle.get('return_path')
    if not result:
        raise ValueError('No return-path result is available.')
    path = Path(path).with_suffix('.html')
    path.parent.mkdir(parents=True, exist_ok=True)
    json_path = path.with_suffix('.json')
    json_path.write_text(json.dumps(bundle, indent=2, allow_nan=False), encoding='utf-8')
    html = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>WayriCAD Return-path review</title>'
            '<style>body{font:15px system-ui,sans-serif;max-width:1050px;margin:32px auto;padding:0 20px;color:#173039}'
            'table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}</style>'
            '<h1>WayriCAD Return-path review</h1><p>Read-only saved-board analysis. '
            '<a href="' + escape(json_path.name) + '">Complete JSON evidence</a>.</p>')
    html += '<p>' + escape(result['basis']) + '</p>'
    html += '<p>' + str(result['warning_count']) + ' warnings · ' + str(result['unknown_count']) + ' unknowns</p>'
    html += '<table><tr><th>Level</th><th>Code</th><th>Layer</th><th>Position mm</th><th>Detail</th></tr>'
    for row in result['findings']:
        position = ', '.join(f'{value:.4g}' for value in row['position_mm']) if row['position_mm'] else '—'
        html += '<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in (
            row['level'], row['code'], row['layer'], position, row['detail'])) + '</tr>'
    path.write_text(html + '</table></html>', encoding='utf-8')
    return {'html': str(path), 'json': str(json_path)}


def interactive_fields(bundle,layer):
    """Offline cell probes using saved triangles; holes and unknowns stay gaps."""
    import numpy as np
    from wayricad_runtime.interactive_plots import interactive_plot
    mesh=bundle['mesh'];result=bundle['result']
    points=np.asarray(mesh['points_mm'])
    indices=[i for i,v in enumerate(mesh['triangle_layer']) if str(v)==str(layer)]
    triangles=np.asarray(mesh['triangles'],dtype=int)[indices]
    polygons=points[triangles,:2].tolist()
    centers=points[triangles,:2].mean(axis=1)
    html=''
    for metric in ('drop','density','loss'):
        values=cell_values(mesh,result,metric)
        rows=[[float(x),float(y),float(values[i]),'Cell '+str(i)] for (x,y),i in zip(centers,indices)]
        html+=interactive_plot(METRICS[metric][0],rows,METRICS[metric][1],polygons=polygons)
    return html
