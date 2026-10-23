"""wx/Agg plots also work with KiCad builds lacking optional wx.svg binaries."""
import time
import wx


class _DrawScheduler:
    """Keep only the latest idle render, at most 30 per second per canvas."""
    def _cancel_draw(self):
        timer=getattr(self,'_render_timer',None)
        if timer is not None:
            timer.Stop();self._render_timer=None

    def _schedule_draw(self):
        if getattr(self,'_closed',False) or getattr(self,'_render_timer',None) is not None:return
        # Mouse events can arrive much faster than a large copper scene renders.
        # A single timer leaves room for input and always renders the newest limits.
        delay=max(1,round(1000*(1/30-(time.monotonic()-getattr(self,'_last_render',0)))))
        self._render_timer=wx.CallLater(delay,self._idle_draw)

    def _idle_draw(self):
        self._render_timer=None
        if not getattr(self,'_closed',False):self.draw()


try:
    from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as _NativeCanvas,NavigationToolbar2WxAgg

    class FigureCanvasWxAgg(_DrawScheduler,_NativeCanvas):
        """WxAgg with bounded, coalesced idle rendering during interaction."""
        def __init__(self,*args,**kwargs):
            self._closed=False;self._render_timer=None;self._last_render=0
            super().__init__(*args,**kwargs)
            self.Bind(wx.EVT_WINDOW_DESTROY,self._destroy_scheduler)

        def _destroy_scheduler(self,event):
            if event.GetEventObject() is self:
                self._closed=True;self._cancel_draw()
            event.Skip()

        def draw(self,*args,**kwargs):
            self._cancel_draw()
            if self._closed:return
            super().draw(*args,**kwargs)
            self._last_render=time.monotonic()

        def draw_idle(self,*args,**kwargs):self._schedule_draw()
