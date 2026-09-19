"""Layer and local-loss summaries from the actual solved sheet/barrel model."""
import heapq
import math


def thickness_label(row):
    low,high=row['thickness_min_mm']*1000,row['thickness_max_mm']*1000
    return f'{low:.6g} µm' if low==high else f'{low:.6g}–{high:.6g} µm'


def summarize(mesh, result):
    geometry=mesh.get('geometry',{})
    names={str(layer['id']):layer.get('name',str(layer['id'])) for layer in geometry.get('layers',[])}
    layers={};density_heap=[];heating_heap=[];serial=0
    def hotspot(row):
        nonlocal serial
        serial+=1
        for heap,field in ((density_heap,'current_density_A_mm2'),(heating_heap,'power_density_W_mm3')):
            value=row.get(field)
            if value is None:continue
            item=(value,serial,row)
            if len(heap)<12:heapq.heappush(heap,item)
            elif value>heap[0][0]:heapq.heapreplace(heap,item)
    for i,(triangle,thickness,layer) in enumerate(zip(mesh['triangles'],mesh['triangle_thickness_mm'],result['cell_layer'])):
        a,b,c=(mesh['points_mm'][index] for index in triangle)
        area=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2
        volume=area*thickness;power=result['cell_power_W'][i];vector=result['cell_J_A_mm2'][i]
        key=str(layer)
        row=layers.setdefault(key,{'layer':layer,'name':names.get(key,key),'area_mm2':0.,'volume_mm3':0.,
            'connected_area_mm2':0.,'connected_volume_mm3':0.,'planar_power_W':0.,
            'thickness_min_mm':float(thickness),'thickness_max_mm':float(thickness),
            'peak_current_density_A_mm2':None,'peak_location_mm':None,'triangle_count':0,'floating_triangles':0})
        row['area_mm2']+=area;row['volume_mm3']+=volume;row['triangle_count']+=1
        row['thickness_min_mm']=min(row['thickness_min_mm'],float(thickness))
        row['thickness_max_mm']=max(row['thickness_max_mm'],float(thickness))
        if power is None or vector is None:
            row['floating_triangles']+=1;continue
        row['connected_area_mm2']+=area;row['connected_volume_mm3']+=volume;row['planar_power_W']+=power
        density=math.sqrt(sum(value*value for value in vector));location=result['cell_centroid_mm'][i]
        if row['peak_current_density_A_mm2'] is None or density>row['peak_current_density_A_mm2']:
            row['peak_current_density_A_mm2']=density;row['peak_location_mm']=location
        hotspot({'kind':'sheet','id':i,'layer':layer,'layer_name':row['name'],'location_mm':location,
                 'thickness_mm':float(thickness),'current_density_A_mm2':density,'power_W':power,
                 'power_density_W_mm3':power/volume,'thermal':result['cell_thermal'][i]})
    via_metadata={str(v['id']):v for v in mesh.get('vias',[])}
    for via in result.get('vias',[]):
        if via.get('power_W') is None:continue
        metadata=via_metadata.get(str(via['id']),{})
        points=[mesh['points_mm'][i] for name in ('top_nodes','bottom_nodes') for i in metadata.get(name,[])]
        location=[sum(p[axis] for p in points)/len(points) for axis in range(3)] if points else None
        if location and 'x_mm' in metadata and 'y_mm' in metadata:location[:2]=[metadata['x_mm'],metadata['y_mm']]
        span=[metadata.get('top_layer'),metadata.get('bottom_layer')]
        hotspot({'kind':'via','id':via['id'],'layer':span,'layer_name':' → '.join(names.get(str(v),str(v)) for v in span),
                 'location_mm':location,'current_density_A_mm2':via['current_density_A_mm2'],
                 'power_W':via['power_W'],'power_density_W_mm3':via['power_W']/via['volume_mm3'],
                 'thermal':via.get('thermal',{})})
    planar=sum(row['planar_power_W'] for row in layers.values())
    barrels=sum(v.get('power_W') or 0 for v in result.get('vias',[]))
    component=result.get('component_power_W',0.)
    ranked=lambda heap:[dict(row,rank=index+1) for index,(_,_,row) in enumerate(sorted(heap,reverse=True))]
    return {'layers':list(layers.values()),'losses':{'planar_W':planar,'via_W':barrels,'component_W':component,
            'total_W':planar+barrels+component,'accounting_error_W':abs(planar+barrels+component-result['total_power_W'])},
            'hotspots_by_current_density':ranked(density_heap),'hotspots_by_heating_density':ranked(heating_heap),
            'thickness_basis':'Actual triangle thickness from saved board stackup or explicit stackup override; no nominal copper-weight guess.',
            'notice':'Areas and volumes describe meshed copper on the selected net(s); floating copper is reported separately. '
                     'Via loss is separate and is not assigned twice to its endpoint layers. Hotspots are mesh-dependent cell/barrel estimates, '
                     'not whole-track ratings. Adiabatic pulse screening does not predict actual fusing or steady-state temperature.'}


def details_text(result):
    analysis=result.get('analytics',{})
    if not analysis:return 'Run the analysis to view layer and loss details.'
    losses=analysis['losses']
    lines=['LOSS ACCOUNTING',f"Sheets {losses['planar_W']:.6g} W | Via barrels {losses['via_W']:.6g} W | Components {losses['component_W']:.6g} W",
           f"Total {losses['total_W']:.6g} W | Accounting error {losses['accounting_error_W']:.3g} W",'', 'COPPER LAYERS']
    for row in analysis['layers']:
        peak=row['peak_current_density_A_mm2']
        peak_text=f'{peak:.6g} A/mm²' if peak is not None else 'unavailable (floating copper)'
        lines.append(f"{row['name']}: {thickness_label(row)}; "
                     f"area {row['area_mm2']:.6g} mm²; volume {row['volume_mm3']:.6g} mm³; loss {row['planar_power_W']:.6g} W; "
                     f"peak J {peak_text}; connected area {row['connected_area_mm2']:.6g} mm²")
    lines.extend(['','HOTSPOTS — HIGHEST VOLUMETRIC HEATING'])
    for row in analysis['hotspots_by_heating_density']:
        location=', '.join(f'{x:.5g}' for x in row['location_mm']) if row['location_mm'] else 'unavailable'
        thermal=row['thermal'];ratio=thermal.get('energy_ratio')
        lines.append(f"{row['rank']}. {row['kind']} {row['id']} | {row['layer_name']} | ({location}) mm | "
                     f"J {row['current_density_A_mm2']:.5g} A/mm² | {row['power_density_W_mm3']:.5g} W/mm³ | "
                     +(f"pulse energy/limit {ratio:.5g}" if ratio is not None else 'pulse duration required for thermal screening'))
    lines.extend(['',analysis['thickness_basis'],analysis['notice'],result.get('thermal_assumptions',{}).get('notice','')])
    return '\n'.join(lines)
