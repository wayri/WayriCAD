"""Optional, bounded Gmsh/CalculiX steady-state thermal deck.

The 2D Gmsh triangles are extruded into conforming copper/dielectric wedges.
Coordinates in the input snapshot are mm; CalculiX coordinates are metres.
This deliberately requires an explicit isothermal lower face and rejects
plated barrels, mounts and separate heatsinks, which need contact models.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from .thermal_board_view import _inside


def find_calculix(executable=None):
    """Resolve a user-selected, environment or PATH ccx without guessing installs."""
    selected = executable or os.environ.get("WAYRICAD_CCX")
    if selected:
        path = Path(selected).expanduser().resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"CalculiX executable is unavailable: {path}")
        return str(path)
    return shutil.which("ccx")


def _finite(value, label, *, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite.") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{label} must be finite{' and positive' if positive else ''}.")
    return number


def _ring(ring):
    points = [(_finite(x, "X"), _finite(y, "Y")) for x, y in ring]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        raise ValueError("Board outline rings need at least three points.")
    area = math.fsum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1]))/2
    if abs(area) <= 1e-12:
        raise ValueError("Board outline ring has zero area.")
    return points


def _contains(point, polygon):
    return _inside(point, polygon["outer"]) and not any(
        _inside(point, hole) for hole in polygon.get("holes", []))


def _validate(geometry, view, result, settings):
    if geometry.get("outline_status") != "valid" or not geometry.get("outline"):
        raise ValueError("A verified saved Edge.Cuts outline is required.")
    if geometry.get("barrels") or geometry.get("mounting_holes"):
        raise ValueError("CalculiX bridge does not model vias, drilled pads or mounting contacts.")
    if settings.get("mount_boundaries"):
        raise ValueError("CalculiX bridge does not model selected mount boundaries.")
    layers = geometry.get("layers", [])
    if len(layers) < 2:
        raise ValueError("At least two explicit copper layers are required.")
    cuts = []
    for index, layer in enumerate(layers):
        center = _finite(layer["z_mm"], "Copper Z")
        thick = _finite(layer["thickness_mm"], "Copper thickness", positive=True)
        low, high = center-thick/2, center+thick/2
        if index and low <= cuts[-1][1]:
            raise ValueError("Copper layers overlap or lack dielectric separation.")
        cuts.append((low, high))
    if abs(cuts[0][0]) > 1e-8:
        raise ValueError("Top copper must start at board Z=0 mm.")
    sources = []
    located = {row["reference"]: row for row in view.get("components", [])}
    for part in result.get("components", []):
        if part.get("heat_path") != "board":
            raise ValueError("CalculiX bridge supports board heat paths only.")
        power = _finite(part["power_w"], "Component power")
        if power < 0:
            raise ValueError("Component power must be nonnegative.")
        if power == 0:
            continue
        ref = part["reference"]
        site = located.get(ref)
        if not site or not site.get("on_board", True):
            raise ValueError(f"{ref}: no verified board position.")
        side = site.get("side", "top").lower()
        if side not in ("top", "bottom"):
            raise ValueError(f"{ref}: unknown board side.")
        if side == "bottom":
            raise ValueError(f"{ref}: bottom sources conflict with the prescribed lower temperature.")
        if settings.get("source_contact_pad_numbers", {}).get(ref):
            raise ValueError(f"{ref}: pad contact resistance is not represented in this bridge.")
        box = site.get("bbox_mm")
        if not box or len(box) != 4:
            raise ValueError(f"{ref}: a saved footprint bbox_mm is required for source area.")
        x0, y0, x1, y1 = [_finite(v, "Source bound") for v in box]
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"{ref}: invalid source bounding box.")
        sources.append((ref, power, (x0, y0, x1, y1)))
    mesh_mm = _finite(settings.get("gmsh_mesh_size_mm"), "Gmsh mesh size", positive=True)
    dielectric_k = _finite(settings.get("dielectric_k_w_mk"), "Dielectric conductivity", positive=True)
    copper_k = _finite(settings.get("copper_k_w_mk", 385), "Copper conductivity", positive=True)
    bottom_c = _finite(settings.get("bottom_temperature_c"), "Lower face temperature")
    if bottom_c < -273.15:
        raise ValueError("Lower face temperature is below absolute zero.")
    if settings.get("board_h_w_m2k", 0) or settings.get("board_emissivity", 0):
        raise ValueError("Convection and radiation are not implemented in the CalculiX bridge.")
    return layers, cuts, sources, mesh_mm, dielectric_k, copper_k, bottom_c


def gmsh_geo(geometry, mesh_size_mm):
    """Return a Gmsh built-in-kernel surface script with true outline cutouts."""
    size = _finite(mesh_size_mm, "Gmsh mesh size", positive=True)
    lines = ["// QuickTherm saved-board outline; all coordinates in mm", "Mesh.MshFileVersion = 2.2;",
             "Mesh.Binary = 0;", "Mesh.ElementOrder = 1;"]
    point_id = edge_id = loop_id = 0
    surfaces = []
    for shape in geometry["outline"]:
        loops = []
        for ring_index, raw in enumerate([shape["outer_mm"], *shape.get("holes_mm", [])]):
            ring = _ring(raw)
            signed = math.fsum(a[0]*b[1]-b[0]*a[1] for a, b in zip(ring, ring[1:]+ring[:1]))
            if (signed < 0) == (ring_index == 0):
                ring.reverse()
            ids = []
            for x, y in ring:
                point_id += 1
                ids.append(point_id)
                lines.append(f"Point({point_id}) = {{{x:.12g}, {y:.12g}, 0, {size:.12g}}};")
            edges = []
            for first, second in zip(ids, ids[1:]+ids[:1]):
                edge_id += 1
                edges.append(edge_id)
                lines.append(f"Line({edge_id}) = {{{first}, {second}}};")
            loop_id += 1
            loops.append(loop_id)
            lines.append(f"Curve Loop({loop_id}) = {{{', '.join(map(str, edges))}}};")
        surfaces.append(len(surfaces)+1)
        lines.append(f"Plane Surface({surfaces[-1]}) = {{{', '.join(map(str, loops))}}};")
    lines.append(f"Physical Surface(1) = {{{', '.join(map(str, surfaces))}}};")
    return "\n".join(lines)+"\n"


def read_msh2(path):
    """Read ASCII MSH 2.2 linear triangles, rejecting other volume topology."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if lines[:3] != ["$MeshFormat", "2.2 0 8", "$EndMeshFormat"]:
        raise ValueError("Expected ASCII Gmsh MSH 2.2.")
    try:
        start = lines.index("$Nodes")
        count = int(lines[start+1])
        nodes = {}
        for line in lines[start+2:start+2+count]:
            columns = line.split()
            nodes[int(columns[0])] = (float(columns[1]), float(columns[2]))
        if lines[start+2+count] != "$EndNodes" or len(nodes) != count:
            raise ValueError("Invalid Gmsh node block.")
        start = lines.index("$Elements")
        count = int(lines[start+1])
        triangles = []
        for line in lines[start+2:start+2+count]:
            columns = [int(v) for v in line.split()]
            kind, tags = columns[1:3]
            corners = columns[3+tags:]
            if kind == 2:
                if len(corners) != 3 or any(node not in nodes for node in corners):
                    raise ValueError("Invalid Gmsh triangle.")
                triangles.append(tuple(corners))
            elif kind not in (1, 15):
                raise ValueError("Only first-order Gmsh triangles are supported.")
        if lines[start+2+count] != "$EndElements" or not triangles:
            raise ValueError("Gmsh mesh has no valid triangles.")
    except (IndexError, StopIteration, KeyError) as exc:
        raise ValueError("Incomplete Gmsh MSH 2.2 mesh.") from exc
    return nodes, triangles


