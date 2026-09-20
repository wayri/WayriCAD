"""Native equivalent-model review, explicit missing inputs and local exports."""
import json
import hashlib
import math
from pathlib import Path
import wx
from .equivalent import equivalent, export_bundle, spice


class ModelPlot(wx.Panel):
    def __init__(self,parent,result):
        super().__init__(parent);self.result=result;self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)));dc.Clear()
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        dc.DrawText('Generated winding geometry · reduced model, not a solved field',self.FromDIP(16),self.FromDIP(12))
        segments=self.result.segments
        if not segments:return
        xs=[x for s in segments for x in (s.x1_mm,s.x2_mm)];ys=[y for s in segments for y in (s.y1_mm,s.y2_mm)]
        lowx,lowy=min(xs),min(ys);span=max(max(xs)-lowx,max(ys)-lowy,1e-6)
        width,height=self.GetClientSize();scale=max(1,min(width-80,height-120))/span
        for segment in segments:
            dc.SetPen(wx.Pen(wx.Colour('#b66528' if segment.winding=='Primary' else '#278abb'),max(1,round(segment.width_mm*scale))))
            dc.DrawLine(round(40+(segment.x1_mm-lowx)*scale),round(65+(segment.y1_mm-lowy)*scale),round(40+(segment.x2_mm-lowx)*scale),round(65+(segment.y2_mm-lowy)*scale))


