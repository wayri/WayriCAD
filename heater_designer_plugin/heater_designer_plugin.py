from __future__ import annotations

import csv
import json
import os
import webbrowser
from pathlib import Path

import pcbnew
import wx

from .analysis import (GRADIENT_AXES, ORGANIC_DEFAULT_POINTS, HeatZone, HeaterEngine,
                       HeaterResult, HeaterSpec, ThermalResult, ThermalSpec)
from .guided_ui import add_workflow
from .placement import validate_placement


VERSION = "3.4.0"
PALETTE = ("#157f74", "#d1495b", "#edae49", "#5267a5", "#8f5aa6", "#3c91a3")
ORGANIC_DEFAULT_TEXT = "\n".join(f"{x:g},{y:g}" for x,y in ORGANIC_DEFAULT_POINTS)


def point(x_mm: float, y_mm: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))

def copper_layer(index: int, count: int) -> int:
    if index <= 0: return int(pcbnew.F_Cu)
    if index >= count - 1: return int(pcbnew.B_Cu)
    return int(getattr(pcbnew, f"In{index}_Cu"))


class HeaterPreview(wx.Panel):
    def __init__(self,parent,on_add_zone=None,on_add_path_point=None):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetMinSize((-1, 320)); self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.heater: HeaterResult | None = None; self.thermal: ThermalResult | None = None
        self.mode = "pattern"; self.zoom = 1.0; self.pan = (0,0); self.drag = None
        self.zone_drag = None; self.on_add_zone = on_add_zone
        self.on_add_path_point = on_add_path_point; self.draw_path = False
        self.canvas_spec = None; self.draft_points_percent = ()
        self.Bind(wx.EVT_PAINT,self.paint); self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.pan_start); self.Bind(wx.EVT_LEFT_UP, self.pan_end)
        self.Bind(wx.EVT_MOTION, self.pan_move); self.Bind(wx.EVT_LEFT_DCLICK, self.fit)
        self.Bind(wx.EVT_RIGHT_DOWN, self.zone_start); self.Bind(wx.EVT_RIGHT_UP, self.zone_end)
        self.Bind(wx.EVT_SIZE,self._on_size); self.Bind(wx.EVT_ERASE_BACKGROUND,self._on_erase)

    def _on_size(self,event):self._repaint();event.Skip()
    def _on_erase(self,_event):pass

    def _repaint(self):self.Refresh();self.Update()
    def show_pattern(self,result):
        self.heater=result;self.canvas_spec=result.spec;self.thermal=None;self.mode="pattern";self.draft_points_percent=();self._repaint()
    def show_thermal(self,result):
        self.heater=result.heater;self.canvas_spec=result.heater.spec;self.thermal=result;self.mode="thermal";self._repaint()
    def show_draft(self,spec):
        self.heater=None;self.canvas_spec=spec;self.thermal=None;self.mode="draft"
        self.draft_points_percent=spec.organic_points_percent;self._repaint()
    def wheel(self,event): self.zoom=max(0.5,min(5.0,self.zoom*(1.12 if event.GetWheelRotation()>0 else 0.89)));self._repaint()
    def pan_start(self,event):
        if self.draw_path and self.on_add_path_point:
            xy=self.path_point_from_click(event.GetPosition(),*self.GetClientSize())
            if xy is not None:self.on_add_path_point(xy)
            return
        self.drag=event.GetPosition();self.CaptureMouse()
    def pan_end(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()
    def pan_move(self,event):
        if self.drag is not None and event.Dragging():
            point=event.GetPosition();self.pan=(self.pan[0]+point.x-self.drag.x,self.pan[1]+point.y-self.drag.y);self.drag=point;self._repaint()
        if self.zone_drag is not None and event.RightIsDown():
            self.zone_drag=(self.zone_drag[0],event.GetPosition());self._repaint()
    def fit(self,event=None):self.zoom=1.0;self.pan=(0,0);self._repaint()

    def _transform(self, width, height):
        spec=self.heater.spec if self.heater else self.canvas_spec
        scale=min((width-64)/spec.width_mm,(height-64)/spec.height_mm)*self.zoom
        return scale,(width-spec.width_mm*scale)/2+self.pan[0],(height-spec.height_mm*scale)/2+self.pan[1]

    def path_point_from_click(self, point, width, height):
        if not (self.heater or self.canvas_spec):return None
        spec=self.heater.spec if self.heater else self.canvas_spec
        scale,ox,oy=self._transform(width,height)
        if scale<=0:return None
        x=(point.x-ox)/scale; y=spec.height_mm-(point.y-oy)/scale
        margin=spec.trace_width_mm/2
        if not (margin<=x<=spec.width_mm-margin and margin<=y<=spec.height_mm-margin):return None
        return round(100*x/spec.width_mm,2),round(100*y/spec.height_mm,2)

    def zone_start(self,event):
        if self.heater is None or self.on_add_zone is None:return
        point=event.GetPosition();self.zone_drag=(point,point)
        self.CaptureMouse()

    def zone_end(self,event):
        if self.zone_drag is None:return
        start,_=self.zone_drag;self.zone_drag=None
        if self.HasCapture():self.ReleaseMouse()
        zone=self.zone_from_drag(start,event.GetPosition(),*self.GetClientSize())
        if zone is not None:self.on_add_zone(zone)
        self._repaint()

    def zone_from_drag(self, start, end, width, height):
        """Map a right-dragged circular region into heater coordinates."""
        if self.heater is None:return None
        scale,ox,oy=self._transform(width,height)
        radius_px=((end.x-start.x)**2+(end.y-start.y)**2)**0.5
        if scale<=0 or radius_px<8:return None
        spec=self.heater.spec
        x=max(0.0,min(100.0,(start.x-ox)/scale/spec.width_mm*100))
        y=max(0.0,min(100.0,(spec.height_mm-(start.y-oy)/scale)/spec.height_mm*100))
        radius=max(2.0,min(100.0,radius_px/scale/min(spec.width_mm,spec.height_mm)*100))
        return HeatZone("Region",round(x,1),round(y,1),round(radius,1),1.5)

    def paint(self,_event):
        dc=wx.AutoBufferedPaintDC(self)
        self.draw(dc, *self.GetClientSize())

    def draw(self, dc, w, h):
        """Render to a paint or memory DC so the preview can be checked offscreen."""
        dc.SetBackground(wx.Brush("#f7f9fb"));dc.Clear()
        if w<48 or h<48:return
        if not self.heater and not self.canvas_spec:
            dc.SetTextForeground("#52616b");dc.DrawLabel("Generate a heater to inspect exact copper geometry and zoned power.",wx.Rect(10,10,w-20,h-20),wx.ALIGN_CENTER);return
        spec=self.heater.spec if self.heater else self.canvas_spec;scale,ox,oy=self._transform(w,h)
        project=lambda x,y:(int(ox+x*scale),int(oy+(spec.height_mm-y)*scale))
        x1,y1=project(0,spec.height_mm);x2,y2=project(spec.width_mm,0)
        # Paint the board before copper. On some Windows DCs the rectangle's
        # brush fills its interior even when a transparent brush was requested.
        dc.SetPen(wx.Pen("#263744",2));dc.SetBrush(wx.Brush("#f7f9fb"))
        dc.DrawRectangle(x1,y1,x2-x1,y2-y1)
        if self.mode=="draft":
            points=[project(spec.width_mm*x/100,spec.height_mm*y/100)
                    for x,y in self.draft_points_percent]
            dc.SetPen(wx.Pen("#d77b19",2,wx.PENSTYLE_DOT))
            for a,b in zip(points,points[1:]):dc.DrawLine(*a,*b)
            for index,(x,y) in enumerate(points,1):
                dc.SetBrush(wx.Brush("#d77b19"));dc.DrawCircle(x,y,5)
                dc.SetTextForeground("#603c16");dc.DrawText(str(index),x+6,y-6)
            dc.SetTextForeground("#263744")
            dc.DrawText("Organic path draft · click to add control points · Preview after 3 points",12,10)
            return
        if self.mode=="thermal" and self.thermal:
            grid=self.thermal.temperatures_c;lo=self.thermal.minimum_c;span=max(self.thermal.maximum_c-lo,1e-6);ny=len(grid);nx=len(grid[0])
            for iy,row in enumerate(grid):
                for ix,value in enumerate(row):
                    t=(value-lo)/span;color=wx.Colour(int(35+220*t),int(105+90*(1-t)),int(220*(1-t)))
                    x1,y1=project(ix*spec.width_mm/nx,(iy+1)*spec.height_mm/ny);x2,y2=project((ix+1)*spec.width_mm/nx,iy*spec.height_mm/ny);dc.SetPen(wx.Pen(color));dc.SetBrush(wx.Brush(color));dc.DrawRectangle(min(x1,x2),min(y1,y2),abs(x2-x1)+1,abs(y2-y1)+1)
        zones={"Uniform":"#157f74"}
        for zone in spec.zones:
            zones.setdefault(zone.name,PALETTE[len(zones)%len(PALETTE)])
            cx,cy=project(spec.width_mm*zone.x_percent/100,spec.height_mm*zone.y_percent/100)
            radius=round(min(spec.width_mm,spec.height_mm)*zone.radius_percent/100*scale)
            dc.SetPen(wx.Pen(zones[zone.name],1,wx.PENSTYLE_DOT))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawCircle(cx,cy,max(1,radius))
            dc.SetTextForeground(zones[zone.name]);dc.DrawText(f"{zone.name} ×{zone.resistance_factor:g}",cx+5,cy-max(14,radius))
        for segment in self.heater.segments:
            zones.setdefault(segment.zone,PALETTE[len(zones)%len(PALETTE)]);dc.SetPen(wx.Pen(zones[segment.zone],max(2,int(segment.width_mm*scale))));dc.DrawLine(*project(segment.x1_mm,segment.y1_mm),*project(segment.x2_mm,segment.y2_mm))
        for via in self.heater.vias:
            radius=max(0.6,spec.trace_width_mm*1.8)*scale/2;drill=max(0.3,spec.trace_width_mm*0.7)*scale/2
            dc.SetBrush(wx.Brush("#ac7c26"));dc.SetPen(wx.Pen("#674d00",1));dc.DrawCircle(*project(via.x_mm,via.y_mm),max(1,round(radius)))
            dc.SetBrush(wx.Brush("#f7f9fb"));dc.SetPen(wx.TRANSPARENT_PEN);dc.DrawCircle(*project(via.x_mm,via.y_mm),max(1,round(drill)))
        if spec.pattern=="Organic path":
            for index,(x,y) in enumerate(spec.organic_points_percent,1):
                px,py=project(spec.width_mm*x/100,spec.height_mm*y/100)
                dc.SetPen(wx.Pen("#d77b19",1));dc.SetBrush(wx.Brush("#fff2d8"));dc.DrawCircle(px,py,4)
                dc.SetTextForeground("#603c16");dc.DrawText(str(index),px+5,py-5)
        if self.thermal:
            for marker in self.thermal.sensors:
                px,py=project(marker.x_mm,marker.y_mm)
                colour="#af2e45" if marker.kind=="PTC" else "#2865b0"
                dc.SetPen(wx.Pen("#ffffff",2));dc.SetBrush(wx.Brush(colour));dc.DrawCircle(px,py,9)
                dc.SetTextForeground("#ffffff");dc.DrawText(marker.kind[0],px-4,py-7)
                dc.SetTextForeground(colour)
                dc.DrawText(f"{marker.kind} {marker.estimated_c:.1f}°C",px+12,py-7)
        if self.zone_drag is not None:
            start,end=self.zone_drag
            radius=round(((end.x-start.x)**2+(end.y-start.y)**2)**0.5)
            dc.SetPen(wx.Pen("#ed8b28",2,wx.PENSTYLE_DOT));dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawCircle(start.x,start.y,max(1,radius))
        label=f"{self.mode.title()} | {self.heater.resistance_ohm:.3f} ohm | {self.heater.current_a:.2f} A | {self.heater.power_w:.2f} W | wheel: zoom"
        dc.SetTextForeground("#263744");dc.DrawText(label,12,10)
        if self.thermal and spec.gradient_axis!="Uniform":
            dc.DrawText(f"{spec.gradient_axis} heat bias ×{spec.gradient_ratio:.3f} · estimated hot−cool {self.thermal.gradient_delta_c:+.1f}°C",12,29)
        dc.DrawText(f"{spec.width_mm:g} mm × {spec.height_mm:g} mm · {spec.pattern} · {spec.layers} layer(s) · right-drag: add region",12,h-22)


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
        super().__init__(parent,title="WayriCAD PCB / Foil Heater Designer",size=(1280,850));self.SetIcon(wx.Icon(str(Path(__file__).with_name("resources") / "icon-48.png"), wx.BITMAP_TYPE_PNG));self.SetMinSize((1040,720));self.board=board;self.result=None;self.thermal=None;self.preview_items=[];self.undo_stack=[];self.redo_stack=[];self._build();self.undo_stack=self._persistent_groups();self.Bind(wx.EVT_CLOSE,self.on_close);self.Centre()
    def _settings_signature(self):
        return super()._settings_signature() + (("heating_regions", self.zones.GetValue()),
                                                ("organic_points", self.organic_points.GetValue()),
                                                ("gradient_axis", self.gradient_axis.GetStringSelection()),
                                                ("gradient_ratio", self.gradient_ratio.GetValue()),
                                                ("target_gradient", self.thermal_fields['target'].GetValue()),
                                                ("sensor_keepaway", self.thermal_fields['sensor_clearance'].GetValue()))
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
        self.pattern = choice(geometry, grid, "Pattern", ["Serpentine", "Concentric spiral", "Zoned raster", "Organic path"])
        self.gradient_axis = choice(geometry, grid, "Heat-bias direction", GRADIENT_AXES)
        self.gradient_ratio = field(geometry, grid, "Directional heat bias (0.5–4)", 1.0)
        for label, key, value in (("Copper layers","layers",1),("Origin X (mm)","origin_x",20),("Origin Y (mm)","origin_y",20)):
            self.fields[key] = field(placement, placement_grid, label, value)
        self.net = choice(placement, placement_grid, "Net", ["<no net>"] + self._net_names())
        self.thermal_fields = {}
        for label,key,value in (("Ambient (°C)","ambient",25),("In-plane k (W/mK)","k",0.30),
                                 ("Thickness (mm)","thickness",1.6),("Convection (W/m²K)","h",10),
                                 ("Grid X","gx",42),("Grid Y","gy",28),
                                 ("Target hot−cool (°C, 0=off)","target",0),
                                 ("Sensor copper keepaway (mm)","sensor_clearance",0.1)):
            self.thermal_fields[key] = field(thermal, thermal_grid, label, value)
        organic_layout = wx.StaticBoxSizer(wx.VERTICAL, geometry, "Organic path")
        geometry_layout.Add(organic_layout, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        organic_parent = organic_layout.GetStaticBox()
        organic_hint = wx.StaticText(organic_parent, label="Ordered X%,Y% control points. Choose Organic path to edit this smooth series route, or clear points and click the preview to draw your own.")
        organic_hint.Wrap(275)
        organic_layout.Add(organic_hint, 0, wx.ALL, 6)
        self.organic_points = wx.TextCtrl(organic_parent,value=ORGANIC_DEFAULT_TEXT,style=wx.TE_MULTILINE)
        self.organic_points.SetMinSize((-1,105))
        organic_layout.Add(self.organic_points, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        organic_actions=wx.BoxSizer(wx.HORIZONTAL)
        self.draw_path_button=wx.ToggleButton(organic_parent,label="Draw path on preview")
        self.draw_path_button.Bind(wx.EVT_TOGGLEBUTTON,self.toggle_path_drawing)
        organic_actions.Add(self.draw_path_button,1,wx.RIGHT,5)
        clear_path=wx.Button(organic_parent,label="Clear points")
        clear_path.Bind(wx.EVT_BUTTON,self.clear_path_points)
        organic_actions.Add(clear_path,0)
        organic_layout.Add(organic_actions,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        zone_layout = wx.StaticBoxSizer(wx.VERTICAL, geometry, "Heating regions")
        geometry_layout.Add(zone_layout, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        zone_parent = zone_layout.GetStaticBox()
        hint = wx.StaticText(zone_parent, label="One region per line: name, X%, Y%, radius%, resistance factor. Above 1 narrows the trace and raises local heating.")
        hint.Wrap(275)
        zone_layout.Add(hint, 0, wx.ALL, 6)
        self.zones = wx.TextCtrl(zone_parent, value="Hotspot,50,50,18,1.8\nCold edge,10,50,12,0.65", style=wx.TE_MULTILINE)
        self.zones.SetMinSize((-1,90))
        zone_layout.Add(self.zones, 0, wx.EXPAND | wx.ALL, 6)
        body.Add(controls, 0, wx.EXPAND | wx.RIGHT, 14)
        right = wx.BoxSizer(wx.VERTICAL)
        self.preview = HeaterPreview(panel,self.add_region,self.add_path_point)
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
        for label, handler in (("Preview",self.generate),("Simulate / tune",self.simulate),("Apply to PCB",self.commit)):
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
    def add_region(self,zone):
        names={existing.name for existing in self._zones()}
        index=1
        while f"Region {index}" in names:index+=1
        value=self.zones.GetValue().strip()
        line=f"Region {index},{zone.x_percent:g},{zone.y_percent:g},{zone.radius_percent:g},{zone.resistance_factor:g}"
        self.zones.SetValue(f"{value}\n{line}" if value else line)
        self.generate(None)
    def _organic_points(self):
        points=[]
        for line in self.organic_points.GetValue().splitlines():
            if not line.strip():continue
            values=[part.strip() for part in line.split(",")]
            if len(values)!=2:raise ValueError("Enter one organic point per line as X%,Y%.")
            points.append((float(values[0]),float(values[1])))
        return tuple(points)
    def toggle_path_drawing(self,_event):
        self.preview.draw_path=self.draw_path_button.GetValue()
        if self.preview.draw_path:
            if self.organic_points.GetValue().strip()==ORGANIC_DEFAULT_TEXT:
                self.clear_path_points(None)
            self.pattern.SetStringSelection("Organic path")
            self.status.SetLabel("Click the preview to add organic path points. Right-drag still adds a heating region.")
    def clear_path_points(self,_event):
        self.pattern.SetStringSelection("Organic path")
        self.organic_points.SetValue("")
        self.result=None;self.thermal=None;self.clear_preview(None)
        self.preview.show_draft(self._spec())
        self.draw_path_button.SetValue(True);self.preview.draw_path=True
        self.status.SetLabel("Organic path cleared. Click at least three points in the preview, then Preview.")
    def add_path_point(self,xy):
        x,y=xy
        value=self.organic_points.GetValue().strip()
        self.organic_points.SetValue(f"{value}\n{x:g},{y:g}" if value else f"{x:g},{y:g}")
        points=self._organic_points()
        self.preview.show_draft(self._spec())
        if len(points)>=3:
            self.generate(None,quiet=True)
        else:
            self.status.SetLabel(f"Organic path: {len(points)} point(s). Add at least three.")
    def _spec(self):
        f=self.fields;return HeaterSpec(float(f['width'].GetValue()),float(f['height'].GetValue()),float(f['trace'].GetValue()),float(f['spacing'].GetValue()),float(f['copper'].GetValue()),float(f['voltage'].GetValue()),int(f['layers'].GetValue()),self.pattern.GetStringSelection(),self._zones(),self._organic_points(),self.gradient_axis.GetStringSelection(),float(self.gradient_ratio.GetValue()))
    def generate(self,_e,*,quiet=False):
        draft=None
        try:
            self.clear_preview(None);self.thermal=None;self.result=None
            draft=self._spec();self.result=HeaterEngine.generate(draft)
            self.preview.show_pattern(self.result);self._metrics()
            self.status.SetLabel(f"Preview: {len(self.result.segments)} segments and {len(self.result.vias)} layer transitions. PCB unchanged.")
            self.guide.set_step(1,"Review the path, heat-bias widths and electrical loading; then simulate before applying.")
            self._capture_review()
            return True
        except Exception as exc:
            self.result=None;self.thermal=None;self._review_board=None
            if quiet and draft is not None:
                self.preview.show_draft(draft)
                self.status.SetLabel(str(exc)+" Add or move a point, then preview again.")
            else:
                self.preview.heater=None;self.preview.canvas_spec=None;self.preview._repaint()
                wx.MessageBox(str(exc),"Heater generation failed",wx.OK|wx.ICON_ERROR)
            return False
    def simulate(self,_e):
        try:
            self.generate(None)
            if not self.result:return
            f=self.thermal_fields;spec=ThermalSpec(float(f['ambient'].GetValue()),float(f['k'].GetValue()),float(f['thickness'].GetValue()),float(f['h'].GetValue()),int(f['gx'].GetValue()),int(f['gy'].GetValue()),sensor_clearance_mm=float(f['sensor_clearance'].GetValue()))
            target=float(f['target'].GetValue())
            if target<0:raise ValueError("Target hot−cool difference cannot be negative.")
            if target>0:
                self.thermal=HeaterEngine.tune_gradient(self._spec(),spec,target)
                self.result=self.thermal.heater
                self.gradient_ratio.SetValue(f"{self.result.spec.gradient_ratio:.6f}")
            else:self.thermal=HeaterEngine.simulate(self.result,spec)
            self.clear_preview(None);self._capture_review()
            self.preview.show_thermal(self.thermal);self._metrics()
            warning=" · predicted temperature exceeds 180°C" if self.thermal.maximum_c>180 else ""
            self.status.SetLabel(f"Model: hot−cool {self.thermal.gradient_delta_c:+.1f}°C; {len(self.thermal.sensors)} sensor marker(s){warning}. PCB unchanged.")
            self.guide.set_step(2,"Review the model gradient, sensor markers and temperature limits before applying copper.")
        except Exception as exc:wx.MessageBox(str(exc),"Thermal simulation failed",wx.OK|wx.ICON_ERROR)
    def _metrics(self):
        self.metrics.DeleteAllItems();r=self.result;rows=[("Resistance",f"{r.resistance_ohm:.4f} ohm","20 C copper estimate"),("Current",f"{r.current_a:.3f} A","Check connector, supply, and copper current limits"),("Power",f"{r.power_w:.3f} W",f"{r.watts_per_cm2:.3f} W/cm2"),("Layers / vias",f"{r.spec.layers} / {len(r.vias)}","Series-connected copper layers")]
        if self.thermal:
            rows.extend((("Temperature min / avg / max",f"{self.thermal.minimum_c:.1f} / {self.thermal.average_c:.1f} / {self.thermal.maximum_c:.1f} C","Reduced-order steady-state estimate"),("Thermal nonuniformity",f"{self.thermal.uniformity_c:.1f} C","Max minus min across model grid")))
            if r.spec.gradient_axis!="Uniform":
                rows.append(("Directional hot−cool",f"{self.thermal.gradient_delta_c:+.1f} °C",f"{r.spec.gradient_axis}; target {self.thermal_fields['target'].GetValue()} °C"))
            ox=float(self.fields['origin_x'].GetValue());oy=float(self.fields['origin_y'].GetValue())
            for marker in self.thermal.sensors:
                rows.append((f"{marker.kind} {marker.role}",f"{ox+marker.x_mm:.1f}, {oy+marker.y_mm:.1f} mm",
                             f"PCB coordinate · model {marker.estimated_c:.1f} °C · copper gap {marker.copper_clearance_mm:.2f} mm"))
            if self.thermal.maximum_c>180:
                rows.append(("Temperature warning",">180 °C","Outside safe design range; revise power/materials"))
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
            origin=(float(self.fields['origin_x'].GetValue()),float(self.fields['origin_y'].GetValue()))
            markers=[] if not self.thermal else [{"kind":m.kind,"role":m.role,"local_x_mm":m.x_mm,"local_y_mm":m.y_mm,"pcb_x_mm":origin[0]+m.x_mm,"pcb_y_mm":origin[1]+m.y_mm,"estimated_c":m.estimated_c,"copper_clearance_mm":m.copper_clearance_mm} for m in self.thermal.sensors]
            payload={"resistance_ohm":self.result.resistance_ohm,"current_a":self.result.current_a,"power_w":self.result.power_w,"zone_power_w":self.result.zone_power_w,"pattern":self.result.spec.pattern,"organic_points_percent":self.result.spec.organic_points_percent if self.result.spec.pattern=="Organic path" else [],"gradient_axis":self.result.spec.gradient_axis,"gradient_ratio":self.result.spec.gradient_ratio,"sensor_markers":markers,"thermal":None if not self.thermal else {"minimum_c":self.thermal.minimum_c,"average_c":self.thermal.average_c,"maximum_c":self.thermal.maximum_c,"uniformity_c":self.thermal.uniformity_c,"directional_hot_minus_cool_c":self.thermal.gradient_delta_c,"notes":self.thermal.notes}};Path(d.GetPath()).write_text(json.dumps(payload,indent=2),encoding="utf-8")
    def on_close(self,event):self.clear_preview(None);event.Skip()
