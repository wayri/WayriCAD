"""Extract test-point descriptors and export manufacturing documentation."""

from __future__ import annotations

import csv
import html
import os
import re
from typing import Any, Dict, Iterable, List, Sequence

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import footprint, select_items
from .guided_ui import add_workflow
from .fixture import collect_fixture_points, generate_fixture_board


TYPE_LABELS = {
    "TM": "Telemetry",
    "TC": "Telecommand",
    "TA": "Telemetry Analog",
    "TD": "Telemetry Digital",
    "CA": "Command Analog",
    "CD": "Command Digital",
}


def _fields(footprint: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
    getter = getattr(footprint, "GetFields", None)
    if not callable(getter):
        return result
    try:
        for field in getter():
            result[str(field.GetName())] = str(field.GetText())
    except Exception:
        return result
    return result


def parse_net_descriptor(net_name: str, board_order: Sequence[str] = ()) -> Dict[str, str]:
    raw = str(net_name or "")
    upper = raw.upper()
    board_hits = []
    for board in board_order:
        board = str(board).strip().upper()
        if not board:
            continue
        for match in re.finditer(re.escape(board), upper):
            before = upper[match.start() - 1] if match.start() else ""
            after = upper[match.end()] if match.end() < len(upper) else ""
            if before.isalnum() or after.isalnum():
                continue
            board_hits.append((match.start(), match.end(), board))
    board_hits.sort(key=lambda item: (item[0], item[1]))
    spans = []
    for hit in board_hits:
        if not spans or hit[0] >= spans[-1][1]:
            spans.append(hit)
    boards = [item[2] for item in spans]
    markers = list(re.finditer(r"(?<![A-Z0-9])(TM|TC|TA|TD|CA|CD)(?![A-Z0-9])", upper))
    kind = markers[0].group(1) if markers else ""
    masked = list(upper)
    for start, end, _board in spans:
        for index in range(start, end):
            masked[index] = " "
    for marker_match in markers:
        for index in range(marker_match.start(), marker_match.end()):
            masked[index] = " "
    signal_tokens = [token for token in re.findall(r"[A-Z0-9]+", "".join(masked)) if token not in {"SIGNAL", "SIG", "NET"}]
    source = boards[0] if boards else ""
    destination = boards[1] if len(boards) > 1 else ""
    return {
        "Type": kind,
        "Type Description": TYPE_LABELS.get(kind, ""),
        "Source Board": source,
        "Destination Board": destination,
        "Signal": "_".join(signal_tokens),
    }


def _pin_function(pad: Any) -> str:
    for name in ("GetPinFunction", "GetName"):
        getter = getattr(pad, name, None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                continue
            if value:
                return str(value)
    return ""


def _is_pass_through(footprint: Any) -> bool:
    reference = str(footprint.GetReference()).upper()
    fields = _fields(footprint)
    return reference.startswith(("R", "C", "L", "FB", "F", "JP", "JMP")) or bool(str(fields.get("NetTie_Path", "")).strip())


def resolve_connected_ics(board: Any, start_net: str, max_hops: int = 8) -> List[Dict[str, str]]:
    """Trace a TP net through series parts to terminal IC pins."""
    net_map: Dict[str, List[Any]] = {}
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            net_name = str(getattr(pad, "GetNetname", lambda: "")())
            if net_name:
                net_map.setdefault(net_name, []).append((footprint, pad))
    queue = [(start_net, [], [f"[{start_net}]"])]
    seen_nets = {start_net}
    endpoints: Dict[tuple[str, str], Dict[str, str]] = {}
    while queue:
        net_name, intermediates, path = queue.pop(0)
        if len(intermediates) > max_hops:
            continue
        for footprint, pad in net_map.get(net_name, []):
            reference = str(footprint.GetReference())
            upper = reference.upper()
            pin = str(pad.GetNumber())
            if upper.startswith(("U", "IC", "Q", "M")):
                endpoints.setdefault((reference, pin), {
                    "Reference": reference,
                    "Pin": pin,
                    "Pin Function": _pin_function(pad),
                    "Value": str(footprint.GetValue()),
                    "Terminal Net": net_name,
                    "Intermediates": ", ".join(intermediates),
                    "Path": " -> ".join(path + [f"{reference}.{pin}"]),
                })
                continue
            if not _is_pass_through(footprint) or reference in intermediates:
                continue
            for other_pad in footprint.Pads():
                other_net = str(getattr(other_pad, "GetNetname", lambda: "")())
                if not other_net or other_net == net_name or other_net in seen_nets:
                    continue
                seen_nets.add(other_net)
                queue.append((
                    other_net,
                    intermediates + [reference],
                    path + [f"{reference}.{pin}", f"{reference}.{other_pad.GetNumber()}", f"[{other_net}]"],
                ))
    return sorted(endpoints.values(), key=lambda row: (row["Reference"], row["Pin"]))


def extract_test_points(board: Any, descriptor_field: str = "TP_Descriptor", board_order: Sequence[str] = ()) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for footprint in board.GetFootprints():
        reference = str(footprint.GetReference())
        value = str(footprint.GetValue())
        if not (reference.upper().startswith("TP") or "TESTPOINT" in value.upper()):
            continue
        fields = _fields(footprint)
        descriptor = fields.get(descriptor_field, "")
        if not descriptor:
            descriptor = fields.get("Descriptor", fields.get("Function", fields.get("Description", "")))
        for pad in footprint.Pads():
            net = str(pad.GetNetname()) if hasattr(pad, "GetNetname") else ""
            parsed = parse_net_descriptor(net, board_order)
            endpoints = resolve_connected_ics(board, net)
            rows.append({
                "TP Reference": reference,
                "Value": value,
                "Footprint": str(footprint.GetFPIDAsString()) if hasattr(footprint, "GetFPIDAsString") else "",
                "Pad": str(pad.GetNumber()),
                "Net Name": net,
                "Descriptor": descriptor,
                "Type": parsed["Type"],
                "Type Description": parsed["Type Description"],
                "Source Board": parsed["Source Board"],
                "Destination Board": parsed["Destination Board"],
                "Signal": parsed["Signal"],
                "Connected IC": "; ".join(item["Reference"] for item in endpoints),
                "IC Pin": "; ".join(item["Pin"] for item in endpoints),
                "IC Pin Function": "; ".join(item["Pin Function"] for item in endpoints),
                "IC Value": "; ".join(item["Value"] for item in endpoints),
                "Terminal Net": "; ".join(item["Terminal Net"] for item in endpoints),
                "Intermediate Components": "; ".join(item["Intermediates"] for item in endpoints),
                "Trace Path": " | ".join(item["Path"] for item in endpoints),
                "Notes": fields.get("Notes", fields.get("Comment", "")),
            })
    return rows


class TestPointDescriptorPlugin(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "WayriCAD Test Point Descriptor Extractor"
        self.category = "Documentation"
        self.description = "Extract test-point nets, descriptors, and TM/TC metadata to engineering documents."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.version = "3.1.0"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            TestPointFrame(None, board).Show()
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Test Point Descriptor Extractor", wx.OK | wx.ICON_ERROR)


class TestPointFrame(wx.Frame):
    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="WayriCAD Test Point Descriptor Extractor", size=(1280, 720), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((960, 600))
        self.board = board
        self.rows: List[Dict[str, str]] = []
        self.sort_column = 0
        self.sort_ascending = True
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(
            panel, root, "Test Point Descriptor Extractor",
            "Configure descriptor conventions, preview parsed records, then export reviewed documentation.",
            ("Configure", "Review preview", "Export"),
        )
        settings = wx.CollapsiblePane(panel, label="Extraction settings", style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        options_parent = settings.GetPane()
        options_box = wx.BoxSizer(wx.VERTICAL)
        options = wx.FlexGridSizer(0, 2, 6, 8)
        self.field = wx.TextCtrl(options_parent, value="TP_Descriptor")
        self.boards = wx.TextCtrl(options_parent, value="DEMO_CTRL,DEMO_SENSOR,DEMO_POWER,DEMO_IO")
        self.consolidate = wx.CheckBox(options_parent, label="Consolidate duplicate TP/net records")
        self.consolidate.SetValue(True)
        self.probe_type = wx.ComboBox(options_parent, choices=["P75 spring probe", "P100 spring probe", "P160 spring probe", "Custom"], style=wx.CB_READONLY)
        self.probe_type.SetSelection(0)
        options.Add(wx.StaticText(options_parent, label="Descriptor field:"), 0, wx.ALIGN_CENTER_VERTICAL)
        options.Add(self.field, 1, wx.EXPAND)
        options.Add(wx.StaticText(options_parent, label="Board order (comma separated):"), 0, wx.ALIGN_CENTER_VERTICAL)
        options.Add(self.boards, 1, wx.EXPAND)
        options.Add(self.consolidate, 0, wx.ALIGN_CENTER_VERTICAL)
        options.Add(self.probe_type, 1, wx.EXPAND)
        options.AddGrowableCol(1, 1)
        options_box.Add(options, 0, wx.EXPAND | wx.ALL, 8)
        options_parent.SetSizer(options_box)
        settings.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda event: panel.Layout())
        root.Add(settings, 0, wx.EXPAND | wx.ALL, 8)
        self.list = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.select_test_point)
        self.list.Bind(wx.EVT_LIST_COL_CLICK, self.on_sort_column)
        columns = ("TP Reference", "Net Name", "Descriptor", "Type", "Connected IC", "IC Pin", "IC Pin Function", "Terminal Net", "Intermediate Components", "Trace Path", "Source Board", "Destination Board", "Signal", "Notes")
        for index, label in enumerate(columns):
            self.list.InsertColumn(index, label, width=145 if index not in (2, 7) else 210)
        root.Add(self.list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        row = wx.WrapSizer(wx.HORIZONTAL)
        for label, handler in (("Refresh Preview", self.extract), ("Export…", self.export_menu)):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            row.Add(button, 0, wx.ALL, 5)
        select = wx.Button(panel, label="Select on PCB")
        select.Bind(wx.EVT_BUTTON, self.select_test_point)
        row.Add(select, 0, wx.ALL, 5)
        help_btn = wx.Button(panel, label="Help")
        help_btn.Bind(wx.EVT_BUTTON, lambda _event: open_help(self))
        row.Add(help_btn, 0, wx.ALL, 5)
        root.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        self.status = wx.StaticText(panel, label="Ready.")
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        panel.SetSizer(root)
        self.extract(None)
        self.Centre()

    def _refresh_list(self) -> None:
        self.list.DeleteAllItems()
        keys = ("TP Reference", "Net Name", "Descriptor", "Type", "Connected IC", "IC Pin", "IC Pin Function", "Terminal Net", "Intermediate Components", "Trace Path", "Source Board", "Destination Board", "Signal", "Notes")
        for row in self.rows:
            index = self.list.InsertItem(self.list.GetItemCount(), row.get(keys[0], ""))
            for col, key in enumerate(keys[1:], 1):
                self.list.SetItem(index, col, row.get(key, ""))
        self.status.SetLabel(f"Extracted {len(self.rows)} test-point records.")
        self.workflow.set_step(1 if self.rows else 0, "Cross-select uncertain rows and verify parsed endpoints/types before export." if self.rows else "Check the descriptor field and TP naming, then Extract again.")

    def export_menu(self, event: Any) -> None:
        menu = wx.Menu()
        for label, handler in (("CSV", self.export_csv), ("Markdown", self.export_markdown), ("HTML", self.export_html), ("Fixture Plan", self.export_fixture_plan), ("Fixture PCB…", self.generate_fixture_pcb)):
            item = menu.Append(wx.ID_ANY, label)
            menu.Bind(wx.EVT_MENU, handler, id=item.GetId())
        try:
            event.GetEventObject().PopupMenu(menu)
        finally:
            menu.Destroy()

    def extract(self, _event: Any) -> None:
        board_order = [item.strip() for item in self.boards.GetValue().split(",") if item.strip()]
        self.rows = extract_test_points(self.board, self.field.GetValue().strip() or "TP_Descriptor", board_order)
        if self.consolidate.GetValue():
            unique = {}
            for row in self.rows:
                key = (row.get("TP Reference", ""), row.get("Pad", ""), row.get("Net Name", ""))
                unique.setdefault(key, row)
            self.rows = list(unique.values())
        self._refresh_list()

    def on_sort_column(self, event: Any) -> None:
        keys = ("TP Reference", "Net Name", "Descriptor", "Type", "Connected IC", "IC Pin", "IC Pin Function", "Terminal Net", "Intermediate Components", "Trace Path", "Source Board", "Destination Board", "Signal", "Notes")
        column = event.GetColumn()
        self.sort_ascending = not self.sort_ascending if column == self.sort_column else True
        self.sort_column = column
        key = keys[column]
        self.rows.sort(key=lambda row: self._natural_key(row.get(key, "")), reverse=not self.sort_ascending)
        self._refresh_list()

    @staticmethod
    def _natural_key(value: str) -> list[Any]:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value))]

    def export_fixture_plan(self, _event: Any) -> None:
        path = self._save_path("CSV files (*.csv)|*.csv")
        if not path:
            return
        fields = ("Fixture Channel", "TP Reference", "TP Pad", "Net Name", "Probe Type", "Connected IC", "IC Pin", "IC Pin Function", "Trace Path")
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
            for channel, row in enumerate(self.rows, 1):
                writer.writerow({"Fixture Channel": channel, "TP Reference": row.get("TP Reference", ""), "TP Pad": row.get("Pad", ""), "Net Name": row.get("Net Name", ""), "Probe Type": self.probe_type.GetValue(), "Connected IC": row.get("Connected IC", ""), "IC Pin": row.get("IC Pin", ""), "IC Pin Function": row.get("IC Pin Function", ""), "Trace Path": row.get("Trace Path", "")})
        self.status.SetLabel(f"Wrote reviewed bed-of-nails channel assignment plan to {path}")

    def generate_fixture_pcb(self, _event: Any) -> None:
        points = collect_fixture_points(self.board, self.rows)
        if not points:
            wx.MessageBox("No extracted TP pads with PCB coordinates are available. Extract and review the table first.", "Fixture preview required", wx.OK | wx.ICON_INFORMATION)
            return
        message = (
            f"Generate a separate fixture PCB for {len(points)} reviewed probe channels?\n\n"
            "The source PCB is not modified. The generated escape routing is a manufacturing starting point: "
            "assign the actual connector footprint, inspect mechanics, clean up routing, and run DRC before fabrication."
        )
        if wx.MessageBox(message, "Generate reviewed bed-of-nails fixture", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        with wx.FileDialog(self, "Write bed-of-nails fixture PCB", wildcard="KiCad PCB (*.kicad_pcb)|*.kicad_pcb", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            content = generate_fixture_board(points, self.probe_type.GetValue())
            with open(dialog.GetPath(), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            self.status.SetLabel(f"Generated {len(points)}-channel fixture board at {dialog.GetPath()}; open it separately and run DRC.")

    def select_test_point(self, event: Any) -> None:
        index = event.GetIndex() if hasattr(event, "GetIndex") else self.list.GetFirstSelected()
        if index < 0 or index >= len(self.rows):
            wx.MessageBox("Select a test-point row first.", "WayriCAD", wx.OK | wx.ICON_INFORMATION)
            return
        references = [self.rows[index].get("TP Reference", "")]
        references.extend(item.strip() for item in self.rows[index].get("Connected IC", "").split(";") if item.strip())
        select_items(self.board, [footprint(self.board, reference) for reference in references])
        self.status.SetLabel(f"Selected TP and {len(references) - 1} connected IC endpoint(s) on the PCB.")
        self.workflow.set_step(2, "Continue reviewing records or export the approved document.")

    def _save_path(self, wildcard: str) -> str:
        with wx.FileDialog(self, "Export test-point documentation", wildcard=wildcard, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return ""
            return dialog.GetPath()

    def export_csv(self, _event: Any) -> None:
        path = self._save_path("CSV files (*.csv)|*.csv")
        if not path: return
        keys = list(self.rows[0].keys()) if self.rows else ["TP Reference", "Net Name", "Descriptor"]
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys); writer.writeheader(); writer.writerows(self.rows)
        self.status.SetLabel(f"Wrote {path}")
        self.workflow.set_step(3, "Open the exported CSV and complete review/sign-off.")

    def _markdown(self) -> str:
        keys = list(self.rows[0].keys()) if self.rows else ["TP Reference", "Net Name", "Descriptor"]
        lines = ["# Test Point Descriptor Report", "", "| " + " | ".join(keys) + " |", "|" + "|".join(["---"] * len(keys)) + "|"]
        for row in self.rows:
            lines.append("| " + " | ".join(str(row.get(key, "")).replace("|", "\\|").replace("\n", " ") for key in keys) + " |")
        return "\n".join(lines) + "\n"

    def export_markdown(self, _event: Any) -> None:
        path = self._save_path("Markdown files (*.md)|*.md")
        if path:
            with open(path, "w", encoding="utf-8") as handle: handle.write(self._markdown())
            self.status.SetLabel(f"Wrote {path}")
            self.workflow.set_step(3, "Open the exported Markdown and complete review/sign-off.")

    def export_html(self, _event: Any) -> None:
        path = self._save_path("HTML files (*.html)|*.html")
        if not path: return
        keys = list(self.rows[0].keys()) if self.rows else ["TP Reference", "Net Name", "Descriptor"]
        table = "<table><thead><tr>" + "".join(f"<th>{html.escape(key)}</th>" for key in keys) + "</tr></thead><tbody>"
        for row in self.rows:
            table += "<tr>" + "".join(f"<td>{html.escape(str(row.get(key, '')))}</td>" for key in keys) + "</tr>"
        table += "</tbody></table>"
        document = "<!doctype html><html><head><meta charset='utf-8'><style>body{font-family:Arial;margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd3da;padding:6px;text-align:left}th{background:#edf2f7}</style></head><body><h1>Test Point Descriptor Report</h1>" + table + "</body></html>"
        with open(path, "w", encoding="utf-8") as handle: handle.write(document)
        self.status.SetLabel(f"Wrote {path}")
        self.workflow.set_step(3, "Open the exported HTML and complete review/sign-off.")
