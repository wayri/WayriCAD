"""Top-side saved-board display of lumped QuickTherm component estimates."""
from __future__ import annotations

import numpy as np
from matplotlib import colormaps
from matplotlib.patches import Polygon


def _draw_3d(figure,view,selected_id,network,azim,elev):
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
        xs=field.get('x_centers_mm',[]);ys=field.get('y_centers_mm',[])
        points=[(x,y,value) for j,y in enumerate(ys) for i,x in enumerate(xs)
                if (value:=field['values_c'][j][i]) is not None]
        if points:
            dx=abs(xs[1]-xs[0]) if len(xs)>1 else 1
            dy=abs(ys[1]-ys[0]) if len(ys)>1 else 1
            lo=min(p[2] for p in points);hi=max(p[2] for p in points)
            quads=[[(x-dx/2,y-dy/2,thickness+.02),(x+dx/2,y-dy/2,thickness+.02),
                    (x+dx/2,y+dy/2,thickness+.02),(x-dx/2,y+dy/2,thickness+.02)]
                   for x,y,_ in points]
            colors=[colormaps['inferno'](.5 if hi==lo else (value-lo)/(hi-lo))
                    for _,_,value in points]
            ax.add_collection3d(Poly3DCollection(quads,facecolors=colors,edgecolor='none',alpha=.55))
    solved=[item['junction_c'] for item in view.get('components',[]) if item.get('junction_c') is not None]
    low=min(solved) if solved else 0;high=max(solved) if solved else 1
    for item in view.get('components',[]):
        if not item.get('in_scope') or not item.get('position_mm'):continue
        x,y=item['position_mm'];top=item.get('top_side',True)
        z=thickness+.8 if top else -.8
        value=item.get('junction_c')
        color='#758591' if value is None else colormaps['inferno'](.5 if high==low else (value-low)/(high-low))
        ax.scatter([x],[y],[z],color=[color],s=145 if item['id']==selected_id else 70,
                   edgecolor='#00d3b1' if item['id']==selected_id else 'white',depthshade=False)
        ax.text(x,y,z+.25,item['reference'],fontsize=8)
        ax.plot([x,x],[y,y],[thickness if top else 0,z],color='#576d70',linewidth=.7)
    bbox=view.get('bbox_mm')
    if bbox:
        x0,y0,x1,y1=bbox;ax.set_xlim(x0,x1);ax.set_ylim(y1,y0)
        ax.set_box_aspect((max(x1-x0,1),max(y1-y0,1),max(thickness*5,4)),zoom=.9)
    ax.set_zlim(-1.2,thickness+1.5);ax.set_xlabel('X mm');ax.set_ylabel('Y mm');ax.set_zlabel('Illustrative height')
    ax.view_init(elev=elev,azim=azim)
    ax.set_title('Saved board 3D overview · marker heights illustrative')
    figure.tight_layout();return ax


def draw_thermal_view(figure, view, mode='Top-side map', selected_id=None,
                      network=None,azim=-60,elev=28):
    figure.clear()
    if mode=='3D overview':return _draw_3d(figure,view,selected_id,network,azim,elev)
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
    contour='contour' in mode.lower()
    board_model='board model' in mode.lower() or bool(layer_name)
    field=view.get('fields_by_side',{}).get(side,field)
    if contour and field.get('status')=='available':
        values=np.ma.masked_invalid(np.asarray([[np.nan if value is None else value for value in row]
                                                for row in field['values_c']],dtype=float))
        if values.count():
            x=np.asarray(field['x_centers_mm']);y=np.asarray(field['y_centers_mm'])
            mesh=ax.contourf(x,y,values,levels=24,cmap='inferno',alpha=.75)
            figure.colorbar(mesh,ax=ax,label='Interpolated junction estimate °C')
    elif contour:
        ax.text(.5,.05,field.get('reason') or 'Contour unavailable',ha='center',va='bottom',
                transform=ax.transAxes,bbox={'facecolor':'white','alpha':.9,'edgecolor':'none'})
    if board_model:
        model_field=(network or {}).get('board_field',{})
        if (network or {}).get('layers'):
            layers=network['layers']
            model_field=next((row for row in layers if row['name']==layer_name),layers[-1 if bottom else 0])
        if model_field.get('values_c'):
            values=np.ma.masked_invalid(np.asarray([[np.nan if value is None else value for value in row]
                                                    for row in model_field['values_c']],dtype=float))
            if values.count():
                mesh=ax.contourf(model_field['x_centers_mm'],model_field['y_centers_mm'],values,
                                   levels=32,cmap='inferno',alpha=.9)
                figure.colorbar(mesh,ax=ax,label=('Layer temperature °C' if (network or {}).get('layers') else 'Approximate board midplane °C'))
        else:ax.text(.5,.05,'Run the optional board heat model for this field.',ha='center',va='bottom',
                     transform=ax.transAxes,bbox={'facecolor':'white','alpha':.9,'edgecolor':'none'})
    for outline in view.get('outline',[]):
        outer=outline.get('outer_mm',[])
        if len(outer)>=3:
            ax.add_patch(Polygon(outer,closed=True,fill=False,edgecolor='#315e68',linewidth=2))
        for hole in outline.get('holes_mm',[]):
            if len(hole)>=3:ax.add_patch(Polygon(hole,closed=True,fill=False,edgecolor='#315e68',linewidth=1))
    bbox=view.get('bbox_mm')
    if bbox and not view.get('outline'):
        x0,y0,x1,y1=bbox
        ax.add_patch(Polygon([[x0,y0],[x1,y0],[x1,y1],[x0,y1]],closed=True,fill=False,
                             linestyle='--',edgecolor='#888'))
    shown=[item for item in components if item.get('side')==side]
    solved=[item for item in shown if item.get('solved') and item.get('position_mm')]
    temps=[item['junction_c'] for item in solved]
    low=min(temps) if temps else None;high=max(temps) if temps else None
    for item in shown:
        position=item.get('position_mm')
        if not position:continue
        current=item['id']==selected_id
        value=item.get('junction_c')
        color='#697985' if value is None else colormaps['inferno'](
            .5 if high==low else (value-low)/(high-low))
        ax.scatter(*position,s=195 if current else 95,marker='o',
                   facecolor=color,edgecolor='#00d3b1' if current else 'white',linewidth=2 if current else .8,zorder=4)
        if item.get('in_scope'):
            ax.annotate(item['reference'],position,xytext=(5,5),textcoords='offset points',
                        fontsize=8,fontweight='bold' if current else 'normal',zorder=5)
    if not shown:
        ax.text(.5,.5,'No saved '+side+'-side footprints',ha='center',transform=ax.transAxes)
    if bbox:
        x0,y0,x1,y1=bbox;pad=max(x1-x0,y1-y0)*.05 or 1
        ax.set_xlim((x1+pad,x0-pad) if bottom else (x0-pad,x1+pad));ax.set_ylim(y1+pad,y0-pad)
    else:ax.invert_yaxis()
    ax.set_aspect('equal',adjustable='box');ax.set_xlabel('X mm'+(' · mirrored bottom view' if bottom else ''));ax.set_ylabel('Y mm')
    ax.set_title('Saved PCB '+side+' view · '+((layer_name+' copper layer' if layer_name else 'approximate board midplane') if board_model else
                 'same-side junction interpolation' if contour else 'component junction estimates'))
    figure.tight_layout();return ax
