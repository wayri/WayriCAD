"""Discover a compatible local interpreter without importing its binary modules."""
import os
from pathlib import Path
import subprocess
import sys


def child_environment():
    from wayricad_runtime.runtime_setup import child_environment as environment
    env = environment()
    env['WAYRICAD_COPPER_NO_REGISTER'] = '1'
    return env


def find_native_python():
    from wayricad_runtime.runtime_setup import ensure_runtime
    return ensure_runtime()


def launch(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        python = find_native_python()
        process = subprocess.run([str(python), '-I', str(Path(__file__).with_name('native_app.py')), *arguments],
                                 env=child_environment(),
                                 capture_output=bool(arguments), text=True, encoding='utf-8', errors='replace',
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if arguments:
            if process.stdout:
                print(process.stdout, end='')
            if process.stderr:
                print(process.stderr, end='', file=sys.stderr)
        return process.returncode
    except Exception as exc:
        if arguments:
            print(str(exc), file=sys.stderr)
        else:
            from wayricad_runtime.bootstrap import failure
            return failure(exc, 'WayriCAD Copper Balancer')
        return 1
