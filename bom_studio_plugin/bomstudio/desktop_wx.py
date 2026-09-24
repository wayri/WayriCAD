"""Local wx/WebView host using the same authenticated, limited desktop API."""
from concurrent.futures import Future
import json
import os
import tempfile
import shutil
import threading
import sys
from pathlib import Path
from urllib.parse import urlsplit


def _set_window_icon(window, wx):
    """Give the preferred wx/WebView window its own taskbar identity."""
    icon_path = Path(__file__).resolve().parents[1] / 'resources' / 'icon.ico'
    if sys.platform != 'win32' or not icon_path.is_file():
        return False
    try:
        icon = wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO)
        if not icon.IsOk():
            return False
        window.SetIcon(icon)
    except Exception:
        # Optional branding must never prevent the editor action from opening.
        return False
    return True


def _workspace_loaded(window, event, expected_url, on_ready=None):
    """Ignore initial blank pages and subdocuments before bridging the workspace."""
    # The app consumes and clears its session-token fragment during startup.
    # Match the document (including query), not that transient fragment.
    expected = urlsplit(expected_url)._replace(fragment='')
    if (urlsplit(event.GetURL())._replace(fragment='') != expected
            or urlsplit(window.view.GetCurrentURL())._replace(fragment='') != expected
            or event.GetTarget()):
        return
    _initialize_bridge(window, on_ready)


def _initialize_bridge(window, on_ready=None):
    """Queue bridge setup once, without pumping a synchronous native event loop."""
    if window.ready:
        return
    window.ready = True
    try:
        window.view.RunScriptAsync("""
                (() => {
                  let next = 0; const pending = new Map();
                  window.wayricadReply = (id, result) => { const done=pending.get(id); if(done){pending.delete(id);done(result);} };
                  const call=(method,args)=>new Promise(resolve=>{const id=++next;pending.set(id,resolve);window.wayricad.postMessage(JSON.stringify({id,method,args}));});
                  window.pywebview={api:{save_download:(...args)=>call('save_download',args),open_external:(...args)=>call('open_external',args)}};
                  window.dispatchEvent(new Event('pywebviewready'));
                })();
            """)
    except Exception:
        window.ready = False
        raise
    if hasattr(window, 'loading'):
        window.loading.Hide()
        window.Layout()
    if on_ready:
        on_ready('desktop')


