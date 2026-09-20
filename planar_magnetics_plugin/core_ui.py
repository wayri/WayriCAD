"""Local dimensional core editor and inspectable nonlinear circuit sweep."""
import csv
import threading
from dataclasses import replace
import wx
from .magnetic_circuit import current_sweep, validate_core, transformer_flux_swing


class StepPreview(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent);self.geometry=None;self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_SIZE,lambda e:(self.Refresh(),e.Skip()))

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)));dc.Clear()
        if not self.geometry:return
        points=[(x-y,.45*(x+y)-z) for x,y,z in self.geometry['vertices_mm']]
        if not points:return
        xs,ys=zip(*points);lowx,lowy=min(xs),min(ys);spanx,spany=max(xs)-lowx,max(ys)-lowy
        width,height=self.GetClientSize();scale=min(max(1,width-30)/max(spanx,1e-9),max(1,height-30)/max(spany,1e-9))
        mapped=[wx.Point(round(15+(x-lowx)*scale),round(15+(y-lowy)*scale)) for x,y in points]
        dc.SetPen(wx.Pen(wx.Colour('#478ba8'),1))
        # Bounded display work. Inspection/export retains the complete tessellation.
        faces=self.geometry['triangles'];stride=max(1,(len(faces)+4999)//5000)
        for a,b,c in faces[::stride]:dc.DrawLines([mapped[a],mapped[b],mapped[c],mapped[a]])


class StepCoreDialog(wx.Dialog):
    def __init__(self,parent,path):
        super().__init__(parent,title='STEP core · geometry reference',size=(760,600))
        self.SetSize(self.FromDIP((760,600)))
        root=wx.BoxSizer(wx.VERTICAL);self.status=wx.StaticText(self,label='Inspecting solid in an isolated FreeCAD process…');root.Add(self.status,0,wx.ALL,12)
        self.preview=StepPreview(self);root.Add(self.preview,1,wx.EXPAND|wx.ALL,12)
        root.Add(wx.StaticText(self,label='Geometry reference only: enter Ae, le, air gap and material in Edit custom core.\nThis tessellation is a surface preview, not a magnetic solver mesh.'),0,wx.ALL,12)
        root.Add(self.CreateButtonSizer(wx.CLOSE),0,wx.ALL|wx.ALIGN_RIGHT,12);self.SetSizer(root)
        def work():
            from .step_core import inspect_step
            try:result,error=inspect_step(path),None
            except Exception as exc:result,error=None,str(exc)
            wx.CallAfter(self.complete,result,error)
        threading.Thread(target=work,daemon=True).start()

    def complete(self,result,error):
        if not self or self.IsBeingDeleted():return
        if error:self.status.SetLabel(error);self.status.Wrap(710);self.Layout();return
        self.preview.geometry=result;self.preview.Refresh()
        dims=' × '.join(f'{x:.5g}' for x in result['bounding_dimensions_mm'])
        self.status.SetLabel(f"{result['solid_count']} solids · bounds {dims} mm · volume {result['solid_volume_mm3']:.6g} mm³\n{result['engine']} · surface wireframe preview")


class CoreEditor(wx.Dialog):
    def __init__(self, parent, core):
        super().__init__(parent, title='Custom magnetic core', size=(590, 650))
        self.SetSize(self.FromDIP((590,650)))
        self.core = core
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self, label='Effective magnetic dimensions, not outside STEP bounds.\nUse supplier data or a justified magnetic path.'), 0, wx.ALL, 12)
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=10); grid.AddGrowableCol(1)
        self.fields = {}
        for name, label in [('name','Name'), ('effective_area_mm2','Effective area Ae (mm²)'),
                            ('path_length_mm','Core path le (mm)'), ('gap_mm','Total series air gap (mm)'),
                            ('permeability','Relative permeability'), ('saturation_t','Saturation threshold (T)')]:
            grid.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control = wx.TextCtrl(self,value=str(getattr(core,name))); self.fields[name]=control
            grid.Add(control,1,wx.EXPAND)
        root.Add(grid,0,wx.EXPAND|wx.ALL,12)
        root.Add(wx.StaticText(self,label='Optional B-H samples: B (T), H (A/m), one pair per line.\nStart at 0,0; both columns must increase. No extrapolation.'),0,wx.ALL,12)
        self.bh = wx.TextCtrl(self,value='\n'.join(f'{b},{h}' for b,h in core.bh_points),style=wx.TE_MULTILINE)
        root.Add(self.bh,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        root.Add(self.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALL|wx.ALIGN_RIGHT,12)
        self.SetSizer(root); self.Bind(wx.EVT_BUTTON,self.accept,id=wx.ID_OK)

    def accept(self,event):
        try:
            values={key:control.GetValue().strip() if key=='name' else float(control.GetValue()) for key,control in self.fields.items()}
            if not values['name']: raise ValueError('Core name is required')
            points=tuple(tuple(float(v.strip()) for v in line.split(',')) for line in self.bh.GetValue().splitlines() if line.strip())
            # Edited dimensions/material invalidate canned loss coefficients.
            self.result=replace(self.core,**values,family='Custom',material='User defined',bh_points=points,loss_k=0.)
            validate_core(self.result)
        except (TypeError,ValueError) as exc:
            wx.MessageBox(str(exc),'Check core inputs',wx.OK|wx.ICON_ERROR,parent=self);return
        self.EndModal(wx.ID_OK)


class SweepPlot(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent);self.samples=[];self.threshold=0.;self.metric='flux_density_t';self.SetMinSize((460,230))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT);self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda e:(self.Refresh(),e.Skip()))

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)));dc.Clear()
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        if not self.samples:return
        width,height=self.GetClientSize();left,top,right,bottom=self.FromDIP(80),self.FromDIP(30),width-self.FromDIP(18),height-self.FromDIP(36)
        if right<=left or bottom<=top:return
        data=[s for s in self.samples if s[self.metric] is not None]
        if not data:dc.DrawText('No valid values for this quantity. A positive gap is required for force.',20,40);return
        maximum=self.samples[-1]['current_a'];factor=1e6 if self.metric=='differential_inductance_h' else 1
        peak=max((self.threshold if self.metric=='flux_density_t' else 0),max(s[self.metric]*factor for s in data),1e-20)*1.12
        x=lambda value:left+(right-left)*value/maximum
        y=lambda value:bottom-(bottom-top)*value/peak
        dc.SetPen(wx.Pen(wx.Colour('#888888')));dc.DrawLine(left,top,left,bottom);dc.DrawLine(left,bottom,right,bottom)
        unit={'flux_density_t':'T','differential_inductance_h':'µH','ideal_gap_force_n':'N'}[self.metric]
        dc.DrawText(f'{peak:.3g} {unit}',2,top);dc.DrawText('0',left-15,bottom-8);dc.DrawText(f'{maximum:g} A',right-55,bottom+8)
        if self.metric=='flux_density_t':
            dc.SetPen(wx.Pen(wx.Colour('#c66c28'),1,wx.PENSTYLE_SHORT_DASH));dc.DrawLine(left,int(y(self.threshold)),right,int(y(self.threshold)))
            dc.DrawText(f'Saturation threshold {self.threshold:g} T',left+5,3)
        else:dc.DrawText('Only valid circuit samples are plotted',left+5,3)
        dc.SetPen(wx.Pen(wx.Colour('#278abb'),2))
        if len(data)>1:dc.DrawLines([wx.Point(round(x(s['current_a'])),round(y(s[self.metric]*factor))) for s in data])


