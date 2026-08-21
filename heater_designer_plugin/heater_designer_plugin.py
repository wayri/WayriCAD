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


VERSION = "0.1.2"
PALETTE = ("#157f74", "#d1495b", "#edae49", "#5267a5", "#8f5aa6", "#3c91a3")


def point(x_mm: float, y_mm: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))

def copper_layer(index: int, count: int) -> int:
    if index <= 0: return int(pcbnew.F_Cu)
    if index >= count - 1: return int(pcbnew.B_Cu)
    return index


class HeaterPreview(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetMinSize((-1, 320)); self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.heater: HeaterResult | None = None; self.thermal: ThermalResult | None = None
        self.mode = "pattern"; self.zoom = 1.0; self.Bind(wx.EVT_PAINT,self.paint); self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_SIZE,self._on_size); self.Bind(wx.EVT_ERASE_BACKGROUND,self._on_erase)

    def _on_size(self,event):self._repaint();event.Skip()
    def _on_erase(self,_event):pass

    def _repaint(self):self.Refresh();self.Update()
    def show_pattern(self,result): self.heater=result; self.thermal=None; self.mode="pattern"; self._repaint()
    def show_thermal(self,result): self.heater=result.heater; self.thermal=result; self.mode="thermal"; self._repaint()
    def wheel(self,event): self.zoom=max(0.5,min(5.0,self.zoom*(1.12 if event.GetWheelRotation()>0 else 0.89)));self._repaint()

    def paint(self,_event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush("#f7f9fb"));dc.Clear();w,h=self.GetClientSize()
        if w<48 or h<48:return
        if not self.heater:
            dc.SetTextForeground("#52616b");dc.DrawLabel("Generate a heater to inspect exact copper geometry and zoned power.",wx.Rect(10,10,w-20,h-20),wx.ALIGN_CENTER);return
        margin=32;spec=self.heater.spec;scale=min((w-2*margin)/spec.width_mm,(h-2*margin)/spec.height_mm)*self.zoom
        ox=(w-spec.width_mm*scale)/2;oy=(h-spec.height_mm*scale)/2
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
            dc.SetBrush(wx.Brush("#f6c453"));dc.SetPen(wx.Pen("#674d00",2));dc.DrawCircle(*project(via.x_mm,via.y_mm),5)
        dc.SetPen(wx.Pen("#263744",2));dc.SetBrush(wx.TRANSPARENT_BRUSH);x1,y1=project(0,spec.height_mm);x2,y2=project(spec.width_mm,0);dc.DrawRectangle(x1,y1,x2-x1,y2-y1)
        label=f"{self.mode.title()} | {self.heater.resistance_ohm:.3f} ohm | {self.heater.current_a:.2f} A | {self.heater.power_w:.2f} W | wheel: zoom"
        dc.SetTextForeground("#263744");dc.DrawText(label,12,10)


class HeaterDesignerPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name="KiWay PCB / Foil Heater Designer";self.category="PCB Engineering";self.description="Design zoned PCB heaters and simulate thermal patterns.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"icon.png");self.dark_icon_file_name=self.icon_file_name;self.version=VERSION
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None: wx.MessageBox("Open a PCB first.",self.name,wx.OK|wx.ICON_ERROR);return
        HeaterFrame(None,board).Show()


