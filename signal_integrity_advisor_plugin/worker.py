"""Private saved-board worker entry point; never starts a GUI or edits a PCB."""
import importlib
import json
from pathlib import Path
import sys
import types


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if len(args)!=2:return 2
    request,target=map(Path,args)
    if request.resolve()==target.resolve():return 2
    # wx must never see worker command-line options during dependency imports.
    sys.argv=sys.argv[:1]
    root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root));sys.path.insert(0,str(root.parent))
    package=types.ModuleType('wayricad_si_worker');package.__path__=[str(root)];package.__package__=package.__name__;sys.modules[package.__name__]=package
    try:
        payload=json.loads(request.read_text(encoding='utf-8'))
        protected={Path(payload['board_path']).resolve(),*(Path(name).resolve() for name in payload.get('source_fingerprints',{}))}
        if target.resolve() in protected:return 2
        result=importlib.import_module('.service',package.__name__).execute(payload);status=0
    except Exception as error:
        result={'error':str(error),'error_type':type(error).__name__};status=2
    target.write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
    return status


if __name__=='__main__':raise SystemExit(main())
