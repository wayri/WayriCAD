"""Local, lossless coupled-line screening under an explicit ideal reference.

Two equal-width rectangular strips in a homogeneous dielectric above one
infinite PEC plane. Constant-charge panels integrate the image-charge Green
function exactly; even/odd modes supply C, L and Z. This is a local hypothetical
cross section, not extraction of the board's complete dielectric/plane field.
"""
from __future__ import annotations

import copy
import math
from functools import lru_cache

EPS0 = 8.8541878128e-12
C_MM_NS = 299.792458
MODEL = "Local homogeneous-plane coupled strips; explicit ideal reference; lossless matched-end step"
LIMITATIONS = [
    "Local section estimates are not summed or cascaded into a whole-route/circuit waveform.",
    "Reference height and homogeneous Er are explicit what-if assumptions. Actual plane continuity, other planes, air interfaces, soldermask and return transitions are unresolved.",
    "Equal-width/thickness straight rectangular strips only. No conductor/dielectric loss, pads, bends, vias, branches, crossing or broadside coupling.",
    "All four section ports use R=sqrt(Zeven*Zodd); route case driver/load resistances are NOT used by this local matched-end model.",
    "FEXT is exactly zero only in this ideal homogeneous model with equal modal velocities; it is not evidence of zero board crosstalk.",
    "Source swing is open-circuit Thevenin voltage. Rise time is 10–90% of a linear ramp.",
]


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + " must be a positive finite number.")
    return float(value)


def checked_pairs(config, cases):
    pairs = config.get("crosstalk", [])
    if not isinstance(pairs, list) or len(pairs) > 64:
        raise ValueError("crosstalk must be a list of at most 64 explicit directed pairs.")
    ids = {case["id"] for case in cases}
    seen = set()
    result = []
    for index, raw in enumerate(pairs):
        if not isinstance(raw, dict) or set(raw) - {"id", "aggressor", "victim", "rise_ns", "swing_v", "reference"}:
            raise ValueError("Unknown crosstalk pair fields.")
        row = copy.deepcopy(raw)
        row.setdefault("id", "coupling-" + str(index + 1))
        if not isinstance(row["id"], str) or not row["id"].strip() or row["id"] in seen:
            raise ValueError("Crosstalk pair IDs must be nonempty and unique.")
        seen.add(row["id"])
        if row.get("aggressor") not in ids or row.get("victim") not in ids or row["aggressor"] == row["victim"]:
            raise ValueError("Choose distinct existing aggressor/victim case IDs.")
        for key in ("rise_ns", "swing_v"):
            row[key] = _positive(row.get(key), key)
        ref = row.get("reference")
        if isinstance(ref,dict) and ref.get("model") == "saved-stripline":
            if set(ref) != {"model", "layer", "upper_layer"} or any(not isinstance(ref.get(k),str) or not ref[k].strip() for k in ("layer","upper_layer")) or ref["layer"] == ref["upper_layer"]:
                raise ValueError("saved-stripline needs two distinct bounding copper layer names: layer and upper_layer.")
            result.append(row)
            continue
        if not isinstance(ref, dict) or set(ref) != {"model", "layer", "height_mm", "epsilon_r"}:
            raise ValueError("Reference needs model, layer, height_mm and epsilon_r.")
        if ref["model"] != "homogeneous-plane" or not isinstance(ref["layer"], str) or not ref["layer"].strip():
            raise ValueError("Select homogeneous-plane and an explicit reference copper layer.")
        ref["height_mm"] = _positive(ref["height_mm"], "height_mm")
        ref["epsilon_r"] = _positive(ref["epsilon_r"], "epsilon_r")
        if ref["epsilon_r"] < 1:
            raise ValueError("epsilon_r must be at least one.")
        result.append(row)
    return result


