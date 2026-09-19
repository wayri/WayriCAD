"""Independent 2.5D DC copper conduction using linear triangular FEM.

SI units internally. Copper polygons are meshed separately per layer; finite
resistance via barrels join equipotential annular faces. Source and sink node
sets are ideal electrodes. This is neither an AC nor a thermal field solver.
"""
from __future__ import annotations
import math


class SolverError(ValueError):
    """A mesh or electrical boundary condition cannot be solved reliably."""


class _Union:
    def __init__(self, n): self.p = list(range(n))
    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]; i = self.p[i]
        return i
    def merge(self, nodes):
        first = self.find(nodes[0])
        for i in nodes[1:]: self.p[self.find(i)] = first


def solve(mesh, source_nodes, sink_nodes, source_voltage=1.0,
          sink_current=1.0, options=None):
    """Solve a selected net mesh and return JSON-serializable physical results.

    mesh: points_mm[N,3], triangles[M,3], triangle_thickness_mm[M], optional
    triangle_layer[M], vias[{id, top_nodes, bottom_nodes, length_mm, drill_mm,
    plating_mm}]. Each via record is one barrel segment between adjacent layers.
    Optional equipotential_groups joins nodes in ideal conductive contacts.
    Optional lumped_branches[{id,top_nodes,bottom_nodes,resistance_ohm,
    inductance_h}] joins different copper domains through explicit components.
    L stores DC magnetic energy; it contributes no steady-state voltage drop.

    options: resistivity_ohm_m (at 20 C), temperature_c, temperature_coefficient,
    ambient_c, temperature_limit_c, pulse_duration_s, density_kg_m3,
    specific_heat_J_kgK. Defaults describe copper; user parameters are retained
    in the report. Fusing risk is a no-cooling adiabatic temperature-limit screen,
    not a certified fuse-opening current or an electrothermal simulation.
    """
    try:
        import numpy as np
        from scipy.sparse import coo_matrix, triu
        from scipy.sparse.csgraph import connected_components
        from scipy.sparse.linalg import splu, MatrixRankWarning
    except ImportError as exc:
        raise SolverError('Quick PI requires NumPy and SciPy in its native Python runtime.') from exc
    import warnings

    options = dict(options or {})
    unknown = set(options)-{'resistivity_ohm_m','temperature_c','temperature_coefficient',
                           'ambient_c','temperature_limit_c','pulse_duration_s',
                           'density_kg_m3','specific_heat_J_kgK'}
    if unknown: raise SolverError('Unknown solver option: '+', '.join(sorted(unknown)))
    def number(value, name, *, positive=False, nonnegative=False):
        try: value = float(value)
        except (TypeError, ValueError) as exc: raise SolverError(name + ' must be a finite number.') from exc
        if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
            raise SolverError(name + ' is outside its valid range.')
        return value

    source_voltage = number(source_voltage, 'Source voltage')
    sink_current = number(sink_current, 'Sink current', positive=True)
    try:
        points = np.asarray(mesh['points_mm'], dtype=float)
        raw_triangles = np.asarray(mesh['triangles'])
        thickness = np.asarray(mesh['triangle_thickness_mm'], dtype=float)
    except (KeyError, TypeError, ValueError) as exc: raise SolverError('Invalid point, triangle or copper thickness arrays.') from exc
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise SolverError('points_mm must be a finite N by 3 array.')
    n = len(points)
    if not 2 <= n <= 250000: raise SolverError('Mesh requires 2 to 250,000 vertices.')
    if raw_triangles.ndim != 2 or raw_triangles.shape[1] != 3 or not 1 <= len(raw_triangles) <= 500000:
        raise SolverError('triangles must contain 1 to 500,000 vertex triples.')
    if not np.issubdtype(raw_triangles.dtype, np.integer): raise SolverError('Triangle node indices must be integers.')
    triangles = raw_triangles.astype(np.int64)
    if np.any(triangles < 0) or np.any(triangles >= n): raise SolverError('Triangle node index is outside the mesh.')
    m = len(triangles)
    if thickness.shape != (m,) or not np.isfinite(thickness).all() or np.any(thickness <= 0):
        raise SolverError('Each triangle needs a finite positive copper thickness.')
    layers = mesh.get('triangle_layer', [0] * m)
    if len(layers) != m: raise SolverError('Each triangle needs one layer label.')
    layers = [x.item() if isinstance(x, np.generic) else x for x in layers]
    xyz = points[triangles] * 1e-3
    if np.any(np.ptp(xyz[:, :, 2], axis=1) > 1e-9): raise SolverError('Each copper triangle must lie on one XY layer.')
    x, y = xyz[:, :, 0], xyz[:, :, 1]
    area2 = (x[:, 1]-x[:, 0])*(y[:, 2]-y[:, 0]) - (x[:, 2]-x[:, 0])*(y[:, 1]-y[:, 0])
    if np.any(np.abs(area2) < 1e-24): raise SolverError('Degenerate copper triangles must be removed by the mesher.')
    area = np.abs(area2) / 2
    gradients = np.stack((np.stack((y[:, 1]-y[:, 2], y[:, 2]-y[:, 0], y[:, 0]-y[:, 1]), axis=1),
                          np.stack((x[:, 2]-x[:, 1], x[:, 0]-x[:, 2], x[:, 1]-x[:, 0]), axis=1)), axis=2) / area2[:, None, None]
    temperature = number(options.get('temperature_c', 20), 'Copper temperature')
    alpha = number(options.get('temperature_coefficient', 0.00393), 'Temperature coefficient', nonnegative=True)
    rho20 = number(options.get('resistivity_ohm_m', 1.724e-8), 'Copper resistivity', positive=True)
    rho = number(rho20 * (1 + alpha*(temperature-20)), 'Temperature-adjusted resistivity', positive=True)
    sigma = 1 / rho
    thickness_m = thickness * 1e-3
    stiffness = np.einsum('mik,mjk->mij', gradients, gradients) * (sigma * thickness_m * area)[:, None, None]

    def nodes(value, name):
        try: result = list(value)
        except TypeError as exc: raise SolverError(name + ' requires node indices.') from exc
        if not result or any(isinstance(i, (bool, np.bool_)) or not isinstance(i, (int, np.integer)) or not 0 <= i < n for i in result):
            raise SolverError(name + ' requires nonempty valid integer node indices.')
        return sorted(set(int(i) for i in result))

    source_nodes = nodes(source_nodes, 'Source electrode')
    sink_nodes = nodes(sink_nodes, 'Sink electrode')
    union = _Union(n)
    for group in mesh.get('equipotential_groups', []): union.merge(nodes(group, 'Contact group'))
    union.merge(source_nodes); union.merge(sink_nodes)
    via_segments = []
    for index, via in enumerate(mesh.get('vias', [])):
        top = nodes(via.get('top_nodes'), 'Via top face')
        bottom = nodes(via.get('bottom_nodes'), 'Via bottom face')
        length = number(via.get('length_mm'), 'Via length', positive=True)
        drill = number(via.get('drill_mm'), 'Via drill', positive=True)
        plating = number(via.get('plating_mm'), 'Via plating', positive=True)
        union.merge(top); union.merge(bottom)
        barrel_area_mm2 = math.pi * plating * (drill + plating)
        resistance = rho * (length * 1e-3) / (barrel_area_mm2 * 1e-6)
        via_segments.append((via.get('id', str(index)), top[0], bottom[0], resistance, barrel_area_mm2, length))
    branches=[]
    for index,branch in enumerate(mesh.get('lumped_branches', [])):
        top=nodes(branch.get('top_nodes'),'Component first terminal')
        bottom=nodes(branch.get('bottom_nodes'),'Component second terminal')
        resistance=number(branch.get('resistance_ohm',0),'Component resistance',nonnegative=True)
        inductance=number(branch.get('inductance_h',0),'Component inductance',nonnegative=True)
        union.merge(top);union.merge(bottom)
        branches.append((branch.get('id',str(index)),top[0],bottom[0],resistance,inductance))
    # Preserve the contact grouping before ideal DC shorts. It lets us recover
    # unique ideal-inductor currents from Kirchhoff balance on a shorting tree.
    _, pre_groups=np.unique([union.find(i) for i in range(n)],return_inverse=True)
    for _,a,b,resistance,_ in branches:
        if resistance==0:union.merge([a,b])
    _, groups = np.unique([union.find(i) for i in range(n)], return_inverse=True)
    source, sink = int(groups[source_nodes[0]]), int(groups[sink_nodes[0]])
    if source == sink: raise SolverError('Source and sink electrodes overlap or share an ideal contact; choose separate terminals.')
    g = int(groups.max()) + 1
    grouped_triangles = groups[triangles]
    distinct=(grouped_triangles[:,0]!=grouped_triangles[:,1]) & (grouped_triangles[:,0]!=grouped_triangles[:,2]) & (grouped_triangles[:,1]!=grouped_triangles[:,2])
    # Condense ideal electrode contacts before stamping. Adding all nine large
    # entries of a collapsed skinny triangle leaves a rounding-error shunt to
    # ground. An all-equipotential cell contributes exactly zero; a two-node
    # cell contributes one positive conductance from the isolated shape basis.
    ordinary=grouped_triangles[distinct]
    rows = np.repeat(ordinary, 3, axis=1).ravel().tolist()
    cols = np.tile(ordinary, (1, 3)).ravel().tolist()
    values = stiffness[distinct].ravel().tolist()
    for local in range(3):
        other1=(local+1)%3;other2=(local+2)%3
        paired=(grouped_triangles[:,other1]==grouped_triangles[:,other2]) & (grouped_triangles[:,local]!=grouped_triangles[:,other1])
        for index in np.flatnonzero(paired):
            a,b=map(int,(grouped_triangles[index,local],grouped_triangles[index,other1]))
            conductance=float(stiffness[index,local,local])
            rows.extend((a,a,b,b));cols.extend((a,b,a,b));values.extend((conductance,-conductance,-conductance,conductance))
    for _, a, b, resistance, _, _ in via_segments:
        a, b = int(groups[a]), int(groups[b]); conductance = 1 / resistance
        rows.extend((a, a, b, b)); cols.extend((a, b, a, b))
        values.extend((conductance, -conductance, -conductance, conductance))
    for _,a,b,resistance,_ in branches:
        if resistance==0:continue
        a,b=int(groups[a]),int(groups[b]);conductance=1/resistance
        rows.extend((a,a,b,b));cols.extend((a,b,a,b))
        values.extend((conductance,-conductance,-conductance,conductance))
    matrix = coo_matrix((values, (rows, cols)), shape=(g, g)).tocsr()
    matrix.sum_duplicates(); matrix.eliminate_zeros()
    _, components = connected_components(matrix, directed=False)
    active = components == components[source]
    if not active[sink]: raise SolverError('Source and sink are disconnected in the copper/via mesh.')
    free = np.flatnonzero(active & (np.arange(g) != source))
    load = np.zeros(g); load[sink] = -sink_current
    offset = np.zeros(g)  # solve relative to source to avoid voltage cancellation
    upper=triu(matrix,k=1).tocoo()
    def conservative_reaction(voltage):
        # Evaluate edge fluxes from differences in the widest native float. A common
        # potential on a remote copper domain must never become a parasitic
        # shunt through rounding of a large sparse-matrix diagonal.
        extended=np.asarray(voltage,dtype=np.longdouble)
        flux=np.asarray(upper.data,dtype=np.longdouble)*(extended[upper.col]-extended[upper.row])
        result=np.zeros(g,dtype=np.longdouble)
        np.add.at(result,upper.row,flux);np.add.at(result,upper.col,-flux)
        return np.asarray(result,dtype=float)
    refinements=0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', MatrixRankWarning)
            reduced=matrix[free][:,free]
            diagonal=reduced.diagonal()
            if np.any(diagonal<=0):raise SolverError('Copper stiffness has a non-positive diagonal.')
            scale=1/np.sqrt(diagonal)
            factor=splu(reduced.multiply(scale[:,None]).multiply(scale[None,:]).tocsc())
            offset[free]=scale*factor.solve(scale*load[free])
            for _ in range(6):
                error=load[free]-conservative_reaction(offset)[free]
                if np.max(np.abs(error))<=max(1e-12,sink_current*1e-10):break
                offset[free]+=scale*factor.solve(scale*error);refinements+=1
    except (RuntimeError, MatrixRankWarning) as exc: raise SolverError('Singular copper mesh; inspect disconnected or degenerate contacts.') from exc
    if not np.isfinite(offset[free]).all(): raise SolverError('FEM returned non-finite voltages.')
    reaction = conservative_reaction(offset)
    residual = float(np.max(np.abs(reaction[free]-load[free])))
    if residual > max(1e-8, sink_current*1e-6): raise SolverError('FEM current conservation failed; refine or repair the mesh.')
    voltage_offset = offset[groups]
    node_active = active[groups]
    cell_active = node_active[triangles].all(axis=1)
    # The gradient depends on voltage differences, not a common domain offset.
    # This remains accurate for microscopic slivers attached to lumped branches.
    local_voltage=voltage_offset[triangles]
    gradient_v = np.einsum('mi,mij->mj', local_voltage[:,1:]-local_voltage[:,:1], gradients[:,1:,:])
    current_density = -sigma * gradient_v / 1e6  # A/mm2
    sheet_current = current_density * thickness[:, None]  # A/mm
    cell_power = sigma * np.sum(gradient_v**2, axis=1) * thickness_m * area
    cell_power[~cell_active] = 0
    via_results = []
    for identifier, a, b, resistance, barrel_area, length in via_segments:
        connected = bool(node_active[a] and node_active[b])
        current = float((voltage_offset[a]-voltage_offset[b])/resistance) if connected else None
        via_results.append({'id': identifier.item() if isinstance(identifier, np.generic) else identifier, 'current_A': current,
                            'direction': 'top_to_bottom_positive', 'resistance_ohm': resistance,
                            'current_density_A_mm2': abs(current)/barrel_area if connected else None,
                            'power_W': current*current*resistance if connected else None,
                            'volume_mm3': barrel_area*length, 'connected': connected})
    conductor_loss = float(cell_power.sum()) + sum(v['power_W'] or 0 for v in via_results)
    branch_currents={}
    for index,(_,a,b,resistance,_) in enumerate(branches):
        if resistance and node_active[a] and node_active[b]:
            branch_currents[index]=float((voltage_offset[a]-voltage_offset[b])/resistance)
    # Current through a tree of zero-ohm links is unique. A loop of ideal shorts
    # has indeterminate branch currents in DC; do not invent its stored energy.
    if any(resistance==0 for _,_,_,resistance,_ in branches):
        imbalance=np.zeros(int(pre_groups.max())+1)
        element_current=np.einsum('mij,mj->mi',gradients,gradient_v)*(sigma*thickness_m*area)[:,None]
        np.add.at(imbalance,pre_groups[triangles].ravel(),-element_current.ravel())
        for via,(_,a,b,_,_,_) in zip(via_results,via_segments):
            current=via['current_A'] or 0
            imbalance[pre_groups[a]]-=current;imbalance[pre_groups[b]]+=current
        for index,(_,a,b,resistance,_) in enumerate(branches):
            if resistance:
                current=branch_currents.get(index,0)
                imbalance[pre_groups[a]]-=current;imbalance[pre_groups[b]]+=current
        imbalance[pre_groups[source_nodes[0]]]+=float(reaction[source])
        imbalance[pre_groups[sink_nodes[0]]]-=sink_current
        adjacency={}
        for index,(_,a,b,resistance,_) in enumerate(branches):
            if resistance==0 and node_active[a] and node_active[b]:
                a,b=int(pre_groups[a]),int(pre_groups[b])
                adjacency.setdefault(a,[]).append((b,index,1))
                adjacency.setdefault(b,[]).append((a,index,-1))
        seen=set()
        for root in adjacency:
            if root in seen:continue
            order=[];parents={root:None};queue=[root];seen.add(root);edge_ids=set()
            while queue:
                vertex=queue.pop();order.append(vertex)
                for neighbor,index,direction in adjacency[vertex]:
                    edge_ids.add(index)
                    if neighbor not in seen:
                        seen.add(neighbor);parents[neighbor]=(vertex,index,-direction);queue.append(neighbor)
            if len(edge_ids)!=len(order)-1:continue
            for vertex in reversed(order[1:]):
                parent,index,direction=parents[vertex]
                branch_currents[index]=float(imbalance[vertex]*direction)
                imbalance[parent]+=imbalance[vertex]
    component_results=[]
    for index,(identifier,a,b,resistance,inductance) in enumerate(branches):
        connected=bool(node_active[a] and node_active[b]);current=branch_currents.get(index)
        component_results.append({'id':identifier.item() if isinstance(identifier,np.generic) else identifier,
            'connected':connected,'current_A':current,'direction':'top_to_bottom_positive',
            'current_status':'known' if current is not None else 'indeterminate_ideal_short_loop' if connected else 'disconnected',
            'resistance_ohm':resistance,'inductance_h':inductance,
            'voltage_drop_V':float(voltage_offset[a]-voltage_offset[b]) if connected else None,
            'power_W':current*current*resistance if current is not None else 0. if connected and resistance==0 else None,
            'magnetic_energy_J':.5*inductance*current*current if current is not None else None,
            'inductive_voltage_drop_V':0. if connected else None})
    component_loss=sum(c['power_W'] or 0 for c in component_results)
    loss = conductor_loss+component_loss
    drop = float(-offset[sink]); terminal_loss = sink_current * drop
    energy_error = abs(loss-terminal_loss)/max(abs(terminal_loss), 1e-30)
    if drop <= 0 or energy_error > 1e-6: raise SolverError('FEM energy balance failed; inspect mesh conditioning.')

    ambient = number(options.get('ambient_c', temperature), 'Ambient temperature')
    limit = number(options.get('temperature_limit_c', 150), 'Temperature limit')
    if limit <= ambient: raise SolverError('Temperature limit must exceed ambient temperature.')
    density = number(options.get('density_kg_m3', 8960), 'Copper density', positive=True)
    heat = number(options.get('specific_heat_J_kgK', 385), 'Copper specific heat', positive=True)
    duration = options.get('pulse_duration_s')
    if duration is not None: duration = number(duration, 'Pulse duration', positive=True)
    volume_mm3 = area * 1e6 * thickness
    def thermal(power, volume):
        budget = volume * 1e-9 * density * heat * (limit-ambient)
        if power is None: return {'status': 'disconnected', 'energy_budget_J': budget}
        ratio = power*duration/budget if duration is not None else None
        return {'status': ('pulse_duration_required' if ratio is None else
                          'temperature_limit_exceeded_adiabatic' if ratio >= 1 else 'below_adiabatic_limit'),
                'energy_budget_J': budget, 'time_to_limit_s': budget/power if power > 0 else None,
                'energy_ratio': ratio,
                'adiabatic_temperature_c': ambient + power*duration/(volume*1e-9*density*heat) if duration is not None else None}
    cell_thermal = [thermal(float(cell_power[i]) if cell_active[i] else None, float(volume_mm3[i])) for i in range(m)]
    for via in via_results: via['thermal'] = thermal(via['power_W'], via['volume_mm3'])
    valid_j = np.linalg.norm(current_density[cell_active], axis=1)
    potential = source_voltage + voltage_offset
    result = {'model': '2.5D linear triangular DC conductivity FEM', 'frequency_dependent': False,
            'potential_V': [float(v) if a else None for v, a in zip(potential, node_active)],
            'cell_J_A_mm2': [j.tolist() if a else None for j, a in zip(current_density, cell_active)],
            'cell_sheet_current_A_mm': [j.tolist() if a else None for j, a in zip(sheet_current, cell_active)],
            'cell_power_W': [float(p) if a else None for p, a in zip(cell_power, cell_active)],
            'cell_centroid_mm': (points[triangles].mean(axis=1)).tolist(),
            'cell_layer': list(layers), 'cell_thermal': cell_thermal, 'vias': via_results,
            'components':component_results,
            'source_voltage_V': source_voltage, 'sink_voltage_V': source_voltage-drop,
            'source_current_A': float(reaction[source]), 'sink_current_A': sink_current,
            'voltage_drop_V': drop, 'drop_over_current_ohm': drop/sink_current,
            'V_over_I_ohm': source_voltage/sink_current,
            'total_power_W': loss, 'conductor_power_W':conductor_loss,'component_power_W':component_loss,
            'current_balance_error_A': abs(float(reaction[source])-sink_current),
            'max_nodal_residual_A': residual, 'energy_relative_error': energy_error,
            'iterative_refinement_steps':refinements,
            'flux_precision_bits':int(np.finfo(np.longdouble).nmant+1),
            'max_current_density_A_mm2': float(valid_j.max()),
            'floating_nodes': int((~node_active).sum()), 'floating_triangles': int((~cell_active).sum()),
            'negative_sink_voltage': bool(source_voltage-drop < 0),
            'material': {'resistivity_ohm_m': rho, 'resistivity_at_20C_ohm_m': rho20,
                         'temperature_c': temperature, 'temperature_coefficient': alpha},
            'thermal_assumptions': {'model': 'adiabatic constant-property temperature-limit screen',
                'ambient_c': ambient, 'temperature_limit_c': limit, 'pulse_duration_s': duration,
                'density_kg_m3': density, 'specific_heat_J_kgK': heat,
                'notice': 'No cooling, heat spreading, temperature feedback, melting or fuse-opening simulation. Not a fusing-current certification.'}}
    from .analytics import summarize
    result['analytics'] = summarize(mesh,result)
    result['planar_power_W'] = result['analytics']['losses']['planar_W']
    result['via_power_W'] = result['analytics']['losses']['via_W']
    return result
