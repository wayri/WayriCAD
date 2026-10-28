"""VTK scene primitives from source geometry and original solver samples."""
import math
import vtk
from matplotlib import colormaps
from matplotlib.colors import Normalize, LogNorm
from .inspection import scale_limits
from .model import validate_config


def polygon(shape, z):
    """Triangulate actual outer and hole contours, preserving concave outlines."""
    pts, lines = vtk.vtkPoints(), vtk.vtkCellArray()
    for ring in [shape['outer_mm']] + shape.get('holes_mm', []):
        clean = list(ring)
        if len(clean) > 1 and clean[0] == clean[-1]: clean.pop()
        if len(clean) < 3: continue
        ids = []
        for x, y in clean: ids.append(pts.InsertNextPoint(x, y, z))
        for a, b in zip(ids, ids[1:] + ids[:1]):
            line = vtk.vtkLine(); line.GetPointIds().SetId(0, a); line.GetPointIds().SetId(1, b); lines.InsertNextCell(line)
    source = vtk.vtkPolyData(); source.SetPoints(pts); source.SetLines(lines)
    triangulator = vtk.vtkContourTriangulator(); triangulator.SetInputData(source); triangulator.Update()
    out = vtk.vtkPolyData(); out.DeepCopy(triangulator.GetOutput()); return out


def rectangle(x, y, w, h):
    return {'outer_mm': [(x,y),(x+w,y),(x+w,y+h),(x,y+h)], 'holes_mm': []}


def geometry_parts(config, region=None):
    """Return (category, polygon, z, RGB, opacity) and port line segments."""
    parts, ports = [], []
    if region is not None:
        th = region['substrate']['thickness_mm']
        for shape in region['substrate']['outline']: parts.append(('show_context', shape, -th/2, (.13,.53,.42), .3))
        for row in region['copper']:
            for shape in row['polygons']:
                parts.append(('copper', shape, 0 if row['layer']=='F.Cu' else -th, (.87,.68,.32) if row['layer']=='F.Cu' else (.4,.55,.68), .95))
        for port in region['ports']:
            a,b = port['a_mm'], port['b_mm']; x,y = (a[0]+b[0])/2,(a[1]+b[1])/2
            ports.append(((x,y,-th),(x,y,0)))
    else:
        c = validate_config(config); sx,sy,th = c['substrate_x_mm'],c['substrate_y_mm'],c['thickness_mm']
        base = rectangle(-sx/2,-sy/2,sx,sy)
        parts.extend([('show_context',base,-th/2,(.13,.53,.42),.3),('copper',base,-th,(.72,.54,.27),1)])
        if c['mode']=='patch':
            w,l,f,s,i=(c[k] for k in ('patch_width_mm','patch_length_mm','feed_width_mm','inset_width_mm','inset_length_mm'))
            rects=[rectangle(-w/2,-l/2+i,w,l-i),rectangle(-w/2,-l/2,w/2-f/2-s,i),rectangle(f/2+s,-l/2,w/2-f/2-s,i),rectangle(-f/2,-l/2,f,i)]
            extension=c['advanced']['patch_feed_extension_mm']; offset=c['advanced']['patch_offset_y_mm']
            if extension: rects.append(rectangle(-f/2,-l/2-extension,f,extension))
            rects=[{'outer_mm':[[x,y+offset] for x,y in shape['outer_mm']], 'holes_mm':[]} for shape in rects]
            centers=[(0,-l/2-extension+offset)]
        else:
            l,w=c['line_length_mm'],c['line_width_mm']; rects=[rectangle(-l/2,-w/2,l,w)]; centers=[(-l/2,0),(l/2,0)]
        parts.extend(('copper',shape,0,(.85,.66,.32),1) for shape in rects)
        ports.extend(((x,y,-th),(x,y,0)) for x,y in centers)
    return parts, ports