def _solve(matrix, rhs):
    """Small dense partial-pivot solve, avoiding an optional runtime dependency."""
    rows = [list(row) + [value] for row, value in zip(matrix, rhs)]
    n = len(rows)
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: abs(rows[j][i]))
        rows[i], rows[pivot] = rows[pivot], rows[i]
        if abs(rows[i][i]) < 1e-14:
            raise ValueError("Electrostatic panel matrix is singular.")
        for j in range(i + 1, n):
            factor = rows[j][i] / rows[i][i]
            for k in range(i + 1, n + 1):
                rows[j][k] -= factor * rows[i][k]
    out = [0.] * n
    for i in reversed(range(n)):
        out[i] = (rows[i][-1] - sum(rows[i][j] * out[j] for j in range(i + 1, n))) / rows[i][i]
    return out


def _primitive(x, height):
    # Integral log(sqrt(x²+4h²)/abs(x)) dx, including the integrable x=0 singularity.
    if x == 0:
        return 0.
    return .5 * x * math.log1p((2 * height / x) ** 2) + 2 * height * math.atan(x / (2 * height))


def _modal_capacitances(width, gap, height, er, panels):
    # Cosine spacing resolves the integrable edge charge singularity.
    edges = [width * (1 - math.cos(math.pi * i / panels)) / 2 for i in range(panels + 1)]
    intervals = [(a + offset, b + offset) for offset in (0., width + gap) for a, b in zip(edges, edges[1:])]
    centers = [(a + b) / 2 for a, b in intervals]
    matrix = [[(_primitive(b - x, height) - _primitive(a - x, height)) / ((b - a) * 2 * math.pi)
               for a, b in intervals] for x in centers]
    even = _solve(matrix, [1.] * (2 * panels))
    odd = _solve(matrix, [1.] * panels + [-1.] * panels)
    return EPS0 * er * sum(even[:panels]), EPS0 * er * sum(odd[:panels])


def _log_integral(x, distance):
    if distance < 1e-15:
        return 0. if x == 0 else x * (math.log(abs(x)) - 1)
    return .5 * x * math.log(x * x + distance * distance) - x + distance * math.atan(x / distance)


def _panel_log_distance(point, panel):
    a, b = panel
    length = _distance(a, b)
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    dx, dy = point[0] - a[0], point[1] - a[1]
    along, perpendicular = dx * ux + dy * uy, abs(dx * uy - dy * ux)
    return (_log_integral(length - along, perpendicular) - _log_integral(-along, perpendicular)) / length


def _potential_matrix(panels):
    """2D PEC-ground image Green function integrated over straight line panels."""
    centers = [[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] for a, b in panels]
    return [[(_panel_log_distance(point, ((a[0], -a[1]), (b[0], -b[1]))) -
              _panel_log_distance(point, (a, b))) / (2 * math.pi)
             for a, b in panels] for point in centers]


def _rectangle_panels(width, height, thickness, panels, offset):
    x = [offset + width * (1 - math.cos(math.pi * i / panels)) / 2 for i in range(panels + 1)]
    side_count = max(4, math.ceil(panels * thickness / width))
    y = [height - thickness / 2 + thickness * (1 - math.cos(math.pi * i / side_count)) / 2 for i in range(side_count + 1)]
    return ([((a, y[0]), (b, y[0])) for a, b in zip(x, x[1:])] +
            [((a, y[-1]), (b, y[-1])) for a, b in zip(x, x[1:])] +
            [((x[0], a), (x[0], b)) for a, b in zip(y, y[1:])] +
            [((x[-1], a), (x[-1], b)) for a, b in zip(y, y[1:])])


def _finite_capacitances(width, gap, height, thickness, er, panels):
    first = _rectangle_panels(width, height, thickness, panels, 0.)
    second = _rectangle_panels(width, height, thickness, panels, width + gap)
    matrix = _potential_matrix(first + second)
    n = len(first)
    even = _solve(matrix, [1.] * (2 * n))
    odd = _solve(matrix, [1.] * n + [-1.] * n)
    return EPS0 * er * sum(even[:n]), EPS0 * er * sum(odd[:n])


