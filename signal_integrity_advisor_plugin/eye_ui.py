"""Native wx plotting without a browser or plotting-library dependency."""
import wx
from .eye_view import plots


class EyePanel(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent)
        self.result=None;self.probes=[];self.hover=None;self._plot_regions=[]
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.Bind(wx.EVT_MOTION,self.inspect)
        self.Bind(wx.EVT_LEFT_DOWN,self.pin_probe)
        self.Bind(wx.EVT_RIGHT_DOWN,self.clear_probes)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((300,260))
        self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))

    def show_result(self,result):
        self.result=result;self.probes=[];self.hover=None;self._plot_regions=[]
        self.Refresh()

    def inspect(self,event):
        from .plot_probe import sample_at
        self.hover=None
        for index,(bounds,xs,traces,limits) in enumerate(self._plot_regions):
            left,top,right,bottom=bounds
            if left<=event.GetX()<=right and top<=event.GetY()<=bottom:
                x=xs[0]+(event.GetX()-left)/(right-left)*(xs[-1]-xs[0])
                lo,hi=limits;y=hi-(event.GetY()-top)/(bottom-top)*(hi-lo)
                sample=sample_at(xs,traces,x,y)
                if sample:self.hover=dict(sample,plot=index)
                break
        self.Refresh();event.Skip()

    def pin_probe(self,event):
        self.inspect(event)
        if self.hover and self.hover not in self.probes:self.probes.append(dict(self.hover))
        self.Refresh()

    def clear_probes(self,event):
        self.probes=[];self.Refresh()

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        self._plot_regions=[]
        dc.SetBackground(wx.Brush('#fafcfe'));dc.Clear()
        dc.SetTextForeground('#20303c')
        if not self.result or self.result.get('status')=='UNAVAILABLE':
            text=self.result['reason'] if self.result else 'Enable Illustrative eye, enter the bit rate and source swing, then screen the path.'
            for i,line in enumerate(__import__('textwrap').wrap(text,65)):
                dc.DrawText(line,15,15+20*i)
            return
        width,height=self.GetClientSize()
        if width<150 or height<180:return
        self._plot_regions=[]
        for index,(title,xlabel,xs,traces,(lo,hi)) in enumerate(plots(self.result)):
            top=index*height/2+28;bottom=(index+1)*height/2-35
            left,right=65,width-18
            self._plot_regions.append(((left,top,right,bottom),xs,traces,(lo,hi)))
            px=lambda value:left+(value-xs[0])/(xs[-1]-xs[0])*(right-left)
            py=lambda value:bottom-(value-lo)/(hi-lo)*(bottom-top)
            dc.DrawText(title,left,int(top-24))
            dc.SetPen(wx.Pen('#dde5eb'))
            for i in range(5):
                xv=xs[0]+(xs[-1]-xs[0])*i/4;yv=lo+(hi-lo)*i/4
                dc.DrawLine(int(px(xv)),int(top),int(px(xv)),int(bottom))
                dc.DrawLine(left,int(py(yv)),right,int(py(yv)))
                dc.DrawText(f'{xv:.3g}',int(px(xv)-10),int(bottom+3))
                dc.DrawText(f'{yv:.3g}',5,int(py(yv)-7))
            dc.DrawText(xlabel,int((left+right)/2-30),int(bottom+18))
            dc.DrawText('V',8,int(top-20))
            gc=wx.GraphicsContext.Create(dc)
            if gc:
                gc.SetPen(wx.Pen(wx.Colour(20,127,148,45 if len(traces)>1 else 255),1))
                for trace in traces:
                    path=gc.CreatePath();path.MoveToPoint(px(xs[0]),py(trace[0]))
                    for a,b in zip(xs[1:],trace[1:]):path.AddLineToPoint(px(a),py(b))
                    gc.StrokePath(path)

            visible=[probe for probe in self.probes+([self.hover] if self.hover else [])
                     if probe['plot']==index]
            for number,probe in enumerate(visible):
                sx,sy=int(px(probe['x'])),int(py(probe['voltage_v']))
                dc.SetPen(wx.Pen('#c45c12',1));dc.DrawLine(sx,int(top),sx,int(bottom))
                dc.SetBrush(wx.Brush('#c45c12'));dc.DrawCircle(sx,sy,3)
                dc.DrawText(f"{probe['x']:.5g} {('UI' if index==0 else 'ns')} · {probe['voltage_v']:.5g} V",left,int(top+3+number*16))
