"""Native, local meridian field view for the bounded axisymmetric FEM subset."""
import json
import math
import threading
import wx
from .axisymmetric import AxisymmetricSpec,solve,convergence,validate


class FieldCanvas(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent);self.result=None;self.mesh=False;self.metric='magnitude';self.probe=None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT);self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()));self.Bind(wx.EVT_LEFT_DOWN,self.pick)

    def layout_transform(self):
        vertices=self.result['vertices_m'];width,height=self.GetClientSize()
        self.rmax=max(p[0] for p in vertices);self.zmax=max(abs(p[1]) for p in vertices)
        plot_width=max(1,width-self.FromDIP(160))
        self.scale=min(max(1,plot_width-self.FromDIP(40))/(2*self.rmax),max(1,height-self.FromDIP(65))/(2*self.zmax))
        self.origin=(plot_width/2,height/2)

    def point(self,vertex):return wx.Point(round(self.origin[0]+vertex[0]*self.scale),round(self.origin[1]-vertex[1]*self.scale))

    def field_color(self,value,peak):
        fraction=min(1,abs(value)/peak)
        if self.metric=='magnitude':return wx.Colour(int(25+220*fraction),int(55+150*math.sqrt(fraction)),int(160-100*fraction))
        # Signed components share a neutral zero and opposite hue directions.
        endpoint=(35,100,210) if value>=0 else (210,65,40)
        return wx.Colour(*(round(245+(channel-245)*fraction) for channel in endpoint))

    def legend(self,dc,peak):
        width,height=self.GetClientSize();x=width-self.FromDIP(140);y=self.FromDIP(55)
        bar_width=self.FromDIP(18);bar_height=min(self.FromDIP(240),max(self.FromDIP(80),height-self.FromDIP(120)))
        low=0. if self.metric=='magnitude' else -peak
        for pixel in range(bar_height):
            value=peak-(peak-low)*pixel/max(1,bar_height-1)
            dc.SetPen(wx.Pen(self.field_color(value,peak)));dc.DrawLine(x,y+pixel,x+bar_width,y+pixel)
        foreground=wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        dc.SetPen(wx.Pen(foreground));dc.SetBrush(wx.TRANSPARENT_BRUSH);dc.DrawRectangle(x,y,bar_width,bar_height)
        dc.DrawText('mT',x,y-self.FromDIP(25))
        for value in (peak,peak*.5,0.) if self.metric=='magnitude' else (peak,0.,-peak):
            py=y+round((peak-value)/(peak-low)*bar_height)
            dc.DrawLine(x+bar_width,py,x+bar_width+self.FromDIP(4),py)
            dc.DrawText(f'{value*1000:.4g}',x+bar_width+self.FromDIP(8),py-dc.GetCharHeight()//2)

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)));dc.Clear()
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        if not self.result:dc.DrawText('Define an annular winding, then solve to inspect its field and mesh.',20,30);return
        self.layout_transform();result=self.result
        values=[math.hypot(a,b) if self.metric=='magnitude' else a if self.metric=='br' else b for a,b in zip(result['br_t'],result['bz_t'])]
        peak=max(max(abs(value) for value in values),1e-30)
        for side in (-1,1):
            points=[self.point((side*p[0],p[1])) for p in result['vertices_m']]
            for triangle,value in zip(result['triangles'],values):
                if self.metric=='br':value*=side
                color=self.field_color(value,peak)
                dc.SetBrush(wx.Brush(color));dc.SetPen(wx.Pen(wx.Colour('#79939f') if self.mesh else color,1))
                dc.DrawPolygon([points[i] for i in triangle])
        spec=result['spec'];dc.SetBrush(wx.TRANSPARENT_BRUSH);dc.SetPen(wx.Pen(wx.Colour('#e5e5e5'),2))
        for ri,ro,height in ((spec['winding_inner_mm'],spec['winding_outer_mm'],spec['winding_height_mm']),
                             (spec['core_inner_mm'],spec['core_outer_mm'],spec['core_height_mm'])):
            if ro<=ri:continue
            for low,high in ((ri,ro),(-ro,-ri)):
                top=self.point((low*.001,height*.0005));bottom=self.point((high*.001,-height*.0005));dc.DrawRectangle(top.x,top.y,bottom.x-top.x,bottom.y-top.y)
        dc.DrawText(f'{self.metric} · peak |B| {peak*1000:.4g} mT',10,4)
        self.legend(dc,peak)
        dc.DrawText('Mirrored axial section · solver r ≥ 0 · z ↑ · click a cell to inspect B.',10,self.GetClientSize().height-self.FromDIP(22))

    def pick(self,event):
        if not self.result:return
        self.layout_transform();p=event.GetPosition();r=abs((p.x-self.origin[0])/self.scale);z=(self.origin[1]-p.y)/self.scale
        if not 0<=r<=self.rmax or abs(z)>self.zmax:return
        points=self.result['vertices_m'];triangles=self.result['triangles']
        index=min(range(len(triangles)),key=lambda i:(sum(points[j][0] for j in triangles[i])/3-r)**2+(sum(points[j][1] for j in triangles[i])/3-z)**2)
        if self.probe:self.probe(f"Nearest cell {index}: Br {self.result['br_t'][index]*1000:.6g} mT, Bz {self.result['bz_t'][index]*1000:.6g} mT · "+['air','winding','core'][self.result['regions'][index]])


