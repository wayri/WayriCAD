"""Assumption-bearing reconstruction of Ma et al., Micromachines 15 (2024) 728.

Source: https://doi.org/10.3390/mi15060728, Figure 1, Figure 7a and Table 2.
Audited PDF SHA256: cb6ca2f85491d1a0f0b35853f6a29a738f466923bdf40b5601ba5e1a5c1e741e.
This is not the authors' CAD or a validated reproduction of their RF results.
``geometry_spec`` uses only Python's standard library and returns fresh JSON data.
Coordinates are mm, propagation is +X, top copper is Z=0, bottom is Z=-h.
"""
from __future__ import annotations

import math


def geometry_spec():
    """Return source parameters, inferred construction, and viewer solids.

    Table 2's Wi is the feeder width, NOT the equivalent SIW width called Wi
    in equations (2)-(4). Wt is the straight via-row center separation.
    Figure 6c illustrates possible slot types, not a dimensioned slot placement.
    """
    p = dict(W=11.8, Wo=13.0, L1=6.705, L2=21.795, L3=3.980,
             Wi=1.575, Li=3.5, Wt=3.383, Lt=8.405, Wm=2.835, Lm=1.064,
             Wf=1.15, Lf=12.0, P=0.15, Wc=0.192, Lc=5.9, d=0.3, S=0.6)
    h, er, loss = 0.508, 2.55, 0.0014
    mouth = p['L1'] + p['L2']
    length = mouth + p['L3']
    origin = -length / 2
    neck = p['Li'] + p['Lm']
    flare = neck + p['Lt']
    angle = math.radians(15)
    tip_half = p['Wi'] / 2 + p['Lm'] * math.tan(math.radians(21.2))

    def contour(points, z):
        return [[x + origin, y, z] for x, y in points]

    def rectangle(x0, y0, x1, y1, z):
        return contour([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z)

    outline = [(0, -p['Wi'] / 2), (p['Li'], -p['Wi'] / 2),
               (neck, -tip_half), (neck, -p['W'] / 2 + p['Wm']),
               (p['L1'], -p['W'] / 2), (mouth, -p['W'] / 2),
               (mouth, p['W'] / 2), (p['L1'], p['W'] / 2),
               (neck, p['W'] / 2 - p['Wm']), (neck, tip_half),
               (p['Li'], p['Wi'] / 2), (0, p['Wi'] / 2)]
    sheets = []
    belt_margin = (p['L3'] - 3 * p['Wf'] - 2 * p['P']) / 2
    slot_x = neck + p['d'] / 2
    slot_offset = p['Wt'] / 2 - p['d'] - p['Wc'] / 2
    for z, face in ((0.0, 'top'), (-h, 'bottom')):
        holes = [rectangle(slot_x, sign * slot_offset - p['Wc'] / 2,
                           slot_x + p['Lc'], sign * slot_offset + p['Wc'] / 2, z)
                 for sign in (-1, 1)]
        sheets.append(dict(name=face + '_slotted_horn',
                           vertices_mm=contour(outline, z), holes_mm=holes))
        for index in range(3):
            x = mouth + belt_margin + index * (p['Wf'] + p['P'])
            sheets.append(dict(name=f'{face}_belt_{index + 1}',
                               vertices_mm=rectangle(x, -p['Lf'] / 2,
                                                     x + p['Wf'], p['Lf'] / 2, z)))

    # Pitch is arc length along the straight-then-flared row. Do not force an
    # extra endpoint post: that would violate the source pitch/board boundary.
    row_length = p['Lt'] + (mouth - flare) / math.cos(angle)
    vias = []
    for index in range(math.floor(row_length / p['S']) + 1):
        distance = index * p['S']
        flared_distance = max(0.0, distance - p['Lt'])
        x = neck + min(distance, p['Lt']) + flared_distance * math.cos(angle)
        half_width = p['Wt'] / 2 + flared_distance * math.sin(angle)
        for sign in (-1, 1):
            vias.append(dict(x_mm=x + origin, y_mm=sign * half_width,
                             z0_mm=-h, z1_mm=0.0, radius_mm=p['d'] / 2))

    assumptions = [
        'Paper-derived reconstruction, not author CAD; no solved or measured agreement is claimed.',
        'Table 2 segment lengths give 6.705 + 21.795 + 3.980 = 32.48 mm; '
        'the text states 32 mm overall. Segment dimensions take precedence; no rescaling.',
        'Figure 1/Table 2 distinguish W=11.8 mm body, Wo=13 mm output substrate, '
        'Lf=12 mm belt span and Wt=3.383 mm via-row centers. Wi=1.575 mm is '
        'the feeder width, not the equivalent guide width used in equations (2)-(4).',
        'Figure 1 15 degree half-flare is interpreted as the text\'s 30 degree full aperture. '
        'The inferred flare starts at Li+Lm+Lt=12.969 mm, not at L1. '
        'Its extrapolated mouth row span is approximately 11.706 mm, not W or Wo.',
        'Inferred via phase: first center at Li+Lm, 0.6 mm arc-length pitch along each '
        'piecewise row; last center is the last full pitch before the mouth. '
        'Posts are solid PEC cylinders, not continuous walls or hollow plated barrels.',
        'Figure 7a suggests three belts per face. Their 1.15 mm width and 0.15 mm '
        'edge gaps leave inferred 0.115 mm end margins in L3; each 12 mm belt is '
        'centered on the 13 mm output dielectric. No electrical bridges are added.',
        'Inferred slots: two longitudinal 5.9 by 0.192 mm cuts on each face; '
        'start at Li+Lm+d/2, with d/2 clearance from the inner via edge. '
        'Slot count, offsets, face symmetry and endpoint phase are not tabulated.',
        'Inferred metal outline: 21.2 degree feed taper extends Li by Lm; '
        'Wm is the transverse corner cutback at Li+Lm, joined to full W at L1. '
        'Upper and lower patterns are identical as idealized from Figure 7a.',
        'Ideal parallel-strip vertical edge port replaces the underdetermined 50 ohm '
        'microstrip/probe launch. It does not establish 50 ohm characteristic impedance; '
        'connector, probe pads and calibration reference plane are omitted.',
        'Arlon AD255C is homogeneous and nondispersive: er=2.55, tan(delta)=0.0014, '
        'h=0.508 mm. Copper source thickness is 17.5 um and conductivity 5.8e7 S/m; '
        'this builder uses zero-thickness PEC sheets and PEC posts, not copper-loss modeling. '
        'The physical 0.543 mm total thickness is therefore not the solver Z extent.',
        'Rectangular body and wider output dielectric boxes abut at L1+L2; '
        'their step outline is inferred from Figure 1. Slots remove copper only, not dielectric.',
    ]
    return dict(kind='research_solids', unit='mm', source_geometry_kind='paper_siw_horn',
                template_id='ma-2024-siw-horn', doi='10.3390/mi15060728',
                source_parameters_mm=p, copper_thickness_um=17.5,
                copper_conductivity_s_m=5.8e7, board_mm=[length, p['Wo']],
                long_axis='X', bounds_mm=[origin, -p['Wo'] / 2, -h,
                                         -origin, p['Wo'] / 2, 0.0],
                dielectrics=[
                    dict(bounds_mm=[origin, -p['W'] / 2, -h,
                                    mouth + origin, p['W'] / 2, 0.0], er=er, loss_tangent=loss),
                    dict(bounds_mm=[mouth + origin, -p['Wo'] / 2, -h,
                                    -origin, p['Wo'] / 2, 0.0], er=er, loss_tangent=loss)],
                sheets=sheets, vias=vias,
                ports=[[[origin, 0.0, -h], [origin, 0.0, 0.0]]],
                port_width_mm=p['Wi'], assumptions=assumptions)


def build(em, np, c, template):
    """Build and commit real EMerge geometry; return the standard research tuple.

    Only PEC is supported deliberately: the shared finite-sheet boundary path
    must not be applied to volumetric posts as though they were copper sheets.
    Material/board dimensions come from the audited spec, not unrelated defaults.
    """
    from .advanced import ADVANCED_DEFAULTS, assign_conductor
    from .research_geometry import (
        MM, _base_model, _finish, _material, _polygon, _rect,
    )

    advanced = {**ADVANCED_DEFAULTS, **c.get('advanced', {})}
    if advanced['conductor'] != 'pec':
        raise ValueError('Ma SIW horn currently supports PEC sheets/posts only')
    config = {**c, 'advanced': advanced}
    spec = geometry_spec()
    sx, sy = spec['board_mm']
    h = -spec['bounds_mm'][2]
    model, air = _base_model(em, config, sx, sy, h)
    dielectrics=[]
    for dielectric in spec['dielectrics']:
        x0, y0, z0, x1, y1, z1 = dielectric['bounds_mm']
        solid=em.geo.Box((x1 - x0) * MM, (y1 - y0) * MM, (z1 - z0) * MM,
                   position=(x0 * MM, y0 * MM, z0 * MM)).set_material(
                       _material(em, dielectric['er'], dielectric['loss_tangent']))
        dielectrics.append(solid)
    conductors = []
    for sheet in spec['sheets']:
        vertices = sheet['vertices_mm']
        z = vertices[0][2]
        surface = _polygon(em, [(x, y) for x, y, _ in vertices], z)
        for hole in sheet.get('holes_mm', []):
            x0, y0, _ = hole[0]
            x1, y1, _ = hole[2]
            surface = em.geo.remove(surface, _rect(em, x0, y0, x1 - x0, y1 - y0, z))
        conductors.append(assign_conductor(em, surface, config))
    for via in spec['vias']:
        post = em.geo.Cylinder(
            via['radius_mm'] * MM, (via['z1_mm'] - via['z0_mm']) * MM,
            cs=em.GCS.displace(via['x_mm'] * MM, via['y_mm'] * MM, via['z0_mm'] * MM))
        for i, solid in enumerate(dielectrics):
            dielectrics[i]=em.geo.remove(solid,post,remove_tool=False)
        post.properties+=em.VoidAttribute()
        conductors.append(assign_conductor(em, post, config))
    start, stop = spec['ports'][0]
    width = spec['port_width_mm'] * MM
    # +X propagation needs a Y-Z face. The shared microstrip helper spans X-Z
    # and would put half this source outside the board instead of on its edge.
    port = em.geo.Plate(np.asarray([start[0], -spec['port_width_mm']/2, start[2]])*MM,
                        np.asarray([0., spec['port_width_mm']*MM, 0.]),
                        np.asarray([0., 0., (stop[2]-start[2])*MM]))
    assumptions = list(spec['assumptions'])
    if template.get('model_scope'):
        assumptions.insert(0, template['model_scope'])
    _finish(model, config, conductors, [port], [width], [h * MM], [em.ZAX],
            spec, [1 + 0j], 'Ideal parallel-strip edge excitation toward +X', assumptions)
    return model, air, [port], [width], h * MM, [-sx / 2, -sy / 2, sx / 2, sy / 2]
