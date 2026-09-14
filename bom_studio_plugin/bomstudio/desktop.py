"""Native plugin-owned window containing a local webview, not a browser tab.

IPC plugins run out of process. This is a modeless desktop window launched by
KiCad; it is NOT a dockable panel inserted into KiCad's wxWidgets process.
No Python/eval/file bridge is exposed other than explicit, authenticated native
Save/Open-external actions. The existing loopback API retains its auth and CSP.
"""
from __future__ import annotations
import base64
import binascii
import hashlib
import hmac
import importlib
from importlib import metadata
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit
import webbrowser

MAX_DOWNLOAD = 128 * 1024 * 1024

class DesktopUnavailable(RuntimeError):
    pass


def ui_mode(no_browser=False, ui=None):
    if ui not in (None,'desktop','browser','none'):raise ValueError('Unknown UI mode.')
    if no_browser and ui not in (None,'none'):
        raise ValueError('--no-browser means headless --ui none; do not combine it with another UI mode.')
    return 'none' if no_browser else (ui or 'desktop')


def diagnostic():
    try:installed=metadata.version('pywebview')
    except metadata.PackageNotFoundError:installed=None
    try:wx_installed=metadata.version('wxPython')
    except metadata.PackageNotFoundError:wx_installed=None
    return {'schema':'wayricad-desktop-diagnostic-1','python':sys.executable,'platform':sys.platform,
            'pywebview':installed,'wxPython':wx_installed,'preferred_host':'wxPython WebView','default_ui':'desktop','browser_requires_explicit_opt_in':False,'fallback':'local browser when embedded runtime unavailable',
            'renderer':('edgechromium (WebView2)' if sys.platform=='win32' else 'cocoa (WebKit)' if sys.platform=='darwin' else 'WebKitGTK'),
            'package_present':wx_installed is not None or installed is not None,'native_engine_tested':False,
            'window':'Separate modeless IPC plugin window; not a docked KiCad panel.',
            'downloads':'Authenticated native Save dialog, exclusive file creation, maximum 128 MiB per file.'}


def unavailable_message(exc=None):
    detail=('\nDetails: '+str(exc)) if exc else ''
    return ('WayriCAD could not create its embedded desktop window. The local browser fallback will be attempted.\n\n'
            'In KiCad, recreate the WayriCAD plugin Python environment so the updated requirements.txt is installed. '
            'The interpreter is:\n'+sys.executable+'\n\n'
            'Windows: wxPython and Microsoft Edge WebView2 Runtime are required. '
            'Linux: install the declared wxPython dependencies and system WebKitGTK libraries. '
            'macOS: wxPython uses the system WebKit runtime.\n\n'
            'For deliberate browser troubleshooting, run cli.py gui PROJECT --ui browser. '
            'Headless CLI commands do not need a webview.'+detail)


def notify_failure(message):
    print(message,file=sys.stderr,flush=True)
    if sys.platform=='win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'WayriCAD BOM Studio — startup error',0x10)
        except Exception:pass


def _filename(name):
    if not isinstance(name,str) or not name or len(name)>240:
        raise ValueError('Invalid download filename.')
    if name in ('.','..') or any(c in name for c in '/\\\x00\r\n') or any(ord(c)<32 for c in name):
        raise ValueError('Download filename must be a basename, not a path.')
    # Names also need to work on Windows. No device/alternate-stream filenames.
    if any(c in name for c in ':*?"<>|') or name[-1:] in (' ','.'):
        raise ValueError('Download filename is not portable.')
    stem=name.split('.')[0].upper()
    if stem in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('Reserved download filename.')
    return name


def _http_url(value):
    if not isinstance(value,str) or len(value)>8192 or any(ord(c)<32 for c in value):raise ValueError('Invalid external URL.')
    url=urlsplit(value)
    if url.scheme not in ('https','http') or not url.hostname or url.username or url.password:
        raise ValueError('Only explicit HTTP/HTTPS links can be opened externally.')
    return value


