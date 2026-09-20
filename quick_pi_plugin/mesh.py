"""Conforming 2.5D copper meshes from filled KiCad polygons, retaining holes.

VTK triangulates each disjoint copper/contact region. Coincident vertices are
merged before edge-length-only subdivision so electrode boundaries conform.
Layer vertices remain distinct; electrical barrel links are explicit.
"""
from __future__ import annotations
import math
import numpy as np
from matplotlib.path import Path


def contains(points, polygons):
    points = np.asarray(points, dtype=float)[:, :2]
    result = np.zeros(len(points), dtype=bool)
    for polygon in polygons:
        outer = np.asarray(polygon['outer'], dtype=float)
        # Matplotlib's positive-radius direction follows ring orientation.
        area = np.sum(outer[:,0]*np.roll(outer[:,1],-1)-outer[:,1]*np.roll(outer[:,0],-1))
        inside = Path(np.vstack((outer,outer[0]))).contains_points(points,radius=1e-8 if area>0 else -1e-8)
        for ring in polygon.get('holes', []):
            ring = np.asarray(ring,dtype=float)
            area = np.sum(ring[:,0]*np.roll(ring[:,1],-1)-ring[:,1]*np.roll(ring[:,0],-1))
            # Keep hole boundaries, which are valid electrode edge nodes.
            inside &= ~Path(np.vstack((ring,ring[0]))).contains_points(points,radius=-1e-8 if area>0 else 1e-8)
        result |= inside
    return result


def _conforming_contours(polygons, cancelled=None, maximum_edge=None):
    """Split shared edges at every contact-region vertex before triangulation.

    Merging coincident vertices cannot repair a T junction: the neighboring
    triangle must contain the same edge subdivisions. Polygon clipping can
    retain a collinear vertex on only one side of an electrode boundary.
    """
    from scipy.spatial import cKDTree
    normalized=[]; all_points=[]
    for polygon in polygons:
        rings=[]
        for ring in [polygon['outer'],*polygon.get('holes',[])]:
            array=np.asarray(ring,dtype=float)
            if array.ndim!=2 or array.shape[1]<2 or not np.isfinite(array).all():
                raise ValueError('Copper contours require finite XY coordinates.')
            array=array[:,:2]
            if len(array)>1 and np.array_equal(array[0],array[-1]):array=array[:-1]
            if len(array)<3:raise ValueError('A copper contour has fewer than three vertices.')
            rings.append(array);all_points.extend(array.tolist())
        normalized.append(rings)
    if not all_points:raise ValueError('No filled copper area can be meshed.')
    cloud=np.unique(np.asarray(all_points),axis=0);tree=cKDTree(cloud);result=[]
    tolerance=1e-9
    for rings in normalized:
        if cancelled and cancelled():raise InterruptedError('Meshing cancelled.')
        split_rings=[]
        for ring in rings:
            out=[]
            for a,b in zip(ring,np.roll(ring,-1,axis=0)):
                direction=b-a; length=float(np.linalg.norm(direction))
                if length<=tolerance:continue
                out.append(a.tolist())
                nearby=cloud[tree.query_ball_point((a+b)/2,length/2+tolerance)]
                fraction=((nearby-a)@direction)/(length*length)
                distance=np.linalg.norm(nearby-(a+fraction[:,None]*direction),axis=1)
                keep=(fraction>tolerance/length)&(fraction<1-tolerance/length)&(distance<=tolerance)
                indices=np.flatnonzero(keep)
                for index in indices[np.argsort(fraction[indices])]:
                    point=nearby[index]
                    if np.linalg.norm(point-np.asarray(out[-1]))>tolerance:out.append(point.tolist())
            if len(out)<3:raise ValueError('Degenerate copper contour.')
            if maximum_edge is not None:
                refined=[]
                for a,b in zip(np.asarray(out),np.roll(out,-1,axis=0)):
                    count=max(1,math.ceil(float(np.linalg.norm(b-a))/maximum_edge))
                    if count>400000:raise ValueError('Contour subdivision exceeds mesh budget.')
                    refined.extend((a+(b-a)*i/count).tolist() for i in range(count))
                out=refined
            split_rings.append(out)
        result.append({'outer':split_rings[0],'holes':split_rings[1:]})
    return result


