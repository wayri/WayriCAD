"""Native wx plotting without a browser or plotting-library dependency."""
import wx
from .eye_view import plots


class EyePanel(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent)
        self.result=None;self._samples=[];self._hover=None;self._probes=[];self._cursor=None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((300,260))
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.Bind(wx.EVT_MOTION,self.motion);self.Bind(wx.EVT_LEFT_UP,self.pin);self.Bind(wx.EVT_RIGHT_UP,self.clear_probes)
        self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))

    def show_result(self,result):
        self.result=result;self._probes=[];self._hover=None
        self.Refresh()

    def motion(self,event):
        import math
        p=event.GetPosition();self._cursor=p
        candidates=[(math.hypot(p.x-row[0],p.y-row[1]),row) for row in self._samples]
        best=min(candidates,key=lambda v:v[0]) if candidates else None
        self._hover=best[1] if best and best[0]<12 else None;self.Refresh()

    def pin(self,event):
        if self._hover:self._probes.append(self._hover);self.Refresh()

    def clear_probes(self,event):
        self._probes=[];self.Refresh()

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush('#fafcfe'));dc.Clear()
        dc.SetTextForeground('#20303c')
        if not self.result or self.result.get('status')=='UNAVAILABLE':
            text=self.result['reason'] if self.result else 'Enable Illustrative eye, enter the bit rate and source swing, then screen the path.'
            for i,line in enumerate(__import__('textwrap').wrap(text,65)):
                dc.DrawText(line,15,15+20*i)
            return
        self._samples=[];self._coordinates={}
        width,height=self.GetClientSize()
        if width<150 or height<180:return
        for index,(title,xlabel,xs,traces,(lo,hi)) in enumerate(plots(self.result)):
            top=index*height/2+28;bottom=(index+1)*height/2-35
            left,right=65,width-18
            px=lambda value:left+(value-xs[0])/(xs[-1]-xs[0])*(right-left)
            py=lambda value:bottom-(value-lo)/(hi-lo)*(bottom-top)
            self._coordinates[xlabel]=(left,right,top,bottom,xs[0],xs[-1],lo,hi)
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
                    self._samples.extend((px(a),py(b),a,b,xlabel) for a,b in zip(xs,trace))
                    path=gc.CreatePath();path.MoveToPoint(px(xs[0]),py(trace[0]))
                    for a,b in zip(xs[1:],trace[1:]):path.AddLineToPoint(px(a),py(b))
                    gc.StrokePath(path)

        dc.SetTextForeground('#172832')
        if self._cursor:
            dc.SetPen(wx.Pen('#8999a5',1,wx.PENSTYLE_SHORT_DASH));dc.DrawLine(self._cursor.x,0,self._cursor.x,height);dc.DrawLine(0,self._cursor.y,width,self._cursor.y)
        if self._hover:
            _,_,x,v,label=self._hover;dc.DrawText(f'{label}: {x:.7g} | {v:.7g} V (click to probe; right-click clears)',15,height-18)
        for index,(x,y,t,v,label) in enumerate(self._probes):
            left,right,top,bottom,xmin,xmax,lo,hi=self._coordinates[label]
            x=left+(t-xmin)/(xmax-xmin)*(right-left);y=bottom-(v-lo)/(hi-lo)*(bottom-top)
            dc.SetPen(wx.Pen('#111',1));dc.DrawCircle(int(x),int(y),4);dc.DrawText(f'P{index+1}: {t:.5g}, {v:.5g} V',int(x+6),int(y-16))
