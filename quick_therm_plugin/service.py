"""Read-only saved-board inspection and thermal analysis in a bounded worker."""

import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time


def run_job(request, cancelled=None, timeout=1800, progress=None):
    if not math.isfinite(float(timeout)) or float(timeout) <= 0:
        raise ValueError("Worker timeout must be finite and positive.")
    if cancelled and cancelled():
        raise InterruptedError("QuickTherm cancelled before starting the worker.")
    from wayricad_runtime.runtime_setup import (
        REQUIREMENTS_QUICK_THERM, child_environment, ensure_runtime,
    )

    requirements = {name: spec for name, spec in REQUIREMENTS_QUICK_THERM.items()
                    if name != "kipy"}
    if (request.get("thermal_model_kind") == "calculix" or
            request.get("calculix_export_dir") or request.get("calculix_run")):
        import shutil
        if not shutil.which("gmsh"):
            requirements["gmsh"] = "gmsh>=4.11,<5"
    python = ensure_runtime(requirements)
    with tempfile.TemporaryDirectory(prefix="wayricad-quick-therm-") as temporary:
        root = Path(temporary)
        source, target = root / "request.json", root / "response.json"
        payload = dict(request, _emit_progress=bool(progress))
        source.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        log_path = root / "worker.log"
        with log_path.open("w+", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(python), "-I", str(Path(__file__).with_name("quickmain.py")),
                 "--worker", str(source), str(target)],
                env=child_environment(), stdin=subprocess.DEVNULL,
                stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            started = time.monotonic()
            progress_offset = 0

            def read_progress():
                nonlocal progress_offset
                if progress is None:
                    return
                with log_path.open("r", encoding="utf-8", errors="replace") as reader:
                    reader.seek(progress_offset)
                    while True:
                        line = reader.readline()
                        if not line or not line.endswith("\n"):
                            break
                        progress_offset = reader.tell()
                        if line.startswith("WAYRICAD_PROGRESS "):
                            try:
                                progress(json.loads(line[len("WAYRICAD_PROGRESS "):]))
                            except Exception:
                                pass
            try:
                while process.poll() is None:
                    if cancelled and cancelled():
                        raise InterruptedError("QuickTherm cancelled. No PCB files were changed.")
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("QuickTherm exceeded its time budget. Review mesh resolution and progress before retrying.")
                    read_progress()
                    time.sleep(0.1)
                read_progress()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            log.seek(0)
            details = log.read()[-4000:]
            if not target.is_file():
                raise RuntimeError("QuickTherm worker did not produce a result. " + details)
            try:
                result = json.loads(target.read_text(encoding="utf-8-sig"))
            except (ValueError, OSError) as exc:
                raise RuntimeError("QuickTherm worker returned incomplete output. " + details) from exc
            if not isinstance(result, dict):
                raise RuntimeError("QuickTherm worker returned an invalid result object. " + details)
            if result.get("error"):
                raise ValueError(result["error"])
            if process.returncode:
                raise RuntimeError("QuickTherm worker failed: " + details)
            return result


