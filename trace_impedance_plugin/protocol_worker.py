"""Saved-board protocol scans in a disposable native process, never a wx callback."""
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent if not (ROOT/'wayricad_runtime').is_dir() else ROOT))


def main():
    from wayricad_runtime.analysis_process import contain_converters
    contain_converters()
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0002)
    name='wayricad_rlc_protocol_worker'
    package=types.ModuleType(name);package.__path__=[str(ROOT)];package.__package__=name
    sys.modules[name]=package
    import importlib
    cli=importlib.import_module('.cli',package.__name__)
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    argv=['protocols',request.pop('board')]
    for key,value in request.items():
        if value is not None:argv.extend(['--'+key.replace('_','-'),str(value)])
    args=cli.parser().parse_args(argv)
    result=cli.analyze(args)
    cli.write_report(Path(sys.argv[2]),result,Path(args.board))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(1)
