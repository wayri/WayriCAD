"""Read-only native imported CAM/reference netlist comparison."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import wx

from .fab_compare_report import (
    NOTICE, assert_sources_current, build_report, export_report, report_rows,
    source_snapshot, validate_report,
)

MAX_VISIBLE_ROWS = 5000
MAX_DETAIL_CHARS = 500000
MAX_CELL_CHARS = 500


def detail_preview(value, limit=MAX_DETAIL_CHARS):
    chunks, length = [], 0
    for chunk in json.JSONEncoder(indent=2, ensure_ascii=False, allow_nan=False).iterencode(value):
        if length+len(chunk) > limit:
            chunks.append(chunk[:max(0, limit-length)])
            chunks.append("\n[Details truncated at "+str(limit)+" characters; export JSON for the complete pin map.]")
            break
        chunks.append(chunk)
        length += len(chunk)
    return "".join(chunks)


def compare_files(reference_path, observed_path, confirmed, board_path=None, *, cancel=None):
    """Pure file/data worker: never load pcbnew objects or access native controls."""
    from .fab_compare import load_netlist, compare_netlists
    from .fab_reference import check_reference_receipt

    def check():
        if cancel and cancel():
            raise InterruptedError("Comparison cancelled.")

    check()
    sources = [source_snapshot(reference_path, "reference"), source_snapshot(observed_path, "observed CAM")]
    if board_path:
        sources.append(source_snapshot(board_path, "board context"))
    binding = check_reference_receipt(reference_path, board_path)
    if binding.get("receipt_path"):
        receipt_source = source_snapshot(binding["receipt_path"], "native receipt")
        if receipt_source["sha256"] != binding["receipt_sha256"]:
            raise ValueError("Native reference receipt changed while binding the comparison.")
        sources.append(receipt_source)
    reference = load_netlist(reference_path)
    check()
    observed = load_netlist(observed_path)
    check()
    comparison = compare_netlists(reference, observed, confirm_independent_cam=confirmed)
    comparison["reference_binding"] = binding
    check()
    assert_sources_current(sources)
    result = build_report(comparison, sources=sources, board_path=board_path)
    check()
    return result


def _reference_files(board, destination, *, cancel=None):
    from .fab_reference import export_reference
    sources = [source_snapshot(board, "board context")]
    receipt = export_reference(board, destination, cancel=cancel)
    if cancel and cancel():
        raise InterruptedError("Reference export cancelled.")
    assert_sources_current(sources)
    output = source_snapshot(destination, "design reference")
    if (receipt.get("basis") != "design-netlist" or receipt.get("output_sha256") != output["sha256"]
            or receipt.get("source_sha256") != sources[0]["sha256"]):
        raise ValueError("Native reference receipt does not match its output.")
    return dict(receipt=receipt, destination=destination, sources=sources+[output])


def _worker(snapshot, cancelled, closed, lock, complete, function=None):
    result, error = None, None
    try:
        result = (function or compare_files)(*snapshot, cancel=cancelled.is_set)
    except InterruptedError:
        cancelled.set()
    except Exception as exc:
        error = str(exc)
    with lock:
        if not closed.is_set():
            wx.CallAfter(complete, result, error)


class FabCompareDialog(wx.Dialog):
    def __init__(self, parent, reference_path=None, board_path=None):
        super().__init__(parent, title="Fabrication Net Comparison", size=(1120, 820),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((800, 620))
        self.board_path = str(Path(board_path).absolute()) if board_path else None
        self.report = None
        self._accepted_inputs = None
        self._generation = 0
        self._thread = None
        self._cancelled = None
        self._closed = threading.Event()
        self._dispatch_lock = threading.Lock()
        self._rows = {}
        self._order = []
        self._sort_column = None
        self._ascending = True

        root = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(0, 2, 8, 12)
        form.AddGrowableCol(1)
        wildcard = "Netlist files (*.d356;*.ipc;*.json)|*.d356;*.ipc;*.json|All files (*.*)|*.*"
        form.Add(wx.StaticText(self, label="Design reference"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.reference = wx.FilePickerCtrl(self, path=str(reference_path or ""), wildcard=wildcard,
            style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        form.Add(self.reference, 1, wx.EXPAND)
        form.Add(wx.StaticText(self, label="Observed CAM netlist"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.observed = wx.FilePickerCtrl(self, wildcard=wildcard,
            style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
        form.Add(self.observed, 1, wx.EXPAND)
        root.Add(form, 0, wx.EXPAND | wx.ALL, 12)
        self.confirm = wx.CheckBox(self, label="I reviewed that the observed netlist was independently extracted from CAM data")
        root.Add(self.confirm, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        if self.board_path:
            context = wx.StaticText(self, label="Saved PCB context: "+Path(self.board_path).name)
            context.SetToolTip(self.board_path)
            root.Add(context, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        commands = wx.BoxSizer(wx.HORIZONTAL)
        self.compare_button = wx.Button(self, label="Compare")
        self.compare_button.SetDefault()
        self.cancel_button = wx.Button(self, label="Cancel operation")
        self.cancel_button.Disable()
        self.cancel_button.SetToolTip("Cancel between parser/comparator calls; an active call cannot be interrupted.")
        self.export_button = wx.Button(self, label="Export report...")
        self.export_button.Disable()
        self.reference_button = wx.Button(self, label="Export design reference...") if self.board_path else None
        help_button = wx.Button(self, label="Help")
        for control in (self.compare_button, self.cancel_button, self.export_button):
            commands.Add(control, 0, wx.RIGHT, 8)
        if self.reference_button is not None:
            commands.Add(self.reference_button, 0, wx.RIGHT, 8)
        commands.AddStretchSpacer()
        commands.Add(help_button)
        root.Add(commands, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.notice = wx.StaticText(self, label="No comparison accepted. MATCH is not fabrication approval.")
        root.Add(self.notice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.summary = wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 95))
        root.Add(self.summary, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        split.SetMinimumPaneSize(100)
        split.SetSashGravity(.55)
        self.table = wx.ListCtrl(split, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate((("Type", 85), ("Identity", 150), ("Design nets", 230),
                ("CAM nets", 160), ("Pins", 220), ("Finding", 360))):
            self.table.InsertColumn(index, label, width=width)
        self.details = wx.TextCtrl(split, style=wx.TE_READONLY | wx.TE_MULTILINE | wx.HSCROLL)
        split.SplitHorizontally(self.table, self.details, 245)
        root.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(root)
        for picker in (self.reference, self.observed):
            picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.invalidate)
            if picker.GetTextCtrl():
                picker.GetTextCtrl().Bind(wx.EVT_TEXT, self.invalidate)
        self.confirm.Bind(wx.EVT_CHECKBOX, self.invalidate)
        self.compare_button.Bind(wx.EVT_BUTTON, self.compare)
        self.cancel_button.Bind(wx.EVT_BUTTON, self.cancel)
        self.export_button.Bind(wx.EVT_BUTTON, self.export)
        if self.reference_button is not None:
            self.reference_button.Bind(wx.EVT_BUTTON, self.export_reference)
        help_button.Bind(wx.EVT_BUTTON, self.help)
        self.table.Bind(wx.EVT_LIST_COL_CLICK, self.sort)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.select)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _inputs(self):
        reference, observed = self.reference.GetPath().strip(), self.observed.GetPath().strip()
        if not reference or not observed:
            raise ValueError("Choose both the saved design reference and observed CAM netlist.")
        return reference, observed, bool(self.confirm.GetValue()), self.board_path

    def _clear(self):
        self.report = None
        self._accepted_inputs = None
        self._rows = {}
        self._order = []
        self.table.DeleteAllItems()
        self.details.SetValue("")
        self.summary.SetValue("")
        self.export_button.Disable()

    def invalidate(self, event=None):
        if self._closed.is_set():
            return
        self._generation += 1
        self._clear()
        if self._cancelled is not None:
            self._cancelled.set()
            self.cancel_button.Disable()
            self.notice.SetLabel("Inputs changed; cancelling. An active parser/comparator call cannot be interrupted.")
        else:
            self.notice.SetLabel("Inputs changed; compare again before export.")
        if event is not None:
            event.Skip()

    def compare(self, event=None):
        if self._closed.is_set() or self._thread is not None:
            return
        self._clear()
        try:
            snapshot = copy.deepcopy(self._inputs())
        except ValueError as exc:
            self.notice.SetLabel(str(exc))
            return
        generation = self._generation
        cancelled = threading.Event()
        self._cancelled = cancelled
        self.compare_button.Disable()
        if self.reference_button is not None:
            self.reference_button.Disable()
        self.cancel_button.Enable()
        self.notice.SetLabel("Comparing saved endpoint partitions...")
        complete = lambda report, error: self._complete(generation, snapshot, cancelled, report, error)
        self._thread = threading.Thread(target=_worker,
            args=(snapshot, cancelled, self._closed, self._dispatch_lock, complete),
            name="fab-net-compare", daemon=True)
        try:
            self._thread.start()
        except Exception as exc:
            self._complete(generation, snapshot, cancelled, None, str(exc))

    def cancel(self, event=None):
        if self._cancelled is not None and not self._closed.is_set():
            self._cancelled.set()
            self.cancel_button.Disable()
            self.notice.SetLabel("Cancelling; an active parser/comparator call cannot be interrupted.")

    def _complete(self, generation, snapshot, cancelled, report, error):
        if self._closed.is_set():
            return
        self._thread = None
        self._cancelled = None
        self.compare_button.Enable()
        if self.reference_button is not None:
            self.reference_button.Enable()
        self.cancel_button.Disable()
        try:
            if cancelled.is_set() or generation != self._generation or snapshot != self._inputs():
                raise InterruptedError("Comparison cancelled or inputs changed; no result accepted.")
            if error:
                raise ValueError(error)
            validate_report(report)
            self.report = report
            self._accepted_inputs = snapshot
            self._rows = dict(enumerate(report_rows(report, limit=MAX_VISIBLE_ROWS), 1))
            self._order = list(self._rows)
            self._render_rows()
            summary = report["summary"]
            self.summary.SetValue(
                f"Status: {report['status']} | Net compare errors: {summary['short_groups']+summary['open_groups']} "
                f"| Short groups: {summary['short_groups']} | Open groups: {summary['open_groups']}\n"
                f"Matched pins: {summary['matched_pins']} | Missing: {summary['missing_pins']} "
                f"| Extra: {summary['extra_pins']} | Complete: {summary['complete']}\n"
                f"Independent CAM confirmed: {report['independence']['confirmed']} | Fabrication verified: False\n"
                f"Reference binding: {report['reference_binding']['status']}\n"
                f"Report SHA-256: {report['report_metadata']['sha256']}")
            total = len(report.get("shorts", []))+len(report.get("opens", []))+len(report.get("issues", []))
            total += sum(bool(report.get("coverage", {}).get(key)) for key in ("missing_pins", "extra_pins"))
            self.notice.SetLabel(f"Showing {len(self._rows)} of {total} finding rows; exports retain all. MATCH is not fabrication approval.")
            self.export_button.Enable()
            if self._order:
                self.table.Select(0)
                self._show_row(self._order[0])
            else:
                self.details.SetValue(detail_preview({key: report[key] for key in
                    ("coverage", "independence", "reference_binding", "provenance", "limits")}))
        except Exception as exc:
            self._clear()
            self.notice.SetLabel(str(exc))
            self.notice.SetToolTip(str(exc))

    def _render_rows(self, selected=None):
        self.table.Freeze()
        try:
            self.table.DeleteAllItems()
            for key in self._order:
                row = self._rows[key]
                index = self.table.InsertItem(self.table.GetItemCount(), row["kind"])
                for column, name in enumerate(("id", "reference_nets", "observed_nets", "pins", "message"), 1):
                    text = row[name]
                    self.table.SetItem(index, column, text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS]+"...")
                self.table.SetItemData(index, key)
                if key == selected:
                    self.table.Select(index)
        finally:
            self.table.Thaw()

    def _show_row(self, key):
        row = self._rows.get(key)
        if row is not None:
            self.details.SetValue(row["kind"]+" "+row["id"]+"\n\n"+
                detail_preview(row["details"]))

    def select(self, event):
        self._show_row(self.table.GetItemData(event.GetIndex()))

    def sort(self, event):
        column = event.GetColumn()
        keys = ("kind", "id", "reference_nets", "observed_nets", "pins", "message")
        if not 0 <= column < len(keys):
            return
        selected = self.table.GetFirstSelected()
        selected = self.table.GetItemData(selected) if selected >= 0 else None
        self._ascending = not self._ascending if column == self._sort_column else True
        self._sort_column = column
        self._order.sort(key=lambda key: (self._rows[key][keys[column]].casefold(), self._rows[key]["id"], key),
                         reverse=not self._ascending)
        self._render_rows(selected)
        if selected is not None:
            self._show_row(selected)

    def export(self, event=None):
        try:
            if self.report is None or self._thread is not None or self._inputs() != self._accepted_inputs:
                raise ValueError("Compare the current inputs before export.")
            validate_report(self.report)
            wildcard = "JSON evidence (*.json)|*.json|HTML report (*.html)|*.html|CSV table (*.csv)|*.csv|Text report (*.txt)|*.txt"
            with wx.FileDialog(self, "Export fabrication net comparison", wildcard=wildcard,
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                suffix = (".json", ".html", ".csv", ".txt")[dialog.GetFilterIndex()]
                destination = Path(dialog.GetPath())
                if destination.suffix.lower() != suffix:
                    destination = destination.with_suffix(suffix)
                export_report(self.report, destination)
                self.notice.SetLabel("Exported source-bound comparison: "+destination.name)
        except Exception as exc:
            self.invalidate()
            self.notice.SetLabel(str(exc))
            self.notice.SetToolTip(str(exc))

    def help(self, event=None):
        try:
            from .wayricad_runtime.help import open_help
        except ModuleNotFoundError as exc:
            if exc.name != __package__+".wayricad_runtime":
                raise
            from wayricad_runtime.help import open_help
        open_help(self, Path(__file__).parent/"fab_compare_help.html", title="Fabrication Net Comparison Help")

    def export_reference(self, event=None):
        if self._closed.is_set() or self._thread is not None or not self.board_path:
            return
        with wx.FileDialog(self, "Export new saved-design reference", wildcard="IPC-D-356 (*.d356)|*.d356",
                           style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = str(Path(dialog.GetPath()).with_suffix(".d356"))
        self._clear()
        snapshot = (self.board_path, destination)
        generation = self._generation
        cancelled = threading.Event()
        self._cancelled = cancelled
        self.compare_button.Disable()
        self.reference_button.Disable()
        self.cancel_button.Enable()
        self.notice.SetLabel("Exporting a private saved-PCB copy; design netlist only, not CAM extraction...")
        complete = lambda result, error: self._reference_complete(generation, snapshot, cancelled, result, error)
        self._thread = threading.Thread(target=_worker,
            args=(snapshot, cancelled, self._closed, self._dispatch_lock, complete, _reference_files),
            name="fab-reference-export", daemon=True)
        try:
            self._thread.start()
        except Exception as exc:
            self._reference_complete(generation, snapshot, cancelled, None, str(exc))

    def _reference_complete(self, generation, snapshot, cancelled, result, error):
        if self._closed.is_set():
            return
        self._thread = None
        self._cancelled = None
        self.compare_button.Enable()
        self.reference_button.Enable()
        self.cancel_button.Disable()
        try:
            if cancelled.is_set() or generation != self._generation or snapshot[0] != self.board_path:
                raise InterruptedError("Reference export cancelled or inputs changed. A completed new output may remain at the chosen path.")
            if error:
                raise ValueError(error)
            assert_sources_current(result["sources"])
            self.reference.SetPath(result["destination"])
            self.invalidate()
            self.notice.SetLabel("Design reference and receipt exported. Choose independent observed CAM data before comparison.")
        except Exception as exc:
            self._clear()
            self.notice.SetLabel(str(exc))
            self.notice.SetToolTip(str(exc))

    def _deactivate(self):
        with self._dispatch_lock:
            self._closed.set()
            if self._cancelled is not None:
                self._cancelled.set()

    def _on_close(self, event):
        self._deactivate()
        event.Skip()

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self._deactivate()
        event.Skip()

    def Destroy(self):
        self._deactivate()
        return super().Destroy()


def open_dialog(parent, reference_path=None, board_path=None):
    with FabCompareDialog(parent, reference_path=reference_path, board_path=board_path) as dialog:
        dialog.ShowModal()
        return copy.deepcopy(dialog.report)