def _split_point_contacts(points, triangles):
    """A shared vertex alone has zero conducting width; split separate fans."""
    edges=np.sort(np.concatenate((triangles[:,[0,1]],triangles[:,[1,2]],triangles[:,[2,0]])),axis=1)
    unique,counts=np.unique(edges,axis=0,return_counts=True)
    if np.any(counts>2):raise ValueError('Copper triangulation has overlapping or non-manifold edges.')
    boundary=unique[counts==1]
    vertices,degree=np.unique(boundary.ravel(),return_counts=True)
    candidates=vertices[degree>2]
    added=[]
    for vertex in candidates:
        incident=np.flatnonzero(np.any(triangles==vertex,axis=1))
        by_neighbor={}
        for cell in incident:
            for other in triangles[cell]:
                if other!=vertex:by_neighbor.setdefault(int(other),[]).append(int(cell))
        neighbors={int(cell):set() for cell in incident}
        for cells in by_neighbor.values():
            for cell in cells:neighbors[cell].update(cells)
        remaining=set(neighbors);first=True
        while remaining:
            queue=[remaining.pop()];component=[]
            while queue:
                cell=queue.pop();component.append(cell)
                new=neighbors[cell]&remaining;remaining-=new;queue.extend(new)
            if first:first=False;continue
            replacement=len(points)+len(added);added.append(points[vertex].copy())
            for cell in component:triangles[cell,triangles[cell]==vertex]=replacement
    if added:points=np.vstack((points,added))
    return points,triangles,len(added)


def _improve_angles(points, triangles, regions, passes=32, cancelled=None):
    """Lawson flips within one copper/contact region, preserving all constraints.

    Only convex pairs sharing an interior edge may flip. Edges between contact
    regions, exterior boundaries and holes remain untouched. Disjoint pairs are
    processed together so no triangle participates in two flips in one pass.
    """
    t=triangles.copy();xy=points[:,:2]
    cross=lambda a,b:a[:,0]*b[:,1]-a[:,1]*b[:,0]
    for _ in range(passes):
        if cancelled and cancelled():raise InterruptedError('Meshing cancelled.')
        edges=np.sort(np.concatenate((t[:,[0,1]],t[:,[1,2]],t[:,[2,0]])),axis=1)
        owners=np.tile(np.arange(len(t)),3)
        opposite=np.concatenate((t[:,2],t[:,0],t[:,1]))
        order=np.lexsort((edges[:,1],edges[:,0]));ordered=edges[order]
        shared=np.flatnonzero(np.all(ordered[1:]==ordered[:-1],axis=1))
        if not len(shared):break
        i,j=order[shared],order[shared+1]
        left,right=owners[i],owners[j]
        a,b=edges[i].T;c,d=opposite[i],opposite[j]
        ab=xy[b]-xy[a];cd=xy[d]-xy[c]
        side_c=cross(ab,xy[c]-xy[a]);side_d=cross(ab,xy[d]-xy[a])
        side_a=cross(cd,xy[a]-xy[c]);side_b=cross(cd,xy[b]-xy[c])
        convex=(side_c*side_d<0)&(side_a*side_b<0)&(regions[left]==regions[right])
        # The sum of opposite cotangents is negative exactly when an interior
        # edge violates the local Delaunay criterion; avoid co-circular flips.
        denominator_c=np.abs(cross(xy[a]-xy[c],xy[b]-xy[c]))
        denominator_d=np.abs(cross(xy[a]-xy[d],xy[b]-xy[d]))
        cot_c=np.sum((xy[a]-xy[c])*(xy[b]-xy[c]),axis=1)/np.maximum(denominator_c,1e-300)
        cot_d=np.sum((xy[a]-xy[d])*(xy[b]-xy[d]),axis=1)/np.maximum(denominator_d,1e-300)
        chosen=np.flatnonzero(convex & (cot_c+cot_d < -1e-10))
        if not len(chosen):break
        first=np.full(len(t),len(chosen),dtype=np.int64);rank=np.arange(len(chosen))
        np.minimum.at(first,left[chosen],rank);np.minimum.at(first,right[chosen],rank)
        chosen=chosen[(first[left[chosen]]==rank)&(first[right[chosen]]==rank)]
        l,r=left[chosen],right[chosen]
        t[l]=np.column_stack((c[chosen],d[chosen],a[chosen]))
        t[r]=np.column_stack((d[chosen],c[chosen],b[chosen]))
    signed=cross(xy[t[:,1]]-xy[t[:,0]],xy[t[:,2]]-xy[t[:,0]])
    t[signed<0]=t[signed<0][:,[0,2,1]]
    return t