@lru_cache(maxsize=512)
def coupled_modes(width_mm, gap_mm, height_mm, epsilon_r, copper_mm=0.):
    """Image-plane BEM; cosine panels, adaptive refinement, 2% acceptance."""
    w, g, h, er = [_positive(v, n) for v, n in zip(
        (width_mm, gap_mm, height_mm, epsilon_r), ("width", "gap", "height", "Er"))]
    if er < 1 or not .1 <= w / h <= 10 or g / h < .1:
        raise ValueError("Panel screening requires Er >= 1, 0.1 <= width/height <= 10 and gap/height >= 0.1.")
    if not math.isfinite(copper_mm) or copper_mm < 0 or copper_mm > w or copper_mm >= h:
        raise ValueError("Copper thickness must be between zero and width, and below center-to-plane height.")
    calculation = (lambda n: _finite_capacitances(w, g, h, copper_mm, er, n)) if copper_mm else (lambda n: _modal_capacitances(w, g, h, er, n))
    low = calculation(8)
    ce, co = calculation(16)
    count = 16
    refinement = max(abs(a - b) / b for a, b in zip(low, (ce, co)))
    coupling_floor=1e-9
    coefficient=lambda values:(values[1]-values[0])/(values[1]+values[0])
    delta=abs(coefficient(low)-coefficient((ce,co)))
    if refinement > .005 or delta > max(coupling_floor,.005*abs(coefficient((ce,co)))):
        low = (ce, co)
        ce, co = calculation(32)
        count = 32
        refinement = max(abs(a - b) / b for a, b in zip(low, (ce, co)))
        delta=abs(coefficient(low)-coefficient((ce,co)))
    if not 0 < ce <= co or refinement > .02:
        raise ValueError("Electrostatic modes failed positivity/convergence (2% panel refinement limit).")
    k=coefficient((ce,co))
    if delta > max(coupling_floor,.02*abs(k)):
        raise ValueError("Coupling coefficient failed its separate 2% / 1e-9 absolute refinement gate.")
    velocity = C_MM_NS * 1e6 / math.sqrt(er)
    ze, zo = 1 / (velocity * ce), 1 / (velocity * co)
    return dict(z_even_ohm=ze, z_odd_ohm=zo, c_even_pf_m=ce * 1e12,
                c_odd_pf_m=co * 1e12, l_even_nh_m=ze / velocity * 1e9,
                l_odd_nh_m=zo / velocity * 1e9, panel_refinement_relative=refinement,
                panels_per_horizontal_face=count, copper_thickness_mm=copper_mm,
                coupling_refinement_absolute=delta,
                coupling_refinement_relative=delta/abs(k) if abs(k)>=coupling_floor else None,
                coupling_numerical_floor=coupling_floor,
                coupling_numerical_status="RESOLVED" if abs(k)>=coupling_floor else "BELOW_NUMERICAL_FLOOR",
                coupling=(ze - zo) / (ze + zo))


