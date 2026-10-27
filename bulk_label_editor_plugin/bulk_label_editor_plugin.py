"""Bulk label/component editor for KiCad pcbnew."""

from __future__ import annotations

import csv
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, List

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .guided_ui import add_workflow
from wayricad_runtime.ui import more_button
from wayricad_runtime.ipc import read_snapshot, selected_footprints
from wayricad_runtime.net_filter import SearchIndex
from .rules import compile_rule, validate_changes, apply_reviewed
from .inventory import collect_nets
from wayricad_runtime.geometry import item_id


class ResultTable(wx.ListCtrl):
    """Virtual rows keep large net lists responsive without thousands of inserts."""

    def __init__(self, parent, columns):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL)
        self.rows = []
        for index, (label, width) in enumerate(columns):
            self.InsertColumn(index, label, width=width)
        self.Bind(wx.EVT_LIST_COL_CLICK, self.on_sort)
        self.sort_column = None
        self.descending = False

    def OnGetItemText(self, item, column):
        return str(self.rows[item][column]) if item < len(self.rows) else ""

    def set_rows(self, rows):
        self.ClearSelection()
        self.rows = list(rows)
        self.SetItemCount(len(self.rows))
        if self.sort_column is not None:
            self.rows.sort(key=lambda row: row[self.sort_column], reverse=self.descending)
        self.Refresh()

    def ClearSelection(self):
        for index in self.selected_indices():
            self.SetItemState(index, 0, wx.LIST_STATE_SELECTED)

    def selected_indices(self):
        result = []
        index = self.GetFirstSelected()
        while index >= 0:
            result.append(index)
            index = self.GetNextSelected(index)
        return result

    def on_sort(self, event):
        column = event.GetColumn()
        self.descending = column == self.sort_column and not self.descending
        self.sort_column = column
        self.set_rows(self.rows)


@dataclass
class EditableItem:
    kind: str
    owner: str
    current: str
    setter: Callable[[str], None]
    board_item: Any = None
    getter: Any = None
    owner_id: str = ""


class EditOperation(list):
    """Retain the original duplicate counts so Undo can restore unannotated parts."""

    def __init__(self, changes, items):
        super().__init__(changes)
        self.original_references = Counter(item.current.casefold() for item in items if item.kind == "Reference")


class BulkLabelEditorPlugin(pcbnew.ActionPlugin):
    """ActionPlugin entry point for wildcard/regex board text edits."""

    def defaults(self) -> None:
        self.name = "WayriCAD Bulk Label Editor"
        self.category = "Utilities"
        self.description = "Bulk rename labels, PCB text, footprint references, values, and fields using wildcard or regex rules."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.version = "3.6.40"

    def Run(self) -> None:
        try:
            board = pcbnew.GetBoard()
            if board is None or not hasattr(board, "GetFootprints"):
                raise RuntimeError("Open a PCB in PCB Editor first.")
            existing = getattr(self, "_frame", None)
            if existing is not None and existing:
                existing.Show()
                existing.Raise()
                return
            self._frame = BulkLabelEditorFrame(None, board)
            self._frame.Show()
            self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(str(exc), "WayriCAD Bulk Label Editor", wx.OK | wx.ICON_ERROR)


