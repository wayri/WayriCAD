"""Run a reviewed, read-only four-board QuickTherm RC transient job."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="JSON model with four ordered saved boards")
    parser.add_argument("--output", required=True, type=Path, help="Full JSON evidence output")
    parser.add_argument("--csv", type=Path, help="Temperature and heat-flow time series")
    parser.add_argument("--svg", type=Path, help="Standalone junction/air temperature plot")
    parser.add_argument("--require-checks-pass", action="store_true",
                        help="Exit nonzero unless all declared thermal limits pass")
    args = parser.parse_args(argv)
    try:
        if args.config.stat().st_size > 1024*1024:
            raise ValueError("Transient config exceeds 1 MiB.")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        source_paths = {Path(board["board_path"]).resolve() for board in config.get("boards", [])}
        outputs = [path for path in (args.output, args.csv, args.svg) if path]
        if any(path.resolve() in source_paths or path.resolve() == args.config.resolve()
               for path in outputs):
            raise ValueError("Outputs cannot overwrite the config or source PCB files.")
        if len({path.resolve() for path in outputs}) != len(outputs):
            raise ValueError("JSON, CSV and SVG outputs must be different files.")
        from .service import run_job

        result = run_job({"action": "coupled_transient", **config})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"inputs": config, **result}, indent=2,
                                          allow_nan=False), encoding="utf-8")
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            with args.csv.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["time_s", "board", "inlet_air_c", "outlet_air_c",
                                 "power_w", "air_heat_w", "fixture_heat_w", "stored_heat_w",
                                 "energy_residual_w", "node", "temperature_c"])
                for sample in result["history"]:
                    for board in sample["boards"]:
                        for node, temperature in board["temperatures_c"].items():
                            writer.writerow([sample["time_s"], board["name"],
                                             board["inlet_air_c"], board["outlet_air_c"],
                                             board["power_w"], board["air_heat_w"],
                                             board["fixture_heat_w"], board["stored_heat_w"],
                                             board["energy_residual_w"],
                                             node, temperature])
        if args.svg:
            args.svg.parent.mkdir(parents=True, exist_ok=True)
            args.svg.write_text(_temperature_svg(result), encoding="utf-8")
        hashes = {"json": hashlib.sha256(args.output.read_bytes()).hexdigest()}
        if args.csv:
            hashes["csv"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        if args.svg:
            hashes["svg"] = hashlib.sha256(args.svg.read_bytes()).hexdigest()
        print(json.dumps({"status": result["status"],
                          "check_status": result["check_status"],
                          "model_sha256": result["model_sha256"],
                          "output": str(args.output), "csv": str(args.csv) if args.csv else None,
                          "svg": str(args.svg) if args.svg else None,
                          "output_sha256": hashes}))
        return 3 if args.require_checks_pass and result["check_status"] != "PASS" else 0
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


def _temperature_svg(result):
    """Plot the saved four-board junction and downstream-air time histories."""
    samples = result["history"]
    series = []
    colors = ("#1d6f91", "#ba4b34", "#577838", "#8a5aa8", "#3d5566",
              "#a16620", "#488b7e", "#bd7290")
    first = samples[0]["boards"]
    for index, board in enumerate(first):
        refs = [key for key in board["temperatures_c"] if key not in ("board",)
                and not key.endswith(" sink")]
        for ref in refs:
            series.append((f"{board['name']} {ref}",
                           [sample["boards"][index]["temperatures_c"][ref]
                            for sample in samples]))
        series.append((f"{board['name']} air out",
                       [sample["boards"][index]["outlet_air_c"] for sample in samples]))
    values = [value for _, line in series for value in line]
    ymin, ymax = min(values), max(values)
    if ymax-ymin < 1:
        ymax, ymin = ymax+.5, ymin-.5
    else:
        padding = (ymax-ymin)*.08
        ymin, ymax = ymin-padding, ymax+padding
    xmax = samples[-1]["time_s"]
    width, height = 1100, max(650, 115+len(series)*23)
    x = lambda time: 80+690*time/xmax
    y = lambda temperature: 550-480*(temperature-ymin)/(ymax-ymin)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
             'role="img" aria-label="QuickTherm temperature time histories">',
             f'<rect width="1100" height="{height}" fill="#f8fafb"/>',
             '<text x="80" y="36" font-size="22" font-family="sans-serif" fill="#173043">QuickTherm coupled-board transient</text>',
             '<path d="M80 70V550H770" fill="none" stroke="#40576a" stroke-width="2"/>',
             '<text x="320" y="604" font-family="sans-serif">Time (s)</text>',
             '<text x="8" y="60" font-family="sans-serif">°C</text>']
    for tick in range(6):
        value = ymin+(ymax-ymin)*tick/5
        yy = y(value)
        parts.append(f'<line x1="80" y1="{yy:.2f}" x2="770" y2="{yy:.2f}" '
                     'stroke="#dde5e8"/>')
        parts.append(f'<text x="28" y="{yy+4:.2f}" font-size="12" '
                     f'font-family="sans-serif">{value:.1f}</text>')
    for index, (label, line) in enumerate(series):
        color = colors[index % len(colors)]
        points = " ".join(f"{x(sample['time_s']):.2f},{y(value):.2f}"
                          for sample, value in zip(samples, line))
        dash = ' stroke-dasharray="5 4"' if label.endswith("air out") else ""
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" '
                     f'stroke-width="2"{dash}/>')
        legend_y = 85+index*23
        parts.append(f'<line x1="805" y1="{legend_y}" x2="833" y2="{legend_y}" '
                     f'stroke="{color}" stroke-width="3"{dash}/>')
        parts.append(f'<text x="843" y="{legend_y+4}" font-size="12" '
                     f'font-family="sans-serif" fill="#173043">{html.escape(label)}</text>')
    parts.append('</svg>')
    return "\n".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
