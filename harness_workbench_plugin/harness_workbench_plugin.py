from __future__ import annotations

import math
import os
import tempfile
import webbrowser
from pathlib import Path

import pcbnew
import wx
import wx.grid as gridlib

from .analysis import (
    HarnessBundle, HarnessSplice, PinMapRow, VirtualLoad, apply_bundle, apply_splice,
    auto_link_multi, connector_correspondence, connector_graph,
    build_system_signal_paths, discover_pin_documents, export_csv, export_rows, harness_bom,
    links_from_pin_map, load_pin_documents, load_pin_map_csv, load_signal_path_documents, net_map_rows,
    parse_connector_rules, pin_map_editor_rows, pin_map_rows, universal_harness_svg,
    system_signal_rows, validate_links, validate_pin_map, virtual_load_records,
)
from .guided_ui import add_workflow, mark_primary, section
from .report import interactive_harness_html

MAX_PROJECTS = 50
MAX_VISIBLE_ROWS = 10000


def make_sortable(table):
    state = {"column": 0, "reverse": False}
    def sort(event):
        column = event.GetColumn()
        state["reverse"] = not state["reverse"] if column == state["column"] else False
        state["column"] = column
        rows = [[table.GetItemText(r, c) for c in range(table.GetColumnCount())]
                for r in range(table.GetItemCount())]
        rows.sort(key=lambda row: row[column].casefold(), reverse=state["reverse"])
        table.DeleteAllItems()
        for row in rows:
            index = table.InsertItem(table.GetItemCount(), row[0])
            for col, value in enumerate(row[1:], 1): table.SetItem(index, col, value)
    table.Bind(wx.EVT_LIST_COL_CLICK, sort)


def _table(parent, columns, widths=None):
    table = wx.ListCtrl(parent, style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES)
    widths = widths or [150] * len(columns)
    for index, name in enumerate(columns): table.InsertColumn(index, name, width=widths[index])
    make_sortable(table)
    return table


def _fill(table, rows, fields):
    table.Freeze()
    try:
        table.DeleteAllItems()
        for row in rows[:MAX_VISIBLE_ROWS]:
            values = [str(row.get(field, "")) for field in fields]
            index = table.InsertItem(table.GetItemCount(), values[0])
            for column, value in enumerate(values[1:], 1): table.SetItem(index, column, value)
    finally:
        table.Thaw()


