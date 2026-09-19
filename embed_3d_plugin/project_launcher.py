"""Independent project-library window; closing PCB Editor does not close it."""
from __future__ import annotations
import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def launch(source='',advanced=False,library=False):
    from wayricad_runtime.native_analysis import native_python,child_environment
    command=[str(native_python()),'-I',str(Path(__file__).resolve())]
    if source:command.extend(['--source',str(source)])
    if advanced:command.append('--advanced')
    if library:command.append('--library')
    env=child_environment();env['WAYRICAD_EMBED3D_NO_REGISTER']='1'
    return subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def saved_bridge(source):
    import pcbnew
    from .native import NativeBridge
    class SavedFileBridge(NativeBridge):
        supports_live_tools=False
        supports_file_tools=True
        capability_note='Saved-file tools. This window does not own an active PCB Editor board.'
        def footprints(self,selected=False):return []
        def prepare_live(self,*args,**kwargs):raise RuntimeError('Live model editing requires an active PCB Editor action.')
        def apply_live(self,*args,**kwargs):raise RuntimeError('This saved-file window cannot mutate an active PCB Editor board.')
        def sources(self,*args,**kwargs):raise RuntimeError('Choose footprint files or a library in this saved-file window.')
    bridge=SavedFileBridge(pcbnew)
    # The board object provides project context only. Every live operation above
    # is disabled, even when a saved board can be loaded for read-only context.
    source=Path(source).resolve() if source else None
    pcb=source.with_suffix('.kicad_pcb') if source else None
    bridge.board=pcbnew.LoadBoard(str(pcb)) if pcb and pcb.is_file() else pcbnew.BOARD()
    if source and not pcb.is_file():bridge.board.SetFileName(str(source.with_suffix('.kicad_pcb')))
    return bridge


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',default='');parser.add_argument('--advanced',action='store_true');parser.add_argument('--library',action='store_true')
    args=parser.parse_args(argv)
    os.environ['WAYRICAD_EMBED3D_NO_REGISTER']='1'
    root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root))
    name='wayricad_project_library_window'
    if (root.parent/'wayricad_runtime').is_dir():sys.path.insert(0,str(root.parent))
    spec=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)])
    package=importlib.util.module_from_spec(spec);sys.modules[name]=package;spec.loader.exec_module(package)
    import wx
    app=wx.App(False)
    try:
        launcher=importlib.import_module('.project_launcher',name)
        bridge=launcher.saved_bridge(args.source)
        if args.library:dialog=importlib.import_module('.ui',name).EmbedDialog(None,bridge)
        elif args.advanced:dialog=importlib.import_module('.workspace_ui',name).WorkspaceDialog(None,bridge)
        else:dialog=importlib.import_module('.project_ui',name).ProjectLibraryDialog(None,bridge,args.source)
        dialog.ShowModal();dialog.Destroy()
    except Exception as exc:
        wx.MessageBox(str(exc),'WayriCAD Embed3D',wx.OK|wx.ICON_ERROR)
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
