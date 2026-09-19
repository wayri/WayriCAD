"""Native worker, standalone window and scriptable Quick PI entry point."""
from __future__ import annotations
import argparse
import importlib
import importlib.util
import json
from pathlib import Path
import sys


def package():
    root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root))
    if (root.parent/'wayricad_runtime').is_dir():sys.path.insert(0,str(root.parent))
    name='wayricad_quick_pi_worker'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return name


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',nargs=2,metavar=('REQUEST','RESPONSE'))
    parser.add_argument('--board',type=Path)
    parser.add_argument('--ui',action='store_true')
    args=parser.parse_args(argv);name=package()
    if args.worker:
        request,response=map(Path,args.worker)
        if request.resolve()==response.resolve():
            print(json.dumps({'error':'Worker response must not overwrite the request file.'}));return 2
        try:
            payload=json.loads(request.read_text(encoding='utf-8'))
            if payload.get('board_path') and Path(payload['board_path']).resolve()==response.resolve():
                print(json.dumps({'error':'Worker response must not overwrite the source PCB.'}));return 2
            result=importlib.import_module('.service',name).execute(payload)
            if payload.get('html_output'):
                importlib.import_module('.report',name).write_report(payload['html_output'],result)
            status=0
        except Exception as exc:
            result={'error':str(exc),'error_type':type(exc).__name__};status=2
        def convert(value):
            if hasattr(value,'tolist'):return value.tolist()
            if hasattr(value,'item'):return value.item()
            raise TypeError(type(value).__name__)
        response.write_text(json.dumps(result,default=convert,allow_nan=False),encoding='utf-8')
        return status
    if not args.board:parser.error('--board is required for the native window')
    import wx
    app=wx.App(False)
    try:
        frame=importlib.import_module('.ui',name).QuickPIFrame(None,args.board)
        frame.Show();app.MainLoop();return 0
    except Exception as exc:
        wx.MessageBox(str(exc),'WayriCAD Quick PI',wx.OK|wx.ICON_ERROR);return 2


if __name__=='__main__':raise SystemExit(main())