class HarnessCanvas(wx.Panel):
    """Native pan/zoom harness draft; avoids embedded browser lifetime hazards."""
    COLORS = ("#237c73", "#d15b45", "#5577aa", "#8d62a8", "#d39b32", "#3c8d56")

    def __init__(self, parent, on_node=None):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.links, self.positions = [], {}
        self.scale, self.pan, self.drag_start = 1.0, wx.Point2D(0, 0), None
        self.on_node = on_node
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self._wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._down)
        self.Bind(wx.EVT_LEFT_UP, self._up)
        self.Bind(wx.EVT_MOTION, self._motion)
        self.Bind(wx.EVT_LEFT_DCLICK, self._double_click)

    def set_links(self, links): self.links = list(links); self.fit()
    def fit(self): self.scale, self.pan = 1.0, wx.Point2D(0, 0); self.Refresh()
    def _screen(self, x, y): return x * self.scale + self.pan.x, y * self.scale + self.pan.y

    def _layout(self):
        nodes, _ = connector_graph(self.links)
        columns = max(2, math.ceil(math.sqrt(max(1, len(nodes)))))
        return {node: (170 + (i % columns) * 300, 120 + (i // columns) * 170)
                for i, node in enumerate(nodes)}

    def _paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        dc.SetBackground(wx.Brush(bg)); dc.Clear()
        if not self.links:
            dc.SetTextForeground(fg)
            dc.DrawLabel("Build the universal harness to view the system draft.",
                         self.GetClientRect(), wx.ALIGN_CENTER)
            return
        gc = wx.GraphicsContext.Create(dc); self.positions = self._layout()
        bundles = sorted({link.bundle or "Unbundled" for link in self.links})
        colors = {name: self.COLORS[i % len(self.COLORS)] for i, name in enumerate(bundles)}
        grouped = {}
        for source, destination, link in connector_graph(self.links)[1]:
            grouped.setdefault((source, destination), []).append(link)
        for (source, destination), group in grouped.items():
            x1, y1 = self.positions[source]; x2, y2 = self.positions[destination]
            for index, link in enumerate(group):
                offset = (index - (len(group) - 1) / 2) * 3
                sx, sy = self._screen(x1 + 105, y1 + offset)
                ex, ey = self._screen(x2 - 105, y2 + offset)
                path = gc.CreatePath(); path.MoveToPoint(sx, sy)
                path.AddCurveToPoint((sx + ex) / 2, sy, (sx + ex) / 2, ey, ex, ey)
                gc.SetPen(wx.Pen(colors[link.bundle or "Unbundled"],
                                max(1, int(2 * self.scale))))
                gc.StrokePath(path)
        for node, (x, y) in self.positions.items():
            sx, sy = self._screen(x - 105, y - 42)
            dc.SetPen(wx.Pen("#526b7a", max(1, int(2 * self.scale))))
            dc.SetBrush(wx.Brush(bg))
            dc.DrawRoundedRectangle(int(sx), int(sy), int(210 * self.scale),
                                    int(84 * self.scale), max(2, int(5 * self.scale)))
            if self.scale >= .5:
                project, connector = node.split(":", 1)
                count = sum(node in (f"{l.source.project}:{l.source.connector}",
                                     f"{l.destination.project}:{l.destination.connector}")
                            for l in self.links)
                dc.SetTextForeground(fg)
                dc.DrawText(connector, int(sx + 12 * self.scale), int(sy + 10 * self.scale))
                dc.DrawText(f"{project} | {count} wires",
                            int(sx + 12 * self.scale), int(sy + 39 * self.scale))

    def _wheel(self, event):
        old = self.scale
        self.scale = min(3.5, max(.25, old * (1.15 if event.GetWheelRotation() > 0 else 1 / 1.15)))
        point = event.GetPosition()
        self.pan.x = point.x - (point.x - self.pan.x) * self.scale / old
        self.pan.y = point.y - (point.y - self.pan.y) * self.scale / old
        self.Refresh()
    def _down(self, event): self.drag_start = event.GetPosition(); self.CaptureMouse()
    def _up(self, _event):
        self.drag_start = None
        if self.HasCapture(): self.ReleaseMouse()
    def _motion(self, event):
        if self.drag_start is None or not event.Dragging(): return
        point = event.GetPosition(); delta = point - self.drag_start; self.drag_start = point
        self.pan.x += delta.x; self.pan.y += delta.y; self.Refresh()
    def _double_click(self, event):
        if not self.on_node: return
        point = event.GetPosition(); nearest, distance = None, float("inf")
        for node, (x, y) in self.positions.items():
            sx, sy = self._screen(x, y); candidate = (point.x - sx) ** 2 + (point.y - sy) ** 2
            if candidate < distance: nearest, distance = node, candidate
        if nearest and distance < (120 * self.scale) ** 2: self.on_node(nearest)


class HarnessWorkbenchPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "KiWay Harness and Cable Workbench"
        self.category = "Documentation"
        self.description = "Build multi-board harness maps, drawings, bundles, splices, and BoMs."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.dark_icon_file_name = self.icon_file_name
        self.version = "0.5.0"
    def Run(self): HarnessFrame(None).Show()


class HarnessFrame(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title="KiWay Harness and Cable Workbench", size=(1400, 900))
        self.records, self.virtual_loads, self.links, self.bundles, self.splices = [], [], [], [], []
        self.board_paths, self.system_paths = [], []
        self._build(); self.Centre()

    def _build(self):
        panel = wx.Panel(self); root = wx.BoxSizer(wx.VERTICAL)
        self.guide = add_workflow(
            panel, root, "Harness and Cable Workbench",
            "Ingest up to 50 board pin documents, map connector families, and release reviewed harness data.",
            ("Sources", "Link rules", "Pin map", "Wire review", "System paths", "Report"), self._help)
        self.notebook = wx.Notebook(panel)
        self._build_sources(); self._build_rules(); self._build_pin_editor(); self._build_wires()
        self._build_system_map(); self._build_canvas(); self._build_outputs()
        root.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(panel, label="Import board pin CSV files or a directory to begin.")
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(root)

    def _page(self, title):
        page = wx.Panel(self.notebook); self.notebook.AddPage(page, title); return page

    def _build_sources(self):
        page = self._page("1  Sources"); root = wx.BoxSizer(wx.VERTICAL); actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Import Pin CSV Files...", self._import_files),
                               ("Import Directory...", self._import_directory),
                               ("Import IC / Connector Paths...", self._import_signal_paths),
                               ("Clear Sources", self._clear_sources)):
            button = wx.Button(page, label=label); button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(actions, 0, wx.ALL, 10)
        self.source_table = _table(page, ("Project", "Connector", "Pins", "Connector Part", "Endpoint Type"),
                                   (190, 150, 80, 250, 130))
        root.Add(self.source_table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.path_source_status = wx.StaticText(page, label="No audited IC/peripheral-to-connector path documents loaded.")
        root.Add(self.path_source_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticText(page, label="Columns: project, connector/reference, pin/pad, net, function, voltage, connector part, contact part, load A."),
                 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10); page.SetSizer(root)

    def _build_rules(self):
        page = self._page("2  Link Rules"); root = wx.BoxSizer(wx.VERTICAL)
        box = section(page, "Automatic Matching"); parent = box.GetStaticBox(); row = wx.BoxSizer(wx.HORIZONTAL)
        self.match_nets = wx.CheckBox(parent, label="Indexed net matching"); self.match_nets.SetValue(True)
        self.net_pattern = wx.TextCtrl(parent, value="*"); self.use_regex = wx.CheckBox(parent, label="Regex")
        self.include_power = wx.CheckBox(parent, label="Include power nets")
        row.Add(self.match_nets, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        row.Add(wx.StaticText(parent, label="Net pattern"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        row.Add(self.net_pattern, 1, wx.RIGHT, 10); row.Add(self.use_regex, 0, wx.RIGHT, 10)
        row.Add(self.include_power); box.Add(row, 0, wx.EXPAND | wx.ALL, 8); root.Add(box, 0, wx.EXPAND | wx.ALL, 8)
        rules = section(page, "Connector Correspondence (pin N maps to pin N)")
        self.connector_rules = wx.TextCtrl(rules.GetStaticBox(), style=wx.TE_MULTILINE)
        self.connector_rules.SetHint("DEMO_CTRL:J1 -> DEMO_IO:J2\nDEMO_A:J3 -> DEMO_B:J7 [map=1:3,2:4]")
        rules.Add(self.connector_rules, 1, wx.EXPAND | wx.ALL, 8); root.Add(rules, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        loads = section(page, "External Loads and Non-Schematic Endpoints")
        self.load_text = wx.TextCtrl(loads.GetStaticBox(), style=wx.TE_MULTILINE)
        self.load_text.SetHint("PROJECT,REFERENCE,PIN,NET,FUNCTION,VOLTAGE,CURRENT_A,CONNECTOR_PART\nLOADS,MOTOR_A,1,MOTOR_POS,Drive motor,24V,3.5,TE-DEMO")
        loads.Add(self.load_text, 1, wx.EXPAND | wx.ALL, 8); root.Add(loads, 1, wx.EXPAND | wx.ALL, 8)
        build = mark_primary(wx.Button(page, label="Build Universal Harness"), "Apply net and connector rules")
        build.Bind(wx.EVT_BUTTON, self._build_links); root.Add(build, 0, wx.ALIGN_RIGHT | wx.ALL, 10); page.SetSizer(root)

    def _build_pin_editor(self):
        page = self._page("3  Pin Map"); root = wx.BoxSizer(wx.VERTICAL)
        seed = section(page, "Seed a connector pair, then edit any pin relationship")
        parent = seed.GetStaticBox(); row = wx.BoxSizer(wx.HORIZONTAL)
        self.map_source = wx.ComboBox(parent, style=wx.CB_READONLY)
        self.map_destination = wx.ComboBox(parent, style=wx.CB_READONLY)
        seed_button = wx.Button(parent, label="Seed N-to-N Rows")
        seed_button.SetToolTip("Create editable starting rows for pins present on both connectors.")
        seed_button.Bind(wx.EVT_BUTTON, self._seed_pin_map)
        for label, control in (("Source", self.map_source), ("Destination", self.map_destination)):
            row.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            row.Add(control, 1, wx.RIGHT, 12)
        row.Add(seed_button); seed.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        root.Add(seed, 0, wx.EXPAND | wx.ALL, 8)

        columns = ("Source Project", "Source Connector", "Source Pin", "Destination Project",
                   "Destination Connector", "Destination Pin", "Wire ID", "AWG", "Color",
                   "Bundle", "Splice", "Length m", "Shield", "Notes")
        self.pin_grid = gridlib.Grid(page)
        self.pin_grid.CreateGrid(0, len(columns))
        for index, label in enumerate(columns):
            self.pin_grid.SetColLabelValue(index, label)
        widths = (150, 120, 75, 150, 130, 90, 85, 60, 85, 100, 90, 80, 120, 240)
        for index, width in enumerate(widths):
            self.pin_grid.SetColSize(index, width)
        self.pin_grid.EnableDragRowSize(False)
        root.Add(self.pin_grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Add Row", self._add_pin_map_row), ("Delete Selected Rows", self._delete_pin_map_rows),
                               ("Import Mapping CSV...", self._import_pin_map), ("Export Mapping CSV...", self._export_pin_map),
                               ("Validate Mapping", self._validate_pin_map_ui)):
            button = wx.Button(page, label=label); button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 8)
        actions.AddStretchSpacer()
        build = mark_primary(wx.Button(page, label="Build Universal Harness"), "Build exact rows plus enabled automatic rules")
        build.Bind(wx.EVT_BUTTON, self._build_links); actions.Add(build)
        root.Add(actions, 0, wx.EXPAND | wx.ALL, 8)
        root.Add(wx.StaticText(page, label="Every row is explicit. One source may feed several destinations when a splice is intentional."),
                 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        page.SetSizer(root)

    def _build_wires(self):
        page = self._page("4  Wire List"); root = wx.BoxSizer(wx.VERTICAL)
        fields = ("Wire", "Source", "Source Net", "Destination", "Destination Net", "AWG",
                  "Color", "Bundle", "Splice", "Length m", "Shield", "Status")
        self.wire_table = _table(page, fields, (85, 210, 160, 210, 160, 65, 85, 120, 100, 80, 120, 90))
        root.Add(self.wire_table, 1, wx.EXPAND | wx.ALL, 8)
        props = section(page, "Selected Wire / Bundle Properties"); parent = props.GetStaticBox()
        grid = wx.FlexGridSizer(2, 12, 6, 7)
        self.awg = wx.ComboBox(parent, choices=["30","28","26","24","22","20","18","16","14","12"], value="24", style=wx.CB_READONLY)
        self.color = wx.TextCtrl(parent); self.bundle_name = wx.TextCtrl(parent, value="MAIN")
        self.splice_name = wx.TextCtrl(parent); self.length = wx.TextCtrl(parent, value="1.0")
        self.shield = wx.ComboBox(parent, choices=["","Overall shield","Pair shield","Drain wire"], style=wx.CB_READONLY)
        for label, control in (("AWG",self.awg),("Color",self.color),("Bundle",self.bundle_name),
                               ("Splice",self.splice_name),("Length m",self.length),("Shield",self.shield)):
            grid.Add(wx.StaticText(parent,label=label),0,wx.ALIGN_CENTER_VERTICAL); grid.Add(control,1,wx.EXPAND)
        props.Add(grid, 1, wx.EXPAND | wx.ALL, 8); buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Apply to Selected (or All)", self._apply_properties),
                               ("Create / Update Bundle", self._apply_bundle),
                               ("Create / Update Splice", self._apply_splice)):
            button=wx.Button(parent,label=label); button.Bind(wx.EVT_BUTTON,handler); buttons.Add(button,0,wx.RIGHT,8)
        props.Add(buttons,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,8); root.Add(props,0,wx.EXPAND|wx.ALL,8); page.SetSizer(root)

    def _build_canvas(self):
        page=self._page("6  Draft Canvas"); root=wx.BoxSizer(wx.VERTICAL); tools=wx.BoxSizer(wx.HORIZONTAL)
        fit=wx.Button(page,label="Fit Drawing"); fit.Bind(wx.EVT_BUTTON,lambda _e:self.canvas.fit())
        refresh=wx.Button(page,label="Refresh Draft"); refresh.Bind(wx.EVT_BUTTON,lambda _e:self.canvas.set_links(self.links))
        tools.Add(fit,0,wx.RIGHT,8); tools.Add(refresh); tools.AddStretchSpacer()
        tools.Add(wx.StaticText(page,label="Mouse wheel: zoom   Drag: pan   Double-click: inspect connector"),0,wx.ALIGN_CENTER_VERTICAL)
        root.Add(tools,0,wx.EXPAND|wx.ALL,8); self.canvas=HarnessCanvas(page,self._show_connector)
        root.Add(self.canvas,1,wx.EXPAND|wx.LEFT|wx.RIGHT,8); self.canvas_detail=wx.StaticText(page,label="No connector selected.")
        root.Add(self.canvas_detail,0,wx.EXPAND|wx.ALL,8); page.SetSizer(root)

    def _build_outputs(self):
        page=self._page("7  Reports"); root=wx.BoxSizer(wx.VERTICAL); book=wx.Notebook(page)
        pin,net,bom=wx.Panel(book),wx.Panel(book),wx.Panel(book)
        book.AddPage(pin,"Pin Map"); book.AddPage(net,"Net Map"); book.AddPage(bom,"Harness BoM")
        self.pin_table=_table(pin,("Wire","Source","Source Net","Destination","Destination Net","Function","Bundle","Splice","Status"))
        s=wx.BoxSizer(wx.VERTICAL);s.Add(self.pin_table,1,wx.EXPAND);pin.SetSizer(s)
        self.net_table=_table(net,("Net / Signal","Endpoints","Wires","Bundles","Loads (A)"),(170,500,180,140,90))
        s=wx.BoxSizer(wx.VERTICAL);s.Add(self.net_table,1,wx.EXPAND);net.SetSizer(s)
        self.bom_table=_table(bom,("Category","Part Number","Description","Quantity","Unit","Notes"),(100,210,260,90,70,400))
        s=wx.BoxSizer(wx.VERTICAL);s.Add(self.bom_table,1,wx.EXPAND);bom.SetSizer(s)
        root.Add(book,1,wx.EXPAND|wx.ALL,8); actions=wx.BoxSizer(wx.HORIZONTAL)
        for label,kind in (("Export Pin Map CSV...","pin"),("Export Net Map CSV...","net"),
                           ("Export Wire List CSV...","wire"),("Export Harness BoM CSV...","bom"),
                           ("Export System Paths CSV...","system"),("Export Universal SVG...","svg"),
                           ("Preview Interactive HTML","preview-html"),("Export Interactive HTML...","html")):
            button=wx.Button(page,label=label);button.Bind(wx.EVT_BUTTON,lambda event,k=kind:self._export(k));actions.Add(button,0,wx.RIGHT,8)
        root.Add(actions,0,wx.ALL,8);page.SetSizer(root)

    def _build_system_map(self):
        page = self._page("5  System Paths"); root = wx.BoxSizer(wx.VERTICAL)
        controls = section(page, "End-to-end path scope"); parent = controls.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.system_source_refs = wx.TextCtrl(parent, value="U*")
        self.system_destination_refs = wx.TextCtrl(parent, value="U*")
        self.system_include_partial = wx.CheckBox(parent, label="Include incomplete connector-only paths")
        self.system_include_partial.SetValue(True)
        for label, control in (("Source IC / peripheral refs", self.system_source_refs),
                               ("Destination IC / peripheral refs", self.system_destination_refs)):
            row.Add(wx.StaticText(parent, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            row.Add(control, 1, wx.RIGHT, 12)
        row.Add(self.system_include_partial, 0, wx.ALIGN_CENTER_VERTICAL)
        controls.Add(row, 0, wx.EXPAND | wx.ALL, 8); root.Add(controls, 0, wx.EXPAND | wx.ALL, 8)
        fields = ("Path", "Source IC / Peripheral", "Source Function", "Source Net", "Source Connector",
                  "Wire", "Bundle", "Destination Connector", "Destination IC / Peripheral",
                  "Destination Function", "Destination Net", "Protocol", "Inline Components", "Status", "Confidence")
        widths = (75, 200, 150, 140, 120, 80, 100, 140, 220, 160, 140, 100, 240, 90, 90)
        self.system_table = _table(page, fields, widths); root.Add(self.system_table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (("Build End-to-End Paths", self._build_system_paths),
                               ("Preview Interactive HTML", self._preview_html),
                               ("Export Interactive HTML...", lambda event: self._export("html"))):
            button = wx.Button(page, label=label); button.Bind(wx.EVT_BUTTON, handler); actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(actions, 0, wx.ALL, 8)
        root.Add(wx.StaticText(page, label="Board-side paths must come from the safeguarded Pin Extractor controller map. File stem or Project column must match the pin document project."),
                 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10); page.SetSizer(root)

    def _import_files(self,_event):
        with wx.FileDialog(self,"Import board pin documents",wildcard="CSV (*.csv)|*.csv",
                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE) as dialog:
            if dialog.ShowModal()==wx.ID_OK:self._load_paths([Path(path) for path in dialog.GetPaths()])
    def _import_directory(self,_event):
        with wx.DirDialog(self,"Import a directory of board pin documents") as dialog:
            if dialog.ShowModal()==wx.ID_OK:self._load_paths(discover_pin_documents(dialog.GetPath()))
    def _import_signal_paths(self,_event):
        with wx.FileDialog(self,"Import Pin Extractor controller-map CSV files",wildcard="CSV (*.csv)|*.csv",
                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:
                imported=load_signal_path_documents([Path(path) for path in dialog.GetPaths()],MAX_PROJECTS)
                combined={(p.project,p.endpoint_reference,p.endpoint_pin,p.connector,p.connector_pin,p.ordered_path):p
                          for p in self.board_paths}
                combined.update({(p.project,p.endpoint_reference,p.endpoint_pin,p.connector,p.connector_pin,p.ordered_path):p
                                 for p in imported})
                self.board_paths=list(combined.values())
                projects=len({p.project for p in self.board_paths})
                self.path_source_status.SetLabel(f"Loaded {len(self.board_paths)} audited board paths from {projects} projects.")
                self._refresh_system_paths()
            except Exception as exc:wx.MessageBox(str(exc),"Signal path import failed",wx.OK|wx.ICON_ERROR)
    def _load_paths(self,paths):
        try:
            imported=load_pin_documents(paths,MAX_PROJECTS)
            combined={(r.project,r.connector,r.pin,r.net):r for r in self.records}
            combined.update({(r.project,r.connector,r.pin,r.net):r for r in imported})
            if len({r.project for r in combined.values()})>MAX_PROJECTS:raise ValueError(f"Import exceeds {MAX_PROJECTS} projects.")
            self.records=list(combined.values());self._refresh_sources()
            self.status.SetLabel(f"Loaded {len(self.records)} pins from {len({r.project for r in self.records})} projects.")
            self.guide.set_step(1,"Define connector correspondence, net rules, and external loads.")
        except Exception as exc:wx.MessageBox(str(exc),"Import failed",wx.OK|wx.ICON_ERROR)
    def _clear_sources(self,_event):
        self.records=[];self.virtual_loads=[];self.links=[];self.board_paths=[];self.system_paths=[]
        self.path_source_status.SetLabel("No audited IC/peripheral-to-connector path documents loaded.")
        self._refresh_sources();self._refresh_all()
    def _refresh_sources(self):
        groups={}
        for row in self.records:
            key=(row.project,row.connector,row.connector_part,row.endpoint_type);groups[key]=groups.get(key,0)+1
        rows=[{"Project":k[0],"Connector":k[1],"Pins":v,"Connector Part":k[2],"Endpoint Type":k[3]} for k,v in sorted(groups.items())]
        _fill(self.source_table,rows,("Project","Connector","Pins","Connector Part","Endpoint Type"))
        choices = [f"{project}:{connector}" for project, connector, _part, _kind in sorted(groups)]
        for control in (self.map_source, self.map_destination):
            current = control.GetValue(); control.SetItems(choices)
            if current in choices: control.SetValue(current)
    def _parse_loads(self):
        loads=[]
        for number,line in enumerate(self.load_text.GetValue().splitlines(),1):
            if not line.strip() or line.lstrip().startswith("#") or line.upper().startswith("PROJECT,"):continue
            fields=[part.strip() for part in line.split(",")]+[""]*8
            if not all(fields[:4]):raise ValueError(f"External load line {number} needs PROJECT,REFERENCE,PIN,NET.")
            try:current=float(fields[6] or 0)
            except ValueError as exc:raise ValueError(f"Invalid current on external load line {number}.") from exc
            loads.append(VirtualLoad(fields[0],fields[1],fields[2],fields[3],fields[4] or "External load",fields[5],current,fields[7]))
        return loads
    def _build_links(self,_event):
        try:
            self.virtual_loads=self._parse_loads();endpoints=self.records+virtual_load_records(self.virtual_loads);links=[]
            if self.match_nets.GetValue():links+=auto_link_multi(endpoints,self.net_pattern.GetValue() or "*",self.use_regex.GetValue(),self.include_power.GetValue())
            links+=connector_correspondence(endpoints,parse_connector_rules(self.connector_rules.GetValue()))
            manual = self._pin_map_rows()
            links += links_from_pin_map(endpoints, manual)
            unique={}
            for link in links:
                key=(link.source.project,link.source.connector,link.source.pin,link.destination.project,link.destination.connector,link.destination.pin)
                if key not in unique or link.notes.startswith("Manual pin map") or (unique[key].status!="linked" and link.status=="linked"):unique[key]=link
            self.links=list(unique.values())
            for index,link in enumerate(self.links,1):link.wire_id=f"W{index:05d}"
            self._refresh_all();issues=validate_links(self.links)
            self.status.SetLabel(f"{len(self.links)} wires across {len({r.project for r in endpoints})} projects | {len(issues)} findings.")
            self.guide.set_step(2,"Review mappings and assign bundle, splice, gauge, color, and length.")
            self.notebook.SetSelection(3)
        except Exception as exc:wx.MessageBox(str(exc),"Harness build failed",wx.OK|wx.ICON_ERROR)

    def _build_system_paths(self,_event=None):
        self._refresh_system_paths()
        self.status.SetLabel(f"Resolved {len(self.system_paths)} end-to-end IC/peripheral paths from {len(self.board_paths)} audited board paths.")

    def _refresh_system_paths(self):
        self.system_paths=build_system_signal_paths(
            self.links,self.board_paths,self.system_source_refs.GetValue() or "*",
            self.system_destination_refs.GetValue() or "*",self.system_include_partial.GetValue()) if self.links else []
        fields=("Path","Source IC / Peripheral","Source Function","Source Net","Source Connector","Wire","Bundle",
                "Destination Connector","Destination IC / Peripheral","Destination Function","Destination Net",
                "Protocol","Inline Components","Status","Confidence")
        _fill(self.system_table,system_signal_rows(self.system_paths),fields)

    def _append_pin_map_rows(self, rows):
        data = pin_map_editor_rows(rows); start = self.pin_grid.GetNumberRows()
        if data: self.pin_grid.AppendRows(len(data))
        fields = ("source_project", "source_connector", "source_pin", "destination_project",
                  "destination_connector", "destination_pin", "wire_id", "gauge_awg", "color",
                  "bundle", "splice", "length_m", "shield", "notes")
        for offset, item in enumerate(data):
            for column, field in enumerate(fields): self.pin_grid.SetCellValue(start + offset, column, item[field])

    def _pin_map_rows(self):
        rows = []
        for index in range(self.pin_grid.GetNumberRows()):
            values = [self.pin_grid.GetCellValue(index, column).strip() for column in range(14)]
            if not any(values): continue
            if not all(values[position] for position in range(6)):
                raise ValueError(f"Pin mapping row {index + 1} requires both project, connector, and pin endpoints.")
            try: length = float(values[11] or 1)
            except ValueError as exc: raise ValueError(f"Pin mapping row {index + 1} has an invalid length.") from exc
            rows.append(PinMapRow(*values[:6], values[6], values[7] or "24", values[8], values[9],
                                  values[10], length, values[12], values[13] or "Manual pin map"))
        return rows

    def _add_pin_map_row(self, _event):
        self._append_pin_map_rows([PinMapRow("", "", "", "", "", "")])
        self.pin_grid.MakeCellVisible(self.pin_grid.GetNumberRows() - 1, 0)

    def _delete_pin_map_rows(self, _event):
        selected = sorted(set(self.pin_grid.GetSelectedRows()), reverse=True)
        if not selected and self.pin_grid.GetGridCursorRow() >= 0: selected = [self.pin_grid.GetGridCursorRow()]
        for row in selected:
            if 0 <= row < self.pin_grid.GetNumberRows(): self.pin_grid.DeleteRows(row, 1)

    def _seed_pin_map(self, _event):
        try:
            source_project, source_connector = self.map_source.GetValue().split(":", 1)
            destination_project, destination_connector = self.map_destination.GetValue().split(":", 1)
        except ValueError:
            wx.MessageBox("Choose both connector endpoints first.", "Pin map", wx.OK | wx.ICON_INFORMATION); return
        source_pins = {r.pin for r in self.records if r.project == source_project and r.connector == source_connector}
        destination_pins = {r.pin for r in self.records if r.project == destination_project and r.connector == destination_connector}
        pins = sorted(source_pins & destination_pins, key=lambda value: (len(value), value.casefold()))
        self._append_pin_map_rows([PinMapRow(source_project, source_connector, pin,
                                             destination_project, destination_connector, pin)
                                   for pin in pins])
        self.status.SetLabel(f"Seeded {len(pins)} editable rows. Change destination pins for non-corresponding connectors.")

    def _validate_pin_map_ui(self, _event):
        try: issues = validate_pin_map(self.records + virtual_load_records(self._parse_loads()), self._pin_map_rows())
        except Exception as exc: wx.MessageBox(str(exc), "Pin map validation", wx.OK | wx.ICON_ERROR); return
        wx.MessageBox("\n".join(issues[:30]) if issues else "All explicit endpoints resolve.",
                      "Pin map validation", wx.OK | (wx.ICON_WARNING if issues else wx.ICON_INFORMATION))

    def _import_pin_map(self, _event):
        with wx.FileDialog(self, "Import explicit pin mapping", wildcard="CSV (*.csv)|*.csv",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            try: self._append_pin_map_rows(load_pin_map_csv(dialog.GetPath()))
            except Exception as exc: wx.MessageBox(str(exc), "Pin map import failed", wx.OK | wx.ICON_ERROR)

    def _export_pin_map(self, _event):
        with wx.FileDialog(self, "Export explicit pin mapping", wildcard="CSV (*.csv)|*.csv",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            try: export_rows(dialog.GetPath(), pin_map_editor_rows(self._pin_map_rows()))
            except Exception as exc: wx.MessageBox(str(exc), "Pin map export failed", wx.OK | wx.ICON_ERROR)
    def _wire_rows(self):
        return [{"Wire":l.wire_id,"Source":f"{l.source.project}:{l.source.connector}.{l.source.pin}","Source Net":l.source.net,
                 "Destination":f"{l.destination.project}:{l.destination.connector}.{l.destination.pin}","Destination Net":l.destination.net,
                 "AWG":l.gauge_awg,"Color":l.color,"Bundle":l.bundle,"Splice":l.splice,"Length m":f"{l.length_m:.3f}",
                 "Shield":l.shield,"Status":l.status} for l in self.links]
    def _refresh_all(self):
        _fill(self.wire_table,self._wire_rows(),("Wire","Source","Source Net","Destination","Destination Net","AWG","Color","Bundle","Splice","Length m","Shield","Status"))
        pins=pin_map_rows(self.links);nets=net_map_rows(self.links);bom=harness_bom(self.records+virtual_load_records(self.virtual_loads),self.links,self.bundles,self.splices)
        _fill(self.pin_table,pins,("Wire","Source","Source Net","Destination","Destination Net","Function","Bundle","Splice","Status"))
        _fill(self.net_table,nets,("Net / Signal","Endpoints","Wires","Bundles","Loads (A)"))
        _fill(self.bom_table,bom,("Category","Part Number","Description","Quantity","Unit","Notes"));self.canvas.set_links(self.links)
        self._refresh_system_paths()
    def _selected(self):
        result=[];index=self.wire_table.GetFirstSelected()
        while index!=-1:result.append(self.wire_table.GetItemText(index,0));index=self.wire_table.GetNextSelected(index)
        return result or [l.wire_id for l in self.links]
    def _apply_properties(self,_event):
        try:length=float(self.length.GetValue())
        except ValueError:wx.MessageBox("Length must be numeric.","Invalid length",wx.OK|wx.ICON_ERROR);return
        targets=set(self._selected())
        for link in self.links:
            if link.wire_id in targets:
                link.gauge_awg=self.awg.GetValue();link.color=self.color.GetValue();link.bundle=self.bundle_name.GetValue()
                link.splice=self.splice_name.GetValue();link.length_m=max(0,length);link.shield=self.shield.GetValue()
        self._refresh_all()
    def _apply_bundle(self,_event):
        name=self.bundle_name.GetValue().strip()
        if not name:return
        try:length=float(self.length.GetValue())
        except ValueError:length=1
        bundle=HarnessBundle(name,self._selected(),self.awg.GetValue(),self.shield.GetValue(),"",max(0,length))
        self.bundles=[b for b in self.bundles if b.name!=name]+[bundle];apply_bundle(self.links,bundle);self._refresh_all()
    def _apply_splice(self,_event):
        name=self.splice_name.GetValue().strip()
        if not name:return
        splice=HarnessSplice(name,self._selected());self.splices=[s for s in self.splices if s.splice_id!=name]+[splice]
        apply_splice(self.links,splice);self._refresh_all()
    def _show_connector(self,node):
        relevant=[l for l in self.links if node in (f"{l.source.project}:{l.source.connector}",f"{l.destination.project}:{l.destination.connector}")]
        self.canvas_detail.SetLabel(f"{node}: {len(relevant)} mapped wires | bundles: {', '.join(sorted({l.bundle or 'Unbundled' for l in relevant}))}")
    def _html(self):
        return interactive_harness_html(self.records+virtual_load_records(self.virtual_loads),self.links,
                                        self.bundles,self.splices,self.system_paths,
                                        "KiWay Interactive System Harness")
    def _preview_html(self,_event):
        if not self.links:return
        path=Path(tempfile.gettempdir())/"kiway-interactive-harness-preview.html"
        path.write_text(self._html(),encoding="utf-8");webbrowser.open(path.resolve().as_uri())
        self.status.SetLabel(f"Opened interactive preview: {path.name}")
    def _export(self,kind):
        if not self.links:return
        if kind=="preview-html":self._preview_html(None);return
        wildcard="HTML (*.html)|*.html" if kind=="html" else "SVG (*.svg)|*.svg" if kind=="svg" else "CSV (*.csv)|*.csv"
        with wx.FileDialog(self,"Export harness output",wildcard=wildcard,style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
            if kind=="wire":export_csv(path,self.links)
            elif kind=="pin":export_rows(path,pin_map_rows(self.links))
            elif kind=="net":export_rows(path,net_map_rows(self.links))
            elif kind=="bom":export_rows(path,harness_bom(self.records+virtual_load_records(self.virtual_loads),self.links,self.bundles,self.splices))
            elif kind=="system":export_rows(path,system_signal_rows(self.system_paths))
            elif kind=="html":Path(path).write_text(self._html(),encoding="utf-8")
            else:Path(path).write_text(universal_harness_svg(self.links),encoding="utf-8")
            self.status.SetLabel(f"Exported {Path(path).name}")
    def _help(self,_event):webbrowser.open(Path(__file__).with_name("help.html").resolve().as_uri())
