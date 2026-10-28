"""Convert saved Quick-tool evidence into bounded, data-only Blender scenes.

Coordinates remain millimetres with PCB X/Y and upward Z. Every field is a
per-face value; unknown values remain null. This module never runs a solver,
opens a native editor or invents spatial waveforms from terminal estimates.
"""
from __future__ import annotations

import math
from pathlib import PureWindowsPath

MAX_FACES = 200_000
MAX_VERTICES = 400_000
MAX_VALUES = 5_000_000
MAX_FRAMES = 1_000


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Blender values must be finite numbers or null.')
    return float(value)


def _vector(point):
    if not isinstance(point, (list, tuple)) or len(point) not in (2, 3):
        raise ValueError('A Blender mesh point needs two or three coordinates.')
    values = [_number(v) for v in point]
    if any(v is None for v in values):
        raise ValueError('Mesh coordinates cannot be unknown.')
    return [values[0], values[1], -values[2] if len(values) == 3 else 0.]


def _mesh(name, points, faces, values=None, field_name='', unit='', color=None, properties=None):
    if len(points) > MAX_VERTICES or len(faces) > MAX_FACES:
        raise ValueError('Blender mesh budget exceeded; export a smaller study.')
    obj = {'name': str(name), 'vertices_mm': points, 'faces': faces,
           'color': color or [.07, .45, .32, 1.]}
    if values is not None:
        if len(values) != len(faces):
            raise ValueError('Blender face field length does not match its geometry.')
        obj['field'] = {'name': field_name, 'unit': unit, 'values': values}
    if properties:
        obj['properties'] = properties
    return obj


def _source(bundle):
    request = bundle.get('request') or {}
    geometry = bundle.get('geometry') or {}
    path = bundle.get('board_path') or request.get('board_path') or geometry.get('source_path') or bundle.get('board')
    result = {}
    if path:
        result['board_name'] = PureWindowsPath(str(path)).name
    digest = bundle.get('source_sha256') or bundle.get('board_sha256') or geometry.get('source_sha256')
    if digest:
        result['sha256'] = str(digest)
    fingerprints = bundle.get('source_fingerprints') or {}
    if fingerprints:
        result['files'] = [{'name': PureWindowsPath(str(path)).name, 'sha256': str(value)}
                           for path, value in fingerprints.items() if value]
    return result


def _wall_mesh(name, rings, thickness):
    points, faces = [], []
    for ring in rings:
        if len(ring) < 3:
            continue
        clean = list(ring[:-1] if ring[0] == ring[-1] else ring)
        if len(points) + 2 * len(clean) > MAX_VERTICES or len(faces) + len(clean) > MAX_FACES:
            raise ValueError('Saved board contours exceed the Blender geometry budget.')
        offset = len(points)
        for p in clean:
            xy = _vector(p)
            points.extend([[xy[0], xy[1], 0.], [xy[0], xy[1], -thickness]])
        for i in range(len(clean)):
            j = (i + 1) % len(clean)
            faces.append([offset + 2*i, offset + 2*j, offset + 2*j+1, offset + 2*i+1])
    return _mesh(name, points, faces, color=[.08, .23, .14, 1.]) if faces else None


