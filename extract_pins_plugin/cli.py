#!/usr/bin/env python3
"""KiWay command line interface.

The CLI is intentionally built on KiWay core modules that do not import wx or
pcbnew. Commands that need an open PCB load pcbnew only inside the adapter
function, so XML/netlist, cross-project, validation, reporting, and benchmark
workflows run in normal Python.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .core.cross_linker import CrossProjectLinker, PinDocumentImporter, parse_link_rules
from .core.diagram_generator import SVGDiagramGenerator
from .core.doc_generator import DocGenerator
from .core.schematic_graph import SchematicGraphParser

VERSION = "2.10.0"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_RUNTIME = 1


class CliError(Exception):
    """Expected CLI failure with a stable exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_RUNTIME, diagnostics: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.diagnostics = diagnostics or {}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return EXIT_USAGE
    try:
        merged = merge_config(args)
        return int(merged.func(merged) or EXIT_OK)
    except CliError as exc:
        emit_diagnostic("error", str(exc), args, exc.diagnostics)
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        emit_diagnostic("error", str(exc), args, {"type": exc.__class__.__name__})
        return EXIT_RUNTIME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kiway",
        description="KiWay electrical systems CLI for KiCad projects, netlists, cross-linking, validation, reports, and benchmarks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"KiWay {VERSION}")
    parser.add_argument("--config", help="JSON configuration file. CLI flags override config values.")
    parser.add_argument("--diagnostics", choices=("text", "json"), default="text", help="Diagnostic format on stderr.")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error diagnostics.")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    add_inspect(sub)
    add_extract(sub)
    add_crosslink(sub)
    add_validate(sub)
    add_report(sub)
    add_benchmark(sub)
    add_dependencies(sub)
    add_test(sub)
    add_legacy_board_commands(sub)
    return parser


def add_common_project_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("inputs", nargs="+", help="KiCad XML netlist files, .net files, or directories containing them.")
    p.add_argument("--board-sequence", default="", help="Comma-separated board tokens used for TM/TC source/destination parsing.")
    p.add_argument("--sheet-alias", action="append", default=[], help="Sheet alias rule: Name:path_glob:ref_glob. Repeatable.")
    p.add_argument("-f", "--format", choices=("json", "csv", "md", "markdown", "html", "svg"), default="json")
    p.add_argument("-o", "--output", help="Output path. Defaults to stdout.")


