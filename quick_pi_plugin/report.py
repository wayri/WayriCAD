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
    'resistance':('DC transfer resistance ΔV/I','mΩ','magma'),
    'density':('Current density','A/mm²','inferno'),
    'flow':('Current flow','A/mm','viridis'),
    'loss':('Copper loss density','W/mm²','inferno'),
    'risk':('Adiabatic pulse energy / limit','ratio','YlOrRd'),
}


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


def draw_view(figure,bundle,view='Results',layer=None,metric='drop'):
    """Draw actual polygon/triangle geometry; GUI and export use identical data."""
    import numpy as np
    from matplotlib.collections import PolyCollection
    from matplotlib.patches import Circle
    geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
    rows=geometry.get('layers',[])
    if layer is None and rows:layer=rows[0]['id']
    selected=next((row for row in rows if str(row['id'])==str(layer)),None)
    figure.clear();ax=figure.add_subplot(111);ax.set_facecolor('#ffffff')
    ax.set_aspect('equal',adjustable='box');ax.set_xlabel('X (mm)');ax.set_ylabel('Y (mm)')
    ax.grid(False)
    if not selected:
        ax.text(.5,.5,'Choose a net and preview its copper.',ha='center',va='center',transform=ax.transAxes)
        figure.tight_layout();return ax
    for polygon in selected.get('polygons',[]):ax.add_patch(_polygon_patch(polygon))
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
                    image=PolyCollection(polygons[finite],array=values[finite],cmap=cmap,edgecolors='none',rasterized=True)
                    limits=[*values[finite],*via_values]
                    if metric=='risk':image.set_clim(0,max(1.,float(max(limits))))
                    elif via_values:image.set_clim(min(limits),max(limits))
                    ax.add_collection(image)
                    figure.colorbar(image,ax=ax,pad=.025,label=f'{METRICS[metric][0]} ({unit})')
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
                title+=' · '+METRICS[metric][0]
            else:ax.text(.02,.98,'Run the analysis to see electrical results.',va='top',transform=ax.transAxes)
    if image is None and via_values:
        from matplotlib.cm import ScalarMappable
        from matplotlib.colors import Normalize
        image=ScalarMappable(norm=Normalize(0,max(1.,max(via_values))) if metric=='risk' else Normalize(min(via_values),max(via_values)),cmap=METRICS[metric][2])
        figure.colorbar(image,ax=ax,pad=.025,label=f'{METRICS[metric][0]} ({METRICS[metric][1]})')
    for via in geometry.get('vias',[]):
        if not any(str(v)==str(layer) for v in via.get('layers',[])):continue
        if 'x_mm' not in via:continue
        center=(via['x_mm'],via['y_mm'])
        face='none'
        ax.add_patch(Circle(center,via.get('diameter_mm',.5)/2,facecolor=face,edgecolor='#355b67',linewidth=.6))
        ax.add_patch(Circle(center,via.get('drill_mm',.3)/2,facecolor='white',edgecolor='#355b67',linewidth=.3))
    for marker in markers:
        center=(marker['x_mm'],marker['y_mm']);color=image.cmap(image.norm(marker['value']))
        patch=Circle(center,marker['outer_radius_mm'],facecolor=color,edgecolor=color,linewidth=1.5,zorder=5)
        patch.set_gid('via-barrel:'+','.join(marker['segments']));ax.add_patch(patch)
        ax.add_patch(Circle(center,marker['drill_radius_mm'],facecolor='white',edgecolor=color,linewidth=.6,zorder=6))
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
    source=request.get('source_terminal',request.get('source'));sink=request.get('sink_terminal',request.get('sink'))
    for terminal in geometry.get('terminals',[]):
        if terminal.get('id') not in (source,sink) and terminal.get('label') not in (source,sink):continue
        polygons=terminal.get('polygons',{}).get(str(layer),terminal.get('polygons',{}).get(layer,[]))
        if not polygons:continue
        ring=np.asarray(polygons[0]['outer'])[:,:2];center=ring.mean(axis=0)
        is_source=terminal['id']==source or terminal.get('label')==source
        ax.plot(*center,marker='o' if is_source else 's',markersize=6,color='#13854c' if is_source else '#b94535',markeredgecolor='white')
        ax.annotate(('Source: ' if is_source else 'Sink: ')+terminal.get('label',terminal['id']),center,xytext=(7,7),textcoords='offset points',fontsize=8,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':2})
    ax.autoscale_view();ax.invert_yaxis();ax.set_title(title,loc='left',fontsize=10)
    ax._wayricad_home=(ax.get_xlim(),ax.get_ylim())
    ax.set_anchor('C')
    figure.subplots_adjust(left=.08,right=.90,bottom=.20,top=.90)
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
    for metric in METRICS:
        figure=Figure(figsize=(8.8,5.2),dpi=110);FigureCanvasAgg(figure)
        draw_view(figure,bundle,'Results',layer,metric)
        stream=io.BytesIO();figure.savefig(stream,format='png',dpi=110,facecolor='white')
        images.append('<figure><figcaption>'+escape(METRICS[metric][0])+'</figcaption><img alt="'+escape(METRICS[metric][0])+'" src="data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')+'"></figure>')
        figure.clear()
    scope='Circuit' if bundle.get('request',{}).get('series') else 'Copper'
    values=[(scope+' resistance ΔV/I',_number(result.get('drop_over_current_ohm'),'mΩ',1000)),
            ('Voltage drop',_number(result.get('voltage_drop_V'),'mV',1000)),
            ('Total loss',_number(result.get('total_power_W'),'W')),
            ('Peak copper-sheet current density',_number(result.get('max_current_density_A_mm2'),'A/mm²')),
            ('Source voltage',_number(result.get('source_voltage_V'),'V')),
            ('Sink current',_number(result.get('sink_current_A'),'A')),
            ('Operating-point source V/I',_number(result.get('V_over_I_ohm'),'Ω')),
            ('Current balance error',_number(result.get('current_balance_error_A'),'A')),
            ('Energy relative error',_number(result.get('energy_relative_error'))),
            ('Floating triangles',str(result.get('floating_triangles',0)))]
    for key,label in [('conductor_power_W','Conductor loss'),('component_power_W','Component loss')]:
        if key in result:values.append((label,_number(result[key],'W')))
    table=''.join('<tr><th>'+escape(name)+'</th><td>'+escape(value)+'</td></tr>' for name,value in values)
    assumptions=result.get('thermal_assumptions',{})
    json_path=path.with_suffix('.json')
    json_path.write_text(json.dumps(bundle,indent=2,allow_nan=False),encoding='utf-8')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WayriCAD Quick PI</title><style>body{font:15px system-ui,sans-serif;margin:32px auto;max-width:1080px;padding:0 20px;color:#172a2b;background:#fff}h1{font-size:26px}p{line-height:1.5}table{border-collapse:collapse}th,td{text-align:left;padding:7px 20px 7px 0;border-bottom:1px solid #e0e6e5}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:18px}figure{margin:0;border:1px solid #e0e6e5;border-radius:5px;padding:12px}figcaption{font-weight:600}img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f6;padding:14px}</style><h1>WayriCAD Quick PI</h1>'''
    html+='<p>2.5D DC copper conduction · plotted layer '+escape(selected)+'. All layer mesh and numerical data are in <a href="'+escape(json_path.name)+'">the paired JSON report</a>.</p>'
    html+='<p><strong>Mesh convergence not verified.</strong> Compare refined meshes before relying on resistance or localized current-density and pulse-risk peaks. These maps are screening estimates.</p>'
    html+='<p>The DC transfer-resistance map divides the source-to-cell potential drop by the specified sink current. It is not an AC impedance map.</p>'
    html+='<table>'+table+'</table><p>'+scope+' resistance uses the solved voltage drop divided by load current. Source V/I is the operating point, not copper resistance. Gray copper has no connected result. Dashed component links represent explicit lumped branches, not physical copper.</p><section>'+''.join(images)+'</section>'
    if result.get('components'):
        html+='<h2>Explicit component branches</h2><p>DC resistance contributes to the solved path. Inductance is reported as an input; this is not an AC or transient solve.</p><pre>'+escape(json.dumps(result['components'],indent=2))+'</pre>'
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