def _context(bundle, scene):
    """Keep real perimeter/drill walls and clearly labelled part envelopes."""
    view = bundle.get('board_thermal_view') or {}
    if not view:
        scene['notes'].append('Saved board context is absent; only the supplied analysis geometry is exported.')
        return
    thickness = _number(view.get('board_thickness_mm'))
    if thickness is None or thickness <= 0:
        raise ValueError('Board context needs its saved positive thickness.')
    rings = []
    for shape in view.get('outline', []):
        rings.append(shape.get('outer_mm', []))
        rings.extend(shape.get('holes_mm', []))
    rings.extend(row.get('contour_mm', []) for row in view.get('drills', []))
    walls = _wall_mesh('Saved board perimeter and drilled walls', rings, thickness)
    if walls:
        scene['objects'].append(walls)
    scene['notes'].append('Board context shows saved perimeter/cutout/drill walls; it does not fill a bounding rectangle across holes.')
    parts = view.get('components', [])
    if len(parts) > 10_000:
        raise ValueError('Too many component objects for the Blender export budget.')
    thermal = {row['reference']: row for row in (bundle.get('thermal_network') or {}).get('components', [])}
    thermal.update({row['reference']: row for row in (bundle.get('quick_therm') or {}).get('components', []) if row['reference'] not in thermal})
    used_envelope = False
    for part in parts:
        reference = str(part.get('reference', 'Component'))
        solid = (view.get('component_models') or {}).get('components',{}).get(reference)
        solid = solid or part.get('model_3d') or part.get('solid')
        if isinstance(solid, dict) and solid.get('vertices_mm') and solid.get('triangles'):
            # Native STEP display coordinates keep Z, with the front at the
            # positive saved board thickness; scene copper uses front Z=0.
            points = [[_number(p[0]),_number(p[1]),_number(p[2])-thickness] for p in solid['vertices_mm']]
            faces = [list(f) for f in solid['triangles']]
            meaning = 'Saved component mesh'
        else:
            bbox = part.get('bbox_mm')
            if not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = [_number(v) for v in bbox]
            if None in (x0, y0, x1, y1) or x1 <= x0 or y1 <= y0:
                continue
            top = part.get('side', 'top') != 'bottom'
            z0, z1 = (0., .5) if top else (-thickness-.5, -thickness)
            points = [[x, y, z] for z in (z0, z1) for x, y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
            faces = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
            used_envelope = True
            meaning = 'Footprint bounding envelope; illustrative 0.5 mm height, not a package solid'
        row = thermal.get(reference, part)
        value = row.get('component_temperature_c')
        if value is None:
            value = row.get('junction_c', row.get('junction_temperature_c'))
        if value is not None:
            obj = _mesh(reference, points, faces, [_number(value)]*len(faces),
                        str(row.get('temperature_kind') or 'junction estimate'), '°C',
                        properties={'reference': reference, 'geometry_meaning': meaning})
        else:
            obj = _mesh(reference, points, faces, color=[.18,.20,.22,1.],
                        properties={'reference': reference, 'geometry_meaning': meaning})
        transient = (bundle.get('thermal_network') or {}).get('transient') or {}
        definition = next((r for r in transient.get('components',[]) if r.get('reference') == reference),None)
        if definition and transient.get('frames'):
            frames = _component_frames(definition,transient,len(faces))
            obj.setdefault('field',{'name':str(definition.get('temperature_kind') or 'junction estimate'),
                                   'unit':'°C','values':[None]*len(faces)})['frames'] = frames
        scene['objects'].append(obj)
    if used_envelope:
        scene['notes'].append('Parts without saved model triangles use footprint bounding envelopes with illustrative 0.5 mm height; these are not exact component solids.')


def _schedule_scale(points, time, interpolation):
    if not points:
        return 1.
    if time <= points[0][0]:
        return _number(points[0][1])
    for left,right in zip(points,points[1:]):
        if time < right[0]:
            a,b = _number(left[1]),_number(right[1])
            return a if interpolation == 'step' else a+(b-a)*(time-left[0])/(right[0]-left[0])
    return _number(points[-1][1])


def _component_frames(definition,transient,face_count):
    frames = transient['frames']
    if len(frames) > MAX_FRAMES or len(frames)*face_count > MAX_VALUES:
        raise ValueError('Component transient exceeds Blender frame/value budgets.')
    result = []
    for frame in frames:
        temperatures = frame.get('temperatures_c',[])
        storage = definition.get('storage_node')
        value = None
        if storage is not None:
            if not isinstance(storage,int) or not 0 <= storage < len(temperatures):
                raise ValueError('Component transient storage node is missing.')
            value = _number(temperatures[storage])
        elif definition.get('junction_resistance_k_per_w') is not None:
            contact = 0.
            for node,weight in definition.get('nodes',[]):
                if not isinstance(node,int) or not 0 <= node < len(temperatures):
                    raise ValueError('Component transient contact node is missing.')
                temp = _number(temperatures[node])
                if temp is None:
                    contact = None;break
                contact += temp*_number(weight)
            if contact is not None:
                scale = _schedule_scale((transient.get('power_schedules') or {}).get(definition['reference']),
                                        frame['time_s'],transient.get('schedule_interpolation','step'))
                value = contact+_number(definition['power_w'])*scale*_number(definition['junction_resistance_k_per_w'])
        result.append({'time_s':_number(frame['time_s']),'values':[value]*face_count})
    return result


def _pi_values(mesh, result, faces, cell_ids, metric):
    if metric in ('voltage', 'drop'):
        potential = result.get('potential_V', [])
        if len(potential) != len(mesh.get('points_mm', [])):
            raise ValueError('PI result lacks its complete nodal potential field.')
        values = []
        source = _number(result.get('source_voltage_V'))
        for face in faces:
            samples = [_number(potential[i]) for i in face]
            value = None if any(x is None for x in samples) else sum(samples)/len(samples)
            if metric == 'drop' and value is not None:
                if source is None:
                    raise ValueError('PI drop requires the solved source voltage.')
                value = value-source if result.get('physical_return') else source-value
            values.append(value)
        return values, 'Potential' if metric == 'voltage' else 'Voltage drop', 'V'
    key = 'cell_J_A_mm2' if metric == 'density' else 'cell_power_W'
    raw = result.get(key, [])
    total = len(mesh.get('tetrahedra') or mesh.get('triangles', []))
    if len(raw) != total:
        raise ValueError('PI result lacks its complete '+key+' field.')
    values = []
    for index in cell_ids:
        value = raw[index]
        if metric == 'density' and value is not None:
            expected = 3 if mesh.get('tetrahedra') else 2
            if not isinstance(value,(list,tuple)) or len(value) != expected:
                raise ValueError('PI current-density vectors do not match the solved model dimension.')
            parts = [_number(v) for v in value]
            value = None if any(v is None for v in parts) else math.sqrt(sum(v*v for v in parts))
        values.append(_number(value))
    return values, 'Current density' if metric == 'density' else 'Cell dissipated power', 'A/mm²' if metric == 'density' else 'W'


def _pi(bundle, scene, metric, prefix=''):
    mesh = bundle.get('mesh') or {}
    result = bundle.get('result') or {}
    if not mesh or not result:
        raise ValueError('PI Blender export requires a complete solved mesh/result, not a report-reference descriptor.')
    raw_points = mesh.get('points_mm', [])
    if len(raw_points) > MAX_VERTICES:
        raise ValueError('PI vertices exceed the Blender export budget.')
    points = [_vector(p) for p in raw_points]
    tetra = mesh.get('tetrahedra')
    if tetra:
        if len(tetra) > MAX_FACES:
            raise ValueError('PI tetrahedron processing exceeds the Blender export budget.')
        boundary = {}
        for index, cell in enumerate(tetra):
            if len(cell) != 4 or len(set(cell)) != 4 or any(not isinstance(v,int) or not 0 <= v < len(points) for v in cell):
                raise ValueError('Invalid PI tetrahedron connectivity.')
            for local in ((0,2,1),(0,1,3),(1,2,3),(2,0,3)):
                face = [cell[i] for i in local]
                key = tuple(sorted(face))
                if key in boundary:
                    boundary[key] = None
                else:
                    boundary[key] = (face,index)
        entries = [row for row in boundary.values() if row is not None]
        faces, cell_ids = [row[0] for row in entries], [row[1] for row in entries]
        scene['notes'].append('3D PI uses boundary faces of the actual tetrahedral copper mesh; cell power on each boundary face is the adjacent tetrahedron power, not a surface flux.')
    else:
        faces = [list(f) for f in mesh.get('triangles', [])]
        cell_ids = list(range(len(faces)))
    if not faces:
        raise ValueError('PI mesh has no supported solved faces.')
    for face in faces:
        if len(face) != 3 or any(not isinstance(v,int) or not 0 <= v < len(points) for v in face):
            raise ValueError('Invalid PI triangle connectivity.')
    if metric not in ('voltage', 'drop', 'density', 'loss'):
        raise ValueError('PI Blender metric must be voltage, drop, density or loss.')
    values, name, unit = _pi_values(mesh, result, faces, cell_ids, metric)
    net = str((bundle.get('geometry') or {}).get('net', 'Copper'))
    scene['objects'].append(_mesh(prefix+net+' · '+name, points, faces, values, name, unit,
                                 properties={'net':net,'model':str(result.get('model','DC copper'))}))
    scene['notes'].append('PI fields are saved DC values. No spatial transient or AC wave propagation is inferred.')


def _pi_batch(bundle, scene, metric):
    batch = bundle['batch']
    if not batch.get('cases'):
        raise ValueError('PI batch has no complete solved cases to visualize.')
    for case in batch.get('cases', []):
        child = case.get('electrical') or case.get('bundle')
        if not isinstance(child, dict) or not child.get('result'):
            raise ValueError('PI batch contains an unresolved or external case; export its complete solved case JSON.')
        _pi(child, scene, metric, str(case.get('name','Case'))+' · ')
    if batch.get('shared_returns'):
        scene['notes'].append('Shared-return metadata is retained by the source result; only the supplied per-case copper fields are rendered, without a new coupled solve.')


def _thermal_grid(row, layer_index, transient):
    values = row.get('values_c', [])
    xs, ys = row.get('x_edges_mm'), row.get('y_edges_mm')
    if not xs or not ys:
        raise ValueError('Thermal board fields require explicit saved cell edges; interpolated maps are not converted into solved geometry.')
    xs,ys = [_number(x) for x in xs],[_number(y) for y in ys]
    if any(v is None for v in xs+ys) or any(b <= a for edges in (xs,ys) for a,b in zip(edges,edges[1:])):
        raise ValueError('Thermal cell edges must be finite and strictly increasing.')
    if len(values) != len(ys)-1 or any(len(r) != len(xs)-1 for r in values):
        raise ValueError('Thermal grid dimensions do not match its saved edges.')
    points, faces, scalars, cells = [], [], [], []
    z = -(_number(row.get('z_mm')) or 0.)
    for j, line in enumerate(values):
        for i, value in enumerate(line):
            if value is None:
                continue
            if len(faces) >= MAX_FACES or len(points)+4 > MAX_VERTICES:
                raise ValueError('Thermal field exceeds the Blender export budget.')
            offset = len(points)
            points.extend([[_number(xs[i]),_number(ys[j]),z],[_number(xs[i+1]),_number(ys[j]),z],
                           [_number(xs[i+1]),_number(ys[j+1]),z],[_number(xs[i]),_number(ys[j+1]),z]])
            faces.append([offset,offset+1,offset+2,offset+3])
            scalars.append(_number(value)); cells.append((i,j))
    obj = _mesh(str(row.get('name','Board temperature')), points, faces, scalars, 'Board temperature', '°C')
    frames = transient.get('frames') or []
    if frames:
        if len(frames) > MAX_FRAMES or len(frames)*len(faces) > MAX_VALUES:
            raise ValueError('Thermal animation exceeds the Blender scalar-value budget.')
        meta = transient.get('spatial_index') or {}
        lookup = {tuple(cell): index for index,cell in enumerate(meta.get('cells', []))}
        count = meta.get('active_cells_per_layer')
        if not isinstance(count,int) or count != len(lookup):
            raise ValueError('Thermal transient is missing its complete spatial node mapping.')
        indices = []
        for cell in cells:
            if cell not in lookup:
                raise ValueError('Thermal frame mapping omits an exported active cell.')
            indices.append(layer_index*count+lookup[cell])
        converted = []
        previous = -math.inf
        for frame in frames:
            time = _number(frame.get('time_s'))
            temperatures = frame.get('temperatures_c', [])
            if time is None or time < 0 or time <= previous or (indices and max(indices) >= len(temperatures)):
                raise ValueError('Thermal frames need increasing nonnegative times and complete temperatures.')
            previous = time
            converted.append({'time_s':time,'values':[_number(temperatures[i]) for i in indices]})
        obj['field']['frames'] = converted
    return obj


def _therm(bundle, scene, metric):
    if metric not in (None,'temperature'):
        raise ValueError('Thermal Blender metric must be temperature.')
    network = bundle.get('thermal_network') or {}
    layers = network.get('layers') or []
    transient = network.get('transient') or {}
    if layers:
        for index,row in enumerate(layers):
            scene['objects'].append(_thermal_grid(row,index,transient))
        scene['notes'].append('Temperature faces are actual finite-volume cells; subcell drills/copper geometry may remain unresolved exactly as in the source solver. No temperature interpolation is invented.')
    elif network.get('board_field'):
        row = dict(network['board_field'])
        thickness = (bundle.get('board_thermal_view') or {}).get('board_thickness_mm')
        if row.get('z_mm') is None and thickness is not None:
            row['z_mm'] = _number(thickness)/2
        scene['objects'].append(_thermal_grid(row,0,{}))
        scene['notes'].append('Thin-sheet values are one approximate midplane field, not separate top/bottom solutions.')
    elif not (bundle.get('quick_therm') or {}).get('components'):
        raise ValueError('Thermal export needs solved board fields or component results.')
    else:
        scene['notes'].append('Component-only result: no solved spatial board-temperature field exists.')


def _strip(start, end, width, z):
    a, b = _vector(start), _vector(end)
    dx,dy = b[0]-a[0],b[1]-a[1]
    length = math.hypot(dx,dy)
    if not length or width is None or width <= 0:
        return None
    nx,ny = -dy/length*width/2,dx/length*width/2
    return [[a[0]+nx,a[1]+ny,z],[b[0]+nx,b[1]+ny,z],
            [b[0]-nx,b[1]-ny,z],[a[0]-nx,a[1]-ny,z]]


def _si_case(report, path, scene, metric, name, layer_z):
    if metric not in ('impedance','delay','resistance'):
        raise ValueError('SI Blender metric must be impedance, delay or resistance.')
    points,faces,values = [],[],[]
    omitted = 0
    unknown_z = set()
    for segment in path.get('segments', []):
        start,end = segment.get('start_mm'),segment.get('end_mm')
        if not start or not end or segment.get('kind') != 'track' or segment.get('geometry','straight') != 'straight':
            omitted += 1; continue
        layer = str(segment.get('layer','Unknown'))
        if layer not in layer_z:
            unknown_z.add(layer)
        z = _number(layer_z.get(layer,0.))
        vertices = _strip(start,end,_number(segment.get('width_mm')),z)
        if not vertices:
            omitted += 1; continue
        offset = len(points);points.extend(vertices);faces.append([offset+i for i in range(4)])
        key = {'impedance':'impedance_ohm','delay':'screening_delay_ns','resistance':'resistance_ohm'}[metric]
        values.append(_number(segment.get(key)))
    if not faces:
        raise ValueError('SI result contains no supported spatial track geometry; export a complete route report.')
    title,unit = {'impedance':('Resolved section impedance','Ω'),'delay':('Ideal-section screening delay','ns'),
                  'resistance':('Section DC resistance','Ω')}[metric]
    scene['objects'].append(_mesh(name,points,faces,values,title,unit,
                                 properties={'net':str(path.get('net_name','Unknown')),'result_status':str(report.get('status','Unknown'))}))
    if unknown_z:
        scene['notes'].append('SI physical Z missing for '+', '.join(sorted(unknown_z))+': these segments are coplanar at Z=0, not an inferred stackup.')
    if omitted:
        scene['notes'].append(f'{name}: {omitted} non-straight, via, zone or unresolved segments omitted; no geometry or via discontinuity was fabricated.')
    scene['notes'].append('SI colors show section estimates, not a full-wave spatial signal animation. Null impedance/delay remains unavailable.')


def _si(bundle,scene,metric):
    before = len(scene['objects'])
    if bundle.get('cases'):
        for case in bundle['cases']:
            report = case.get('report') or {}
            if not report:
                scene['notes'].append(str(case.get('id','Case'))+': failed/unresolved case has no geometry to export.')
                continue
            _si_case(report,case.get('path_data') or report.get('path') or {},scene,metric,
                     str(case.get('id') or case.get('net') or 'Signal'),bundle.get('blender_layer_z_mm') or {})
    else:
        report = bundle.get('report') or bundle
        path = bundle.get('path_data') or report.get('path') or {}
        _si_case(report,path,scene,metric,str(path.get('net_name','Signal')),bundle.get('blender_layer_z_mm') or {})
    if len(scene['objects']) == before:
        raise ValueError('SI study has no completed supported route geometry to visualize.')


def _transient(bundle,scene):
    result = bundle.get('transient') or bundle
    times = result.get('times_s')
    if not isinstance(times,list) or not times:
        raise ValueError('Transient visualization requires stored sample times.')
    previous = -math.inf
    for time in times:
        value = _number(time)
        if value is None or value < 0 or value < previous:
            raise ValueError('Transient sample times must be finite, nonnegative and nondecreasing.')
        previous = value
    if len(times) != len(set(times)):
        scene['notes'].append('Coincident transient sample times retain event pre/post discontinuities; no artificial time offset or smoothing is applied.')
    rows = result.get('loads') or result.get('components') or []
    for row in rows:
        key,unit = ('voltage_V','V') if 'voltage_V' in row else ('temperature_c','°C')
        values = row.get(key)
        if not isinstance(values,list) or len(values) != len(times):
            raise ValueError('Transient samples and times do not match.')
        scene['traces'].append({'name':str(row.get('reference') or row.get('label') or row.get('id','Load')),
                                'unit':unit,'time_s':[_number(t) for t in times],'values':[_number(v) for v in values]})
    if result.get('source_current_A'):
        scene['traces'].append({'name':'Source current','unit':'A','time_s':[_number(t) for t in times],
                                'values':[_number(v) for v in result['source_current_A']]})
    scene['notes'].append('Lumped transient traces have no spatial positions. They are not painted onto board copper or treated as propagation fields.')


def normalize(bundle, tool='auto', metric=None):
    """Build one data-only scene from saved evidence without recomputing results."""
    if not isinstance(bundle,dict):
        raise ValueError('Blender export input must be a result object.')
    if tool == 'auto':
        if 'quick_therm' in bundle or 'thermal_network' in bundle:
            tool = 'therm'
        elif 'mesh' in bundle or 'batch' in bundle or 'transient' in bundle or 'times_s' in bundle:
            transient = bundle.get('transient') or bundle
            tool = 'therm' if 'components' in transient and 'loads' not in transient else 'pi'
        elif 'path' in bundle or 'cases' in bundle or 'report' in bundle:
            tool = 'si'
        else:
            raise ValueError('Unknown result type; choose a completed PI, SI or thermal result.')
    aliases = {'quick-pi':'pi','quick-si':'si','signal-integrity':'si','quick-therm':'therm','thermal':'therm'}
    tool = aliases.get(tool,tool)
    if tool not in ('pi','si','therm'):
        raise ValueError('Blender tool must be pi, si or therm.')
    scene = {'schema':'wayricad.blender-scene/v1','title':'Quick '+{'pi':'PI','si':'SI','therm':'Therm'}[tool],
             'tool':tool,'source':_source(bundle),'notes':[],'objects':[],'traces':[]}
    if bundle.get('transient') or bundle.get('times_s'):
        _transient(bundle,scene)
    elif tool == 'pi':
        if 'batch' in bundle:
            _pi_batch(bundle,scene,metric or 'voltage')
        else:
            _pi(bundle,scene,metric or 'voltage')
    elif tool == 'si':
        _si(bundle,scene,metric or 'delay')
    else:
        _therm(bundle,scene,metric)
    _context(bundle,scene)
    faces = sum(len(obj['faces']) for obj in scene['objects'])
    vertices = sum(len(obj['vertices_mm']) for obj in scene['objects'])
    count = sum(len(obj.get('field',{}).get('values',[])) +
                sum(len(f['values']) for f in obj.get('field',{}).get('frames',[])) for obj in scene['objects'])
    if faces > MAX_FACES or vertices > MAX_VERTICES or count > MAX_VALUES:
        raise ValueError('Combined scene exceeds Blender export geometry/scalar budgets; reduce the study scope.')
    if not scene['objects'] and not scene['traces']:
        raise ValueError('No supported result geometry or temporal samples available for Blender.')
    scene['notes'] = list(dict.fromkeys(scene['notes']))
    return scene