class FieldDialog(wx.Dialog):
    def __init__(self,parent):
        super().__init__(parent,title='Axisymmetric magnetic field · linear FEM',size=(950,750));self.SetSize(self.FromDIP((950,750)))
        self.result=None;self.busy=False;self.fields={}
        root=wx.BoxSizer(wx.VERTICAL);self.book=wx.Notebook(self);geometry=wx.Panel(self.book);layout=wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(geometry,label='Define a cylindrical winding in the r–z plane. This independent geometry\nis not inferred from the PCB winding or imported STEP model.'),0,wx.ALL,12)
        self.form(geometry,layout,[('winding_inner_mm','Winding inner radius (mm)'),('winding_outer_mm','Winding outer radius (mm)'),('winding_height_mm','Winding height (mm)'),('turns','Turns'),('current_a','Current (A)')])
        advanced=wx.CollapsiblePane(geometry,label='Linear core and field mesh');pane=advanced.GetPane();inside=wx.BoxSizer(wx.VERTICAL)
        self.form(pane,inside,[('core_inner_mm','Core inner radius (mm)'),('core_outer_mm','Core outer radius (mm; 0 = air)'),('core_height_mm','Core height (mm)'),('core_mu_r','Linear core relative permeability'),('radial_cells','Radial mesh cells'),('axial_cells','Axial mesh cells'),('air_extent','Air domain multiplier')])
        pane.SetSizer(inside);advanced.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(geometry.Layout(),self.Layout()));layout.Add(advanced,0,wx.EXPAND|wx.ALL,12)
        layout.Add(wx.StaticText(geometry,label='Aφ = 0 on axis and outer air boundary. Review mesh and air-domain\nchanges before trusting values. No nonlinear saturation, eddy currents,\nhysteresis, arbitrary STEP field solve or Maxwell-stress force.'),0,wx.ALL,12)
        geometry.SetSizer(layout);self.book.AddPage(geometry,'1 · Geometry')
        field=wx.Panel(self.book);field_layout=wx.BoxSizer(wx.VERTICAL);toolbar=wx.BoxSizer(wx.HORIZONTAL)
        metric=wx.Choice(field,choices=['|B| magnitude','Br radial','Bz axial']);metric.SetSelection(0);toolbar.Add(metric,0,wx.RIGHT,12)
        mesh=wx.CheckBox(field,label='Show mesh');self.mesh_control=mesh;toolbar.Add(mesh);field_layout.Add(toolbar,0,wx.ALL,10)
        self.canvas=FieldCanvas(field);field_layout.Add(self.canvas,1,wx.EXPAND|wx.ALL,10)
        self.summary=wx.StaticText(field,label='No field result');self.canvas.probe=self.summary.SetLabel;field_layout.Add(self.summary,0,wx.EXPAND|wx.ALL,10)
        metric.Bind(wx.EVT_CHOICE,lambda event:self.set_plot(['magnitude','br','bz'][metric.GetSelection()],mesh.GetValue()))
        mesh.Bind(wx.EVT_CHECKBOX,lambda event:self.set_plot(['magnitude','br','bz'][metric.GetSelection()],mesh.GetValue()))
        field.SetSizer(field_layout);self.book.AddPage(field,'2 · Field and mesh');root.Add(self.book,1,wx.EXPAND|wx.ALL,10)
        self.status=wx.StaticText(self,label='Geometry is independent of the PCB. No board write.');root.Add(self.status,0,wx.LEFT|wx.RIGHT,12)
        actions=wx.BoxSizer(wx.HORIZONTAL);self.run_button=wx.Button(self,label='Solve field');self.run_button.Bind(wx.EVT_BUTTON,lambda event:self.run(False));actions.Add(self.run_button)
        self.review_button=wx.Button(self,label='Review convergence');self.review_button.Bind(wx.EVT_BUTTON,lambda event:self.run(True));actions.Add(self.review_button,0,wx.LEFT,8)
        export=wx.Button(self,label='Export result JSON');export.Bind(wx.EVT_BUTTON,self.export);actions.Add(export,0,wx.LEFT,8);actions.Add(self.CreateButtonSizer(wx.CLOSE),0,wx.LEFT,8);root.Add(actions,0,wx.ALL|wx.ALIGN_RIGHT,12);self.SetSizer(root)

    def form(self,parent,sizer,items):
        grid=wx.FlexGridSizer(cols=2,vgap=6,hgap=15);grid.AddGrowableCol(1);defaults=AxisymmetricSpec()
        for name,label in items:
            grid.Add(wx.StaticText(parent,label=label),0,wx.ALIGN_CENTER_VERTICAL);control=wx.TextCtrl(parent,value=str(getattr(defaults,name)));self.fields[name]=control;grid.Add(control,0,wx.EXPAND)
            control.Bind(wx.EVT_TEXT,self.invalidate)
        sizer.Add(grid,0,wx.EXPAND|wx.ALL,12)

    def invalidate(self,event):
        if hasattr(self,'canvas'):self.result=None;self.canvas.result=None;self.canvas.Refresh();self.status.SetLabel('Inputs changed; solve again before exporting.')
        event.Skip()

    def set_plot(self,metric,mesh):self.canvas.metric=metric;self.canvas.mesh=mesh;self.canvas.Refresh()

    def run(self,review):
        if self.busy:return
        try:
            values={key:float(control.GetValue()) for key,control in self.fields.items()}
            spec=AxisymmetricSpec(**values);validate(spec)
        except ValueError as exc:wx.MessageBox(str(exc),'Check geometry',parent=self);return
        self.busy=True;self.result=None;self.canvas.result=None;self.canvas.Refresh();self.run_button.Disable();self.review_button.Disable()
        for control in self.fields.values():control.Disable()
        self.status.SetLabel('Solving three mesh/domain cases…' if review else 'Solving linear axisymmetric field…')
        def work():
            try:result,error=(convergence(spec) if review else {'base':solve(spec),'evidence':{}}),None
            except Exception as exc:result,error=None,str(exc)
            wx.CallAfter(self.complete,result,error)
        threading.Thread(target=work,daemon=True).start()

    def complete(self,result,error):
        if not self or self.IsBeingDeleted():return
        self.busy=False;self.run_button.Enable();self.review_button.Enable()
        for control in self.fields.values():control.Enable()
        if error:self.status.SetLabel('Field solve failed: '+error);return
        self.result=result;self.canvas.result=result['base'];self.canvas.Refresh();self.book.SetSelection(1);r=result['base']
        self.summary.SetLabel(f"L {r['inductance_h']*1e6:.6g} µH · energy {r['energy_j']*1000:.6g} mJ · axis center B {r['axis_center_b_t']*1000:.6g} mT · {r['triangle_count']} triangles")
        if r['core_peak_b_t'] is not None:self.summary.SetLabel(self.summary.GetLabel()+f"\nPeak core B {r['core_peak_b_t']:.5g} T: compare with actual material saturation; this field solve is linear.")
        ev=result['evidence']
        self.status.SetLabel('Mesh ΔL %.2f%% · larger air-domain ΔL %.2f%% · review both; no automatic accuracy certification.'%(100*ev['mesh_l_change'],100*ev['air_l_change']) if ev else 'Single solve only. Review convergence before relying on field or inductance values.')
        if ev:self.status.SetLabel(self.status.GetLabel()+'\nMesh ΔBaxis %.2f%% · air-domain ΔBaxis %.2f%%'%(100*ev['mesh_axis_b_change'],100*ev['air_axis_b_change'])+(' · refined analytic B error %.2f%%'%(100*ev['analytic_axis_b_relative_error']) if 'analytic_axis_b_relative_error' in ev else ''))
        self.Layout()

    def export(self,event):
        if not self.result:return
        with wx.FileDialog(self,'Export field result',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:
                with open(dialog.GetPath(),'w',encoding='utf-8') as stream:json.dump(self.result,stream,allow_nan=False)
            except OSError as exc:wx.MessageBox(str(exc),'Export failed',parent=self)
