from __future__ import annotations

import csv
import json
import math
import os
import webbrowser
from dataclasses import asdict
from pathlib import Path

import pcbnew
import wx

from .analysis import CORE_CATALOG, CoilSpec, MagneticsEngine, MagneticResult, MotionSpec, load_core_catalog, save_core_catalog
from .guided_ui import add_workflow


VERSION="0.2.0";LAYER_COLORS=("#c43c35","#2b8cbe","#3a9d5d","#9b59b6","#d68b28","#455a73")
def point(x,y):return pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))
def copper_layer(index,count):
    if index<=0:return int(pcbnew.F_Cu)
    if index>=count-1:return int(pcbnew.B_Cu)
    return index


class MagneticPreview(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent,style=wx.BORDER_SIMPLE);self.SetMinSize((-1,330));self.SetBackgroundStyle(wx.BG_STYLE_PAINT);self.result=None;self.zoom=1.0;self.phase=0.0;self.animate=False;self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_MOUSEWHEEL,self.wheel);self.timer=wx.Timer(self);self.Bind(wx.EVT_TIMER,self.tick,self.timer)
    def show_result(self,result):self.result=result;self.Refresh()
    def wheel(self,e):self.zoom=max(.5,min(5,self.zoom*(1.12 if e.GetWheelRotation()>0 else .89)));self.Refresh()
    def set_animation(self,enabled):self.animate=enabled;self.timer.Start(45) if enabled else self.timer.Stop();self.Refresh()
    def tick(self,_e):self.phase=(self.phase+.12)%(2*math.pi);self.Refresh()
    def paint(self,_e):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush("#f7f9fb"));dc.Clear();w,h=self.GetClientSize()
        if not self.result:dc.SetTextForeground("#52616b");dc.DrawLabel("Analyze a winding to preview copper, vias, field contours, and actuator motion.",wx.Rect(10,10,w-20,h-20),wx.ALIGN_CENTER);return
        spec=self.result.spec;margin=35;scale=min((w-2*margin)/spec.outer_width_mm,(h-2*margin)/spec.outer_height_mm)*self.zoom;ox=(w-spec.outer_width_mm*scale)/2;oy=(h-spec.outer_height_mm*scale)/2;project=lambda x,y:(int(ox+x*scale),int(oy+(spec.outer_height_mm-y)*scale))
        cx,cy=project(spec.outer_width_mm/2,spec.outer_height_mm/2)
        for ring in range(5,0,-1):
            strength=max(0.08,min(1.0,self.result.field_center_mt/100));color=wx.Colour(65,int(120+80*strength),int(190+40*(1-strength)));dc.SetPen(wx.Pen(color,1));radius=int(min(spec.outer_width_mm,spec.outer_height_mm)*scale*(.08+ring*.10));dc.DrawEllipse(cx-radius,cy-radius,2*radius,2*radius)
        for segment in self.result.segments:dc.SetPen(wx.Pen(LAYER_COLORS[segment.layer%len(LAYER_COLORS)],max(2,int(segment.width_mm*scale))));dc.DrawLine(*project(segment.x1_mm,segment.y1_mm),*project(segment.x2_mm,segment.y2_mm))
        for via in self.result.vias:dc.SetBrush(wx.Brush("#f6c453"));dc.SetPen(wx.Pen("#674d00",2));dc.DrawCircle(*project(via.x_mm,via.y_mm),5)
        if self.animate:
            if self.result.dynamics and self.result.dynamics.samples:
                sample=self.result.dynamics.samples[int(self.phase/(2*math.pi)*len(self.result.dynamics.samples))%len(self.result.dynamics.samples)]
                normalized=sample.displacement_m/max(self.result.dynamics.peak_displacement_m,1e-15)
                displacement=normalized*min(h*.16,70)
            else:displacement=math.sin(self.phase)*self.result.travel_mm*scale
            dc.SetBrush(wx.Brush("#758493"));dc.SetPen(wx.Pen("#263744",2));dc.DrawRoundedRectangle(int(cx-26),int(cy-12-displacement),52,24,5);dc.SetTextForeground("#ffffff");dc.DrawText("Mover",int(cx-20),int(cy-8-displacement))
        dc.SetTextForeground("#263744");dc.DrawText(f"{self.result.inductance_uh:.2f} uH | {self.result.resistance_ac_ohm:.3f} ohm AC | Q {self.result.quality_factor:.1f} | {self.result.field_center_mt:.2f} mT | wheel: zoom",12,10)


