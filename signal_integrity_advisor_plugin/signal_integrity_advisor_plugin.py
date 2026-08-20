"""Guided KiCad signal-integrity design checks."""

from __future__ import annotations

import os
from typing import Any, Optional

import pcbnew
import wx

from .analysis import ImpedanceResult, PROTOCOL_PRESETS, SignalIntegrityEngine
from .help_utils import open_help


class RoutePreview(wx.Panel):
    """Board-like routed geometry preview with layer-aware colors."""

    COLORS = ("#e34a43", "#3fa56b", "#d4a62a", "#3399cc", "#a45ac7", "#d67142")

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetMinSize((-1, 230)); self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.result: Optional[ImpedanceResult] = None
        self.Bind(wx.EVT_PAINT, self._paint)

    def show_result(self, result: ImpedanceResult) -> None:
        self.result = result; self.Refresh()

    def _paint(self, _event: Any) -> None:
        dc = wx.AutoBufferedPaintDC(self); dc.SetBackground(wx.Brush("#151a20")); dc.Clear()
        width, height = self.GetClientSize()
        dc.SetPen(wx.Pen("#29333d"))
        for x in range(20, width, 40): dc.DrawLine(x, 0, x, height)
        for y in range(20, height, 40): dc.DrawLine(0, y, width, y)
        if not self.result:
            dc.SetTextForeground("#aebdca"); dc.DrawLabel("Analyze a routed path to review its layer sequence, vias, and endpoints.", wx.Rect(20, 20, width-40, height-40), wx.ALIGN_CENTER); return
        paths = [self.result.primary] + ([self.result.mate] if self.result.mate else [])
        tracks = []
        for lane, path in enumerate(paths):
            for item in path.board_items:
                if not hasattr(item, "GetStart") or not hasattr(item, "GetEnd"):
                    continue
                start, end = item.GetStart(), item.GetEnd()
                layer = str(getattr(item, "GetLayerName", lambda: "")())
                tracks.append((float(start.x), float(start.y), float(end.x), float(end.y), layer, lane))
        if tracks:
            xs = [value for row in tracks for value in (row[0], row[2])]
            ys = [value for row in tracks for value in (row[1], row[3])]
            span_x, span_y = max(max(xs)-min(xs), 1.0), max(max(ys)-min(ys), 1.0)
            margin = 35; scale = min((width-2*margin)/span_x, (height-2*margin)/span_y)
            colors = {}; color_index = 0
            for x1, y1, x2, y2, layer, _lane in tracks:
                if layer not in colors:
                    colors[layer] = self.COLORS[color_index % len(self.COLORS)]; color_index += 1
                project = lambda x, y: (margin + int((x-min(xs))*scale), height-margin-int((y-min(ys))*scale))
                dc.SetPen(wx.Pen(colors[layer], 4)); dc.DrawLine(*project(x1,y1), *project(x2,y2))
            dc.SetTextForeground("#d9e2ea"); dc.DrawText("Actual routed copper: " + ", ".join(colors), 12, 10)
            return
        lane_height = max(70, height // max(len(paths), 1))
        for lane, path in enumerate(paths):
            y = lane_height // 2 + lane * lane_height
            left, right = 75, width - 75
            layers = path.layers or [path.reference_layer or "unresolved"]
            section = max(1, (right-left)//len(layers))
            dc.SetTextForeground("#d9e2ea"); dc.DrawText(path.net_name, 10, y-28)
            for index, layer in enumerate(layers):
                x1, x2 = left + index*section, left + (index+1)*section
                dc.SetPen(wx.Pen(self.COLORS[index % len(self.COLORS)], 5)); dc.DrawLine(x1, y, x2, y)
                dc.DrawText(layer, x1+4, y+8)
                if index:
                    dc.SetPen(wx.Pen("#e7edf2", 2)); dc.SetBrush(wx.Brush("#1f2831")); dc.DrawCircle(x1, y, 6)
            dc.SetBrush(wx.Brush("#e5b14b")); dc.SetPen(wx.Pen("#f4d48d", 2)); dc.DrawCircle(left, y, 8); dc.DrawCircle(right, y, 8)


class SignalIntegrityAdvisorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Signal Integrity Advisor"
        self.category = "Analysis"
        self.description = "I2C pull-up recommendations and routed impedance validation."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.dark_icon_file_name = self.icon_file_name
        self.version = "0.1.0"

    def Run(self) -> None:
        board = pcbnew.GetBoard()
        if board is None or not hasattr(board, "GetFootprints"):
            wx.MessageBox("Open a PCB in PCB Editor first.", self.name, wx.OK | wx.ICON_ERROR); return
        SignalIntegrityFrame(None, board).Show()


class SignalIntegrityFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Signal Integrity Advisor", size=(1220, 820), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((980, 700)); self.board = board; self.engine = SignalIntegrityEngine(board)
        self._build(); self._load_board(); self.Centre()

    def _build(self) -> None:
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(panel, label="Signal Integrity Advisor"); title.SetFont(title.GetFont().Bold().Larger())
        header.Add(title, 1, wx.ALIGN_CENTER_VERTICAL); help_btn = wx.Button(panel, label="Help"); help_btn.Bind(wx.EVT_BUTTON, open_help); header.Add(help_btn)
        root.Add(header, 0, wx.EXPAND | wx.ALL, 12)
        intro = wx.StaticText(panel, label="1  Choose a check    2  Define electrical limits and routed endpoints    3  Review evidence and disposition")
        root.Add(intro, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.tabs = wx.Notebook(panel); self.tabs.AddPage(self._i2c_page(self.tabs), "I2C Pull-ups"); self.tabs.AddPage(self._impedance_page(self.tabs), "Impedance & Differential Pairs")
        root.Add(self.tabs, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(root)

    def _i2c_page(self, parent: wx.Window) -> wx.Panel:
        page = wx.Panel(parent); root = wx.BoxSizer(wx.HORIZONTAL); controls = wx.BoxSizer(wx.VERTICAL)
        controls_title=wx.StaticText(page,label="Bus limits"); controls_title.SetFont(controls_title.GetFont().Bold()); controls.Add(controls_title,0,wx.BOTTOM,6)
        grid = wx.FlexGridSizer(0, 2, 8, 10); grid.AddGrowableCol(1, 1)
        self.i2c_fields = {}
        for label, key, value in (("Bus voltage (V)","v","3.3"),("Total bus capacitance (pF)","c","100"),("Maximum rise time (ns)","tr","300"),("Sink-current capability (mA)","i","3"),("VOL maximum (V)","vol","0.4")):
            control = wx.TextCtrl(page, value=value); self.i2c_fields[key]=control; grid.Add(wx.StaticText(page,label=label),0,wx.ALIGN_CENTER_VERTICAL); grid.Add(control,1,wx.EXPAND)
        controls.Add(grid,0,wx.EXPAND|wx.ALL,10); run=wx.Button(page,label="Calculate permitted range"); run.SetDefault(); run.Bind(wx.EVT_BUTTON,self._calculate_i2c); controls.Add(run,0,wx.EXPAND|wx.ALL,10)
        root.Add(controls,0,wx.EXPAND|wx.ALL,10)
        result_box=wx.BoxSizer(wx.VERTICAL); result_title=wx.StaticText(page,label="Recommendation and checks"); result_title.SetFont(result_title.GetFont().Bold()); result_box.Add(result_title,0,wx.BOTTOM,6); self.i2c_result=wx.ListCtrl(page,style=wx.LC_REPORT); self.i2c_result.InsertColumn(0,"Item",width=250); self.i2c_result.InsertColumn(1,"Result",width=430); result_box.Add(self.i2c_result,1,wx.EXPAND)
        root.Add(result_box,1,wx.EXPAND|wx.ALL,10); page.SetSizer(root); return page

    def _impedance_page(self, parent: wx.Window) -> wx.Panel:
        page=wx.Panel(parent); root=wx.BoxSizer(wx.VERTICAL); split=wx.BoxSizer(wx.HORIZONTAL); config=wx.BoxSizer(wx.VERTICAL)
        config_title=wx.StaticText(page,label="Constraint and route"); config_title.SetFont(config_title.GetFont().Bold()); config.Add(config_title,0,wx.BOTTOM,6)
        grid=wx.FlexGridSizer(0,2,6,8); grid.AddGrowableCol(1,1)
        self.protocol=wx.ComboBox(page,choices=list(PROTOCOL_PRESETS),style=wx.CB_READONLY); self.protocol.SetSelection(0); self.protocol.Bind(wx.EVT_COMBOBOX,self._preset)
        self.net=wx.ComboBox(page,style=wx.CB_READONLY); self.start=wx.ComboBox(page,style=wx.CB_READONLY); self.end=wx.ComboBox(page,style=wx.CB_READONLY); self.mate=wx.ComboBox(page,style=wx.CB_READONLY); self.mate_start=wx.ComboBox(page,style=wx.CB_READONLY); self.mate_end=wx.ComboBox(page,style=wx.CB_READONLY); self.reference=wx.ComboBox(page,style=wx.CB_READONLY)
        self.target=wx.TextCtrl(page,value="50"); self.tolerance=wx.TextCtrl(page,value="10"); self.frequency=wx.TextCtrl(page,value="100")
        for label,control in (("Protocol / constraint",self.protocol),("Target impedance (ohm)",self.target),("Tolerance (%)",self.tolerance),("Frequency (MHz)",self.frequency),("Primary net",self.net),("Start pad",self.start),("End pad",self.end),("Differential mate",self.mate),("Mate start pad",self.mate_start),("Mate end pad",self.mate_end),("Reference layer",self.reference)):
            grid.Add(wx.StaticText(page,label=label),0,wx.ALIGN_CENTER_VERTICAL); grid.Add(control,1,wx.EXPAND)
        config.Add(grid,1,wx.EXPAND|wx.ALL,8)
        actions=wx.BoxSizer(wx.HORIZONTAL); use_selection=wx.Button(page,label="Use PCB selection"); use_selection.Bind(wx.EVT_BUTTON,self._use_selection); actions.Add(use_selection,0,wx.RIGHT,6); run=wx.Button(page,label="Analyze and validate path"); run.Bind(wx.EVT_BUTTON,self._analyze); actions.Add(run,1); config.Add(actions,0,wx.EXPAND|wx.ALL,8); split.Add(config,0,wx.EXPAND|wx.ALL,8)
        self.preview=RoutePreview(page); split.Add(self.preview,1,wx.EXPAND|wx.ALL,8); root.Add(split,1,wx.EXPAND)
        self.results=wx.ListCtrl(page,style=wx.LC_REPORT); self.results.InsertColumn(0,"Check",width=230); self.results.InsertColumn(1,"Value",width=330); self.results.InsertColumn(2,"Disposition",width=520); root.Add(self.results,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        page.SetSizer(root); self.net.Bind(wx.EVT_COMBOBOX,lambda e:self._pads(self.net,self.start,self.end)); self.mate.Bind(wx.EVT_COMBOBOX,lambda e:self._pads(self.mate,self.mate_start,self.mate_end)); return page

    def _load_board(self) -> None:
        names=self.engine.measurement.net_names(); self.net.AppendItems(names); self.mate.Append("<none>"); self.mate.AppendItems(names)
        if names: self.net.SetSelection(0); self._pads(self.net,self.start,self.end)
        self.mate.SetSelection(0); layers=[x.name for x in self.engine.measurement.stackup_layers() if x.name.endswith(".Cu") or "copper" in x.kind.lower()]; self.reference.AppendItems(layers)
        if layers: self.reference.SetSelection(0)

    def _pads(self, net: wx.ComboBox, start: wx.ComboBox, end: wx.ComboBox) -> None:
        values=[] if net.GetValue()=="<none>" else self.engine.measurement.pads_for_net(net.GetValue()); start.Clear(); end.Clear(); start.AppendItems(values); end.AppendItems(values)
        if values: start.SetSelection(0); end.SetSelection(len(values)-1)

    def _preset(self,_event:Any) -> None:
        preset=PROTOCOL_PRESETS[self.protocol.GetValue()]; self.target.SetValue(str(preset["target"])); self.tolerance.SetValue(str(preset["tolerance"]))

    def _use_selection(self, _event: Any) -> None:
        selected_pads=[]; selected_nets=[]
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                if bool(getattr(pad,"IsSelected",lambda:False)()):
                    selected_pads.append((str(getattr(pad,"GetNetname",lambda:"")()), f"{footprint.GetReference()}.{pad.GetNumber()}"))
        for track in getattr(self.board,"GetTracks",lambda:[])():
            if bool(getattr(track,"IsSelected",lambda:False)()):
                selected_nets.append(str(getattr(track,"GetNetname",lambda:"")()))
        net=next((name for name,_pad in selected_pads if name), next((name for name in selected_nets if name), ""))
        if not net:
            wx.MessageBox("Select a routed track or one or more pads in PCB Editor first.","No routed selection",wx.OK|wx.ICON_INFORMATION); return
        self.net.SetValue(net); self._pads(self.net,self.start,self.end)
        endpoints=[pad for name,pad in selected_pads if name==net]
        if endpoints:
            self.start.SetValue(endpoints[0]); self.end.SetValue(endpoints[-1])

    def _set_rows(self, control: wx.ListCtrl, rows: list[tuple[str,str,str]]) -> None:
        control.DeleteAllItems()
        for row in rows:
            index=control.InsertItem(control.GetItemCount(),row[0]); control.SetItem(index,1,row[1]);
            if control.GetColumnCount()>2: control.SetItem(index,2,row[2])

    def _calculate_i2c(self,_event:Any) -> None:
        try:
            f=self.i2c_fields; r=self.engine.i2c_pullup(float(f["v"].GetValue()),float(f["c"].GetValue()),float(f["tr"].GetValue()),float(f["i"].GetValue()),float(f["vol"].GetValue()))
            recommendation="none" if r.recommended_ohm is None else f"{r.recommended_ohm:g} ohm (E24 midpoint candidate)"
            self._set_rows(self.i2c_result,[("Status",r.status,""),("Minimum resistance",f"{r.minimum_ohm:.1f} ohm",""),("Maximum resistance",f"{r.maximum_ohm:.1f} ohm",""),("Recommended value",recommendation,""),("Engineering note",r.note,"")])
        except Exception as exc: wx.MessageBox(str(exc),"I2C calculation failed",wx.OK|wx.ICON_ERROR)

    def _analyze(self,_event:Any) -> None:
        try:
            mate="" if self.mate.GetValue()=="<none>" else self.mate.GetValue()
            r=self.engine.validate_impedance(self.net.GetValue(),self.start.GetValue(),self.end.GetValue(),self.reference.GetValue(),float(self.frequency.GetValue()),float(self.target.GetValue()),float(self.tolerance.GetValue()),mate,self.mate_start.GetValue(),self.mate_end.GetValue())
            rows=[("Overall",r.status,"Resolve topology before signoff." if r.status=="UNRESOLVED" else "Within target tolerance." if r.status=="PASS" else "Outside target tolerance."),("Estimated impedance",f"{r.measured_ohm:.2f} ohm",f"Target {r.target_ohm:g} ohm +/- {r.tolerance_percent:g}%"),("Error",f"{r.error_percent:.2f}%",""),("Primary route",f"{r.primary.length_mm:.3f} mm",f"{r.primary.track_count} tracks, {r.primary.via_count} vias, {r.primary.layer_changes} layer changes"),("Reference geometry",r.primary.reference_layer,f"{r.primary.stackup_source}; h={r.primary.dielectric_height_mm:.4f} mm; Er={r.primary.relative_permittivity:.3g}"),("Differential skew",f"{r.skew_mm:.3f} mm","Review protocol timing/skew budget."),("Discontinuity review",r.stub_warning,"Visual and field-solver review required for signoff.")]
            self._set_rows(self.results,rows); self.preview.show_result(r)
        except Exception as exc: wx.MessageBox(str(exc),"Impedance analysis failed",wx.OK|wx.ICON_ERROR)
