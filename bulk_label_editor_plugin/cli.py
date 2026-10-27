"""Read saved PCB nets or preview data-only rename rules; never modify designs."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(value == "--request" or value.startswith("--request=") for value in arguments):
        # Preserve existing data-only automation clients and their output format.
        from wayricad_runtime.control_cli import main as control
        return control(["bulk-label-editor", *arguments])
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    nets = subs.add_parser("nets", help="List saved-board net names, pad/track/via/zone counts and terminals.")
    nets.add_argument("board", type=Path)
    nets.add_argument("--search", default="", help="Substring, * and ? wildcards, or ~fuzzy search.")
    nets.add_argument("--output", type=Path, help="Write a NEW .json report; existing files are preserved.")
    preview = subs.add_parser("preview", help="Preview wildcard/regex replacements of supplied strings.")
    preview.add_argument("values", nargs="+")
    preview.add_argument("--find", required=True)
    preview.add_argument("--replace", required=True)
    preview.add_argument("--regex", action="store_true")
    preview.add_argument("--case-sensitive", action="store_true")
    args = parser.parse_args(arguments)
    try:
        if args.command == "nets":
            if not args.board.is_file() or args.board.suffix.lower() != ".kicad_pcb":
                raise ValueError("Choose an existing .kicad_pcb file.")
            if args.output and (args.output.suffix.lower() != ".json" or args.output.exists()):
                raise ValueError("Choose a separate NEW .json report.")
            before = hashlib.sha256(args.board.read_bytes()).hexdigest()
            try:
                import pcbnew
            except ImportError as exc:
                raise RuntimeError("Saved-board net inventory needs KiCad's Python with pcbnew; --help and data-only preview do not.") from exc
            from .inventory import collect_nets
            from wayricad_runtime.net_filter import SearchIndex
            board = pcbnew.LoadBoard(str(args.board.resolve()))
            if board is None:
                raise ValueError("KiCad could not load this PCB.")
            rows = collect_nets(board)
            selected = SearchIndex([row.name for row in rows]).match(args.search)
            if hashlib.sha256(args.board.read_bytes()).hexdigest() != before:
                raise ValueError("The saved PCB changed while reading; rerun the inventory.")
            result = dict(schema="wayricad.labels/nets-v1", source_sha256=before,
                          total_nets=len(rows), shown_nets=len(selected),
                          nets=[asdict(rows[index]) for index in selected], read_only=True)
        else:
            from .rules import compile_rule
            rule = compile_rule(args.find, args.replace, regex=args.regex, case_sensitive=args.case_sensitive)
            result = {"changes": [{"current": value, "new": rule(value)}
                                  for value in args.values if rule(value) != value], "read_only": True}
        rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if getattr(args, "output", None):
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        print(rendered, end="")
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