class DesktopAPI:
    """Only these public methods are exposed by pywebview to this local page."""
    def __init__(self,server,module):
        self._server=server;self._module=module;self._window=None;self._dialogs=threading.Lock()
    def _trusted(self,token):
        if not isinstance(token,str) or not hmac.compare_digest(token,self._server.app.token):
            raise ValueError('Native operation requires the current session token.')
        if self._window is None:raise ValueError('Native window is not ready.')
        here=urlsplit(self._window.get_current_url() or '')
        origin=urlsplit(self._server.origin)
        if (here.scheme,here.hostname,here.port)!=(origin.scheme,origin.hostname,origin.port) or here.path not in ('','/'):
            raise ValueError('Native operation is restricted to the local WayriCAD page.')
    def save_download(self,name,encoded,token):
        """The caller cannot choose a path. A human chooses it in a native dialog."""
        try:
            self._trusted(token);name=_filename(name)
            if not isinstance(encoded,str) or len(encoded)>((MAX_DOWNLOAD+2)//3)*4:
                raise ValueError('Desktop downloads are limited to 128 MiB. Use a CLI output path for larger files.')
            try:data=base64.b64decode(encoded,validate=True)
            except (ValueError,binascii.Error):raise ValueError('Invalid download encoding.')
            if len(data)>MAX_DOWNLOAD:raise ValueError('Desktop download exceeds 128 MiB.')
            with self._dialogs:
                kind=getattr(getattr(self._module,'FileDialog',None),'SAVE',None)
                if kind is None:kind=self._module.SAVE_DIALOG
                chosen=self._window.create_file_dialog(kind,save_filename=name)
                if not chosen:return {'ok':True,'cancelled':True}
                filename=chosen[0] if isinstance(chosen,(list,tuple)) else chosen
                target=Path(filename)
                # New-file policy matches the CLI. Never overwrite a native
                # project/library by a misleading export filename or a symlink.
                if target.suffix.lower() in ('.kicad_pro','.kicad_sch','.kicad_pcb') or (target.suffix.lower() in ('.kicad_sym','.kicad_mod') and target.suffix.lower()!=Path(name).suffix.lower()):
                    raise ValueError('Choose a report/archive filename, not a native KiCad design file.')
                created=False
                try:
                    with target.open('xb') as out:
                        created=True;out.write(data);out.flush();os.fsync(out.fileno())
                except Exception:
                    if created:
                        try:target.unlink()
                        except OSError:pass
                    raise
            return {'ok':True,'cancelled':False,'name':target.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        except Exception as exc:return {'ok':False,'error':str(exc)}
    def open_external(self,url,token):
        try:
            self._trusted(token);url=_http_url(url)
            parsed=urlsplit(url)
            if parsed.hostname in ('localhost','127.0.0.1','::1'):
                raise ValueError('Local-session URLs are not sent to an external browser.')
            opened=webbrowser.open(url,new=2)
            return {'ok':bool(opened),'error':'' if opened else 'No external browser accepted the link.'}
        except Exception as exc:return {'ok':False,'error':str(exc)}


class DesktopHost:
    def __init__(self,server,module):
        self.server=server;self.module=module;self.api=DesktopAPI(server,module);self.window=None
    def pick_project(self):
        kind=getattr(getattr(self.module,'FileDialog',None),'OPEN',None)
        if kind is None:kind=self.module.OPEN_DIALOG
        with self.api._dialogs:
            files=self.window.create_file_dialog(kind,allow_multiple=False,
                file_types=('KiCad project (*.kicad_pro;*.kicad_sch)','All files (*.*)'))
        if not files:return ''
        return str(files[0] if isinstance(files,(list,tuple)) else files)


def run(server,on_ready=None,module=None):
    """Prefer the embedded host; retain a working local UI without WebView2."""
    try:
        return _run_embedded(server,on_ready,module)
    except DesktopUnavailable as exc:
        if module is not None:
            raise
        return run_local_browser(server,on_ready,str(exc))


def run_local_browser(server,on_ready=None,reason=''):
    """Own the loopback service until the page's authenticated Quit action."""
    server.app.ui_mode='browser'
    server.app.desktop_host=None
    server.app.startup_note='Local browser mode: the embedded WebView is unavailable. All UI and project processing stay on this computer. Use Quit to stop the local service.'
    worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.15},daemon=True,name='wayricad-local-browser')
    worker.start()
    try:
        if not webbrowser.open(server.url,new=1):
            raise DesktopUnavailable('No local UI browser could be opened. '+reason)
        if on_ready:on_ready('browser')
        worker.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def _run_embedded(server,on_ready=None,module=None):
    """Run the native event loop on the main thread; own server shutdown too."""
    if threading.current_thread() is not threading.main_thread():raise RuntimeError('Desktop UI must run on the main thread.')
    if module is None:
        try:
            import wx.html2
        except ImportError:
            pass
        else:
            from .desktop_wx import run as run_local
            try:
                return run_local(server,on_ready)
            except DesktopUnavailable:
                raise
            except Exception as exc:
                raise DesktopUnavailable(unavailable_message(exc)) from exc
    try:module=module or importlib.import_module('webview')
    except ImportError as exc:raise DesktopUnavailable(unavailable_message(exc)) from exc
    host=DesktopHost(server,module);server.app.desktop_host=host;server.app.ui_mode='desktop'
    # Export blobs use our explicit native Save operation, not renderer-specific
    # download fallbacks. No file:// access, Python eval API or CSP weakening.
    module.settings['ALLOW_DOWNLOADS']=False
    module.settings['ALLOW_FILE_URLS']=False
    module.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=True
    root=Path(__file__).resolve().parents[1]
    icon=root/'resources'/('icon.ico' if sys.platform=='win32' else 'icon-48.png')
    stopped=threading.Event();ready=threading.Event();closing=threading.Event()
    def serve():
        try:server.serve_forever(poll_interval=.15)
        finally:stopped.set()
    def loaded():
        if not ready.is_set():
            ready.set()
            if on_ready:on_ready('desktop')
    def closed():
        closing.set()
        if not stopped.is_set():threading.Thread(target=server.shutdown,daemon=True,name='wayricad-desktop-stop').start()
    def close_after_quit():
        stopped.wait()
        if host.window is not None and not closing.is_set():
            # The in-program Quit action already asked about unsaved changes.
            host.window.confirm_close=False
            try:host.window.destroy()
            except Exception:pass
    worker=None
    try:
        project=server.app.workspace.project.pro_path.stem if server.app.workspace else 'Catalogue'
        host.window=module.create_window('WayriCAD BOM Studio — '+project,server.url,js_api=host.api,
            width=1440,height=940,min_size=(900,650),resizable=True,confirm_close=True,
            text_select=True,zoomable=True)
        host.api._window=host.window
        host.window.events.loaded += loaded
        host.window.events.closed += closed
        worker=threading.Thread(target=serve,daemon=True,name='wayricad-http');worker.start()
        threading.Thread(target=close_after_quit,daemon=True,name='wayricad-window-quit').start()
        renderer='edgechromium' if sys.platform=='win32' else 'cocoa' if sys.platform=='darwin' else 'qt'
        options={'gui':renderer,'debug':False,'private_mode':True,
                 'localization':{'global.quitConfirmation':'Close WayriCAD BOM Studio? Unsaved workspace, grid and form edits will be lost. Cancel and use Save workspace to keep them.'}}
        # macOS expects an .icns, not a PNG; retain its platform default here.
        if sys.platform!='darwin' and icon.is_file():options['icon']=str(icon)
        module.start(**options)
        if not ready.is_set() and not closing.is_set():raise DesktopUnavailable('Embedded window exited before loading the workspace.')
    except Exception as exc:
        if isinstance(exc,DesktopUnavailable):raise
        raise DesktopUnavailable(unavailable_message(exc)) from exc
    finally:
        closing.set()
        if worker:
            if not stopped.is_set():server.shutdown()
            worker.join(timeout=5)
        server.server_close()
        server.app.desktop_host=None
