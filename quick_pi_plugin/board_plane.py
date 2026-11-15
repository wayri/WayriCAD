"""Conservative saved PI sheet-mesh adapter for an explicitly ideal-reference PDN."""
import math


def study_from_mesh(bundle, first_ids, second_ids, parameters):
    mesh=bundle.get('mesh',{})
    triangles=mesh.get('triangles',[])
    barrels=(mesh.get('vias') or mesh.get('geometry',{}).get('vias')
             or bundle.get('geometry',{}).get('vias'))
    if not triangles or len(set(mesh.get('triangle_layer',[])))!=1 or barrels:
        raise ValueError('Planar PDN requires one copper layer and no modelled vias. Multilayer coupling is unsupported.')
    points=mesh.get('points_mm',[])
    if not points or max(point[2] for point in points)-min(point[2] for point in points)>1e-8:
        raise ValueError('Planar PDN requires coplanar copper vertices.')
    thickness=mesh.get('triangle_thickness_mm',[])
    if len(thickness)!=len(triangles) or not thickness or min(thickness)<=0 or not math.isclose(min(thickness),max(thickness),rel_tol=1e-8):
        raise ValueError('Planar PDN requires explicit uniform positive copper thickness.')
    groups=mesh.get('terminal_nodes',{})
    ports=[]
    for name,identifiers in (('P1',first_ids),('P2',second_ids)):
        if not identifiers or any(not groups.get(identifier) for identifier in identifiers):
            raise ValueError('Both selected pad ports must resolve to mesh nodes.')
        nodes=sorted({node for identifier in identifiers for node in groups[identifier]})
        ports.append({'name':name,'nodes':nodes,'weights':[1/len(nodes)]*len(nodes)})
    return {'schema':'wayricad.pi-plane-ports/v1',
            'vertices_mm':[[point[0],point[1]] for point in points],
            'triangles':triangles,'ports':ports,'reference_plane':'ideal',
            'copper_thickness_mm':thickness[0],**parameters}
