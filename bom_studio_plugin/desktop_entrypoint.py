#!/usr/bin/env python3
"""PCM toolbar entrypoint: prefer embedded local desktop, with browser fallback."""
import sys
from entrypoint import main

def desktop_main():
    # Keep project/demo/IPC arguments; the toolbar always chooses the desktop-first local launcher.
    if any(a in ('--ui','--no-browser') or a.startswith('--ui=') for a in sys.argv[1:]):
        raise SystemExit('Toolbar launch selects the local desktop automatically. Use cli.py gui --ui browser for explicit troubleshooting.')
    sys.argv += ['--ui','desktop']
    return main()

if __name__=='__main__':raise SystemExit(desktop_main())
