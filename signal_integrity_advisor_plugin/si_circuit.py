"""Export reviewed point-to-point paths to editable KiCad-native IBIS circuits.

No PCB writes or IBIS-to-SPICE approximation occur here. KiCad owns IBIS model
interpretation. Each exported case is independent, with an ideal common reference.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from .ibis_models import assignment_from_catalog, load_ibis

DEFAULT_OPTIONS = {"duration_ns": 100.0, "timestep_ns": 0.1,
                   "frequency_mhz": 100.0, "duty_percent": 50.0,
                   "allow_approximations": False, "via_capacitance_pf": None,
                   "via_inductance_nh": None, "copper_thickness_um": None}
LIMITS = [
    "Independent single-ended point-to-point networks; no inter-net coupling or simultaneous-switching model.",
    "Ideal common reference; return-path impedance, pad spreading, radiation, skin/dielectric loss and dispersion are not solved.",
    "Each track uses a lossless distributed line plus its extracted lumped series DC resistance.",
    "Native IBIS package parasitics are included by KiCad; no separate package RLC is added.",
    "IBIS source/load replace the route screen's linear source/load resistances; those screening assumptions are not extra physical terminations.",
    "Export is a reviewable circuit model, not proof of native transient convergence or board qualification.",
    "Separate exports have distinct signal-net namespaces. Repeatedly pasting the same clipboard text shares its global net names; re-export for an isolated copy. Ground remains common by design.",
]


class CircuitExportError(ValueError):
    """The reviewed inputs cannot produce a complete supported circuit."""


def _number(value, label, *, zero=False, maximum=1e12):
    if isinstance(value, bool):
        raise CircuitExportError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CircuitExportError(f"{label} is unknown; supply a reviewed value") from exc
    if not math.isfinite(result) or result < 0 or (not zero and result == 0) or result > maximum:
        raise CircuitExportError(f"{label} must be {'non-negative' if zero else 'positive'}, finite and <= {maximum:g}")
    return result


def _options(options):
    if options is not None and not isinstance(options, dict):
        raise CircuitExportError("Export options must be an object")
    unknown = set(options or {}) - set(DEFAULT_OPTIONS)
    if unknown:
        raise CircuitExportError("Unknown export options: " + ", ".join(sorted(unknown)))
    out = dict(DEFAULT_OPTIONS, **(options or {}))
    for key in ("duration_ns", "timestep_ns", "frequency_mhz", "duty_percent"):
        out[key] = _number(out[key], key)
    if out["duty_percent"] >= 100:
        raise CircuitExportError("Duty percent must be strictly between 0 and 100")
    if out["timestep_ns"] > out["duration_ns"]:
        raise CircuitExportError("Timestep must not exceed duration")
    if out["duration_ns"] / out["timestep_ns"] > 2_000_000:
        raise CircuitExportError("Requested transient exceeds 2,000,000 output intervals")
    if out["frequency_mhz"] * out["duration_ns"] / 1000 > 100_000:
        raise CircuitExportError("Requested IBIS waveform exceeds 100,000 cycles")
    if type(out["allow_approximations"]) is not bool:
        raise CircuitExportError("allow_approximations must be true or false")
    for key in ("via_capacitance_pf", "via_inductance_nh", "copper_thickness_um"):
        if out[key] is not None:
            out[key] = _number(out[key], key)
    return out


def _json_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CircuitExportError("Reports must contain finite JSON data, without live board objects") from exc


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assignment(value, role, catalogs):
    if not isinstance(value, dict) or not value.get("sha256"):
        raise CircuitExportError(f"{role}: assign a reviewed IBIS file with SHA-256 first")
    if value.get("role") != role:
        raise CircuitExportError(f"{role}: assignment role does not match circuit terminal")
    try:
        path = str(Path(value["path"]).expanduser().resolve(strict=True))
        if path not in catalogs:
            catalogs[path] = load_ibis(path)
        catalog = catalogs[path]
        if catalog["sha256"] != value["sha256"]:
            raise CircuitExportError("IBIS file changed since assignment review")
        return assignment_from_catalog(catalog, value["component"], value["pin"],
                                       value["model"], role, value["corners"])
    except (KeyError, ValueError, OSError) as exc:
        raise CircuitExportError(f"{role} IBIS assignment: {exc}") from exc


def _topology(report):
    if report.get("terminal_count") != 2:
        raise CircuitExportError("Export requires exactly two terminals; branches and additional sinks must be modeled explicitly")
    evidence = report.get("circuit_topology", {})
    if (evidence.get("complete") is not True or evidence.get("branch_count") != 0
            or evidence.get("stub_count") != 0 or evidence.get("unmodeled_item_uuids") != []):
        raise CircuitExportError("Whole-net topology is unverified or contains branches/stubs: rerun the circuit topology check; an endpoint path alone is insufficient")


def _sections(report, options):
    _topology(report)
    path = report.get("path", {})
    if path.get("status") not in ("ok", "partial"):
        raise CircuitExportError("The selected path is disconnected or unresolved")
    sections = path.get("segments")
    if not isinstance(sections, list) or not sections or len(sections) > 4096:
        raise CircuitExportError("A circuit requires 1 to 4096 extracted sections")
    if not path.get("start_pad") or not path.get("end_pad") or path["start_pad"] == path["end_pad"]:
        raise CircuitExportError("Select two distinct source and receiver pads")
    inputs = report.get("inputs", {})
    z_assumed = inputs.get("assumed_z0_ohm")
    er_assumed = inputs.get("assumed_epsilon_eff")
    if z_assumed is not None:
        z_assumed = _number(z_assumed, "User-assumed Z0")
    if er_assumed is not None:
        er_assumed = _number(er_assumed, "User-assumed effective permittivity")
        if er_assumed < 1:
            raise CircuitExportError("Effective permittivity must be at least 1")
    # A path may have valid section models without one uniform route impedance.
    accepted = {"NONUNIFORM_IMPEDANCE", "UNIFORM_Z0_UNAVAILABLE", "COMPLETE_DELAY_UNAVAILABLE"}
    if z_assumed is not None and er_assumed is not None:
        accepted |= {"REFERENCE_PLANE_MISSING", "STACKUP_DIELECTRIC_MISSING", "ASYMMETRIC_INTERNAL_LINE"}
    if options["allow_approximations"]:
        accepted |= {"VIA_DISCONTINUITY_UNMODELED", "ZONE_DISTRIBUTED_MODEL_UNAVAILABLE"}
    for blocker in report.get("blockers", []) + path.get("blockers", []):
        if blocker.get("code") not in accepted:
            raise CircuitExportError("Unresolved circuit geometry: " + str(blocker.get("message", blocker.get("code", "unknown blocker"))))
    result, graph, length = [], {}, 0.0
    for index, section in enumerate(sections):
        kind = section.get("kind")
        if kind not in ("track", "via", "zone"):
            raise CircuitExportError(f"Section {index + 1}: unsupported kind {kind!r}")
        uid = section.get("item_uuid")
        if not isinstance(uid, str) or not uid:
            raise CircuitExportError(f"Section {index + 1}: missing source item UUID")
        layer = section.get("layer")
        if not isinstance(layer, str) or not layer:
            raise CircuitExportError(f"Section {index + 1}: missing copper layer")
        ends = []
        for key in ("start_mm", "end_mm"):
            xy = section.get(key)
            if not isinstance(xy, (list, tuple)) or len(xy) != 2:
                raise CircuitExportError(f"Section {index + 1}: missing endpoint geometry")
            try:
                coordinates = tuple(round(float(v), 6) for v in xy)
            except (TypeError, ValueError) as exc:
                raise CircuitExportError("Invalid section coordinates") from exc
            if not all(math.isfinite(v) for v in coordinates):
                raise CircuitExportError("Non-finite section coordinates")
            end_layer = section.get("end_layer") if kind == "via" and key == "end_mm" else layer
            if not isinstance(end_layer, str) or not end_layer:
                raise CircuitExportError("Via end layer is missing")
            ends.append((end_layer, *coordinates))
        if ends[0] == ends[1]:
            raise CircuitExportError(f"Section {index + 1}: zero-span or unresolved geometry")
        for a, b in (ends, ends[::-1]):
            graph.setdefault(a, []).append(b)
        distance = _number(section.get("length_mm"), f"Section {index + 1} length")
        length += distance
        resistance = _number(section.get("resistance_ohm"), f"Section {index + 1} DC resistance", zero=True)
        resistance_basis = "Extracted section DC resistance"
        if kind == "track" and section.get("copper_thickness_source") != "saved_stackup":
            manual_thickness = options["copper_thickness_um"]
            if manual_thickness is None:
                raise CircuitExportError(f"Section {index + 1}: copper thickness is not saved; enter an explicit copper_thickness_um assumption")
            if z_assumed is None or er_assumed is None:
                raise CircuitExportError(
                    f"Section {index + 1}: unsaved copper thickness invalidates the extracted line model; "
                    "enter explicit uniform Z0 and effective permittivity, rescreen, and enter reviewed copper thickness")
            old_thickness = _number(section.get("copper_thickness_mm"), f"Section {index + 1} original thickness for resistance scaling")
            resistance *= old_thickness / (manual_thickness / 1000)
            resistance_basis = "User-entered copper thickness; extracted DC R rescaled inversely with thickness, same copper resistivity assumption"
        row = {"index": index, "item_uuid": uid, "kind": kind, "layer": layer,
               "length_mm": distance, "resistance_ohm": resistance,
               "resistance_basis": resistance_basis,
               "source_section": copy.deepcopy(section), "references": []}
        if kind == "track":
            geometry = section.get("geometry", "")
            if geometry != "straight" and not geometry.startswith("arc (exact length,"):
                raise CircuitExportError(f"Section {index + 1}: unsupported track geometry {geometry!r}")
            z = z_assumed if z_assumed is not None else section.get("impedance_ohm")
            td = distance * math.sqrt(er_assumed) / 299.792458 if er_assumed is not None else section.get("propagation_delay_ns")
            row.update(z0_ohm=_number(z, f"Section {index + 1} Z0"),
                       delay_ns=_number(td, f"Section {index + 1} propagation delay"),
                       basis="Explicit user assumptions" if z_assumed is not None or er_assumed is not None else "Extracted section geometry")
        else:
            if not options["allow_approximations"]:
                raise CircuitExportError(f"Section {index + 1}: {kind} requires explicit lumped-approximation consent")
            if kind == "via":
                inductance = options["via_inductance_nh"]
                capacitance = options["via_capacitance_pf"]
                basis = "User-entered via loop L and capacitance; extracted barrel DC R"
            else:
                inductance, capacitance = section.get("inductance_nh"), section.get("capacitance_pf")
                basis = "Explicit lumped pi approximation of extracted zone corridor R/L/C"
            row.update(inductance_nh=_number(inductance, f"Section {index + 1} {kind} loop inductance nH"),
                       capacitance_pf=_number(capacitance, f"Section {index + 1} {kind} capacitance pF"), basis=basis)
        result.append(row)
    if not math.isclose(length, _number(path.get("length_mm"), "Path length"), rel_tol=1e-6, abs_tol=1e-6):
        raise CircuitExportError("Section lengths do not account for the entire selected path")
    # Independent topology check of serialized sections: no holes, loops or forks.
    if any(len(adjacent) > 2 for adjacent in graph.values()) or sum(len(v) == 1 for v in graph.values()) != 2:
        raise CircuitExportError("Section geometry contains a branch, loop, overlap or unsupported transition")
    seen, pending = set(), [next(iter(graph))]
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(graph[node])
    if len(seen) != len(graph):
        raise CircuitExportError("Selected sections are disconnected; pad spreading/bridges are not modeled")
    # Report sequence must follow the connected chain, in either item orientation.
    previous_ends = None
    visited_links = set()
    for section in sections:
        a = (section["layer"], *[round(float(v), 6) for v in section["start_mm"]])
        b = (section.get("end_layer", section["layer"]), *[round(float(v), 6) for v in section["end_mm"]])
        link = frozenset((a, b))
        if link in visited_links or (previous_ends is not None and not previous_ends.intersection(link)):
            raise CircuitExportError("Section order repeats or skips part of the channel")
        visited_links.add(link)
        previous_ends = link
    return result


def _q(value):
    return json.dumps(str(value), ensure_ascii=False)


def _uid():
    return str(uuid.uuid4())


def _fmt(value):
    return format(value, ".12g")


def _effects(size=1.0, hide=False):
    return f'(effects (font (size {size} {size}))' + (' (hide yes)' if hide else '') + ')'


PINS = {"SOURCE": [(1, 0, -5.08, 90), (2, 7.62, 0, 180)],
        "SINK": [(1, 0, -5.08, 90), (2, -7.62, 0, 0)],
        "LINE": [(1, -7.62, 0, 0), (2, -5.08, -5.08, 90), (3, 7.62, 0, 180), (4, 5.08, -5.08, 90)],
        "R": [(1, -7.62, 0, 0), (2, 7.62, 0, 180)],
        "L": [(1, -7.62, 0, 0), (2, 7.62, 0, 180)],
        "C": [(1, -7.62, 0, 0), (2, 7.62, 0, 180)]}


def _libraries(*, standalone=False):
    definitions = []
    for kind, pins in PINS.items():
        pin_text = ''.join(f'(pin passive line (at {x} {y} {angle}) (length 2.54)'
                           f' (name "~" {_effects()}) (number "{number}" {_effects()}))'
                           for number, x, y, angle in pins)
        name = kind if standalone else f"QuickSI:{kind}"
        definitions.append(f'(symbol "{name}" (pin_names (offset 0)) (in_bom no) (on_board no)'
                           f' (property "Reference" "U" (at 0 5.08 0) {_effects()})'
                           f' (property "Value" "{kind}" (at 0 2.54 0) {_effects()})'
                           f' (symbol "{kind}_0_1" (rectangle (start -5.08 2.54) (end 5.08 -2.54)'
                           ' (stroke (width 0.254) (type default)) (fill (type background))))'
                           f' (symbol "{kind}_1_1" {pin_text}))')
    header = '(kicad_symbol_lib (version 20231120) (generator "wayricad") ' if standalone else '(lib_symbols '
    return header + ''.join(definitions) + ')'


def _property(name, value, x, y, hide=True):
    return f'(property {_q(name)} {_q(value)} (at {_fmt(x)} {_fmt(y)} 0) {_effects(hide=hide)})'


def _text(value, x, y, size=1.27):
    return f'(text {_q(value)} (at {_fmt(x)} {_fmt(y)} 0) {_effects(size)} (uuid "{_uid()}"))'


def _terminal(name, x, y, direction):
    # Short wires make label-pin connectivity visible and native-netlist testable.
    dx, dy = direction
    ex, ey = x + dx * 2.54, y + dy * 2.54
    wire = f'(wire (pts (xy {_fmt(x)} {_fmt(y)}) (xy {_fmt(ex)} {_fmt(ey)})) (stroke (width 0) (type default)) (uuid "{_uid()}"))'
    angle = 180 if dx < 0 else 0
    justification = "right" if dx < 0 else "left"
    label = f'(global_label {_q(name)} (shape bidirectional) (at {_fmt(ex)} {_fmt(ey)} {angle}) (effects (font (size 0.8 0.8)) (justify {justification})) (uuid "{_uid()}"))'
    return wire + label


def _symbol(block, x, y, sheet_id, project, library_paths):
    kind, ref = block["kind"], block["reference"]
    fields = dict(block["fields"])
    if "model_sha256" in block:
        fields["Sim.Library"] = library_paths[block["model_sha256"]]
    content = (f'(symbol (lib_id "QuickSI:{kind}") (at {_fmt(x)} {_fmt(y)} 0) (unit 1)'
               f' (in_bom no) (on_board no) (dnp no) (uuid "{_uid()}")'
               + _property("Reference", ref, x, y - 7.62, False)
               + _property("Value", block["value"], x, y - 5.08, False)
               + ''.join(_property(key, value, x, y) for key, value in fields.items())
               + ''.join(f'(pin "{pin[0]}" (uuid "{_uid()}"))' for pin in PINS[kind])
               + f'(instances (project {_q(project)} (path {_q(sheet_id)} (reference {_q(ref)}) (unit 1)))))')
    for number, px, py, _ in PINS[kind]:
        direction = (-1, 0) if px < 0 and py == 0 else (1, 0) if px > 0 and py == 0 else (0, 1)
        content += _terminal(block["nets"][number - 1], x + px, y - py, direction)
    return content


def _bridge(previous, current, x, y):
    """Join consecutive same-row signal ports; labels retain cross-page identity."""
    right = next((pin for pin in PINS[previous["kind"]] if pin[1] > 0 and pin[2] == 0), None)
    left = next((pin for pin in PINS[current["kind"]] if pin[1] < 0 and pin[2] == 0), None)
    if not right or not left or previous["nets"][right[0]-1] != current["nets"][left[0]-1]:
        return ""
    a, b = x - 66.04 + right[1] + 2.54, x + left[1] - 2.54
    return f'(wire (pts (xy {_fmt(a)} {_fmt(y)}) (xy {_fmt(b)} {_fmt(y)})) (stroke (width 0) (type default)) (uuid "{_uid()}"))'


def _circuit(case, index, sections, options, counters, namespace):
    blocks = []
    prefix, next_node = f"{namespace}_C{index:03d}", 0
    def node():
        nonlocal next_node
        next_node += 1
        return f"{prefix}_N{next_node:04d}"
    def add(kind, value, nets, fields, section=None, model=None):
        category = "U" if kind in ("SOURCE", "SINK") else "O" if kind == "LINE" else kind
        counters[category] = counters.get(category, 0) + 1
        block = dict(kind=kind, reference=f"{category}{counters[category]}", value=value, nets=nets, fields=fields, case_id=case["id"])
        if model:
            block["model_sha256"] = model["sha256"]
        blocks.append(block)
        if section is not None:
            section["references"].append(block["reference"])
    def ibis(role, net):
        assignment = case[role]
        params = ' '.join(f"{key}={value}" for key, value in assignment["corners"].items())
        if role == "source":
            period = 1000 / options["frequency_mhz"]
            ton = period * options["duty_percent"] / 100
            params += f' ton={_fmt(ton)}n toff={_fmt(period-ton)}n td=0 n={math.ceil(options["duration_ns"] / period) + 1}'
        fields = {"Sim.Device": "IBIS", "Sim.Type": "RECTDRIVER" if role == "source" else "DEVICE",
                  "Sim.Name": assignment["component"], "Sim.Ibis.Pin": assignment["pin"],
                  "Sim.Ibis.Model": assignment["model"], "Sim.Pins": "1=GND 2=IN/OUT", "Sim.Params": params}
        add("SOURCE" if role == "source" else "SINK", assignment["model"], ["0", net], fields, model=assignment)
    current = node()
    ibis("source", current)
    for section in sections:
        section["input_net"] = current
        resistance = section["resistance_ohm"]
        if section["kind"] != "track":
            add("C", _fmt(section["capacitance_pf"] / 2) + "p", [current, "0"], {"Sim.Device": "C", "Sim.Pins": "1=1 2=2"}, section)
        if resistance:
            after = node()
            add("R", _fmt(resistance), [current, after], {"Sim.Device": "R", "Sim.Pins": "1=1 2=2"}, section)
            current = after
        after = node()
        if section["kind"] == "track":
            add("LINE", f'{_fmt(section["z0_ohm"])} ohm / {_fmt(section["delay_ns"])} ns',
                [current, "0", after, "0"], {"Sim.Device": "TLINE", "Sim.Type": "",
                "Sim.Pins": "1=1+ 2=1- 3=2+ 4=2-", "Sim.Params": f'z0={_fmt(section["z0_ohm"])} td={_fmt(section["delay_ns"])}n'}, section)
        else:
            add("L", _fmt(section["inductance_nh"]) + "n", [current, after], {"Sim.Device": "L", "Sim.Pins": "1=1 2=2"}, section)
            add("C", _fmt(section["capacitance_pf"] / 2) + "p", [after, "0"], {"Sim.Device": "C", "Sim.Pins": "1=1 2=2"}, section)
        current = after
        section["output_net"] = current
    ibis("sink", current)
    return blocks


def _document(objects, sheet_uuid, page, *, title="Quick SI IBIS circuit", paper="A3"):
    return (f'(kicad_sch (version 20231120) (generator "wayricad") (uuid "{sheet_uuid}") (paper "{paper}")'
            f' (title_block (title {_q(title)}))' + _libraries() + ''.join(objects)
            + f'(sheet_instances (path "/" (page "{page}"))))\n')


def export_circuit(cases, destination, options=None, *, guard=None):
    """Publish a NEW bundle directory; return absolute artifact paths and text.

    Reports require circuit_topology evidence: complete=true, branch_count=0,
    stub_count=0, unmodeled_item_uuids=[]. This evidence must come from a whole-net
    check, never be inferred from an endpoint path or two-terminal count alone.
    Every report must include source_fingerprints, or the caller must supply a
    guard callback accepting responsibility for source custody at publication.
    """
    opts = _options(options)
    if not isinstance(cases, (list, tuple)) or not 1 <= len(cases) <= 64:
        raise CircuitExportError("Export requires 1 to 64 independent cases")
    if any(not isinstance(case, dict) or not isinstance(case.get("report"), dict) for case in cases):
        raise CircuitExportError("Each case must contain a report object")
    if guard is not None and not callable(guard):
        raise CircuitExportError("The source custody guard must be callable")
    if guard is None and any("source_fingerprints" not in case["report"] for case in cases):
        raise CircuitExportError("Source custody is unverified: provide saved source fingerprints or an explicit caller guard")
    if guard is not None:
        guard()
    snapshot = copy.deepcopy(list(cases))
    initial_bytes = _json_bytes(snapshot)
    def check_sources():
        from .ibis_workflow import require_report_source
        checked = set()
        for case in snapshot:
            report = case.get("report", {})
            if "source_fingerprints" in report:
                key = _json_bytes(report["source_fingerprints"])
                if key not in checked:
                    require_report_source(report)
                    checked.add(key)
    check_sources()
    target = Path(destination).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise CircuitExportError("Destination already exists; choose a new circuit bundle directory")
    if not target.parent.is_dir():
        raise CircuitExportError("Destination parent directory does not exist")
    counters, blocks, records, models, ids, catalogs = {}, [], [], {}, set(), {}
    namespace = "SI" + uuid.uuid4().hex[:16]
    for index, case in enumerate(snapshot, 1):
        ident = case.get("id")
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 128 or ident in ids:
            raise CircuitExportError("Case IDs must be unique nonempty strings up to 128 characters")
        ids.add(ident)
        try:
            report = case["report"]
            sections = _sections(report, opts)
            for role in ("source", "sink"):
                case[role] = _assignment(case.get(role), role, catalogs)
                models[case[role]["sha256"]] = case[role]["path"]
            blocks.extend(_circuit(case, index, sections, opts, counters, namespace))
        except (KeyError, TypeError, AttributeError) as exc:
            raise CircuitExportError(f"Case {ident}: malformed report or assignment ({exc})") from exc
        records.append({"id": ident, "source": case["source"], "sink": case["sink"],
                        "report_sha256": hashlib.sha256(_json_bytes(report)).hexdigest(),
                        "report": report, "sections": sections})
    if len(blocks) > 9216:
        raise CircuitExportError("Circuit exceeds 9216 model blocks; export smaller groups")
    relative = {sha: f"models/{sha}.ibs" for sha in models}
    absolute = {sha: (target / path).as_posix() for sha, path in relative.items()}
    root_id = _uid()
    pages, children, clipboard = [], [], []
    # 36 blocks/page, each visibly labeled; global net labels preserve crossings
    # between pages and let a complete clipboard selection carry the same graph.
    for offset in range(0, len(blocks), 36):
        page = len(pages) + 2
        child_id = _uid()
        child_name = f"channel_{page-1:03d}.kicad_sch"
        objects = [_text("Quick SI: independent IBIS channels — review manifest assumptions", 190, 18, 1.5)]
        for j, block in enumerate(blocks[offset:offset+36]):
            x, y = 38.1 + (j % 6) * 66.04, 38.1 + (j // 6) * 38.1
            objects.append(_symbol(block, x, y, f"/{root_id}/{child_id}", "circuit", relative))
            # KiCad interprets schematic text starting with '.' as SPICE commands.
            # User case IDs are captions, never multiline simulator directives.
            caption = "Case: " + " ".join(block["case_id"].split())[:32]
            objects.append(_text(caption, x, y + 13, .9))
            # Spread clipboard pages vertically; no hierarchy is needed when pasted.
            clipboard.append(_symbol(block, x, y + (page-2) * 254, "/", "circuit", absolute))
            if j % 6:
                objects.append(_bridge(blocks[offset+j-1], block, x, y))
                clipboard.append(_bridge(blocks[offset+j-1], block, x, y + (page-2) * 254))
        pages.append((child_name, _document(objects, child_id, page)))
        sx, sy = 15 + ((page-2) % 8) * 48, 55 + ((page-2) // 8) * 9
        children.append(f'(sheet (at {sx} {sy}) (size 40 7) (stroke (width 0) (type default)) (fill (color 0 0 0 0)) (uuid "{child_id}")'
                        f'(property "Sheetname" "Channels {page-1}" (at {sx} {sy} 0) {_effects(.8)})'
                        f'(property "Sheetfile" "{child_name}" (at {sx} {sy+7} 0) {_effects(.8)})'
                        f'(instances (project "circuit" (path "/{root_id}" (page "{page}")))))')
    directive = f'.tran {_fmt(opts["timestep_ns"])}n {_fmt(opts["duration_ns"])}n'
    root_objects = [_text("Quick SI — Native IBIS Simulation Circuit", 180, 15, 2),
                    _text("Open channel sheets; inspect manifest before simulation. Ideal common ground; uncoupled cases.", 190, 25),
                    _text(directive, 100, 38)] + children
    root = _document(root_objects, root_id, 1, paper="A2")
    clip_text = _libraries() + ''.join(clipboard) + _text(directive, 100, 15) + '\n'
    manifest = {"schema": "wayricad.quick-si-circuit/v1", "options": opts, "limits": LIMITS,
                "signal_net_namespace": namespace,
                "native_simulator_validation": "Not run by exporter", "cases": records,
                "model_files": [{"source": source, "sha256": sha, "bundled": relative[sha]} for sha, source in models.items()],
                "blocks": blocks, "pages": [name for name, _ in pages],
                "merging": "No sections merged; every original section and UUID is retained"}
    stage = Path(tempfile.mkdtemp(prefix=".quick-si-export-", dir=target.parent))
    try:
        (stage / "models").mkdir()
        for sha, source in models.items():
            shutil.copyfile(source, stage / relative[sha])
            if _hash(stage / relative[sha]) != sha:
                raise CircuitExportError("IBIS file changed while bundling; reload assignments")
        files = {"circuit.kicad_sch": root, "circuit.kicad_pro": json.dumps({"meta": {"filename": "circuit.kicad_pro", "version": 1}}, indent=2),
                 "quicksi.kicad_sym": _libraries(standalone=True),
                 "sym-lib-table": '(sym_lib_table (version 7) (lib (name "QuickSI")(type "KiCad")(uri "${KIPRJMOD}/quicksi.kicad_sym")(options "")(descr "Quick SI authored simulation symbols")))\n',
                 "clipboard.txt": clip_text, "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False)}
        files.update(pages)
        for name, content in files.items():
            (stage / name).write_text(content, encoding="utf-8")
        for attempt in range(4):
            for source, catalog in catalogs.items():
                if _hash(source) != catalog["sha256"]:
                    raise CircuitExportError("IBIS file changed before publication; reload assignments")
            if _json_bytes(list(cases)) != initial_bytes:
                raise CircuitExportError("Input reports changed during export; rerun the review")
            check_sources()
            if guard is not None:
                guard()
            if target.exists() or target.is_symlink():
                raise CircuitExportError("Destination appeared during export; nothing was overwritten")
            try:
                stage.rename(target)
                break
            except PermissionError as exc:
                # Windows scanners can briefly hold a newly closed staged file.
                # Retry only known sharing/access errors, preserving all guards.
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32) or attempt == 3:
                    raise
                time.sleep(.05 * 2 ** attempt)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {"schematic": str(target / "circuit.kicad_sch"), "project": str(target / "circuit.kicad_pro"),
            "manifest": str(target / "manifest.json"), "clipboard_text": clip_text,
            "clipboard_file": str(target / "clipboard.txt"), "model_files": [str(target / path) for path in relative.values()],
            "sheets": [str(target / name) for name, _ in pages]}
