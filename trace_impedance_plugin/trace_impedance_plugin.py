"""wxPython UI for routed trace RLC and impedance analysis."""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
from typing import Any, List, Optional

import pcbnew
import wx

from .measurement import PathMeasurement, TraceMeasurementEngine
from .help_utils import open_help
from .selection_utils import pads_on_net, select_items
from .guided_ui import add_workflow
from . import rlc_model
from . import diff_pairs
from .preview_kit import PanZoomCanvas, add_zoom_toolbar, TEXT, pcb_select_items, pcb_highlight_net

LAYER_COLOURS = ("#e34a43", "#3fa56b", "#d4a62a", "#3399cc", "#a45ac7", "#d67142", "#4fb3bf")


class TraceImpedancePlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Trace RLC / Impedance Analyzer"
        self.category = "Analysis"
        self.description = "Measure routed net geometry and estimate RLC, impedance, vias, layers, and zones."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.version = "3.4.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            TraceFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Trace RLC / Impedance Analyzer", wx.OK | wx.ICON_ERROR)


class TraceFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any, saved_board: bool = False) -> None:
        super().__init__(parent, title="WayriCAD Trace RLC / Impedance Analyzer", size=(1180, 760), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((940, 650))
        self.board = board
        self.saved_board = saved_board
        self.engine = TraceMeasurementEngine(board)
        self.current: Optional[PathMeasurement] = None
        self.mate_result: Optional[PathMeasurement] = None
        self.last_selection_signature = ()
        self.selection_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_selection_timer, self.selection_timer)
        self._build_ui()
        self._load_nets()
        self._load_stackup()
        if not self.saved_board:
            self.selection_timer.Start(500)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(panel, root, "Trace RLC / Impedance Analyzer", "Choose a route and stackup context, preview measured geometry, then export the engineering estimate.", ("Configure path", "Review result", "Export"))
        if self.saved_board:
            banner = wx.StaticText(panel, label="Saved board analysis — save/refill in KiCad and reopen to refresh.")
            root.Add(banner, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        config_box = wx.BoxSizer(wx.VERTICAL)
        config = wx.FlexGridSizer(0, 4, 6, 8)
        self.net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.start = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.end = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.diff_net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.frequency = wx.TextCtrl(panel, value="100")
        self.reference = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.mode = wx.Choice(panel, choices=["Path (traces + vias + zones)", "Zone / plane"])
        self.mode.SetSelection(0)
        self.zone_layer = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.zone_options = []
        self.corridor_width = wx.TextCtrl(panel, value="0.2")
        self.corridor_width.SetToolTip("Assumed current corridor width inside filled zone copper; does not modify the PCB.")
        for label, control in (("Mode", self.mode), ("Net", self.net), ("Start terminal", self.start), ("End terminal", self.end), ("Frequency (MHz)", self.frequency), ("Filled island", self.zone_layer)):
            config.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL); config.Add(control, 1, wx.EXPAND)
        config.AddGrowableCol(1, 1)
        config.AddGrowableCol(3, 1)
        config_box.Add(config, 0, wx.EXPAND | wx.ALL, 4)
        self.options = wx.CollapsiblePane(panel, label="Reference and pair options", style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        options_panel = self.options.GetPane()
        self.diff_net.Reparent(options_panel)
        self.reference.Reparent(options_panel)
        self.corridor_width.Reparent(options_panel)
        self.auto_refresh = wx.CheckBox(options_panel, label="Follow PCB selection")
        self.auto_refresh.SetValue(False)
        self.auto_refresh.Enable(not self.saved_board)
        self.auto_pair = wx.CheckBox(options_panel, label="Detect differential mate")
        self.auto_pair.SetValue(True)
        self.auto_pair.SetToolTip("Detect pair mates via _P/_N, +/-, _DP/_DM and P/N suffix patterns")
        advanced = wx.FlexGridSizer(0, 4, 6, 8)
        for label, control in (("Reference layer", self.reference), ("Differential mate", self.diff_net)):
            advanced.Add(wx.StaticText(options_panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL); advanced.Add(control, 1, wx.EXPAND)
        advanced.Add(self.auto_refresh); advanced.Add(self.auto_pair)
        advanced.Add(wx.StaticText(options_panel, label="Zone current width (mm)"), 0, wx.ALIGN_CENTER_VERTICAL)
        advanced.Add(self.corridor_width, 1, wx.EXPAND)
        advanced.AddGrowableCol(1, 1); advanced.AddGrowableCol(3, 1)
        options_panel.SetSizer(advanced)
        config_box.Add(self.options, 0, wx.EXPAND | wx.ALL, 4)
        self.options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda event: panel.Layout())
        root.Add(config_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.net.Bind(wx.EVT_COMBOBOX, self._load_pads)
        self.mode.Bind(wx.EVT_CHOICE, self._mode_changed)
        self.zone_layer.Bind(wx.EVT_COMBOBOX, self._zone_changed)
        for control in (self.start, self.end, self.reference, self.diff_net):
            control.Bind(wx.EVT_COMBOBOX, self._invalidate)
        for control in (self.frequency, self.corridor_width):
            control.Bind(wx.EVT_TEXT, self._invalidate)
        self.measure_button = wx.Button(panel, label="Analyze")
        self.measure_button.Bind(wx.EVT_BUTTON, self.analyze)
        export = wx.Button(panel, label="Export CSV")
        self.export_button = export
        export.Disable()
        export.Bind(wx.EVT_BUTTON, self.export_csv)
        more = wx.Button(panel, label="More")
        more.Bind(wx.EVT_BUTTON, self._more)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self.measure_button, 0, wx.ALL, 5); row.Add(export, 0, wx.ALL, 5); row.Add(more, 0, wx.ALL, 5)
        self.measure_button.SetDefault()
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.summary = wx.StaticText(panel, label="Select a net and optional start/end pads.")
        root.Add(self.summary, 0, wx.EXPAND | wx.ALL, 8)
        notebook = wx.Notebook(panel)
        preview_page = wx.Panel(notebook)
        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        self.route_preview = RoutePreview(preview_page, self.board)
        self.route_preview.SetMinSize((-1, 145))
        self.route_preview.on_pick = self._on_route_pick
        preview_sizer.Add(self.route_preview, 2, wx.EXPAND | wx.ALL, 6)
        add_zoom_toolbar(preview_page, self.route_preview, preview_sizer)
        display=wx.BoxSizer(wx.HORIZONTAL)
        display.Add(wx.StaticText(preview_page,label='Colour geometry by'),0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,5)
        self.route_colours=wx.Choice(preview_page,choices=['Copper layer','DC resistance contribution','AC resistance contribution','Model coverage'])
        self.route_colours.SetSelection(0)
        self.route_colours.Bind(wx.EVT_CHOICE,lambda e:self.route_preview.set_colour_mode(self.route_colours.GetSelection()))
        display.Add(self.route_colours,0,wx.ALL,5)
        preview_sizer.Add(display,0,wx.EXPAND)
        preview_page.SetSizer(preview_sizer)
        result_page = wx.Panel(notebook)
        result_sizer = wx.BoxSizer(wx.VERTICAL)
        stackup_page = wx.Panel(notebook)
        stackup_sizer = wx.BoxSizer(wx.VERTICAL)
        notes_page = wx.Panel(notebook)
        notes_sizer = wx.BoxSizer(wx.VERTICAL)
        model_page = wx.Panel(notebook)
        model_sizer = wx.BoxSizer(wx.VERTICAL)
        self.stackup_list = wx.ListCtrl(stackup_page, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, label in enumerate(("Layer", "Type", "Copper mm", "Dielectric mm", "Er", "Material")):
            self.stackup_list.InsertColumn(index, label, width=150 if index in (0, 5) else 105)
        stackup_sizer.Add(self.stackup_list, 1, wx.EXPAND | wx.ALL, 6)
        stackup_page.SetSizer(stackup_sizer)
        self.table = wx.ListCtrl(result_page, style=wx.LC_REPORT)
        for index, label in enumerate(("Metric", "Value")):
            self.table.InsertColumn(index, label, width=260 if index == 0 else 620)
        result_sizer.Add(self.table, 1, wx.EXPAND | wx.ALL, 6)
        self.sections = wx.ListCtrl(preview_page, style=wx.LC_REPORT)
        self.sections.SetMinSize((-1, 100))
        for index, label in enumerate(("Section", "Layer / transition", "Reference", "Length mm", "R DC Ω", "R AC Ω", "L nH", "C pF", "Z₀ Ω")):
            self.sections.InsertColumn(index, label, width=135 if index < 3 else 88)
        preview_sizer.Add(self.sections, 1, wx.EXPAND | wx.ALL, 6)
        self.sections.Bind(wx.EVT_LIST_ITEM_SELECTED,self._section_selected)
        result_page.SetSizer(result_sizer)
        self.notes = wx.TextCtrl(notes_page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        notes_sizer.Add(self.notes, 1, wx.EXPAND | wx.ALL, 6)
        notes_page.SetSizer(notes_sizer)
        model_row = wx.BoxSizer(wx.HORIZONTAL)
        self.model_table = wx.ListCtrl(model_page, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, label in enumerate(("Model quantity", "Value")):
            self.model_table.InsertColumn(index, label, width=280 if index == 0 else 300)
        model_row.Add(self.model_table, 0, wx.EXPAND | wx.ALL, 6)
        self.sweep_canvas = SweepCanvas(model_page)
        model_row.Add(self.sweep_canvas, 1, wx.EXPAND | wx.ALL, 6)
        model_sizer.Add(model_row, 1, wx.EXPAND | wx.ALL, 6)
        model_page.SetSizer(model_sizer)
        notebook.AddPage(preview_page, "Copper & sections")
        notebook.AddPage(result_page, "Results")
        notebook.AddPage(model_page, "RLC Model")
        from .frequency_ui import FrequencyPanel
        self.frequency_panel=FrequencyPanel(notebook,self.board.GetFileName())
        notebook.AddPage(self.frequency_panel,"AC loss sweep")
        notebook.AddPage(stackup_page, "Board Stackup")
        notebook.AddPage(notes_page, "Engineering Notes")
        root.Add(notebook, 1, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)
        self._mode_changed(None)
        self.workflow.set_step(0, "Choose a net and two terminals. Auto reference searches ground copper by layer.")

    def _mode_changed(self, _event: Any) -> None:
        zone = self.mode.GetSelection() == 1
        self.zone_layer.Enable(zone)
        self.diff_net.Enable(not zone)
        self.auto_pair.Enable(not zone)
        self.corridor_width.Enable(zone)
        if self.net.GetValue():
            self._zone_changed(None)

    def _zone_changed(self, _event: Any) -> None:
        self._invalidate(None)
        index = self.zone_layer.GetSelection()
        if self.mode.GetSelection() == 1:
            pads = self.engine.zone_terminals(self.zone_options[index]['id']) if index != wx.NOT_FOUND else []
        else:
            pads = self.engine.pads_for_net(self.net.GetValue())
        previous = (self.start.GetValue(), self.end.GetValue())
        self.start.Clear(); self.end.Clear()
        self.start.AppendItems(pads); self.end.AppendItems(pads)
        if pads:
            self.start.SetValue(previous[0] if previous[0] in pads else pads[0])
            self.end.SetValue(previous[1] if previous[1] in pads and previous[1] != self.start.GetValue() else pads[-1])
        self.measure_button.Enable(len(pads) > 1)
        if self.mode.GetSelection() == 1:
            self.summary.SetLabel(f"{len(pads)} terminals touch this filled island. R/L uses the assumed current width; C uses reference overlap.")

    def _invalidate(self, _event: Any) -> None:
        self.export_button.Disable()
        if self.current is None:
            return
        self.current = self.mate_result = None
        self.table.DeleteAllItems(); self.sections.DeleteAllItems(); self.model_table.DeleteAllItems()
        self.notes.Clear()
        self.route_preview.show_measurement(None)
        self.sweep_canvas.curve = []; self.sweep_canvas.marker = None
        self.sweep_canvas.Refresh()
        self.frequency_panel.set_path(None)
        self.summary.SetLabel("Settings changed. Analyze the selected copper to refresh results.")

    def _more(self, _event: Any) -> None:
        menu = wx.Menu()
        actions = [("Help", lambda event: open_help(self))]
        if not self.saved_board:
            actions = [("Select net on PCB", self.select_net), ("Highlight net on PCB", self.highlight_net), ("Refresh stackup", self._load_stackup), *actions]
        for label, handler in actions:
            item = menu.Append(wx.ID_ANY, label)
            menu.Bind(wx.EVT_MENU, handler, item)
        self.PopupMenu(menu)
        menu.Destroy()

    def _load_nets(self) -> None:
        names = self.engine.net_names()
        self.net.AppendItems(names); self.diff_net.Append("<none>"); self.diff_net.AppendItems(names)
        if names: self.net.SetSelection(0); self._load_pads(None)

    def _load_stackup(self, _event: Any = None) -> None:
        previous_reference = self.reference.GetValue()
        if _event is not None:
            # The explicit Refresh action must reread the saved stackup and
            # invalidate a result computed from the old material geometry.
            self.engine._stackup_cache = None
            self._invalidate(None)
        layers = self.engine.stackup_layers()
        self.reference.Clear()
        reference_names = [layer.name for layer in layers if layer.name.endswith(".Cu") or "copper" in layer.kind.lower() or layer.kind == "routed"]
        self.reference.AppendItems(["Auto", *reference_names])
        selected = self.reference.FindString(previous_reference)
        self.reference.SetSelection(selected if selected != wx.NOT_FOUND else 0)
        self.reference.SetToolTip("Auto chooses ground copper per section. Choosing a layer explicitly overrides layer selection; see reference coverage in Notes.")
        self.stackup_list.DeleteAllItems()
        for layer in layers:
            index = self.stackup_list.InsertItem(self.stackup_list.GetItemCount(), layer.name)
            values = (layer.kind, f"{layer.thickness_mm:.4f}", f"{layer.dielectric_height_mm:.4f}", f"{layer.relative_permittivity:.4g}", layer.material)
            for column, value in enumerate(values, 1):
                self.stackup_list.SetItem(index, column, str(value))
        grounds = self.engine.ground_nets()
        self.summary.SetLabel(f"{len(reference_names)} copper layers · Ground candidates: {', '.join(grounds) or 'none detected'} · Reference: {self.reference.GetValue()}")

    def _load_pads(self, _event: Any) -> None:
        pads = self.engine.pads_for_net(self.net.GetValue())
        self.start.Clear(); self.end.Clear(); self.start.AppendItems(pads); self.end.AppendItems(pads)
        if pads: self.start.SetSelection(0); self.end.SetSelection(len(pads) - 1)
        self.zone_options = sorted(self.engine.zone_options(self.net.GetValue()), key=lambda row: row['area_mm2'], reverse=True)
        self.zone_layer.Clear()
        self.zone_layer.AppendItems([f"{row['layer']} · island {row['island'] + 1} · {row['area_mm2']:.2f} mm²" for row in self.zone_options])
        if self.zone_options:
            self.zone_layer.SetSelection(0)
        self._zone_changed(None)
        self._auto_mate()

    def _auto_mate(self) -> None:
        """Fill the differential-mate combo automatically from pair patterns."""
        if not self.auto_pair.GetValue():
            return
        current = self.net.GetValue()
        names = [self.net.GetString(i) for i in range(self.net.GetCount())]
        mate = diff_pairs.find_mate(current, names)
        rule = next((pair.rule for pair in diff_pairs.detect_pairs(names) if current in (pair.positive, pair.negative)), "")
        index = self.diff_net.FindString(mate) if mate else wx.NOT_FOUND
        if mate and index != wx.NOT_FOUND:
            self.diff_net.SetSelection(index)
            self.summary.SetLabel(f"Detected differential pair: {current} + {mate} ({rule}).")
        elif not self.auto_pair.GetValue():
            return
        else:
            self.diff_net.SetSelection(0)

    def _mate_net(self) -> str:
        value = self.diff_net.GetValue()
        return "" if (not value or value == "<none>" or value == self.net.GetValue()) else value

    def analyze(self, _event: Any) -> None:
        try:
            frequency = float(self.frequency.GetValue())
            self.mate_result = None
            if self.mode.GetSelection() == 1:
                index = self.zone_layer.GetSelection()
                if index == wx.NOT_FOUND:
                    raise ValueError("This net has no filled zone islands. Fill its zones in PCB Editor, then reopen the analyzer.")
                self.current = self.engine.measure_zone(self.net.GetValue(), self.start.GetValue(), self.end.GetValue(), self.zone_options[index]['id'], reference_layer=self.reference.GetValue(), frequency_mhz=frequency, corridor_width_mm=float(self.corridor_width.GetValue()))
            else:
                self.current = self.engine.measure(self.net.GetValue(), self.start.GetValue(), self.end.GetValue(), frequency, self.reference.GetValue())
            mate = self._mate_net() if self.mode.GetSelection() == 0 else ""
            if mate:
                pads = self.engine.pads_for_net(mate)
                if len(pads) >= 2:
                    self.mate_result = self.engine.measure(mate, pads[0], pads[-1], frequency, self.reference.GetValue())
                elif pads:
                    self.current.notes.append(f"Mate {mate} has fewer than two terminals; pair measurement unavailable.")
            self._show(self.current)
            self.workflow.set_step(2, "Review geometry, per-section estimates and notes; export when ready." if self.saved_board else "Review route geometry, skew, and notes; cross-select or highlight the pair; then export if appropriate.")
        except Exception as exc:
            wx.MessageBox(str(exc), "Trace analysis failed", wx.OK | wx.ICON_ERROR)

    def _on_route_pick(self, data: Any) -> None:
        """Click a preview segment: cross-select it and highlight its net."""
        if isinstance(data,tuple) and data[0]=='section' and self.current:
            for index,section in enumerate(self.current.segments):
                if section.get('item_uuid')==data[1]:
                    for row in range(self.sections.GetItemCount()):self.sections.Select(row,False)
                    self.sections.Select(index);self.sections.EnsureVisible(index)
                    break
            return
        if self.saved_board:
            return
        if not isinstance(data, tuple) or len(data) < 2:
            return
        kind, net, _layer = (list(data) + ["", ""])[:3]
        if kind != "net" or not net:
            return
        items = [item for item in getattr(self.board, "GetTracks", lambda: [])() if str(getattr(item, "GetNetname", lambda: "")()) == net]
        pcb_select_items(items + pads_on_net(self.board, net))
        pcb_highlight_net(self.board, net)
        self.summary.SetLabel(f"Selected and highlighted {net} from the route preview.")

    def _section_selected(self,event):
        if self.current is None or event.GetIndex()>=len(self.current.segments):return
        section=self.current.segments[event.GetIndex()]
        self.route_preview.selected_uuid=section.get('item_uuid');self.route_preview.Refresh()
        self.summary.SetLabel(f"{section['kind']} on {section['layer']} · {section.get('length_mm',0):.3f} mm · R DC {section.get('resistance_ohm',0):.5g} Ω · R AC {section.get('resistance_ac_ohm',0):.5g} Ω · {section.get('model','Model unresolved')}")
        self.summary.Wrap(max(500,self.GetClientSize().width-35))

    def highlight_net(self, _event: Any = None) -> None:
        if self.saved_board:
            return
        nets = [self.net.GetValue()]
        mate = self._mate_net()
        if mate:
            nets.append(mate)
        done = []
        for name in nets:
            if name and pcb_highlight_net(self.board, name):
                done.append(name)
        targets = list(self.current.board_items) if self.current else []
        if self.mate_result:
            targets.extend(self.mate_result.board_items)
        if targets:
            pcb_select_items(targets + pads_on_net(self.board, nets[0]))
        if done:
            self.summary.SetLabel("Highlighted: " + " + ".join(done) + (" (differential pair)" if len(done) > 1 else "") + ".")
        else:
            self.summary.SetLabel("Highlight is not supported by this KiCad version; items were selected instead.")

    def select_net(self, _event: Any) -> None:
        if self.saved_board:
            return
        net_name = self.net.GetValue()
        targets = list(pads_on_net(self.board, net_name))
        targets.extend(item for item in getattr(self.board, "GetTracks", lambda: [])() if str(getattr(item, "GetNetname", lambda: "")()) == net_name)
        count = select_items(self.board, targets)
        self.summary.SetLabel(f"Selected {count} pads/tracks on {net_name} in PCB Editor.")

    def _show(self, result: PathMeasurement) -> None:
        self.export_button.Enable()
        self.frequency_panel.set_path(result.as_report())
        self.table.DeleteAllItems()
        for key, value in result.as_dict().items():
            index = self.table.InsertItem(self.table.GetItemCount(), key); self.table.SetItem(index, 1, str(value))
        self.notes.SetValue("\n".join(result.notes))
        status = getattr(result, "status", "partial")
        self.summary.SetLabel(f"{result.net_name} · {status.upper()} · {result.length_mm:.3f} mm · {result.via_count} vias · {result.layer_changes} layer changes · reference {result.reference_layer or 'unavailable'}")
        self.summary.Wrap(max(500, self.GetClientSize().width - 35))
        self.sections.DeleteAllItems()
        for section in getattr(result, "segments", []):
            values = self._section_values(section)
            index = self.sections.InsertItem(self.sections.GetItemCount(), values[0])
            for column, value in enumerate(values[1:], 1):
                self.sections.SetItem(index, column, value)
        index = self.zone_layer.GetSelection()
        selected_zone = self.zone_options[index] if self.mode.GetSelection() == 1 and index != wx.NOT_FOUND else None
        self.route_preview.show_measurement(result, self.mate_result, selected_zone)
        if self.mate_result:
            skew_mm = abs(result.length_mm - self.mate_result.length_mm)
            extra = (
                ("Differential mate", f"{self.mate_result.net_name} ({self.mate_result.length_mm:.3f} mm)"),
                ("Intra-pair skew", f"{skew_mm:.4f} mm"),
                ("Skew scope", "Measured selected terminal paths; check timing budget and pair endpoint mapping."),
            )
            for key, value in extra:
                index = self.table.InsertItem(self.table.GetItemCount(), key); self.table.SetItem(index, 1, str(value))
            result.notes.append(f"Pair {result.net_name} + {self.mate_result.net_name}: intra-pair skew {skew_mm:.4f} mm.")
        self._show_model(result)
        self.notes.SetValue("\n".join(result.notes))
        self.Layout()

    @staticmethod
    def _section_values(section: dict) -> list[str]:
        def number(key):
            value = section.get(key)
            return "—" if value is None else f"{value:.5g}" if isinstance(value, (float, int)) else str(value)
        layer = str(section.get("layer", "—"))
        if section.get("end_layer") and section["end_layer"] != layer:
            layer += " → " + str(section["end_layer"])
        reference = " / ".join(str(section[key]) for key in ("reference_net", "reference_layer") if section.get(key)) or "Unavailable"
        return [str(section.get("kind", "section")), layer, reference, *[number(key) for key in ("length_mm", "resistance_ohm", "resistance_ac_ohm", "inductance_nh", "capacitance_pf", "impedance_ohm")]]

    def _show_model(self, result: PathMeasurement) -> None:
        self.model_table.DeleteAllItems()
        models = " ".join(str(row.get("model", "")) for row in getattr(result, "segments", [])).lower()
        topology = "microstrip" if "microstrip" in models else "stripline"
        uniform = getattr(result, "impedance_valid", False)
        def contribution(key, total, unit):
            sections = getattr(result, "segments", [])
            if not sections or not any(row.get(key) is not None for row in sections):
                return "Unavailable"
            suffix = " (modeled contributions)" if result.status != "ok" else ""
            return f"{total:.4g} {unit}{suffix}"
        rows = (
            ("Topology", result.impedance_model or "-"),
            ("Average trace width", f"{result.average_width_mm:.4g} mm" if result.average_width_mm else "-"),
            ("Dielectric height to reference", f"{result.dielectric_height_mm:.4g} mm" if uniform and result.dielectric_height_mm else "See per-section reference geometry"),
            ("Width / height ratio", f"{result.width_to_height:.4g}" if uniform and result.width_to_height else "See sections"),
            ("Effective permittivity", f"{result.effective_permittivity:.4g}" if uniform and result.effective_permittivity else "See sections"),
            ("Characteristic impedance Z0", f"{result.impedance_ohm:.3g} ohm" if result.impedance_ohm and getattr(result, "impedance_valid", False) else "Unavailable; see section estimates and notes"),
            ("C (selected geometry)", contribution("capacitance_pf", result.capacitance_pf, "pF")),
            ("L (selected geometry)", contribution("inductance_nh", result.inductance_nh, "nH")),
            ("R DC (modeled sections)", contribution("resistance_ohm", result.resistance_ohm, "ohm")),
            ("R AC with skin effect", f"{result.resistance_ac_ohm:.6g} ohm" if result.resistance_ac_ohm else "-"),
            ("Propagation delay", f"{result.propagation_delay_ns:.4g} ns" if result.propagation_delay_ns else "-"),
        )
        for key, value in rows:
            index = self.model_table.InsertItem(self.model_table.GetItemCount(), key)
            self.model_table.SetItem(index, 1, value)
        try:
            frequency = float(self.frequency.GetValue())
        except ValueError:
            frequency = 100.0
        self.sweep_canvas.configure_route(result, frequency, topology)

    def _selected_board_items(self) -> list[Any]:
        items = []
        for footprint in self.board.GetFootprints():
            items.extend(pad for pad in footprint.Pads() if bool(getattr(pad, "IsSelected", lambda: False)()))
        items.extend(item for item in getattr(self.board, "GetTracks", lambda: [])() if bool(getattr(item, "IsSelected", lambda: False)()))
        return items

    def on_selection_timer(self, _event: Any) -> None:
        if self.saved_board or not self.auto_refresh.GetValue():
            return
        try:
            items = self._selected_board_items()
            signature = tuple(sorted(str(getattr(item, 'm_Uuid', id(item))) for item in items))
            if signature == self.last_selection_signature:
                return
            self.last_selection_signature = signature
            net_names = [str(getattr(item, "GetNetname", lambda: "")()) for item in items]
            net_name = next((name for name in net_names if name), "")
            if net_name and self.net.FindString(net_name) != wx.NOT_FOUND:
                self.net.SetValue(net_name)
                self._load_pads(None)
            selected_pads = []
            for footprint in self.board.GetFootprints():
                for pad in footprint.Pads():
                    if bool(getattr(pad, "IsSelected", lambda: False)()):
                        selected_pads.append(f"{footprint.GetReference()}.{pad.GetNumber()}")
            if selected_pads:
                self.start.SetValue(selected_pads[0])
                self.end.SetValue(selected_pads[-1])
            self.summary.SetLabel(f"PCB selection: {len(items)} routed items; net {net_name or 'none'}; {len(selected_pads)} endpoint pads.")
        except Exception:
            pass

    def on_close(self, event: Any) -> None:
        self.selection_timer.Stop()
        event.Skip()

    def export_csv(self, _event: Any) -> None:
        if not self.current:
            wx.MessageBox("Analyze copper first.", "WayriCAD", wx.OK | wx.ICON_INFORMATION); return
        source=Path(self.board.GetFileName()).resolve()
        with wx.FileDialog(self, "Export trace measurement", defaultDir=str(source.parent), defaultFile=source.stem+"-trace-rlc.csv", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            target=Path(dialog.GetPath()).resolve()
            if target==source or target.suffix.lower()!=".csv":
                wx.MessageBox("Choose a separate .csv report.", "Export", parent=self); return
            row = self.current.as_dict()
            try:
                with target.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            except OSError as exc:
                wx.MessageBox(str(exc), "Export failed", parent=self); return
            self.workflow.set_step(3, "Validate critical results with a field solver or measurement before release.")


class RoutePreview(PanZoomCanvas):
    """Actual copper geometry, including filled islands, holes, pads and via drills."""

    def __init__(self, parent: Any, board: Any = None) -> None:
        super().__init__(parent, empty_text="Analyze copper to see its layers, filled zones and terminals.")
        self.board = board
        self.measurement = None
        self.segments = []
        self.copper = []
        self.vias = []
        self.terminals = []
        self.corridor = None
        self.colours = {}
        self.colour_mode=0;self.selected_uuid=None;self.section_metrics={};self.metric_max={}

    def set_colour_mode(self,mode):
        self.colour_mode=mode
        maximum=self.metric_max.get('resistance_ohm' if mode==1 else 'resistance_ac_ohm',0)
        self.set_legend([(colour,layer) for layer,colour in self.colours.items()] if mode==0 else
            [('#b34c39',f'{maximum:.4g} Ω / item'),('#298fac','0 Ω / item')] if mode in (1,2) else
            [('#25855e','Modeled line'),('#c39236','Partial / unresolved')])
        self.Refresh()

    def item_colour(self,item,layer):
        if not self.colour_mode:return self.colours.get(layer,'#718096')
        section=self.section_metrics.get(str(item.m_Uuid.AsString()),{})
        if self.colour_mode==3:return '#25855e' if section.get('status')=='ok' else '#c39236'
        key='resistance_ohm' if self.colour_mode==1 else 'resistance_ac_ohm'
        maximum=self.metric_max.get(key,0)
        fraction=math.sqrt(max(0,section.get(key,0))/maximum) if maximum else 0
        return wx.Colour(round(41+138*fraction),round(143-67*fraction),round(172-115*fraction))

    @staticmethod
    def _point(point):
        # PCB coordinates increase downward; the shared chart canvas increases upward.
        return (float(point.x) / 1e6, -float(point.y) / 1e6)

    def status_for(self, world):
        return "" if world is None else f"{world[0]:.3f}, {-world[1]:.3f} mm"

    def fit(self) -> None:
        bounds = self.scene_bounds()
        size = self.GetClientSize()
        if bounds is None or min(size.width, size.height) < 50:
            return
        left, top, right, bottom = bounds
        self.scale = min((size.width - 48) / max(right-left, 1e-6), (size.height - 48) / max(bottom-top, 1e-6))
        self.center_x, self.center_y = (left+right)/2, (top+bottom)/2
        self.Refresh()

    @classmethod
    def _polygons(cls, polygons):
        def ring(chain):
            return [cls._point(chain.CPoint(i)) for i in range(chain.PointCount())]
        return [(ring(polygons.COutline(i)), [ring(polygons.CHole(i, h)) for h in range(polygons.HoleCount(i))]) for i in range(polygons.OutlineCount())]

    def _layer(self, number):
        try:
            # Stackup/measurement identities use canonical names even when the
            # board calls In8.Cu something like GND8.Cu.
            return str(pcbnew.LayerName(number))
        except Exception:
            return str(number)

    def show_measurement(self, result, mate=None, selected_zone=None) -> None:
        self.measurement = result
        self.selected_uuid=None
        self.section_metrics={}
        for measurement in (result,mate):
            for section in getattr(measurement,'segments',[]):
                uid=section.get('item_uuid')
                if uid:
                    previous=self.section_metrics.get(uid)
                    if previous:
                        previous['resistance_ohm']+=section.get('resistance_ohm',0)
                        previous['resistance_ac_ohm']+=section.get('resistance_ac_ohm',0)
                    else:self.section_metrics[uid]=dict(section)
        self.metric_max={key:max((row.get(key,0) for row in self.section_metrics.values()),default=0) for key in ('resistance_ohm','resistance_ac_ohm')}
        self.segments, self.copper, self.vias, self.terminals = [], [], [], []
        self.corridor = None
        for measurement, lane in ((result, 0), (mate, 1)):
            if measurement is None:
                continue
            items = list(measurement.board_items)
            if selected_zone and self.board is not None:
                # Retain the selected filled island as context when its terminals
                # cannot be connected; the status still reports incomplete.
                for zone in self.board.Zones():
                    if selected_zone['id'].startswith(str(zone.m_Uuid.AsString()) + ':') and zone not in items:
                        items.append(zone)
            for item in items:
                if hasattr(item, "GetFilledPolysList"):
                    for number in item.GetLayerSet().Seq():
                        if selected_zone and self._layer(number) != selected_zone['layer']:
                            continue
                        for island, (outer, holes) in enumerate(self._polygons(item.GetFilledPolysList(number))):
                            if selected_zone and island != selected_zone['island']:
                                continue
                            self.copper.append((outer, holes, self._layer(number), "zone"))
                    continue
                if hasattr(item, "GetDrillValue"):
                    point = self._point(item.GetPosition())
                    self.vias.append((point, float(item.GetWidth(item.GetLayer())) / 1e6, float(item.GetDrillValue()) / 1e6, self._layer(item.GetLayer()), item))
                    continue
                if not hasattr(item, "GetStart"):
                    continue
                points = [self._point(item.GetStart()), self._point(item.GetEnd())]
                if hasattr(item, "GetMid"):
                    # The native center and signed arc angle preserve curved tracks.
                    try:
                        center = self._point(item.GetCenter())
                        angle = -float(item.GetArcAngle().AsRadians())
                        radius = math.dist(center, points[0])
                        start = math.atan2(points[0][1] - center[1], points[0][0] - center[0])
                        count = max(8, int(abs(angle) * 24))
                        points = [(center[0] + radius * math.cos(start + angle * i / count), center[1] + radius * math.sin(start + angle * i / count)) for i in range(count + 1)]
                    except (AttributeError, TypeError):
                        points.insert(1, self._point(item.GetMid()))
                self.segments.append((points, self._layer(item.GetLayer()), float(item.GetWidth()) / 1e6, lane, item))
            if self.board is not None:
                wanted = {measurement.start_pad, measurement.end_pad}
                for footprint in self.board.GetFootprints():
                    for pad in footprint.Pads():
                        label = f"{footprint.GetReference()}.{pad.GetNumber()}"
                        if label not in wanted or str(pad.GetNetname()) != measurement.net_name:
                            continue
                        self.terminals.append((self._point(pad.GetPosition()), label))
                        try:
                            for outer, holes in self._polygons(pad.GetEffectivePolygon(pad.GetLayer())):
                                self.copper.append((outer, holes, self._layer(pad.GetLayer()), "pad"))
                        except (AttributeError, TypeError):
                            pass
        layers = list(dict.fromkeys([row[1] for row in self.segments] + [row[2] for row in self.copper] + [row[3] for row in self.vias]))
        self.colours = {layer: LAYER_COLOURS[i % len(LAYER_COLOURS)] for i, layer in enumerate(layers)}
        legend = [(colour, layer) for layer, colour in self.colours.items()]
        if selected_zone and result is not None and result.zone_count and len(self.terminals) == 2:
            self.corridor = (self.terminals[0][0], self.terminals[1][0], result.average_width_mm)
            legend.append(("#245f91", "Assumed current corridor"))
        self.set_legend(legend)
        self.set_colour_mode(self.colour_mode)
        picks = [{"x": points[len(points)//2][0], "y": points[len(points)//2][1], "r": max(width, .3), "data": ("section",str(item.m_Uuid.AsString())), "marker": False} for points, layer, width, lane, item in self.segments]
        picks += [dict(x=point[0],y=point[1],r=max(width,.3),data=('section',str(item.m_Uuid.AsString())),marker=False) for point,width,drill,layer,item in self.vias]
        self.set_picks(picks)
        self.Refresh()
        if self.scene_bounds():
            self.fit()

    def scene_bounds(self):
        points = [point for row in self.segments for point in row[0]]
        points += [point for outer, holes, layer, kind in self.copper for point in outer]
        points += [row[0] for row in self.vias] + [row[0] for row in self.terminals]
        if not points:
            return None
        return (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))

    def draw_scene(self, gc, project) -> None:
        for outer, holes, layer, kind in sorted(self.copper, key=lambda row: row[3] == "pad"):
            if not outer:
                continue
            path = gc.CreatePath()
            for ring in [outer, *holes]:
                if not ring:
                    continue
                path.MoveToPoint(*project(ring[0]))
                for point in ring[1:]:
                    path.AddLineToPoint(*project(point))
                path.CloseSubpath()
            colour = wx.Colour(self.colours.get(layer, "#718096"))
            fill = wx.Colour(colour.Red(), colour.Green(), colour.Blue(), 42 if kind == "zone" else 170)
            gc.SetPen(wx.Pen(colour, 1))
            gc.SetBrush(wx.Brush(fill))
            gc.DrawPath(path, wx.ODDEVEN_RULE)
        for points, layer, width, lane, item in self.segments:
            if str(item.m_Uuid.AsString())==self.selected_uuid:
                gc.SetPen(wx.Pen('#ecb943',max(5,round(width*self.scale)+5)));gc.StrokeLines([project(point) for point in points])
            gc.SetPen(wx.Pen(wx.Colour(self.item_colour(item,layer)), max(1, round(width * self.scale))))
            gc.StrokeLines([project(point) for point in points])
        for point, width, drill, layer, item in self.vias:
            x, y = project(point)
            diameter = max(2., width * self.scale)
            gc.SetPen(wx.Pen('#ecb943' if str(item.m_Uuid.AsString())==self.selected_uuid else wx.Colour(self.item_colour(item,layer)), 3))
            gc.SetBrush(wx.Brush(wx.Colour(self.item_colour(item,layer))))
            gc.DrawEllipse(x-diameter/2, y-diameter/2, diameter, diameter)
            diameter = max(1., drill * self.scale)
            gc.SetBrush(wx.Brush(wx.Colour("#f8fafc")))
            gc.DrawEllipse(x-diameter/2, y-diameter/2, diameter, diameter)
        if self.corridor:
            a, b, width = self.corridor
            gc.SetPen(wx.Pen(wx.Colour("#245f91"), max(2, round(width * self.scale)), wx.PENSTYLE_SHORT_DASH))
            gc.StrokeLine(*project(a), *project(b))
        gc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), TEXT)
        for point, label in self.terminals:
            x, y = project(point)
            gc.DrawText(label, x+7, y-16)


class SweepCanvas(PanZoomCanvas):
    """Synthesis insight: characteristic impedance versus trace width."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, empty_text="Analyze a route to explore Z0 across trace widths at this stackup.")
        self.curve: List[tuple] = []
        self.marker: Optional[tuple] = None

    def configure_route(self, result: PathMeasurement, frequency_mhz: float, topology: str) -> None:
        if not getattr(result, "impedance_valid", False) or not result.dielectric_height_mm or not result.relative_permittivity:
            self.curve = []
            self.marker = None
            self.empty_text = "No single uniform transmission-line model for this measurement. Review sections and assumptions."
            self.Refresh()
            return
        self.curve = rlc_model.z0_width_sweep(
            height_mm=result.dielectric_height_mm,
            copper_mm=result.copper_thickness_mm or 0.035,
            relative_permittivity=result.relative_permittivity,
            topology=topology,
        )
        self.marker = (result.average_width_mm or None, result.impedance_ohm or None)
        self.set_legend([("#3399cc", "Z0(width)")])
        self.Refresh()
        self.fit()

    def scene_bounds(self):
        if not self.curve:
            return None
        xs = [point[0] for point in self.curve]
        ys = [point[1] for point in self.curve]
        return (min(xs), max(min(ys), 0.0), max(xs), max(ys))

    def draw_scene(self, gc, project) -> None:
        if len(self.curve) < 2:
            return
        # Reference lines at common design targets.
        for target, colour in ((50.0, "#3fa56b"), (90.0, "#a45ac7"), (100.0, "#d67142")):
            gc.SetPen(wx.Pen(wx.Colour(colour), 1, wx.PENSTYLE_SHORT_DASH))
            left_x, right_x = self.curve[0][0], self.curve[-1][0]
            gc.StrokeLine(*project((left_x, target)), *project((right_x, target)))
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), TEXT)
            gc.DrawText(f"{target:g} ohm", *project((right_x, target)))
        gc.SetPen(wx.Pen(wx.Colour("#3399cc"), 2))
        points = [project(point) for point in self.curve]
        gc.StrokeLines(points)
        if self.marker and all(value is not None for value in self.marker):
            mx, my = project((float(self.marker[0]), float(self.marker[1])))
            gc.SetPen(wx.Pen(wx.Colour("#f4d48d"), 2))
            gc.SetBrush(wx.Brush(wx.Colour("#5c4a1e")))
            gc.DrawEllipse(mx - 6, my - 6, 12, 12)
            gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), "#f4d48d")
            gc.DrawText(f"route {self.marker[0]:.3g} mm -> {self.marker[1]:.3g} ohm", mx + 10, my - 16)
