"""Two-winding coaxial field extraction; independent geometry, local worker."""
import threading
import math
import wx
from .axisymmetric import AxisymmetricSpec, solve_coupled
from .axisymmetric_ui import FieldCanvas


class CoupledCanvas(FieldCanvas):
    secondary=None
    def paint(self,event):
        super().paint(event)
        if not self.result or not self.secondary:return
        dc=wx.PaintDC(self);dc.SetBrush(wx.TRANSPARENT_BRUSH);dc.SetPen(wx.Pen(wx.Colour('#ff75d0'),2))
        s=self.secondary;z=s.get('z_offset_mm',0.)
        for sign in (-1,1):
            low,high=sorted([sign*s['winding_inner_mm'],sign*s['winding_outer_mm']])
            top=self.point((low*.001,(z+s['winding_height_mm']/2)*.001));bottom=self.point((high*.001,(z-s['winding_height_mm']/2)*.001))
            dc.DrawRectangle(top.x,top.y,bottom.x-top.x,bottom.y-top.y)
    def pick(self,event):
        if not self.result:return
        self.layout_transform();p=event.GetPosition();r=abs((p.x-self.origin[0])/self.scale);z=(self.origin[1]-p.y)/self.scale
        points=self.result['vertices_m'];triangles=self.result['triangles']
        if not 0<=r<=self.rmax or abs(z)>self.zmax:return
        i=min(range(len(triangles)),key=lambda i:(sum(points[j][0] for j in triangles[i])/3-r)**2+(sum(points[j][1] for j in triangles[i])/3-z)**2)
        region=self.result['regions'][i];br=self.result['br_t'][i];bz=self.result['bz_t'][i]
        h=math.hypot(br,bz)/(4e-7*math.pi*(self.result['spec']['core_mu_r'] if region==2 else 1.))
        if self.probe:self.probe(f"Nearest cell {i} ({['air','primary','core','secondary'][region]}): Br {br*1000:.5g} mT · Bz {bz*1000:.5g} mT · |H| {h:.5g} A/m · primary 1 A, secondary open")


