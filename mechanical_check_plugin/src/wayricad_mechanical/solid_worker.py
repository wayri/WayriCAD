"""Run with FreeCAD's Python. KiCad alone owns model transforms and STEP export."""
import json
import math
import re
import sys
from pathlib import Path

from .findings import bbox_distance, candidate_pairs, finding, gaps


def analyze(job):
    import FreeCAD as App
    import Import
    import Part
    config, board = job['config'], job['board']
    issues, missing = [], list(board['gaps'])
    doc = App.newDocument('ThreeDvalid')
    Import.insert(job['step'], doc.Name)
    shapes = {}
    pcb = []
    imported = set()
    for obj in doc.Objects:
        # Leaves only: aggregate App::Part Shapes would double count geometry.
        if obj.TypeId != 'PartDesign::Feature' and obj.TypeId != 'Part::Feature':
            continue
        if not hasattr(obj, 'Shape') or obj.Shape.isNull():
            continue
        shape = obj.Shape.copy()
        shape.Placement = obj.getGlobalPlacement()
        match = re.search(r'TDV\d{6}M\d{3}', obj.Label)
        if match and match[0] in board['model_map']:
            imported.add(match[0])
            shapes.setdefault(board['model_map'][match[0]], []).append(shape)
        elif '_PCB' in obj.Label:
            pcb.append(shape)
    for token, ref in board['model_map'].items():
        if token not in imported:
            missing.append(ref + ': model omitted by STEP exporter or importer (' + token + ')')
    by_ref = {c['ref']: c for c in board['components']}
    bodies = []
    for ref, parts in shapes.items():
        shape = Part.makeCompound(parts)
        if not shape.isValid() or not shape.Solids:
            missing.append(ref + ': invalid or non-solid STEP geometry')
            continue
        bodies.append(dict(ref=ref, shape=shape, bounds=box(shape), kind='component', side=by_ref[ref]['side']))
    if not pcb:
        missing.append('Board solid unavailable: board penetration checks skipped')
    for item in config['enclosures']:
        try:
            shape = Part.read(item['path'])
            if shape.isNull() or not shape.Solids or not shape.isValid():
                raise ValueError('No valid solids')
            bodies.append(dict(ref='Enclosure:' + item.get('name', Path(item['path']).stem),
                               shape=shape, bounds=box(shape), kind='enclosure', side='both'))
        except Exception as exc:
            missing.append('Enclosure ' + item['path'] + ': ' + str(exc))
    for enclosure in [b for b in bodies if b['kind']=='enclosure']:
        for i, substrate in enumerate(pcb):
            if bbox_distance(enclosure['bounds'], box(substrate)) > config['clearance_mm']:
                continue
            try:
                distance, points, _ = enclosure['shape'].distToShape(substrate)
                overlap = enclosure['shape'].common(substrate) if distance < 1e-7 else None
                volume = overlap.Volume if overlap is not None else 0
                refs = [enclosure['ref'], 'PCB' + (str(i) if i else '')]
                if volume > config['volume_tolerance_mm3']:
                    issues.append(finding('solid.enclosure_board', refs, 'PCB substrate intersects enclosure',
                                          'Correct the enclosure placement, standoffs or board outline.', measured=volume, unit='mm³',
                                          conflict_mesh=mesh(overlap), conflict_bounds=box(overlap)))
                elif distance < config['clearance_mm'] - 1e-7:
                    issues.append(finding('solid.enclosure_board_clearance', refs, 'Insufficient PCB-to-enclosure clearance',
                                          'Check enclosure wall spacing and board standoff allowances.', measured=distance,
                                          limit=config['clearance_mm'], unit='mm', points=point_list(points)))
            except Exception as exc:
                missing.append(enclosure['ref'] + ': enclosure-to-board check failed: ' + str(exc))
    margin = max(config['clearance_mm'], config['xy_clearance_mm'], config['z_clearance_mm'])
    for a, b in candidate_pairs(bodies, margin):
        try:
            distance, points, _ = a['shape'].distToShape(b['shape'])
            overlap = a['shape'].common(b['shape']) if distance < 1e-7 else None
            volume = overlap.Volume if overlap is not None else 0
            refs = [a['ref'], b['ref']]
            if volume > config['volume_tolerance_mm3']:
                issues.append(finding('solid.collision', refs, 'STEP solids intersect',
                                      'Move a part or correct its model offset; inspect the actual intersecting surfaces.',
                                      measured=volume, limit=config['volume_tolerance_mm3'], unit='mm³',
                                      conflict_mesh=mesh(overlap), conflict_bounds=box(overlap)))
            elif distance < config['clearance_mm'] - 1e-7:
                issues.append(finding('solid.clearance', refs, 'Insufficient 3D surface clearance',
                                      'Increase the distance between these parts.', measured=distance,
                                      limit=config['clearance_mm'], unit='mm', points=point_list(points)))
            # Independent XY/Z policy is a conservative envelope test, never an exact collision.
            gx, gy, gz = gaps(a['bounds'], b['bounds'])
            xy = math.hypot(gx, gy)
            if volume <= config['volume_tolerance_mm3'] and distance >= config['clearance_mm'] and xy < config['xy_clearance_mm'] and gz < config['z_clearance_mm']:
                issues.append(finding('envelope.axis_clearance', refs, 'Horizontal / vertical clearance envelope needs review',
                                      'Check the actual overhang and review separate XY and Z limits.', 'conservative',
                                      severity='warning', measured=round(gz, 6), limit=config['z_clearance_mm'], unit='mm', xy_gap_mm=xy))
        except Exception as exc:
            missing.append('Solid pair ' + a['ref'] + '/' + b['ref'] + ': ' + str(exc))
    thickness = board['thickness']
    for body in bodies:
        if body['kind'] != 'component':
            continue
        ref, bounds, side = body['ref'], body['bounds'], body['side']
        height = max(0, bounds[5] - thickness if side == 'top' else -bounds[2])
        limit = config[side + '_height_mm']
        if height > limit + 1e-7:
            issues.append(finding('height.maximum', [ref], 'Component exceeds ' + side + ' height limit',
                                  'Choose a lower component or revise the enclosure height allowance.', measured=height, limit=limit, unit='mm'))
        for zone in config['height_zones']:
            x0, y0, x1, y1 = zone['bounds']  # KiCad board coordinates, Y down
            if side == zone['side'] and bounds[0] <= x1 and bounds[3] >= x0 and -bounds[4] <= y1 and -bounds[1] >= y0 and height > zone['max_height_mm']:
                issues.append(finding('height.zone', [ref], 'Regional height limit exceeded',
                                      'Check this component against the regional lid or keepout profile.', 'conservative',
                                      measured=height, limit=zone['max_height_mm'], unit='mm', location_key=zone.get('name', str(zone['bounds']))))
        for zone in config['keepouts']:
            z = zone['bounds']  # CAD X/Y/Z, board bottom Z=0
            keepout = Part.makeBox(z[3]-z[0], z[4]-z[1], z[5]-z[2], App.Vector(*z[:3]))
            if bbox_distance(bounds, z) == 0:
                try:
                    overlap = body['shape'].common(keepout)
                    volume = overlap.Volume
                    if volume > config['volume_tolerance_mm3']:
                        issues.append(finding('solid.keepout', [ref], 'Component enters 3D keepout',
                                              'Move the part outside the reserved volume.', measured=volume, unit='mm³', location_key=zone.get('name', str(z)),
                                              conflict_mesh=mesh(overlap), conflict_bounds=box(overlap)))
                except Exception as exc:
                    missing.append(ref + ' keepout: ' + str(exc))
        for board_shape in pcb:
            if bbox_distance(bounds, box(board_shape)) > 0:
                continue
            try:
                overlap = body['shape'].common(board_shape)
                volume = overlap.Volume
                if volume > config['volume_tolerance_mm3']:
                    issues.append(finding('solid.board_penetration', [ref], 'Model intersects PCB substrate',
                                          'Check standoff, underside placement, board cutouts and pin drill alignment.', measured=volume, unit='mm³',
                                          conflict_mesh=mesh(overlap), conflict_bounds=box(overlap)))
            except Exception as exc:
                missing.append(ref + ' board intersection: ' + str(exc))
    hardware_checks(board, config, bodies, issues, missing, App, Part)
    nozzle_checks(board, config, bodies, issues)
    for i, shape in enumerate(pcb):
        bodies.append(dict(ref='PCB' + (str(i) if i else ''), shape=shape, bounds=box(shape), kind='board', side='both'))
    for body in bodies:
        body['mesh'] = mesh(body['shape'])
    result = dict(findings=issues, bodies=[{k: v for k, v in b.items() if k != 'shape'} for b in bodies],
                  coverage=dict(engine='FreeCAD ' + '.'.join(App.Version()[:3]) + ' / Open CASCADE solids',
                                expected_models=len(board['model_map']), imported_models=len(imported),
                                components_with_solids=len([b for b in bodies if b['kind'] == 'component']),
                                gaps=sorted(set(missing)),
                                screening=['XY/Z envelopes', 'pad and pin proximity', 'pick-and-place vertical nozzle access', 'regional height envelopes']))
    App.closeDocument(doc.Name)
    return result