def calculix_deck(geometry, view, result, settings, nodes, triangles):
    """Return deck and audit metadata; does not claim solver completion."""
    layers, cuts, sources, _, kd, kc, bottom_c = _validate(geometry, view, result, settings)
    z_edges = []
    slab_types = []
    for index, (low, high) in enumerate(cuts):
        if not z_edges:
            z_edges.append(low)
        else:
            slab_types.append(("dielectric", None))
            z_edges.append(low)
        slab_types.append(("copper", index))
        z_edges.append(high)
    ordered = sorted(nodes)
    node_numbers = {(level, old): level*len(ordered)+new for level in range(len(z_edges))
                    for new, old in enumerate(ordered, 1)}
    deck = ["** QuickTherm Gmsh mesh, steady conduction, SI units", "*NODE"]
    for level, z in enumerate(z_edges):
        for old in ordered:
            x, y = nodes[old]
            deck.append(f"{node_numbers[level, old]}, {x/1000:.12g}, {y/1000:.12g}, {z/1000:.12g}")
    groups = {"DIEL": []}
    for index in range(len(layers)):
        groups[f"CU{index}"] = []
        groups[f"DI{index}"] = []
    eid = 0
    elements = {}
    bottom_copper_triangles = []
    for level, (kind, index) in enumerate(slab_types):
        for triangle_index, triangle in enumerate(triangles):
            a, b, c = triangle
            ax, ay = nodes[a]; bx, by = nodes[b]; cx, cy = nodes[c]
            area2 = (bx-ax)*(cy-ay)-(by-ay)*(cx-ax)
            if abs(area2) <= 1e-12:
                raise ValueError("Gmsh produced a degenerate triangle.")
            if area2 < 0:
                b, c = c, b
            center = ((ax+bx+cx)/3, (ay+by+cy)/3)
            if not any(_inside(center, shape["outer_mm"]) and not any(
                    _inside(center, hole) for hole in shape.get("holes_mm", []))
                    for shape in geometry["outline"]):
                raise ValueError("Gmsh mesh contains a triangle outside the saved board outline.")
            if kind == "copper":
                copper = any(_contains(center, poly) for poly in layers[index].get("polygons_mm", []))
                group = f"CU{index}" if copper else f"DI{index}"
                if copper and level == len(slab_types)-1:
                    bottom_copper_triangles.append(triangle_index)
            else:
                group = "DIEL"
            eid += 1
            wedge = tuple(node_numbers[level, old] for old in (a, b, c)) + tuple(
                node_numbers[level+1, old] for old in (a, b, c))
            groups[group].append(eid)
            elements[eid] = wedge
    deck.append("*ELEMENT, TYPE=DC3D6, ELSET=ALL")
    for eid, wedge in elements.items():
        deck.append(f"{eid}, "+", ".join(map(str, wedge)))
    for group, members in groups.items():
        if not members:
            continue
        deck.append(f"*ELSET, ELSET={group}")
        deck.extend(f"{eid}," for eid in members)
    deck += ["*MATERIAL, NAME=DIELECTRIC", "*CONDUCTIVITY", f"{kd:.12g}",
             "*MATERIAL, NAME=COPPER", "*CONDUCTIVITY", f"{kc:.12g}"]
    for group, members in groups.items():
        if members:
            deck.append(f"*SOLID SECTION, ELSET={group}, MATERIAL={'COPPER' if group.startswith('CU') else 'DIELECTRIC'}")
    bottom_nodes = [node_numbers[len(z_edges)-1, old] for old in ordered]
    deck.append("*NSET, NSET=BOTTOM")
    deck.extend(f"{nid}," for nid in bottom_nodes)
    # Each top triangle supplies area/3 to each vertex. Clip by centroid as a
    # documented approximation; a source smaller than an element is rejected.
    load = {}
    source_totals = {}
    for ref, power, box in sources:
        weights = {}
        for triangle in triangles:
            a, b, c = triangle
            ax, ay = nodes[a]; bx, by = nodes[b]; cx, cy = nodes[c]
            x, y = (ax+bx+cx)/3, (ay+by+cy)/3
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                area = abs((bx-ax)*(cy-ay)-(by-ay)*(cx-ax))/2
                for old in triangle:
                    nid = node_numbers[0, old]
                    weights[nid] = weights.get(nid, 0)+area/3
        total = math.fsum(weights.values())
        if total <= 0:
            raise ValueError(f"{ref}: source footprint contains no mesh triangle centroid; refine Gmsh mesh.")
        for nid, weight in weights.items():
            load[nid] = load.get(nid, 0)+power*weight/total
        source_totals[ref] = power
    deck += ["*STEP", "*HEAT TRANSFER, STEADY STATE", "*BOUNDARY", f"BOTTOM, 11, 11, {bottom_c:.12g}"]
    if load:
        deck.append("*CFLUX")
        deck.extend(f"{nid}, 11, {watts:.12g}" for nid, watts in sorted(load.items()))
    deck += ["*NODE FILE", "NT", "*END STEP"]
    audit = {"status": "deck_ready", "mesh_nodes_2d": len(nodes), "mesh_triangles_2d": len(triangles),
             "wedge_elements": eid, "z_interfaces_mm": z_edges, "element_groups":
             {key: len(value) for key, value in groups.items()}, "power_w": math.fsum(load.values()),
             "component_power_w": source_totals, "bottom_temperature_c": bottom_c,
             "bottom_copper_triangles": bottom_copper_triangles,
             "copper_k_w_mk": kc, "dielectric_k_w_mk": kd,
             "boundary_model": "isothermal entire lower face; remaining faces adiabatic",
             "copper_model": "triangle-centroid occupancy; features smaller than mesh may disappear",
             "source_model": "top footprint bbox, triangle-centroid area weights; junction resistance excluded",
             "result_status": "not_solved"}
    if not math.isclose(audit["power_w"], math.fsum(source_totals.values()), rel_tol=1e-10, abs_tol=1e-12):
        raise ArithmeticError("Source distribution lost power.")
    return "\n".join(deck)+"\n", audit


