"""Compact native controls for the saved-board analysis workspace."""
import math
import wx


def icon_button(parent, text, art, tooltip):
    button=wx.Button(parent,label=text,style=wx.BU_EXACTFIT)
    bitmap=wx.ArtProvider.GetBitmap(art,wx.ART_BUTTON,parent.FromDIP(wx.Size(16,16)))
    if bitmap.IsOk():button.SetBitmap(bitmap)
    button.SetToolTip(tooltip)
    button.SetName(text or tooltip)
    return button


class StatusText(wx.StaticText):
    def __init__(self,parent,label=''):
        super().__init__(parent,label=label,style=wx.ST_ELLIPSIZE_END)
        self.SetMinSize((1,-1));self.SetToolTip(label)

    def SetLabel(self,label):
        super().SetLabel(' '.join(label.splitlines()));self.SetToolTip(label)


class SidebarText(wx.StaticText):
    """Wrap long solver messages without widening the setup panel."""
    def __init__(self,parent,label='',width=218):
        self.wrap_width=parent.FromDIP(width)
        super().__init__(parent,label=label)
        self.SetMinSize((1,-1));self.Wrap(self.wrap_width);self.SetToolTip(label)

    def SetLabel(self,label):
        super().SetLabel(label);self.Wrap(self.wrap_width);self.SetToolTip(label)


class ColorLegend(wx.Panel):
    """Metric units and calibrated colours outside the board canvas."""
    def __init__(self,parent):
        super().__init__(parent,size=(-1,parent.FromDIP(52)))
        self.scale=None;self.SetMinSize((1,parent.FromDIP(52)))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint)

    def set_scale(self,scale):
        self.scale=scale;self.SetToolTip((scale or {}).get('note',''));self.Show(bool(scale));self.Refresh(False)
        self.GetParent().Layout()

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()));dc.Clear()
        if not self.scale:return
        from matplotlib import colormaps
        scale=self.scale;low,high=scale['limits'];cmap=colormaps.get_cmap(scale['cmap'])
        width=max(1,self.GetClientSize().width-2);font=self.GetFont();font.SetPointSize(8);dc.SetFont(font)
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        dc.DrawText(f"{scale['label']} · {scale['unit']}",0,0)
        for x in range(width):
            colour=cmap(x/max(1,width-1));dc.SetPen(wx.Pen(wx.Colour(*[round(255*v) for v in colour[:3]])))
            dc.DrawLine(x,self.FromDIP(18),x,self.FromDIP(29))
        lo,hi=f'{low:.5g}',f'{high:.5g}'
        dc.DrawText(lo,0,self.FromDIP(31));dc.DrawText(hi,max(0,width-dc.GetTextExtent(hi).width),self.FromDIP(31))


class BoardNavigation:
    """Simple direct pan/zoom for both native WxAgg and the KiCad Agg fallback."""
    mode=''
    def __init__(self,canvas):
        self.canvas=canvas;self.drag=None;self.connections=[]
        # The fallback canvas already supplies the same native mouse gestures.
        if not hasattr(canvas,'zoom'):
            for name,handler in [('button_press_event',self.down),('button_release_event',self.up),
                                 ('motion_notify_event',self.motion),('scroll_event',self.wheel)]:
                self.connections.append(canvas.mpl_connect(name,handler))

    def axes(self):
        return self.canvas.figure.axes[0] if self.canvas.figure.axes else None

    def update(self):pass

    def fit(self):
        ax=self.axes()
        if ax is None:return
        callback=getattr(ax,'_wayricad_fit',None)
        if callback:callback()
        elif hasattr(ax,'_wayricad_home'):
            x,y=ax._wayricad_home;ax.set_xlim(*x);ax.set_ylim(*y)
        self.canvas.draw_idle()

    def zoom(self,factor,center=None):
        ax=self.axes()
        if ax is None:return
        xlim,ylim=ax.get_xlim(),ax.get_ylim()
        x,y=center or ((xlim[0]+xlim[1])/2,(ylim[0]+ylim[1])/2)
        ax.set_xlim(*[x+(v-x)*factor for v in xlim]);ax.set_ylim(*[y+(v-y)*factor for v in ylim])
        self.canvas.draw_idle()

    def down(self,event):
        if event.dblclick:self.fit();return
        ax=self.axes()
        if event.button not in (1,3) or event.inaxes is not ax or event.xdata is None:return
        self.drag=(event.x,event.y,ax.get_xlim(),ax.get_ylim())

    def motion(self,event):
        ax=self.axes()
        if self.drag is None or ax is None:return
        x,y,xlim,ylim=self.drag
        dx=(event.x-x)*(xlim[1]-xlim[0])/max(1,ax.bbox.width)
        dy=(event.y-y)*(ylim[1]-ylim[0])/max(1,ax.bbox.height)
        ax.set_xlim(xlim[0]-dx,xlim[1]-dx);ax.set_ylim(ylim[0]-dy,ylim[1]-dy)
        self.canvas.draw_idle()

    def up(self,event):self.drag=None

    def wheel(self,event):
        if event.inaxes is self.axes():
            center=(event.xdata,event.ydata) if event.xdata is not None else None
            self.zoom(math.exp(-event.step*.15),center)
