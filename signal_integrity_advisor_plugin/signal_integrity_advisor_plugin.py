"""Guided KiCad signal-integrity design checks."""

from __future__ import annotations

import os
from typing import Any, Optional

import pcbnew
import wx

from .analysis import ImpedanceResult, PROTOCOL_PRESETS, SignalIntegrityEngine
from .help_utils import open_help
from .preview_kit import PanZoomCanvas, add_zoom_toolbar, TEXT as TEXT_COLOUR, pcb_select_items, pcb_highlight_net
from . import diff_pairs


LAYER_COLOURS = ("#e34a43", "#3fa56b", "#d4a62a", "#3399cc", "#a45ac7", "#d67142")


class RoutePreview(PanZoomCanvas):
    """Board-like routed geometry preview with pan/zoom and a layer legend."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, empty_text="Analyze a routed path to review its layer sequence, vias, and endpoints.")
        self.result: Optional[ImpedanceResult] = None
        self.tracks = []

    def show_result(self, result: ImpedanceResult) -> None:
        self.result = result
        self.route_endpoints = None
        self.tracks = []
        paths = [result.primary] + ([result.mate] if result.mate else [])
        for path in paths:
            lane = 0 if path is result.primary else 1
            for item in getattr(path, "board_items", []):
                if not hasattr(item, "GetStart") or not hasattr(item, "GetEnd"):
                    continue
                start, end = item.GetStart(), item.GetEnd()
                try:
                    import pcbnew as _pcbnew
                    layer = str(_pcbnew.LayerName(item.GetLayer()))
                except Exception:
                    layer = str(getattr(item, "GetLayerName", lambda: "")() or "unknown")
                self.tracks.append((
                    float(start.x) / 1e6, float(start.y) / 1e6,
                    float(end.x) / 1e6, float(end.y) / 1e6,
                    layer, lane, item,
                ))
        legend = []
        colours: dict[str, str] = {}
        for position, layer in enumerate(dict.fromkeys(track[4] for track in self.tracks)):
            colour = LAYER_COLOURS[position % len(LAYER_COLOURS)]
            colours[layer] = colour
            legend.append((colour, layer))
        if result.primary is not None:
            legend.append(("#f4d48d", f"primary {getattr(result.primary, 'net_name', '')}"))
        if result.mate is not None:
            legend.append(("#8fd3f4", f"mate {getattr(result.mate, 'net_name', '')}"))
        self.set_legend(legend)
        picks = []
        for x1, y1, x2, y2, _layer, _lane, item in self.tracks:
            picks.append({
                "x": (x1 + x2) / 2.0, "y": (y1 + y2) / 2.0, "r": 0.4,
                "data": (str(getattr(item, "GetNetname", lambda: "")()), item),
                "marker": False,
            })
        self.set_picks(picks)
        self.Refresh()
        if self.tracks:
            self.fit()

    def scene_bounds(self):
        if not self.tracks:
            return None
        xs = [value for track in self.tracks for value in (track[0], track[2])]
        ys = [value for track in self.tracks for value in (track[1], track[3])]
        return (min(xs), min(ys), max(xs), max(ys))

    def draw_scene(self, gc, project) -> None:
        if not self.tracks:
            return
        colours = {}
        mate_shades = {"#e34a43": "#ff9c94", "#3fa56b": "#8fe0ae", "#d4a62a": "#ffd97a",
                       "#3399cc": "#8fd3f4", "#a45ac7": "#cba6ec", "#d67142": "#ffb08e"}
        for position, layer in enumerate(dict.fromkeys(track[4] for track in self.tracks)):
            colours[layer] = LAYER_COLOURS[position % len(LAYER_COLOURS)]
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        for x1, y1, x2, y2, layer, lane, _item in self.tracks:
            base_colour = colours.get(layer, "#8fa5b8")
            colour = mate_shades.get(base_colour, base_colour) if lane else base_colour
            gc.SetPen(wx.Pen(wx.Colour(colour), 4))
            gc.StrokeLine(*project((x1, y1)), *project((x2, y2)))
            if _item is not None and 'VIA' in str(getattr(_item,'GetClass',lambda:'')()):
                sx,sy=project((x1,y1));diameter=max(6,float(_item.GetWidth(_item.TopLayer()))/1e6*self.scale)
                gc.SetBrush(wx.Brush(wx.Colour('#f8fafc')));gc.DrawEllipse(sx-diameter/2,sy-diameter/2,diameter,diameter);gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), TEXT_COLOUR)
        endpoints = getattr(self,"route_endpoints",None) or ((self.tracks[0][0], self.tracks[0][1]), (self.tracks[-1][2], self.tracks[-1][3]))
        path=getattr(self.result,'primary',None)
        labels=('Source '+str(getattr(path,'start_pad','')),'Receiver '+str(getattr(path,'end_pad','')))
        for index,point in enumerate(endpoints):
            sx,sy=project(point);colour=wx.Colour('#13854c' if index==0 else '#b94535')
            gc.SetPen(wx.Pen(colour,2));gc.SetBrush(wx.Brush(colour))
            if index==0:gc.DrawEllipse(sx-6,sy-6,12,12)
            else:gc.DrawRectangle(sx-6,sy-6,12,12)
            gc.SetFont(wx.Font(9,wx.FONTFAMILY_DEFAULT,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_BOLD),colour)
            gc.DrawText(labels[min(index,1)],sx+9,sy-20 if index==0 else sy+8)



TEXT_COLOUR = "#aab7c4"


class SignalIntegrityAdvisorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Quick SI"
        self.category = "Analysis"
        self.description = "Routed signal timing, reflections and termination screening with impedance and I2C checks."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.version = "3.3.0"

    def Run(self) -> None:
        board = pcbnew.GetBoard()
        if board is None or not hasattr(board, "GetFootprints"):
            wx.MessageBox("Open a PCB in PCB Editor first.", self.name, wx.OK | wx.ICON_ERROR); return
        SignalIntegrityFrame(None, board).Show()


class SignalIntegrityFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any, saved_board: bool = False) -> None:
        super().__init__(parent, title="WayriCAD Quick SI", size=(1220, 820), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((980, 700)); self.board = board; self.saved_board = saved_board; self.engine = SignalIntegrityEngine(board)
        self._build(); self._load_board(); self.Centre()

    def _build(self) -> None:
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(panel, label="Quick SI"); title.SetFont(title.GetFont().Bold().Larger())
        header.Add(title, 1, wx.ALIGN_CENTER_VERTICAL); help_btn = wx.Button(panel, label="Help"); help_btn.Bind(wx.EVT_BUTTON, open_help); header.Add(help_btn)
        root.Add(header, 0, wx.EXPAND | wx.ALL, 12)
        if self.saved_board:
            root.Add(wx.StaticText(panel, label="Electrical checks use saved copper. Test point labels connect separately to this originating editor."), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        intro = wx.StaticText(panel, label="1  Choose a check    2  Define electrical limits and routed endpoints    3  Review evidence and disposition")
        root.Add(intro, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.tabs = wx.Notebook(panel)
        from .quick_ui import QuickSIPanel
        self.quick_si=QuickSIPanel(self.tabs,self.board,RoutePreview,self.saved_board)
        self.tabs.AddPage(self.quick_si,"Quick SI")
        self.tabs.AddPage(self._impedance_page(self.tabs),"Impedance & pairs")
        self.tabs.AddPage(self._i2c_page(self.tabs),"I2C pull-ups")
        from .return_path.return_path_auditor_plugin import ReturnPathFrame
        from .test_points.test_point_descriptor_plugin import TestPointFrame
        from .testpoint_ui import TestPointLabelsPanel
        self.return_path=ReturnPathFrame(self.tabs,self.board);self.tabs.AddPage(self.return_path,"Return path")
        self.test_points=TestPointFrame(self.tabs,self.board);self.tabs.AddPage(self.test_points,"Test point records")
        self.testpoint_labels=TestPointLabelsPanel(self.tabs,self.board,self.saved_board);self.tabs.AddPage(self.testpoint_labels,"Test point labels")
        from .protocol_ui import ProtocolPanel
        self.protocols=ProtocolPanel(self.tabs,self.quick_si,RoutePreview)
        self.tabs.AddPage(self.protocols,"Protocol suites")
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
        actions=wx.BoxSizer(wx.HORIZONTAL); use_selection=wx.Button(page,label="Use PCB selection"); use_selection.Bind(wx.EVT_BUTTON,self._use_selection); use_selection.Enable(not self.saved_board); actions.Add(use_selection,0,wx.RIGHT,6); run=wx.Button(page,label="Analyze and validate path"); run.Bind(wx.EVT_BUTTON,self._analyze); actions.Add(run,1); config.Add(actions,0,wx.EXPAND|wx.ALL,8); split.Add(config,0,wx.EXPAND|wx.ALL,8)
        preview_host=wx.Panel(page); preview_column=wx.BoxSizer(wx.VERTICAL); self.preview=RoutePreview(preview_host); self.preview.on_pick=self._on_route_pick; preview_column.Add(self.preview,1,wx.EXPAND); add_zoom_toolbar(preview_host,self.preview,preview_column); preview_host.SetSizer(preview_column); split.Add(preview_host,1,wx.EXPAND|wx.ALL,8); root.Add(split,1,wx.EXPAND)
        self.status_pair=wx.StaticText(page,label=""); root.Add(self.status_pair,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.results=wx.ListCtrl(page,style=wx.LC_REPORT); self.results.InsertColumn(0,"Check",width=230); self.results.InsertColumn(1,"Value",width=330); self.results.InsertColumn(2,"Disposition",width=520); root.Add(self.results,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        page.SetSizer(root); self.net.Bind(wx.EVT_COMBOBOX,lambda e:(self._pads(self.net,self.start,self.end),self._auto_mate())); self.mate.Bind(wx.EVT_COMBOBOX,lambda e:self._pads(self.mate,self.mate_start,self.mate_end)); return page

    def _load_board(self) -> None:
        names=self.engine.measurement.net_names(); self.net.AppendItems(names); self.mate.Append("<none>"); self.mate.AppendItems(names)
        if names: self.net.SetSelection(0); self._pads(self.net,self.start,self.end)
        self.mate.SetSelection(0); layers=[x.name for x in self.engine.measurement.stackup_layers() if x.name.endswith(".Cu") or "copper" in x.kind.lower()]; self.reference.AppendItems(["Auto", *layers])
        self.reference.SetSelection(0)
        self.reference.SetToolTip("Auto searches ground reference copper per routed section. An explicit layer overrides layer selection.")
        self._auto_mate()

    def _pads(self, net: wx.ComboBox, start: wx.ComboBox, end: wx.ComboBox) -> None:
        values=[] if net.GetValue()=="<none>" else self.engine.measurement.pads_for_net(net.GetValue()); start.Clear(); end.Clear(); start.AppendItems(values); end.AppendItems(values)
        if values: start.SetSelection(0); end.SetSelection(len(values)-1)

    def _auto_mate(self) -> None:
        """Auto-fill the differential mate from detected pair patterns."""
        names = [self.net.GetString(i) for i in range(self.net.GetCount())]
        mate = diff_pairs.find_mate(self.net.GetValue(), names)
        index = self.mate.FindString(mate) if mate else wx.NOT_FOUND
        if mate and index != wx.NOT_FOUND:
            self.mate.SetSelection(index)
            self._pads(self.mate, self.mate_start, self.mate_end)
        elif self.mate.GetSelection() == 0 or not self.mate.GetValue():
            self.mate.SetSelection(0)
        pair = next((p for p in diff_pairs.detect_pairs(names) if self.net.GetValue() in (p.positive, p.negative)), None)
        if pair is not None:
            self.preview.set_legend(list(self.preview.legend_items) + [])  # keep legend stable
            self.status_pair.SetLabel(f"Pair detected ({pair.rule}): {pair.positive} + {pair.negative}")
        else:
            self.status_pair.SetLabel("No differential mate pattern detected for the primary net.")

    def _preset(self,_event:Any) -> None:
        preset=PROTOCOL_PRESETS[self.protocol.GetValue()]; self.target.SetValue(str(preset["target"])); self.tolerance.SetValue(str(preset["tolerance"]))

    def _use_selection(self, _event: Any) -> None:
        if self.saved_board:
            return
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

    def _on_route_pick(self, data: Any) -> None:
        """Click a preview track: cross-select it and highlight its net."""
        if self.saved_board:
            return
        if isinstance(data, tuple) and data:
            net, item = (list(data) + ["", None])[:2]
            items = [item] if item is not None else []
            pcb_select_items(items)
            if pcb_highlight_net(self.board, net):
                self.status_pair.SetLabel(f"Selected and highlighted {net} from the preview.")

    def _analyze(self,_event:Any) -> None:
        try:
            mate="" if self.mate.GetValue()=="<none>" else self.mate.GetValue()
            r=self.engine.validate_impedance(self.net.GetValue(),self.start.GetValue(),self.end.GetValue(),self.reference.GetValue(),float(self.frequency.GetValue()),float(self.target.GetValue()),float(self.tolerance.GetValue()),mate,self.mate_start.GetValue(),self.mate_end.GetValue())
            disposition = {"PASS": "Within target tolerance.", "FAIL": "Outside target tolerance."}.get(r.status, "Impedance unavailable: inspect section/reference geometry and engineering assumptions.")
            measured = "Unavailable" if r.measured_ohm is None else f"{r.measured_ohm:.2f} ohm"
            error = "Unavailable" if r.error_percent is None else f"{r.error_percent:.2f}%"
            rows=[("Overall",r.status,disposition),("Estimated impedance",measured,f"Target {r.target_ohm:g} ohm +/- {r.tolerance_percent:g}%"),("Error",error,""),("Primary route",f"{r.primary.length_mm:.3f} mm",f"{r.primary.track_count} tracks, {r.primary.via_count} vias, {r.primary.layer_changes} layer changes"),("Reference geometry",r.primary.reference_layer,f"{r.primary.stackup_source}; review per-section reference coverage."),("Differential skew",f"{r.skew_mm:.3f} mm","Review protocol timing/skew budget."),("Discontinuity review",r.stub_warning,"Visual and field-solver review required for signoff.")]
            rows.extend(("Engineering assumption", "", note) for note in r.primary.notes)
            self._set_rows(self.results,rows); self.preview.show_result(r)
        except Exception as exc: wx.MessageBox(str(exc),"Impedance analysis failed",wx.OK|wx.ICON_ERROR)
