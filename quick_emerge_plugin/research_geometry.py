"""Solver-facing geometry for published antenna benchmarks.

Only dimensions explicitly recorded in :mod:`research_antennas` are treated as
source data.  Ideal ports and omitted connector/feed-network details are listed
in each result's assumptions.
"""
from __future__ import annotations

import math

from .advanced import air_region, assign_conductor, configure_solver
from .research_antennas import get_template


MM = 1e-3


def _material(em, er, loss=0.0, color="#268568", opacity=0.35):
    return em.Material(er=er, tand=loss, color=color, opacity=opacity)


def _rect(em, x, y, width, height, z=0.0):
    return em.geo.XYPlate(width * MM, height * MM,
                          position=(x * MM, y * MM, z * MM))


def _polygon(em, points, z=0.0):
    polygon = em.geo.XYPolygon([point[0] * MM for point in points],
                               [point[1] * MM for point in points], resolution=1e-9)
    return polygon.geo(cs=em.GCS.displace(0.0, 0.0, z * MM))


def _add(em, surfaces):
    surfaces = list(surfaces)
    result = surfaces[0]
    for surface in surfaces[1:]:
        result = em.geo.add(result, surface)
    return result


def _vertical_port(em, np, x_mm, y_mm, z0_mm, z1_mm, width_mm=1.0):
    return em.geo.Plate(np.array([(x_mm - width_mm / 2) * MM, y_mm * MM, z0_mm * MM]),
                        np.array([width_mm * MM, 0.0, 0.0]),
                        np.array([0.0, 0.0, (z1_mm - z0_mm) * MM]))


def _base_model(em, config, sx_mm, sy_mm, lower_mm, upper_mm=0.0):
    model = em.Simulation("QuickEMergeResearch")
    configure_solver(em, model, config)
    air = air_region(em, config, sx_mm * MM, sy_mm * MM,
                     lower_mm * MM, -sx_mm * MM / 2, -sy_mm * MM / 2)
    model.mw.set_resolution(config["resolution"])
    model.mw.set_frequency_range(config["f_start_hz"], config["f_stop_hz"], config["points"])
    return model, air


def _finish(model, config, conductors, ports, port_widths, port_heights,
            port_directions, scene, weights, excitation, assumptions):
    model._quick_conductors = conductors
    model._quick_port_heights = port_heights
    model._quick_port_directions = port_directions
    model._quick_scene_geometry = scene
    model._quick_excitation_weights = weights
    model._quick_excitation_description = excitation
    model._quick_research_assumptions = assumptions
    model._quick_shunt = None
    model.commit_geometry()
    edge = config["mesh_edge_mm"] * MM
    for conductor in conductors:
        model.mesher.set_boundary_size(conductor, edge)
    for port, width, height in zip(ports, port_widths, port_heights):
        model.mesher.set_face_size(port, min(width, height, edge))


def _dual_feed_patch(em, np, config, template):
    g = template["geometry"]
    sx, sy = g["board_mm"]
    h, side = g["substrate_height_mm"], g["patch_side_mm"]
    model, air = _base_model(em, config, sx, sy, h)
    em.geo.Box(sx * MM, sy * MM, h * MM,
               position=(-sx * MM / 2, -sy * MM / 2, -h * MM)).set_material(
                   _material(em, g["relative_permittivity"], config["advanced"]["loss_tangent"]))
    patch = assign_conductor(em, _rect(em, -side / 2, -side / 2, side, side), config)
    ground = assign_conductor(em, _rect(em, -sx / 2, -sy / 2, sx, sy, -h), config)
    ports = [_vertical_port(em, np, -side / 2, 0.0, -h, 0.0),
             _vertical_port(em, np, 0.0, -side / 2, -h, 0.0)]
    state = config["advanced"]["research_excitation"]
    weights = {
        "auto": [1 / math.sqrt(2), 1 / math.sqrt(2)],
        "linear": [1 / math.sqrt(2), 1 / math.sqrt(2)],
        "rhcp": [1 / math.sqrt(2), -1j / math.sqrt(2)],
        "lhcp": [1 / math.sqrt(2), 1j / math.sqrt(2)],
    }[state]
    _finish(model, config, [patch, ground], ports, [1 * MM, 1 * MM], [h * MM, h * MM],
            [em.ZAX, em.ZAX], {"kind": g["kind"], "unit": "mm", **g}, weights,
            f"Two orthogonal ideal probes; {'linear' if state == 'auto' else state} coherent excitation",
            [template["model_scope"],
             "Ideal probe feeds replace the published reconfigurable feed network.",
             g["board_extent_provenance"]])
    return model, air, ports, [1 * MM, 1 * MM], h * MM, [-sx / 2, -sy / 2, sx / 2, sy / 2]


