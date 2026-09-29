"""Keep the reproducible example portable and free of local file paths."""

import json
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    report = folder / "thermal-demo-report.json"
    bundle = json.loads(report.read_text(encoding="utf-8"))
    bundle["request"]["board_path"] = "examples/thermal-demo.kicad_pcb"
    bundle["request"]["html_output"] = "examples/thermal-demo-report.html"
    report.write_text(json.dumps(bundle, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    thermal = bundle["quick_therm"]
    summary = {
        "board": "examples/thermal-demo.kicad_pcb",
        "source_sha256": bundle["source_sha256"],
        "environment": thermal["environment"],
        "ambient_c": thermal["ambient_c"],
        "coverage": thermal["coverage"],
        "components": thermal["components"],
        "model": thermal["model"],
        "assumptions": thermal["assumptions"],
        "temperature_limits": bundle.get("temperature_limits"),
        "probes": bundle.get("probes"),
        "board_model": ({"status": bundle["thermal_network"]["status"],
                         "sampled_min_c": bundle["thermal_network"]["board_field"]["sampled_min_c"],
                         "sampled_max_c": bundle["thermal_network"]["board_field"]["sampled_max_c"],
                         "heat_balance": bundle["thermal_network"]["heat_balance"]}
                        if bundle.get("thermal_network") else None),
    }
    (folder / "thermal-demo-result.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for suffix in (".kicad_prl", ".kicad_pro"):
        generated = folder / ("thermal-demo" + suffix)
        if generated.is_file():
            generated.unlink()


if __name__ == "__main__":
    main()
