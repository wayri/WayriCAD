"""Native searchable offline help, F1 routing and packaged-image viewer.
Uses wx.html (not a browser or server). Native-host acceptance remains required.
"""
import html
from urllib.parse import urlparse
import wx
import wx.html
from .help_system import HelpLibrary,HelpHistory,plain_text

class HelpPanel(wx.Panel):
    def __init__(self,parent,initial='start'):
        super().__init__(parent)
        self.library=HelpLibrary();self.history=HelpHistory();self.current='start';self.rows=[];self._last_width=0
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        bar=wx.WrapSizer();root.Add(bar,0,wx.EXPAND|wx.ALL,10)
        self.back_button=self._button(bar,'Back',lambda e:self.navigate(self.history.back(),False))
        self.forward_button=self._button(bar,'Forward',lambda e:self.navigate(self.history.forward(),False))
        self._button(bar,'Home',lambda e:self.navigate('start'))
        self._button(bar,'UI gallery',lambda e:self.navigate('ui-gallery'))
        self._button(bar,'Constraint reference',lambda e:self.navigate('constraint-reference'))
        self._button(bar,'Copy topic text',self.copy)
        self.count=wx.StaticText(self,label='');bar.Add(self.count,0,wx.LEFT|wx.ALIGN_CENTER_VERTICAL,12)
        self.split=wx.SplitterWindow(self,style=wx.SP_LIVE_UPDATE);root.Add(self.split,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        left=wx.Panel(self.split);s=wx.BoxSizer(wx.VERTICAL);left.SetSizer(s)
        lab=wx.StaticText(left,label='SEARCH OFFLINE HELP');f=lab.GetFont();f.SetWeight(wx.FONTWEIGHT_BOLD);lab.SetFont(f);s.Add(lab,0,wx.ALL,8)
        self.search=wx.SearchCtrl(left,style=wx.TE_PROCESS_ENTER);self.search.ShowCancelButton(True);self.search.SetDescriptiveText('BGA, matrix, via_count, signing…')
        self.search.SetName('Search all offline help topics');self.search.SetToolTip('Search titles, keywords and complete topic text. No network request.');s.Add(self.search,0,wx.EXPAND|wx.ALL,8)
        self.sections=['All sections']+list(dict.fromkeys(t['section'] for t in self.library.topics))
        self.section=wx.Choice(left,choices=self.sections);self.section.SetSelection(0);self.section.SetName('Help section filter');s.Add(self.section,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.list=wx.ListBox(left);self.list.SetName('Help search results');s.Add(self.list,1,wx.EXPAND|wx.ALL,8)
        self.content=wx.html.HtmlWindow(self.split,style=wx.html.HW_SCROLLBAR_AUTO);self.content.SetStandardFonts(11);self.content.SetName('Offline help topic')
        self.split.SetMinimumPaneSize(190);self.split.SplitVertically(left,self.content,305);self.split.SetSashGravity(0.0)
        self.search.Bind(wx.EVT_TEXT,self.filter);self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN,self.clear_search)
        self.section.Bind(wx.EVT_CHOICE,self.filter);self.list.Bind(wx.EVT_LISTBOX,self.choose)
        self.content.Bind(wx.html.EVT_HTML_LINK_CLICKED,self.link);self.content.Bind(wx.EVT_SIZE,self.resized)
        self.Bind(wx.EVT_CHAR_HOOK,self.keys);self._populate();self.navigate(initial)
    def _button(self,sizer,title,fn):
        b=wx.Button(self,label=title);b.Bind(wx.EVT_BUTTON,fn);sizer.Add(b,0,wx.RIGHT|wx.BOTTOM,6);return b
    def _populate(self):
        section=self.section.GetStringSelection();section='' if section=='All sections' else section
        self.rows=self.library.search(self.search.GetValue(),section)
        self.list.Set([t['title'] for t in self.rows]);self.count.SetLabel(str(len(self.rows))+' of '+str(len(self.library.topics))+' topics · offline')
        for i,t in enumerate(self.rows):
            if t['id']==self.current:self.list.SetSelection(i);break
        self.Layout()
    def filter(self,event):self._populate()
    def clear_search(self,event):self.search.ChangeValue('');self._populate()
    def choose(self,event):
        i=self.list.GetSelection()
        if 0<=i<len(self.rows):self.navigate(self.rows[i]['id'])
    def navigate(self,id,remember=True):
        topic=self.library.topic(id);self.current=topic['id']
        if remember:self.history.visit(self.current)
        if self.current not in [t['id'] for t in self.rows]:
            self.search.ChangeValue('');self.section.SetSelection(0);self._populate()
        for i,t in enumerate(self.rows):
            if t['id']==self.current:self.list.SetSelection(i);break
        self.render();self.back_button.Enable(self.history.can_back);self.forward_button.Enable(self.history.can_forward)
    def render(self):
        width=max(240,self.content.GetClientSize().width-50);self._last_width=width
        self.content.SetPage(self.library.body(self.current,width));self.content.Scroll(0,0)
    def resized(self,event):
        event.Skip()
        width=max(240,self.content.GetClientSize().width-50)
        if abs(width-self._last_width)>32 and 'src="images/' in self.library.topic(self.current)['html']:
            # Refresh only image pages when width materially changes; ordinary text reflows natively.
            wx.CallAfter(self._resize_render)
    def _resize_render(self):
        if self and not self.IsBeingDeleted():self.render()
    def copy(self,event):
        t=self.library.topic(self.current);text=t['title']+'\n\n'+t['summary']+'\n\n'+plain_text(t['html'])
        if wx.TheClipboard.Open():
            try:wx.TheClipboard.SetData(wx.TextDataObject(text));wx.TheClipboard.Flush()
            finally:wx.TheClipboard.Close()
        else:wx.MessageBox('Clipboard is in use. Try again.','Offline help',wx.OK|wx.ICON_INFORMATION,self)
    def keys(self,event):
        if event.GetKeyCode()==ord('F') and event.ControlDown():self.search.SetFocus();self.search.SelectAll();return
        event.Skip()
    def link(self,event):
        href=event.GetLinkInfo().GetHref()
        try:
            if href.startswith('help:'):self.navigate(href[5:])
            elif href.startswith('asset:'):
                with HelpImageDialog(self,self.library.asset_path(href[6:])) as d:d.ShowModal()
            elif href.startswith('https://'):
                host=urlparse(href).hostname
                if host not in {'docs.kicad.org','dev-docs.kicad.org','docs.wxpython.org'}:raise ValueError('This external help destination is not on the reference allowlist.')
                if wx.MessageBox('Open this optional external reference in your browser?\n\n'+href,'External documentation',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION,self)==wx.YES:wx.LaunchDefaultBrowser(href)
            elif href.startswith('#'):self.content.ScrollToAnchor(href[1:])
            else:raise ValueError('Only packaged help/image links and explicit documentation references are supported.')
        except Exception as e:wx.MessageBox(str(e),'Offline help',wx.OK|wx.ICON_WARNING,self)

class HelpImageDialog(wx.Dialog):
    def __init__(self,parent,path):
        super().__init__(parent,title='UI render — '+path.name,style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER,size=(1280,860))
        self.original=wx.Image(str(path));root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        caption=wx.StaticText(self,label='SOURCE-DERIVED UI RENDER · illustrative values · not a native KiCad/wx screenshot');root.Add(caption,0,wx.ALL,12)
        row=wx.BoxSizer(wx.HORIZONTAL);root.Add(row,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        row.Add(wx.StaticText(self,label='Image zoom'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.zoom=wx.Choice(self,choices=['Fit width','100%','150%']);self.zoom.SetSelection(0);row.Add(self.zoom,0)
        self.scroller=wx.ScrolledWindow(self);self.scroller.SetScrollRate(12,12);root.Add(self.scroller,1,wx.EXPAND|wx.ALL,10)
        self.bitmap=wx.StaticBitmap(self.scroller,bitmap=wx.Bitmap(self.original));s=wx.BoxSizer(wx.VERTICAL);self.scroller.SetSizer(s);s.Add(self.bitmap,0)
        close=wx.Button(self,wx.ID_CLOSE,'Close');root.Add(close,0,wx.ALIGN_RIGHT|wx.ALL,10);close.Bind(wx.EVT_BUTTON,lambda e:self.EndModal(wx.ID_CLOSE))
        self.zoom.Bind(wx.EVT_CHOICE,lambda e:self.update_image());self.scroller.Bind(wx.EVT_SIZE,self.size_changed)
        area=wx.GetClientDisplayRect();self.SetSize((min(1280,area.width-40),min(860,area.height-60)));self.CenterOnParent();wx.CallAfter(self.update_image)
    def size_changed(self,event):event.Skip();wx.CallAfter(self.update_image)
    def update_image(self):
        if not self or self.IsBeingDeleted() or not self.original.IsOk():return
        w,h=self.original.GetWidth(),self.original.GetHeight()
        scale=min(1,max(100,self.scroller.GetClientSize().width-24)/w) if self.zoom.GetSelection()==0 else (1 if self.zoom.GetSelection()==1 else 1.5)
        size=(max(1,round(w*scale)),max(1,round(h*scale)))
        if tuple(self.bitmap.GetSize())==size:return
        self.bitmap.SetBitmap(wx.Bitmap(self.original.Scale(*size,wx.IMAGE_QUALITY_HIGH)));self.scroller.FitInside()

class HelpDialog(wx.Dialog):
    def __init__(self,parent,topic='start'):
        super().__init__(parent,title='Constraint Studio — Offline help',style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER,size=(1280,850))
        s=wx.BoxSizer(wx.VERTICAL);self.SetSizer(s);self.panel=HelpPanel(self,topic);s.Add(self.panel,1,wx.EXPAND)
        close=wx.Button(self,wx.ID_CLOSE,'Close help');s.Add(close,0,wx.ALIGN_RIGHT|wx.ALL,10);close.Bind(wx.EVT_BUTTON,lambda e:self.EndModal(wx.ID_CLOSE))
        area=wx.GetClientDisplayRect();self.SetSize((min(1280,area.width-40),min(850,area.height-60)));self.SetMinSize((650,420));self.CenterOnParent()

def show_help_dialog(parent,topic='start'):
    try:
        with HelpDialog(parent,topic) as d:d.ShowModal()
    except Exception as e:wx.MessageBox('Offline help could not be opened. Reinstall the matching complete package.\n\n'+str(e),'Constraint Studio help',wx.OK|wx.ICON_WARNING,parent)

def bind_dialog_help(dialog,topic):
    """Bind existing wx.ID_HELP button and F1 without changing OK/Cancel semantics."""
    def show(event):show_help_dialog(dialog,topic() if callable(topic) else topic)
    def key(event):
        if event.GetKeyCode()==wx.WXK_F1:show(event)
        else:event.Skip()
    dialog.Bind(wx.EVT_BUTTON,show,id=wx.ID_HELP);dialog.Bind(wx.EVT_CHAR_HOOK,key)