def prepare_calculix(geometry, view, result, settings, output_dir, *, gmsh=None):
    """Write a reviewable .geo; if Gmsh exists, also write .msh and .inp.

    The returned manifest is explicit about absent tools and absent temperature
    results. No input PCB or existing output directory is overwritten.
    """
    _validate(geometry, view, result, settings)
    if geometry.get("source_path") and geometry.get("source_sha256"):
        actual = hashlib.sha256(Path(geometry["source_path"]).read_bytes()).hexdigest()
        if actual != geometry["source_sha256"]:
            raise ValueError("Saved PCB has changed since thermal geometry extraction.")
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    geo = directory/"board.geo"
    geo.write_text(gmsh_geo(geometry, settings["gmsh_mesh_size_mm"]), encoding="utf-8")
    manifest = {"status": "needs_gmsh", "result_status": "not_solved", "geometry_file": geo.name,
                "gmsh_mesh_size_mm": float(settings["gmsh_mesh_size_mm"]),
                "source_sha256": geometry.get("source_sha256"), "limitations":
                ["No via, plated-hole or mounting-contact model", "Entire bottom face is isothermal",
                 "Copper and source footprints use triangle-centroid occupancy", "No component junction model"]}
    exe = gmsh or shutil.which("gmsh")
    python_gmsh = not exe and importlib.util.find_spec("gmsh") is not None
    if exe or python_gmsh:
        mesh = directory/"board.msh"
        diagnostic = None
        if exe:
            completed = subprocess.run([str(exe), str(geo), "-2", "-format", "msh2", "-o", str(mesh)],
                                       cwd=directory, capture_output=True, text=True, timeout=180)
            if completed.returncode != 0:
                diagnostic = (completed.stderr or completed.stdout)[-2000:]
            manifest["mesh_backend"] = "gmsh_executable"
        else:
            import gmsh as gmsh_api

            initialized = gmsh_api.isInitialized()
            if not initialized:
                gmsh_api.initialize()
            try:
                gmsh_api.clear()
                gmsh_api.option.setNumber("General.Terminal", 0)
                gmsh_api.option.setNumber("Mesh.MshFileVersion", 2.2)
                gmsh_api.option.setNumber("Mesh.Binary", 0)
                gmsh_api.open(str(geo))
                gmsh_api.model.mesh.generate(2)
                gmsh_api.write(str(mesh))
            except Exception as exc:
                diagnostic = str(exc)[-2000:]
            finally:
                gmsh_api.clear()
                if not initialized:
                    gmsh_api.finalize()
            manifest["mesh_backend"] = "gmsh_python"
        if diagnostic or not mesh.exists():
            manifest["status"] = "gmsh_failed"
            manifest["diagnostic"] = diagnostic or "Gmsh did not write the requested mesh."
        else:
            nodes, triangles = read_msh2(mesh)
            deck, audit = calculix_deck(geometry, view, result, settings, nodes, triangles)
            inp = directory/"board.inp"
            inp.write_text(deck, encoding="utf-8")
            manifest.update(audit, status="deck_ready", mesh_file=mesh.name, calculix_deck=inp.name,
                            calculix_available=bool(shutil.which("ccx")))
    (directory/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return manifest


def run_calculix(output_dir, *, ccx=None, timeout_s=300, display_grid_mm=None):
    """Run a prepared deck and import a checked top/bottom temperature field."""
    directory = Path(output_dir).resolve()
    manifest_path = directory/"manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "deck_ready" or manifest.get("calculix_deck") != "board.inp":
        raise ValueError("A ready QuickTherm CalculiX deck is required.")
    exe = find_calculix(ccx)
    if not exe:
        manifest.update(status="needs_calculix", result_status="not_solved",
                        diagnostic="Install CalculiX ccx, add it to PATH, set WAYRICAD_CCX, or select its executable in QuickTherm.")
    else:
        try:
            completed = subprocess.run([str(exe), "-i", "board"], cwd=directory,
                                       capture_output=True, text=True, timeout=timeout_s)
        except (OSError, subprocess.TimeoutExpired) as exc:
            manifest.update(status="calculix_failed", result_status="not_solved",
                            diagnostic=f"CalculiX could not finish: {exc}")
            manifest_path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
            return manifest
        if completed.returncode == 0 and (directory/"board.frd").exists():
            manifest["result_file"] = "board.frd"
            try:
                from .thermal_calculix_result import import_calculix_field

                field = import_calculix_field(directory, manifest,
                                              display_grid_mm=display_grid_mm)
                (directory/"board_field.json").write_text(
                    json.dumps(field, indent=2)+"\n", encoding="utf-8")
                manifest.update(status="solved", result_status="field_validated",
                                field_file="board_field.json",
                                heat_balance=field["heat_balance"])
            except (OSError, ValueError) as exc:
                manifest.update(status="result_rejected", result_status="not_solved",
                                diagnostic=str(exc))
        else:
            manifest.update(status="calculix_failed", result_status="not_solved",
                            diagnostic=(completed.stderr or completed.stdout)[-2000:])
    manifest_path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return manifest
