"""Explicit-dielectric capacitance review: bounded geometry, field and mapping."""
import math
import threading
from dataclasses import asdict
import wx
from .equivalent_ui import ModelPlot
from .capacitance import solve_interwinding,estimate_pcb_sidewall


class CapacitanceCanvas(ModelPlot):
    field=None
    coaxial=None
    def paint(self,event):
        if self.field is None and self.coaxial is None:return super().paint(event)
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)));dc.Clear();dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        w,h=self.GetClientSize();left,top=self.FromDIP(35),self.FromDIP(40);right,bottom=w-self.FromDIP(70),h-self.FromDIP(35)
        if right<=left or bottom<=top:return
        if self.field:
            points=self.field['vertices_m'];rmax=max(p[0] for p in points);zmax=max(abs(p[1]) for p in points)
            point=lambda p:wx.Point(round(left+p[0]/rmax*(right-left)),round(top+(zmax-p[1])/(2*zmax)*(bottom-top)))
            for tri in self.field['triangles']:
                value=sum(self.field['potential_V'][i] for i in tri)/3;f=max(0,min(1,value));color=wx.Colour(round(25+220*f),round(55+160*f),round(170-120*f))
                dc.SetPen(wx.Pen(color));dc.SetBrush(wx.Brush(color));dc.DrawPolygon([point(points[i]) for i in tri])
            dc.DrawText('Potential · primary 1 V, secondary / enclosure 0 V',left,4)
            for pixel in range(max(1,bottom-top)):
                f=1-pixel/max(1,bottom-top-1);dc.SetPen(wx.Pen(wx.Colour(round(25+220*f),round(55+160*f),round(170-120*f))));dc.DrawLine(right+10,top+pixel,right+25,top+pixel)
            dc.DrawText('1 V',right+30,top);dc.DrawText('0 V',right+30,bottom-15)
            if self.coaxial:
                dc.SetTextForeground(wx.Colour('#222222'))
                for winding,label in zip(self.coaxial[:2],('P\n1 V','S\n0 V')):
                    at=point(((winding['winding_inner_mm']+winding['winding_outer_mm'])*.0005,winding.get('z_offset_mm',0)*.001));dc.DrawText(label,at.x-self.FromDIP(8),at.y-self.FromDIP(15))
        else:
            primary,secondary,rmax,zmax=self.coaxial
            point=lambda r,z:wx.Point(round(left+r/rmax*(right-left)),round(top+(zmax-z)/(2*zmax)*(bottom-top)))
            dc.SetPen(wx.Pen(wx.Colour('#657786'),2));dc.SetBrush(wx.TRANSPARENT_BRUSH);dc.DrawRectangle(left,top,right-left,bottom-top)
            for winding,color in ((primary,'#b97825'),(secondary,'#258bb1')):
                z=winding.get('z_offset_mm',0);a=point(winding['winding_inner_mm'],z+winding['winding_height_mm']/2);b=point(winding['winding_outer_mm'],z-winding['winding_height_mm']/2)
                dc.SetBrush(wx.Brush(wx.Colour(color)));dc.DrawRectangle(a.x,a.y,b.x-a.x,b.y-a.y)
            dc.DrawText('Independent coaxial geometry · grounded outer reference',left,4)
        dc.DrawText('r →   z ↑   Meridian section; homogeneous dielectric',left,bottom+8)


