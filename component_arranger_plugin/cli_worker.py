"""Run saved-board CLI operations with owned KiCad native process lifetime."""
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    destination=Path(sys.argv[2])
    try:
        root=Path(__file__).resolve().parent
        spec=importlib.util.spec_from_file_location('arranger_cli',root/'__init__.py',submodule_search_locations=[str(root)])
        package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
        from arranger_cli.cli import run_native
        result=run_native(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
        destination.write_text(json.dumps(result),encoding='utf-8');return 0
    except Exception as error:
        destination.write_text(json.dumps(dict(status='ERROR',error=str(error))),encoding='utf-8');return 1


if __name__=='__main__': os._exit(main())
