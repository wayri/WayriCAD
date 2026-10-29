"""Lazy native HTML report viewer with explicit loading and error states."""
import sys
from html import escape
import wx
import wx.html2


class ReportPreview(wx.Panel):
    def __init__(self, parent, on_loaded, on_error):
        super().__init__(parent)
        self.on_loaded, self.on_error = on_loaded, on_error
        self.signature = None
        self.pending = False
        backend = wx.html2.WebViewBackendDefault
        if sys.platform == 'win32' and wx.html2.WebView.IsBackendAvailable(wx.html2.WebViewBackendEdge):
            backend = wx.html2.WebViewBackendEdge
        self.browser = wx.html2.WebView.New(self, backend=backend)
        self.browser.Bind(wx.html2.EVT_WEBVIEW_LOADED, self._loaded)
        self.browser.Bind(wx.html2.EVT_WEBVIEW_ERROR, self._error)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(self.browser, 1, wx.EXPAND)
        self.SetSizer(layout)

    def show_report(self, document, signature):
        self.signature = signature
        self.pending = True
        self.browser.SetPage(document, 'about:blank')
        self.Layout()

    def clear(self, message='Setup changed. Generate a report from new simulation results.'):
        self.signature = None
        self.pending = False
        self.browser.SetPage('<html><body style="font-family:system-ui;color:#65717f;padding:24px">'+escape(message)+'</body></html>', 'about:blank')

    def _loaded(self, event):
        if self.pending:
            self.pending = False
            self.on_loaded(self.signature)
        event.Skip()

    def _error(self, event):
        if self.pending:
            self.pending = False
            self.on_error(event.GetString() or 'The native HTML viewer could not load the report.')
        event.Skip()