def matched_step(z_even, z_odd, delay_ns, rise_ns, swing_v):
    """Exact modal reflections for equal delays and geometric-mean port loads.

    NEXT(t)=Vs*r/2 [f(t)-(1-r²) Σ r^(2n) f(t-2(n+1)td)].
    Piecewise-linear extrema occur at ramp knots, so no sampling peak error.
    """
    ze, zo, td, rise, swing = [_positive(v, n) for v, n in zip(
        (z_even, z_odd, delay_ns, rise_ns, swing_v), ("Zeven", "Zodd", "delay", "rise", "swing"))]
    if ze < zo:
        raise ValueError("Even-mode impedance must be at least odd-mode impedance.")
    r = (math.sqrt(ze) - math.sqrt(zo)) / (math.sqrt(ze) + math.sqrt(zo))
    full_rise = rise / .8
    count = 1 if r == 0 else max(1, math.ceil(math.log(1e-12) / math.log(r * r)))
    if count > 512:
        raise ValueError("Coupling reflection settling exceeds the bounded screening workload.")
    ramp = lambda t: min(1., max(0., t / full_rise))
    def voltage(t):
        return swing * r / 2 * (ramp(t) - (1 - r * r) * sum(
            r ** (2 * n) * ramp(t - 2 * (n + 1) * td) for n in range(count)))
    knots = sorted({0., full_rise, *[2 * (n + 1) * td for n in range(count)],
                    *[2 * (n + 1) * td + full_rise for n in range(count)]})
    samples = [[t, voltage(t)] for t in knots]
    peak = max(samples, key=lambda p: abs(p[1]))
    return dict(next_peak_v=abs(peak[1]), next_peak_time_ns=peak[0], fext_peak_v=0.,
                delay_ns=td, full_ramp_ns=full_rise, matched_port_ohm=math.sqrt(ze * zo),
                next_samples=samples, settling_tail_bound_v=swing * abs(r) / 2 * r ** (2 * count))


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def oriented_sections(case, source_xy):
    """Orient the extracted path from its explicit source; merge straight runs."""
    result = []
    current = source_xy
    offset = 0.
    for original in case["path_data"].get("segments", []):
        row = copy.deepcopy(original)
        a, b = row.get("start_mm"), row.get("end_mm")
        if a is not None and b is not None:
            if _distance(current, b) < _distance(current, a):
                a, b = b, a
            row["start_mm"], row["end_mm"] = a, b
            current = b
        row["offset_mm"] = offset
        offset += row.get("length_mm", 0.)
        if result and row.get("kind") == "track" and row.get("geometry") == "straight":
            prev = result[-1]
            if prev.get("kind") == "track" and prev.get("geometry") == "straight" and prev.get("layer") == row.get("layer") and prev.get("width_mm") == row.get("width_mm") and prev.get("copper_thickness_mm") == row.get("copper_thickness_mm") and _distance(prev["end_mm"], a) < 1e-6:
                p = prev["start_mm"]
                if abs(_distance(p, b) - prev["length_mm"] - row["length_mm"]) < 1e-6:
                    prev["end_mm"] = b
                    prev["length_mm"] += row["length_mm"]
                    prev["item_uuids"].append(row["item_uuid"])
                    continue
        row["item_uuids"] = [row.get("item_uuid")]
        result.append(row)
    return result


def parallel_overlap(a, b):
    """True projected overlap and edge gap, in mm; no bounding-box coupling."""
    if a.get("kind") != "track" or b.get("kind") != "track" or a.get("geometry") != "straight" or b.get("geometry") != "straight" or a.get("layer") != b.get("layer"):
        return None
    p, q = a["start_mm"], a["end_mm"]
    s, t = b["start_mm"], b["end_mm"]
    la, lb = _distance(p, q), _distance(s, t)
    if min(la, lb) <= 1e-9:
        return None
    u = ((q[0] - p[0]) / la, (q[1] - p[1]) / la)
    v = ((t[0] - s[0]) / lb, (t[1] - s[1]) / lb)
    dot = u[0] * v[0] + u[1] * v[1]
    if abs(u[0] * v[1] - u[1] * v[0]) > 1e-7:
        return None
    project = lambda xy: (xy[0] - p[0]) * u[0] + (xy[1] - p[1]) * u[1]
    bs, bt = project(s), project(t)
    start, end = max(0., min(bs, bt)), min(la, max(bs, bt))
    if end - start <= 1e-6:
        return None
    gap = abs((s[0] - p[0]) * u[1] - (s[1] - p[1]) * u[0]) - (a["width_mm"] + b["width_mm"]) / 2
    b0, b1 = sorted(((start - bs) / dot, (end - bs) / dot))
    return dict(length_mm=end - start, gap_mm=gap, layer=a["layer"],
                signed_separation_mm=-(s[0]-p[0])*u[1]+(s[1]-p[1])*u[0],
                aggressor_interval_mm=[a["offset_mm"] + start, a["offset_mm"] + end],
                victim_interval_mm=[b["offset_mm"] + b0, b["offset_mm"] + b1],
                direction="same" if dot > 0 else "opposite",
                near_victim_role="source-side" if dot > 0 else "receiver-side",
                aggressor_item_uuids=a["item_uuids"], victim_item_uuids=b["item_uuids"],
                start_mm=[p[0] + start * u[0], p[1] + start * u[1]],
                end_mm=[p[0] + end * u[0], p[1] + end * u[1]])


def _union_length(intervals):
    end = -math.inf
    total = 0.
    for a, b in sorted(intervals):
        total += max(0., b - max(a, end))
        end = max(end, b)
    return total


