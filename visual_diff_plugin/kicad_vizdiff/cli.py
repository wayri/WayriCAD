import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
import tempfile
import webbrowser

from .git import VizError, root, safe_path, snapshot, run
from .render import DEFAULT_LAYERS, find_kicad, pair_pages, render


def write_report(output, data):
    template = files(__package__).joinpath("viewer.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    output.parent.mkdir(parents=True, exist_ok=True)
    # A failed write must not truncate the previous report.
    fd, temporary = tempfile.mkstemp(prefix=".wayricad-report-", suffix=".html", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(template.replace("__REPORT_DATA__", payload))
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(prog="wayricad-diff", description="View and visually compare KiCad designs using KiCad's native renderer.")
    subs = p.add_subparsers(dest="command", required=True)
    for command in ("view", "diff"):
        sub = subs.add_parser(command)
        sub.add_argument("file", help="Repository-relative root .kicad_sch or .kicad_pcb")
        sub.add_argument("--repo", default=".", help="Git repository directory")
        if command == "diff":
            sub.add_argument("--base", default="HEAD", help="Old revision (default HEAD)")
            sub.add_argument("--head", default="WORKTREE", help="New revision or WORKTREE (default WORKTREE)")
            sub.add_argument("--old-file", help="Old repository-relative path when the design was renamed")
        else:
            sub.add_argument("--ref", default="WORKTREE", help="Revision or WORKTREE")
        sub.add_argument("--output", "-o", default=".wayricad-visual-diff/index.html")
        sub.add_argument("--layers", default=DEFAULT_LAYERS, help="Comma-separated native PCB layer names")
        sub.add_argument("--theme", help="Installed KiCad color theme name")
        sub.add_argument("--kicad-cli", help="Path to KiCad 10+ CLI")
        sub.add_argument("--open", action="store_true", help="Open report in the default browser")
    subs.add_parser("doctor", help="Check Git and KiCad CLI availability").add_argument("--kicad-cli")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        executable = find_kicad(args.kicad_cli)
        version = run([executable, "version"]).decode().strip()
        if int(version.split(".")[0]) < 10:
            raise VizError(f"KiCad 10+ required; found {version}.")
        if args.command == "doctor":
            print(run(["git", "--version"]).decode().strip())
            print(f"KiCad {version}: {executable}")
            return 0
        repo = root(Path(args.repo))
        relative = args.file.replace("\\", "/")
        old_relative = (getattr(args, "old_file", None) or relative).replace("\\", "/")
        safe_path(repo, relative)
        safe_path(repo, old_relative)
        output = Path(args.output).resolve()
        if output.suffix.lower() != ".html":
            raise VizError("Report output must end in .html.")
        if output in (safe_path(repo, relative), safe_path(repo, old_relative)):
            raise VizError("Report must not overwrite a design file.")
        with tempfile.TemporaryDirectory(prefix="wayricad-visual-diff-") as temp:
            temp = Path(temp)
            before, base_id = {}, None
            if args.command == "diff":
                print(f"Rendering {args.base}:{old_relative}", file=sys.stderr)
                base_id = snapshot(repo, args.base, temp / "base")
                before = render(temp / "base", old_relative, temp / "before", executable, args.layers, args.theme)
            head = args.head if args.command == "diff" else args.ref
            print(f"Rendering {head}:{relative}", file=sys.stderr)
            head_id = snapshot(repo, head, temp / "head")
            after = render(temp / "head", relative, temp / "after", executable, args.layers, args.theme)
            if not before and not after:
                raise VizError(f"Design not found in the selected revision(s): {relative}")
            pages = pair_pages(before, after)
            if args.command == "view":
                for page in pages:
                    page["status"] = "view"
            write_report(output, {"file": relative, "oldFile": old_relative, "base": base_id,
                                  "head": head_id, "mode": args.command, "kicad": version,
                                  "pages": pages, "theme": args.theme or "KiCad default"})
        print(output)
        if args.open:
            webbrowser.open(output.as_uri())
        return 0
    except (VizError, OSError, ValueError) as exc:
        print(f"WayriCAD Visual Diff: {exc}", file=sys.stderr)
        return 1