def box(shape):
    b = shape.BoundBox
    return [b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax]


def mesh(shape):
    vertices, triangles = shape.tessellate(0.08)
    return dict(vertices=[[round(v.x, 6), round(v.y, 6), round(v.z, 6)] for v in vertices], faces=[list(t) for t in triangles])


def point_list(points):
    return [[list(p) for p in pair] for pair in points[:1]]


def hardware_checks(board, config, bodies, issues, missing, App, Part):
    hardware_bodies = []
    configured = set(config['mounts'])
    present = {h['ref'] for h in board['mounts']}
    for ref in configured - present:
        missing.append(ref + ': configured mounting hole was not found')
    for hole in board['mounts']:
        ref = hole['ref']
        if ref not in config['mounts']:
            missing.append(ref + ': mounting hardware / plating intent not configured')
            issues.append(finding('mount.intent', [ref], 'Confirm hardware and plating intent',
                                  'Assign required plating and actual screw / washer dimensions in Rules.', 'metadata', severity='warning'))
            solid = Part.makeCylinder(min(hole['drill'])/2, board['thickness'], App.Vector(hole['x'], -hole['y'], 0))
            hardware_bodies.append(dict(ref=ref, shape=solid, bounds=box(solid), kind='hole allowance', side='both'))
            continue
        mount = config['mounts'][ref]
        expected = mount['expected_plating']
        if expected != 'either' and expected != hole['plating']:
            issues.append(finding('mount.plating', [ref], 'Mounting hole is ' + hole['plating'] + '; expected ' + expected,
                                  'Change the footprint pad type, or correct the documented mounting intent.', 'metadata', location_key=hole['number']))
        shaft = mount.get('shaft_diameter_mm', 0)
        if shaft > min(hole['drill']):
            issues.append(finding('mount.shaft_fit', [ref], 'Screw shaft exceeds the finished drill size',
                                  'Use the specified clearance-hole diameter, including manufacturing tolerance.', 'metadata', measured=min(hole['drill']), limit=shaft, unit='mm'))
        radius = max(mount.get('head_diameter_mm', 0), mount.get('washer_diameter_mm', 0)) / 2
        height = mount.get('head_height_mm', 0)
        sides = ('top', 'bottom') if mount.get('side', 'top') == 'both' else (mount.get('side', 'top'),)
        for side in sides:
            z = board['thickness'] if side == 'top' else -height
            if radius > 0 and height > 0:
                solid = Part.makeCylinder(radius, height, App.Vector(hole['x'], -hole['y'], z))
                hardware_bodies.append(dict(ref=ref, shape=solid, bounds=box(solid), kind='hardware envelope', side=side))
                # A full cylinder conservatively encloses the washer/head stack, including the bore.
                for body in bodies:
                    if body['ref'] == ref or bbox_distance(box(solid), body['bounds']) > config['screw_clearance_mm']:
                        continue
                    try:
                        distance, points, _ = solid.distToShape(body['shape'])
                        if distance < config['screw_clearance_mm'] + 1e-7:
                            issues.append(finding('mount.hardware_clearance', [ref, body['ref']], 'Component is inside the screw / washer allowance',
                                                  'Inspect the hardware stack and move the component or select smaller hardware.', 'conservative',
                                                  measured=distance, limit=config['screw_clearance_mm'], unit='mm', severity='warning', location_key=side,
                                                  conflict_mesh=mesh(solid.common(body['shape'])) if distance < 1e-7 else None,
                                                  points=point_list(points)))
                    except Exception as exc:
                        missing.append(ref + ' hardware: ' + str(exc))
            tool_radius = mount.get('tool_radius_mm', 0)
            for body in bodies:
                if tool_radius <= 0 or body['ref'] == ref or body['side'] not in (side, 'both'):
                    continue
                b = body['bounds']
                d = math.hypot(max(b[0]-hole['x'], hole['x']-b[3], 0), max(b[1]+hole['y'], -hole['y']-b[4], 0))
                if d < tool_radius:
                    issues.append(finding('mount.tool_access', [ref, body['ref']], 'Screwdriver access envelope is obstructed',
                                          'Check the driver diameter, insertion direction and assembly sequence.', 'conservative', severity='warning', location_key=side))
            for pad in board['pads']:
                if pad['ref'] == ref or not pad['copper'] or not pad[side]:
                    continue
                # Circumscribed pad circle handles arbitrary rotation and custom pads conservatively.
                clearance = math.hypot(pad['x']-hole['x'], pad['y']-hole['y']) - radius - pad.get('clearance_radius_mm',math.hypot(*pad['size']) / 2)
                if clearance < config['screw_clearance_mm']:
                    issues.append(finding('mount.pad_proximity', [ref, pad['ref']], 'Screw / washer is near pad ' + pad['number'],
                                          'Inspect exposed copper and pin protrusion; allow for washer eccentricity and insulation.', 'conservative', severity='warning',
                                          measured=clearance, limit=config['screw_clearance_mm'], unit='mm', location_key=side + ':' + pad['number']))
    bodies.extend(hardware_bodies)