def saved_stripline_reference(board, reference, signal_layer, overlap, width, engine):
    """Validate bounding stackup and filled copper over the entire pair envelope."""
    physical = list(board.GetEnabledLayers().CuStack())
    names = [str(board.GetLayerName(layer)) for layer in physical]
    signal = names.index(signal_layer)
    refs = sorted((names.index(reference["layer"]), names.index(reference["upper_layer"])))
    if refs != [signal - 1, signal + 1]:
        raise ValueError("Saved stripline requires the immediately adjacent copper layer on both sides.")
    if not hasattr(engine,"_coupling_stackup_checked"):
        from pathlib import Path
        path=Path(board.GetFileName())
        if not path.is_file():
            raise ValueError("Save the physical stackup before saved-stripline analysis.")
        text=path.read_text(encoding="utf-8")
        start=text.find("(stackup")
        if start<0 or "addsublayer" in engine._balanced_block(text,start):
            raise ValueError("Missing stackup or dielectric sublayers are unsupported; their individual materials must not be collapsed.")
        engine._coupling_stackup_checked=True
    rows = engine.stackup_layers()
    copper = [i for i,r in enumerate(rows) if r.name.endswith(".Cu") or "copper" in r.kind.lower()]
    if len(copper) != len(physical):
        raise ValueError("Saved physical stackup does not match enabled copper layers.")
    signal_row = rows[copper[signal]]
    thickness = signal_row.thickness_mm
    if thickness <= 0:
        raise ValueError("Saved signal copper thickness is missing.")
    dielectrics = [rows[copper[refs[0]]+1:copper[signal]], rows[copper[signal]+1:copper[refs[1]]]]
    values = [[(r.thickness_mm,r.relative_permittivity) for r in group] for group in dielectrics]
    if any(not group for group in values) or any(not math.isfinite(h) or h <= 0 or not math.isfinite(er) or er < 1 for group in values for h,er in group):
        raise ValueError("Saved dielectric thickness/permittivity is missing.")
    ers = [er for group in values for _,er in group]
    if max(ers)-min(ers) > 1e-6 * max(ers):
        raise ValueError("Inhomogeneous saved dielectrics need a different coupled-field model.")
    heights = [sum(h for h,_ in group) + thickness/2 for group in values]
    geometry = engine._geometry()
    # The envelope spans both actual strip edges plus three total plane
    # spacings on either side; finite plane-edge fields remain a limitation.
    a,b = overlap["start_mm"],overlap["end_mm"]
    length = _distance(a,b)
    ux,uy = (b[0]-a[0])/length,(b[1]-a[1])/length
    end_margin=3*sum(heights)
    if length <= 2*end_margin:
        raise ValueError("Overlap is shorter than two end-transition exclusion margins (three plane spacings each).")
    overlap["raw_overlap_length_mm"]=length
    overlap["end_exclusion_mm"]=end_margin
    a=[a[0]+ux*end_margin,a[1]+uy*end_margin]
    b=[b[0]-ux*end_margin,b[1]-uy*end_margin]
    overlap.update(start_mm=a,end_mm=b,length_mm=length-2*end_margin)
    for role in ("aggressor","victim"):
        interval=overlap[role+"_interval_mm"]
        overlap[role+"_interval_mm"]=[interval[0]+end_margin,interval[1]-end_margin]
    center_offset = overlap["signed_separation_mm"]/2
    p = [round((a[0]-uy*center_offset)*1e6),round((a[1]+ux*center_offset)*1e6)]
    q = [round((b[0]-uy*center_offset)*1e6),round((b[1]+ux*center_offset)*1e6)]
    envelope = 2*width+overlap["gap_mm"]+6*sum(heights)
    probe=geometry.corridor(p,q,envelope)
    box=probe.BBox()
    if not hasattr(engine,"_coupling_copper"):
        engine._coupling_copper=(list(board.GetTracks())+[pad for fp in board.GetFootprints() for pad in fp.Pads()]
                                 +list(board.GetDrawings())+[item for fp in board.GetFootprints() for item in fp.GraphicalItems()])
    modeled=set(overlap["aggressor_item_uuids"]+overlap["victim_item_uuids"])
    for item in engine._coupling_copper:
        if str(item.m_Uuid.AsString()) in modeled or not item.IsOnLayer(physical[signal]) or not item.GetBoundingBox().Intersects(box):
            continue
        poly=geometry.pcb.SHAPE_POLY_SET()
        item.TransformShapeToPolygon(poly,physical[signal],0,1000,geometry.pcb.ERROR_INSIDE)
        poly.BooleanIntersection(probe)
        if poly.Area()>4:
            raise ValueError("Additional same-layer copper (including pads, vias or same-net branches) enters the pair field-margin corridor; two-conductor model unresolved.")
    for island in geometry.islands:
        if island["layer"]!=physical[signal]:
            continue
        poly=geometry.pcb.SHAPE_POLY_SET(island["poly"]);poly.BooleanIntersection(probe)
        if poly.Area()>4:
            raise ValueError("Same-layer filled copper enters the pair field-margin corridor; coplanar coupling unresolved.")
    reference_nets=[]
    for index in refs:
        matches=[island for island in geometry.islands if island["layer"]==physical[index] and geometry.fits(island,p,q,envelope)]
        if not matches:
            raise ValueError("Filled bounding reference does not continuously cover the pair plus field-margin corridor.")
        reference_nets.append(sorted({island["net"] for island in matches}))
    if not set(reference_nets[0]).intersection(reference_nets[1]):
        raise ValueError("Bounding planes do not share a reference net; their return connection is unresolved.")
    return dict(height_mm=heights[0],upper_height_mm=heights[1],epsilon_r=ers[0],copper_thickness_mm=thickness,
                bounding_layers=[names[i] for i in refs],reference_nets=reference_nets,
                coverage_margin_mm=3*sum(heights),reference_continuity="LOCAL_FILLED_CORRIDOR_COVERED",
                scope="Saved homogeneous stackup and local filled-plane envelope; finite plane edges/return connections remain approximate.")