def triangulate(polygons, edge_mm, max_cells=400_000, cancelled=None):
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy,numpy_to_vtkIdTypeArray
    edge_mm = float(edge_mm)
    if not math.isfinite(edge_mm) or edge_mm <= 0:
        raise ValueError('Mesh edge length must be positive and finite.')
    if max_cells<1:raise ValueError('No triangle budget remains; increase mesh edge length.')
    polygons=_conforming_contours(polygons,cancelled,maximum_edge=min(edge_mm,.5))
    if sum(len(r) for p in polygons for r in [p['outer'],*p['holes']])>max_cells*2:
        raise ValueError('Contour subdivision exceeds mesh budget. Increase mesh edge length or reduce the net.')
    append = vtk.vtkAppendPolyData()
    expected_area = 0.
    def signed_area(ring):
        return sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(ring,ring[1:]+ring[:1]))/2
    for region_id,polygon in enumerate(polygons):
        if cancelled and cancelled():raise InterruptedError('Meshing cancelled.')
        points=vtk.vtkPoints(); points.SetDataTypeToDouble(); lines=vtk.vtkCellArray();loops=vtk.vtkCellArray()
        for index, ring in enumerate([polygon['outer'],*polygon.get('holes',[])]):
            ring = [list(p[:2]) for p in ring]
            if ring and ring[0] == ring[-1]:ring.pop()
            if len(ring)<3:raise ValueError('A copper contour has fewer than three vertices.')
            area=signed_area(ring)
            expected_area += abs(area)*(1 if index==0 else -1)
            if (area>0) != (index==0):ring.reverse()
            ids=[points.InsertNextPoint(x,y,0.) for x,y in ring]
            loops.InsertNextCell(len(ids))
            for vertex in ids:loops.InsertCellPoint(vertex)
            for a,b in zip(ids,ids[1:]+ids[:1]):
                lines.InsertNextCell(2);lines.InsertCellPoint(a);lines.InsertCellPoint(b)
        poly=vtk.vtkPolyData();poly.SetPoints(points);poly.SetLines(lines)
        # Ear clipping can fail on aligned hole vertices. A rigid rotation
        # changes its numerical tie-breaks without altering any copper boundary.
        # Restore the exact original coordinates and require every contour edge.
        original=vtk_to_numpy(points.GetData()).copy()
        required={tuple(sorted((int(a),int(b)))) for a,b in
                  vtk_to_numpy(lines.GetConnectivityArray()).reshape(-1,2)}
        # Start with constrained Delaunay rather than ear clipping. Ear clipping
        # routinely joins three almost-collinear rounded contour vertices,
        # creating nanometre-altitude slivers and excessive edge subdivision.
        # Delaunay retains every contact/hole boundary while improving angles.
        accepted=None
        constrained=vtk.vtkPolyData();constrained.SetPoints(points);constrained.SetPolys(loops)
        # Give broad planes interior vertices before triangulation. Refining a
        # boundary-only fan spends the budget splitting long skinny diagonals
        # instead of resolving area. The source retains the original boundary
        # indices, so interior seeds cannot relax any contour/contact constraint.
        seeded=vtk.vtkPoints();seeded.SetDataTypeToDouble();seeded.DeepCopy(points)
        low=original[:,:2].min(axis=0);high=original[:,:2].max(axis=0)
        spacing=edge_mm*.7
        grid_shape=np.maximum(0,np.ceil((high-low)/spacing).astype(np.int64)-1)
        if len(original)>1000 and int(grid_shape[0])*int(grid_shape[1]) <= max_cells//2:
            xx,yy=np.meshgrid(low[0]+spacing*np.arange(1,grid_shape[0]+1),
                             low[1]+spacing*np.arange(1,grid_shape[1]+1))
            seeds=np.column_stack((xx.ravel(),yy.ravel()))
            seeds=seeds[contains(seeds,[polygon])]
            if len(seeds):
                from scipy.spatial import cKDTree
                tree=cKDTree(seeds);keep=np.ones(len(seeds),dtype=bool)
                clearance=.15*spacing
                for ring in [polygon['outer'],*polygon.get('holes',[])]:
                    for a,b in zip(np.asarray(ring),np.roll(ring,-1,axis=0)):
                        delta=b-a;length=np.linalg.norm(delta)
                        near=np.asarray(tree.query_ball_point((a+b)/2,length/2+clearance),dtype=np.int64)
                        if not len(near):continue
                        fraction=np.clip((seeds[near]-a)@delta/max(length*length,1e-30),0,1)
                        keep[near[np.linalg.norm(seeds[near]-(a+fraction[:,None]*delta),axis=1)<clearance]]=False
                for x,y in seeds[keep]:seeded.InsertNextPoint(x,y,0.)
        attempts=[seeded,points] if seeded.GetNumberOfPoints()>points.GetNumberOfPoints() else [points]
        for trial_points in attempts:
            if cancelled and cancelled():raise InterruptedError('Meshing cancelled.')
            seeded_poly=vtk.vtkPolyData();seeded_poly.SetPoints(trial_points)
            seeded_original=vtk_to_numpy(trial_points.GetData())
            delaunay=vtk.vtkDelaunay2D();delaunay.SetInputData(seeded_poly);delaunay.SetSourceData(constrained)
            delaunay.SetTolerance(1e-12);delaunay.SetOffset(10);delaunay.Update()
            output=delaunay.GetOutput();cells=output.GetPolys()
            if output.GetNumberOfPoints()!=len(seeded_original) or not np.all(np.diff(vtk_to_numpy(cells.GetOffsetsArray()))==3):continue
            tris=vtk_to_numpy(cells.GetConnectivityArray()).reshape(-1,3)
            first=seeded_original[tris[:,1],:2]-seeded_original[tris[:,0],:2]
            second=seeded_original[tris[:,2],:2]-seeded_original[tris[:,0],:2]
            nondegenerate=not np.any(abs(first[:,0]*second[:,1]-first[:,1]*second[:,0])<1e-16)
            edges=np.sort(np.concatenate((tris[:,[0,1]],tris[:,[1,2]],tris[:,[2,0]])),axis=1)
            unique,counts=np.unique(edges,axis=0,return_counts=True)
            if nondegenerate and contains(seeded_original[tris].mean(axis=1),[polygon]).all() and {tuple(map(int,e)) for e in unique[counts==1]}==required and not np.any(counts>2):
                accepted=vtk.vtkPolyData();accepted.DeepCopy(output);accepted.SetPoints(trial_points);break
        for angle in (0.,.1,.7,1.3):
            if accepted is not None:break
            if cancelled and cancelled():raise InterruptedError('Meshing cancelled.')
            trial=vtk.vtkPolyData();trial.DeepCopy(poly)
            if angle:
                xy=original[:,:2]-original[:,:2].mean(axis=0)
                rotation=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
                xy=xy@rotation
                rotated=vtk.vtkPoints();rotated.SetDataTypeToDouble()
                for x,y in xy:rotated.InsertNextPoint(x,y,0.)
                trial.SetPoints(rotated)
            contour=vtk.vtkContourTriangulator();contour.SetInputData(trial);contour.Update()
            output=contour.GetOutput()
            if contour.GetTriangulationError() or output.GetNumberOfPoints()!=len(original):continue
            cells=output.GetPolys()
            if not np.all(np.diff(vtk_to_numpy(cells.GetOffsetsArray()))==3):continue
            tris=vtk_to_numpy(cells.GetConnectivityArray()).reshape(-1,3)
            first=original[tris[:,1],:2]-original[tris[:,0],:2]
            second=original[tris[:,2],:2]-original[tris[:,0],:2]
            if np.any(abs(first[:,0]*second[:,1]-first[:,1]*second[:,0])<1e-16):continue
            if not contains(original[tris].mean(axis=1),[polygon]).all():continue
            edges=np.sort(np.concatenate((tris[:,[0,1]],tris[:,[1,2]],tris[:,[2,0]])),axis=1)
            unique,counts=np.unique(edges,axis=0,return_counts=True)
            boundary={tuple(map(int,e)) for e in unique[counts==1]}
            if boundary!=required or np.any(counts>2):continue
            accepted=vtk.vtkPolyData();accepted.DeepCopy(output);accepted.SetPoints(points);break
        if accepted is None:
            raise ValueError('Copper triangulation failed to preserve all contour edges. Inspect filled geometry or relax polygon tolerance.')
        region=vtk.vtkIntArray();region.SetName('copper_region')
        region.SetNumberOfTuples(accepted.GetNumberOfCells());region.Fill(region_id)
        accepted.GetCellData().AddArray(region)
        append.AddInputData(accepted)
    append.Update()
    clean=vtk.vtkCleanPolyData();clean.SetInputConnection(append.GetOutputPort())
    clean.ToleranceIsAbsoluteOn();clean.SetAbsoluteTolerance(1e-9);clean.Update()
    triangles=vtk.vtkTriangleFilter();triangles.SetInputConnection(clean.GetOutputPort());triangles.Update()
    poly=triangles.GetOutput()
    if not poly.GetNumberOfPolys():raise ValueError('No filled copper area can be meshed.')
    def arrays(data):
        p=vtk_to_numpy(data.GetPoints().GetData()).copy()
        cells=data.GetPolys()
        offsets=vtk_to_numpy(cells.GetOffsetsArray())
        if not np.all(np.diff(offsets)==3):raise ValueError('Triangulation returned a non-triangle cell.')
        return p,vtk_to_numpy(cells.GetConnectivityArray()).reshape(-1,3).astype(np.int64,copy=True)
    for _ in range(24):
        if cancelled and cancelled():raise InterruptedError('Meshing cancelled.')
        p,t=arrays(poly)
        regions=vtk_to_numpy(poly.GetCellData().GetArray('copper_region'))
        t=_improve_angles(p,t,regions,cancelled=cancelled)
        cells=vtk.vtkCellArray()
        cells.SetData(numpy_to_vtkIdTypeArray(np.arange(0,3*len(t)+1,3,dtype=np.int64),deep=True),
                      numpy_to_vtkIdTypeArray(t.ravel(),deep=True))
        poly.SetPolys(cells)
        if len(t)>max_cells:raise ValueError(f'Mesh exceeds {max_cells:,} triangles. Increase mesh edge length.')
        lengths=np.linalg.norm(p[t]-np.roll(p[t],-1,axis=1),axis=2)
        if float(lengths.max())<=edge_mm*(1+1e-8):break
        # Splitting k edges produces k+1 child triangles. Count requested
        # splits instead of assuming every cell quadruples: that old bound
        # rejected meshes that still fit comfortably within the cell budget.
        predicted=len(t)+int(np.count_nonzero(lengths>edge_mm))
        if predicted>max_cells:
            raise ValueError('Further refinement exceeds the mesh budget. Increase mesh edge length.')
        refine=vtk.vtkAdaptiveSubdivisionFilter();refine.SetInputData(poly)
        refine.SetMaximumEdgeLength(edge_mm);refine.SetMaximumTriangleArea(1e100)
        refine.SetMaximumNumberOfTriangles(2**31-1);refine.SetMaximumNumberOfPasses(1)
        refine.Update();result=vtk.vtkPolyData();result.DeepCopy(refine.GetOutput());poly=result
    else:raise ValueError('Mesh refinement did not converge within 24 passes.')
    a=p[t[:,1],:2]-p[t[:,0],:2];b=p[t[:,2],:2]-p[t[:,0],:2]
    cross=a[:,0]*b[:,1]-a[:,1]*b[:,0]
    if np.any(abs(cross)<1e-16):raise ValueError('Degenerate copper triangle; refine or repair the geometry.')
    actual_area=float(np.sum(abs(cross))/2)
    if not math.isclose(actual_area,expected_area,rel_tol=1e-7,abs_tol=1e-7):
        raise ValueError(f'Mesh area differs from copper area ({actual_area:g} vs {expected_area:g} mm²).')
    if not np.all(contains(p[t].mean(axis=1),polygons)):
        raise ValueError('A triangle crosses outside copper or into a hole.')
    p,t,splits=_split_point_contacts(p,t)
    return p,t,{'area_mm2':actual_area,'maximum_edge_mm':float(lengths.max()),'triangles':len(t),
               'point_contacts_separated':splits}


