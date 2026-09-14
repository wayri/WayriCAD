from __future__ import annotations
import csv,fnmatch,os,webbrowser
from pathlib import Path
import pcbnew,wx
from .analysis import PadNode,analyze_decoupling,infer_regulators
from .guided_ui import add_workflow, mark_primary, section
from .preview_kit import PanZoomCanvas, add_zoom_toolbar, severity_colour, pcb_select_items, pcb_highlight_net

STATUS_COLOURS={"PASS":"#3fa56b","WARN":"#d4a62a","FAIL":"#e34a43","INFO":"#3399cc"}
ROLE_COLOURS={"rail":"#3fa56b","ground":"#e34a43","load":"#d4a62a","capacitor":"#3399cc","other":"#8fa5b8"}

def make_sortable(table):
    state={"column":0,"reverse":False}
    def sort(event):
        column=event.GetColumn();state["reverse"]=not state["reverse"] if column==state["column"] else False;state["column"]=column;rows=[[table.GetItemText(r,c) for c in range(table.GetColumnCount())] for r in range(table.GetItemCount())];rows.sort(key=lambda row:row[column].casefold(),reverse=state["reverse"]);table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);[table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)]
    table.Bind(wx.EVT_LIST_COL_CLICK,sort)

class PdnMapPreview(PanZoomCanvas):
    """Placement map of rails, ground, loads, capacitors, and flagged pins."""
    def __init__(self,parent):
        super().__init__(parent,empty_text="Analyze the PDN to preview rail, ground, load, and decoupling placement.")
        self.nodes=[];self.flagged=set()
    def load(self,pads,findings,rails,grounds,loads,caps):
        def matches(net,patterns):return any(fnmatch.fnmatch(net,p.strip()) for p in patterns.split(",") if p.strip())
        self.nodes=[]
        for p in pads:
            net=p.net or ""
            role="other"
            if matches(net,grounds):role="ground"
            elif matches(net,rails):role="rail"
            elif fnmatch.fnmatch(p.reference,caps):role="capacitor"
            elif fnmatch.fnmatch(p.reference,loads):role="load"
            self.nodes.append((role,(p.x_mm,p.y_mm),f"{p.reference}.{p.pad}",p.net))
        self.flagged={item.load for item in findings if getattr(item,"severity","").upper()=="FAIL" and getattr(item,"load","")}
        self.set_legend([(ROLE_COLOURS[name],name) for name in ("rail","ground","load","capacitor")]+[(STATUS_COLOURS["FAIL"],"failed pin")])
        self.set_picks([{"x":node[1][0],"y":node[1][1],"r":0.8,"data":(node[2],node[3])} for node in self.nodes])
        self.Refresh();self.fit()
    def scene_bounds(self):
        if not self.nodes:return None
        xs=[node[1][0] for node in self.nodes];ys=[node[1][1] for node in self.nodes]
        return (min(xs),min(ys),max(xs),max(ys))
    def draw_scene(self,gc,project):
        gc.SetFont(wx.Font(8,wx.FONTFAMILY_DEFAULT,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_NORMAL),"#aab7c4")
        for node in self.nodes:
            role,(x,y),label,_net=node
            sx,sy=project((x,y));colour=wx.Colour(ROLE_COLOURS.get(role,ROLE_COLOURS["other"]))
            gc.SetPen(wx.Pen(colour,1));gc.SetBrush(wx.Brush(colour))
            size=10 if role!="capacitor" else 7
            if role=="capacitor":gc.DrawRectangle(sx-size/2,sy-size/2,size,size)
            else:gc.DrawEllipse(sx-size/2,sy-size/2,size,size)
            if label in self.flagged:
                gc.SetPen(wx.Pen(wx.Colour(STATUS_COLOURS["FAIL"]),2));gc.SetBrush(wx.TRANSPARENT_BRUSH);gc.DrawEllipse(sx-9,sy-9,18,18)

class PdnDecouplingPlugin(pcbnew.ActionPlugin):
    def defaults(self):self.name="WayriCAD PDN and Decoupling Planner";self.category="Analysis";self.description="Audit power-rail topology and local decoupling placement.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"resources","icon-24.png");self.dark_icon_file_name=self.icon_file_name.replace("icon-24.png", "icon-dark-24.png");self.version="3.0.0"
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:return
        PdnFrame(None,board).Show()
