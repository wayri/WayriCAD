"""Check that installed BOM Studio loads its embedded desktop on Marble."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-entrypoint", action="store_true",
                        help="Exercise source entrypoint without the separately provisioned runtime")
    parser.add_argument("--python", type=Path, default=Path(sys.executable),
                        help="Python executable containing KiCad's wx bindings")
    args = parser.parse_args()
    root, project, output = args.root.resolve(), args.project.resolve(), args.output.resolve()
    executable = "entrypoint.py" if args.source_entrypoint else "desktop_entrypoint.py"
    if not (root / executable).is_file() or not project.is_file():
        parser.error("Installed BOM Studio and saved Marble project must exist")
    session = output.with_name("bom-session.json")
    log = output.with_name("bom-window.log")
    session.unlink(missing_ok=True)
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "KICAD_API_SOCKET", "KICAD_API_TOKEN"):
        env.pop(name, None)
    command = [str(args.python), *([] if args.source_entrypoint else ["-I"]), str(root / executable),
               str(project), "--no-auto-link", "--session-file", str(session)]
    if args.source_entrypoint:
        command.extend(["--ui", "desktop"])
    result = {"status": "starting", "project": project.name, "desktop_ready": False}
    with log.open("w", encoding="utf-8") as stream:
        child = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if session.is_file():
                    try:
                        ready = json.loads(session.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        # The producer may still be writing the readiness file.
                        time.sleep(.2)
                        continue
                    result.update(status="passed" if ready.get("ui_mode") == "desktop" else "failed",
                                  desktop_ready=ready.get("ui_mode") == "desktop",
                                  session_pid=ready.get("pid"))
                    # The ready signal comes only after the embedded window loads.
                    try:
                        with urlopen(ready["url"], timeout=4) as response:
                            result["http_status"] = response.status
                    except Exception as exc:
                        result.update(status="failed", http_error=f"{type(exc).__name__}: {exc}")
                    break
                if child.poll() is not None:
                    result.update(status="failed", error="Desktop process exited before readiness",
                                  exit_code=child.returncode)
                    break
                time.sleep(.2)
            else:
                result.update(status="failed", error="Desktop did not load within 35 seconds")
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            result["log_tail"] = log.read_text(encoding="utf-8", errors="replace")[-1200:]
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