def colored_grid(x, y, z, values, options, radiation=False):
    """Make scalar-colored quads; any invalid corner removes its entire face."""
    mode=options.get('scale','linear'); flat=[v for row in values for v in row if v is not None and math.isfinite(v) and (mode!='log' or v>0)]
    if not flat: return None, None
    lo,hi=scale_limits(flat,mode,options.get('minimum'),options.get('maximum'))
    norm=(LogNorm if mode=='log' else Normalize)(lo,hi,clip=False); cmap=colormaps[options.get('cmap','viridis' if radiation else 'inferno')]
    points=vtk.vtkPoints(); cells=vtk.vtkCellArray(); colors=vtk.vtkUnsignedCharArray(); colors.SetNumberOfComponents(3); colors.SetName('RGB')
    ny,nx=len(values),len(values[0])
    for j in range(ny):
        for i in range(nx):
            points.InsertNextPoint(float(x[j][i]),float(y[j][i]),float(z[j][i]))
            v=values[j][i]; color=(0,0,0) if v is None or not math.isfinite(v) or (mode=='log' and v<=0) else tuple(int(255*c) for c in cmap(norm(v))[:3])
            colors.InsertNextTuple3(*color)
    for j in range(ny-1):
        for i in range(nx-1):
            indices=[(j,i),(j,i+1),(j+1,i+1),(j+1,i)]
            if any(values[a][b] is None or not math.isfinite(values[a][b]) or (mode=='log' and values[a][b]<=0) for a,b in indices): continue
            quad=vtk.vtkQuad()
            for k,(a,b) in enumerate(indices): quad.GetPointIds().SetId(k,a*nx+b)
            cells.InsertNextCell(quad)
    data=vtk.vtkPolyData(); data.SetPoints(points); data.SetPolys(cells); data.GetPointData().SetScalars(colors)
    return data, (lo,hi,mode,cmap)


def preview_geometry(config):
    """Describe advanced template geometry without importing the solver or STEP."""
    c=validate_config(config); a=c['advanced']; study=a['study']
    if study=='waveguide':
        w,h,l=a['waveguide_width_mm'],a['waveguide_height_mm'],a['waveguide_length_mm']
        return {'kind':'waveguide','unit':'mm','bounds':[-w/2,-h/2,0,w/2,h/2,l]}
    if study=='array':
        nx,ny=a['array_count_x'],a['array_count_y']
        centers=[[(ix-(nx-1)/2)*a['array_pitch_x_mm'],(iy-(ny-1)/2)*a['array_pitch_y_mm']] for iy in range(ny) for ix in range(nx)]
        return {'kind':'patch_array','unit':'mm','centers_mm':centers,'patch_size':[c['patch_width_mm'],c['patch_length_mm']],'substrate_size':[c['substrate_x_mm'],c['substrate_y_mm']],'thickness':c['thickness_mm']}
    if study=='driven' and c['mode']=='pcb_line' and a['line_geometry']=='stripline_via':
        sx,sy,th,l=c['substrate_x_mm'],c['substrate_y_mm'],c['thickness_mm'],c['line_length_mm']
        return {'kind':'stripline_via','unit':'mm','bounds':[-sx/2,-sy/2,-th,sx/2,sy/2,0],'trace_width':c['line_width_mm'],'line_length':l,'layer_z_mm':[-th,-2*th/3,-th/3,0],'via_radius':a['via_radius_mm'],'via_x_mm':[-l/4,l/4]}
    if study=='periodic':
        return {'kind':'periodic_patch','unit':'mm','cell_size':[c['substrate_x_mm'],c['substrate_y_mm']],
                'patch_size':[c['patch_width_mm'],c['patch_length_mm']], 'thickness':c['thickness_mm'],
                'z_bounds':[-c['thickness_mm']-c['air_margin_mm'],c['air_margin_mm']]}
    if study=='scattering':
        if a['step_path']: return {'kind':'step','unit':'mm','bounds':None}
        r=a['scatter_radius_mm']; return {'kind':'sphere','unit':'mm','bounds':[-r,-r,-r,r,r,r],'radius':r}
    if study=='thermal':
        sx,sy,th=c['substrate_x_mm'],c['substrate_y_mm'],c['thickness_mm']
        return {'kind':'thermal_substrate','unit':'mm','bounds':[-sx/2,-sy/2,-th,sx/2,sy/2,0]}
    return None