class PdnFrame(wx.Frame):
    def __init__(self,parent,board):super().__init__(parent,title="WayriCAD PDN and Decoupling Planner",size=(1150,760));self.board=board;self.findings=[];self._build();self.Centre()
    def _build(self):
        p=wx.Panel(self);r=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,r,"PDN and Decoupling Planner","Qualify rail-to-ground capacitors, check load proximity, and review regulator candidates without changing placement.",("Classify","Analyze","Review","Export"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()))
        settings_box=section(p,"Rail Classification and Placement Limits")
        settings_parent=settings_box.GetStaticBox()
        g=wx.FlexGridSizer(2,6,7,8);g.AddGrowableCol(1,1);g.AddGrowableCol(3,1);self.rails=wx.TextCtrl(settings_parent,value="VCC*,VDD*,VBAT*,*VOUT*,+*V,3V*,5V*,12V*");self.ground=wx.TextCtrl(settings_parent,value="GND*,AGND*,DGND*,PGND*,VSS*");self.distance=wx.TextCtrl(settings_parent,value="3.0");self.loads=wx.TextCtrl(settings_parent,value="U*")
        for label,c in (("Rail patterns",self.rails),("Ground patterns",self.ground),("Maximum capacitor distance (mm)",self.distance),("Load references",self.loads)):g.Add(wx.StaticText(settings_parent,label=label));g.Add(c,1,wx.EXPAND)
        a=mark_primary(wx.Button(settings_parent,label="Analyze PDN"),"Analyze power pins and nearby valid decoupling capacitors");a.Bind(wx.EVT_BUTTON,self.analyze);g.Add(a);self.summary=wx.StaticText(settings_parent,label="No analysis yet.");g.Add(self.summary,1,wx.ALIGN_CENTER_VERTICAL);        settings_box.Add(g,1,wx.EXPAND|wx.ALL,8);r.Add(settings_box,0,wx.EXPAND|wx.ALL,10)
        split=wx.SplitterWindow(p);left=wx.Panel(split);right=wx.Panel(split);ls=wx.BoxSizer(wx.VERTICAL);rs=wx.BoxSizer(wx.VERTICAL)
        self.table=wx.ListCtrl(left,style=wx.LC_REPORT);[(self.table.InsertColumn(i,name,width=width)) for i,(name,width) in enumerate((("Severity",90),("Rail",160),("Load pin",140),("Check",190),("Evidence",500)))];self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED,self.select);ls.Add(self.table,1,wx.EXPAND);left.SetSizer(ls)
        self.preview=PdnMapPreview(right);self.preview.on_pick=self.on_map_pick;rs.Add(self.preview,1,wx.EXPAND);add_zoom_toolbar(right,self.preview,rs);self.map_summary=wx.StaticText(right,label="Placement map appears after analysis.");rs.Add(self.map_summary,0,wx.EXPAND|wx.ALL,6);right.SetSizer(rs)
        split.SplitVertically(left,right,560);r.Add(split,1,wx.EXPAND|wx.ALL,8);ex=wx.Button(p,label="Export CSV");ex.Bind(wx.EVT_BUTTON,self.export);r.Add(ex,0,wx.ALIGN_RIGHT|wx.ALL,8);p.SetSizer(r)
        make_sortable(self.table)
    def pads(self):
        rows=[]
        for fp in self.board.GetFootprints():
            ref,value=str(fp.GetReference()),str(fp.GetValue())
            for pad in fp.Pads():pos=pad.GetPosition();rows.append(PadNode(ref,str(pad.GetNumber()),str(pad.GetNetname()),float(pcbnew.ToMM(pos.x)),float(pcbnew.ToMM(pos.y)),value))
        return rows
    def analyze(self,_event):
        pads=self.pads();self.findings=analyze_decoupling(pads,self.rails.GetValue(),self.ground.GetValue(),load_patterns=self.loads.GetValue(),maximum_distance_mm=float(self.distance.GetValue()));regs=infer_regulators(pads);self.table.DeleteAllItems()
        for f in self.findings:row=(f.severity,f.rail,f.load,f.check,f.detail);i=self.table.InsertItem(self.table.GetItemCount(),row[0]);[self.table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)];self.table.SetItemTextColour(i,wx.Colour(STATUS_COLOURS.get(f.severity.upper(),"#8fa5b8")))
        self.preview.load(pads,self.findings,self.rails.GetValue(),self.ground.GetValue(),"C*",self.loads.GetValue())
        self.map_summary.SetLabel(f"Map: {len(pads)} pads | {sum(1 for n in self.preview.nodes if n[0]=='rail')} rail pins | {sum(1 for n in self.preview.nodes if n[0]=='capacitor')} capacitors | red rings mark failed pins.")
        self.summary.SetLabel(f"{len(set(p.net for p in pads if p.net))} nets | {len(regs)} regulator candidates | {len(self.findings)} load-pin checks");self.guide.set_step(2,"Review findings and the placement map; double-click a load pin to cross-select its component.")
    def select(self,event):
        target=self.table.GetItemText(event.GetIndex(),2).split(".",1)[0]
        self.preview.set_highlight(next((node[2] for node in self.preview.nodes if node[2].split(".",1)[0]==target),""))
        try:
            for fp in self.board.GetFootprints():
                if str(fp.GetReference())==target:fp.SetSelected()
            pcbnew.Refresh()
        except Exception:pass
    def on_map_pick(self,data):
        """Click a preview pad: highlight it, cross-select its footprint, mark its net."""
        if not isinstance(data,tuple) or not data:return
        label,net=(list(data)+[""])[:2]
        reference=label.split(".",1)[0]
        self.preview.set_highlight(label)
        try:
            for fp in self.board.GetFootprints():
                if str(fp.GetReference())==reference:fp.SetSelected()
            pcb_select_items([])
            pcb_highlight_net(self.board,self.board.FindFootprintByReference(reference).Pads()[0].GetNetname() if hasattr(self.board,"FindFootprintByReference") else net)
            pcbnew.Refresh()
            self.map_summary.SetLabel(f"Picked {label}" + (f" on {net}; net highlighted." if net else "."))
        except Exception as exc:
            self.map_summary.SetLabel(f"Picked {label} ({exc}).")
    def export(self,_event):
        if not self.findings:return
        with wx.FileDialog(self,"Export PDN audit",wildcard="CSV (*.csv)|*.csv",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            with open(d.GetPath(),"w",newline="",encoding="utf-8") as h:w=csv.writer(h);w.writerow(["severity","rail","load","check","detail"]);w.writerows((f.severity,f.rail,f.load,f.check,f.detail) for f in self.findings)