def _wlan(em, np, config, template):
    g = template["geometry"]
    sx, sy = g["board_mm"]
    h = g["substrate_height_mm"]
    model, air = _base_model(em, config, sx, sy, h)
    em.geo.Box(sx * MM, sy * MM, h * MM,
               position=(-sx * MM / 2, -sy * MM / 2, -h * MM)).set_material(
                   _material(em, g["relative_permittivity"], config["advanced"]["loss_tangent"]))
    bottom = -sy / 2
    junction = bottom + g["feed_length_mm"]
    l2, l3, l4, l5, l6 = (g[key] for key in ("l2_mm", "l3_mm", "l4_mm", "l5_mm", "l6_mm"))
    parts = [
        _rect(em, -g["feed_width_mm"] / 2, bottom, g["feed_width_mm"], g["feed_length_mm"] + 1),
        _rect(em, -g["l1_mm"] / 2, junction, g["l1_mm"], 1.0),
        _rect(em, -g["l1_mm"] / 2, junction, l3, l2),
        _rect(em, g["l1_mm"] / 2 - l3, junction, l3, l2),
        _rect(em, -l3 / 2, junction, l3, l4),
        _rect(em, -l5 / 2, junction + l4 - l3, l5, l3),
        _rect(em, -l5 / 2, junction + l4 - l6, l3, l6),
        _rect(em, l5 / 2 - l3, junction + l4 - l6, l3, l6),
    ]
    radiator = assign_conductor(em, _add(em, parts), config)
    ground = assign_conductor(em, _rect(em, -sx / 2, bottom, sx, g["partial_ground_length_mm"], -h), config)
    port = _vertical_port(em, np, 0.0, bottom, -h, 0.0, g["feed_width_mm"])
    _finish(model, config, [radiator, ground], [port], [g["feed_width_mm"] * MM], [h * MM],
            [em.ZAX], {"kind": g["kind"], "unit": "mm", **g}, [1 + 0j],
            "Unit-amplitude edge microstrip port",
            [template["model_scope"], "One-millimetre joining bars are inferred from the dimensioned source drawing."])
    return model, air, [port], [g["feed_width_mm"] * MM], h * MM, [-sx / 2, -sy / 2, sx / 2, sy / 2]


def _yagi(em, np, config, template):
    g = template["geometry"]
    sx, sy = g["board_mm"]
    h, w, spacing = g["substrate_height_mm"], g["element_width_mm"], g["element_spacing_mm"]
    model, air = _base_model(em, config, sx, sy, h)
    em.geo.Box(sx * MM, sy * MM, h * MM,
               position=(-sx * MM / 2, -sy * MM / 2, -h * MM)).set_material(
                   _material(em, g["relative_permittivity"], g["loss_tangent"]))
    x0 = g["balun_driven_x_mm"]
    lengths = [g["reflector_length_mm"], g["driven_length_mm"],
               g["director_1_length_mm"], g["director_2_length_mm"]]
    elements = [_rect(em, x0 + index * spacing - w / 2, -length / 2, w, length)
                for index, length in enumerate(lengths)]
    feed = _rect(em, -sx / 2, -g["balanced_feed_width_mm"] / 2,
                 x0 + sx / 2 + spacing, g["balanced_feed_width_mm"])
    half_gap = g["balun_outer_half_gap_mm"]
    upper = _polygon(em, [(-sx / 2 + 1, half_gap), (x0 - w / 2, half_gap),
                          (-sx / 2 + 1, sy / 2 - 1)])
    lower = _polygon(em, [(-sx / 2 + 1, -half_gap), (x0 - w / 2, -half_gap),
                          (-sx / 2 + 1, -sy / 2 + 1)])
    radiator = assign_conductor(em, _add(em, [*elements, feed, upper, lower]), config)
    port = em.geo.Plate(np.array([(-sx / 2 + 2) * MM, -half_gap * MM, 0.0]),
                        np.array([3 * MM, 0.0, 0.0]), np.array([0.0, 1 * MM, 0.0]))
    _finish(model, config, [radiator], [port], [3 * MM], [1 * MM], [em.YAX],
            {"kind": g["kind"], "unit": "mm", **g}, [1 + 0j],
            "Ideal balanced coplanar port across the published one-millimetre balun gap",
            [template["model_scope"], g["balun_geometry_provenance"],
             "The ideal coplanar port does not reproduce the SMA launch or CubeSat chassis."])
    return model, air, [port], [3 * MM], h * MM, [-sx / 2, -sy / 2, sx / 2, sy / 2]


