"""Owned CLI native process, isolated from unsafe SWIG project finalization."""
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    result = Path(sys.argv[2])
    try:
        root = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location('trace_refiner_cli', root / '__init__.py',
                                                     submodule_search_locations=[str(root)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = package
        spec.loader.exec_module(package)
        from trace_refiner_cli.cli import run_native
        payload = run_native(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
        result.write_text(json.dumps(payload), encoding='utf-8')
        return 0
    except ImportError as exc:
        message = 'Use KiCad 10 native Python with pcbnew installed: ' + str(exc)
    except Exception as exc:
        message = str(exc)
    result.write_text(json.dumps(dict(status='ERROR', error=message)), encoding='utf-8')
    return 1


if __name__ == '__main__':
    # The owned child's files are closed before bypassing SWIG shutdown order.
    os._exit(main())
