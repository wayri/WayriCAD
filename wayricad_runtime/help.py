"""Open packaged help in a native window, with a native HTML fallback."""
from pathlib import Path
from urllib.parse import urlparse, unquote


def open_help(parent, path, title='WayriCAD Help'):
    import wx
    import wx.html
    from .local_webview import try_new_webview
    path = Path(path).resolve()
    if not path.is_file():
        wx.MessageBox('Help file not found: ' + str(path), title, wx.OK | wx.ICON_ERROR, parent)
        return None
    # Reuse this tool's help window while it remains open.
    existing = getattr(parent, '_wayricad_help_window', None) if parent else None
    if existing and not existing.IsBeingDeleted() and getattr(existing, '_help_path', None) == path:
        existing.Show(); existing.Raise(); return existing
    frame = wx.Frame(parent, title=title, size=(1060, 780))
    frame._help_path = path
    panel = wx.Panel(frame); layout = wx.BoxSizer(wx.VERTICAL); panel.SetSizer(layout)
    viewer, reason = try_new_webview(panel)
    def external(url):
        if wx.MessageBox('Open this external reference in your browser?\n\n' + url, title,
                         wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, frame) == wx.YES:
            wx.LaunchDefaultBrowser(url)
    if viewer is not None:
        import wx.html2
        def navigate(event):
            url = event.GetURL(); parsed = urlparse(url)
            if parsed.scheme in ('http', 'https'):
                event.Veto(); external(url)
            elif parsed.scheme == 'file' and parsed.path.lower().endswith(('.md', '.txt')):
                event.Veto()
                local = unquote(parsed.path)
                if len(local) > 2 and local[0] == '/' and local[2] == ':': local = local[1:]
                document = Path(local).resolve()
                if not document.is_relative_to(path.parent): return
                dialog = wx.Dialog(frame, title=document.name, size=(940, 720), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
                content = wx.TextCtrl(dialog, value=document.read_text(encoding='utf-8'), style=wx.TE_MULTILINE | wx.TE_READONLY)
                box = wx.BoxSizer(wx.VERTICAL); box.Add(content, 1, wx.EXPAND | wx.ALL, 12)
                box.Add(dialog.CreateButtonSizer(wx.CLOSE), 0, wx.EXPAND | wx.ALL, 8); dialog.SetSizer(box)
                dialog.Bind(wx.EVT_BUTTON, lambda event: dialog.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)
                dialog.ShowModal(); dialog.Destroy()
            elif parsed.scheme not in ('file', 'about', ''): event.Veto()
        viewer.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, navigate)
        viewer.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Veto())
        viewer.LoadURL(path.as_uri())
    else:
        class NativeHtml(wx.html.HtmlWindow):
            def OnLinkClicked(self, link):
                url = link.GetHref()
                if url.startswith(('https://', 'http://')): external(url)
                else: super().OnLinkClicked(link)
        viewer = NativeHtml(panel, style=wx.html.HW_SCROLLBAR_AUTO)
        viewer.LoadPage(str(path)); viewer.SetToolTip(reason)
    layout.Add(viewer, 1, wx.EXPAND)
    close = wx.Button(panel, wx.ID_CLOSE, 'Close help')
    close.Bind(wx.EVT_BUTTON, lambda event: frame.Close())
    layout.Add(close, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
    if parent: parent._wayricad_help_window = frame
    frame.CentreOnParent(); frame.Show(); return frame


def open_tk_help(parent, path, title='WayriCAD Help'):
    """Tk tools get an in-app readable reference without starting another GUI loop."""
    import tkinter as tk
    from tkinter import scrolledtext
    from html.parser import HTMLParser
    class TextHelp(HTMLParser):
        def __init__(self): super().__init__(); self.parts=[]; self.hidden=0
        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style'): self.hidden += 1
            if tag in ('h1','h2','h3','p','li','br','tr'): self.parts.append('\n')
        def handle_endtag(self, tag):
            if tag in ('script', 'style'): self.hidden = max(0,self.hidden-1)
            if tag in ('h1','h2','h3','p','li','tr'): self.parts.append('\n')
        def handle_data(self, data):
            if not self.hidden: self.parts.append(data)
    path = Path(path)
    parser=TextHelp(); parser.feed(path.read_text(encoding='utf-8'))
    window=tk.Toplevel(parent); window.title(title); window.geometry('980x730')
    text=scrolledtext.ScrolledText(window, wrap='word', padx=22, pady=20, font=('Segoe UI',11))
    text.pack(fill='both',expand=True); text.insert('1.0',''.join(parser.parts)); text.configure(state='disabled')
    return window
