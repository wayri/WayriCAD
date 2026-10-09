"""Supported thermal sample gradients, vendored into each independent plugin."""
from __future__ import annotations
import numpy as np

def _field_values(field):
    """Masked raw samples; unavailable cells never become display temperatures."""
    values=np.ma.masked_invalid(np.asarray([[np.nan if value is None else value for value in row]
                                           for row in field.get('values_c',[])],dtype=float))
    return values


def _cell_edges(field, values):
    """Explicit finite-volume cells have area; arbitrary sampled points do not."""
    if field.get('value_location') != 'finite_volume_cell' or values.ndim != 2:
        return None
    ny, nx = values.shape
    if not nx or not ny:
        return None
    try:
        xs = np.asarray(field.get('x_centers_mm', []), dtype=float)
        ys = np.asarray(field.get('y_centers_mm', []), dtype=float)
        xe = np.asarray(field.get('x_edges_mm', []), dtype=float)
        ye = np.asarray(field.get('y_edges_mm', []), dtype=float)
    except (TypeError, ValueError):
        return None
    for centers, edges, count in ((xs, xe, nx), (ys, ye, ny)):
        if centers.shape != (count,) or edges.shape != (count + 1,):
            return None
        if not np.isfinite(centers).all() or not np.isfinite(edges).all():
            return None
        if not (np.diff(edges) > 0).all():
            return None
        if not ((edges[:-1] < centers) & (centers < edges[1:])).all():
            return None
    return xe, ye


def field_available(field):
    """Known physical cells or a complete quad of supported point samples."""
    if field.get('status')=='unavailable':return False
    values=_field_values(field)
    if _cell_edges(field, values) is not None:
        return bool(values.count())
    if values.ndim!=2 or min(values.shape)<2:return False
    if len(field.get('x_centers_mm',[]))!=values.shape[1] or len(field.get('y_centers_mm',[]))!=values.shape[0]:return False
    valid=~np.ma.getmaskarray(values)
    return bool(np.any(valid[:-1,:-1]&valid[1:,:-1]&valid[:-1,1:]&valid[1:,1:]))

def _draw_field(ax,field,view,norm,offset):
    """Display supported cell areas, smoothing only complete known quads."""
    if not field_available(field):return None
    values=_field_values(field)-offset;ny,nx=values.shape
    valid=~np.ma.getmaskarray(values)
    quads=valid[:-1,:-1]&valid[1:,:-1]&valid[:-1,1:]&valid[1:,1:]
    triangles=[]
    for j,i in zip(*np.nonzero(quads)):
        a=j*nx+i;b=a+1;c=a+nx;d=c+1
        triangles.extend(((a,b,d),(a,d,c)))
    x,y=np.meshgrid(field['x_centers_mm'],field['y_centers_mm'])
    # Gouraud triangle edges acquire dark seams with per-triangle alpha.
    # Render one opaque field beneath the translucent saved PCB geometry.
    meshes=[]
    cell_edges = _cell_edges(field, values)
    if cell_edges is not None:
        # A solved finite-volume value represents this cell, including the
        # outer half-cell beyond its centre. Do not give junction/FE point
        # samples that area or fill unavailable cells. The smooth overlay uses
        # the same raw values and never crosses a missing-sample quad.
        meshes.append(ax.pcolormesh(*cell_edges, values, shading='flat',
                                   norm=norm, cmap='inferno', alpha=1.,
                                   edgecolors='none', linewidth=0, zorder=-1.1))
    if triangles:
        meshes.append(ax.tripcolor(x.ravel(),y.ravel(),np.asarray(triangles),values.ravel(),
                         shading='gouraud',norm=norm,cmap='inferno',alpha=1.,
                         edgecolors='none',linewidth=0,zorder=-1))
    # Clip subcell openings and disjoint board outlines, even if an opening is
    # too small to contain a solver/display sample centre.
    from matplotlib.path import Path as MplPath
    vertices=[];codes=[]
    for shape in view.get('outline',[]):
        for index,ring in enumerate([shape.get('outer_mm',[]),*shape.get('holes_mm',[])]):
            points=[tuple(point[:2]) for point in ring]
            if len(points)<3:continue
            area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))
            if (area>0)!=(index==0):points.reverse()
            vertices.extend([*points,points[0]])
            codes.extend([MplPath.MOVETO,*[MplPath.LINETO]*(len(points)-1),MplPath.CLOSEPOLY])
    if vertices:
        path=MplPath(vertices,codes)
        for mesh in meshes:
            if hasattr(mesh,'set_clip_path'):mesh.set_clip_path(path,ax.transData)
            else:
                for collection in mesh.collections:collection.set_clip_path(path,ax.transData)
    return meshes[-1]



def draw_field(ax, field, outline, norm):
    return _draw_field(ax, field, {"outline": outline}, norm, 0.)
