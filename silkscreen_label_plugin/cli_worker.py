"""Own native planner lifetime; close JSON output before SWIG finalization."""
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    if len(sys.argv)!=3:
        print('Provide request and NEW result JSON paths.',file=sys.stderr);return 1
    request=Path(sys.argv[1]).resolve();result=Path(sys.argv[2]).resolve()
    root=Path(__file__).resolve().parent
    try:
        data=json.loads(request.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or not isinstance(data.get('board'),str):
            raise ValueError('Request requires a saved board path.')
        board=Path(data['board']).resolve()
        protected={request,board,board.with_suffix('.kicad_pro'),board.with_suffix('.kicad_dru')}
        if result in protected or result.exists():raise ValueError('Result must be a separate NEW JSON file.')
        if result.suffix.lower()!='.json':raise ValueError('Result must end in .json.')
    except Exception as exc:
        print(str(exc),file=sys.stderr);return 1
    def write(payload):
        with result.open('x',encoding='utf-8') as stream:
            json.dump(payload,stream,allow_nan=False)
    try:
        spec=importlib.util.spec_from_file_location('_wayricad_silk_cli',root/'__init__.py',submodule_search_locations=[str(root)])
        package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
        from _wayricad_silk_cli.cli import run_native
        payload=run_native(data)
    except Exception as exc:
        try:write({'status':'ERROR','error':str(exc)})
        except OSError as error:print(str(error),file=sys.stderr)
        return 1
    try:write(payload);return 0
    except OSError as error:print(str(error),file=sys.stderr);return 1

if __name__=='__main__':os._exit(main())
