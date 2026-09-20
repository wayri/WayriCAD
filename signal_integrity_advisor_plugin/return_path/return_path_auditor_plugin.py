from __future__ import annotations
from wayricad_runtime.help import open_help as open_native_help

import csv
import math
import os
import webbrowser
from pathlib import Path

import pcbnew
import wx

from .analysis import CopperSegment, ReferenceRegion, ReturnPathAnalyzer, ViaPoint, collect_board_geometry
from .guided_ui import add_workflow, mark_primary, section
from .preview_kit import PanZoomCanvas, add_zoom_toolbar, pcb_select_items, pcb_highlight_net

SEVERITY_COLOURS={"PASS":"#3fa56b","WARN":"#d4a62a","FAIL":"#e34a43"}


def mm(value): return float(pcbnew.ToMM(value))
def make_sortable(table):
    state={"column":0,"reverse":False}
    def sort(event):
        column=event.GetColumn();state["reverse"]=not state["reverse"] if column==state["column"] else False;state["column"]=column
        rows=[[table.GetItemText(row,col) for col in range(table.GetColumnCount())] for row in range(table.GetItemCount())];rows.sort(key=lambda row:row[column].casefold(),reverse=state["reverse"]);table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);[table.SetItem(i,col,value) for col,value in enumerate(row[1:],1)]
    table.Bind(wx.EVT_LIST_COL_CLICK,sort)


class BoardPreview(PanZoomCanvas):
    def __init__(self, parent):
        super().__init__(parent, empty_text="Analyze the board to preview routed geometry, return vias, and severity-ranked findings.")
        self.result = None
    def show_result(self,result):
        self.result=result;        picks=[{"x":f.x_mm,"y":f.y_mm,"r":1.2,"data":index} for index,f in enumerate(self.result.findings)] if self.result else []
        self.set_picks(picks)
        self.set_legend([(SEVERITY_COLOURS[name],label) for name,label in (("FAIL","fail"),("WARN","warn"),("PASS","ok"))]+[("#f9a825","return via")])
        self.Refresh()
        if self.result is not None:self.fit()
    def scene_bounds(self):
        if not self.result or not self.result.segments:return None
        xs=[p for s in self.result.segments for p in (s.start[0],s.end[0])];ys=[p for s in self.result.segments for p in (s.start[1],s.end[1])]
        return (min(xs),min(ys),max(xs),max(ys))
    def draw_scene(self,gc,project):
        if not self.result or not self.result.segments:return
        palette=("#1976d2","#2e7d32","#8e24aa","#ef6c00");colours={}
        for segment in self.result.segments:
            colours.setdefault(segment.layer,palette[len(colours)%len(palette)])
            gc.SetPen(wx.Pen(wx.Colour(colours[segment.layer]),max(2,min(int(segment.width_mm*self.scale),12))))
            gc.StrokeLine(*project(segment.start),*project(segment.end))
        gc.SetBrush(wx.Brush(wx.Colour("#f9a825")));gc.SetPen(wx.Pen(wx.Colour("#7f6000")))
        for via in self.result.vias:
            sx,sy=project(via.position);gc.DrawEllipse(sx-3,sy-3,6,6)
        counts={"FAIL":0,"WARN":0,"PASS":0}
        gc.SetFont(wx.Font(8,wx.FONTFAMILY_DEFAULT,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_NORMAL),"#aab7c4")
        for finding in self.result.findings:
            severity=finding.severity.upper()[:4];counts[severity if severity in counts else "WARN"]=counts.get(severity if severity in counts else "WARN",0)+1
            colour=wx.Colour(SEVERITY_COLOURS.get("PASS" if severity.startswith("PASS") else ("FAIL" if severity.startswith("FAIL") else "WARN"),"#d4a62a"))
            sx,sy=project((finding.x_mm,finding.y_mm));gc.SetPen(wx.Pen(colour,2));gc.SetBrush(wx.TRANSPARENT_BRUSH);gc.DrawEllipse(sx-7,sy-7,14,14)
        total=len(self.result.findings)
        if total:gc.DrawText(f"findings: {total} (fail {counts['FAIL']} / warn {counts['WARN']} / ok {counts['PASS']})",10,self.GetClientSize().height-44)


class ReturnPathAuditorPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name="WayriCAD Return-Path Auditor"; self.category="Analysis"; self.description="Find return-path discontinuities, unreferenced transitions, and routed stubs."; self.show_toolbar_button=True; self.icon_file_name=os.path.join(os.path.dirname(__file__),"resources","icon-24.png"); self.dark_icon_file_name=self.icon_file_name.replace("icon-24.png", "icon-dark-24.png"); self.version="3.2.0"
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None: wx.MessageBox("Open a PCB first.",self.name,wx.OK|wx.ICON_ERROR); return
        ReturnPathFrame(None,board).Show()


class ReturnPathFrame(wx.Panel):
    def __init__(self,parent,board):
        super().__init__(parent); self.board=board; self.result=None; self._build()
    def _build(self):
        p=wx.Panel(self); root=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,root,"Return-Path and Discontinuity Auditor","Audit signal transitions, reference continuity, routed branches, and differential geometry without modifying the PCB.",("Configure","Analyze","Review","Export"),lambda e:open_native_help(self,Path(__file__).with_name("help.html")))
        settings_box=section(p,"Audit Settings")
        settings_parent=settings_box.GetStaticBox()
        settings=wx.FlexGridSizer(3,6,7,8); settings.AddGrowableCol(1,1); settings.AddGrowableCol(3,1)
        self.ground=wx.TextCtrl(settings_parent,value="GND,AGND,DGND,PGND,VSS"); self.radius=wx.TextCtrl(settings_parent,value="2.0"); self.stub=wx.TextCtrl(settings_parent,value="5.0"); self.diff_gap=wx.TextCtrl(settings_parent,value="1.0"); self.diff_skew=wx.TextCtrl(settings_parent,value="0.5")
        for label,control in (("Return-net patterns",self.ground),("Return-via radius (mm)",self.radius),("Stub warning length (mm)",self.stub),("Diff uncoupling gap (mm)",self.diff_gap),("Diff skew limit (mm)",self.diff_skew)): settings.Add(wx.StaticText(settings_parent,label=label),0,wx.ALIGN_CENTER_VERTICAL);settings.Add(control,1,wx.EXPAND)
        analyze=mark_primary(wx.Button(settings_parent,label="Analyze Board"),"Analyze the current PCB without changing it"); analyze.Bind(wx.EVT_BUTTON,self.analyze); settings.Add(analyze,0,wx.EXPAND); export=wx.Button(settings_parent,label="Export CSV…");self.export_button=export;export.Disable();export.SetToolTip("Export the reviewed findings as CSV");export.Bind(wx.EVT_BUTTON,self.export);settings.Add(export,0,wx.EXPAND);settings_box.Add(settings,1,wx.EXPAND|wx.ALL,10);root.Add(settings_box,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,10)
        split=wx.SplitterWindow(p); left=wx.Panel(split); right=wx.Panel(split); ls=wx.BoxSizer(wx.VERTICAL); rs=wx.BoxSizer(wx.VERTICAL)
        self.table=wx.ListCtrl(left,style=wx.LC_REPORT); columns=(("Severity",85),("Check",190),("Net",150),("Layer",100),("Location",120),("Detail",430),("Suggested action",450))
        for i,(name,width) in enumerate(columns):self.table.InsertColumn(i,name,width=width)
        make_sortable(self.table)
        self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED,self.select); ls.Add(self.table,1,wx.EXPAND);left.SetSizer(ls)
        self.preview=BoardPreview(right);self.preview.on_pick=self.on_finding_pick;rs.Add(self.preview,1,wx.EXPAND);add_zoom_toolbar(right,self.preview,rs);self.summary=wx.StaticText(right,label="No analysis yet.");rs.Add(self.summary,0,wx.EXPAND|wx.ALL,8);right.SetSizer(rs);split.SplitVertically(left,right,730);root.Add(split,1,wx.EXPAND|wx.ALL,8);p.SetSizer(root); host=wx.BoxSizer(wx.VERTICAL);host.Add(p,1,wx.EXPAND);self.SetSizer(host)
        for control in (self.ground,self.radius,self.stub,self.diff_gap,self.diff_skew):control.Bind(wx.EVT_TEXT,self.invalidate)
    def invalidate(self,event=None):
        self.result=None;self.table.DeleteAllItems();self.preview.show_result(None);self.export_button.Disable();self.summary.SetLabel('Inputs changed; analyze again.')
        if event:event.Skip()
    def on_finding_pick(self,data):
        """Click a finding marker in the preview: highlight it and cross-select its net."""
        index=data if isinstance(data,int) else None
        if index is None or not self.result or index>=len(self.result.findings):return
        finding=self.result.findings[index]
        for row in range(self.table.GetItemCount()):
            if self.table.GetItemText(row,4).startswith(f"{finding.x_mm:.2f}, {finding.y_mm:.2f}"):
                self.table.SetItemState(row,wx.LIST_STATE_SELECTED|wx.LIST_STATE_FOCUSED,wx.LIST_STATE_SELECTED|wx.LIST_STATE_FOCUSED);break
        self.cross_select_net(finding.net,f"Preview click: selected and highlighted {finding.net}; finding {index+1} marked.")
    def collect(self):
        return collect_board_geometry(self.board)
    def analyze(self,_event):
        self.invalidate()
        try:
            for control in (self.radius,self.stub,self.diff_gap,self.diff_skew):
                value=float(control.GetValue())
                if not math.isfinite(value) or value<0:raise ValueError('Audit distances must be finite and nonnegative.')
            if not self.ground.GetValue().strip():raise ValueError('Enter return-net patterns.')
            analyzer=ReturnPathAnalyzer(self.ground.GetValue().split(","));segments,vias,regions=self.collect();self.result=analyzer.audit(segments,vias,regions,float(self.radius.GetValue()),float(self.stub.GetValue()),float(self.diff_gap.GetValue()),float(self.diff_skew.GetValue()),layer_order=[str(self.board.GetLayerName(layer)) for layer in self.board.GetEnabledLayers().CuStack()]);self.table.DeleteAllItems()
            for finding in self.result.findings:
                row=(finding.severity,finding.check,finding.net,finding.layer,f"{finding.x_mm:.2f}, {finding.y_mm:.2f}",finding.detail,finding.remedy);index=self.table.InsertItem(self.table.GetItemCount(),row[0]);[self.table.SetItem(index,col,value) for col,value in enumerate(row[1:],1)]
            self.export_button.Enable();self.preview.show_result(self.result);self.summary.SetLabel(f"{len(segments)} routed segments | {len(vias)} vias | {len(regions)} reference regions | {len(self.result.findings)} findings")
            self.guide.set_step(2,"Review findings; double-click a row to cross-select its net.")
        except Exception as exc:wx.MessageBox(str(exc),"Audit failed",wx.OK|wx.ICON_ERROR)
    def select(self,event):
        index=event.GetIndex()
        net=self.table.GetItemText(index,2)
        self.preview.set_highlight(index)
        self.cross_select_net(net,f"Selected and highlighted {net}; finding marked in preview.")
    def cross_select_net(self,net,message):
        try:
            from ..origin_selection import select_origin
            count=select_origin(self.board,net=net)
            self.summary.SetLabel(f'{count} items selected on the originating PCB; finding highlighted here.')
        except Exception as exc:
            from wayricad_runtime.context import redact_error
            self.summary.SetLabel('Preview highlighted. '+redact_error(exc))
    def export(self,_event):
        if not self.result:return
        with wx.FileDialog(self,"Export findings",defaultDir=str(Path(self.board.GetFileName()).parent),wildcard="CSV (*.csv)|*.csv",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            with open(dialog.GetPath(),"w",newline="",encoding="utf-8") as handle:
                writer=csv.writer(handle);writer.writerow(["severity","check","net","layer","x_mm","y_mm","detail","remedy"]);writer.writerows((f.severity,f.check,f.net,f.layer,f.x_mm,f.y_mm,f.detail,f.remedy) for f in self.result.findings)
            self.guide.set_step(3,"Use the exported evidence in design review or resolve findings in PCB Editor.")