class MotionPlot(wx.Panel):
    COLORS=("#237c73","#d15b45","#5577aa","#8d62a8")
    def __init__(self,parent):
        super().__init__(parent,style=wx.BORDER_SIMPLE);self.SetMinSize((-1,280));self.SetBackgroundStyle(wx.BG_STYLE_PAINT);self.dynamics=None;self.Bind(wx.EVT_PAINT,self.paint)
    def show(self,dynamics):self.dynamics=dynamics;self.Refresh()
    def paint(self,_event):
        dc=wx.AutoBufferedPaintDC(self);bg=wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW);fg=wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT);dc.SetBackground(wx.Brush(bg));dc.Clear();w,h=self.GetClientSize()
        if not self.dynamics or not self.dynamics.samples:dc.SetTextForeground(fg);dc.DrawLabel("Run the coupled simulation to view position, speed, acceleration, and force.",wx.Rect(8,8,w-16,h-16),wx.ALIGN_CENTER);return
        samples=self.dynamics.samples;left,right,top,bottom=62,18,32,30;plot_w=max(1,w-left-right);lane_h=max(38,(h-top-bottom)//4)
        series=(("Position",lambda s:s.displacement_m,"m"),("Speed",lambda s:s.velocity_m_s,"m/s"),("Acceleration",lambda s:s.acceleration_m_s2,"m/s2"),("Force / torque",lambda s:s.force_n,"N or N m"))
        tmax=max(samples[-1].time_s,1e-15);dc.SetTextForeground(fg)
        for lane,(label,getter,unit) in enumerate(series):
            y0=top+lane*lane_h;values=[getter(s) for s in samples];peak=max(max(abs(v) for v in values),1e-30)
            dc.SetPen(wx.Pen("#9aa7b2",1));dc.DrawLine(left,y0+lane_h//2,w-right,y0+lane_h//2)
            dc.DrawText(f"{label}\n{peak:.3g} {unit}",4,y0+3);points=[]
            for sample,value in zip(samples,values):
                x=left+sample.time_s/tmax*plot_w;y=y0+lane_h/2-value/peak*(lane_h*.38);points.append(wx.Point(int(x),int(y)))
            dc.SetPen(wx.Pen(self.COLORS[lane],2))
            if len(points)>1:dc.DrawLines(points)
        dc.DrawText(f"0 s",left,h-22);dc.DrawText(f"{tmax:.4g} s",max(left,w-right-75),h-22)


class PlanarMagneticsPlugin(pcbnew.ActionPlugin):
    def defaults(self):self.name="KiWay Planar Magnetics & Actuator Workbench";self.category="PCB Engineering";self.description="Design PCB inductors, transformers, motors, actuators, and magnetic torquers.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"icon.png");self.dark_icon_file_name=self.icon_file_name;self.version=VERSION
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:wx.MessageBox("Open a PCB first.",self.name,wx.OK|wx.ICON_ERROR);return
        MagneticsFrame(None,board).Show()


class MagneticsFrame(wx.Frame):
    def __init__(self,parent,board):
        super().__init__(parent,title="KiWay Planar Magnetics & Actuator Workbench",size=(1320,880));self.SetMinSize((1080,740));self.board=board;self.catalog=dict(CORE_CATALOG);self.result=None;self.preview_items=[];self.undo_stack=[];self.redo_stack=[];self._build();self.undo_stack=self._persistent_groups();self.Bind(wx.EVT_CLOSE,self.on_close);self.Centre()
    def _build(self):
        p=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL);self.guide=add_workflow(p,root,"Planar Magnetics and Actuator Workbench","Generate multilayer/via-connected windings, apply core and frequency models, inspect fields and motion, then commit only reviewed copper.",("Winding","Model","Field and motion","PCB commit"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()));self.tabs=wx.Notebook(p);self.tabs.AddPage(self.design_page(self.tabs),"Winding and Core");self.tabs.AddPage(self.model_page(self.tabs),"LCR / Parasitics");self.tabs.AddPage(self.actuator_page(self.tabs),"Field and Actuator");root.Add(self.tabs,1,wx.EXPAND|wx.ALL,8);p.SetSizer(root)
    def design_page(self,parent):
        p=wx.Panel(parent);root=wx.BoxSizer(wx.HORIZONTAL)
        rail=wx.Panel(p);rail.SetMinSize((390,-1));rail_root=wx.BoxSizer(wx.VERTICAL)
        scroll=wx.ScrolledWindow(rail,style=wx.VSCROLL);scroll.SetScrollRate(0,12)
        box=wx.StaticBoxSizer(wx.VERTICAL,scroll,"Geometry and excitation");bp=box.GetStaticBox();g=wx.FlexGridSizer(0,2,6,8);g.AddGrowableCol(1,1);self.fields={}
        self.shape=wx.Choice(bp,choices=["Rectangular spiral","Circular spiral"]);self.shape.SetSelection(0);g.Add(wx.StaticText(bp,label="Winding shape"));g.Add(self.shape,1,wx.EXPAND)
        for label,key,value in (("Outer width (mm)","width","35"),("Outer height (mm)","height","35"),("Turns per layer","turns","8"),("Trace width (mm)","trace","0.5"),("Spacing (mm)","spacing","0.25"),("Copper thickness (um)","copper","35"),("Primary copper layers","layers","2"),("Frequency (kHz)","frequency","100"),("Current (A)","current","0.5"),("Voltage (V)","voltage","5"),("Secondary turns (0=none)","secondary","0"),("Secondary layers","secondary_layers","1"),("Coupling coefficient","coupling","0.90"),("Origin X (mm)","origin_x","20"),("Origin Y (mm)","origin_y","20")):
            c=wx.TextCtrl(bp,value=value);self.fields[key]=c;g.Add(wx.StaticText(bp,label=label));g.Add(c,1,wx.EXPAND)
        self.connection=wx.Choice(bp,choices=["Series","Parallel"]);self.connection.SetSelection(0);g.Add(wx.StaticText(bp,label="Layer connection"));g.Add(self.connection,1,wx.EXPAND);self.core=wx.ComboBox(bp,choices=sorted(self.catalog),style=wx.CB_READONLY);self.core.SetValue("Air / no core");g.Add(wx.StaticText(bp,label="Magnetic core"));g.Add(self.core,1,wx.EXPAND);nets=["<no net>"]+self._nets();self.net=wx.ComboBox(bp,choices=nets,style=wx.CB_READONLY);self.net.SetSelection(0);g.Add(wx.StaticText(bp,label="Primary PCB net"));g.Add(self.net,1,wx.EXPAND);self.secondary_net=wx.ComboBox(bp,choices=nets,style=wx.CB_READONLY);self.secondary_net.SetSelection(0);g.Add(wx.StaticText(bp,label="Secondary PCB net"));g.Add(self.secondary_net,1,wx.EXPAND);box.Add(g,1,wx.EXPAND|wx.ALL,10)
        core_actions=wx.BoxSizer(wx.HORIZONTAL);load=wx.Button(bp,label="Import Cores...");load.Bind(wx.EVT_BUTTON,self.load_cores);save=wx.Button(bp,label="Export Cores...");save.Bind(wx.EVT_BUTTON,self.save_cores);core_actions.Add(load,1,wx.RIGHT,6);core_actions.Add(save,1);box.Add(core_actions,0,wx.EXPAND|wx.ALL,10)
        scroll.SetSizer(box);scroll.FitInside();rail_root.Add(scroll,1,wx.EXPAND)
        analyze=wx.Button(rail,label="Generate and Analyze Winding");analyze.SetDefault();analyze.Bind(wx.EVT_BUTTON,self.analyze);rail_root.Add(analyze,0,wx.EXPAND|wx.TOP,8);rail.SetSizer(rail_root);root.Add(rail,0,wx.EXPAND|wx.ALL,10)
        right=wx.BoxSizer(wx.VERTICAL);self.preview=MagneticPreview(p);right.Add(self.preview,1,wx.EXPAND);actions=wx.BoxSizer(wx.HORIZONTAL)
        for label,handler in (("Show on PCB",self.show_pcb),("Clear PCB Preview",self.clear_preview),("Commit to PCB",self.commit),("Undo Commit",self.undo),("Redo Commit",self.redo),("Export JSON...",self.export_json),("Export Geometry CSV...",self.export_csv)):
            b=wx.Button(p,label=label);b.Bind(wx.EVT_BUTTON,handler);actions.Add(b,0,wx.RIGHT,6)
        right.Add(actions,0,wx.TOP,8);self.status=wx.StaticText(p,label="No winding analyzed. PCB unchanged.");right.Add(self.status,0,wx.TOP,8);root.Add(right,1,wx.EXPAND|wx.ALL,10);p.SetSizer(root);return p
    def model_page(self,parent):
        p=wx.Panel(parent);root=wx.BoxSizer(wx.VERTICAL);self.results=wx.ListCtrl(p,style=wx.LC_REPORT);self.results.InsertColumn(0,"Metric",width=270);self.results.InsertColumn(1,"Result",width=250);self.results.InsertColumn(2,"Model / review note",width=680);root.Add(self.results,1,wx.EXPAND|wx.ALL,10);p.SetSizer(root);return p
    def actuator_page(self,parent):
        p=wx.Panel(parent);root=wx.BoxSizer(wx.HORIZONTAL);rail=wx.ScrolledWindow(p,style=wx.VSCROLL);rail.SetMinSize((390,-1));rail.SetScrollRate(0,12);rs=wx.BoxSizer(wx.VERTICAL)
        concept=wx.StaticBoxSizer(wx.VERTICAL,rail,"Actuator and drive");cp=concept.GetStaticBox();grid=wx.FlexGridSizer(0,2,6,8);grid.AddGrowableCol(1,1)
        self.actuator=wx.Choice(cp,choices=["Voice coil","Linear solenoid","PCB coil motor","PCB magnetic torquer"]);self.actuator.SetSelection(0)
        self.external=wx.TextCtrl(cp,value="50");self.drive_mode=wx.Choice(cp,choices=["Voltage step","Voltage sine","Current step","Current sine"]);self.drive_mode.SetSelection(0)
        for label,control in (("Actuator concept",self.actuator),("External field (uT)",self.external),("Drive waveform",self.drive_mode)):grid.Add(wx.StaticText(cp,label=label),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(control,1,wx.EXPAND)
        concept.Add(grid,1,wx.EXPAND|wx.ALL,8);rs.Add(concept,0,wx.EXPAND|wx.ALL,8)
        mechanics=wx.StaticBoxSizer(wx.VERTICAL,rail,"Mechanical model");mp=mechanics.GetStaticBox();g=wx.FlexGridSizer(0,2,6,8);g.AddGrowableCol(1,1);self.motion_fields={}
        for label,key,value in (("Moving mass (ng)","mass_ng","1000000"),("Spring stiffness (N/m)","spring","1"),("Mechanical Q","mech_q","20"),("Damping (N s/m, 0=Q)","damping","0"),("Initial magnetic gap (um)","gap_um","500"),("Travel limit (um or urad)","stroke_um","1000"),("Opposing load (uN)","load_un","0"),("Static friction (uN)","friction_un","0"),("Drive frequency (Hz)","drive_hz","100"),("Duration (ms)","duration_ms","20"),("Requested step (us)","step_us","2"),("Temperature (K)","temperature","293.15"),("Rotor inertia (kg m2)","inertia","1e-10"),("Angular stiffness (N m/rad)","angular_stiffness","0")):
            control=wx.TextCtrl(mp,value=value);self.motion_fields[key]=control;g.Add(wx.StaticText(mp,label=label),0,wx.ALIGN_CENTER_VERTICAL);g.Add(control,1,wx.EXPAND)
        mechanics.Add(g,1,wx.EXPAND|wx.ALL,8);preset=wx.BoxSizer(wx.HORIZONTAL);macro=wx.Button(mp,label="Macro Preset");macro.Bind(wx.EVT_BUTTON,lambda e:self._motion_preset(False));nano=wx.Button(mp,label="Nano Screening Preset");nano.Bind(wx.EVT_BUTTON,lambda e:self._motion_preset(True));preset.Add(macro,1,wx.RIGHT,6);preset.Add(nano,1);mechanics.Add(preset,0,wx.EXPAND|wx.ALL,8);rs.Add(mechanics,0,wx.EXPAND|wx.LEFT|wx.RIGHT,8)
        run=wx.Button(rail,label="Run Coupled Motion Simulation");run.SetDefault();run.Bind(wx.EVT_BUTTON,self.run_dynamics);rs.Add(run,0,wx.EXPAND|wx.ALL,8);rail.SetSizer(rs);rail.FitInside();root.Add(rail,0,wx.EXPAND|wx.ALL,8)
        right=wx.BoxSizer(wx.VERTICAL);toolbar=wx.BoxSizer(wx.HORIZONTAL);self.animate=wx.ToggleButton(p,label="Animate Simulated Motion");self.animate.Bind(wx.EVT_TOGGLEBUTTON,lambda e:self.preview.set_animation(self.animate.GetValue()));toolbar.Add(self.animate,0,wx.RIGHT,8);export=wx.Button(p,label="Export Motion CSV...");export.Bind(wx.EVT_BUTTON,self.export_motion);toolbar.Add(export);right.Add(toolbar,0,wx.BOTTOM,8)
        self.motion_plot=MotionPlot(p);right.Add(self.motion_plot,1,wx.EXPAND|wx.BOTTOM,8);self.actuator_results=wx.ListCtrl(p,style=wx.LC_REPORT|wx.LC_HRULES|wx.LC_VRULES);self.actuator_results.InsertColumn(0,"Quantity",width=250);self.actuator_results.InsertColumn(1,"Estimate",width=220);self.actuator_results.InsertColumn(2,"Interpretation",width=520);right.Add(self.actuator_results,1,wx.EXPAND);root.Add(right,1,wx.EXPAND|wx.ALL,10);p.SetSizer(root);return p
    def _nets(self):
        try:return sorted(str(n) for n in self.board.GetNetsByName().keys() if str(n))
        except Exception:return []
    def _spec(self):
        f=self.fields;return CoilSpec(shape=self.shape.GetStringSelection(),outer_width_mm=float(f['width'].GetValue()),outer_height_mm=float(f['height'].GetValue()),turns=int(f['turns'].GetValue()),trace_width_mm=float(f['trace'].GetValue()),spacing_mm=float(f['spacing'].GetValue()),copper_um=float(f['copper'].GetValue()),layers=int(f['layers'].GetValue()),layer_connection=self.connection.GetStringSelection(),frequency_khz=float(f['frequency'].GetValue()),current_a=float(f['current'].GetValue()),voltage_v=float(f['voltage'].GetValue()),core_name=self.core.GetValue(),secondary_turns=int(f['secondary'].GetValue()),secondary_layers=int(f['secondary_layers'].GetValue()),coupling=float(f['coupling'].GetValue()),external_field_ut=float(self.external.GetValue()))
    def _motion_spec(self):
        f=self.motion_fields;return MotionSpec(moving_mass_kg=float(f["mass_ng"].GetValue())*1e-12,spring_n_m=float(f["spring"].GetValue()),mechanical_q=float(f["mech_q"].GetValue()),damping_ns_m=float(f["damping"].GetValue()),initial_gap_m=float(f["gap_um"].GetValue())*1e-6,stroke_limit_m=float(f["stroke_um"].GetValue())*1e-6,load_force_n=float(f["load_un"].GetValue())*1e-6,static_friction_n=float(f["friction_un"].GetValue())*1e-6,drive_mode=self.drive_mode.GetStringSelection(),drive_frequency_hz=float(f["drive_hz"].GetValue()),duration_s=float(f["duration_ms"].GetValue())*1e-3,time_step_s=float(f["step_us"].GetValue())*1e-6,temperature_k=float(f["temperature"].GetValue()),rotor_inertia_kg_m2=float(f["inertia"].GetValue()),angular_stiffness_nm_rad=float(f["angular_stiffness"].GetValue()))
    def _motion_preset(self,nano):
        values={"mass_ng":"1","spring":"0.1","mech_q":"100","damping":"0","gap_um":"0.5","stroke_um":"0.2","load_un":"0","friction_un":"0","drive_hz":"100000","duration_ms":"0.2","step_us":"0.001","temperature":"293.15","inertia":"1e-24","angular_stiffness":"1e-12"} if nano else {"mass_ng":"1000000","spring":"1","mech_q":"20","damping":"0","gap_um":"500","stroke_um":"1000","load_un":"0","friction_un":"0","drive_hz":"100","duration_ms":"20","step_us":"2","temperature":"293.15","inertia":"1e-10","angular_stiffness":"0"}
        for key,value in values.items():self.motion_fields[key].SetValue(value)
        self.status.SetLabel("Nanoscale screening preset loaded; process-calibrated multiphysics validation is mandatory." if nano else "Macro-scale actuator preset loaded.")
    def analyze(self,_e):
        try:self._calculate(1)
        except Exception as exc:wx.MessageBox(str(exc),"Magnetics analysis failed",wx.OK|wx.ICON_ERROR)
    def run_dynamics(self,_e):
        try:self._calculate(2)
        except Exception as exc:wx.MessageBox(str(exc),"Motion simulation failed",wx.OK|wx.ICON_ERROR)
    def _calculate(self,tab):
        self.clear_preview(None);self.result=MagneticsEngine.analyze(self._spec(),self.catalog,self.actuator.GetStringSelection());MagneticsEngine.simulate_dynamics(self.result,self._motion_spec(),self.actuator.GetStringSelection());self.preview.show_result(self.result);self.motion_plot.show(self.result.dynamics);self._fill_results();self.tabs.SetSelection(tab);self.status.SetLabel(f"Analyzed {len(self.result.segments)} segments and {len(self.result.dynamics.samples)} motion samples. PCB unchanged. {self.result.dynamics.validity}.");self.guide.set_step(2,"Review force, acceleration, speed, travel, resonance, noise, and every model warning.")
    def _fill(self,table,rows):
        table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);table.SetItem(i,1,row[1]);table.SetItem(i,2,row[2])
    def _fill_results(self):
        r=self.result;rows=[("Conductor length",f"{r.conductor_length_mm:.2f} mm","Includes approximate via barrel length"),("DC resistance",f"{r.resistance_dc_ohm:.5f} ohm","Copper bulk resistivity"),("AC resistance",f"{r.resistance_ac_ohm:.5f} ohm",f"First-order skin/proximity at {r.spec.frequency_khz:g} kHz"),("Inductance",f"{r.inductance_uh:.3f} uH",f"{r.core.name}; reduced-order winding/core model"),("Parasitic capacitance",f"{r.capacitance_pf:.2f} pF","Geometry-based estimate"),("Self resonance",f"{r.self_resonance_mhz:.3f} MHz","L-C estimate; stay well below for lumped operation"),("Quality factor",f"{r.quality_factor:.2f}","omega L / Rac"),("Copper loss",f"{r.copper_loss_w:.4f} W","I^2 Rac"),("Core loss",f"{r.core_loss_w:.4f} W","Catalog Steinmetz-like estimate"),("Saturation current",f"{r.saturation_current_a:.3f} A","Gap/core reluctance estimate")]
        if r.spec.secondary_turns:rows.extend((("Secondary inductance",f"{r.secondary_inductance_uh:.3f} uH","Turns-ratio estimate"),("Mutual inductance",f"{r.mutual_inductance_uh:.3f} uH",f"k={r.spec.coupling:g}"),("Turns ratio",f"1:{r.turns_ratio:.3f}","Primary effective turns to secondary")))
        self._fill(self.results,rows)
        d=r.dynamics
        motion_rows=[("Center field",f"{r.field_center_mt:.3f} mT","Limited at catalog saturation flux density")]
        if d:
            unit="rad" if d.mode=="Rotary" else "m"
            motion_rows.extend([
                ("Model validity",d.validity,"Read every warning before using results"),
                ("Peak force / torque",f"{d.peak_force_n:.6g} {'N m' if d.mode=='Rotary' else 'N'}","Position-dependent coupled estimate"),
                ("Force / torque constant",f"{d.force_constant_n_a:.6g} {'N m/A' if d.mode=='Rotary' else 'N/A'}","Local linearized transduction constant"),
                ("Force gradient",f"{d.force_gradient_n_m:.6g} N/m","Central difference at the initial position"),
                ("Peak acceleration",f"{d.peak_acceleration_m_s2:.6g} {unit}/s2","Includes spring, damping, load, and stiction inputs"),
                ("Peak speed",f"{d.peak_speed_m_s:.6g} {unit}/s","Coupled electrical-mechanical trajectory"),
                ("Peak travel",f"{d.peak_displacement_m:.6g} {unit}","Hard travel stop enforced"),
                ("Final position",f"{d.final_displacement_m:.6g} {unit}","At simulation end"),
                ("Mechanical resonance",f"{d.natural_frequency_hz:.6g} Hz","sqrt(k/m) or rotary equivalent"),
                ("Mechanical damping",f"{d.damping_ns_m:.6g} {'N m s/rad' if d.mode=='Rotary' else 'N s/m'}","Explicit value or derived from Q"),
                ("2% settling time","Not settled" if d.settling_time_s is None else f"{d.settling_time_s:.6g} s","Within simulated duration and travel clamp"),
                ("Thermal force noise",f"{d.thermal_force_noise_n_sqrt_hz:.6g} N/sqrt(Hz)","One-sided lumped viscous-damping estimate"),
                ("Brownian displacement RMS",f"{d.brownian_displacement_rms_m:.6g} {unit}","sqrt(kB T / k); excludes readout and surface noise"),
            ])
            motion_rows.extend((f"Warning {index}",warning,"Requires engineering disposition") for index,warning in enumerate(d.warnings,1))
        motion_rows.append(("Required validation","Coupled FEA + process data + prototype","Especially mandatory for MEMS/NEMS and nanoscale travel"))
        self._fill(self.actuator_results,motion_rows)
    def load_cores(self,_e):
        with wx.FileDialog(self,"Import core catalog",wildcard="JSON (*.json)|*.json",style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            self.catalog=load_core_catalog(d.GetPath());self.core.SetItems(sorted(self.catalog));self.core.SetValue("Air / no core")
    def save_cores(self,_e):
        with wx.FileDialog(self,"Export core catalog",wildcard="JSON (*.json)|*.json",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:save_core_catalog(d.GetPath(),self.catalog)
    def _make_items(self):
        if not self.result:return []
        ox=float(self.fields['origin_x'].GetValue());oy=float(self.fields['origin_y'].GetValue());items=[];net=None
        secondary_net=None
        if self.net.GetValue()!="<no net>":
            try:net=self.board.GetNetsByName()[self.net.GetValue()]
            except Exception:pass
        if self.secondary_net.GetValue()!="<no net>":
            try:secondary_net=self.board.GetNetsByName()[self.secondary_net.GetValue()]
            except Exception:pass
        copper=max(1,int(getattr(self.board,"GetCopperLayerCount",lambda:2)()))
        required=self.result.spec.layers+(self.result.spec.secondary_layers if self.result.spec.secondary_turns else 0)
        if required>copper:raise ValueError(f"The windings require {required} copper layers, but this PCB exposes {copper}.")
        for s in self.result.segments:
            track=pcbnew.PCB_TRACK(self.board);track.SetStart(point(ox+s.x1_mm,oy+s.y1_mm));track.SetEnd(point(ox+s.x2_mm,oy+s.y2_mm));track.SetWidth(pcbnew.FromMM(s.width_mm));track.SetLayer(copper_layer(s.layer,copper));selected_net=secondary_net if s.winding=="Secondary" else net
            if selected_net is not None:track.SetNet(selected_net)
            self.board.Add(track);items.append(track)
        for v in self.result.vias:
            via=pcbnew.PCB_VIA(self.board);via.SetPosition(point(ox+v.x_mm,oy+v.y_mm));via.SetWidth(pcbnew.FromMM(max(.6,self.result.spec.trace_width_mm*1.8)));via.SetDrill(pcbnew.FromMM(max(.3,self.result.spec.trace_width_mm*.7)))
            if hasattr(via,"SetLayerPair"):via.SetLayerPair(copper_layer(v.from_layer,copper),copper_layer(v.to_layer,copper))
            selected_net=secondary_net if v.winding=="Secondary" else net
            if selected_net is not None:via.SetNet(selected_net)
            self.board.Add(via);items.append(via)
        if hasattr(pcbnew,"Refresh"):pcbnew.Refresh()
        return items
    def show_pcb(self,_e):
        if not self.result:wx.MessageBox("Analyze a winding first.","Preview required",wx.OK|wx.ICON_INFORMATION);return
        try:self.clear_preview(None);self.preview_items=self._make_items();self.status.SetLabel(f"Temporary PCB preview: {len(self.preview_items)} items. Run visual clearance checks before commit.");self.guide.set_step(3,"Inspect all copper layers and via transitions, then commit or clear the preview.")
        except Exception as exc:wx.MessageBox(str(exc),"PCB preview failed",wx.OK|wx.ICON_ERROR)
    def clear_preview(self,_e):
        for item in self.preview_items:
            try:self.board.Remove(item)
            except Exception:pass
        self.preview_items=[]
        if hasattr(pcbnew,"Refresh"):pcbnew.Refresh()
    def commit(self,_e):
        if not self.preview_items:wx.MessageBox("Show the exact winding on the PCB before committing.","PCB preview required",wx.OK|wx.ICON_INFORMATION);return
        items=list(self.preview_items);self.preview_items=[]
        group=self._new_group(items);self.undo_stack.append(group);self.redo_stack.clear()
        self.status.SetLabel(f"Committed {len(items)} items. Run DRC, field simulation, LCR measurement, and thermal validation.")
    def _persistent_groups(self):
        return [g for g in getattr(self.board,"Groups",lambda:[])() if str(getattr(g,"GetName",lambda:"")()).startswith("KiWay Planar Magnetics Commit")]
    def _group_items(self,group):
        for name in ("GetItems","GetBoardItems"):
            try:return list(getattr(group,name)())
            except Exception:pass
        return []
    def _new_group(self,items,name=""):
        if not hasattr(pcbnew,"PCB_GROUP"):return list(items)
        group=pcbnew.PCB_GROUP(self.board);group.SetName(name or f"KiWay Planar Magnetics Commit {len(self._persistent_groups())+1:03d}");self.board.Add(group)
        for item in items:group.AddItem(item)
        return group
    def undo(self,_e):
        if not self.undo_stack:self.status.SetLabel("No KiWay magnetics commit to undo.");return
        entry=self.undo_stack.pop();items=list(entry) if isinstance(entry,list) else self._group_items(entry);name="KiWay Planar Magnetics Commit" if isinstance(entry,list) else str(entry.GetName())
        if not isinstance(entry,list):
            for item in items:
                try:entry.RemoveItem(item)
                except Exception:pass
            try:self.board.Remove(entry)
            except Exception:pass
        for item in items:
            try:self.board.Remove(item)
            except Exception:pass
        self.redo_stack.append((name,items));self.status.SetLabel(f"Undid magnetics commit containing {len(items)} items.");pcbnew.Refresh()
    def redo(self,_e):
        if not self.redo_stack:self.status.SetLabel("No KiWay magnetics commit to redo.");return
        name,items=self.redo_stack.pop()
        for item in items:self.board.Add(item)
        self.undo_stack.append(self._new_group(items,name));self.status.SetLabel(f"Redid magnetics commit containing {len(items)} items.");pcbnew.Refresh()
    def export_json(self,_e):
        if not self.result:return
        with wx.FileDialog(self,"Export magnetic model",wildcard="JSON (*.json)|*.json",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:Path(d.GetPath()).write_text(json.dumps(asdict(self.result),indent=2),encoding="utf-8")
    def export_csv(self,_e):
        if not self.result:return
        with wx.FileDialog(self,"Export winding geometry",wildcard="CSV (*.csv)|*.csv",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            with open(d.GetPath(),"w",newline="",encoding="utf-8") as h:w=csv.writer(h);w.writerow(("winding","layer","x1_mm","y1_mm","x2_mm","y2_mm","width_mm"));w.writerows((s.winding,s.layer,s.x1_mm,s.y1_mm,s.x2_mm,s.y2_mm,s.width_mm) for s in self.result.segments)
    def export_motion(self,_e):
        if not self.result or not self.result.dynamics:return
        with wx.FileDialog(self,"Export actuator motion",wildcard="CSV (*.csv)|*.csv",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            with open(d.GetPath(),"w",newline="",encoding="utf-8") as h:
                writer=csv.writer(h);writer.writerow(("time_s","displacement_m_or_rad","velocity_m_s_or_rad_s","acceleration_m_s2_or_rad_s2","current_a","force_n_or_torque_nm"))
                writer.writerows((s.time_s,s.displacement_m,s.velocity_m_s,s.acceleration_m_s2,s.current_a,s.force_n) for s in self.result.dynamics.samples)
    def on_close(self,event):self.preview.set_animation(False);self.clear_preview(None);event.Skip()
