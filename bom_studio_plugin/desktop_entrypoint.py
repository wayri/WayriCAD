#!/usr/bin/env python3
"""PCM toolbar entrypoint: prefer embedded local desktop, with browser fallback."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from entrypoint import main

def desktop_main():
    # Keep project/demo/IPC arguments; the toolbar always chooses the desktop-first local launcher.
    if any(a in ('--ui','--no-browser') or a.startswith('--ui=') for a in sys.argv[1:]):
        raise SystemExit('Toolbar launch selects the local desktop automatically. Use cli.py gui --ui browser for explicit troubleshooting.')
    root = Path(__file__).resolve().parent
    if not (root / 'wayricad_runtime').is_dir():
        sys.path.insert(0, str(root.parent))
    if '--help' not in sys.argv[1:] and '-h' not in sys.argv[1:]:
        from wayricad_runtime.bootstrap import relaunch, failure
        try:
            status = relaunch(root, 'desktop_entrypoint.py', profile='ipc')
            if status is not None: return status
        except Exception as exc:
            return failure(exc, 'WayriCAD BOM Studio')
    sys.argv += ['--ui','desktop']
    return main()

if __name__=='__main__':raise SystemExit(desktop_main())