class EquivalentDialog(wx.Dialog):
    def __init__(self,parent,result,board_path):
        super().__init__(parent,title='Magnetic equivalent · review and export',size=parent.FromDIP((1000,730)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.result=result;self.board_path=board_path;self.model=None;self.field_model=None;self.simulation=None;self.capacitance_evidence={};self.capacitance_fields={}
        source=Path(board_path)
        self.source_hash=hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
        root=wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self,label='Review the winding model, supply known parasitics, then export a project-local report and SPICE subcircuit.'),0,wx.ALL,12)
        body=wx.BoxSizer(wx.HORIZONTAL);inputs=wx.BoxSizer(wx.VERTICAL)
        self.fields={}
        form=wx.FlexGridSizer(cols=2,vgap=8,hgap=8)
        labels=[('primary_resistance_ohm','Primary Rdc override (ohm)',''),('secondary_resistance_ohm','Secondary Rdc (ohm)',''),('coupling','Supplied coupling k',str(result.spec.coupling)),('primary_capacitance_f','Primary capacitance (pF)',''),('secondary_capacitance_f','Secondary capacitance (pF)',''),('interwinding_capacitance_f','Interwinding C (pF)','')]
        for key,label,value in labels:
            form.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL);control=wx.TextCtrl(self,value=value,size=self.FromDIP((95,-1)));self.fields[key]=control;form.Add(control)
        inputs.Add(form,0,wx.ALL,8)
        note=wx.StaticText(self,label='Blank capacitances remain unknown and are omitted. k is an assumption unless extracted with the coaxial field tool.');note.Wrap(self.FromDIP(300));inputs.Add(note,0,wx.ALL,8)
        self.actuator=wx.CheckBox(self,label='Moving-coil equivalent (constant Bl)');inputs.Add(self.actuator,0,wx.ALL,8)
        self.motion=wx.Choice(self,choices=['Linear actuator','DC motor (explicit parameters)']);self.motion.SetSelection(0);inputs.Add(self.motion,0,wx.ALL,8);self.motion.Bind(wx.EVT_CHOICE,self.motion_changed)
        mechanical=wx.FlexGridSizer(cols=2,vgap=6,hgap=8);self.mechanics={};self.mechanic_labels=[]
        for key,label,value in [('Bl_N_per_A','Bl (N/A)','1'),('mass_kg','Mass (kg)','0.01'),('damping_Ns_per_m','Damping (N s/m)','0.1'),('spring_N_per_m','Spring (N/m)','10')]:
            caption=wx.StaticText(self,label=label);self.mechanic_labels.append(caption);mechanical.Add(caption);control=wx.TextCtrl(self,value=value,size=self.FromDIP((95,-1)));self.mechanics[key]=control;mechanical.Add(control);control.Disable()
        self.actuator.Bind(wx.EVT_CHECKBOX,lambda event:[c.Enable(self.actuator.IsChecked()) for c in self.mechanics.values()]);inputs.Add(mechanical,0,wx.ALL,8)
        for control in self.mechanic_labels+list(self.mechanics.values()):control.Hide()
        update=wx.Button(self,label='Review model');update.Bind(wx.EVT_BUTTON,self.review);inputs.Add(update,0,wx.ALL,8)
        field=wx.Button(self,label='Extract coaxial coupling…');field.Bind(wx.EVT_BUTTON,self.extract_coupling);inputs.Add(field,0,wx.ALL,8)
        cap=wx.Button(self,label='Compute capacitance…');cap.Bind(wx.EVT_BUTTON,self.compute_capacitance);inputs.Add(cap,0,wx.ALL,8)
        self.export=wx.Button(self,label='Export report + SPICE');self.export.Bind(wx.EVT_BUTTON,self.export_model);inputs.Add(self.export,0,wx.ALL,8)
        self.status=wx.StaticText(self,label='');self.status.Wrap(self.FromDIP(300));inputs.Add(self.status,0,wx.ALL,8)
        body.Add(inputs,0,wx.EXPAND|wx.RIGHT,12)
        book=wx.Notebook(self);self.book=book;self.details=wx.TextCtrl(book,style=wx.TE_MULTILINE|wx.TE_READONLY);book.AddPage(self.details,'Model and limits');book.AddPage(ModelPlot(book,result),'Winding geometry');self.netlist=wx.TextCtrl(book,style=wx.TE_MULTILINE|wx.TE_READONLY);book.AddPage(self.netlist,'SPICE')
        from .simulation_ui import SimulationPanel
        self.simulation_panel=SimulationPanel(book,self);book.AddPage(self.simulation_panel,'Run simulation')
        body.Add(book,1,wx.EXPAND);root.Add(body,1,wx.EXPAND|wx.ALL,12);root.Add(self.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,8);self.SetSizer(root)
        self.Bind(wx.EVT_BUTTON,lambda event:self.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        for control in list(self.fields.values())+list(self.mechanics.values()):control.Bind(wx.EVT_TEXT,self.invalidate)
        self.actuator.Bind(wx.EVT_CHECKBOX,self.invalidate)
        self.review()

    def invalidate(self,event):
        for key,control in self.fields.items():
            if event.GetEventObject() is control:
                name=key.replace('_capacitance_f','_C_F');self.capacitance_evidence.pop(name,None);self.capacitance_fields.pop(name,None)
        self.simulation_panel.invalidate()
        if event.GetEventObject() is self.actuator:
            for control in self.mechanic_labels+list(self.mechanics.values()):control.Show(self.actuator.IsChecked());control.Enable(self.actuator.IsChecked())
            self.Layout()
        self.model=None;self.export.Disable();self.status.SetLabel('Inputs changed. Review the model before export.');event.Skip()

    def motion_changed(self,event):
        labels=['Kt = Ke (N m/A)','Rotor inertia (kg m²)','Damping (N m s/rad)','Spring (N m/rad)'] if self.motion.GetSelection() else ['Bl (N/A)','Mass (kg)','Damping (N s/m)','Spring (N/m)']
        for control,label in zip(self.mechanic_labels,labels):control.SetLabel(label)
        self.actuator.SetLabel('Enable mechanical equivalent');self.Layout();self.invalidate(event)

    def review(self,event=None):
        self.simulation_panel.invalidate()
        try:
            values={key:(None if not control.GetValue().strip() else float(control.GetValue())) for key,control in self.fields.items()}
            for key in ('primary_capacitance_f','secondary_capacitance_f','interwinding_capacitance_f'):
                if values[key] is not None:values[key]*=1e-12
            actuator={key:float(c.GetValue()) for key,c in self.mechanics.items()} if self.actuator.IsChecked() else None
            if actuator:actuator['motion_type']='rotary' if self.motion.GetSelection() else 'linear'
            self.model=equivalent(self.result,**values,actuator=actuator,field_model=self.field_model,capacitance_evidence=self.capacitance_evidence)
            if self.field_model:
                self.fields['coupling'].ChangeValue(f"{self.model['k']:.6g}");self.fields['coupling'].Disable();self.fields['coupling'].SetToolTip('Extracted from FEM inductance matrix; cannot be overridden here.')
            m=self.model
            lines=[m['model'],'',f"Primary: {m['primary_L_H']*1e6:.6g} µH · Rdc {m['primary_Rdc_ohm']:.6g} Ω",f"Bias: {m['bias_current_A']:g} A"]
            if 'secondary_L_H' in m:
                lines += [f"Secondary: {m['secondary_L_H']*1e6:.6g} µH · Rdc {m['secondary_Rdc_ohm'] if m['secondary_Rdc_ohm'] is not None else 'unknown'} Ω",f"Mutual: {m['mutual_H']*1e6:.6g} µH · k {m['k']:.6g}",f"Coupling source: {m['coupling_origin']}",f"Short-circuit leakage: primary {m['primary_short_circuit_leakage_H']*1e6:.6g} µH; secondary {m['secondary_short_circuit_leakage_H']*1e6:.6g} µH"]
            if m['core']:
                c=m['core'];lines+=['',f"Core B {c['B_T']:.6g} T · H {c['H_A_per_m']:.6g} A/m",f"Mean path {c['mean_path_m']*1000:g} mm · gap {c['gap_m']*1000:g} mm",f"Secant reluctance {c['secant_total_reluctance_A_per_Wb']:.6g} A/Wb",f"Differential reluctance {c['differential_total_reluctance_A_per_Wb']:.6g} A/Wb"]
            if m.get('field_summary'):
                f=m['field_summary'];lines+=['','Solved field: '+f['excitation'],f"Peak B {f.get('peak_b_t',0)*1000:.6g} mT · peak H {f.get('peak_H_A_per_m',0):.6g} A/m"]
                lines += [f"Core peak B {f['core_peak_b_t']:.6g} T · H {f['core_peak_H_A_per_m']:.6g} A/m"] if f.get('core_peak_b_t') is not None else ['No magnetic core in this field model.']
            lines+=['','Known capacitances:']+[f"{label}: {'unknown' if m[key] is None else format(m[key]*1e12,'.6g')+' pF'}" for key,label in (('primary_C_F','Primary'),('secondary_C_F','Secondary'),('interwinding_C_F','Interwinding'))]
            for key,evidence in m.get('capacitance_evidence',{}).items():lines += [key+' source: '+evidence.get('model','geometry computation')]
            lines+=['','Assumptions and missing data:']+['• '+item for item in m['assumptions']+m['missing']]
            self.details.SetValue('\n'.join(lines))
            try:self.netlist.SetValue(spice(self.model));self.export.Enable();self.status.SetLabel('Reviewed. Reports default to project/reports/wayricad-magnetics.')
            except ValueError as exc:self.netlist.SetValue(str(exc));self.export.Disable();self.status.SetLabel(str(exc))
        except (ValueError,KeyError,TypeError) as exc:self.model=None;self.export.Disable();self.status.SetLabel(str(exc))
        self.simulation_panel.configure()
        self.status.Wrap(self.FromDIP(300));self.Layout()

    def export_model(self,event):
        if not self.model:return
        try:
            if not self.source_hash or hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()!=self.source_hash:
                raise ValueError('Saved board changed or is unavailable. Reopen model review to refresh project context.')
            files=export_bundle(self.model,self.board_path,field_model=self.field_model,simulation=self.simulation,capacitance_fields=self.capacitance_fields)
            self.status.SetLabel('Saved HTML, JSON and SPICE:\n'+str(Path(files['html']).parent));self.status.SetToolTip(files['html'])
        except (OSError,ValueError) as exc:self.status.SetLabel(str(exc))
        self.status.Wrap(self.FromDIP(300));self.Layout()

    def extract_coupling(self,event):
        from .coupled_ui import CoupledDialog
        with CoupledDialog(self) as dialog:
            if dialog.ShowModal()==wx.ID_OK:
                self.field_model=dialog.result
                from .coupled_ui import CoupledCanvas
                canvas=CoupledCanvas(self.book);canvas.secondary=dialog.result['evidence']['secondary'];canvas.probe=lambda text:self.status.SetLabel(text);canvas.result=dialog.result['primary_field'];self.book.AddPage(canvas,'Extracted field',select=True)
                self.review()

    def compute_capacitance(self,event):
        from .capacitance_ui import CapacitanceDialog
        with CapacitanceDialog(self,self.result,self.field_model) as dialog:
            if dialog.ShowModal()==wx.ID_OK:
                for key,evidence in dialog.selection.items():
                    field_result=evidence.pop('_field',None)
                    if field_result:self.capacitance_fields[key]=field_result
                    field=key.replace('_C_F','_capacitance_f')
                    self.fields[field].ChangeValue(f"{evidence['capacitance_F']*1e12:.12g}")
                    self.capacitance_evidence[key]=evidence
                self.review()