class HeaterFrame(wx.Frame):
    def __init__(self,parent,board):
        super().__init__(parent,title="KiWay PCB / Foil Heater Designer",size=(1280,850));self.SetMinSize((1040,720));self.board=board;self.result=None;self.thermal=None;self.preview_items=[];self.undo_stack=[];self.redo_stack=[];self._build();self.undo_stack=self._persistent_groups();self.Bind(wx.EVT_CLOSE,self.on_close);self.Centre()
    def _build(self):
        p=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL);self.guide=add_workflow(p,root,"PCB / Foil Heater Designer","Synthesize variable-resistance copper, review local power density, simulate the board temperature field, then commit only the accepted pattern.",( "Configure","Copper preview","Thermal review","PCB commit"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()))
        body=wx.BoxSizer(wx.HORIZONTAL);left=wx.BoxSizer(wx.VERTICAL);box=wx.StaticBoxSizer(wx.VERTICAL,p,"Heater Definition");bp=box.GetStaticBox();grid=wx.FlexGridSizer(0,2,6,8);grid.AddGrowableCol(1,1);self.fields={}
        for label,key,value in (("Area width (mm)","width","80"),("Area height (mm)","height","50"),("Base trace width (mm)","trace","0.5"),("Trace spacing (mm)","spacing","0.5"),("Copper thickness (um)","copper","35"),("Supply voltage (V)","voltage","12"),("Copper layers","layers","1"),("Origin X (mm)","origin_x","20"),("Origin Y (mm)","origin_y","20")):
            c=wx.TextCtrl(bp,value=value);self.fields[key]=c;grid.Add(wx.StaticText(bp,label=label),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(c,1,wx.EXPAND)
        self.pattern=wx.Choice(bp,choices=["Serpentine","Concentric spiral","Zoned raster"]);self.pattern.SetSelection(0);grid.Add(wx.StaticText(bp,label="Pattern family"));grid.Add(self.pattern,1,wx.EXPAND)
        self.net=wx.ComboBox(bp,choices=["<no net>"]+self._net_names(),style=wx.CB_READONLY);self.net.SetSelection(0);grid.Add(wx.StaticText(bp,label="Electrical net"));grid.Add(self.net,1,wx.EXPAND);box.Add(grid,0,wx.EXPAND|wx.ALL,10)
        box.Add(wx.StaticText(bp,label="Thermal zones: name, X%, Y%, radius%, resistance factor; one per line"),0,wx.LEFT|wx.RIGHT|wx.TOP,10);self.zones=wx.TextCtrl(bp,value="Hotspot,50,50,18,1.8\nCold edge,10,50,12,0.65",style=wx.TE_MULTILINE);self.zones.SetMinSize((-1,70));box.Add(self.zones,0,wx.EXPAND|wx.ALL,10);left.Add(box,0,wx.EXPAND)
        thermal_box=wx.StaticBoxSizer(wx.VERTICAL,p,"Thermal Model");tp=thermal_box.GetStaticBox();tg=wx.FlexGridSizer(0,2,6,8);tg.AddGrowableCol(1,1);self.thermal_fields={}
        for label,key,value in (("Ambient (C)","ambient","25"),("Board in-plane k (W/mK)","k","0.30"),("Board thickness (mm)","thickness","1.6"),("Convection (W/m2K)","h","10"),("Grid X","gx","42"),("Grid Y","gy","28")):
            c=wx.TextCtrl(tp,value=value);self.thermal_fields[key]=c;tg.Add(wx.StaticText(tp,label=label));tg.Add(c,1,wx.EXPAND)
        thermal_box.Add(tg,0,wx.EXPAND|wx.ALL,10);left.Add(thermal_box,0,wx.EXPAND|wx.TOP,8)
        generate=wx.Button(p,label="Generate Copper Preview");generate.SetDefault();generate.Bind(wx.EVT_BUTTON,self.generate);simulate=wx.Button(p,label="Run Thermal Simulation");simulate.Bind(wx.EVT_BUTTON,self.simulate);left.Add(generate,0,wx.EXPAND|wx.TOP,10);left.Add(simulate,0,wx.EXPAND|wx.TOP,6);body.Add(left,0,wx.EXPAND|wx.ALL,10)
        right=wx.BoxSizer(wx.VERTICAL);self.preview=HeaterPreview(p);right.Add(self.preview,1,wx.EXPAND);self.metrics=wx.ListCtrl(p,style=wx.LC_REPORT);self.metrics.InsertColumn(0,"Metric",width=240);self.metrics.InsertColumn(1,"Value",width=280);self.metrics.InsertColumn(2,"Engineering note",width=480);right.Add(self.metrics,0,wx.EXPAND|wx.TOP,8)
        buttons=wx.BoxSizer(wx.HORIZONTAL)
        for label,handler in (("Show on PCB",self.show_pcb),("Clear PCB Preview",self.clear_preview),("Commit to PCB",self.commit),("Undo Commit",self.undo),("Redo Commit",self.redo),("Export CSV...",self.export_csv),("Export JSON...",self.export_json)):
            b=wx.Button(p,label=label);b.Bind(wx.EVT_BUTTON,handler);buttons.Add(b,0,wx.RIGHT,6)
        right.Add(buttons,0,wx.TOP,8);body.Add(right,1,wx.EXPAND|wx.ALL,10);root.Add(body,1,wx.EXPAND);self.status=wx.StaticText(p,label="No generated heater. The PCB has not been changed.");root.Add(self.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10);p.SetSizer(root)
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
        try:self.clear_preview(None);self.result=HeaterEngine.generate(self._spec());self.preview.show_pattern(self.result);self._metrics();self.status.SetLabel(f"Preview: {len(self.result.segments)} segments and {len(self.result.vias)} layer transitions. PCB unchanged.");self.guide.set_step(1,"Review width-coded zones and electrical loading, then run the thermal simulation.")
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
            self.board.Add(track);items.append(track)
        for transition in self.result.vias:
            via=pcbnew.PCB_VIA(self.board);via.SetPosition(point(ox+transition.x_mm,oy+transition.y_mm));via.SetWidth(pcbnew.FromMM(max(0.6,self.result.spec.trace_width_mm*1.8)));via.SetDrill(pcbnew.FromMM(max(0.3,self.result.spec.trace_width_mm*0.7)))
            if hasattr(via,"SetLayerPair"):via.SetLayerPair(copper_layer(transition.from_layer,copper_count),copper_layer(transition.to_layer,copper_count))
            if net is not None:via.SetNet(net)
            self.board.Add(via);items.append(via)
        if hasattr(pcbnew,"Refresh"):pcbnew.Refresh()
        return items
    def show_pcb(self,_e):
        if not self.result:wx.MessageBox("Generate and review a heater first.","Preview required",wx.OK|wx.ICON_INFORMATION);return
        try:self.clear_preview(None);self.preview_items=self._board_items();self.status.SetLabel(f"Temporary PCB preview: {len(self.preview_items)} items. Commit or clear before closing.");self.guide.set_step(3,"Inspect clearances and DRC context, then commit the named group or clear the preview.")
        except Exception as exc:wx.MessageBox(str(exc),"PCB preview failed",wx.OK|wx.ICON_ERROR)
    def clear_preview(self,_e):
        for item in self.preview_items:
            try:self.board.Remove(item)
            except Exception:pass
        self.preview_items=[]
        if hasattr(pcbnew,"Refresh"):pcbnew.Refresh()
    def commit(self,_e):
        if not self.preview_items:wx.MessageBox("Show the reviewed heater on the PCB before committing.","PCB preview required",wx.OK|wx.ICON_INFORMATION);return
        items=list(self.preview_items);self.preview_items=[]
        group=self._new_group(items);self.undo_stack.append(group);self.redo_stack.clear()
        self.status.SetLabel(f"Committed {len(items)} items. Run DRC and electro-thermal validation before fabrication.")
    def _persistent_groups(self):
        return [g for g in getattr(self.board,"Groups",lambda:[])() if str(getattr(g,"GetName",lambda:"")()).startswith("KiWay Heater Commit")]
    def _group_items(self,group):
        for name in ("GetItems","GetBoardItems"):
            try:return list(getattr(group,name)())
            except Exception:pass
        return []
    def _new_group(self,items,name=""):
        if not hasattr(pcbnew,"PCB_GROUP"):return list(items)
        group=pcbnew.PCB_GROUP(self.board);group.SetName(name or f"KiWay Heater Commit {len(self._persistent_groups())+1:03d}");self.board.Add(group)
        for item in items:group.AddItem(item)
        return group
    def undo(self,_e):
        if not self.undo_stack:self.status.SetLabel("No KiWay heater commit to undo.");return
        entry=self.undo_stack.pop();items=list(entry) if isinstance(entry,list) else self._group_items(entry);name="KiWay Heater Commit" if isinstance(entry,list) else str(entry.GetName())
        if not isinstance(entry,list):
            for item in items:
                try:entry.RemoveItem(item)
                except Exception:pass
            try:self.board.Remove(entry)
            except Exception:pass
        for item in items:
            try:self.board.Remove(item)
            except Exception:pass
        self.redo_stack.append((name,items));self.status.SetLabel(f"Undid heater commit containing {len(items)} items.");pcbnew.Refresh()
    def redo(self,_e):
        if not self.redo_stack:self.status.SetLabel("No KiWay heater commit to redo.");return
        name,items=self.redo_stack.pop()
        for item in items:self.board.Add(item)
        self.undo_stack.append(self._new_group(items,name));self.status.SetLabel(f"Redid heater commit containing {len(items)} items.");pcbnew.Refresh()
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
