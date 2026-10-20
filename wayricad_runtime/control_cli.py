"""Headless JSON inputs for the suite's established pure analysis operations."""
import argparse
import json
from pathlib import Path
import sys
from .tool_cli import CONTROL_METHODS


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool',choices=sorted(CONTROL_METHODS))
    parser.add_argument('--request',type=Path,required=True,help='JSON parameters for this tool; no arbitrary RPC method is accepted.')
    parser.add_argument('--output',type=Path,help='NEW JSON result file, never a design or request file.')
    args=parser.parse_args(argv)
    try:
        from .jobs import load_json
        params=load_json(args.request)
        if not isinstance(params,dict):raise ValueError('Parameters must be a JSON object.')
        if args.output and (args.output.resolve()==args.request.resolve() or args.output.suffix.lower()!='.json'):
            raise ValueError('Choose a separate new .json result file.')
        if args.output and args.output.exists():raise ValueError('Output exists; choose a new result file.')
        from extract_pins_plugin.automation import execute
        result=execute({'jsonrpc':'2.0','id':1,'method':CONTROL_METHODS[args.tool],'params':params})
        rendered=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x',encoding='utf-8') as stream:stream.write(rendered)
        print(rendered,end='')
        return 1 if 'error' in result else 0
    except ImportError as exc:
        print(json.dumps({'status':'ERROR','error':'Install the full WayriCAD suite wheel for unified CLI analysis. '+str(exc)}),file=sys.stderr);return 2
    except (OSError,ValueError,RuntimeError,TypeError,KeyError) as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)}),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
