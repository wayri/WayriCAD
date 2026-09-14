"""Saved-board UI and CLI. Applying always writes a new file, never the source."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

os.environ['WAYRICAD_COPPER_NO_REGISTER'] = '1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_output(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or destination.exists():
        raise ValueError('Choose a new output filename. Existing files are never overwritten.')
    if destination.suffix.lower() != '.kicad_pcb':
        raise ValueError('Output must have the .kicad_pcb extension.')
    if not destination.parent.is_dir():
        raise ValueError('The output directory does not exist.')
    return destination


def write_copy(board, source, destination, expected_hash):
    import pcbnew
    destination = validate_output(source, destination)
    if digest(source) != expected_hash:
        raise ValueError('The source board changed. Reopen it and build a fresh preview.')
    with tempfile.TemporaryDirectory(prefix='.wayricad-copper-', dir=destination.parent) as td:
        scratch = Path(td) / destination.name
        pcbnew.SaveBoard(str(scratch), board)
        if not scratch.is_file() or scratch.stat().st_size == 0:
            raise RuntimeError('KiCad did not write the output board.')
        if digest(source) != expected_hash:
            raise ValueError('The source board changed while saving. Reopen it and review again.')
        # Exclusive creation avoids replacing a file created after the picker closed.
        try:
            with destination.open('xb') as out, scratch.open('rb') as src:
                shutil.copyfileobj(src, out)
        except FileExistsError:
            raise ValueError('The output now exists. Choose another filename.') from None
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return destination


def load_native(source):
    import pcbnew
    if not str(pcbnew.Version()).startswith('10.'):
        raise RuntimeError('This geometry adapter requires KiCad 10.x.')
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != '.kicad_pcb':
        raise ValueError('Choose a saved .kicad_pcb board.')
    stamp = digest(source)
    board = pcbnew.LoadBoard(str(source))
    if digest(source) != stamp:
        raise ValueError('The board changed while opening it. Retry with the saved board.')
    return source, stamp, board


def cli(args):
    from copper_balancer.engine import Settings
    from copper_balancer import kicad_backend as backend
    source, stamp, board = load_native(args.board)
    values = json.loads(Path(args.settings).read_text(encoding='utf-8')) if args.settings else {}
    settings = Settings(**values)
    settings.validate()
    names = dict((name, layer) for layer, name in backend.copper_layers(board))
    requested = args.layer or ['F.Cu']
    if any(name not in names for name in requested):
        raise ValueError('Choose enabled copper layers: ' + ', '.join(names))
    previews, warnings = backend.build_preview(board, [names[name] for name in requested], settings)
    report = {'tool': 'WayriCAD Copper Balancer', 'source_sha256': stamp, 'settings': asdict(settings),
              'warnings': warnings, 'layers': [dict(name=p.name, shapes=len(p.plan.shapes),
              added_area_mm2=p.plan.added_area, coverage_percent=p.plan.density) for p in previews]}
    if args.output:
        validate_output(source, args.output)
        backend.apply_preview(board, previews, settings)
        report['output'] = str(write_copy(board, source, args.output, stamp))
    print(json.dumps(report, indent=2))
    return 0


def gui():
    import wx
    from copper_balancer.dialog import CopperBalancerDialog
    app = wx.App.Get() or wx.App(False)
    with wx.FileDialog(None, 'Open saved PCB — edits will be saved as a new copy',
                       wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb',
                       style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as picker:
        if picker.ShowModal() != wx.ID_OK:
            return 0
        source, stamp, board = load_native(picker.GetPath())

    def save_result(operation):
        with wx.FileDialog(None, 'Save balanced PCB as a new copy', defaultDir=str(source.parent),
                           defaultFile=source.stem + '-balanced.kicad_pcb',
                           wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb', style=wx.FD_SAVE) as picker:
            if picker.ShowModal() != wx.ID_OK:
                return False
            validate_output(source, picker.GetPath())
            if digest(source) != stamp:
                raise ValueError('The saved board changed. Reopen it and review again.')
            operation()
            output = write_copy(board, source, picker.GetPath(), stamp)
        wx.MessageBox('Saved ' + str(output) + '\nOpen the copy in KiCad, refill zones and run DRC.',
                      'WayriCAD Copper Balancer', wx.OK | wx.ICON_INFORMATION)
        return True

    dialog = CopperBalancerDialog(None, board)
    dialog.save_result = save_result
    dialog.apply_button.SetLabel('Save balanced copy…')
    dialog.status.SetValue('Saved board: ' + source.name + '. Unsaved editor changes are not included.')
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()
    return 0


def main():
    parser = argparse.ArgumentParser(description='WayriCAD Copper Balancer: plan by default; --output writes a new board copy.')
    parser.add_argument('board', nargs='?')
    parser.add_argument('--settings', help='JSON fields from engine.Settings')
    parser.add_argument('--layer', action='append', help='Enabled copper layer name; repeat for multiple layers')
    parser.add_argument('--output', help='New .kicad_pcb destination; never overwrites')
    args = parser.parse_args()
    if not args.board and (args.settings or args.layer or args.output):
        parser.error('Supply a saved board when using CLI options.')
    try:
        return cli(args) if args.board else gui()
    except Exception as exc:
        if args.board:
            parser.exit(1, str(exc) + '\n')
        import wx
        app = wx.App.Get() or wx.App(False)
        wx.MessageBox(str(exc), 'WayriCAD Copper Balancer', wx.OK | wx.ICON_ERROR)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