def triangle_mesh(vertices, triangles):
    """Build the worker-exported bounded STEP tessellation without opening STEP."""
    points=vtk.vtkPoints(); cells=vtk.vtkCellArray()
    for vertex in vertices: points.InsertNextPoint(*vertex)
    for indices in triangles:
        if len(indices)!=3 or any(isinstance(i,bool) or not isinstance(i,int) or i<0 or i>=len(vertices) for i in indices):
            raise ValueError('Invalid STEP triangle index')
        face=vtk.vtkTriangle()
        for i,index in enumerate(indices): face.GetPointIds().SetId(i,index)
        cells.InsertNextCell(face)
    data=vtk.vtkPolyData(); data.SetPoints(points); data.SetPolys(cells); return data


def colored_points(volume, options):
    """Build one VTK vertex per known original sample, without interpolation."""
    mode=options.get('scale','linear'); samples=[]
    xs,ys,zs=volume['x_mm'],volume['y_mm'],volume['z_mm']; values=volume['values']
    if len(xs)*len(ys)*len(zs)>100000: raise ValueError('Volume exceeds 100000 samples')
    if len(values)!=len(zs) or any(len(layer)!=len(ys) or any(len(row)!=len(xs) for row in layer) for layer in values):
        raise ValueError('Volume dimensions do not match axes')
    for iz,z in enumerate(zs):
        for iy,y in enumerate(ys):
            for ix,x in enumerate(xs):
                value=values[iz][iy][ix]
                if value is None: continue
                value=float(value)
                if not math.isfinite(value) or (mode=='log' and value<=0): continue
                samples.append((x,y,z,value))
    if not samples: return None,None
    lo,hi=scale_limits([sample[3] for sample in samples],mode,options.get('minimum'),options.get('maximum'))
    norm=(LogNorm if mode=='log' else Normalize)(lo,hi,clip=False); cmap=colormaps[options.get('cmap','inferno')]
    points=vtk.vtkPoints(); vertices=vtk.vtkCellArray(); colors=vtk.vtkUnsignedCharArray(); colors.SetNumberOfComponents(3); colors.SetName('RGB')
    for x,y,z,value in samples:
        index=points.InsertNextPoint(x,y,z); vertices.InsertNextCell(1); vertices.InsertCellPoint(index)
        colors.InsertNextTuple3(*(int(255*c) for c in cmap(norm(value))[:3]))
    data=vtk.vtkPolyData(); data.SetPoints(points); data.SetVerts(vertices); data.GetPointData().SetScalars(colors)
    return data,(lo,hi,mode,cmap)


def waveguide_walls(descriptor):
    """Four longitudinal quad faces, with both waveguide ports left open."""
    if descriptor.get('unit')!='mm': raise ValueError('Scene geometry must use mm')
    x0,y0,z0,x1,y1,z1=descriptor['bounds']
    return [[(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)],
            [(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)],
            [(x0,y0,z0),(x0,y1,z0),(x0,y1,z1),(x0,y0,z1)],
            [(x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)]]


def face(points):
    pts=vtk.vtkPoints(); polys=vtk.vtkCellArray(); poly=vtk.vtkPolygon(); poly.GetPointIds().SetNumberOfIds(len(points))
    for i,p in enumerate(points): pts.InsertNextPoint(*p); poly.GetPointIds().SetId(i,i)
    polys.InsertNextCell(poly); data=vtk.vtkPolyData(); data.SetPoints(pts); data.SetPolys(polys); return data


def stripline_segments(descriptor):
    """Return trace rectangles on internal conductor levels and via limits in mm."""
    if descriptor.get('unit')!='mm': raise ValueError('Scene geometry must use mm')
    l,w=descriptor['line_length'],descriptor['trace_width']; a,b=descriptor['via_x_mm']; zs=descriptor['layer_z_mm']
    return [(rectangle(-l/2,-w/2,a+l/2,w),zs[1]),(rectangle(a,-w/2,b-a,w),zs[2]),(rectangle(b,-w/2,l/2-b,w),zs[1])], [(x,zs[1],zs[2],descriptor['via_radius']) for x in (a,b)]