class CoupledDialog(wx.Dialog):
    def __init__(self,parent):
        super().__init__(parent,title='Coaxial transformer · extract inductance matrix',size=parent.FromDIP((1000,740)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.result=None;self.busy=False;self.fields={};root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Independent annular winding geometry in air or a linear core. Two unit-current excitations extract L11, L22 and M.\nThis does not infer a transformer from PCB traces or STEP. All geometry is in mm.');root.Add(note,0,wx.ALL,12)
        body=wx.BoxSizer(wx.HORIZONTAL);input_book=wx.Notebook(self);geometry=wx.Panel(input_book);advanced=wx.Panel(input_book)
        input_book.AddPage(geometry,'Windings');input_book.AddPage(advanced,'Core / mesh')
        form=wx.FlexGridSizer(cols=2,vgap=6,hgap=8);advanced_form=wx.FlexGridSizer(cols=2,vgap=6,hgap=8)
        fields=[('winding_inner_mm','Primary inner radius',8),('winding_outer_mm','Primary outer radius',10),('winding_height_mm','Primary height',30),('turns','Primary turns',100),('secondary_inner','Secondary inner radius',11),('secondary_outer','Secondary outer radius',13),('secondary_height','Secondary height',30),('secondary_z','Secondary z offset',0),('secondary_turns','Secondary turns',100),('core_outer_mm','Core radius (0 = air)',0),('core_height_mm','Core height',30),('core_mu_r','Core relative permeability',1),('radial_cells','Radial cells',32),('axial_cells','Axial cells',64),('air_extent','Air-domain multiplier',3)]
        for key,label,value in fields:
            panel,target=(advanced,advanced_form) if key.startswith('core_') or key in ('radial_cells','axial_cells','air_extent') else (geometry,form)
            if key in ('winding_inner_mm','secondary_inner'):
                heading=wx.StaticText(panel,label='Primary winding' if key=='winding_inner_mm' else 'Secondary winding');heading.SetFont(heading.GetFont().Bold());target.Add(heading);target.AddSpacer(1)
            target.Add(wx.StaticText(panel,label=label),0,wx.ALIGN_CENTER_VERTICAL);control=wx.TextCtrl(panel,value=str(value),size=self.FromDIP((95,-1)));self.fields[key]=control;target.Add(control);control.Bind(wx.EVT_TEXT,self.invalidate)
        for panel,target in ((geometry,form),(advanced,advanced_form)):
            inside=wx.BoxSizer(wx.VERTICAL);inside.Add(target,0,wx.ALL,12);panel.SetSizer(inside)
        body.Add(input_book,0,wx.EXPAND|wx.ALL,8);self.canvas=CoupledCanvas(self);body.Add(self.canvas,1,wx.EXPAND|wx.ALL,8);root.Add(body,1,wx.EXPAND)
        self.status=wx.StaticText(self,label='Review both mesh and air-domain sensitivity before trusting extracted coupling. No capacitance or loss extraction.');root.Add(self.status,0,wx.ALL,12)
        self.canvas.probe=lambda text:self.status.SetLabel(text)
        buttons=wx.BoxSizer(wx.HORIZONTAL);self.solve_button=wx.Button(self,label='Extract L matrix');self.solve_button.Bind(wx.EVT_BUTTON,self.run);buttons.Add(self.solve_button,0,wx.RIGHT,8)
        self.accept=wx.Button(self,label='Use extracted model');self.accept.Disable();self.accept.Bind(wx.EVT_BUTTON,lambda event:self.EndModal(wx.ID_OK));buttons.Add(self.accept,0,wx.RIGHT,8)
        close=wx.Button(self,label='Cancel');close.Bind(wx.EVT_BUTTON,lambda event:self.EndModal(wx.ID_CANCEL));buttons.Add(close);root.Add(buttons,0,wx.ALIGN_RIGHT|wx.ALL,12);self.SetSizer(root)
    def invalidate(self,event):
        self.result=None;self.accept.Disable();self.canvas.result=None;self.canvas.Refresh();event.Skip()
    def run(self,event):
        if self.busy:return
        try:
            values={key:float(control.GetValue()) for key,control in self.fields.items()}
            secondary={'winding_inner_mm':values.pop('secondary_inner'),'winding_outer_mm':values.pop('secondary_outer'),'winding_height_mm':values.pop('secondary_height'),'z_offset_mm':values.pop('secondary_z'),'turns':values.pop('secondary_turns')}
            spec=AxisymmetricSpec(**values)
        except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc));return
        self.busy=True;self.solve_button.Disable();self.accept.Disable()
        for control in self.fields.values():control.Disable()
        self.status.SetLabel('Solving two linear magnetostatic excitations…')
        def work():
            try:result,error=solve_coupled(spec,secondary),None
            except Exception as exc:result,error=None,str(exc)
            wx.CallAfter(self.complete,result,error)
        threading.Thread(target=work,daemon=True).start()
    def complete(self,result,error):
        if not self or self.IsBeingDeleted():return
        self.busy=False;self.solve_button.Enable()
        for control in self.fields.values():control.Enable()
        if error:self.status.SetLabel(error);return
        self.result=result;self.canvas.result=result['primary_field'];self.canvas.secondary=result['evidence']['secondary'];self.canvas.Refresh();self.accept.Enable()
        matrix=result['L_matrix_H'];self.status.SetLabel(f"L1 {matrix[0][0]*1e6:.5g} µH · L2 {matrix[1][1]*1e6:.5g} µH · M {result['mutual_H']*1e6:.5g} µH · k {result['k']:.6f}\nPrimary short-circuit leakage {result['primary_short_circuit_leakage_H']*1e6:.5g} µH. Field shown: primary 1 A, secondary open. Mesh/domain convergence not certified.")
        self.status.Wrap(self.FromDIP(940));self.Layout()
