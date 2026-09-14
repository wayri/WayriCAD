"""Standalone command wrapper; native GUI uses KiCad's configured interpreter."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / 'src'))
    if any(flag in arguments for flag in ('--gui', '--review')) and importlib.util.find_spec('pcbnew') is None:
        from wayricad_mechanical.runtime import discover
        native = discover()['kicad_python']
        if not native or Path(native).resolve() == Path(sys.executable).resolve():
            print('The native viewer requires KiCad 10 Python with pcbnew, wxPython and PyOpenGL. Set WAYRICAD_MECHANICAL_KICAD_PYTHON to that executable.', file=sys.stderr)
            return 1
        environment = os.environ.copy()
        for name in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'):
            environment.pop(name, None)
        return subprocess.run([native, str(root / 'launch.py'), *arguments], env=environment,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).returncode
    from wayricad_mechanical.cli import main as run
    return run(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