def add_inspect(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("inspect", help="Inspect project/netlist structure without pcbnew.")
    add_common_project_args(p)
    p.add_argument("--include-pins", action="store_true", help="Include per-component pin rows.")
    p.set_defaults(func=cmd_inspect)


def add_extract(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("extract", help="Extract pins, connectors, test points, TM/TC rows, or interfaces.")
    add_common_project_args(p)
    p.add_argument("--kind", choices=("pins", "connectors", "testpoints", "tm-tc", "interfaces"), default="pins")
    p.add_argument("--consolidate", action="store_true", help="Consolidate TM/TC rows by net.")
    p.add_argument("--include-power", action="store_true", help="Include likely power nets where filtering applies.")
    p.set_defaults(func=cmd_extract)


def add_crosslink(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("crosslink", help="Link pins across imported CSV/Markdown project exports.")
    p.add_argument("documents", nargs="+", help="CSV or Markdown pin documents.")
    p.add_argument("--project", action="append", default=[], help="Project name for each document. Defaults to file stem.")
    p.add_argument("--rules", default="", help="Inline rules: Name | wildcard/regex | source | destination.")
    p.add_argument("--rules-file", help="File containing cross-link rules.")
    p.add_argument("--no-exact", action="store_true", help="Disable exact matching.")
    p.add_argument("--no-normalized", action="store_true", help="Disable normalized matching.")
    p.add_argument("--include-power", action="store_true", help="Allow power-net links.")
    p.add_argument("--max-links", type=int, default=50000, help="Safety limit for generated links.")
    p.add_argument("-f", "--format", choices=("json", "csv", "md", "markdown", "html", "svg"), default="json")
    p.add_argument("-o", "--output", help="Output path. Defaults to stdout.")
    p.set_defaults(func=cmd_crosslink)


def add_validate(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("validate", help="Run deterministic validation checks on project/netlist data and optional imports.")
    add_common_project_args(p)
    p.add_argument("--imports", nargs="*", default=[], help="Imported CSV/Markdown pin documents to cross-link and validate.")
    p.add_argument("--require-tm-consumer", action="store_true", help="Fail if TM rows do not name a destination board.")
    p.add_argument("--require-tc-origin", action="store_true", help="Fail if TC rows do not name a source board.")
    p.set_defaults(func=cmd_validate)


def add_report(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("report", help="Generate ICD Markdown/HTML/CSV/JSON/SVG reports.")
    add_common_project_args(p)
    p.add_argument("--title", default="KiWay Interface Control Document")
    p.add_argument("--imports", nargs="*", default=[], help="Imported CSV/Markdown pin documents to include as cross-project tracker.")
    p.add_argument("--rules", default="", help="Cross-link rules for imports.")
    p.set_defaults(func=cmd_report)


def add_benchmark(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("benchmark", help="Run non-flaky synthetic parser/linker benchmarks.")
    p.add_argument("--nets", type=int, default=2000, help="Synthetic net count.")
    p.add_argument("--boards", type=int, default=4, help="Synthetic board count.")
    p.add_argument("--threshold-ms", type=int, default=2500, help="Warn/fail threshold for total benchmark time.")
    p.add_argument("-f", "--format", choices=("json", "csv", "md", "markdown"), default="json")
    p.add_argument("-o", "--output", help="Output path. Defaults to stdout.")
    p.set_defaults(func=cmd_benchmark)


def add_dependencies(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("dependencies", help="Check or install dependencies for the complete KiWay suite.")
    p.add_argument("--install", action="store_true", help="Install missing required and recommended dependencies.")
    p.add_argument("--all", action="store_true", help="Include optional dependencies when installing.")
    p.add_argument("--dry-run", action="store_true", help="Print the pip command without executing it.")
    p.add_argument("--no-user", action="store_true", help="Install into the active environment instead of its user-site.")
    p.add_argument("-o", "--output", help="Write the deterministic JSON health report to this path.")
    p.set_defaults(func=cmd_dependencies)


def add_test(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("test", help="Run KiWay's automated test suite.")
    p.add_argument("pytest_args", nargs="*", help="Additional unittest/pytest arguments.")
    p.set_defaults(func=cmd_test)


def add_legacy_board_commands(sub: argparse._SubParsersAction) -> None:
    for name, help_text in (
        ("board-extract", "Extract component/pin data from a .kicad_pcb using pcbnew."),
        ("board-list", "List board components using pcbnew."),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("pcb", help="Path to .kicad_pcb")
        p.add_argument("--refs", default="", help="Reference wildcard filter.")
        p.add_argument("--net-filter", default="", help="Net wildcard filter.")
        p.add_argument("--include-power", action="store_true", help="Include power nets.")
        p.add_argument("-f", "--format", choices=("json", "csv", "md", "markdown"), default="json")
        p.add_argument("-o", "--output", help="Output path. Defaults to stdout.")
        p.set_defaults(func=cmd_board_list if name == "board-list" else cmd_board_extract)


def merge_config(args: argparse.Namespace) -> argparse.Namespace:
    config_path = getattr(args, "config", None)
    if not config_path:
        return args
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise CliError(f"Cannot read config file: {exc}", EXIT_USAGE) from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid JSON config: {exc}", EXIT_USAGE) from exc
    command_config = {}
    if isinstance(data, dict):
        command_config.update(data.get("defaults", {}))
        command_config.update(data.get(getattr(args, "command", ""), {}))
    for key, value in command_config.items():
        if hasattr(args, key) and getattr(args, key) in (None, "", [], False):
            setattr(args, key, value)
    return args


def cmd_inspect(args: argparse.Namespace) -> int:
    parser = load_parser(args)
    rows = {
        "inputs": sorted(expand_inputs(args.inputs)),
        "component_count": len(parser.components),
        "net_count": len(parser.net_to_pins),
        "components": sorted(parser.components.values(), key=lambda row: SchematicGraphParser.natural_sort_key(row.get("reference", ""))),
        "sheets": parser.sheet_summary(),
        "interfaces": normalize_interfaces(parser.group_interfaces()),
    }
    if getattr(args, "include_pins", False):
        rows["pins"] = all_pin_rows(parser)
    return write_rows(rows, args.format, args.output, title="KiWay Inspect")


def cmd_extract(args: argparse.Namespace) -> int:
    parser = load_parser(args)
    doc = DocGenerator()
    if args.kind == "connectors":
        rows: Any = doc.connector_rows_from_parser(parser)
    elif args.kind == "testpoints":
        from .core.test_point_extractor import TestPointExtractor

        rows = TestPointExtractor(parser).as_rows()
    elif args.kind == "tm-tc":
        rows = doc.make_tm_tc_rows(parser, consolidate=args.consolidate)
    elif args.kind == "interfaces":
        rows = normalize_interfaces(parser.group_interfaces())
    else:
        rows = all_pin_rows(parser, include_power=args.include_power)
    return write_rows(rows, args.format, args.output, title=f"KiWay {args.kind} Extract")


def cmd_dependencies(args: argparse.Namespace) -> int:
    from .dependency_manager import health_report, install_dependencies, recommended_missing

    install_result = None
    if args.install:
        keys = recommended_missing(include_optional=args.all)
        if keys:
            install_result = install_dependencies(
                keys,
                use_user_site=not args.no_user,
                dry_run=args.dry_run,
            )
        else:
            install_result = {
                "command": [],
                "returncode": 0,
                "stdout": "All selected dependencies are already installed.",
                "stderr": "",
                "dry_run": bool(args.dry_run),
            }
    report = health_report()
    if install_result is not None:
        report["install"] = install_result
    write_rows(report, "json", args.output, title="KiWay Dependencies")
    if install_result and install_result["returncode"]:
        return EXIT_RUNTIME
    return EXIT_OK


def cmd_crosslink(args: argparse.Namespace) -> int:
    documents = load_import_documents(args.documents, args.project)
    rules = load_rules(args.rules, args.rules_file)
    linker = CrossProjectLinker(documents)
    links = linker.link(
        rules,
        exact_match=not args.no_exact,
        normalized_match=not args.no_normalized,
        include_power=args.include_power,
        max_links=args.max_links,
    )
    if args.format == "svg":
        return write_text(linker.harness_svg(links), args.output)
    return write_rows(links, args.format, args.output, title="KiWay Cross-Project Pin Tracker")


def cmd_validate(args: argparse.Namespace) -> int:
    parser = load_parser(args)
    issues: List[Dict[str, Any]] = []
    for ref, meta in parser.components.items():
        if not parser.get_component_pin_nets(ref):
            issues.append(issue("warning", "component-without-pins", f"{ref} has no connected pins", ref=ref))
        if not meta.get("sheet_path"):
            issues.append(issue("info", "missing-sheet-path", f"{ref} has no native sheet path", ref=ref))
    doc = DocGenerator()
    for row in doc.make_tm_tc_rows(parser, consolidate=True):
        if args.require_tm_consumer and row.get("Type") in {"TM", "TA", "TD"} and not row.get("Destination Board"):
            issues.append(issue("error", "tm-without-consumer", f"{row.get('Net Name')} has no destination board", net=row.get("Net Name")))
        if args.require_tc_origin and row.get("Type") in {"TC", "CA", "CD"} and not row.get("Source Board"):
            issues.append(issue("error", "tc-without-origin", f"{row.get('Net Name')} has no source board", net=row.get("Net Name")))
    if args.imports:
        cross_args = argparse.Namespace(
            documents=args.imports,
            project=[],
            rules="",
            rules_file=None,
            no_exact=False,
            no_normalized=False,
            include_power=False,
            max_links=50000,
        )
        documents = load_import_documents(cross_args.documents, cross_args.project)
        links = CrossProjectLinker(documents).link()
        if not links:
            issues.append(issue("warning", "no-cross-project-links", "No imported project endpoints linked"))
    result = {"status": "fail" if any(i["severity"] == "error" for i in issues) else "pass", "issue_count": len(issues), "issues": issues}
    write_rows(result, args.format, args.output, title="KiWay Validation")
    return EXIT_VALIDATION if result["status"] == "fail" else EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    parser = load_parser(args)
    doc = DocGenerator(args.title)
    cross_links: List[Dict[str, str]] = []
    if args.imports:
        cross_links = CrossProjectLinker(load_import_documents(args.imports, [])).link(load_rules(args.rules, None))
    markdown = doc.build_markdown(
        tm_tc_rows=doc.make_tm_tc_rows(parser, consolidate=True),
        test_point_rows=__import__("extract_pins_plugin.core.test_point_extractor", fromlist=["TestPointExtractor"]).TestPointExtractor(parser).as_rows(),
        interface_maps=parser.group_interfaces(),
        connector_rows=doc.connector_rows_from_parser(parser),
        peripheral_rows=doc.peripheral_rows_from_parser(parser),
        cross_link_rows=cross_links,
    )
    if args.format == "html":
        html_path = args.output or "kiway_report.html"
        doc.export_html(markdown, html_path)
        return EXIT_OK
    if args.format == "csv":
        return write_rows(doc.make_tm_tc_rows(parser), "csv", args.output, title=args.title)
    if args.format == "json":
        return write_rows({"markdown": markdown, "cross_links": cross_links}, "json", args.output, title=args.title)
    if args.format == "svg":
        svg = SVGDiagramGenerator().generate_interface_block_diagram(parser.group_interfaces(), title=args.title)
        return write_text(svg, args.output)
    return write_text(markdown, args.output)


def cmd_benchmark(args: argparse.Namespace) -> int:
    start = time.perf_counter()
    docs = synthetic_documents(args.boards, args.nets)
    build_ms = (time.perf_counter() - start) * 1000
    link_start = time.perf_counter()
    links = CrossProjectLinker(docs).link(exact_match=True, normalized_match=False, include_power=False, max_links=max(args.nets * args.boards, 50000))
    link_ms = (time.perf_counter() - link_start) * 1000
    total_ms = (time.perf_counter() - start) * 1000
    result = {
        "boards": args.boards,
        "nets": args.nets,
        "links": len(links),
        "build_ms": round(build_ms, 3),
        "link_ms": round(link_ms, 3),
        "total_ms": round(total_ms, 3),
        "threshold_ms": args.threshold_ms,
        "status": "pass" if total_ms <= args.threshold_ms else "warn",
    }
    write_rows(result, args.format, args.output, title="KiWay Benchmark")
    return EXIT_OK


def cmd_test(args: argparse.Namespace) -> int:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"] + list(args.pytest_args)
    return subprocess.call(command)


def cmd_board_extract(args: argparse.Namespace) -> int:
    from .core.board_extract import extract_board_pin_rows

    board = load_board(args.pcb)
    rows = extract_board_pin_rows(board, reference_filter=args.refs, net_filter=args.net_filter, include_power=args.include_power)
    return write_rows(rows, args.format, args.output, title="KiWay Board Extract")


def cmd_board_list(args: argparse.Namespace) -> int:
    board = load_board(args.pcb)
    rows = []
    for fp in board.GetFootprints():
        rows.append({"Reference": fp.GetReference(), "Value": fp.GetValue(), "Footprint": str(fp.GetFPID()), "Layer": fp.GetLayerName()})
    return write_rows(sorted(rows, key=lambda r: SchematicGraphParser.natural_sort_key(r["Reference"])), args.format, args.output, title="KiWay Board Components")


def load_parser(args: argparse.Namespace) -> SchematicGraphParser:
    inputs = expand_inputs(args.inputs)
    if not inputs:
        raise CliError("No XML/.net inputs found", EXIT_USAGE)
    parser = SchematicGraphParser(
        schematic_paths=inputs,
        board_sequence=split_csv(getattr(args, "board_sequence", "")),
        sheet_definitions=parse_sheet_aliases(getattr(args, "sheet_alias", [])),
    )
    parser.build()
    return parser


def expand_inputs(inputs: Sequence[str]) -> List[str]:
    paths: List[str] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            paths.extend(str(p) for p in sorted(path.rglob("*")) if p.suffix.lower() in {".xml", ".net"})
        elif path.is_file():
            paths.append(str(path))
    return sorted(dict.fromkeys(paths))


def parse_sheet_aliases(values: Sequence[str]) -> List[Dict[str, str]]:
    rules = []
    for value in values or []:
        parts = [p.strip() for p in str(value).split(":", 2)]
        if len(parts) != 3:
            raise CliError("--sheet-alias must be Name:path_glob:ref_glob", EXIT_USAGE)
        rules.append({"name": parts[0], "path_pattern": parts[1], "reference_pattern": parts[2]})
    return rules


def all_pin_rows(parser: SchematicGraphParser, include_power: bool = True) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ref, meta in sorted(parser.components.items(), key=lambda item: parser.natural_sort_key(item[0])):
        sheet = parser.get_component_sheet(ref)
        for pin in parser.get_component_pin_nets(ref):
            net_name = pin["net"]
            if not include_power and CrossProjectLinker._is_power_endpoint(  # type: ignore[attr-defined]
                PinDocumentImporter().endpoints_from_rows([{"Reference": ref, "Pin": pin["pin"], "Net Name": net_name}], "local", "local")[0]
            ):
                continue
            parsed = parser.parse_interface_label(net_name)
            rows.append(
                {
                    "Reference": ref,
                    "Value": meta.get("value", ""),
                    "Kind": meta.get("kind", ""),
                    "Sheet": sheet["name"],
                    "Sheet Path": sheet["path"],
                    "Pin": pin["pin"],
                    "Pin Function": parser.pin_functions.get((ref, pin["pin"]), ""),
                    "Net Name": net_name,
                    "Source Board": parsed.source_board,
                    "Destination Board": parsed.destination_board,
                    "Interface": parsed.interface,
                    "Signal": parsed.signal,
                    "TM/TC Type": parsed.tm_tc_type,
                }
            )
    return rows


def normalize_interfaces(interfaces: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for name, data in sorted(interfaces.items()):
        rows.append(
            {
                "Interface": name,
                "Source Board": data.get("source_board", ""),
                "Destination Board": data.get("destination_board", ""),
                "Net Count": len(data.get("nets", [])),
                "Nets": ", ".join(data.get("nets", [])),
                "TM/TC Types": ", ".join(data.get("tm_tc_types", [])),
                "Diff Pairs": json.dumps(data.get("diff_pairs", []), sort_keys=True),
            }
        )
    return rows


def load_import_documents(paths: Sequence[str], projects: Sequence[str]) -> List[Any]:
    importer = PinDocumentImporter()
    documents = []
    for index, path in enumerate(paths):
        project = projects[index] if index < len(projects) else Path(path).stem
        documents.append(importer.load(path, project))
    return documents


def load_rules(inline: str = "", path: Optional[str] = None) -> List[Any]:
    text = inline or ""
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            text = text + "\n" + handle.read()
    return parse_link_rules(text) if text.strip() else []


def synthetic_documents(boards: int, nets: int) -> List[Any]:
    importer = PinDocumentImporter()
    docs = []
    for board_index in range(boards):
        rows = [
            {"Reference": f"J{net_index + 1}", "Pin": str(net_index + 1), "Net Name": f"SIG_{net_index:05d}"}
            for net_index in range(nets)
            if board_index in (net_index % boards, (net_index + 1) % boards)
        ]
        project = f"BOARD{board_index + 1}"
        docs.append(importer.endpoints_from_rows(rows, project, f"{project}.csv"))
        docs[-1] = __import__("extract_pins_plugin.core.cross_linker", fromlist=["ImportedPinDocument"]).ImportedPinDocument(project, f"{project}.csv", docs[-1])
    return docs


def write_rows(data: Any, fmt: str, output: Optional[str], title: str = "KiWay") -> int:
    fmt = "md" if fmt == "markdown" else fmt
    if fmt == "json":
        return write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", output)
    if isinstance(data, dict):
        rows = data.get("issues") if "issues" in data else [data]
    else:
        rows = list(data)
    if fmt == "csv":
        return write_text(to_csv(rows), output)
    if fmt == "html":
        markdown = to_markdown(rows, title)
        path = output or "kiway_report.html"
        DocGenerator(title).export_html(markdown, path)
        return EXIT_OK
    if fmt == "svg":
        return write_text(SVGDiagramGenerator().generate_interface_block_diagram({row.get("Interface", "Rows"): {"nets": split_csv(row.get("Nets", ""))} for row in rows}, title), output)
    return write_text(to_markdown(rows, title), output)


def write_text(text: str, output: Optional[str]) -> int:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def to_csv(rows: Sequence[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    headers = ordered_headers(rows)
    from io import StringIO

    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})
    return buf.getvalue()


def to_markdown(rows: Sequence[Dict[str, Any]], title: str) -> str:
    lines = [f"# {title}", ""]
    if not rows:
        return "\n".join(lines + ["No entries found.", ""])
    headers = ordered_headers(rows)
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")).replace("|", "\\|").replace("\n", " ") for h in headers) + " |")
    return "\n".join(lines) + "\n"


def ordered_headers(rows: Sequence[Dict[str, Any]]) -> List[str]:
    headers: List[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    return headers


def load_board(pcb_path: str) -> Any:
    try:
        import pcbnew
    except ImportError as exc:
        raise CliError("pcbnew is not available. Run board commands from KiCad Python or use XML/netlist commands.", EXIT_USAGE) from exc
    if not os.path.exists(pcb_path):
        raise CliError(f"PCB file not found: {pcb_path}", EXIT_USAGE)
    return pcbnew.LoadBoard(pcb_path)


def split_csv(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def issue(severity: str, code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **extra}


def emit_diagnostic(level: str, message: str, args: argparse.Namespace, data: Optional[Dict[str, Any]] = None) -> None:
    if getattr(args, "quiet", False) and level != "error":
        return
    if getattr(args, "diagnostics", "text") == "json":
        print(json.dumps({"level": level, "message": message, "data": data or {}}, sort_keys=True), file=sys.stderr)
    else:
        print(f"kiway: {level}: {message}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
