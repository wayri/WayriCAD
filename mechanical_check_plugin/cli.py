"""Standalone command wrapper; native GUI uses KiCad's configured interpreter."""
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / 'src'))
    if any(flag in arguments for flag in ('--gui', '--review')):
        if not (root / 'wayricad_runtime').is_dir():
            sys.path.insert(0, str(root.parent))
        from wayricad_runtime.runtime_setup import ensure_runtime, child_environment, REQUIREMENTS_MECHANICAL
        if os.environ.get('WAYRICAD_MECHANICAL_KICAD_PYTHON'):
            os.environ['WAYRICAD_KICAD_PYTHON'] = os.environ['WAYRICAD_MECHANICAL_KICAD_PYTHON']
        try:
            native = ensure_runtime(REQUIREMENTS_MECHANICAL)
        except Exception as exc:
            print('Could not prepare the native Mechanical Check viewer: ' + str(exc), file=sys.stderr)
            return 1
        # Even a pcbnew-capable interpreter may lack the OpenGL viewer modules.
        # Enter the prepared environment before importing the native UI.
        if not sys.flags.isolated or os.path.normcase(os.path.abspath(native)) != os.path.normcase(os.path.abspath(sys.executable)):
            return subprocess.run([str(native), '-I', str(root / 'launch.py'), *arguments], env=child_environment(),
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).returncode
    from wayricad_mechanical.cli import main as run
    return run(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
