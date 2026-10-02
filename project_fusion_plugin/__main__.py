"""Command-line runner. Native KiCad CLI verification is mandatory on real merges."""
import argparse
import json
import sys
from .engine import analyse, merge
from .model import Options, MergeError

def main(argv=None):
    parser = argparse.ArgumentParser(description='Wayri Project Fusion: combine 1–100 KiCad 10 project or section instances without changing the originals.')
    parser.add_argument('--config', help='JSON options file (save a setup from the GUI)')
    parser.add_argument('--analyse', action='store_true', help='Read-only structural preflight; no KiCad connectivity certification')
    parser.add_argument('--gui', action='store_true', help='Launch the native wxPython dialog; requires wxPython')
    args = parser.parse_args(argv)
    if args.gui:
        try:
            import wx
            from .gui import FusionDialog
        except ImportError as exc:
            parser.error(f'wxPython is unavailable in this Python interpreter: {exc}. Run from KiCad instead.')
        app = wx.App(False)
        dialog = FusionDialog(None)
        dialog.ShowModal()
        dialog.Destroy()
        return 0
    if not args.config:
        parser.error('--config is required unless --gui is used')
    try:
        workspace=json.loads(__import__('pathlib').Path(args.config).read_text(encoding='utf-8-sig')).get('_workspace',{})
        if workspace.get('import_into_existing') or workspace.get('include_layout') is False:
            raise MergeError('This setup uses the universal import/schematic-only workspace. Open it in the GUI for reviewed Create / Apply.')
        opts = Options.from_json(args.config)
        if any(s.selection for s in opts.sources):
            raise MergeError('This setup contains sheet selections. Open it in the GUI to prepare and review the selected hierarchy.')
        log = lambda msg: print(msg, file=sys.stderr, flush=True)
        result = analyse(opts, log)[2] if args.analyse else merge(opts, log)
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (MergeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Fusion stopped: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