class BulkLabelEditorFrame(wx.Frame):
    """Preview-and-apply editor for common pcbnew text-bearing objects."""

    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="WayriCAD Bulk Label Editor", size=(1080, 720), style=wx.DEFAULT_FRAME_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((860, 600))
        self.board = board
        self.items: List[EditableItem] = []
        self.matches: List[EditableItem] = []
        self.reviewed_changes = []
        self.undo_stack: List[List[tuple[EditableItem, str, str]]] = []
        self.redo_stack: List[List[tuple[EditableItem, str, str]]] = []
        self.net_rows = []
        self.net_error = ""
        self._preview_timer = None
        self._build_ui()
        self.refresh_items()
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        self.workflow = add_workflow(
            panel, root, "Bulk Label Editor",
            "Build a rename rule, inspect every proposed change, then apply exactly that preview.",
            ("Configure", "Review preview", "Apply"),
            lambda _event: open_help(self),
        )

        options = wx.BoxSizer(wx.VERTICAL)
        options_heading = wx.StaticText(panel, label="Rename Rule")
        options_heading.SetFont(options_heading.GetFont().Bold())
        options.Add(options_heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.match_text = wx.TextCtrl(panel)
        self.match_text.SetHint("Find text; * and ? wildcards, or enable Regex")
        self.replacement_text = wx.TextCtrl(panel)
        self.replacement_text.SetHint("Replacement; wildcard captures or regex groups")
        row1.Add(wx.StaticText(panel, label="Find:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        row1.Add(self.match_text, 1, wx.EXPAND | wx.ALL, 4)
        row1.Add(wx.StaticText(panel, label="Replace:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        row1.Add(self.replacement_text, 1, wx.EXPAND | wx.ALL, 4)
        options.Add(row1, 0, wx.EXPAND)

        row2 = wx.FlexGridSizer(cols=4, vgap=4, hgap=12)
        self.use_regex = wx.CheckBox(panel, label="Regex")
        self.case_sensitive = wx.CheckBox(panel, label="Case sensitive")
        self.edit_refs = wx.CheckBox(panel, label="References")
        self.edit_values = wx.CheckBox(panel, label="Values")
        self.edit_fields = wx.CheckBox(panel, label="Fields")
        self.edit_text = wx.CheckBox(panel, label="PCB text")
        for cb in (self.edit_refs, self.edit_text):
            cb.SetValue(True)
        self.edit_refs.SetToolTip("PCB references only; does not reannotate the schematic.")
        self.edit_fields.SetToolTip("Custom footprint fields; built-in reference/value fields are separate.")
        self.edit_text.SetToolTip("Board and footprint graphical text, excluding pads and shapes.")
        self.only_selected = wx.CheckBox(panel, label="Selected footprints only")
        for control in (self.use_regex, self.case_sensitive, self.edit_refs, self.edit_values, self.edit_fields, self.edit_text, self.only_selected):
            control.Bind(wx.EVT_CHECKBOX, self.on_preview)
            row2.Add(control, 0, wx.ALL, 4)
        options.Add(row2, 0, wx.EXPAND)

        row3 = wx.BoxSizer(wx.HORIZONTAL)
        preview_btn = wx.Button(panel, label="Preview")
        preview_btn.Bind(wx.EVT_BUTTON, self.on_preview)
        preview_btn.SetDefault()
        apply_btn = self.apply_button = wx.Button(panel, label="Apply all changes")
        apply_btn.Bind(wx.EVT_BUTTON, self.on_apply)
        apply_btn.Enable(False)
        selected_btn = self.apply_selected_button = wx.Button(panel, label="Apply selected rows")
        selected_btn.Bind(wx.EVT_BUTTON, lambda event: self.on_apply(event, selected_only=True))
        selected_btn.Enable(False)
        self.undo_button = wx.Button(panel, label="Undo")
        self.undo_button.Bind(wx.EVT_BUTTON, self.on_undo)
        self.undo_button.Enable(False)
        self.undo_button.SetToolTip("Restore every field changed by the most recent Apply Preview.")
        self.redo_button = wx.Button(panel, label="Redo")
        self.redo_button.Bind(wx.EVT_BUTTON, self.on_redo)
        self.redo_button.Enable(False)
        self.redo_button.SetToolTip("Reapply every field restored by Undo Last Apply.")
        more = more_button(panel, [("Refresh from PCB", self.on_refresh), ("Select rows on PCB", self.on_select_preview), ("Export visible table as CSV", self.on_export)])
        for btn in (preview_btn, apply_btn, selected_btn, self.undo_button, self.redo_button, more):
            best=btn.GetBestSize()
            width=180 if btn is selected_btn else 150 if btn is apply_btn else 90
            btn.SetMinSize((max(self.FromDIP(width),best.width),max(self.FromDIP(28),best.height)))
            row3.Add(btn, 0, wx.ALL, 4)
        root.Add(options, 0, wx.EXPAND | wx.ALL, 6)

        self.notebook = wx.Notebook(panel)
        self.preview = ResultTable(self.notebook, [("Kind", 120), ("Owner", 140), ("Current", 290), ("New (blank = unchanged)", 290)])
        self.preview.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_select_preview)
        self.preview.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _e: self.apply_selected_button.Enable(bool(self.reviewed_changes)))
        self.notebook.AddPage(self.preview, "Text and rename preview")
        net_panel = wx.Panel(self.notebook)
        net_layout = wx.BoxSizer(wx.VERTICAL)
        self.net_search = wx.SearchCtrl(net_panel)
        self.net_search.SetDescriptiveText("Search nets: substring, * wildcard, ? character, ~fuzzy")
        self.net_search.SetToolTip("Bus brackets are literal. Select multiple rows with Ctrl/Shift; double-click to locate copper.")
        self.net_search.Bind(wx.EVT_TEXT, self.on_net_search)
        net_layout.Add(self.net_search, 0, wx.EXPAND | wx.ALL, 6)
        self.net_table = ResultTable(net_panel, [("Net", 340), ("Pads", 65), ("Tracks", 70), ("Vias", 65), ("Zones", 65), ("Connections (ref.pad)", 380)])
        self.net_table.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_select_nets)
        net_layout.Add(self.net_table, 1, wx.EXPAND | wx.ALL, 6)
        net_buttons = wx.WrapSizer(wx.HORIZONTAL)
        for title, handler in (("Reload PCB and nets", self.on_refresh), ("Select nets on PCB", self.on_select_nets), ("Copy net names", self.on_copy_nets), ("Export CSV", self.on_export)):
            button = wx.Button(net_panel, label=title)
            button.Bind(wx.EVT_BUTTON, handler)
            net_buttons.Add(button, 0, wx.ALL, 4)
        net_layout.Add(net_buttons, 0, wx.EXPAND)
        self.net_status = wx.StaticText(net_panel, label="Loading nets…")
        net_layout.Add(self.net_status, 0, wx.EXPAND | wx.ALL, 6)
        note = wx.StaticText(net_panel, label="Nets are electrical connectivity, not PCB text. Rename labels in Schematic Editor, then Update PCB from Schematic.")
        note.Wrap(900)
        net_layout.Add(note, 0, wx.EXPAND | wx.ALL, 6)
        net_panel.SetSizer(net_layout)
        self.notebook.AddPage(net_panel, "Nets and connections")
        root.Add(self.notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        root.Add(row3, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.status = wx.StaticText(panel, label="Ready.")
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        panel.SetSizer(root)
        self._panel, self._root = panel, root
        self._options, self._actions = options, row3
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_page)
        self.match_text.Bind(wx.EVT_TEXT, self.schedule_preview)
        self.replacement_text.Bind(wx.EVT_TEXT, self.schedule_preview)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def on_page(self, event):
        editing = self.notebook.GetSelection() == 0
        self._root.Show(self._options, editing)
        self._root.Show(self._actions, editing)
        self._panel.Layout()
        event.Skip()

    def on_close(self, event):
        if self._preview_timer is not None:
            self._preview_timer.Stop()
        event.Skip()

    def schedule_preview(self, _event):
        self.reviewed_changes = []
        self.apply_button.Enable(False)
        self.apply_selected_button.Enable(False)
        if self._preview_timer is not None:
            self._preview_timer.Stop()
        self._preview_timer = wx.CallLater(180, self.on_preview, None)

    def refresh_items(self) -> None:
        self.items = []
        with read_snapshot(self.board):
            for fp in self.board.GetFootprints():
                ref = fp.GetReference()
                self.items.append(EditableItem("Reference", ref, ref, fp.SetReference, fp, fp.GetReference, item_id(fp)))
                self.items.append(EditableItem("Value", ref, fp.GetValue(), fp.SetValue, fp, fp.GetValue, item_id(fp)))
                self._add_fields(fp, ref)
                self._add_footprint_text(fp, ref)
            self._add_board_text()
            try:
                self.net_rows = collect_nets(self.board)
                self.net_error = ""
            except Exception as exc:
                self.net_rows = []
                self.net_error = "Net loading failed: " + str(exc)
        self.net_index = SearchIndex([row.name for row in self.net_rows])
        self.on_net_search(None)
        self.on_preview(None)

    def _add_fields(self, fp: Any, owner: str) -> None:
        get_fields = getattr(fp, "GetFields", None)
        if not get_fields:
            return
        try:
            fields = list(get_fields())
        except Exception:
            return
        for field in fields:
            name = field.GetName()
            if name.casefold() in {"reference", "value"}:
                continue
            self.items.append(
                EditableItem(
                    f"Field:{name}",
                    owner,
                    field.GetText(),
                    field.SetText, fp, field.GetText, item_id(fp),
                )
            )

    def _add_footprint_text(self, fp, owner):
        for item in getattr(fp, "GraphicalItems", lambda: ())():
            self._append_text(item, owner, item_id(fp))
        raw = getattr(fp, "raw", None)
        if raw is not None:
            # IPC keeps instance text separate from definition graphics. Fields
            # have their own scope and must not appear a second time as text.
            for text in getattr(raw, "texts_and_fields", ()):
                if not isinstance(text, fp.board.types.Field):
                    self._append_text(fp.board.wrap(text, fp), owner, item_id(fp))

    def _append_text(self, drawing, owner, owner_id=""):
        get_text = getattr(drawing, "GetText", None)
        set_text = getattr(drawing, "SetText", None)
        if callable(get_text) and callable(set_text):
            try:
                text = get_text()
            except (AttributeError, TypeError):
                return
            if isinstance(text, str):
                self.items.append(EditableItem("PCB text", owner, text, set_text, drawing, get_text, owner_id))

    def _add_board_text(self) -> None:
        drawings = getattr(self.board, "GetDrawings", lambda: [])()
        for drawing in drawings:
            get_text = getattr(drawing, "GetText", None)
            set_text = getattr(drawing, "SetText", None)
            if callable(get_text) and callable(set_text):
                # The IPC facade wraps both text and graphical shapes. Shapes
                # expose the same method name but have no text value.
                try:
                    text = get_text()
                except (AttributeError, TypeError):
                    continue
                if isinstance(text, str):
                    self.items.append(EditableItem("PCB text", "Board", text, set_text, drawing, get_text))

    def on_refresh(self, _event: Any) -> None:
        self.refresh_items()

    def on_preview(self, _event: Any) -> None:
        self.matches = []
        self.reviewed_changes = []
        rows = []
        self.apply_button.Enable(False)
        self.apply_selected_button.Enable(False)
        try:
            pattern = self.match_text.GetValue()
            replace = compile_rule(pattern, self.replacement_text.GetValue(),
                                   regex=self.use_regex.GetValue(),
                                   case_sensitive=self.case_sensitive.GetValue()) if pattern else None
            for item in self._filtered_items():
                new_value = replace(item.current) if replace else item.current
                if replace and new_value == item.current:
                    continue
                self.matches.append(item)
                if new_value != item.current:
                    self.reviewed_changes.append((item, item.current, new_value))
                rows.append((item.kind, item.owner, item.current,
                             new_value if new_value != item.current else "", len(self.matches) - 1))
            validate_changes(self.items, self.reviewed_changes)
        except (re.error, ValueError) as exc:
            self.matches = []
            self.reviewed_changes = []
            self.preview.set_rows([])
            self.status.SetLabel(f"Rule needs attention: {exc}")
            return
        self.preview.set_rows(rows)
        self.apply_button.Enable(bool(self.reviewed_changes))
        self.status.SetLabel(f"{len(self.items)} text fields loaded; {len(self.matches)} visible; {len(self.reviewed_changes)} changes. "
                             + ("Enter a find rule to rename; nets are in the next tab." if not pattern else "Review before applying."))
        if self.reviewed_changes:
            self.workflow.set_step(2, "Inspect the rows, double-click uncertain items to locate them, then Apply.")
        else:
            self.workflow.set_step(0, "Browse loaded text and nets, then choose a scope and enter your rename rule.")

    def on_apply(self, _event: Any, selected_only=False) -> None:
        if not self.reviewed_changes:
            wx.MessageBox("No matching items to apply.", "WayriCAD", wx.OK | wx.ICON_INFORMATION)
            return
        operation = list(self.reviewed_changes)
        if selected_only:
            selected = {id(self.matches[self.preview.rows[index][-1]]) for index in self.preview.selected_indices()}
            operation = [row for row in operation if id(row[0]) in selected]
            if not operation:
                self.status.SetLabel("Select changed preview rows first (Ctrl/Shift for multiple rows).")
                return
        operation = EditOperation(operation, self.items)
        if not self._apply_operation(operation):
            return
        count = len(operation)
        if operation:
            self.undo_stack.append(operation)
            self.redo_stack.clear()
            self.undo_button.Enable(True)
            self.redo_button.Enable(False)
        if hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()
        self.refresh_items()
        self.status.SetLabel(f"Applied {count} edits.")
        self.workflow.set_step(3, "Save the PCB and review the result; Undo remains available in this window.")

    def on_select_preview(self, event: Any) -> None:
        indices = self.preview.selected_indices()
        if not indices:
            wx.MessageBox("Select a preview row first.", "WayriCAD", wx.OK | wx.ICON_INFORMATION)
            return
        items = [self.matches[self.preview.rows[index][-1]] for index in indices]
        try:
            select_items(self.board, [item.board_item for item in items])
            self.status.SetLabel(f"Selected {len(items)} text owners on the PCB.")
        except Exception as exc:
            self.status.SetLabel("Selection failed: " + str(exc))

    def on_net_search(self, _event):
        indices = self.net_index.match(self.net_search.GetValue())
        self.net_table.set_rows([(row.name, row.pads, row.tracks, row.vias, row.zones,
                                  ", ".join(row.terminals)) for row in (self.net_rows[index] for index in indices)])
        self.net_status.SetLabel(self.net_error or f"{len(self.net_rows)} named nets loaded; {len(indices)} shown. Nets are read-only.")

    def on_select_nets(self, _event):
        names = [self.net_table.rows[index][0] for index in self.net_table.selected_indices()]
        if not names:
            self.net_status.SetLabel("Select one or more net rows first (Ctrl/Shift).")
            return
        try:
            from .inventory import select_nets
            count = select_nets(self.board, names)
            self.net_status.SetLabel(f"Selected {count} copper items on {len(names)} nets; other items deselected.")
        except Exception as exc:
            self.net_status.SetLabel("Selection failed: " + str(exc))

    def on_copy_nets(self, _event):
        names = [self.net_table.rows[index][0] for index in self.net_table.selected_indices()]
        if names and wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject("\n".join(names)))
            finally:
                wx.TheClipboard.Close()

    def on_export(self, _event):
        nets = self.notebook.GetSelection() == 1
        table = self.net_table if nets else self.preview
        columns = ("Net", "Pads", "Tracks", "Vias", "Zones", "Connections") if nets else ("Kind", "Owner", "Current", "New")
        with wx.FileDialog(self, "Export visible table", wildcard="CSV files (*.csv)|*.csv", style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                # Do not overwrite a project or an earlier report.
                if not dialog.GetPath().lower().endswith(".csv"):
                    raise ValueError("Choose a new .csv file.")
                with open(dialog.GetPath(), "x", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(columns)
                    for row in table.rows:
                        # Neutralize spreadsheet formulas without changing source data.
                        writer.writerow([("'" + str(value)) if str(value).startswith(("=", "+", "-", "@")) else value
                                         for value in row[:len(columns)]])
                self.status.SetLabel(f"Exported {len(table.rows)} rows.")
            except (OSError, ValueError) as exc:
                self.status.SetLabel("Export failed: " + str(exc))

    def on_undo(self, _event: Any) -> None:
        if not self.undo_stack:
            self.status.SetLabel("Nothing to undo.")
            return
        operation = self.undo_stack[-1]
        if not self._apply_operation(operation, reverse=True):
            return
        self.undo_stack.pop()
        self.redo_stack.append(operation)
        self.undo_button.Enable(bool(self.undo_stack))
        self.redo_button.Enable(True)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.refresh_items()
        self.status.SetLabel(f"Undid {len(operation)} edits.")

    def on_redo(self, _event: Any) -> None:
        if not self.redo_stack:
            self.status.SetLabel("Nothing to redo.")
            return
        operation = self.redo_stack[-1]
        if not self._apply_operation(operation):
            return
        self.redo_stack.pop()
        self.undo_stack.append(operation)
        self.undo_button.Enable(True)
        self.redo_button.Enable(bool(self.redo_stack))
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.refresh_items()
        self.status.SetLabel(f"Redid {len(operation)} edits.")

    def _apply_operation(self, operation, reverse=False):
        try:
            from .wayricad_runtime.geometry import item_id
        except ImportError:
            from wayricad_runtime.geometry import item_id
        try:
            # Resolve against a fresh board read, including IPC wrappers. Deleted or externally
            # edited text must not be overwritten through stale preview object references.
            requested = [(item_id(item.board_item), item.kind, old, new) for item,old,new in operation]
            self.refresh_items()
            current = {(item_id(item.board_item),item.kind):item for item in self.items}
            if any((identifier,kind) not in current for identifier,kind,_,_ in requested):
                raise ValueError("A reviewed object was removed. Refresh and review again.")
            operation[:] = [(current[identifier,kind],old,new) for identifier,kind,old,new in requested]
            validate_changes(self.items, [(item, new, old) if reverse else (item, old, new)
                                          for item, old, new in operation],
                             allowed_reference_counts=getattr(operation, "original_references", None) if reverse else None)
            apply_reviewed(operation, reverse=reverse, verify=self._verify_results)
        except Exception as exc:
            wx.MessageBox(str(exc), "Edit stopped", wx.OK | wx.ICON_ERROR)
            return False
        return True

    def _verify_results(self, expected):
        # Refresh issues new editor reads after setters, rather than checking
        # only the local IPC protos that a setter has just mutated.
        wanted = [(item_id(item.board_item), item.kind, value) for item, value in expected]
        self.refresh_items()
        current = {(item_id(item.board_item), item.kind): item.current for item in self.items}
        if any(current.get((identifier, kind)) != value for identifier, kind, value in wanted):
            raise RuntimeError("KiCad readback differs from the reviewed text. Batch rolled back where possible.")

    def _filtered_items(self) -> List[EditableItem]:
        enabled = []
        if self.edit_refs.GetValue():
            enabled.append("Reference")
        if self.edit_values.GetValue():
            enabled.append("Value")
        if self.edit_fields.GetValue():
            enabled.append("Field:")
        if self.edit_text.GetValue():
            enabled.append("PCB text")
        selected = {item_id(fp) for fp in selected_footprints(self.board)} if self.only_selected.GetValue() else None
        return [item for item in self.items if any(item.kind.startswith(prefix) for prefix in enabled)
                and (selected is None or item.owner_id in selected)]

    def _replace(self, text: str) -> str:
        pattern = self.match_text.GetValue()
        replacement = self.replacement_text.GetValue()
        return compile_rule(pattern, replacement, regex=self.use_regex.GetValue(),
                            case_sensitive=self.case_sensitive.GetValue())(text)


def wildcard_replace(text: str, pattern: str, replacement: str, case_sensitive: bool = False) -> str:
    """Replace wildcard matches while expanding '*' captures in replacement."""
    return compile_rule(pattern, replacement, case_sensitive=case_sensitive)(text)