def screen_pair(board, pair, cases):
    """Retain local numeric sections and explicitly account for omitted routes."""
    row = dict(copy.deepcopy(pair), model=MODEL, limitations=list(LIMITATIONS),
               status="UNRESOLVED", sections=[], unresolved=[], reference_continuity="UNRESOLVED",
               actual_material_model="UNRESOLVED: homogeneous idealization is explicitly assumed")
    try:
        a, b = cases[pair["aggressor"]], cases[pair["victim"]]
        if "path_data" not in a or "path_data" not in b:
            raise ValueError("Both route cases must have extracted paths.")
        if a["net"] == b["net"]:
            raise ValueError("Aggressor and victim must be distinct nets.")
        if any(case["report"].get("terminal_count") != 2 for case in (a, b)):
            row["unresolved"].append({"reason":"Multiple physical pads/branches cannot be collapsed into a two-port. Local isolated-section values omit their loading and are not terminal voltages."})
        layers = {str(board.GetLayerName(layer)) for layer in board.GetEnabledLayers().CuStack()}
        if pair["reference"]["layer"] not in layers or (pair["reference"]["model"]=="saved-stripline" and pair["reference"]["upper_layer"] not in layers):
            raise ValueError("Reference layer is not an enabled copper layer on this board.")
        sections = []
        for case in (a, b):
            source = [pad for fp in board.GetFootprints() for pad in fp.Pads()
                      if str(pad.GetNetname()) == case["net"] and str(fp.GetReference()) + "." + str(pad.GetNumber()) == case["start"]]
            if len(source) != 1:
                raise ValueError("Source physical pad is ambiguous.")
            xy = source[0].GetPosition()
            runs = oriented_sections(case, [xy.x / 1e6, xy.y / 1e6])
            # A selected shortest path is not proof of an unbranched two-port.
            board_length = sum(float(item.GetLength()) / 1e6 for item in board.GetTracks()
                               if str(item.GetNetname()) == case["net"] and item.GetClass() != "PCB_VIA")
            selected_length = sum(s["length_mm"] for s in runs if s["kind"] == "track")
            if abs(board_length - selected_length) > 1e-5 or case["path_data"].get("zone_count", 0):
                row["unresolved"].append({"reason":case["id"]+": extra copper, branches, alternate routes or zones are omitted from isolated-section values; whole-route coupling is unresolved."})
            sections.append(runs)
        if len(sections[0]) * len(sections[1]) > 100000:
            raise ValueError("Route pair exceeds 100,000 section comparisons; choose shorter routes.")
        ref = pair["reference"]
        engine = None
        if ref["model"] == "saved-stripline":
            from .measurement import TraceMeasurementEngine
            engine=TraceMeasurementEngine(board)
            row["model"]="Local finite-thickness coupled stripline; saved homogeneous stackup and filled reference corridors; lossless matched-end step"
            row["limitations"][1]="Saved homogeneous dielectric and local filled reference coverage are checked. Infinite PEC plane approximation omits finite edges, losses, global return continuity and other signal layers."
            row["actual_material_model"]="Saved homogeneous stackup required per supported section"
        for sa in sections[0]:
            for sb in sections[1]:
                overlap = parallel_overlap(sa, sb)
                if overlap is None:
                    continue
                try:
                    if overlap["layer"] == ref["layer"]:
                        raise ValueError("Signal and reference cannot share a layer.")
                    if abs(sa["width_mm"] - sb["width_mm"]) > 1e-6:
                        raise ValueError("Unequal-width coupled strips are unsupported.")
                    if overlap["gap_mm"] <= 0:
                        raise ValueError("Touching/overlapping copper has no positive edge gap.")
                    thickness = sa.get("copper_thickness_mm", math.inf)
                    if abs(thickness - sb.get("copper_thickness_mm", math.inf)) > 1e-6:
                        raise ValueError("Unequal copper thicknesses are unsupported.")
                    geometry=ref
                    if ref["model"]=="saved-stripline":
                        geometry=saved_stripline_reference(board,ref,overlap["layer"],overlap,sa["width_mm"],engine)
                        from .coupled_stripline import coupled_stripline_modes
                        modes=coupled_stripline_modes(sa["width_mm"],overlap["gap_mm"],geometry["height_mm"],geometry["upper_height_mm"],geometry["epsilon_r"],geometry["copper_thickness_mm"])
                    else:
                        modes = coupled_modes(sa["width_mm"], overlap["gap_mm"], ref["height_mm"], ref["epsilon_r"], thickness)
                    delay = overlap["length_mm"] * math.sqrt(geometry["epsilon_r"]) / C_MM_NS
                    response = matched_step(modes["z_even_ohm"], modes["z_odd_ohm"], delay, pair["rise_ns"], pair["swing_v"])
                    response["next_numerical_resolution_v"]=pair["swing_v"]*modes["coupling_numerical_floor"]/2
                    row["sections"].append(dict(overlap, width_mm=sa["width_mm"], reference_geometry=geometry,
                                                status="LOCAL_REFERENCE_COVERED" if engine else "ASSUMED_REFERENCE", **modes, **response))
                except ValueError as error:
                    row["unresolved"].append(dict(overlap, reason=str(error)))
                if len(row["sections"]) + len(row["unresolved"]) > 256:
                    raise ValueError("More than 256 coupled sections; narrow the study.")
        coverage = {}
        for role, case in (("aggressor", a), ("victim", b)):
            total = case["path_data"]["length_mm"]
            covered = _union_length([s[role + "_interval_mm"] for s in row["sections"]])
            coverage[role] = dict(route_length_mm=total, supported_overlap_mm=covered,
                                  unmodeled_length_mm=max(0., total - covered),
                                  layers=case["path_data"].get("layers", []))
        row["coverage"] = coverage
        row["status"] = "REVIEW" if row["sections"] else "UNRESOLVED"
        if not row["sections"]:
            row["unresolved"].append({"reason": "No supported parallel same-layer equal-width overlaps. Crossing, vias, other layers and remaining length are not modeled."})
    except Exception as error:
        row["unresolved"].append({"reason": str(error), "error_type":type(error).__name__})
    return row
