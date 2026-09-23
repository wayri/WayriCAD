#!/usr/bin/env python3
"""KiCad IPC action and standalone entrypoint. Python 3.10+; optional official IPC client for live linking."""
from pathlib import Path
import argparse
import sys
import os
import json
import webbrowser


def pick():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
        path=filedialog.askopenfilename(title='Open KiCad project — WayriCAD BOM Studio',filetypes=[('KiCad project or root schematic','*.kicad_pro *.kicad_sch'),('All files','*.*')])
        root.destroy()
        if path:print(path)
    except Exception as exc:
        print(str(exc),file=sys.stderr);return 1
    return 0


def main():
    parser=argparse.ArgumentParser(description='WayriCAD BOM Studio: offline BOM and native-variant workbench')
    parser.add_argument('project',nargs='?',help='Root .kicad_sch or .kicad_pro path')
    parser.add_argument('--demo',action='store_true',help='Open a temporary working copy of the sample project')
    parser.add_argument('--analytics-demo',action='store_true',help='Open a temporary synthetic cost/mass/power sample with mapped settings')
    parser.add_argument('--engineering-demo',action='store_true',help='Open a temporary fictional catalog/variant/qualification sample')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--ui',choices=['desktop','browser','none'],help='Default: embedded desktop; browser must be explicitly requested.')
    parser.add_argument('--port',type=int,default=0,help='Loopback TCP port; 0 chooses a free port')
    parser.add_argument('--no-auto-link',action='store_true',help='Open manually instead of discovering the saved PCB project from KiCad launch context')
    parser.add_argument('--session-file',help=argparse.SUPPRESS)
    parser.add_argument('--pick',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    # wx.App parses process arguments again on Windows.  Project paths and our
    # --ui/--port switches are already consumed here; leaving them in argv can
    # produce KiCad's spurious "Unknown option" dialog before the window opens.
    sys.argv[:]=sys.argv[:1]
    if args.pick:return pick()
    # Detached callers need a diagnostic if imports or project loading stall.
    if args.session_file:
        import faulthandler
        faulthandler.dump_traceback_later(12)
    if sys.version_info<(3,10):raise SystemExit('Python 3.10 or later is required.')
    from bomstudio.server import Application,Server
    from bomstudio.desktop import ui_mode, run, DesktopUnavailable, notify_failure
    mode=ui_mode(args.no_browser,args.ui)
    server=None
    def ready(actual_mode):
        if args.session_file:
            with open(args.session_file,'x',encoding='utf-8') as f:
                json.dump({'pid':os.getpid(),'url':server.url,'ui_mode':actual_mode},f)
            faulthandler.cancel_dump_traceback_later()
    try:
        from bomstudio.startup import load_with_progress
        app=load_with_progress(
            lambda: Application(args.project,args.demo,auto_link=not args.no_auto_link,
                                analytics_demo=args.analytics_demo,engineering_demo=args.engineering_demo),
            enabled=mode=='desktop')
        app.ui_mode=mode;server=Server(app,args.port)
        if mode=='desktop':
            run(server,on_ready=ready)
        else:
            ready(mode)
            print('WayriCAD BOM Studio — private local session:\n'+server.url,flush=True)
            if mode=='browser':webbrowser.open(server.url,new=2)
            try:server.serve_forever(poll_interval=.2)
            finally:server.server_close()
    except KeyboardInterrupt:pass
    except DesktopUnavailable as exc:
        notify_failure(str(exc));return 6
    except Exception as exc:
        notify_failure('WayriCAD BOM Studio could not start: '+str(exc));return 1
    finally:
        if server:server.server_close()
    return 0

if __name__=='__main__':raise SystemExit(main())