def run(server, on_ready=None):
    import wx
    import wx.html2
    from .desktop import DesktopAPI, DesktopUnavailable

    app = wx.App.Get() or wx.App(False)
    closing = threading.Event()

    def main_thread(fn):
        if wx.IsMainThread():
            return fn()
        result = Future()
        def call():
            try:
                result.set_result(fn())
            except Exception as exc:
                result.set_exception(exc)
        wx.CallAfter(call)
        return result.result(timeout=300)

    class Dialogs:
        SAVE_DIALOG = 'save'
        OPEN_DIALOG = 'open'

    class Window(wx.Frame):
        def __init__(self):
            super().__init__(None, title='WayriCAD BOM Studio', size=(1280, 850))
            self.SetMinSize((860, 620))
            _set_window_icon(self, wx)
            backend = wx.html2.WebViewBackendEdge if sys.platform == 'win32' else wx.html2.WebViewBackendDefault
            if not wx.html2.WebView.IsBackendAvailable(backend):
                self.Destroy()
                raise DesktopUnavailable('Local WebView runtime unavailable. On Windows install Microsoft Edge WebView2 Runtime.')
            # WebView2's default profile is shared by every python.exe plugin.
            # Separate IPC processes cannot safely lock that same profile.
            # Set before Create: Edge reads this for its child environment.
            self.profile = tempfile.mkdtemp(prefix='wayricad-bom-webview-')
            self.previous_profile = os.environ.get('WEBVIEW2_USER_DATA_FOLDER')
            try:
                if sys.platform == 'win32':
                    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = self.profile
                self.view = wx.html2.WebView.New(self, backend=backend)
            except Exception:
                self.restore_profile()
                shutil.rmtree(self.profile, ignore_errors=True)
                self.Destroy()
                raise
            layout = wx.BoxSizer(wx.VERTICAL)
            self.loading = wx.StaticText(self, label='  Loading the local BOM workspace…')
            layout.Add(self.loading, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
            layout.Add(self.view, 1, wx.EXPAND)
            self.SetSizer(layout)
            self.api = DesktopAPI(server, Dialogs)
            self.api._window = self
            if not self.view.AddScriptMessageHandler('wayricad'):
                self.Destroy()
                raise DesktopUnavailable('This WebView lacks native message support. Update the local WebView runtime.')
            self.view.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self.message)
            self.ready = False
            self.view.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.loaded)
            self.view.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.navigate)
            self.Bind(wx.EVT_CLOSE, self.close)

        def restore_profile(self):
            if sys.platform == 'win32':
                if self.previous_profile is None: os.environ.pop('WEBVIEW2_USER_DATA_FOLDER', None)
                else: os.environ['WEBVIEW2_USER_DATA_FOLDER'] = self.previous_profile

        def get_current_url(self):
            return main_thread(self.view.GetCurrentURL)

        def create_file_dialog(self, kind, save_filename='', **kwargs):
            def choose():
                style = wx.FD_SAVE if kind == 'save' else wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
                wildcard = 'All files (*.*)|*.*' if kind == 'save' else 'KiCad project (*.kicad_pro;*.kicad_sch)|*.kicad_pro;*.kicad_sch'
                with wx.FileDialog(self, 'Save export' if kind == 'save' else 'Open project',
                                   defaultFile=save_filename, wildcard=wildcard, style=style) as dialog:
                    return [dialog.GetPath()] if dialog.ShowModal() == wx.ID_OK else []
            return main_thread(choose)

        def loaded(self, event):
            # Synchronous RunScript here re-enters LOADED in WebView2 and can
            # stall until the startup watchdog despite a successfully loaded UI.
            _workspace_loaded(self, event, server.url, on_ready)

        def navigate(self, event):
            if event.GetURL() == 'about:blank' and not self.ready:
                return
            target = urlsplit(event.GetURL())
            origin = urlsplit(server.origin)
            if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                event.Veto()

        def message(self, event):
            identifier = None
            try:
                data = json.loads(event.GetString())
                identifier = data['id']
                if type(identifier) is not int or data['method'] not in ('save_download', 'open_external'):
                    raise ValueError('Unsupported native action.')
                result = getattr(self.api, data['method'])(*data['args'])
            except Exception as exc:
                result = {'ok': False, 'error': str(exc)}
            self.view.RunScript('window.wayricadReply(' + json.dumps(identifier) + ',' + json.dumps(result) + ');')

        def close(self, event):
            if event.CanVeto() and not closing.is_set():
                if wx.MessageBox('Close BOM Studio? Save workspace changes before closing.',
                                 'WayriCAD BOM Studio', wx.YES_NO | wx.NO_DEFAULT, self) != wx.YES:
                    event.Veto()
                    return
            closing.set()
            threading.Thread(target=server.shutdown, daemon=True).start()
            self.Destroy()

    class Host:
        def pick_project(self):
            paths = window.create_file_dialog('open')
            return paths[0] if paths else ''

    window = Window()
    server.app.desktop_host = Host()
    server.app.ui_mode = 'desktop'
    def serve():
        try:
            server.serve_forever(poll_interval=.15)
        finally:
            if not closing.is_set():
                closing.set()
                wx.CallAfter(window.Close)
    worker = threading.Thread(target=serve, name='wayricad-local-ui', daemon=True)
    worker.start()
    window.Show()
    window.view.LoadURL(server.url)
    startup_error = []
    def check_startup():
        if not window.ready and not closing.is_set():
            startup_error.append('The embedded browser did not load the local BOM workspace within 20 seconds. Check WebView runtime installation or use local browser mode.')
            closing.set()
            window.Close(force=True)
    startup_timer = wx.CallLater(20000, check_startup)
    try:
        app.MainLoop()
        if startup_error: raise DesktopUnavailable(startup_error[0])
    finally:
        startup_timer.Stop()
        window.restore_profile()
        server.shutdown()
        if not startup_error: server.server_close()
        worker.join(timeout=5)
        shutil.rmtree(window.profile, ignore_errors=True)
