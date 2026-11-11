"""Solver-independent bounds and fallback drawing for audited paper geometries."""
import math


def descriptor(config):
    template = config['advanced']['research_template']
    if template == 'cheh-lin-2023-siw-dra':
        from .siw_dra_geometry import geometry_spec
    elif template == 'ma-2024-siw-horn':
        from .siw_horn_geometry import geometry_spec
    else: return None
    return geometry_spec()


def bounds(scene):
    points=[]
    for solid in scene.get('dielectrics', []):
        b=solid['bounds_mm']; points.extend((b[:3], b[3:]))
    for sheet in scene.get('sheets', []): points.extend(sheet['vertices_mm'])
    if not points: raise ValueError('Paper scene has no source geometry.')
    return tuple(value for i in range(3) for value in (min(p[i] for p in points), max(p[i] for p in points)))


def plot(axes, scene, options):
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    if options.get('show_context', True):
        for solid in scene.get('dielectrics', []):
            x0,y0,z0,x1,y1,z1=solid['bounds_mm']
            vertices=[[(x,y,z) for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]] for z in (z0,z1)]
            vertices.extend([[(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)],
                             [(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)]])
            axes.add_collection3d(Poly3DCollection(vertices,facecolors='#248c85',alpha=.15))
    if options.get('copper', True):
        for sheet in scene.get('sheets', []):
            points=sheet['vertices_mm']
            if sheet.get('holes_mm'):
                # Outline only: filling a polygon across holes would erase slots.
                for ring in [points]+[[[p[0],p[1],points[0][2]] for p in hole] for hole in sheet['holes_mm']]:
                    closed=ring+[ring[0]]
                    axes.plot(*zip(*closed),color='#ad7b2c',linewidth=1)
            else: axes.add_collection3d(Poly3DCollection([points],facecolors='#bb8c3e',alpha=.6))
        for via in scene.get('vias', []):
            r=via['radius_mm']
            for z in (via['z0_mm'], via['z1_mm']):
                angle=[i*math.tau/24 for i in range(25)]
                axes.plot([via['x_mm']+r*math.cos(t) for t in angle],
                          [via['y_mm']+r*math.sin(t) for t in angle], [z]*len(angle),color='#ad7b2c')
    if options.get('ports', True):
        for start,end in scene.get('ports', []): axes.plot(*zip(start,end),color='#d34472',linewidth=3)
    b=bounds(scene)
    axes.set(xlim=b[:2],ylim=b[2:4],zlim=b[4:6])
    axes.set_box_aspect(tuple(max(b[i+1]-b[i],1) for i in (0,2,4)))
