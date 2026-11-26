"""Render sanitized Assistant evidence in an inline, network-isolated report pane."""
from base64 import b64encode
from hashlib import sha256
from html import escape
from io import BytesIO

import wx
import wx.html

from .result_preview import MAX_WEB_DOCUMENT, web_document

_DATA_URL_PREFIX = b"data:text/html;charset=utf-8;base64,"


class ReportView(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        self._browser = None
        self._browser_checked = False
        self._browser_ready = False
        self._browser_document = None
        self._browser_digest = None
        self._browser_title = None
        self._serial = 0
        self._image = wx.StaticBitmap(self)
        self._image.Hide()
        self._text = wx.html.HtmlWindow(self)
        self._text.SetBorders(self.FromDIP(10))
        self._text.Bind(wx.html.EVT_HTML_LINK_CLICKED, lambda event: None)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(self._image, 0, wx.ALIGN_CENTER | wx.ALL, self.FromDIP(4))
        layout.Add(self._text, 1, wx.EXPAND)
        self.SetSizer(layout)

    def clear(self):
        self.message('')

    def message(self, text):
        self._show_native(f'<p>{escape(text)}</p>' if text else '')

    def render(self, name, content, png, svg):
        content = content or f'<p>{escape(name)}</p>'
        self._show_native(content, png, svg)
        self._serial += 1
        title = f'WayriCAD Assistant result {self._serial}'
        document = web_document(title, content, png, svg)
        if document is None:
            return
        browser = self._get_browser()
        if browser is not None:
            self._browser_title = title
            self._browser_document = document
            if self._browser_ready:
                self._set_browser_page()

    def _set_browser_page(self):
        if not self._browser_document or self.IsBeingDeleted():
            return
        document, self._browser_document = self._browser_document, None
        self._browser_digest = sha256(_DATA_URL_PREFIX + b64encode(document.encode('utf-8'))).digest()
        try:
            self._browser.SetPage(document, 'about:blank')
        except RuntimeError:
            self._browser_title = None
            self._browser_digest = None

    def _show_native(self, content, png=None, svg=None):
        self._browser_title = None
        self._browser_document = self._browser_digest = None
        if self._browser is not None:
            self._browser.Hide()
        self._image.Hide()
        self._image.SetBitmap(wx.NullBitmap)
        width = max(160, min(self.GetClientSize().width - 24, 1000))
        height = max(80, min(self.GetClientSize().height // 2, 320))
        bitmap = None
        if png:
            image = wx.Image(BytesIO(png), wx.BITMAP_TYPE_PNG)
            if image.IsOk():
                factor = min(1, width / image.GetWidth(), height / image.GetHeight())
                bitmap = wx.Bitmap(image.Scale(max(1, round(image.GetWidth() * factor)),
                                               max(1, round(image.GetHeight() * factor)), wx.IMAGE_QUALITY_HIGH))
        elif svg and hasattr(wx.BitmapBundle, 'FromSVG'):
            size = wx.Size(width, height)
            bundle = wx.BitmapBundle.FromSVG(svg, size)
            if bundle.IsOk():
                bitmap = bundle.GetBitmap(size)
        if bitmap is not None and bitmap.IsOk():
            self._image.SetBitmap(bitmap)
            self._image.Show()
        self._text.SetPage('<body>' + content + '</body>')
        self._text.Show()
        self.Layout()

    def _get_browser(self):
        if not self._browser_checked:
            self._browser_checked = True
            from wayricad_runtime.local_webview import try_new_webview
            self._browser, _ = try_new_webview(self, url='about:blank')
            if self._browser is not None:
                import wx.html2 as html2
                self._browser.Hide()
                self._browser.EnableContextMenu(False)
                self._browser.EnableHistory(False)
                self._browser.Bind(html2.EVT_WEBVIEW_NAVIGATING, self._navigate)
                self._browser.Bind(html2.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Veto())
                self._browser.Bind(html2.EVT_WEBVIEW_LOADED, self._loaded)
                self.GetSizer().Add(self._browser, 1, wx.EXPAND)
                self._browser.LoadURL('about:blank')
        return self._browser

    def _navigate(self, event):
        url = event.GetURL()
        allowed = url == 'about:blank'
        # wx Edge turns SetPage into a data URL. Accept only the exact
        # in-memory document generated for this report, including its CSP.
        if not allowed and self._browser_digest and len(url) <= 2 * MAX_WEB_DOCUMENT:
            encoded = url.encode('utf-8')
            allowed = (encoded.startswith(_DATA_URL_PREFIX)
                       and sha256(encoded).digest() == self._browser_digest)
        if allowed:
            event.Skip()
        else:
            event.Veto()

    def _loaded(self, event):
        if not self._browser_ready:
            self._browser_ready = True
            self._set_browser_page()
            event.Skip()
            return
        # Retain native content until the expected document has actually loaded.
        # An earlier asynchronous report may finish after the user changes selection.
        if self._browser_title and self._browser.GetCurrentTitle() == self._browser_title:
            self._text.Hide()
            self._image.Hide()
            self._browser.Show()
            self.Layout()
        event.Skip()
