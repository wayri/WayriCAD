"""wxPython UI for routed trace RLC and impedance analysis."""

from __future__ import annotations

import csv
import os
from typing import Any, List, Optional

import pcbnew
import wx

from .measurement import PathMeasurement, TraceMeasurementEngine
from .help_utils import open_help
from .selection_utils import pads_on_net, select_items
from .guided_ui import add_workflow
from . import rlc_model
from . import diff_pairs
from .preview_kit import PanZoomCanvas, add_zoom_toolbar, severity_colour, pcb_select_items, pcb_highlight_net

LAYER_COLOURS = ("#e34a43", "#3fa56b", "#d4a62a", "#3399cc", "#a45ac7", "#d67142", "#4fb3bf")


class TraceImpedancePlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "KiWay Trace RLC / Impedance Analyzer"
        self.category = "Analysis"
        self.description = "Measure routed net geometry and estimate RLC, impedance, vias, layers, and zones."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.dark_icon_file_name = self.icon_file_name
        self.version = "0.8.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            TraceFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "KiWay Trace RLC / Impedance Analyzer", wx.OK | wx.ICON_ERROR)


class TraceFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Trace RLC / Impedance Analyzer", size=(1180, 760), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((940, 650))
        self.board = board
        self.engine = TraceMeasurementEngine(board)
        self.current: Optional[PathMeasurement] = None
        self.mate_result: Optional[PathMeasurement] = None
        self.last_selection_signature = ()
        self.selection_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_selection_timer, self.selection_timer)
        self._build_ui()
        self._load_nets()
        self._load_stackup()
        self.selection_timer.Start(500)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(panel, root, "Trace RLC / Impedance Analyzer", "Choose a route and stackup context, preview measured geometry, then export the engineering estimate.", ("Configure path", "Review result", "Export"))
        config_box = wx.BoxSizer(wx.VERTICAL)
        config_heading = wx.StaticText(panel, label="Measurement Path")
        config_heading.SetFont(config_heading.GetFont().Bold())
        config_box.Add(config_heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        config = wx.FlexGridSizer(0, 4, 6, 8)
        self.net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.start = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.end = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.diff_net = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.frequency = wx.TextCtrl(panel, value="100")
        self.reference = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.auto_refresh = wx.CheckBox(panel, label="Auto-refresh from PCB selection")
        self.auto_refresh.SetValue(True)
        self.auto_pair = wx.CheckBox(panel, label="Auto-detect differential mate")
        self.auto_pair.SetValue(True)
        self.auto_pair.SetToolTip("Detect pair mates via _P/_N, +/-, _DP/_DM and P/N suffix patterns")
        for label, control in (("Net:", self.net), ("Start pad:", self.start), ("End pad:", self.end), ("Differential mate (optional):", self.diff_net), ("Frequency (MHz):", self.frequency), ("Reference layer:", self.reference)):
            config.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL); config.Add(control, 1, wx.EXPAND)
        config.AddGrowableCol(1, 1)
        config.AddGrowableCol(3, 1)
        config_box.Add(config, 0, wx.EXPAND | wx.ALL, 8)
        root.Add(config_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.net.Bind(wx.EVT_COMBOBOX, self._load_pads)
        self.measure_button = wx.Button(panel, label="Analyze Path")
        self.measure_button.Bind(wx.EVT_BUTTON, self.analyze)
        export = wx.Button(panel, label="Export CSV")
        export.Bind(wx.EVT_BUTTON, self.export_csv)
        select = wx.Button(panel, label="Select Net on PCB")
        select.Bind(wx.EVT_BUTTON, self.select_net)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row = wx.WrapSizer(wx.HORIZONTAL); row.Add(self.measure_button, 0, wx.ALL, 5); row.Add(select, 0, wx.ALL, 5); row.Add(export, 0, wx.ALL, 5); row.Add(help_btn, 0, wx.ALL, 5)
        refresh_stackup = wx.Button(panel, label="Refresh Stackup")
        refresh_stackup.Bind(wx.EVT_BUTTON, self._load_stackup)
        row.Add(refresh_stackup, 0, wx.ALL, 5)
        row.Add(self.auto_refresh, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        row.Add(self.auto_pair, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        highlight = wx.Button(panel, label="Highlight Net on PCB")
        highlight.SetToolTip("Highlight the selected net (and its detected pair mate) in PCB Editor")
        highlight.Bind(wx.EVT_BUTTON, self.highlight_net)
        row.Add(highlight, 0, wx.ALL, 5)
        self.measure_button.SetDefault()
        root.Add(row, 0, wx.ALIGN_RIGHT)
        self.summary = wx.StaticText(panel, label="Select a net and optional start/end pads.")
        root.Add(self.summary, 0, wx.EXPAND | wx.ALL, 8)
        notebook = wx.Notebook(panel)
        preview_page = wx.Panel(notebook)
        preview_sizer = wx.BoxSizer(wx.VERTICAL)
        self.route_preview = RoutePreview(preview_page)
        self.route_preview.on_pick = self._on_route_pick
        preview_sizer.Add(self.route_preview, 1, wx.EXPAND | wx.ALL, 6)
        add_zoom_toolbar(preview_page, self.route_preview, preview_sizer)
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
        model_row.AddGrowableCol(1, 1)
        model_page.SetSizer(model_sizer)
        notebook.AddPage(preview_page, "Route Preview")
        notebook.AddPage(result_page, "Results")
        notebook.AddPage(model_page, "RLC Model")
        notebook.AddPage(stackup_page, "Board Stackup")
        notebook.AddPage(notes_page, "Engineering Notes")
        root.Add(notebook, 1, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(root)
        self.workflow.set_step(0, "Select a net, endpoints, frequency, and reference layer; then Analyze Path.")

    def _load_nets(self) -> None:
        names = self.engine.net_names()
        self.net.AppendItems(names); self.diff_net.Append("<none>"); self.diff_net.AppendItems(names)
        if names: self.net.SetSelection(0); self._load_pads(None)

    def _load_stackup(self, _event: Any = None) -> None:
        layers = self.engine.stackup_layers()
        names = [layer.name for layer in layers]
        self.reference.Clear()
        reference_names = [layer.name for layer in layers if layer.name.endswith(".Cu") or "copper" in layer.kind.lower() or layer.kind == "routed"]
        self.reference.AppendItems(reference_names)
        if reference_names:
            self.reference.SetSelection(0)
        self.stackup_list.DeleteAllItems()
        for layer in layers:
            index = self.stackup_list.InsertItem(self.stackup_list.GetItemCount(), layer.name)
            values = (layer.kind, f"{layer.thickness_mm:.4f}", f"{layer.dielectric_height_mm:.4f}", f"{layer.relative_permittivity:.4g}", layer.material)
            for column, value in enumerate(values, 1):
                self.stackup_list.SetItem(index, column, str(value))
        self.summary.SetLabel(f"Detected {len(layers)} stackup layers ({len(reference_names)} copper references). The selected reference is used in C/L/Z0 math.")

    def _load_pads(self, _event: Any) -> None:
        pads = self.engine.pads_for_net(self.net.GetValue())
        self.start.Clear(); self.end.Clear(); self.start.AppendItems(pads); self.end.AppendItems(pads)
        if pads: self.start.SetSelection(0); self.end.SetSelection(len(pads) - 1)
        self._auto_mate()

    def _auto_mate(self) -> None:
        """Fill the differential-mate combo automatically from pair patterns."""
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
            self.current = self.engine.measure(self.net.GetValue(), self.start.GetValue(), self.end.GetValue(), frequency, self.reference.GetValue())
            self.mate_result = None
            mate = self._mate_net()
            if mate:
                pads = self.engine.pads_for_net(mate)
                if len(pads) >= 2:
                    self.mate_result = self.engine.measure(mate, pads[0], pads[-1], frequency, self.reference.GetValue())
                elif pads:
                    self.mate_result = self.engine.measure(mate, pads[0], pads[0], frequency, self.reference.GetValue())
            self._show(self.current)
            self.workflow.set_step(2, "Review route geometry, skew, and notes; cross-select or highlight the pair; then export if appropriate.")
        except Exception as exc:
            wx.MessageBox(str(exc), "Trace analysis failed", wx.OK | wx.ICON_ERROR)

    def _on_route_pick(self, data: Any) -> None:
        """Click a preview segment: cross-select it and highlight its net."""
        if not isinstance(data, tuple) or len(data) < 2:
            return
        kind, net, _layer = (list(data) + ["", ""])[:3]
        if kind != "net" or not net:
            return
        items = [item for item in getattr(self.board, "GetTracks", lambda: [])() if str(getattr(item, "GetNetname", lambda: "")()) == net]
        pcb_select_items(items + pads_on_net(self.board, net))
        pcb_highlight_net(self.board, net)
        self.summary.SetLabel(f"Selected and highlighted {net} from the route preview.")

    def highlight_net(self, _event: Any = None) -> None:
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
        net_name = self.net.GetValue()
        targets = list(pads_on_net(self.board, net_name))
        targets.extend(item for item in getattr(self.board, "GetTracks", lambda: [])() if str(getattr(item, "GetNetname", lambda: "")()) == net_name)
        count = select_items(self.board, targets)
        self.summary.SetLabel(f"Selected {count} pads/tracks on {net_name} in PCB Editor.")

    def _show(self, result: PathMeasurement) -> None:
        self.table.DeleteAllItems()
        for key, value in result.as_dict().items():
            index = self.table.InsertItem(self.table.GetItemCount(), key); self.table.SetItem(index, 1, str(value))
        self.notes.SetValue("\n".join(result.notes))
        self.summary.SetLabel(f"{result.net_name}: {result.length_mm:.3f} mm | reference {result.reference_layer} | h={result.dielectric_height_mm:.4f} mm | Er={result.relative_permittivity:.3g} | {result.via_count} vias")
        self.route_preview.show_measurement(result, self.mate_result)
        self._show_model(result)
        if self.mate_result:
            skew_mm = abs(result.length_mm - self.mate_result.length_mm)
            extra = (
                ("Differential mate", f"{self.mate_result.net_name} ({self.mate_result.length_mm:.3f} mm)"),
                ("Intra-pair skew", f"{skew_mm:.4f} mm"),
                ("Skew verdict", "within 0.5 mm guideline" if skew_mm <= 0.5 else "exceeds 0.5 mm guideline; review"),
            )
            for key, value in extra:
                index = self.table.InsertItem(self.table.GetItemCount(), key); self.table.SetItem(index, 1, str(value))
            result.notes.append(f"Pair {result.net_name} + {self.mate_result.net_name}: intra-pair skew {skew_mm:.4f} mm.")
        self._show_model(result)
        if result.board_items:
            select_items(self.board, result.board_items + pads_on_net(self.board, result.net_name))

    def _show_model(self, result: PathMeasurement) -> None:
        self.model_table.DeleteAllItems()
        topology = "microstrip" if "microstrip" in (result.impedance_model or "").lower() else "stripline"
        rows = (
            ("Topology", result.impedance_model or "-"),
            ("Average trace width", f"{result.average_width_mm:.4g} mm" if result.average_width_mm else "-"),
            ("Dielectric height to reference", f"{result.dielectric_height_mm:.4g} mm" if result.dielectric_height_mm else "-"),
            ("Width / height ratio", f"{result.width_to_height:.4g}" if result.width_to_height else "-"),
            ("Effective permittivity", f"{result.effective_permittivity:.4g}" if result.effective_permittivity else "-"),
            ("Characteristic impedance Z0", f"{result.impedance_ohm:.3g} ohm" if result.impedance_ohm else "-"),
            ("Distributed C", f"{result.capacitance_pf / max(result.length_mm, 1e-9):.4g} pF/mm" if result.length_mm else "-"),
            ("Distributed L", f"{result.inductance_nh / max(result.length_mm, 1e-9):.4g} nH/mm" if result.length_mm else "-"),
            ("R DC (total route)", f"{result.resistance_ohm:.6g} ohm" if result.resistance_ohm else "-"),
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
        if not self.auto_refresh.GetValue():
            return
        try:
            items = self._selected_board_items()
            signature = tuple(sorted(id(item) for item in items))
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
            wx.MessageBox("Analyze a path first.", "KiWay", wx.OK | wx.ICON_INFORMATION); return
        with wx.FileDialog(self, "Export trace measurement", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            row = self.current.as_dict()
            with open(dialog.GetPath(), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerow(row)
            self.workflow.set_step(3, "Validate critical results with a field solver or measurement before release.")


class RoutePreview(PanZoomCanvas):
    """Layer-colored rendering of the measured route with endpoint markers."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, empty_text="Analyze a path to preview its routed geometry, layers, and endpoints.")
        self.measurement: Optional[PathMeasurement] = None
        self.segments: List[tuple] = []

    def show_measurement(self, result: Optional[PathMeasurement], mate: Optional[PathMeasurement] = None) -> None:
        self.measurement = result
        self.segments = []
        legend = []

        def collect(measurement: Optional[PathMeasurement], lane: int) -> None:
            if measurement is None:
                return
            for item in measurement.board_items:
                if not hasattr(item, "GetStart") or not hasattr(item, "GetEnd"):
                    continue
                start, end = item.GetStart(), item.GetEnd()
                try:
                    layer = str(pcbnew.LayerName(item.GetLayer()))
                except Exception:
                    layer = "unknown"
                width = 0.15
                if hasattr(item, "GetWidth"):
                    try:
                        width = float(item.GetWidth()) / 1_000_000.0
                    except Exception:
                        pass
                self.segments.append((
                    float(start.x) / 1e6, float(start.y) / 1e6,
                    float(end.x) / 1e6, float(end.y) / 1e6,
                    layer, width, lane, item,
                ))

        collect(result, 0)
        collect(mate, 1)
        colours: dict[str, str] = {}
        for position, layer in enumerate(dict.fromkeys(segment[4] for segment in self.segments)):
            colour = LAYER_COLOURS[position % len(LAYER_COLOURS)]
            colours[layer] = colour
            legend.append((colour, layer))
        if result is not None:
            legend.append(("#f4d48d", f"primary {result.net_name}"))
        if mate is not None:
            legend.append(("#8fd3f4", f"mate {mate.net_name}"))
        self.set_legend(legend)
        picks = []
        for index, segment in enumerate(self.segments):
            picks.append({
                "x": (segment[0] + segment[2]) / 2.0,
                "y": (segment[1] + segment[3]) / 2.0,
                "r": max(segment[5], 0.3),
                "data": ("net", getattr(segment[7], "GetNetname", lambda: "")(), segment[4]),
                "marker": False,
            })
        self.set_picks(picks)
        self.Refresh()
        if self.segments:
            self.fit()

    def scene_bounds(self):
        if not self.segments:
            return None
        xs = [value for segment in self.segments for value in (segment[0], segment[2])]
        ys = [value for segment in self.segments for value in (segment[1], segment[3])]
        return (min(xs), min(ys), max(xs), max(ys))

    def draw_scene(self, gc, project) -> None:
        if not self.segments:
            return
        colours = {}
        for position, layer in enumerate(dict.fromkeys(segment[4] for segment in self.segments)):
            colours[layer] = LAYER_COLOURS[position % len(LAYER_COLOURS)]
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        for x1, y1, x2, y2, layer, width, lane, _item in self.segments:
            pen_width = max(2.0, min(width * self.scale, 14.0))
            colour = colours.get(layer, "#8fa5b8")
            if lane == 1:
                colour = "#8fd3f4"
            gc.SetPen(wx.Pen(wx.Colour(colour), int(max(1, round(pen_width))), wx.PENSTYLE_SOLID))
            gc.StrokeLine(*project((x1, y1)), *project((x2, y2)))
        if self.segments:
            first = self.segments[0]
            last = self.segments[-1]
            gc.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), "#f4d48d")
            gc.SetPen(wx.Pen(wx.Colour("#f4d48d"), 2))
            gc.SetBrush(wx.Brush(wx.Colour("#5c4a1e")))
            for point, label in ((first, "start"), (last, "end")):
                sx, sy = project((point[0], point[1]))
                gc.DrawEllipse(sx - 6, sy - 6, 12, 12)
                gc.DrawText(label, sx + 9, sy - 7)


class SweepCanvas(PanZoomCanvas):
    """Synthesis insight: characteristic impedance versus trace width."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, empty_text="Analyze a route to explore Z0 across trace widths at this stackup.")
        self.curve: List[tuple] = []
        self.marker: Optional[tuple] = None

    def configure_route(self, result: PathMeasurement, frequency_mhz: float, topology: str) -> None:
        if not result.dielectric_height_mm or not result.relative_permittivity:
            self.curve = []
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