def execute(request):
    """Return a source-hashed inventory or a scoped thermal result."""
    def emit_progress(stage, completed, total, elapsed, eta):
        if request.get("_emit_progress"):
            print("WAYRICAD_PROGRESS " + json.dumps({
                "stage": stage, "completed": completed, "total": total,
                "percent": 100*completed/total if total else 100,
                "elapsed_s": elapsed, "eta_s": eta}, allow_nan=False), flush=True)

    if request.get("action") == "coupled_transient":
        from .thermal_transient import run_saved_board_transient

        return run_saved_board_transient(request)
    import pcbnew

    path = Path(request["board_path"]).resolve()
    if not path.is_file() or path.suffix.lower() != ".kicad_pcb":
        raise ValueError("Choose a saved KiCad PCB.")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    if request.get("expected_source_sha256") and request["expected_source_sha256"] != before:
        raise ValueError("The saved PCB changed since it was loaded. Reload it and review the thermal inputs.")
    board = pcbnew.LoadBoard(str(path))
    if board is None:
        raise ValueError("KiCad could not load this PCB.")
    action = request.get("action", "inspect")
    if action == "inspect":
        from .quick_therm import _footprint_properties

        footprints = list(board.GetFootprints())
        components = [fp for fp in footprints if "*" not in str(fp.GetReference())]
        field_names = sorted({name for fp in components for name in _footprint_properties(fp)})
        mounting_holes = []
        for fp in footprints:
            for pad in fp.Pads():
                if pad.GetAttribute() not in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    continue
                drill = pcbnew.ToMM(pad.GetDrillSize().x)
                if drill <= 0:
                    continue
                mounting_holes.append({
                    "id": pad.m_Uuid.AsString(), "reference": fp.GetReference(),
                    "pad_number": str(pad.GetNumber()), "net": str(pad.GetNetname()),
                    "plated": pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH,
                    "drill_mm": drill,
                })
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError("The board changed during inspection. Reload and run again.")
        return {
            "component_references": sorted(fp.GetReference() for fp in components),
            "field_names": field_names, "mounting_holes": mounting_holes,
            "source_sha256": before,
        }
    if action != "quick_therm":
        raise ValueError("Unknown QuickTherm action: " + str(action))

    from .quick_therm import analyze_board, analyze_manual_board, analyze_power_sources
    from .thermal_board_view import build_board_thermal_view

    options = dict(environment=request["environment"], ambient_c=request.get("ambient_c", 20.0),
                   references=request.get("references"),
                   vacuum_board_to_environment_k_per_w=request.get("vacuum_board_to_environment_k_per_w"),
                   heatsinks=request.get("heatsinks"))
    spatial_power_only = (request.get("transient_settings") is not None or
                          request["environment"] in ("forced_air", "potting", "sealed") or
                          (request["environment"] == "vacuum" and
                           request.get("thermal_model_kind") == "multilayer"))
    if spatial_power_only and request.get("thermal_network_settings") is None:
        raise ValueError("Expanded environment and transient models need thermal_network_settings.")
    if spatial_power_only and request.get("thermal_model_kind") != "multilayer":
        raise ValueError("Expanded environment and transient models require multilayer board mode.")
    if request.get("transient_settings") is not None and request.get("mesh_acceptance") is not None:
        raise ValueError("Run transient spatial refinement as separate explicit grid analyses.")
    if request.get("thermal_model_kind") == "calculix" or spatial_power_only:
        result = analyze_power_sources(
            board, environment=request["environment"],
            ambient_c=request.get("ambient_c", 20.0),
            references=request.get("references"),
            field_map=request.get("field_map"),
            manual_values=request.get("manual_values") if request.get("input_mode") == "manual" else None)
        if result["coverage"]["excluded"]:
            raise ValueError("Board field needs valid power for every selected component: " +
                             ", ".join(row["reference"] for row in result["coverage"]["excluded"]))
    elif request.get("input_mode") == "manual":
        result = analyze_manual_board(board, request.get("manual_values"), **options)
    else:
        result = analyze_board(board, request["field_map"], **options)
    view = build_board_thermal_view(board, result)
    thermal_network = None
    calculix_manifest = None
    geometry = None

    def export_calculix(snapshot):
        from .thermal_calculix import prepare_calculix, run_calculix
        from contextlib import ExitStack
        import tempfile

        settings = request.get("calculix_settings")
        if not isinstance(settings, dict):
            raise ValueError("CalculiX export needs explicit calculix_settings.")
        with ExitStack() as stack:
            directory = request.get("calculix_export_dir")
            if not directory:
                directory = str(Path(stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="wayricad-therm-"))) / "candidate")
            manifest = prepare_calculix(snapshot, view, result, settings, directory)
            field = None
            if request.get("calculix_run") or request.get("thermal_model_kind") == "calculix":
                if manifest["status"] != "deck_ready":
                    raise ValueError("CalculiX mesh preparation failed: " +
                                     manifest.get("diagnostic", manifest["status"]))
                manifest = run_calculix(directory, ccx=request.get("calculix_executable"),
                                        display_grid_mm=settings.get("display_grid_mm"))
                if manifest["status"] != "solved":
                    raise ValueError("CalculiX result unavailable: " +
                                     manifest.get("diagnostic", manifest["status"]))
                field = json.loads((Path(directory)/manifest["field_file"]).read_text(encoding="utf-8"))
            if not request.get("calculix_export_dir"):
                manifest.pop("field_file", None)
                manifest.pop("result_file", None)
                manifest["artifacts_retained"] = False
            return manifest, field

    if request.get("calculix_run") and not request.get("calculix_export_dir") and request.get("thermal_model_kind") != "calculix":
        raise ValueError("CalculiX execution needs an export directory.")
    if request.get("thermal_model_kind") == "calculix" and request.get("thermal_network_settings") is None:
        raise ValueError("CalculiX board mode needs thermal_network_settings.")
    if request.get("thermal_network_settings") is not None:
        settings = dict(request["thermal_network_settings"])
        if request.get("transient_settings") is not None:
            settings["transient_settings"] = request["transient_settings"]
        settings["board_thickness_mm"] = view.get("board_thickness_mm")
        board_field = request.get("thermal_network_component_field")
        missing = []
        if board_field:
            from .quick_therm import _footprint_properties, parse_field_quantity

            footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
            resistances = {}
            for row in result["components"]:
                if row["heat_path"] != "board":
                    continue
                raw = _footprint_properties(footprints[row["reference"]]).get(board_field)
                if raw is None or not str(raw).strip():
                    missing.append(row["reference"])
                    continue
                resistances[row["reference"]] = parse_field_quantity(raw, "theta_jb_k_per_w")
            settings["component_to_board_k_per_w"] = resistances
        elif (request.get("thermal_model_kind") == "calculix" or spatial_power_only) and request.get("input_mode") == "manual":
            from .quick_therm import parse_field_quantity

            settings["component_to_board_k_per_w"] = {
                ref: parse_field_quantity(values["theta_jb_k_per_w"], "theta_jb_k_per_w")
                for ref, values in request.get("manual_values", {}).items()
                if "theta_jb_k_per_w" in values}
        sink_resistances = {}
        sink_key = ("theta_sa_air_k_per_w" if request["environment"] == "air"
                    else "theta_sa_vacuum_k_per_w")
        for row in result["components"]:
            if row["heat_path"] == "heatsink":
                sink_resistances[row["reference"]] = (
                    row["resistance_k_per_w"] - row["heatsink"][sink_key]
                )
        if sink_resistances:
            settings["component_to_sink_k_per_w"] = sink_resistances
        if request.get("thermal_model_kind") in ("multilayer", "calculix"):
            from .thermal_geometry import collect_thermal_geometry

            geometry = collect_thermal_geometry(
                board, path, contact_pads=settings.get("source_contact_pad_numbers"),
                progress=emit_progress)
            if request.get("thermal_model_kind") == "calculix":
                calculix_manifest, thermal_network = export_calculix(geometry)
                thermal_network["settings"] = dict(request["calculix_settings"])
                thermal_network["assumptions"] = list(calculix_manifest.get("limitations", []))
                from .thermal_review import cursor_readout

                components = []
                for part in view.get("components", []):
                    if not part.get("position_mm") or not part.get("on_board", True):
                        continue
                    x, y = part["position_mm"]
                    site = cursor_readout(view, thermal_network, x, y, part["side"])["temperature_c"]
                    power = next((row["power_w"] for row in result["components"]
                                  if row["reference"] == part["reference"]), 0)
                    rjb = settings.get("component_to_board_k_per_w", {}).get(part["reference"])
                    components.append({"reference": part["reference"], "board_site_c": site,
                                       "junction_c": site + power*rjb if site is not None and rjb is not None else None,
                                       "junction_method": "board site + declared RthetaJB" if rjb is not None else "unknown"})
                thermal_network["components"] = components
                modeled = {row["reference"]: row for row in components}
                for row in result["components"]:
                    junction = modeled[row["reference"]]["junction_c"]
                    if junction is not None:
                        row["junction_c"] = junction
                        row["rise_above_ambient_k"] = junction-result["ambient_c"]
                        row["rise_local_k"] = row["power_w"] * settings["component_to_board_k_per_w"][row["reference"]]
                        row["resistance_k_per_w"] = settings["component_to_board_k_per_w"][row["reference"]]
                result["coverage"]["solved"] = sum(row["junction_c"] is not None for row in result["components"])
                result["assumptions"].append("Modeled junctions use the solved board site plus declared RÎ¸JB; others remain unknown.")
                view = build_board_thermal_view(board, result)
            elif request.get("calculix_export_dir"):
                calculix_manifest, _ = export_calculix(geometry)
            if request.get("thermal_model_kind") == "calculix":
                # The checked external field is already the board model.
                pass
            elif request.get("mesh_acceptance") is not None:
                from .thermal_multilayer import solve_multilayer_thermal_convergence
                thermal_network = solve_multilayer_thermal_convergence(
                    geometry, view, result, settings, request["mesh_acceptance"],
                    progress=emit_progress)
            else:
                from .thermal_multilayer import solve_multilayer_thermal
                thermal_network = solve_multilayer_thermal(
                    geometry, view, result, settings, progress=emit_progress)
        else:
            from .thermal_network import solve_thermal_network

            thermal_network = solve_thermal_network(view, result, settings)
        thermal_network["junction_mapping"] = {
            "board_field": board_field,
            "board_references_with_field": sorted(settings.get("component_to_board_k_per_w", {})),
            "board_references_missing_field": missing,
            "sink_references_from_explicit_rtheta_jc_and_contact": sorted(sink_resistances),
        }
    if request.get("calculix_export_dir") and calculix_manifest is None:
        from .thermal_geometry import collect_thermal_geometry

        geometry = collect_thermal_geometry(board, path, progress=emit_progress)
        calculix_manifest, imported = export_calculix(geometry)
        if imported is not None:
            thermal_network = imported
            thermal_network["settings"] = dict(request["calculix_settings"])
            thermal_network["assumptions"] = list(calculix_manifest.get("limitations", []))
    from .thermal_review import evaluate_limits, sample_probes

    limits = evaluate_limits(board, result, request.get("limit_fields"))
    probes = sample_probes(view, thermal_network, request.get("probes"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError("The board changed during QuickTherm analysis. Reload and run again.")

    return {
        "quick_therm": result, "board_thermal_view": view,
        "thermal_network": thermal_network,
        "calculix": calculix_manifest,
        "request": {key: value for key, value in request.items() if key != "_emit_progress"},
        "temperature_limits": limits, "probes": probes,
        "source_sha256": before,
    }