except (ImportError,ModuleNotFoundError):
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    class FigureCanvasWxAgg(_DrawScheduler,wx.Panel,FigureCanvasAgg):
        """Agg pixels in a native wx panel with pan, zoom and image export."""
        def __init__(self,parent,identifier,figure):
            wx.Panel.__init__(self,parent,identifier,style=wx.BORDER_NONE)
            FigureCanvasAgg.__init__(self,figure)
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self._bitmap=None;self._closed=False;self._drag=None;self._pressed_button=None
            self._render_timer=None;self._last_render=0;self._pan_offset=(0,0)
            self.Bind(wx.EVT_PAINT,self._paint);self.Bind(wx.EVT_SIZE,self._resize)
            self.Bind(wx.EVT_MOUSEWHEEL,self._wheel);self.Bind(wx.EVT_LEFT_DOWN,self._down)
            self.Bind(wx.EVT_MOTION,self._motion);self.Bind(wx.EVT_LEFT_UP,self._up)
            self.Bind(wx.EVT_RIGHT_DOWN,lambda event:self._down(event,3))
            self.Bind(wx.EVT_RIGHT_UP,lambda event:self._up(event,3))
            self.Bind(wx.EVT_MIDDLE_DOWN,lambda event:self._down(event,2))
            self.Bind(wx.EVT_MIDDLE_UP,lambda event:self._up(event,2))
            self.Bind(wx.EVT_LEFT_DCLICK,lambda event:self.home())
            self.Bind(wx.EVT_WINDOW_DESTROY,self._destroy)
            self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,self._capture_lost)
            self.Bind(wx.EVT_LEAVE_WINDOW,self._leave)

        def _destroy(self,event):
            if event.GetEventObject() is self:
                self._closed=True;self._cancel_draw()
            event.Skip()

        def draw(self):
            self._cancel_draw()
            if self._closed:return
            width,height=self.GetClientSize()
            if width<2 or height<2:return
            self.figure.set_size_inches(width/self.figure.dpi,height/self.figure.dpi,forward=False)
            FigureCanvasAgg.draw(self)
            self._pan_offset=(0,0);self._last_render=time.monotonic()
            self._update_bitmap()

        def _update_bitmap(self):
            rgba=self.buffer_rgba()
            self._bitmap=wx.Bitmap.FromBufferRGBA(rgba.shape[1],rgba.shape[0],bytes(rgba))
            self.Refresh(False)

        def blit(self,bbox=None):
            """Publish restored Agg pixels after a probe-only artist redraw."""
            if not self._closed and self._drag is None:self._update_bitmap()

        def draw_idle(self,*args,**kwargs):
            if self._drag is None:self._schedule_draw()

        def _paint(self,event):
            dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('white'));dc.Clear()
            if self._bitmap:
                dc.DrawBitmap(self._bitmap,0,0)
                if self._pan_offset!=(0,0):
                    axes=self._axes()
                    if axes is not None:
                        left,bottom,width,height=axes.bbox.bounds
                        top=self.GetClientSize().height-bottom-height
                        dc.SetClippingRegion(round(left),round(top),round(width),round(height))
                        dc.SetBrush(wx.Brush(wx.Colour(*[round(255*c) for c in axes.get_facecolor()])))
                        dc.SetPen(wx.TRANSPARENT_PEN)
                        dc.DrawRectangle(round(left),round(top),round(width),round(height))
                        dc.DrawBitmap(self._bitmap,*self._pan_offset)
                        dc.DestroyClippingRegion()

        def _resize(self,event):self.draw_idle();event.Skip()

        def _axes(self):return self.figure.axes[0] if self.figure.axes else None

        def _coordinate(self,event):
            axes=self._axes()
            if axes is None:return None
            pixel=(event.GetX(),self.GetClientSize().height-event.GetY())
            if not axes.bbox.contains(*pixel):return None
            return axes.transData.inverted().transform(pixel)

        def _mouse_event(self,name,event,button=None,step=0,outside=False):
            from matplotlib.backend_bases import MouseEvent
            mouse=MouseEvent(name,self,event.GetX(),self.GetClientSize().height-event.GetY(),
                             button=button,step=step,guiEvent=event)
            if outside:mouse.inaxes=None;mouse.xdata=None;mouse.ydata=None
            if event.ControlDown():mouse.key='control'
            self.callbacks.process(name,mouse)

        def _down(self,event,button=1):
            self._mouse_event('button_press_event',event,button=button)
            coordinate=self._coordinate(event);axes=self._axes()
            if coordinate is not None and button in (1,2,3) and not event.ControlDown():
                # Capture 3D rotations too: a release outside this panel must
                # reach Matplotlib and the probe controller.
                self._pressed_button=button
                if not self.HasCapture():self.CaptureMouse()
                if button in (1,3) and not hasattr(axes,'get_proj'):
                    self._cancel_draw()
                    self._drag=(event.GetX(),event.GetY(),axes.get_xlim(),axes.get_ylim())
            event.Skip()

        def _motion(self,event):
            if self._drag is None:
                self._mouse_event('motion_notify_event',event)
                event.Skip();return
            if not event.Dragging():return
            x,y,xlim,ylim=self._drag;axes=self._axes()
            dx=(event.GetX()-x)*(xlim[1]-xlim[0])/max(1,axes.bbox.width)
            dy=-(event.GetY()-y)*(ylim[1]-ylim[0])/max(1,axes.bbox.height)
            axes.set_xlim(xlim[0]-dx,xlim[1]-dx);axes.set_ylim(ylim[0]-dy,ylim[1]-dy)
            # Shift existing pixels while dragging instead of re-tessellating and
            # rasterising every copper polygon on every mouse event. Release
            # always requests a complete, exact render of the final limits.
            self._pan_offset=(event.GetX()-x,event.GetY()-y)
            self.Refresh(False)
            event.Skip()

        def _up(self,event,button=1):
            had_drag=self._drag is not None
            self._drag=None;self._pressed_button=None
            if self.HasCapture():self.ReleaseMouse()
            self._mouse_event('button_release_event',event,button=button)
            if had_drag:self.draw_idle()
            event.Skip()

        def _capture_lost(self,event):
            button=self._pressed_button
            self._drag=None;self._pressed_button=None
            if button is not None:
                from matplotlib.backend_bases import MouseEvent
                # Cancellation must clear both Axes3D rotation and pending
                # probes without creating a click at the old press location.
                mouse=MouseEvent('button_release_event',self,-1,-1,button=button,guiEvent=event)
                self.callbacks.process('button_release_event',mouse)
            self.draw_idle();event.Skip()

        def _leave(self,event):
            if self._drag is None:self._mouse_event('motion_notify_event',event,outside=True)
            event.Skip()

        def _wheel(self,event):
            handler=getattr(self,'_wayricad_scroll_handler',None)
            if handler:
                from matplotlib.backend_bases import MouseEvent
                step=event.GetWheelRotation()/max(1,event.GetWheelDelta())
                mouse=MouseEvent('scroll_event',self,event.GetX(),self.GetClientSize().height-event.GetY(),
                                 button='up' if step>0 else 'down',step=step,guiEvent=event,
                                 key='control' if event.ControlDown() else None)
                if handler(mouse):return
            axes=self._axes()
            if axes is not None and hasattr(axes,'get_proj'):
                step=event.GetWheelRotation()/max(1,event.GetWheelDelta())
                self._mouse_event('scroll_event',event,button='up' if step>0 else 'down',step=step)
            else:self.zoom(.8 if event.GetWheelRotation()>0 else 1.25,self._coordinate(event))

        def zoom(self,factor,center=None):
            axes=self._axes()
            if axes is None:return
            xlim,ylim=axes.get_xlim(),axes.get_ylim()
            x,y=center if center is not None else ((xlim[0]+xlim[1])/2,(ylim[0]+ylim[1])/2)
            axes.set_xlim(*[x+(value-x)*factor for value in xlim]);axes.set_ylim(*[y+(value-y)*factor for value in ylim]);self.draw_idle()

        def home(self):
            axes=self._axes()
            if axes is None:return
            callback=getattr(axes,'_wayricad_fit',None)
            if callback:callback();self.draw_idle()
            elif hasattr(axes,'_wayricad_home'):
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
