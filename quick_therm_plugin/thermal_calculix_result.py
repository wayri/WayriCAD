"""Import a completed ASCII CalculiX heat-transfer result onto the board.

Only the final complete NDTEMP block is accepted. The field is sampled from the
same Gmsh triangles and extruded node numbering that produced the input deck;
temperature outside those triangles stays unknown. Package junction estimates
need a separately declared junction-to-board resistance.
"""
from __future__ import annotations

import math
from pathlib import Path

from .thermal_calculix import read_msh2


def read_frd_temperatures(path):
    """Read the last complete ASCII NDTEMP scalar block from a CalculiX FRD."""
    temperatures = None
    current = None
    in_temperature = False
    for line in Path(path).read_text(encoding="ascii", errors="strict").splitlines():
        if line.lstrip().startswith("100CL"):
            in_temperature = False
            current = None
        if line[1:3] == "-4" and line[5:11].strip() == "NDTEMP":
            in_temperature = True
            current = {}
            continue
        if not in_temperature:
            continue
        if line[1:3] == "-1":
            try:
                node = int(line[4:13])
                value = float(line[13:25].replace("D", "E"))
            except ValueError as exc:
                raise ValueError("Malformed CalculiX NDTEMP node record.") from exc
            if node <= 0 or not math.isfinite(value) or value < -273.15:
                raise ValueError("CalculiX returned an invalid node temperature.")
            if node in current:
                raise ValueError("CalculiX returned a duplicate temperature node.")
            current[node] = value
        elif line[1:3] == "-3":
            if current:
                temperatures = current
            in_temperature = False
            current = None
    if in_temperature:
        raise ValueError("CalculiX FRD ends inside an incomplete NDTEMP block.")
    if not temperatures:
        raise ValueError("CalculiX FRD has no complete ASCII NDTEMP result.")
    return temperatures


def _sample_surface(nodes, triangles, values, step_mm):
    """Project nodal values onto a bounded regular display grid without filling holes."""
    import numpy as np
    from matplotlib.tri import Triangulation

    ordered = sorted(nodes)
    points = np.asarray([nodes[node] for node in ordered], dtype=float)
    index = {node: i for i, node in enumerate(ordered)}
    cells = np.asarray([[index[node] for node in triangle] for triangle in triangles], dtype=int)
    extent = points.max(axis=0) - points.min(axis=0)
    shape = [max(3, math.ceil(float(length) / step_mm)) for length in extent]
    if shape[0] * shape[1] > 120_000:
        raise ValueError("CalculiX display grid exceeds 120,000 cells; increase display_grid_mm.")
    edges = [np.linspace(points[:, axis].min(), points[:, axis].max(), shape[axis] + 1)
             for axis in (0, 1)]
    centers = [(axis[:-1] + axis[1:]) / 2 for axis in edges]
    xx, yy = np.meshgrid(*centers)
    finder = Triangulation(points[:, 0], points[:, 1], cells).get_trifinder()
    owners = finder(xx.ravel(), yy.ravel())
    result = np.full(len(owners), np.nan)
    inside = owners >= 0
    selected = cells[owners[inside]]
    a, b, c = points[selected[:, 0]], points[selected[:, 1]], points[selected[:, 2]]
    query = np.column_stack((xx.ravel()[inside], yy.ravel()[inside]))
    denominator = (b[:, 0]-a[:, 0])*(c[:, 1]-a[:, 1])-(c[:, 0]-a[:, 0])*(b[:, 1]-a[:, 1])
    if np.any(np.abs(denominator) < 1e-14):
        raise ValueError("CalculiX display mesh contains a degenerate triangle.")
    u = ((query[:, 0]-a[:, 0])*(c[:, 1]-a[:, 1])-
         (c[:, 0]-a[:, 0])*(query[:, 1]-a[:, 1]))/denominator
    v = ((b[:, 0]-a[:, 0])*(query[:, 1]-a[:, 1])-
         (query[:, 0]-a[:, 0])*(b[:, 1]-a[:, 1]))/denominator
    values = np.asarray([values[node] for node in ordered], dtype=float)
    result[inside] = ((1-u-v)*values[selected[:, 0]] +
                      u*values[selected[:, 1]] + v*values[selected[:, 2]])
    matrix = result.reshape(len(centers[1]), len(centers[0]))
    finite = matrix[np.isfinite(matrix)]
    if not len(finite):
        raise ValueError("CalculiX display grid has no board samples.")
    return {"x_centers_mm": centers[0].tolist(), "y_centers_mm": centers[1].tolist(),
            "x_edges_mm": edges[0].tolist(), "y_edges_mm": edges[1].tolist(),
            "values_c": [[None if not math.isfinite(value) else float(value) for value in row]
                         for row in matrix],
            "sampled_min_c": float(finite.min()), "sampled_max_c": float(finite.max()),
            "status": "available"}


