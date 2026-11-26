"""Layer and local-loss summaries from the actual solved sheet/barrel model."""
import heapq

_CELL_BLOCK_SIZE = 65536


def thickness_label(row):
    low,high=row['thickness_min_mm']*1000,row['thickness_max_mm']*1000
    return f'{low:.6g} µm' if low==high else f'{low:.6g}–{high:.6g} µm'


def summarize(mesh, result):
    import numpy as np

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

    # Evaluate the same XY determinant as the scalar loop in bounded blocks.
    # Keep mesh-sized gather temporaries out of large-board post-processing.
    triangles=np.asarray(mesh['triangles'],dtype=np.intp).reshape(-1,3)
    points=np.asarray(mesh['points_mm'],dtype=float)[:,:2]
    area=np.empty(len(triangles),dtype=float)
    for start in range(0,len(triangles),_CELL_BLOCK_SIZE):
        stop=min(start+_CELL_BLOCK_SIZE,len(triangles))
        a,b,c=points[triangles[start:stop].T]
        ab=b-a;ac=c-a
        area[start:stop]=np.abs(ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0])/2
    thickness=np.asarray(mesh['triangle_thickness_mm'],dtype=float)
    volume=area*thickness

    labels=result['cell_layer']
    source_layers={}
    layer_index={}
    def layer_number(label):
        key=str(label)
        if key not in layer_index:
            layer_index[key]=len(layer_index)
            source_layers[key]=label
        return layer_index[key]
    owner=np.fromiter((layer_number(label) for label in labels),dtype=np.intp,count=len(triangles))
    count=len(layer_index)
    powers=result['cell_power_W']
    vectors=result['cell_J_A_mm2']
    active=np.fromiter((i for i,(power,vector) in enumerate(zip(powers,vectors))
                        if power is not None and vector is not None),dtype=np.intp)
    connected_owner=owner[active]
    connected_power=np.asarray([powers[i] for i in active],dtype=float)
    connected_vectors=np.asarray([vectors[i] for i in active],dtype=float).reshape(-1,2)
    density=np.sqrt(np.sum(connected_vectors*connected_vectors,axis=1))
    heating=connected_power/volume[active]

    total_area=np.bincount(owner,weights=area,minlength=count)
    total_volume=np.bincount(owner,weights=volume,minlength=count)
    connected_area=np.bincount(connected_owner,weights=area[active],minlength=count)
    connected_volume=np.bincount(connected_owner,weights=volume[active],minlength=count)
    planar_loss=np.bincount(connected_owner,weights=connected_power,minlength=count)
    total_cells=np.bincount(owner,minlength=count)
    connected_cells=np.bincount(connected_owner,minlength=count)
    min_thickness=np.full(count,np.inf)
    max_thickness=np.full(count,-np.inf)
    np.minimum.at(min_thickness,owner,thickness)
    np.maximum.at(max_thickness,owner,thickness)
    peaks=np.full(count,-np.inf)
    np.maximum.at(peaks,connected_owner,density)
    peak_cells=np.full(count,len(triangles),dtype=np.intp)
    tied=density==peaks[connected_owner]
    np.minimum.at(peak_cells,connected_owner[tied],active[tied])

    locations=result['cell_centroid_mm']
    for key,j in layer_index.items():
        connected=bool(connected_cells[j])
        layers[key]={'layer':source_layers[key],'name':names.get(key,key),
                'area_mm2':float(total_area[j]),'volume_mm3':float(total_volume[j]),
                'connected_area_mm2':float(connected_area[j]),'connected_volume_mm3':float(connected_volume[j]),
                'planar_power_W':float(planar_loss[j]),'thickness_min_mm':float(min_thickness[j]),
                'thickness_max_mm':float(max_thickness[j]),
                'peak_current_density_A_mm2':float(peaks[j]) if connected else None,
                'peak_location_mm':locations[peak_cells[j]] if connected else None,
                'triangle_count':int(total_cells[j]),'floating_triangles':int(total_cells[j]-connected_cells[j])}
    # Retain the existing equal-value ordering, including later via contenders.
    # Materialize Python scalars in blocks and allocate rows only for contenders.
    for start in range(0,len(active),_CELL_BLOCK_SIZE):
        stop=min(start+_CELL_BLOCK_SIZE,len(active))
        candidates=zip(active[start:stop].tolist(),density[start:stop].tolist(),heating[start:stop].tolist())
        for cell_index,current_density,power_density in candidates:
            if (len(density_heap)<12 or current_density>density_heap[0][0] or
                    len(heating_heap)<12 or power_density>heating_heap[0][0]):
                layer=labels[cell_index]
                key=str(layer)
                hotspot({'kind':'sheet','id':cell_index,'layer':layer,'layer_name':names.get(key,key),
                         'location_mm':locations[cell_index],'thickness_mm':float(thickness[cell_index]),
                         'current_density_A_mm2':current_density,'power_W':float(powers[cell_index]),
                         'power_density_W_mm3':power_density,'thermal':result['cell_thermal'][cell_index]})
            else:
                serial+=1
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
    package=result.get('package_power_W',0.)
    ranked=lambda heap:[dict(row,rank=index+1) for index,(_,_,row) in enumerate(sorted(heap,reverse=True))]
    return {'layers':list(layers.values()),'losses':{'planar_W':planar,'via_W':barrels,'component_W':component,'package_W':package,
            'total_W':planar+barrels+component+package,'accounting_error_W':abs(planar+barrels+component+package-result['total_power_W'])},
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
    if result.get('package_contacts'):
        from .package_contacts import details_text as package_text
        lines.extend(['',package_text(result)])
    lines.extend(['','HOTSPOTS — HIGHEST VOLUMETRIC HEATING'])
    for row in analysis['hotspots_by_heating_density']:
        location=', '.join(f'{x:.5g}' for x in row['location_mm']) if row['location_mm'] else 'unavailable'
        thermal=row['thermal'];ratio=thermal.get('energy_ratio')
        lines.append(f"{row['rank']}. {row.get('display_id') or str(row['kind'])+' '+str(row['id'])} | {row['layer_name']} | ({location}) mm | "
                     f"J {row['current_density_A_mm2']:.5g} A/mm² | {row['power_density_W_mm3']:.5g} W/mm³ | "
                     +(f"pulse energy/limit {ratio:.5g}" if ratio is not None else 'pulse duration required for thermal screening'))
    lines.extend(['',analysis['thickness_basis'],analysis['notice'],result.get('thermal_assumptions',{}).get('notice','')])
    if result.get('fusing'):
        from .fusing import details_text as fusing_text
        lines.extend(['',fusing_text(result['fusing'])])
    return '\n'.join(lines)
