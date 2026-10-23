"""Isolated native-window entry point for source and independently installed ZIPs."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    if not (root / 'wayricad_runtime').is_dir():
        sys.path.insert(0, str(root.parent))
    name = 'wayricad_assistant_window'
    spec = importlib.util.spec_from_file_location(name, root / '__init__.py',
                                                submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from importlib import import_module
    sys.argv = sys.argv[:1]
    import wx
    app = wx.App(False)
    frame = import_module('.gui', name).AssistantFrame(board=args.board)
    frame.Show()
    ready = os.environ.get('WAYRICAD_SPLASH_READY')
    if ready:
        Path(ready).touch()
    app.MainLoop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
