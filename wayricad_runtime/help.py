"""Open packaged help in a native window, with a native HTML fallback."""
from pathlib import Path
from urllib.parse import urlparse, unquote,urljoin


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
    def text_document(document):
        if not document.is_relative_to(path.parent) or not document.is_file():return
        try:text=document.read_text(encoding='utf-8-sig')
        except (OSError,UnicodeError) as exc:
            wx.MessageBox('Cannot read this local reference: '+str(exc),title,wx.OK|wx.ICON_ERROR,frame);return
        dialog=wx.Dialog(frame,title=document.name,size=(940,720),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        content=wx.TextCtrl(dialog,value=text,style=wx.TE_MULTILINE|wx.TE_READONLY)
        box=wx.BoxSizer(wx.VERTICAL);box.Add(content,1,wx.EXPAND|wx.ALL,12)
        box.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.EXPAND|wx.ALL,8);dialog.SetSizer(box)
        dialog.Bind(wx.EVT_BUTTON,lambda event:dialog.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        dialog.ShowModal();dialog.Destroy()
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
                text_document(document)
            elif parsed.scheme not in ('file', 'about', ''): event.Veto()
        viewer.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, navigate)
        viewer.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Veto())
        viewer.LoadURL(path.as_uri())
    else:
        class NativeHtml(wx.html.HtmlWindow):
            def __init__(self,parent):
                super().__init__(parent,style=wx.html.HW_SCROLLBAR_AUTO)
                self.SetBorders(12);self._timer=None;self._render_width=None;self._rendered_html='';self._document=path
                self._canonical=path.read_text(encoding='utf-8-sig');self._dead=False;self._dimensions={}
                self.Bind(wx.EVT_SIZE,self._resized);self.Bind(wx.EVT_WINDOW_DESTROY,self._destroyed)
                wx.CallAfter(self._reflow)

            def _resized(self,event):
                if not self._dead:
                    if self._timer:self._timer.Stop()
                    self._timer=wx.CallLater(80,self._reflow)
                event.Skip()

            def _destroyed(self,event):
                if event.GetEventObject() is self:
                    self._dead=True
                    if self._timer:self._timer.Stop();self._timer=None
                event.Skip()

            def _reflow(self):
                self._timer=None
                if self._dead or self.IsBeingDeleted():return
                available=max(1,self.GetClientSize().width-24-max(16,wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X))-8)
                if available==self._render_width:return
                from .help_images import responsive_html
                old_range=max(1,self.GetScrollRange(wx.VERTICAL)-self.GetScrollThumb(wx.VERTICAL))
                position=self.GetViewStart();fraction=position[1]/old_range
                markup=responsive_html(self._canonical,self._document.parent,available,reader=self._image_size)
                self._render_width=available;self._rendered_html=markup
                self.SetPage(markup)
                # Relative images are absolute local URIs in the rendered copy;
                # relative links continue to resolve from the current document.
                extent=max(0,self.GetScrollRange(wx.VERTICAL)-self.GetScrollThumb(wx.VERTICAL))
                self.Scroll(position[0],round(fraction*extent))

            def _image_size(self,document):
                from .help_images import image_dimensions
                stat=document.stat();key=(document,stat.st_mtime_ns,stat.st_size)
                if key not in self._dimensions:
                    size=image_dimensions(document)
                    if size is None:
                        image=wx.Image(str(document),wx.BITMAP_TYPE_ANY)
                        size=(image.GetWidth(),image.GetHeight()) if image.IsOk() else None
                    self._dimensions[key]=size
                return self._dimensions[key]

            def OnLinkClicked(self, link):
                url=link.GetHref()
                if url.startswith('#'):
                    self.ScrollToAnchor(unquote(url[1:]));return
                parsed=urlparse(urljoin(self._document.as_uri(),url))
                if parsed.scheme in ('http','https'):external(parsed.geturl());return
                if parsed.scheme!='file' or parsed.netloc:return
                local=unquote(parsed.path)
                if len(local)>2 and local[0]=='/' and local[2]==':':local=local[1:]
                document=Path(local).resolve()
                if not document.is_relative_to(path.parent) or not document.is_file():return
                if document.suffix.lower() in ('.md','.txt'):text_document(document);return
                if document.suffix.lower() not in ('.html','.htm'):return
                if document!=self._document:
                    try:canonical=document.read_text(encoding='utf-8-sig')
                    except (OSError,UnicodeError):return
                    self._canonical=canonical;self._document=document;self._render_width=None;self.Scroll(0,0);self._reflow()
                if parsed.fragment:self.ScrollToAnchor(unquote(parsed.fragment))
        viewer = NativeHtml(panel)
        viewer.SetToolTip(reason)
    frame._help_viewer=viewer
    layout.Add(viewer, 1, wx.EXPAND)
    close = wx.Button(panel, wx.ID_CLOSE, 'Close help')
    close.Bind(wx.EVT_BUTTON, lambda event: frame.Close())
    layout.Add(close, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
    if parent: parent._wayricad_help_window = frame
    from .layout import fit_to_display
    frame.CentreOnParent(); fit_to_display(frame); frame.Show(); return frame


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