class CoreSweep(wx.Dialog):
    def __init__(self,parent,core,turns,current):
        super().__init__(parent,title='Core current sweep · magnetic circuit',size=(810,710))
        self.SetSize(self.FromDIP((810,710)))
        self.core,self.turns=core,turns;self.samples=[]
        root=wx.BoxSizer(wx.VERTICAL);row=wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self,label=f'{core.name} · {turns} effective turns · Maximum current (A)'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.maximum=wx.TextCtrl(self,value=str(max(abs(current)*2,0.1)),size=(90,-1));row.Add(self.maximum)
        run=wx.Button(self,label='Calculate');run.Bind(wx.EVT_BUTTON,self.run);row.Add(run,0,wx.LEFT,8)
        root.Add(row,0,wx.ALL,12)
        self.plot=SweepPlot(self);root.Add(self.plot,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        metric=wx.Choice(self,choices=['Flux density / saturation','Incremental inductance','Ideal gap force']);metric.SetSelection(0)
        def change_plot(event):
            self.plot.metric=['flux_density_t','differential_inductance_h','ideal_gap_force_n'][metric.GetSelection()];self.plot.Refresh()
        metric.Bind(wx.EVT_CHOICE,change_plot);root.Add(metric,0,wx.LEFT|wx.TOP,12)
        self.table=wx.ListCtrl(self,style=wx.LC_REPORT,size=(-1,180))
        for i,(label,width) in enumerate([('Current A',100),('B T',100),('Incremental L µH',145),('Ideal gap force N',145),('Validity',230)]):self.table.InsertColumn(i,label,width=self.FromDIP(width))
        root.Add(self.table,1,wx.EXPAND|wx.ALL,12)
        pulse=wx.BoxSizer(wx.HORIZONTAL)
        pulse.Add(wx.StaticText(self,label='Transformer pulse: volts / on-time µs'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.voltage=wx.TextCtrl(self,value='5',size=(65,-1));self.duration=wx.TextCtrl(self,value='5',size=(65,-1));pulse.Add(self.voltage);pulse.Add(self.duration,0,wx.LEFT,6)
        button=wx.Button(self,label='Check ΔB');button.Bind(wx.EVT_BUTTON,self.pulse);pulse.Add(button,0,wx.LEFT,8);root.Add(pulse,0,wx.LEFT|wx.RIGHT,12)
        note=wx.StaticText(self,label='1D circuit: no fringing, leakage, hysteresis or core-temperature model.\nForce assumes one uniform gap/pole face. Invalid linear saturation gives no force or L.');root.Add(note,0,wx.ALL,12)
        buttons=wx.BoxSizer(wx.HORIZONTAL);export=wx.Button(self,label='Export sweep CSV');export.Bind(wx.EVT_BUTTON,self.export);buttons.Add(export);buttons.Add(self.CreateButtonSizer(wx.CLOSE),0,wx.LEFT,8);root.Add(buttons,0,wx.ALL|wx.ALIGN_RIGHT,12)
        self.SetSizer(root);self.run(None)

    def run(self,event):
        self.samples=[];self.plot.samples=[];self.plot.Refresh();self.table.DeleteAllItems()
        try:samples=current_sweep(self.core,self.turns,float(self.maximum.GetValue()))
        except (ValueError,TypeError) as exc:wx.MessageBox(str(exc),'Sweep unavailable',wx.OK|wx.ICON_ERROR,parent=self);return
        self.samples=samples;self.plot.samples=samples;self.plot.threshold=self.core.saturation_t;self.plot.Refresh();self.table.DeleteAllItems()
        for sample in samples:
            values=[f"{sample['current_a']:.5g}",f"{sample['flux_density_t']:.5g}",
                    'Unavailable' if sample['differential_inductance_h'] is None else f"{sample['differential_inductance_h']*1e6:.5g}",
                    'Unavailable' if sample['ideal_gap_force_n'] is None else f"{sample['ideal_gap_force_n']:.5g}",
                    'Above threshold' if sample['saturation_threshold_exceeded'] else 'Within threshold']
            index=self.table.InsertItem(self.table.GetItemCount(),values[0])
            for column,value in enumerate(values[1:],1):self.table.SetItem(index,column,value)
        
    def pulse(self,event):
        try:delta=transformer_flux_swing(self.core,self.turns,float(self.voltage.GetValue()),float(self.duration.GetValue()))
        except ValueError as exc:wx.MessageBox(str(exc),'Check pulse',parent=self);return
        wx.MessageBox(f'One pulse ΔB = {delta:.6g} T\nThreshold = {self.core.saturation_t:g} T\nAdd initial/reset flux to determine peak B. This is not a reset or topology simulation.','Transformer volt-seconds',parent=self)

    def export(self,event):
        if not self.samples:return
        with wx.FileDialog(self,'Export sweep',wildcard='CSV (*.csv)|*.csv',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:
                with open(dialog.GetPath(),'w',encoding='utf-8',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(self.samples[0]));writer.writeheader();writer.writerows(self.samples)
            except OSError as exc:wx.MessageBox(str(exc),'Export failed',wx.OK|wx.ICON_ERROR,parent=self)
