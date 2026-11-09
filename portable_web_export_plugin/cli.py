"""Headless self-contained HTML export for saved KiCad projects."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path

from .exporter import ExportSelection, export_html, scan_project


def _select(values: list[str] | None, available: list[tuple[str, object]], label: str) -> tuple:
    if not values:
        return tuple(item for _name, item in available)
    selected = []
    unmatched = []
    for pattern in values:
        matches = [item for name, item in available if fnmatch.fnmatchcase(name.casefold(), pattern.casefold())]
        if not matches:
            unmatched.append(pattern)
        for item in matches:
            if item not in selected:
                selected.append(item)
    if unmatched:
        raise ValueError(f"No {label} matched: {', '.join(unmatched)}")
    return tuple(selected)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path, help="Saved .kicad_pcb source")
    parser.add_argument("output", type=Path, help="New self-contained .html destination")
    parser.add_argument("--sheet", action="append", help="Project-relative sheet glob; repeat to combine")
    parser.add_argument("--model", action="append", help="Saved model-path glob; repeat to combine")
    parser.add_argument("--no-schematic", action="store_true")
    parser.add_argument("--no-pcb", action="store_true")
    parser.add_argument("--no-bom", action="store_true")
    parser.add_argument("--no-3d", action="store_true")
    parser.add_argument("--manifest", type=Path, help="Optional separate JSON traceability manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        scan = scan_project(args.board)
        output = args.output.resolve()
        source_paths = {scan.board.resolve(), *(path.resolve() for path in scan.schematics)}
        if output in source_paths:
            raise ValueError("Output must not overwrite a KiCad source file.")
        sheet_choices = [(path.relative_to(scan.project_root).as_posix(), path) for path in scan.schematics]
        model_choices = [(model.source, model.source) for model in scan.models if model.supported]
        selection = ExportSelection(
            include_schematic=not args.no_schematic,
            include_pcb=not args.no_pcb,
            include_bom=not args.no_bom,
            include_3d=not args.no_3d,
            schematic_paths=_select(args.sheet, sheet_choices, "schematic sheet"),
            model_sources=_select(args.model, model_choices, "supported model"),
        )
        manifest = export_html(scan, selection, output, Path(__file__).resolve().parent)
        if args.manifest:
            manifest_path = args.manifest.resolve()
            if manifest_path in source_paths or manifest_path == output:
                raise ValueError("Manifest must use a separate non-source path.")
            _write_json(manifest_path, manifest)
        print(json.dumps({"output": str(output), "manifest": manifest}, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
