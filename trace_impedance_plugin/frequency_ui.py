"""Compact native AC-loss sweep and export for reviewed copper geometry."""
import csv
import math
from pathlib import Path
import wx
from .frequency_analysis import sweep


class FrequencyPanel(wx.Panel):
    def __init__(self,parent,board_path=None):
        super().__init__(parent);self.board_path=Path(board_path).resolve() if board_path else None;self.path=None;self.result=None;self.hover=None
        s=wx.BoxSizer(wx.VERTICAL);controls=wx.BoxSizer(wx.HORIZONTAL)
        self.lo=wx.TextCtrl(self,value='0.001',size=(90,-1));self.hi=wx.TextCtrl(self,value='1000',size=(90,-1))
        for label,control in [('Start MHz',self.lo),('Stop MHz',self.hi)]:
            controls.Add(wx.StaticText(self,label=label),0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,5);controls.Add(control,0,wx.ALL,5)
            control.Bind(wx.EVT_TEXT,self.invalidate)
        button=wx.Button(self,label='Sweep reviewed path');button.Bind(wx.EVT_BUTTON,self.run);controls.Add(button,0,wx.ALL,5)
        self.export=wx.Button(self,label='Export CSV');self.export.Disable();self.export.Bind(wx.EVT_BUTTON,self.save);controls.Add(self.export,0,wx.ALL,5)
        s.Add(controls,0,wx.EXPAND)
        self.canvas=wx.Panel(self);self.canvas.SetBackgroundStyle(wx.BG_STYLE_PAINT);self.canvas.Bind(wx.EVT_PAINT,self.paint);self.canvas.Bind(wx.EVT_SIZE,lambda e:(self.canvas.Refresh(),e.Skip()));s.Add(self.canvas,1,wx.EXPAND)
        self.canvas.Bind(wx.EVT_MOTION,self.inspect)
        self.canvas.Bind(wx.EVT_LEAVE_WINDOW,self.leave)
        self.notes=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,110));s.Add(self.notes,0,wx.EXPAND|wx.ALL,5);self.SetSizer(s)

    def invalidate(self,event=None):
        self.result=None;self.hover=None;self.export.Disable();self.canvas.SetToolTip('');self.canvas.Refresh()
        if event:event.Skip()

    def set_path(self,path):
        self.path=path;self.invalidate();self.notes.SetValue('Analyze a path, then sweep its copper sections. Values are model estimates, not compliance results.')

    def run(self,event=None):
        self.invalidate()
        try:
            if not self.path:raise ValueError('Analyze a connected path first.')
            self.result=sweep(self.path,float(self.lo.GetValue()),float(self.hi.GetValue()))
            self.notes.SetValue('\n'.join(self.result['notes']));self.export.Enable();self.canvas.Refresh()
        except (ValueError,KeyError) as exc:self.notes.SetValue(str(exc))

    def inspect(self,event):
        if self.result:
            width=self.canvas.GetClientSize().width
            if width>180:
                rows=self.result['rows']
                self.hover=round(max(0,min(1,(event.GetX()-65)/(width-90)))*(len(rows)-1))
                row=rows[self.hover]
                self.canvas.SetToolTip(f"{row['frequency_mhz']:.5g} MHz\nOne-face R: {row['resistance_one_face_ohm']:.6g} Ω\nTwo-face R: {row['resistance_two_faces_ohm']:.6g} Ω\nSkin depth: {row['skin_depth_um']:.5g} µm")
                self.canvas.Refresh()
        event.Skip()

    def leave(self,event):
        self.hover=None;self.canvas.Refresh();event.Skip()

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self.canvas);dc.SetBackground(wx.Brush('#fafcfe'));dc.Clear();dc.SetTextForeground('#20303c')
        if not self.result:dc.DrawText('Frequency-dependent resistance: run a sweep to view the curves.',15,15);return
        rows=self.result['rows'];w,h=self.canvas.GetClientSize()
        if w<180 or h<130:return
        x0,x1=map(math.log10,(rows[0]['frequency_mhz'],rows[-1]['frequency_mhz']))
        ymax=max(r['resistance_one_face_ohm'] for r in rows)*1.1 or 1
        x=lambda v:65+(math.log10(v)-x0)/(x1-x0)*(w-90)
        y=lambda v:h-35-v/ymax*(h-75)
        dc.DrawText('R AC (ohm)   blue: one face   green: two faces',65,8)
        for i in range(5):
            freq=10**(x0+(x1-x0)*i/4);value=ymax*i/4
            dc.SetPen(wx.Pen('#dde5eb'));dc.DrawLine(int(x(freq)),40,int(x(freq)),h-35);dc.DrawLine(65,int(y(value)),w-25,int(y(value)))
            dc.DrawText(f'{freq:.3g}',int(x(freq)-14),h-29);dc.DrawText(f'{value:.3g}',4,int(y(value)-7))
        for key,color in [('resistance_one_face_ohm','#267ab0'),('resistance_two_faces_ohm','#2d9470')]:
            dc.SetPen(wx.Pen(color,2));dc.DrawLines([wx.Point(round(x(r['frequency_mhz'])),round(y(r[key]))) for r in rows])
        if self.hover is not None:
            row=rows[self.hover];px=round(x(row['frequency_mhz']))
            dc.SetPen(wx.Pen('#718096',1,wx.PENSTYLE_SHORT_DASH));dc.DrawLine(px,40,px,h-35)
            dc.SetBrush(wx.Brush('#267ab0'));dc.DrawCircle(px,round(y(row['resistance_one_face_ohm'])),4)
        dc.DrawText('Frequency (MHz), logarithmic',65,h-15)

    def save(self,event):
        if self.result is None:return
        with wx.FileDialog(self,'Export AC sweep',defaultDir=str(self.board_path.parent) if self.board_path else '',defaultFile=(self.board_path.stem if self.board_path else 'WayriCAD')+'-rlc-ac.csv',wildcard='CSV (*.csv)|*.csv',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            target=Path(dialog.GetPath())
            if target.suffix.lower()!='.csv':wx.MessageBox('Choose a separate .csv report.','Export',parent=self);return
            try:
                with target.open('w',encoding='utf-8-sig',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(self.result['rows'][0]));writer.writeheader();writer.writerows(self.result['rows'])
            except OSError as exc:wx.MessageBox(str(exc),'Export failed',parent=self)
