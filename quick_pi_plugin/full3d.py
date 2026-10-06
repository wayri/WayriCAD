"""Opt-in volumetric DC copper conduction for one saved-board net.

Gmsh OCC unions copper sheets and plated annular barrels before producing
linear tetrahedra. The electrical solve is a three-dimensional conductivity
FEM. It does not model dielectric current, AC skin effect, or thermal feedback.
"""
from __future__ import annotations

import math


class VolumeModelError(ValueError):
    """Geometry, electrodes, or a numerical check cannot be represented."""


def _positive(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise VolumeModelError(name + ' must be finite and positive.') from exc
    if not math.isfinite(result) or result <= 0:
        raise VolumeModelError(name + ' must be finite and positive.')
    return result


def _ring_surface(gmsh, polygon, z):
    """Make one planar OCC face; its inner rings remain real copper voids."""
    loops = []
    for ring in [polygon['outer'], *polygon.get('holes', [])]:
        coordinates = [tuple(map(float, point[:2])) for point in ring]
        if coordinates and coordinates[0] == coordinates[-1]:
            coordinates.pop()
        if len(coordinates) < 3:
            raise VolumeModelError('A copper ring has fewer than three vertices.')
        if not all(math.isfinite(v) for point in coordinates for v in point):
            raise VolumeModelError('A copper ring contains nonfinite coordinates.')
        points = [gmsh.model.occ.addPoint(x, y, z) for x, y in coordinates]
        edges = [gmsh.model.occ.addLine(a, b) for a, b in zip(points, points[1:] + points[:1])]
        loops.append(gmsh.model.occ.addCurveLoop(edges))
    return gmsh.model.occ.addPlaneSurface(loops)


def _ring_area(ring):
    return abs(sum(float(a[0])*float(b[1])-float(a[1])*float(b[0])
                   for a,b in zip(ring,ring[1:]+ring[:1]))) / 2


def _polygon_area(polygon):
    return _ring_area(polygon['outer'])-sum(_ring_area(ring) for ring in polygon.get('holes',[]))


def build_volume_mesh(geometry, edge_mm=.25, plating_mm=.025, max_tetrahedra=250_000):
    """Create true copper volumes and a conforming tetrahedral mesh in mm.

    The saved stackup supplies copper midplanes and thickness. Plating is an
    explicit user input, not inferred from the via drill or board stackup.
    All layer polygons and barrels are boolean-unioned, so a barrel cannot
    become a disconnected lumped resistor in this path.
    """
    import numpy as np
    try:
        import gmsh
    except ImportError as exc:
        raise VolumeModelError('Full 3D Quick PI requires the Gmsh Python module in the worker runtime.') from exc
    from .mesh import contains

    edge_mm = _positive(edge_mm, '3D mesh edge length')
    plating_mm = _positive(plating_mm, 'Via plating thickness')
    if not isinstance(max_tetrahedra, int) or not 1 <= max_tetrahedra <= 1_000_000:
        raise VolumeModelError('3D tetrahedron budget must be between 1 and 1,000,000.')
    layers = geometry.get('layers') or []
    if not layers or not geometry.get('terminals'):
        raise VolumeModelError('Full 3D analysis needs copper layers and pad terminals.')
    if geometry.get('vias') and any(via.get('kind') not in ('via', 'plated_pad') for via in geometry['vias']):
        raise VolumeModelError('Only circular plated via and PTH pad barrels are supported in 3D.')
    layer_by_id = {int(row['id']): row for row in layers}
    if len(layer_by_id) != len(layers):
        raise VolumeModelError('Repeated copper layer in the extracted stackup.')
    for row in layers:
        _positive(row['thickness_mm'], 'Copper thickness')
        if not math.isfinite(float(row['z_mm'])):
            raise VolumeModelError('Copper layer Z must be finite.')

    started = False
    try:
        gmsh.initialize()
        started = True
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('Mesh.ElementOrder', 1)
        gmsh.option.setNumber('Mesh.MeshSizeMax', edge_mm)
        gmsh.option.setNumber('Mesh.MeshSizeMin', min(edge_mm, min(float(row['thickness_mm']) for row in layers)))
        gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 0)
        gmsh.option.setNumber('Mesh.MeshSizeExtendFromBoundary', 1)
        gmsh.model.add('quick-pi-3d-copper')
        solids = []
        expected_volume = 0.
        for row in layers:
            thickness = float(row['thickness_mm'])
            z0 = float(row['z_mm']) - thickness / 2
            for polygon in row.get('polygons', []):
                area = _polygon_area(polygon)
                if area <= 0:
                    raise VolumeModelError('A copper polygon has no positive area.')
                expected_volume += area * thickness
                face = _ring_surface(gmsh, polygon, z0)
                extruded = gmsh.model.occ.extrude([(2, face)], 0, 0, thickness)
                solids.extend((dim, tag) for dim, tag in extruded if dim == 3)
        for via in geometry.get('vias', []):
            drill = _positive(via.get('drill_mm'), 'Plated barrel drill')
            x, y = float(via['x_mm']), float(via['y_mm'])
            if not math.isfinite(x) or not math.isfinite(y):
                raise VolumeModelError('Plated barrel center must be finite.')
            span = [layer_by_id[int(i)] for i in via['layers']]
            if len(span) < 2:
                raise VolumeModelError('A 3D plated barrel must span at least two copper layers.')
            outer_radius = drill / 2 + plating_mm
            if any(float(d) / 2 < outer_radius - 1e-9 for d in via.get('diameters_mm', {}).values()):
                raise VolumeModelError('Plating exceeds a barrel land on a copper layer: ' + str(via['id']))
            # Use the exact native drill contour, not a new analytic circle:
            # a cylinder intersects the polygonal drill wall at many slivers.
            contact_rows = via.get('polygons') or {}
            contour_tolerance=max(float(geometry.get('curve_tolerance_mm',.005))*3,drill*.02)
            candidates=[]
            for records in contact_rows.values():
                for polygon in records:
                    for hole in polygon.get('holes',[]):
                        if len(hole)<3:
                            continue
                        center=(sum(float(point[0]) for point in hole)/len(hole),
                                sum(float(point[1]) for point in hole)/len(hole))
                        if math.hypot(center[0]-x,center[1]-y)<=contour_tolerance:
                            candidates.append(hole)
            if not candidates:
                raise VolumeModelError('3D barrel needs its extracted polygonal drill contour: ' + str(via['id']))
            inner=candidates[0]
            if any(abs(_ring_area(hole)-_ring_area(inner))>max(1e-7,_ring_area(inner)*.005)
                   for hole in candidates[1:]):
                raise VolumeModelError('Plated barrel drill contour changes across layers: ' + str(via['id']))
            if len(inner) < 8:
                raise VolumeModelError('3D barrel drill contour is under-resolved: ' + str(via['id']))
            radii=[math.hypot(float(px)-x,float(py)-y) for px,py in inner]
            if min(radii) <= 0 or min(radii)<drill/2-contour_tolerance or max(radii)>drill/2+contour_tolerance:
                raise VolumeModelError('Barrel drill contour conflicts with drill diameter: ' + str(via['id']))
            outer = [[x+(float(px)-x)*(r+plating_mm)/r,
                      y+(float(py)-y)*(r+plating_mm)/r]
                     for (px,py),r in zip(inner,radii)]
            annulus={'outer':outer,'holes':[inner]}
            span.sort(key=lambda row:float(row['z_mm']))
            intervals=[]
            for upper,lower in zip(span,span[1:]):
                top_bottom=float(upper['z_mm'])+float(upper['thickness_mm'])/2
                lower_top=float(lower['z_mm'])-float(lower['thickness_mm'])/2
                if lower_top <= top_bottom:
                    raise VolumeModelError('Plated barrel layers overlap or have no dielectric gap.')
                intervals.append((top_bottom,lower_top))
            for row in span[1:-1]:
                if not contact_rows.get(str(row['id'])):
                    intervals.append((float(row['z_mm'])-float(row['thickness_mm'])/2,
                                      float(row['z_mm'])+float(row['thickness_mm'])/2))
            for z0,z1 in intervals:
                expected_volume += _polygon_area(annulus)*(z1-z0)
                face = _ring_surface(gmsh, annulus, z0)
                solids.extend((dim,tag) for dim,tag in gmsh.model.occ.extrude([(2,face)],0,0,z1-z0) if dim==3)
        if not solids:
            raise VolumeModelError('The selected net has no 3D copper solids.')
        if len(solids) > 1:
            # Fuse overlapping sheet/barrel material into a single manifold.
            # OCC retains disjoint solids as separate volumes in the result.
            gmsh.model.occ.fuse([solids[0]], solids[1:])
        gmsh.model.occ.synchronize()
        gmsh.model.mesh.setSize(gmsh.model.getEntities(0), edge_mm)
        volumes = gmsh.model.getEntities(3)
        if not volumes:
            raise VolumeModelError('Gmsh produced no copper volume.')
        if not math.isfinite(expected_volume) or expected_volume <= 0:
            raise VolumeModelError('Gmsh produced zero copper volume.')
        gmsh.model.mesh.generate(3)
        node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
        points = np.asarray(coordinates, dtype=float).reshape(-1, 3)
        tags = {int(tag): index for index, tag in enumerate(node_tags)}
        tetra = []
        for _, tag in volumes:
            types, _, connectivity = gmsh.model.mesh.getElements(3, tag)
            for element_type, nodes in zip(types, connectivity):
                if int(element_type) != 4:
                    raise VolumeModelError('Only first-order Gmsh tetrahedra are supported.')
                tetra.extend([tags[int(node)] for node in cell] for cell in np.asarray(nodes).reshape(-1, 4))
        if not tetra or len(tetra) > max_tetrahedra or len(points) > 300_000:
            raise VolumeModelError('3D mesh is empty or exceeds its budget; increase the mesh edge or reduce the selected net.')
        tetra = np.asarray(tetra, dtype=np.int64)
        local = points[tetra]
        volumes_mm3 = np.abs(np.linalg.det(local[:, 1:] - local[:, :1])) / 6
        if np.any(volumes_mm3 < 1e-15):
            raise VolumeModelError('Degenerate tetrahedra in the Gmsh copper volume mesh.')
        relative = abs(float(volumes_mm3.sum()) - expected_volume) / expected_volume
        if relative > 1e-4:
            raise VolumeModelError(f'Extracted copper and tetrahedron volume disagree by {relative:.4%} (geometry {expected_volume:.6g}, mesh {volumes_mm3.sum():.6g} mm^3).')
        contacts = {}
        for terminal in geometry['terminals']:
            selected = set()
            for key, polygons in terminal.get('polygons', {}).items():
                row = layer_by_id.get(int(key))
                if row is None or not polygons:
                    continue
                z0 = float(row['z_mm']) - float(row['thickness_mm']) / 2
                z1 = z0 + float(row['thickness_mm'])
                near = np.flatnonzero((points[:, 2] >= z0-1e-6) & (points[:, 2] <= z1+1e-6))
                hits = contains(points[near, :2], polygons)
                selected.update(map(int, near[hits]))
            if selected:
                contacts[str(terminal['id'])] = sorted(selected)
        return {'model': '3D Gmsh copper volume, linear tetrahedra',
                'points_mm': points.tolist(), 'tetrahedra': tetra.tolist(),
                'terminal_nodes': contacts, 'edge_mm': edge_mm, 'plating_mm': plating_mm,
                'copper_volume_mm3': float(volumes_mm3.sum()),
                'volume_relative_error': relative, 'tetrahedron_count': len(tetra),
                'geometry_sha256': geometry.get('geometry_sha256')}
    except Exception as exc:
        if isinstance(exc, (ValueError, InterruptedError)):
            raise
        raise VolumeModelError('Gmsh could not produce a conforming 3D copper mesh: ' + str(exc)) from exc
    finally:
        if started:
            gmsh.finalize()