def nozzle_profile_clash(bounds, side, pickup_z, distance_mm, config):
    """Return the first interfering stepped-nozzle section, if any."""
    travel = config['nozzle_travel_mm']
    setback = config.get('nozzle_head_setback_mm', 0.0)
    sections = (
        ('tip', config['nozzle_radius_mm'], 0.0, setback),
        ('head', config.get('nozzle_head_radius_mm', config['nozzle_radius_mm']), setback, travel),
    )
    for name, radius, low, high in sections:
        if radius <= 0 or high <= low or distance_mm >= radius:
            continue
        overlap = (bounds[5] > pickup_z + low + 1e-6 and bounds[2] < pickup_z + high) if side == 'top' else (
            bounds[2] < pickup_z - low - 1e-6 and bounds[5] > pickup_z - high)
        if overlap:
            return name, radius
    return None


def nozzle_checks(board, config, bodies, issues):
    if config['nozzle_radius_mm'] <= 0 or config['nozzle_travel_mm'] <= 0:
        return
    components = {c['ref']: c for c in board['components']}
    for target in bodies:
        if target['kind'] != 'component' or not components[target['ref']]['smd']:
            continue
        c, b, side = components[target['ref']], target['bounds'], target['side']
        top = b[5] if side == 'top' else b[2]
        for obstacle in bodies:
            if obstacle is target or obstacle['side'] not in (side, 'both'):
                continue
            o = obstacle['bounds']
            distance = math.hypot(max(o[0]-c['x'], c['x']-o[3], 0), max(o[1]+c['y'], -c['y']-o[4], 0))
            clash = nozzle_profile_clash(o, side, top, distance, config)
            if clash:
                section, radius = clash
                issues.append(finding('assembly.nozzle_access', [target['ref'], obstacle['ref']], 'Vertical nozzle access may be blocked for ' + target['ref'],
                                      f'The {section} envelope intersects the obstacle. Confirm pickup point, nozzle geometry and placement order with the assembler.',
                                      'conservative', severity='warning', measured=distance, limit=radius, unit='mm',
                                      nozzle_section=section, location_key=target['ref'] + ':' + section))


if __name__ == '__main__':
    try:
        job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        result = analyze(job)
        Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding='utf-8')
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
