"""wx/Agg plots also work with KiCad builds lacking optional wx.svg binaries."""
try:
    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg,NavigationToolbar2WxAgg
except (ImportError,ModuleNotFoundError):
    import wx
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    class FigureCanvasWxAgg(wx.Panel,FigureCanvasAgg):
        """Agg pixels in a native wx panel with pan, zoom and image export."""
        def __init__(self,parent,identifier,figure):
            wx.Panel.__init__(self,parent,identifier,style=wx.BORDER_NONE)
            FigureCanvasAgg.__init__(self,figure)
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self._bitmap=None;self._pending=False;self._closed=False;self._drag=None
            self.Bind(wx.EVT_PAINT,self._paint);self.Bind(wx.EVT_SIZE,self._resize)
            self.Bind(wx.EVT_MOUSEWHEEL,self._wheel);self.Bind(wx.EVT_LEFT_DOWN,self._down)
            self.Bind(wx.EVT_MOTION,self._motion);self.Bind(wx.EVT_LEFT_UP,self._up)
            self.Bind(wx.EVT_LEFT_DCLICK,lambda event:self.home())
            self.Bind(wx.EVT_WINDOW_DESTROY,self._destroy)

        def _destroy(self,event):
            if event.GetEventObject() is self:self._closed=True
            event.Skip()

        def draw(self):
            self._pending=False
            if self._closed:return
            width,height=self.GetClientSize()
            if width<2 or height<2:return
            self.figure.set_size_inches(width/self.figure.dpi,height/self.figure.dpi,forward=False)
            FigureCanvasAgg.draw(self)
            rgba=self.buffer_rgba();self._bitmap=wx.Bitmap.FromBufferRGBA(rgba.shape[1],rgba.shape[0],bytes(rgba))
            self.Refresh(False)

        def draw_idle(self,*args,**kwargs):
            if not self._pending and not self._closed:
                self._pending=True;wx.CallAfter(self.draw)

        def _paint(self,event):
            dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('white'));dc.Clear()
            if self._bitmap:dc.DrawBitmap(self._bitmap,0,0)

        def _resize(self,event):self.draw_idle();event.Skip()

        def _axes(self):return self.figure.axes[0] if self.figure.axes else None

        def _coordinate(self,event):
            axes=self._axes()
            if axes is None:return None
            pixel=(event.GetX(),self.GetClientSize().height-event.GetY())
            if not axes.bbox.contains(*pixel):return None
            return axes.transData.inverted().transform(pixel)

        def _down(self,event):
            coordinate=self._coordinate(event);axes=self._axes()
            if coordinate is not None:
                self._drag=(coordinate,axes.get_xlim(),axes.get_ylim())
                if not self.HasCapture():self.CaptureMouse()

        def _motion(self,event):
            if self._drag is None or not event.Dragging():return
            coordinate=self._coordinate(event)
            if coordinate is None:return
            previous,xlim,ylim=self._drag;dx,dy=coordinate-previous;axes=self._axes()
            axes.set_xlim(xlim[0]-dx,xlim[1]-dx);axes.set_ylim(ylim[0]-dy,ylim[1]-dy)
            self._drag=(coordinate,axes.get_xlim(),axes.get_ylim());self.draw_idle()

        def _up(self,event):
            self._drag=None
            if self.HasCapture():self.ReleaseMouse()

        def _wheel(self,event):self.zoom(.8 if event.GetWheelRotation()>0 else 1.25,self._coordinate(event))

        def zoom(self,factor,center=None):
            axes=self._axes()
            if axes is None:return
            xlim,ylim=axes.get_xlim(),axes.get_ylim()
            x,y=center if center is not None else ((xlim[0]+xlim[1])/2,(ylim[0]+ylim[1])/2)
            axes.set_xlim(*[x+(value-x)*factor for value in xlim]);axes.set_ylim(*[y+(value-y)*factor for value in ylim]);self.draw_idle()

        def home(self):
            axes=self._axes()
            if axes is not None and hasattr(axes,'_wayricad_home'):
                xlim,ylim=axes._wayricad_home;axes.set_xlim(*xlim);axes.set_ylim(*ylim);self.draw_idle()

    class NavigationToolbar2WxAgg(wx.Panel):
        def __init__(self,canvas):
            super().__init__(canvas.GetParent())
            self.canvas=canvas;sizer=wx.BoxSizer(wx.HORIZONTAL)
            for label,callback in [('Fit',lambda e:canvas.home()),('Zoom +',lambda e:canvas.zoom(.8)),('Zoom −',lambda e:canvas.zoom(1.25)),('Save image…',self.save)]:
                button=wx.Button(self,label=label,style=wx.BU_EXACTFIT);button.Bind(wx.EVT_BUTTON,callback);sizer.Add(button,0,wx.RIGHT,6)
            sizer.Add(wx.StaticText(self,label='Drag to pan · wheel to zoom · double-click to fit'),1,wx.ALIGN_CENTER_VERTICAL|wx.LEFT,12)
            self.SetSizer(sizer)

        def Realize(self):self.Layout()
        def update(self):pass

        def save(self,event):
            with wx.FileDialog(self,'Save plot',defaultFile='Quick-PI.png',wildcard='PNG image (*.png)|*.png',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal()==wx.ID_OK:self.canvas.figure.savefig(dialog.GetPath(),dpi=160,facecolor='white')