def solve_volume(mesh, source_nodes, sink_nodes, source_voltage=1., sink_current=1., options=None):
    """Solve ∇·(σ∇V)=0 on tetrahedra with ideal pad electrodes and DC load.

    SI units are used for the tetrahedron stiffness integral. The prescribed
    sink current is the only current source; source electrode potential is the
    reference. Dissipation must agree with I×ΔV within the numerical tolerance.
    """
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.sparse.linalg import splu

    options = dict(options or {})
    permitted = {'resistivity_ohm_m', 'temperature_c', 'temperature_coefficient'}
    if set(options) - permitted:
        raise VolumeModelError('Unsupported 3D solver option: ' + ', '.join(sorted(set(options) - permitted)))
    points = np.asarray(mesh.get('points_mm'), dtype=float)
    cells = np.asarray(mesh.get('tetrahedra'))
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise VolumeModelError('3D mesh points must be finite XYZ coordinates in mm.')
    if cells.ndim != 2 or cells.shape[1] != 4 or not np.issubdtype(cells.dtype, np.integer):
        raise VolumeModelError('3D mesh requires integer linear tetrahedra.')
    if not len(cells) or len(cells) > 1_000_000 or len(points) > 300_000:
        raise VolumeModelError('3D mesh exceeds the validated size budget.')
    if np.any(cells < 0) or np.any(cells >= len(points)) or np.any([len(set(cell)) < 4 for cell in cells]):
        raise VolumeModelError('3D mesh has invalid tetrahedron vertices.')
    current = _positive(sink_current, 'Sink current')
    voltage = float(source_voltage)
    if not math.isfinite(voltage):
        raise VolumeModelError('Source voltage must be finite.')
    temperature = float(options.get('temperature_c', 20.))
    alpha = float(options.get('temperature_coefficient', .00393))
    rho20 = _positive(options.get('resistivity_ohm_m', 1.724e-8), 'Copper resistivity')
    if not math.isfinite(temperature) or not math.isfinite(alpha) or alpha < 0:
        raise VolumeModelError('Copper temperature and coefficient must be finite; coefficient must be nonnegative.')
    rho = _positive(rho20 * (1 + alpha * (temperature - 20)), 'Adjusted copper resistivity')
    sigma = 1. / rho
    def electrode(value, name):
        if not isinstance(value, (list, tuple)) or not value or any(type(i) not in (int, np.int32, np.int64) or not 0 <= i < len(points) for i in value):
            raise VolumeModelError(name + ' has no valid mesh vertices; reduce the mesh edge or choose a larger pad.')
        return sorted(set(map(int, value)))
    source = electrode(source_nodes, 'Source pad')
    sink = electrode(sink_nodes, 'Sink pad')
    if set(source) & set(sink):
        raise VolumeModelError('Source and sink electrode nodes overlap.')
    xyz = points[cells] * 1e-3
    edge = xyz[:, 1:] - xyz[:, :1]
    det = np.linalg.det(edge)
    volumes = np.abs(det) / 6
    if not np.isfinite(volumes).all() or np.any(volumes < 1e-24):
        raise VolumeModelError('3D tetrahedron has zero or nonfinite volume.')
    inverse = np.linalg.inv(edge)
    # Barycentric gradients: local coordinates t = inv(edge)^T (x-x0).
    gradients = np.empty((len(cells), 4, 3))
    gradients[:, 1:, :] = inverse.transpose(0, 2, 1)
    gradients[:, 0, :] = -gradients[:, 1:, :].sum(axis=1)
    stiffness = sigma * volumes[:, None, None] * np.einsum('mik,mjk->mij', gradients, gradients)
    parent = np.arange(len(points))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for contact in (source, sink):
        for node in contact[1:]:
            parent[find(node)] = find(contact[0])
    _, groups = np.unique([find(i) for i in range(len(points))], return_inverse=True)
    src, dst = int(groups[source[0]]), int(groups[sink[0]])
    if src == dst:
        raise VolumeModelError('Source and sink electrodes share one copper contact.')
    mapped = groups[cells]
    matrix = coo_matrix((stiffness.ravel(), (np.repeat(mapped, 4, axis=1).ravel(),
                         np.tile(mapped, (1, 4)).ravel())), shape=(groups.max()+1,)*2).tocsr()
    matrix.sum_duplicates()
    graph = coo_matrix((np.ones(len(cells)*12),
                        (np.concatenate([mapped[:, a] for a in range(4) for b in range(4) if a != b]),
                         np.concatenate([mapped[:, b] for a in range(4) for b in range(4) if a != b]))),
                       shape=matrix.shape).tocsr()
    _, components = connected_components(graph, directed=False)
    active = components == components[src]
    if not active[dst]:
        raise VolumeModelError('Source and sink are disconnected in the 3D copper volume.')
    free = np.flatnonzero(active & (np.arange(len(active)) != src))
    load = np.zeros(len(active))
    load[dst] = -current
    offset = np.zeros(len(active))
    reduced = matrix[free][:, free].tocsc()
    diagonal = reduced.diagonal()
    if not np.isfinite(diagonal).all() or np.any(diagonal <= 0):
        raise VolumeModelError('3D copper stiffness is singular or poorly formed.')
    scale = 1 / np.sqrt(diagonal)
    try:
        factor = splu(reduced.multiply(scale[:, None]).multiply(scale[None, :]).tocsc())
        offset[free] = scale * factor.solve(scale * load[free])
    except RuntimeError as exc:
        raise VolumeModelError('3D copper stiffness is singular; inspect isolated contacts.') from exc
    if not np.isfinite(offset).all():
        raise VolumeModelError('3D DC solve returned nonfinite potentials.')
    reaction = matrix @ offset
    residual = float(np.max(np.abs(reaction[free]-load[free])))
    if residual > max(1e-8, current*1e-6):
        raise VolumeModelError('3D current conservation failed; refine the mesh.')
    field = np.einsum('mi,mij->mj', offset[mapped], gradients)
    j = -sigma * field / 1e6
    cell_power = sigma * np.einsum('mi,mi->m', field, field) * volumes
    active_cell = active[mapped].all(axis=1)
    cell_power[~active_cell] = 0
    drop = float(-offset[dst])
    power = float(cell_power.sum())
    balance = abs(power - current * drop) / max(current * drop, 1e-30)
    if drop <= 0 or balance > 1e-6:
        raise VolumeModelError('3D electrical power balance failed; refine the mesh.')
    valid_j = np.linalg.norm(j[active_cell], axis=1)
    return {'model': '3D linear tetrahedral DC conductivity FEM', 'frequency_dependent': False,
            'potential_V': [float(v) if a else None for v, a in zip(voltage+offset[groups], active[groups])],
            'cell_J_A_mm2': [vector.tolist() if a else None for vector, a in zip(j, active_cell)],
            'cell_power_W': [float(value) if a else None for value, a in zip(cell_power, active_cell)],
            'cell_centroid_mm': points[cells].mean(axis=1).tolist(),
            'cell_volume_mm3': (volumes * 1e9).tolist(),
            'source_voltage_V': voltage, 'sink_voltage_V': voltage-drop,
            'source_current_A': float(reaction[src]), 'sink_current_A': current,
            'voltage_drop_V': drop, 'drop_over_current_ohm': drop/current,
            'total_power_W': power, 'conductor_power_W': power,
            'current_balance_error_A': abs(float(reaction[src])-current),
            'max_nodal_residual_A': residual, 'energy_relative_error': balance,
            'max_current_density_A_mm2': float(valid_j.max()),
            'floating_nodes': int((~active[groups]).sum()),
            'floating_tetrahedra': int((~active_cell).sum()),
            'material': {'resistivity_ohm_m': rho, 'resistivity_at_20C_ohm_m': rho20,
                         'temperature_c': temperature, 'temperature_coefficient': alpha},
            'limitations': ['DC fixed-temperature copper conduction only; no AC skin/proximity effect.',
                            'Ideal equipotential pad electrodes; no source/load/package contact impedance.',
                            'No dielectric leakage, thermal feedback, or component series models.']}
