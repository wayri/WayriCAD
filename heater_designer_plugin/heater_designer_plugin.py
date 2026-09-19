from __future__ import annotations

import csv
import json
import os
import webbrowser
from pathlib import Path

import pcbnew
import wx

from .analysis import HeatZone, HeaterEngine, HeaterResult, HeaterSpec, ThermalResult, ThermalSpec
from .guided_ui import add_workflow
from .placement import validate_placement


VERSION = "3.1.1"
PALETTE = ("#157f74", "#d1495b", "#edae49", "#5267a5", "#8f5aa6", "#3c91a3")


def point(x_mm: float, y_mm: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))

def copper_layer(index: int, count: int) -> int:
    if index <= 0: return int(pcbnew.F_Cu)
    if index >= count - 1: return int(pcbnew.B_Cu)
    return int(getattr(pcbnew, f"In{index}_Cu"))


class HeaterPreview(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetMinSize((-1, 320)); self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.heater: HeaterResult | None = None; self.thermal: ThermalResult | None = None
        self.mode = "pattern"; self.zoom = 1.0; self.pan = (0,0); self.drag = None; self.Bind(wx.EVT_PAINT,self.paint); self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.pan_start); self.Bind(wx.EVT_LEFT_UP, self.pan_end)
        self.Bind(wx.EVT_MOTION, self.pan_move); self.Bind(wx.EVT_LEFT_DCLICK, self.fit)
        self.Bind(wx.EVT_SIZE,self._on_size); self.Bind(wx.EVT_ERASE_BACKGROUND,self._on_erase)

    def _on_size(self,event):self._repaint();event.Skip()
    def _on_erase(self,_event):pass

    def _repaint(self):self.Refresh();self.Update()
    def show_pattern(self,result): self.heater=result; self.thermal=None; self.mode="pattern"; self._repaint()
    def show_thermal(self,result): self.heater=result.heater; self.thermal=result; self.mode="thermal"; self._repaint()
    def wheel(self,event): self.zoom=max(0.5,min(5.0,self.zoom*(1.12 if event.GetWheelRotation()>0 else 0.89)));self._repaint()
    def pan_start(self,event):self.drag=event.GetPosition();self.CaptureMouse()
    def pan_end(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()
    def pan_move(self,event):
        if self.drag is not None and event.Dragging():
            point=event.GetPosition();self.pan=(self.pan[0]+point.x-self.drag.x,self.pan[1]+point.y-self.drag.y);self.drag=point;self._repaint()
    def fit(self,event=None):self.zoom=1.0;self.pan=(0,0);self._repaint()

    def paint(self,_event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush("#f7f9fb"));dc.Clear();w,h=self.GetClientSize()
        if w<48 or h<48:return
        if not self.heater:
            dc.SetTextForeground("#52616b");dc.DrawLabel("Generate a heater to inspect exact copper geometry and zoned power.",wx.Rect(10,10,w-20,h-20),wx.ALIGN_CENTER);return
        margin=32;spec=self.heater.spec;scale=min((w-2*margin)/spec.width_mm,(h-2*margin)/spec.height_mm)*self.zoom
        ox=(w-spec.width_mm*scale)/2+self.pan[0];oy=(h-spec.height_mm*scale)/2+self.pan[1]
        project=lambda x,y:(int(ox+x*scale),int(oy+(spec.height_mm-y)*scale))
        if self.mode=="thermal" and self.thermal:
            grid=self.thermal.temperatures_c;lo=self.thermal.minimum_c;span=max(self.thermal.maximum_c-lo,1e-6);ny=len(grid);nx=len(grid[0])
            for iy,row in enumerate(grid):
                for ix,value in enumerate(row):
                    t=(value-lo)/span;color=wx.Colour(int(35+220*t),int(105+90*(1-t)),int(220*(1-t)))
                    x1,y1=project(ix*spec.width_mm/nx,(iy+1)*spec.height_mm/ny);x2,y2=project((ix+1)*spec.width_mm/nx,iy*spec.height_mm/ny);dc.SetPen(wx.Pen(color));dc.SetBrush(wx.Brush(color));dc.DrawRectangle(min(x1,x2),min(y1,y2),abs(x2-x1)+1,abs(y2-y1)+1)
        zones={"Uniform":"#157f74"}
        for segment in self.heater.segments:
            zones.setdefault(segment.zone,PALETTE[len(zones)%len(PALETTE)]);dc.SetPen(wx.Pen(zones[segment.zone],max(2,int(segment.width_mm*scale))));dc.DrawLine(*project(segment.x1_mm,segment.y1_mm),*project(segment.x2_mm,segment.y2_mm))
        for via in self.heater.vias:
            radius=max(0.6,spec.trace_width_mm*1.8)*scale/2;drill=max(0.3,spec.trace_width_mm*0.7)*scale/2
            dc.SetBrush(wx.Brush("#ac7c26"));dc.SetPen(wx.Pen("#674d00",1));dc.DrawCircle(*project(via.x_mm,via.y_mm),max(1,round(radius)))
            dc.SetBrush(wx.Brush("#f7f9fb"));dc.SetPen(wx.TRANSPARENT_PEN);dc.DrawCircle(*project(via.x_mm,via.y_mm),max(1,round(drill)))
        dc.SetPen(wx.Pen("#263744",2));dc.SetBrush(wx.TRANSPARENT_BRUSH);x1,y1=project(0,spec.height_mm);x2,y2=project(spec.width_mm,0);dc.DrawRectangle(x1,y1,x2-x1,y2-y1)
        label=f"{self.mode.title()} | {self.heater.resistance_ohm:.3f} ohm | {self.heater.current_a:.2f} A | {self.heater.power_w:.2f} W | wheel: zoom"
        dc.SetTextForeground("#263744");dc.DrawText(label,12,10)


class HeaterDesignerPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name="WayriCAD PCB / Foil Heater Designer";self.category="PCB Engineering";self.description="Design zoned PCB heaters and simulate thermal patterns.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"resources","icon-24.png");self.dark_icon_file_name=self.icon_file_name.replace("icon-24.png", "icon-dark-24.png");self.version=VERSION
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None: wx.MessageBox("Open a PCB first.",self.name,wx.OK|wx.ICON_ERROR);return
        HeaterFrame(None,board).Show()


try:
    from .wayricad_runtime.generated import ReviewedGeometry
except ImportError:
    from wayricad_runtime.generated import ReviewedGeometry


class HeaterFrame(ReviewedGeometry, wx.Frame):
    group_prefix = 'WayriCAD Heater Commit'
    def __init__(self,parent,board):
        super().__init__(parent,title="WayriCAD PCB / Foil Heater Designer",size=(1280,850));self.SetMinSize((1040,720));self.board=board;self.result=None;self.thermal=None;self.preview_items=[];self.undo_stack=[];self.redo_stack=[];self._build();self.undo_stack=self._persistent_groups();self.Bind(wx.EVT_CLOSE,self.on_close);self.Centre()
    def _build(self):
        try:
            from .wayricad_runtime.ui import form_page, field, choice, more_button, details
        except ImportError:
            from wayricad_runtime.ui import form_page, field, choice, more_button, details
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.guide = add_workflow(panel, root, "Heater Designer", "Preview copper and temperature, then apply the reviewed pattern.",
                                  ("Configure", "Review", "Apply"))
        body = wx.BoxSizer(wx.HORIZONTAL)
        controls = wx.Notebook(panel)
        controls.SetMinSize((330, -1))
        geometry, geometry_layout, grid = form_page(controls, "Geometry")
        thermal, thermal_layout, thermal_grid = form_page(controls, "Thermal")
        placement, _, placement_grid = form_page(controls, "Placement")
        self.fields = {}
        for label, key, value in (("Width (mm)","width",80),("Height (mm)","height",50),
                                   ("Trace width (mm)","trace",0.5),("Spacing (mm)","spacing",0.5),
                                   ("Copper (µm)","copper",35),("Supply (V)","voltage",12)):
            self.fields[key] = field(geometry, grid, label, value)
        self.pattern = choice(geometry, grid, "Pattern", ["Serpentine", "Concentric spiral", "Zoned raster"])
        for label, key, value in (("Copper layers","layers",1),("Origin X (mm)","origin_x",20),("Origin Y (mm)","origin_y",20)):
            self.fields[key] = field(placement, placement_grid, label, value)
        self.net = choice(placement, placement_grid, "Net", ["<no net>"] + self._net_names())
        self.thermal_fields = {}
        for label,key,value in (("Ambient (°C)","ambient",25),("In-plane k (W/mK)","k",0.30),
                                 ("Thickness (mm)","thickness",1.6),("Convection (W/m²K)","h",10),
                                 ("Grid X","gx",42),("Grid Y","gy",28)):
            self.thermal_fields[key] = field(thermal, thermal_grid, label, value)
        zone_parent, zone_layout = details(thermal, thermal_layout, "Thermal zones")
        hint = wx.StaticText(zone_parent, label="Name, X%, Y%, radius%, resistance factor")
        hint.Wrap(275)
        zone_layout.Add(hint, 0, wx.ALL, 6)
        self.zones = wx.TextCtrl(zone_parent, value="Hotspot,50,50,18,1.8\nCold edge,10,50,12,0.65", style=wx.TE_MULTILINE)
        self.zones.SetMinSize((-1,90))
        zone_layout.Add(self.zones, 0, wx.EXPAND | wx.ALL, 6)
        body.Add(controls, 0, wx.EXPAND | wx.RIGHT, 14)
        right = wx.BoxSizer(wx.VERTICAL)
        self.preview = HeaterPreview(panel)
        right.Add(self.preview, 1, wx.EXPAND)
        metrics_parent, metrics_layout = details(panel, right, "Electrical and thermal results")
        self.metrics = wx.ListCtrl(metrics_parent, style=wx.LC_REPORT)
        self.metrics.SetMinSize((-1,180))
        for index, (label, width) in enumerate((("Metric",190),("Value",170),("Review note",350))):
            self.metrics.InsertColumn(index, label, width=width)
        metrics_layout.Add(self.metrics, 1, wx.EXPAND)
        body.Add(right, 1, wx.EXPAND)
        root.Add(body, 1, wx.EXPAND | wx.ALL, 14)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.status = wx.StaticText(panel, label="Choose dimensions, then preview.")
        actions.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        for label, handler in (("Preview",self.generate),("Simulate",self.simulate),("Apply to PCB",self.commit)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON,handler)
            if label == "Preview":button.SetDefault()
            actions.Add(button,0,wx.LEFT,6)
        actions.Add(more_button(panel, [("Review placement",self.show_pcb),("Clear placement",self.clear_preview),
                                       ("Undo last apply",self.undo),("Redo",self.redo),
                                       ("Export CSV…",self.export_csv),("Export JSON…",self.export_json)]),0,wx.LEFT,6)
        root.Add(actions,0,wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,14)
        panel.SetSizer(root)
    def _net_names(self):
        try:return sorted(str(name) for name in self.board.GetNetsByName().keys() if str(name))
        except Exception:return []
    def _zones(self):
        rows=[]
        for line in self.zones.GetValue().splitlines():
            if not line.strip():continue
            name,x,y,r,f=[item.strip() for item in line.split(",")];rows.append(HeatZone(name,float(x),float(y),float(r),float(f)))
        return tuple(rows)
    def _spec(self):
        f=self.fields;return HeaterSpec(float(f['width'].GetValue()),float(f['height'].GetValue()),float(f['trace'].GetValue()),float(f['spacing'].GetValue()),float(f['copper'].GetValue()),float(f['voltage'].GetValue()),int(f['layers'].GetValue()),self.pattern.GetStringSelection(),self._zones())
    def generate(self,_e):
        try:self.clear_preview(None);self.result=HeaterEngine.generate(self._spec());self.preview.show_pattern(self.result);self._metrics();self.status.SetLabel(f"Preview: {len(self.result.segments)} segments and {len(self.result.vias)} layer transitions. PCB unchanged.");self.guide.set_step(1,"Review width-coded zones and electrical loading, then run the thermal simulation.");self._capture_review()
        except Exception as exc:wx.MessageBox(str(exc),"Heater generation failed",wx.OK|wx.ICON_ERROR)
    def simulate(self,_e):
        try:
            if not self.result:self.generate(None)
            f=self.thermal_fields;spec=ThermalSpec(float(f['ambient'].GetValue()),float(f['k'].GetValue()),float(f['thickness'].GetValue()),float(f['h'].GetValue()),int(f['gx'].GetValue()),int(f['gy'].GetValue()));self.thermal=HeaterEngine.simulate(self.result,spec);self.preview.show_thermal(self.thermal);self._metrics();self.guide.set_step(2,"Review peak temperature and nonuniformity, then show the exact pattern temporarily on the PCB.")
        except Exception as exc:wx.MessageBox(str(exc),"Thermal simulation failed",wx.OK|wx.ICON_ERROR)
    def _metrics(self):
        self.metrics.DeleteAllItems();r=self.result;rows=[("Resistance",f"{r.resistance_ohm:.4f} ohm","20 C copper estimate"),("Current",f"{r.current_a:.3f} A","Check connector, supply, and copper current limits"),("Power",f"{r.power_w:.3f} W",f"{r.watts_per_cm2:.3f} W/cm2"),("Layers / vias",f"{r.spec.layers} / {len(r.vias)}","Series-connected copper layers")]
        if self.thermal:rows.extend((("Temperature min / avg / max",f"{self.thermal.minimum_c:.1f} / {self.thermal.average_c:.1f} / {self.thermal.maximum_c:.1f} C","Reduced-order steady-state estimate"),("Thermal nonuniformity",f"{self.thermal.uniformity_c:.1f} C","Max minus min across model grid")))
        for name,power in sorted(r.zone_power_w.items()):rows.append((f"Zone: {name}",f"{power:.3f} W","Series-path Joule contribution"))
        for row in rows:i=self.metrics.InsertItem(self.metrics.GetItemCount(),row[0]);self.metrics.SetItem(i,1,row[1]);self.metrics.SetItem(i,2,row[2])
    def _board_items(self):
        if not self.result:return []
        ox=float(self.fields['origin_x'].GetValue());oy=float(self.fields['origin_y'].GetValue());items=[];net=None
        if self.net.GetValue()!="<no net>":
            try:net=self.board.GetNetsByName()[self.net.GetValue()]
            except Exception:pass
        copper_count=max(1,int(getattr(self.board,"GetCopperLayerCount",lambda:2)()))
        if self.result.spec.layers>copper_count:raise ValueError(f"The model uses {self.result.spec.layers} copper layers, but this PCB exposes {copper_count}.")
        for segment in self.result.segments:
            track=pcbnew.PCB_TRACK(self.board);track.SetStart(point(ox+segment.x1_mm,oy+segment.y1_mm));track.SetEnd(point(ox+segment.x2_mm,oy+segment.y2_mm));track.SetWidth(pcbnew.FromMM(segment.width_mm));track.SetLayer(copper_layer(segment.layer,copper_count));
            if net is not None:track.SetNet(net)
            items.append(track)
        for transition in self.result.vias:
            via=pcbnew.PCB_VIA(self.board);via.SetPosition(point(ox+transition.x_mm,oy+transition.y_mm));via.SetWidth(pcbnew.FromMM(max(0.6,self.result.spec.trace_width_mm*1.8)));via.SetDrill(pcbnew.FromMM(max(0.3,self.result.spec.trace_width_mm*0.7)))
            via.SetViaType(pcbnew.VIATYPE_THROUGH if {transition.from_layer,transition.to_layer} == {0,copper_count-1} else (pcbnew.VIATYPE_BLIND if {transition.from_layer,transition.to_layer} & {0,copper_count-1} else pcbnew.VIATYPE_BURIED))
            via.SetLayerPair(copper_layer(transition.from_layer,copper_count),copper_layer(transition.to_layer,copper_count))
            if net is not None:via.SetNet(net)
            items.append(via)
        validate_placement(self.board,items,pcbnew)
        if hasattr(pcbnew,"Refresh"):pcbnew.Refresh()
        return items
    def _new_group(self, items, name=""):
        validate_placement(self.board,items,pcbnew)
        return super()._new_group(items,name)

    def _persistent_groups(self):
        return [g for g in getattr(self.board,"Groups",lambda:[])() if str(getattr(g,"GetName",lambda:"")()).startswith("WayriCAD Heater Commit")]
    def _group_items(self,group):
        for name in ("GetItems","GetBoardItems"):
            try:return list(getattr(group,name)())
            except Exception:pass
        return []
    def export_csv(self,_e):
        if not self.result:return
        with wx.FileDialog(self,"Export heater geometry",wildcard="CSV (*.csv)|*.csv",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            with open(d.GetPath(),"w",newline="",encoding="utf-8") as h:w=csv.writer(h);w.writerow(("layer","x1_mm","y1_mm","x2_mm","y2_mm","width_mm","zone"));w.writerows((s.layer,s.x1_mm,s.y1_mm,s.x2_mm,s.y2_mm,s.width_mm,s.zone) for s in self.result.segments)
    def export_json(self,_e):
        if not self.result:return
        with wx.FileDialog(self,"Export heater report",wildcard="JSON (*.json)|*.json",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            payload={"resistance_ohm":self.result.resistance_ohm,"current_a":self.result.current_a,"power_w":self.result.power_w,"zone_power_w":self.result.zone_power_w,"thermal":None if not self.thermal else {"minimum_c":self.thermal.minimum_c,"average_c":self.thermal.average_c,"maximum_c":self.thermal.maximum_c,"uniformity_c":self.thermal.uniformity_c,"notes":self.thermal.notes}};Path(d.GetPath()).write_text(json.dumps(payload,indent=2),encoding="utf-8")
    def on_close(self,event):self.clear_preview(None);event.Skip()