def import_calculix_field(directory, manifest, *, display_grid_mm=None):
    """Validate node coverage and power balance, then return top/bottom layers."""
    root = Path(directory)
    nodes, triangles = read_msh2(root / manifest["mesh_file"])
    temperatures = read_frd_temperatures(root / manifest["result_file"])
    count = len(nodes)
    z = manifest["z_interfaces_mm"]
    expected = set(range(1, count * len(z) + 1))
    if set(temperatures) != expected:
        raise ValueError("CalculiX NDTEMP node IDs do not match the generated deck.")
    ordered = sorted(nodes)
    top = {node: temperatures[i] for i, node in enumerate(ordered, 1)}
    bottom_offset = (len(z)-1) * count
    bottom = {node: temperatures[bottom_offset+i] for i, node in enumerate(ordered, 1)}
    boundary = float(manifest["bottom_temperature_c"])
    if any(abs(value-boundary) > .02 for value in bottom.values()):
        raise ValueError("CalculiX lower-face temperatures violate the prescribed boundary.")
    step = float(display_grid_mm or manifest["gmsh_mesh_size_mm"])
    if not math.isfinite(step) or step <= 0:
        raise ValueError("display_grid_mm must be finite and positive.")
    fields = []
    for name, depth, values in (("F.Cu", z[0], top), ("B.Cu", z[-1], bottom)):
        fields.append({"name": name, "z_mm": depth,
                       **_sample_surface(nodes, triangles, values, step)})
    # For the last prism slab, each triangle's vertical face gradient is
    # constant. Integrate the outward bottom flux over its triangular area.
    before = {node: temperatures[bottom_offset-count+i]
              for i, node in enumerate(ordered, 1)}
    groups = []
    conductivity = manifest["copper_k_w_mk"]
    dielectric = manifest["dielectric_k_w_mk"]
    for triangle in triangles:
        a, b, c = [nodes[node] for node in triangle]
        area_mm2 = abs((b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]))/2
        center = ((a[0]+b[0]+c[0])/3, (a[1]+b[1]+c[1])/3)
        groups.append((triangle, area_mm2, center))
    # Material occupancy of the bottom slab is stored as 2D triangle IDs.
    bottom_copper = set(manifest.get("bottom_copper_triangles", []))
    dz_m = (z[-1]-z[-2]) * 1e-3
    if dz_m <= 0:
        raise ValueError("CalculiX stackup has no bottom slab thickness.")
    extracted = math.fsum((conductivity if i in bottom_copper else dielectric) *
                          area * 1e-6 / dz_m *
                          math.fsum(before[node]-bottom[node] for node in triangle)/3
                          for i, (triangle, area, _) in enumerate(groups))
    input_power = float(manifest["power_w"])
    tolerance = max(.02, .05 * input_power)
    if abs(extracted-input_power) > tolerance:
        raise ValueError(f"CalculiX heat balance failed: source {input_power:.6g} W, "
                         f"lower face {extracted:.6g} W.")
    return {"model": "CalculiX 3D steady conduction", "status": "completed",
            "layers": fields,
            "components": [], "heat_balance": {"source_w": input_power,
                                           "bottom_outflow_w": extracted,
                                           "residual_w": extracted-input_power},
            "field_source": "CalculiX NDTEMP; no package junction model"}
