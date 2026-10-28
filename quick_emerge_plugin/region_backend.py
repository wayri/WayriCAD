"""Reviewed polygon-clipped two-layer copper models for EMerge 3."""
import hashlib
import json
import math

from .region_ports import plan_region
from .advanced import configure_solver, dielectric, assign_conductor, air_region


def region_digest(region):
    return hashlib.sha256(json.dumps(region, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def check_complexity(region):
    shapes = list(region['substrate']['outline'])+list(region['area']['outline'])
    shapes.extend(shape for item in region['copper'] for shape in item['polygons'])
    rings = [ring for shape in shapes for ring in [shape['outer_mm']]+shape.get('holes_mm', [])]
    if sum(map(len, rings)) > 20000 or any(len(ring) > 2000 for ring in rings):
        raise ValueError('Rule-area geometry exceeds the bounded planner (20,000 total / 2,000 per contour vertices). Use a smaller enclosure.')


def qualification_region():
    """Synthetic bare-copper coupon for adapter checks, never board extraction evidence."""
    outline = [{'outer_mm': [[-10, -5], [10, -5], [10, 5], [-10, 5]], 'holes_mm': []}]
    snapshot = dict(schema=1, source={'path': 'synthetic-qualification-coupon', 'sha256': 'synthetic'},
                    area={'id': 'qualification-coupon', 'name': 'Synthetic coupon', 'outline': outline},
                    substrate={'outline': outline, 'thickness_mm': 1.0}, unsupported=[],
                    copper=[dict(layer='F.Cu', net='SIGNAL', source_ids=['synthetic-signal'],
                                 polygons=[{'outer_mm': [[-10, -1], [10, -1], [10, 1], [-10, 1]], 'holes_mm': []}]),
                            dict(layer='B.Cu', net='GND', source_ids=['synthetic-ground'], polygons=outline)])
    return plan_region(snapshot, 'SIGNAL', 'GND')


def validate_region(region, config):
    if not isinstance(region, dict) or region.get('schema') != 1:
        raise ValueError('A reviewed rule-area extraction is required.')
    if region.get('blockers'):
        raise ValueError('Region cannot be simulated: '+'; '.join(region['blockers']))
    if region.get('area', {}).get('id') != config['rule_area_id']:
        raise ValueError('Rule-area selection changed; extract and review it again.')
    check_complexity(region)
    checked = plan_region(region, config['signal_net'], config['reference_net'])
    if checked['blockers']:
        raise ValueError('Region cannot be simulated: '+'; '.join(checked['blockers']))
    if checked['ports'] != region.get('ports'):
        raise ValueError('Region port definitions changed after review.')
    points = [p for shape in region['substrate']['outline'] for p in shape['outer_mm']]
    bounds = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
    return checked, bounds


def _surface(em, shape, z_mm):
    cs = em.GCS.displace(0, 0, z_mm*.001)
    def ring(points):
        return em.geo.XYPolygon([p[0]*.001 for p in points], [p[1]*.001 for p in points], resolution=1e-9).geo(cs=cs)
    surface = ring(shape['outer_mm'])
    for hole in shape.get('holes_mm', []):
        surface = em.geo.remove(surface, ring(hole))
    return surface


def build_region(em, np, config, region):
    region, bbox = validate_region(region, config)
    thickness = region['substrate']['thickness_mm']*.001
    model = em.Simulation('QuickEMergeRuleArea')
    configure_solver(em, model, config)
    material = dielectric(em, config)
    for shape in region['substrate']['outline']:
        surface = _surface(em, shape, 0)
        em.geo.extrude(surface, dz=-thickness).set_material(material)
    conductors = []
    for row in region['copper']:
        z = 0 if row['layer'] == 'F.Cu' else -thickness*1000
        for shape in row['polygons']:
            conductors.append(assign_conductor(em, _surface(em, shape, z), config))
    ports = []
    widths = []
    for port in region['ports']:
        a, b = port['a_mm'], port['b_mm']
        ports.append(em.geo.Plate(np.array([a[0]*.001, a[1]*.001, -thickness]),
                                 np.array([(b[0]-a[0])*.001, (b[1]-a[1])*.001, 0]),
                                 np.array([0, 0, thickness])))
        widths.append(port['width_mm']*.001)
    x0, y0, x1, y1 = [v*.001 for v in bbox]
    model._quick_conductors = conductors
    air = air_region(em, config, x1-x0, y1-y0, thickness, x0, y0)
    model.mw.set_resolution(config['resolution'])
    model.mw.set_frequency_range(config['f_start_hz'], config['f_stop_hz'], config['points'])
    model.commit_geometry()
    for conductor in conductors:
        model.mesher.set_boundary_size(conductor, config['mesh_edge_mm']*.001)
    for port, width in zip(ports, widths):
        model.mesher.set_face_size(port, min(width, thickness)/2)
    return model, air, ports, widths, thickness, bbox