def build_mesh(geometry, edge_mm=0.5, plating_mm=0.025, max_cells=400_000, cancelled=None):
    if not math.isfinite(plating_mm) or plating_mm<=0:raise ValueError('Via plating thickness must be positive.')
    points=[]; triangles=[]; thickness=[]; layers=[]; offsets={}; reports=[]
    count=0
    for layer in geometry['layers']:
        if not layer.get('polygons'):continue
        p,t,report=triangulate(layer.get('mesh_regions') or layer['polygons'],edge_mm,max_cells-len(triangles),cancelled)
        p[:,2]=float(layer['z_mm']);offsets[str(layer['id'])]=(count,p)
        triangles.extend((t+count).tolist());points.extend(p.tolist());count+=len(p)
        thickness.extend([float(layer['thickness_mm'])]*len(t));layers.extend([layer['id']]*len(t))
        reports.append({'layer':layer['name'],**report})
    if not triangles:raise ValueError('The selected net has no meshed copper.')
    terminal_nodes={}
    for terminal in geometry.get('terminals',[]):
        nodes=[]
        for layer,polygons in terminal.get('polygons',{}).items():
            if str(layer) not in offsets:continue
            offset,p=offsets[str(layer)]
            nodes.extend((np.flatnonzero(contains(p,polygons))+offset).tolist())
        terminal_nodes[terminal['id']]=sorted(set(nodes))
    vias=[]
    z_by_layer={str(l['id']):float(l['z_mm']) for l in geometry['layers']}
    for via in geometry.get('vias',[]):
        contacts=[]
        for layer in via['layers']:
            key=str(layer)
            if key not in offsets:continue
            offset,p=offsets[key]
            polygons=via.get('polygons',{}).get(key)
            if polygons is not None:mask=contains(p,polygons)
            else:
                r=np.hypot(p[:,0]-via['x_mm'],p[:,1]-via['y_mm'])
                mask=(r<=via['diameter_mm']/2+1e-8)&(r>=via['drill_mm']/2-1e-8)
            nodes=(np.flatnonzero(mask)+offset).tolist()
            if nodes:contacts.append((layer,nodes))
        # A barrel may skip layers without copper. Connect only actual contacts;
        # unused stubs carry no DC current and remain in geometry provenance.
        contacts.sort(key=lambda row:z_by_layer[str(row[0])])
        for (a,top),(b,bottom) in zip(contacts,contacts[1:]):
            vias.append({'id':via['id']+f':{a}-{b}','top_nodes':top,'bottom_nodes':bottom,
                         'length_mm':abs(z_by_layer[str(b)]-z_by_layer[str(a)]),
                         'drill_mm':via['drill_mm'],'plating_mm':plating_mm,
                         'x_mm':via['x_mm'],'y_mm':via['y_mm'],'top_layer':a,'bottom_layer':b})
    return {'points_mm':points,'triangles':triangles,'triangle_thickness_mm':thickness,
            'triangle_layer':layers,'vias':vias,'terminal_nodes':terminal_nodes,
            'mesh_report':reports,'geometry':geometry,'edge_mm':edge_mm,'plating_mm':plating_mm}
