"""Local wx/WebView host using the same authenticated, limited desktop API."""
from concurrent.futures import Future
import json
import threading
import sys
from urllib.parse import urlsplit


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
            backend = wx.html2.WebViewBackendEdge if sys.platform == 'win32' else wx.html2.WebViewBackendDefault
            if not wx.html2.WebView.IsBackendAvailable(backend):
                self.Destroy()
                raise DesktopUnavailable('Local WebView runtime unavailable. On Windows install Microsoft Edge WebView2 Runtime.')
            self.view = wx.html2.WebView.New(self, backend=backend)
            layout = wx.BoxSizer(wx.VERTICAL)
            layout.Add(self.view, 1, wx.EXPAND)
            self.SetSizer(layout)
            self.api = DesktopAPI(server, Dialogs)
            self.api._window = self
            if not self.view.AddScriptMessageHandler('wayricad'):
                self.Destroy()
                raise DesktopUnavailable('This WebView lacks native message support. Update the local WebView runtime.')
            self.view.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self.message)
            self.view.Bind(wx.html2.EVT_WEBVIEW_LOADED, self.loaded)
            self.view.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.navigate)
            self.Bind(wx.EVT_CLOSE, self.close)
            self.view.LoadURL(server.url)

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
            self.view.RunScript("""
                (() => {
                  let next = 0; const pending = new Map();
                  window.wayricadReply = (id, result) => { const done=pending.get(id); if(done){pending.delete(id);done(result);} };
                  const call=(method,args)=>new Promise(resolve=>{const id=++next;pending.set(id,resolve);window.wayricad.postMessage(JSON.stringify({id,method,args}));});
                  window.pywebview={api:{save_download:(...args)=>call('save_download',args),open_external:(...args)=>call('open_external',args)}};
                  window.dispatchEvent(new Event('pywebviewready'));
                })();
            """)
            if on_ready:
                on_ready('desktop')

        def navigate(self, event):
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
    try:
        app.MainLoop()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
