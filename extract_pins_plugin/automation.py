"""Machine-facing KiWay capability registry and JSON-RPC control plane."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, TextIO


SCHEMA = "kiway.control/v1"
JSONRPC = "2.0"
ROOT = Path(__file__).resolve().parent.parent


PLUGIN_CAPABILITIES = (
    ("bulk-label-editor", "KiWay Bulk Label Editor", ("preview", "apply"), True, "board"),
    ("extract-pins", "KiWay Pin Extractor", ("inspect", "extract", "crosslink", "report"), False, "netlist"),
    ("fanout-generator", "KiWay Fanout Generator", ("plan", "preview", "apply"), True, "board"),
    ("harness-workbench", "KiWay Harness and Cable Workbench", ("build", "validate", "export"), False, "documents"),
    ("heater-designer", "KiWay PCB / Foil Heater Designer", ("analyze", "simulate", "apply"), True, "model"),
    ("kilo", "Kilo - KiCad Localizer", ("scan", "validate", "localize", "repair"), True, "project"),
    ("manufacturing-readiness", "KiWay Manufacturing Readiness Manager", ("audit", "release"), True, "project"),
    ("pdn-decoupling", "KiWay PDN and Decoupling Planner", ("analyze",), False, "geometry"),
    ("planar-magnetics", "KiWay Planar Magnetics & Actuator Workbench", ("analyze", "simulate", "apply"), True, "model"),
    ("portable-assets", "KiWay Portable Assets", ("analyze", "apply", "restore"), True, "project"),
    ("protocol-constraints", "KiWay Protocol Constraint Composer", ("detect", "compose", "apply"), True, "nets"),
    ("return-path-auditor", "KiWay Return-Path Auditor", ("audit",), False, "geometry"),
    ("signal-integrity", "KiWay Signal Integrity Advisor", ("i2c-pullup", "impedance"), False, "geometry"),
    ("test-point-descriptor", "KiWay Test Point Descriptor Extractor", ("extract", "fixture"), True, "board"),
    ("trace-impedance", "KiWay Trace RLC / Impedance Analyzer", ("measure",), False, "board"),
    ("variant-workbench", "KiWay Design Variant Workbench", ("inspect", "plan", "apply"), True, "project"),
    ("via-stitching", "KiWay Via Stitching", ("plan", "preview", "apply"), True, "board"),
)


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "transport": {"one_shot": "kiway run --request FILE|-", "stdio": "kiway serve --stdio", "protocol": "JSON-RPC 2.0 / NDJSON"},
        "safety": {"writes_require_apply": True, "stdout_is_machine_data": True, "stderr_is_diagnostics": True},
        "plugins": [
            {"id": key, "name": name, "actions": list(actions), "mutating_actions_present": mutating,
             "input_kind": input_kind}
            for key, name, actions, mutating, input_kind in PLUGIN_CAPABILITIES
        ],
        "operations": sorted(HANDLERS),
    }


def _module(relative: str, key: str):
    path = ROOT / relative
    name = f"_kiway_headless_{key}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load KiWay backend: {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _harness_build(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("harness_workbench_plugin/analysis.py", "harness")
    documents = [Path(item) for item in params.get("documents", [])]
    records = module.load_pin_documents(documents, int(params.get("maximum_projects", 50)))
    rows = []
    if params.get("mapping_csv"):
        rows.extend(module.load_pin_map_csv(params["mapping_csv"]))
    for item in params.get("mappings", []):
        rows.append(module.PinMapRow(**item))
    links = module.links_from_pin_map(records, rows)
    rules = module.parse_connector_rules(params.get("connector_rules", ""))
    links.extend(module.connector_correspondence(records, rules))
    if params.get("auto_match", False):
        links.extend(module.auto_link_multi(records, params.get("net_pattern", "*"),
                                            bool(params.get("regex", False)), bool(params.get("include_power", False))))
    unique = {}
    for link in links:
        key = (link.source.project, link.source.connector, link.source.pin,
               link.destination.project, link.destination.connector, link.destination.pin)
        unique[key] = link
    links = list(unique.values())
    for number, link in enumerate(links, 1):
        if not link.wire_id:
            link.wire_id = f"W{number:05d}"
    board_paths = module.load_signal_path_documents([Path(item) for item in params.get("path_documents", [])])
    system_paths = module.build_system_signal_paths(
        links, board_paths, params.get("source_refs", "U*"), params.get("destination_refs", "U*"),
        bool(params.get("include_partial", True)))
    result = {
        "records": len(records), "links": [_plain(item) for item in links],
        "pin_map": module.pin_map_rows(links), "net_map": module.net_map_rows(links),
        "system_paths": module.system_signal_rows(system_paths),
        "bom": module.harness_bom(records, links),
        "findings": module.validate_pin_map(records, rows) + module.validate_links(links),
    }
    if params.get("include_html", False):
        from harness_workbench_plugin.report import interactive_harness_html
        result["html"] = interactive_harness_html(records, links, system_paths=system_paths,
                                                   title=params.get("title", "KiWay Interactive System Harness"))
    return result


def _i2c_pullup(params: dict[str, Any]) -> dict[str, Any]:
    voltage = float(params["voltage_v"]); capacitance = float(params["capacitance_pf"])
    rise_time = float(params["rise_time_ns"]); sink_current = float(params["sink_current_ma"])
    low_level = float(params.get("low_level_v", 0.4))
    if min(voltage, capacitance, rise_time, sink_current) <= 0:
        raise ValueError("Voltage, capacitance, rise time, and sink current must be positive.")
    minimum = (voltage - low_level) / (sink_current / 1000.0)
    maximum = (rise_time * 1e-9) / (0.8473 * capacitance * 1e-12)
    e24 = (10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91)
    candidates = sorted(base * 10 ** decade for decade in range(7) for base in e24
                        if minimum <= base * 10 ** decade <= maximum)
    return {"minimum_ohm": minimum, "maximum_ohm": maximum,
            "recommended_ohm": candidates[len(candidates) // 2] if candidates else None,
            "status": "PASS" if minimum <= maximum else "FAIL", "standard_values_ohm": candidates}


def _protocol_compose(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("protocol_constraint_composer_plugin/analysis.py", "protocol")
    assignments = module.detect_protocols([str(item) for item in params.get("nets", [])])
    return {"assignments": [_plain(item) for item in assignments], "rules": module.generate_rules(assignments)}


def _manufacturing_audit(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("manufacturing_readiness_plugin/analysis.py", "manufacturing")
    profile = module.FabricatorProfile(**params.get("profile", {}))
    metrics = module.BoardMetrics(**params["metrics"])
    checks = module.audit_metrics(metrics, profile)
    return {"status": "FAIL" if any(item.status == "FAIL" for item in checks) else "PASS",
            "checks": [_plain(item) for item in checks]}


def _heater_analyze(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("heater_designer_plugin/analysis.py", "heater")
    spec_data = dict(params.get("spec", {}))
    spec_data["zones"] = tuple(module.HeatZone(**item) for item in spec_data.get("zones", []))
    result = module.HeaterEngine.generate(module.HeaterSpec(**spec_data))
    output = _plain(result)
    if params.get("thermal") is not None:
        thermal = module.HeaterEngine.simulate(result, module.ThermalSpec(**params["thermal"]))
        output["thermal"] = _plain(thermal)
    return output


def _pdn_analyze(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("pdn_decoupling_plugin/analysis.py", "pdn")
    pads = [module.PadNode(**item) for item in params.get("pads", [])]
    findings = module.analyze_decoupling(pads, params.get("rail_patterns", "VCC*,VDD*,*V"),
                                         params.get("ground_patterns", "GND*,VSS*"),
                                         params.get("capacitor_patterns", "C*"), params.get("load_patterns", "U*"),
                                         float(params.get("maximum_distance_mm", 3.0)))
    return {"findings": [_plain(item) for item in findings], "regulators": module.infer_regulators(pads)}


def _bulk_preview(params: dict[str, Any]) -> dict[str, Any]:
    pattern = str(params.get("pattern", "")); replacement = str(params.get("replacement", ""))
    case_sensitive = bool(params.get("case_sensitive", False)); use_regex = bool(params.get("regex", False))
    if not pattern:
        raise ValueError("pattern is required")
    changes = []
    for item in params.get("values", []):
        current = str(item)
        if use_regex:
            new = re.sub(pattern, replacement, current, flags=0 if case_sensitive else re.IGNORECASE)
        else:
            expression = "^" + "".join("(.*)" if char == "*" else "(.{1})" if char == "?" else re.escape(char)
                                              for char in pattern) + "$"
            match = re.match(expression, current, flags=0 if case_sensitive else re.IGNORECASE)
            new = current
            if match:
                captures = []; group = 1
                for char in pattern:
                    if char == "*": captures.append(match.group(group)); group += 1
                    elif char == "?": group += 1
                new = replacement
                for capture in captures: new = new.replace("*", capture, 1)
        if new != current:
            changes.append({"current": current, "new": new})
    return {"matched": len(changes), "changes": changes, "applied": False}


def _return_path_audit(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("return_path_auditor_plugin/analysis.py", "return_path")
    segments = [module.CopperSegment(**item) for item in params.get("segments", [])]
    vias = [module.ViaPoint(**item) for item in params.get("vias", [])]
    references = [module.ReferenceRegion(**item) for item in params.get("references", [])]
    analyzer = module.ReturnPathAnalyzer(params.get("ground_patterns", ("GND", "AGND", "DGND", "PGND", "VSS")))
    result = analyzer.audit(segments, vias, references,
                            float(params.get("return_via_radius_mm", 2.0)), float(params.get("stub_limit_mm", 5.0)),
                            float(params.get("differential_gap_limit_mm", 1.0)),
                            float(params.get("differential_skew_limit_mm", 0.5)))
    return _plain(result)


def _magnetics_analyze(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("planar_magnetics_plugin/analysis.py", "magnetics")
    actuator = str(params.get("actuator", "Voice coil"))
    result = module.MagneticsEngine.analyze(module.CoilSpec(**params.get("spec", {})), actuator=actuator)
    output = _plain(result)
    if params.get("motion") is not None:
        output["dynamics"] = _plain(module.MagneticsEngine.simulate_dynamics(
            result, module.MotionSpec(**params["motion"]), actuator=actuator))
    return output


def _fixture_generate(params: dict[str, Any]) -> dict[str, Any]:
    module = _module("test_point_descriptor_plugin/fixture.py", "fixture")
    points = [module.FixturePoint(**item) for item in params.get("points", [])]
    board = module.generate_fixture_board(points, str(params.get("probe_type", "P75")),
                                          float(params.get("connector_pitch_mm", 2.54)),
                                          float(params.get("margin_mm", 10.0)))
    return {"point_count": len(points), "board_text": board}


HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "bulk-label.preview": _bulk_preview,
    "harness.build": _harness_build,
    "signal-integrity.i2c-pullup": _i2c_pullup,
    "protocol-constraints.compose": _protocol_compose,
    "manufacturing.audit": _manufacturing_audit,
    "heater.analyze": _heater_analyze,
    "magnetics.analyze": _magnetics_analyze,
    "pdn.analyze": _pdn_analyze,
    "return-path.audit": _return_path_audit,
    "test-point.fixture": _fixture_generate,
}


def execute(request: dict[str, Any]) -> dict[str, Any]:
    request_id = request.get("id", request.get("request_id"))
    method = request.get("method", request.get("operation", ""))
    params = request.get("params", request.get("parameters", {})) or {}
    try:
        if method == "capabilities":
            result = capabilities()
        elif method in HANDLERS:
            result = HANDLERS[method](params)
        else:
            raise KeyError(f"Unknown operation: {method}")
        return {"jsonrpc": JSONRPC, "id": request_id, "result": _plain(result)}
    except KeyError as exc:
        return {"jsonrpc": JSONRPC, "id": request_id,
                "error": {"code": -32601, "message": str(exc)}}
    except (TypeError, ValueError) as exc:
        return {"jsonrpc": JSONRPC, "id": request_id,
                "error": {"code": -32602, "message": str(exc), "type": exc.__class__.__name__}}
    except Exception as exc:
        return {"jsonrpc": JSONRPC, "id": request_id,
                "error": {"code": -32000, "message": str(exc), "type": exc.__class__.__name__}}


def serve(input_stream: TextIO, output_stream: TextIO) -> int:
    """Process newline-delimited JSON-RPC requests until EOF."""
    for line_number, line in enumerate(input_stream, 1):
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            response = execute(request)
        except Exception as exc:
            response = {"jsonrpc": JSONRPC, "id": None,
                        "error": {"code": -32700, "message": f"Line {line_number}: {exc}"}}
        output_stream.write(json.dumps(response, sort_keys=True) + "\n")
        output_stream.flush()
    return 0