def _truncated_square(em, side, cut, center_x, center_y, z):
    half = side / 2
    return _polygon(em, [(center_x - half, center_y - half), (center_x + half, center_y - half),
                         (center_x + half, center_y + half - cut),
                         (center_x + half - cut, center_y + half),
                         (center_x - half, center_y + half)], z)


def _sx_shared(em, np, config, template):
    g = template["geometry"]
    sx, sy = g["board_mm"]
    h, upper = g["lower_layer_height_mm"], g["upper_layer_height_mm"]
    model, air = _base_model(em, config, sx, sy, h, upper + g["air_gap_mm"] + g["prs_height_mm"])
    loss = config["advanced"]["loss_tangent"]
    em.geo.Box(sx * MM, sy * MM, h * MM,
               position=(-sx * MM / 2, -sy * MM / 2, -h * MM)).set_material(
                   _material(em, g["duroid_5880_er"], loss))
    em.geo.Box(sx * MM, sy * MM, upper * MM,
               position=(-sx * MM / 2, -sy * MM / 2, 0.0)).set_material(
                   _material(em, g["duroid_5880_er"], loss))
    prs_z = upper + g["air_gap_mm"]
    em.geo.Box(sx * MM, sy * MM, g["prs_height_mm"] * MM,
               position=(-sx * MM / 2, -sy * MM / 2, prs_z * MM)).set_material(
                   _material(em, g["duroid_6010_er"], loss, "#5f7bb6", 0.25))
    ground = assign_conductor(em, _rect(em, -sx / 2, -sy / 2, sx, sy, -h), config)
    side, slot, gap = g["s_ring_length_mm"], g["s_slot_length_mm"], g["slot_spacing_mm"]
    # Figure 2 uses paper x downward and paper y right. Solver x is right and
    # solver y is up, so (x,y)=(paper_y,-paper_x). The X patch occupies the
    # lower-left slot; the published probe coordinate is not its center.
    slot_center = -side / 2 + (side - 2 * slot - gap) / 2 + slot / 2
    x_patch_center = (slot_center, slot_center)
    x_patch = assign_conductor(em, _truncated_square(
        em, g["x_patch_length_mm"], g["x_corner_perturbation_mm"],
        x_patch_center[0], x_patch_center[1], 0.0), config)
    s_patch = _truncated_square(em, side, g["s_corner_perturbation_mm"], 0.0, 0.0, upper)
    margin = (side - 2 * slot - gap) / 2
    low = -side / 2 + margin
    for x in (low, low + slot + gap):
        for y in (low, low + slot + gap):
            s_patch = em.geo.remove(s_patch, _rect(em, x, y, slot, slot, upper))
    s_patch = assign_conductor(em, s_patch, config)
    sxy = (g["s_feed_xy_mm"][1], -g["s_feed_xy_mm"][0])
    xxy = (g["x_feed_xy_mm"][1], -g["x_feed_xy_mm"][0])
    ports = [_vertical_port(em, np, sxy[0], sxy[1], -h, upper),
             _vertical_port(em, np, xxy[0], xxy[1], -h, 0.0)]
    state = config["advanced"]["research_excitation"]
    if state == "auto":
        state = "s-band" if (config["f_start_hz"] + config["f_stop_hz"]) / 2 < 5e9 else "x-band"
    weights = [1 + 0j, 0 + 0j] if state == "s-band" else [0 + 0j, 1 + 0j]
    _finish(model, config, [ground, x_patch, s_patch], ports, [1 * MM, 1 * MM],
            [(h + upper) * MM, h * MM], [em.ZAX, em.ZAX],
            {"kind": g["kind"], "unit": "mm", **g}, weights,
            f"Ideal coaxial-probe {state} excitation; the other port is matched",
            [template["model_scope"], g["material_permittivity_provenance"],
             "Dielectric-layer loss tangent uses the reviewed study value; bolts and SMA bodies are omitted."])
    return model, air, ports, [1 * MM, 1 * MM], h * MM, [-sx / 2, -sy / 2, sx / 2, sy / 2]


def build_research_geometry(em, np, config):
    template = get_template(config["advanced"]["research_template"])
    kind = template["geometry"]["kind"]
    if kind == 'paper_siw_dra':
        from .siw_dra_geometry import build
        return build(em, np, config, template)
    if kind == 'paper_siw_horn':
        from .siw_horn_geometry import build
        return build(em, np, config, template)
    builders = {
        "dual_feed_square_patch": _dual_feed_patch,
        "yang_wlan_monopole": _wlan,
        "liu_cubesat_yagi": _yagi,
        "kabir_sx_shared_aperture": _sx_shared,
    }
    try:
        return builders[kind](em, np, config, template)
    except KeyError:
        raise ValueError("research template uses an analytical study, not FEM geometry") from None
