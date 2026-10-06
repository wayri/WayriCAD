"""Analyze a saved KiCad PCB with QuickTherm; never modify the board."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("--config", type=Path, help="Reviewed JSON analysis settings for jobsets")
    parser.add_argument("--environment", choices=("air", "vacuum"))
    parser.add_argument("--power-field")
    parser.add_argument("--theta-ja-field")
    parser.add_argument("--theta-jb-field")
    parser.add_argument("--theta-jc-field")
    parser.add_argument("--heatsinks", type=Path, help="JSON mapping of reference to virtual heatsink")
    parser.add_argument("--thermal-refs", nargs="+", help="Dissipating component references")
    parser.add_argument("--temp-min-field", help="Saved footprint field for minimum junction °C")
    parser.add_argument("--temp-max-field", help="Saved footprint field for maximum junction °C")
    parser.add_argument("--probe", action="append", default=[], metavar="LABEL:X,Y:SIDE",
                        help="Virtual probe at board millimetres; SIDE is top or bottom")
    parser.add_argument("--require-limits-pass", action="store_true",
                        help="Exit nonzero unless every scoped component limit passes")
    parser.add_argument("--board-rtheta", type=float, help="Vacuum board-to-environment K/W")
    parser.add_argument("--ambient", type=float)
    parser.add_argument("--output", type=Path, help="JSON result")
    parser.add_argument("--html", type=Path, help="Self-contained HTML and companion JSON")
    parser.add_argument("--calculix-dir", type=Path,
                        help="New directory for an experimental Gmsh/CalculiX deck; needs calculix_settings in --config")
    parser.add_argument("--run-calculix", action="store_true",
                        help="Run ccx after deck creation when installed; FRD temperatures remain unparsed")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args(argv)
    try:
        board = args.board.resolve()
        for output in (args.output, args.html, args.calculix_dir):
            if output and output.resolve() == board:
                raise ValueError("Output must not overwrite the source PCB.")
        if args.config:
            if any((args.environment, args.power_field, args.theta_ja_field, args.theta_jb_field,
                    args.theta_jc_field, args.heatsinks, args.thermal_refs, args.board_rtheta,
                    args.ambient is not None, args.temp_min_field, args.temp_max_field, args.probe)):
                raise ValueError("Use either --config or individual thermal inputs.")
            if args.config.stat().st_size > 262144:
                raise ValueError("QuickTherm config exceeds 256 KiB.")
            settings = json.loads(args.config.read_text(encoding="utf-8"))
            allowed = {"environment", "ambient_c", "field_map", "references", "heatsinks",
                       "vacuum_board_to_environment_k_per_w", "thermal_network_settings",
                       "thermal_network_component_field", "thermal_model_kind", "mesh_acceptance",
                       "limit_fields", "probes", "calculix_settings"}
            if not isinstance(settings, dict) or set(settings) - allowed:
                raise ValueError("QuickTherm config has unsupported settings.")
            if not isinstance(settings.get("field_map"), dict) or not settings["field_map"].get("power_w"):
                raise ValueError("QuickTherm config must map a power_w footprint field.")
            request = {"action": "quick_therm", "board_path": str(board), **settings}
            request.setdefault("environment", "air")
            request.setdefault("ambient_c", 20.0)
        else:
            if not args.power_field:
                raise ValueError("Map --power-field or provide --config.")
            environment = args.environment or "air"
            heatsinks = {}
        if not args.config and args.heatsinks:
            if args.heatsinks.stat().st_size > 262144:
                raise ValueError("Virtual heatsink JSON exceeds 256 KiB.")
            heatsinks = json.loads(args.heatsinks.read_text(encoding="utf-8"))
            if not isinstance(heatsinks, dict):
                raise ValueError("Virtual heatsinks must be keyed by component reference.")
        if not args.config:
            if heatsinks and not args.theta_jc_field:
                raise ValueError("Map --theta-jc-field for virtual heatsinks.")
            field = args.theta_ja_field if environment == "air" else args.theta_jb_field
            if not field and not (heatsinks and args.thermal_refs and set(args.thermal_refs) <= set(heatsinks)):
                raise ValueError("Map RθJA/RθJB for components without heatsinks.")
            field_map = {"power_w": args.power_field}
            if field:
                key = "theta_ja_air_k_per_w" if environment == "air" else "theta_jb_k_per_w"
                field_map[key] = field
            if args.theta_jc_field:
                field_map["theta_jc_k_per_w"] = args.theta_jc_field
            probes = []
            for index, raw in enumerate(args.probe, 1):
                try:
                    label, coordinates, side = raw.split(":")
                    x, y = coordinates.split(",")
                    probes.append({"label": label or f"P{index}", "x_mm": float(x),
                                   "y_mm": float(y), "side": side})
                except (ValueError, TypeError) as exc:
                    raise ValueError("Use --probe LABEL:X,Y:top or LABEL:X,Y:bottom.") from exc
            request = {
                "action": "quick_therm", "board_path": str(board),
                "environment": environment, "ambient_c": 20.0 if args.ambient is None else args.ambient,
                "field_map": field_map, "heatsinks": heatsinks,
                "references": args.thermal_refs,
                "vacuum_board_to_environment_k_per_w": args.board_rtheta,
                "limit_fields": {key: name for key, name in (("minimum_c", args.temp_min_field),
                                                            ("maximum_c", args.temp_max_field)) if name},
                "probes": probes,
            }
        if args.html:
            request["html_output"] = str(args.html.resolve())
        if args.calculix_dir:
            request["calculix_export_dir"] = str(args.calculix_dir.resolve())
        if args.run_calculix:
            request["calculix_run"] = True
        if request.get("calculix_export_dir") and not isinstance(request.get("calculix_settings"), dict):
            raise ValueError("--calculix-dir needs calculix_settings in --config.")
        if request.get("calculix_settings") and not request.get("calculix_export_dir"):
            raise ValueError("calculix_settings needs --calculix-dir.")
        if args.run_calculix and not args.calculix_dir:
            raise ValueError("--run-calculix needs --calculix-dir.")
        from .service import run_job

        result = run_job(request, timeout=args.timeout)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps(result, indent=2, allow_nan=False))
        return 3 if args.require_limits_pass and result.get("temperature_limits", {}).get("status") != "PASS" else 0
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