class CapacitanceDialog(wx.Dialog):
    def __init__(self,parent,result,field_model=None):
        super().__init__(parent,title='Capacitance · geometry, dielectric and terminal model',size=parent.FromDIP((1080,770)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.winding_result=result;self.result=None;self.selection={};self.busy=False;self.fields={}
        root=wx.BoxSizer(wx.VERTICAL);root.Add(wx.StaticText(self,label='Compute only the stated geometry model. Dielectric is an explicit input; review voltage assumptions before using capacitance.'),0,wx.ALL,12)
        body=wx.BoxSizer(wx.HORIZONTAL);left=wx.BoxSizer(wx.VERTICAL);dielectric=wx.BoxSizer(wx.HORIZONTAL);dielectric.Add(wx.StaticText(self,label='Relative permittivity εr'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8);self.er=wx.TextCtrl(self,value='',size=self.FromDIP((90,-1)));dielectric.Add(self.er);left.Add(dielectric,0,wx.ALL,8)
        self.book=wx.Notebook(self);pcb=wx.Panel(self.book);pcb_box=wx.BoxSizer(wx.VERTICAL);self.target=wx.Choice(pcb,choices=['Primary','Secondary']);self.target.SetSelection(0);pcb_box.Add(self.target,0,wx.ALL,8)
        note=wx.StaticText(pcb,label='Uses the actual generated single-layer rectangular winding.\nAdjacent parallel sidewalls only; not total capacitance.\n\nVoltage varies linearly along conductor length.\nFringing, substrate interfaces, broad faces, other\nlayers and nonadjacent turns are excluded.\n\nMultilayer / curved winding requests are rejected.');note.Wrap(self.FromDIP(310));pcb_box.Add(note,0,wx.ALL,8);pcb.SetSizer(pcb_box);self.book.AddPage(pcb,'PCB sidewalls')
        coax=wx.Panel(self.book);grid=wx.FlexGridSizer(cols=2,vgap=5,hgap=8)
        primary={'winding_inner_mm':8,'winding_outer_mm':10,'winding_height_mm':30,'z_offset_mm':0};secondary={'winding_inner_mm':11,'winding_outer_mm':13,'winding_height_mm':30,'z_offset_mm':0}
        if field_model:
            primary.update({k:v for k,v in field_model['primary_field']['spec'].items() if k in primary});secondary.update({k:v for k,v in field_model['evidence']['secondary'].items() if k in secondary})
        for prefix,winding in (('primary',primary),('secondary',secondary)):
            for key,label in [('winding_inner_mm','inner r'),('winding_outer_mm','outer r'),('winding_height_mm','height'),('z_offset_mm','z offset')]:
                grid.Add(wx.StaticText(coax,label=prefix.title()+' '+label+' mm'));control=wx.TextCtrl(coax,value=str(winding[key]),size=self.FromDIP((80,-1)));self.fields[prefix+'_'+key]=control;grid.Add(control)
        for key,label,value in [('domain_radius_mm','Grounded enclosure radius mm',40),('domain_half_height_mm','Enclosure half-height mm',60)]:
            grid.Add(wx.StaticText(coax,label=label));control=wx.TextCtrl(coax,value=str(value),size=self.FromDIP((80,-1)));self.fields[key]=control;grid.Add(control)
        grid.Add(wx.StaticText(coax,label='Base mesh'));self.mesh=wx.Choice(coax,choices=['Coarse 20 × 40','Medium 40 × 80','Fine 80 × 160']);self.mesh.SetSelection(1);grid.Add(self.mesh);self.mesh.Bind(wx.EVT_CHOICE,self.invalidate)
        coax_box=wx.BoxSizer(wx.VERTICAL);coax_box.Add(grid,0,wx.ALL,8);caption=wx.StaticText(coax,label='Independent coaxial geometry; not inferred from PCB traces.\nHomogeneous dielectric and grounded enclosure.\nCompare mesh sizes and enclosure dimensions.');caption.Wrap(self.FromDIP(330));coax_box.Add(caption,0,wx.ALL,8);coax.SetSizer(coax_box);self.book.AddPage(coax,'Coaxial FEM');left.Add(self.book,1,wx.EXPAND|wx.ALL,8)
        self.mapping=wx.CheckBox(self,label='Accept the displayed voltage / terminal assumptions');left.Add(self.mapping,0,wx.ALL,8)
        self.compute=wx.Button(self,label='Compute capacitance');self.compute.Bind(wx.EVT_BUTTON,self.run);left.Add(self.compute,0,wx.ALL,8)
        self.use=wx.Button(self,label='Use reviewed capacitance');self.use.Disable();self.use.Bind(wx.EVT_BUTTON,self.accept);left.Add(self.use,0,wx.ALL,8)
        body.Add(left,0,wx.EXPAND);right=wx.BoxSizer(wx.VERTICAL);self.canvas=CapacitanceCanvas(self,result);right.Add(self.canvas,1,wx.EXPAND|wx.ALL,8);self.details=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=self.FromDIP((-1,190)));right.Add(self.details,0,wx.EXPAND|wx.ALL,8);body.Add(right,1,wx.EXPAND);root.Add(body,1,wx.EXPAND)
        close=wx.Button(self,label='Cancel');close.Bind(wx.EVT_BUTTON,lambda event:self.EndModal(wx.ID_CANCEL));root.Add(close,0,wx.ALIGN_RIGHT|wx.ALL,8);self.SetSizer(root)
        for control in [self.er,*self.fields.values()]:control.Bind(wx.EVT_TEXT,self.invalidate)
        self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,self.invalidate);self.target.Bind(wx.EVT_CHOICE,self.invalidate);self.mapping.Bind(wx.EVT_CHECKBOX,lambda event:self.use.Enable(bool(self.result) and self.mapping.IsChecked()))
    def invalidate(self,event):
        self.result=None;self.use.Disable();self.mapping.SetValue(False);self.canvas.field=None
        try:
            p,s,r,z=self.geometry();self.canvas.coaxial=(p,s,r,z) if self.book.GetSelection()==1 else None
        except ValueError:self.canvas.coaxial=None
        self.canvas.Refresh();event.Skip()
    def geometry(self):
        values={key:float(control.GetValue()) for key,control in self.fields.items()}
        if any(not math.isfinite(value) for value in values.values()) or values['domain_radius_mm']<=0 or values['domain_half_height_mm']<=0:raise ValueError('Geometry needs finite dimensions and a positive enclosure.')
        winding=lambda prefix:{key:values[prefix+'_'+key] for key in ('winding_inner_mm','winding_outer_mm','winding_height_mm','z_offset_mm')}
        return winding('primary'),winding('secondary'),values['domain_radius_mm'],values['domain_half_height_mm']
    def run(self,event):
        if self.busy:return
        try:er=float(self.er.GetValue());geometry=self.geometry() if self.book.GetSelection()==1 else None
        except ValueError:self.details.SetValue('Enter a finite relative permittivity and valid geometry dimensions.');return
        self.busy=True;self.compute.Disable();self.use.Disable();self.result=None;self.mapping.SetValue(False);self.details.SetValue('Computing the specified geometry…')
        target=self.target.GetStringSelection();mode=self.book.GetSelection();cells=[20,40,80][self.mesh.GetSelection()]
        for control in [self.er,self.book,self.target,self.mesh,*self.fields.values()]:control.Disable()
        def work():
            try:
                result=solve_interwinding(geometry[0],geometry[1],epsilon_r=er,domain_radius_mm=geometry[2],domain_half_height_mm=geometry[3],radial_cells=cells,axial_cells=2*cells) if mode else estimate_pcb_sidewall(self.winding_result,epsilon_r=er,winding=target)
                error=None
            except Exception as exc:result,error=None,str(exc)
            wx.CallAfter(self.complete,result,error,mode,target)
        threading.Thread(target=work,daemon=True).start()
    def complete(self,result,error,mode,target):
        if not self or self.IsBeingDeleted():return
        self.busy=False;self.compute.Enable()
        for control in [self.er,self.book,self.target,self.mesh,*self.fields.values()]:control.Enable()
        if error:self.details.SetValue(error);return
        self.result=result;self.mode=mode;self.winding=target
        if mode:
            self.canvas.field=result['field'];self.details.SetValue(f"Mutual capacitance {-result['C_matrix_F'][0][1]*1e12:.6g} pF\nPrimary to environment {result['primary_environment_F']*1e12:.6g} pF\nSecondary to environment {result['secondary_environment_F']*1e12:.6g} pF\n\nAccept mapping: each whole winding is equipotential at dotted terminal P/S; grounded enclosure is tied to primary return N. Export keeps C(P,S), C(P,N), C(S,N). This is a common-mode surrogate, not distributed transformer turn-voltage capacitance. Mesh and enclosure sensitivity are not certified.")
        else:self.details.SetValue(f"{target} sidewall contribution {result['terminal_capacitance_F']*1e12:.6g} pF\n{len(result['pairs'])} adjacent segment pairs from actual generated geometry.\n\nAccept linear voltage versus conductor arc length; equivalent C = Σ Cij (Δα)². This is partial sidewall capacitance, not full winding capacitance or validated self resonance. Do not combine blindly with the equipotential coaxial model.")
        self.canvas.Refresh()
    def accept(self,event):
        if not self.result or not self.mapping.IsChecked():return
        result=self.result
        if self.mode:
            evidence={key:value for key,value in result.items() if key!='field'}
            evidence.update(capacitance_F=result['interwinding_F'],model='Axisymmetric electrostatic FEM; equipotential common-mode surrogate',maxwell_mapping=True)
            evidence['_field']=result['field']
            self.selection={'interwinding_C_F':evidence}
        else:
            evidence=dict(result,capacitance_F=result['terminal_capacitance_F'],model='Actual PCB adjacent-sidewall partial contribution; linear arc-length voltage')
            evidence['winding_spec']=asdict(self.winding_result.spec)
            evidence['source_segments']=[asdict(segment) for segment in self.winding_result.segments if segment.winding==self.winding]
            self.selection={self.winding.lower()+'_C_F':evidence}
        self.EndModal(wx.ID_OK)
