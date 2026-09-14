"""Bulk label/component editor for KiCad pcbnew."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, List

import pcbnew
import wx

from .help_utils import open_help
from .selection_utils import select_items
from .guided_ui import add_workflow
from wayricad_runtime.ui import more_button


@dataclass
class EditableItem:
    kind: str
    owner: str
    current: str
    setter: Callable[[str], None]
    board_item: Any = None
    getter: Any = None


class BulkLabelEditorPlugin(pcbnew.ActionPlugin):
    """ActionPlugin entry point for wildcard/regex board text edits."""

    def defaults(self) -> None:
        self.name = "WayriCAD Bulk Label Editor"
        self.category = "Utilities"
        self.description = "Bulk rename labels, PCB text, footprint references, values, and fields using wildcard or regex rules."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "resources", "icon-24.png")
        self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
        self.version = "3.1.0"

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
        self.match_text.SetValue("CH*_MAIN")
        self.replacement_text = wx.TextCtrl(panel)
        self.replacement_text.SetValue("CH*_REDUNDANT")
        row1.Add(wx.StaticText(panel, label="Find:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        row1.Add(self.match_text, 1, wx.EXPAND | wx.ALL, 4)
        row1.Add(wx.StaticText(panel, label="Replace:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        row1.Add(self.replacement_text, 1, wx.EXPAND | wx.ALL, 4)
        options.Add(row1, 0, wx.EXPAND)

        row2 = wx.WrapSizer(wx.HORIZONTAL)
        self.use_regex = wx.CheckBox(panel, label="Regex")
        self.case_sensitive = wx.CheckBox(panel, label="Case sensitive")
        self.edit_refs = wx.CheckBox(panel, label="References")
        self.edit_values = wx.CheckBox(panel, label="Values")
        self.edit_fields = wx.CheckBox(panel, label="Fields")
        self.edit_text = wx.CheckBox(panel, label="PCB text")
        for cb in (self.edit_refs, self.edit_values, self.edit_fields, self.edit_text):
            cb.SetValue(True)
        for control in (self.use_regex, self.case_sensitive, self.edit_refs, self.edit_values, self.edit_fields, self.edit_text):
            control.Bind(wx.EVT_CHECKBOX, self.on_preview)
            row2.Add(control, 0, wx.ALL, 4)
        options.Add(row2, 0, wx.EXPAND)

        row3 = wx.WrapSizer(wx.HORIZONTAL)
        preview_btn = wx.Button(panel, label="Preview")
        preview_btn.Bind(wx.EVT_BUTTON, self.on_preview)
        preview_btn.SetDefault()
        apply_btn = wx.Button(panel, label="Apply")
        apply_btn.Bind(wx.EVT_BUTTON, self.on_apply)
        self.undo_button = wx.Button(panel, label="Undo")
        self.undo_button.Bind(wx.EVT_BUTTON, self.on_undo)
        self.undo_button.Enable(False)
        self.undo_button.SetToolTip("Restore every field changed by the most recent Apply Preview.")
        self.redo_button = wx.Button(panel, label="Redo")
        self.redo_button.Bind(wx.EVT_BUTTON, self.on_redo)
        self.redo_button.Enable(False)
        self.redo_button.SetToolTip("Reapply every field restored by Undo Last Apply.")
        more = more_button(panel, [("Refresh from PCB", self.on_refresh), ("Select row on PCB", self.on_select_preview)])
        for btn in (preview_btn, apply_btn, self.undo_button, self.redo_button, more):
            row3.Add(btn, 0, wx.ALL, 4)
        root.Add(options, 0, wx.EXPAND | wx.ALL, 6)

        self.preview = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.preview.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_select_preview)
        for idx, (label, width) in enumerate([("Kind", 120), ("Owner", 120), ("Current", 260), ("New", 260)]):
            self.preview.InsertColumn(idx, label, width=width)
        root.Add(self.preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        root.Add(row3, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.status = wx.StaticText(panel, label="Ready.")
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        panel.SetSizer(root)
        self.match_text.Bind(wx.EVT_TEXT, self.on_preview)
        self.replacement_text.Bind(wx.EVT_TEXT, self.on_preview)

    def refresh_items(self) -> None:
        self.items = []
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            self.items.append(EditableItem("Reference", ref, ref, fp.SetReference, fp, fp.GetReference))
            self.items.append(EditableItem("Value", ref, fp.GetValue(), fp.SetValue, fp, fp.GetValue))
            self._add_fields(fp, ref)
        self._add_board_text()
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
            self.items.append(
                EditableItem(
                    f"Field:{name}",
                    owner,
                    field.GetText(),
                    field.SetText, fp, field.GetText,
                )
            )

    def _add_board_text(self) -> None:
        drawings = getattr(self.board, "GetDrawings", lambda: [])()
        for drawing in drawings:
            get_text = getattr(drawing, "GetText", None)
            set_text = getattr(drawing, "SetText", None)
            if callable(get_text) and callable(set_text):
                self.items.append(EditableItem(type(drawing).__name__, "Board", get_text(), set_text, drawing, get_text))

    def on_refresh(self, _event: Any) -> None:
        self.refresh_items()

    def on_preview(self, _event: Any) -> None:
        self.preview.DeleteAllItems()
        self.matches = []
        self.reviewed_changes = []
        try:
            for item in self._filtered_items():
                new_value = self._replace(item.current)
                if new_value == item.current:
                    continue
                self.matches.append(item)
                self.reviewed_changes.append((item, item.current, new_value))
                idx = self.preview.InsertItem(self.preview.GetItemCount(), item.kind)
                self.preview.SetItem(idx, 1, item.owner)
                self.preview.SetItem(idx, 2, item.current)
                self.preview.SetItem(idx, 3, new_value)
        except re.error as exc:
            self.matches = []
            self.reviewed_changes = []
            self.status.SetLabel(f"Regex error: {exc}")
            return
        self.status.SetLabel(f"{len(self.matches)} matching editable items.")
        if self.matches:
            self.workflow.set_step(2, "Inspect the rows, double-click uncertain items to locate them, then Apply.")
        else:
            self.workflow.set_step(0, "Adjust the find rule or enabled object scopes until Preview finds the intended rows.")

    def on_apply(self, _event: Any) -> None:
        if not self.matches:
            wx.MessageBox("No matching items to apply.", "WayriCAD", wx.OK | wx.ICON_INFORMATION)
            return
        operation = list(self.reviewed_changes)
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
        index = event.GetIndex() if hasattr(event, "GetIndex") else self.preview.GetFirstSelected()
        if index < 0 or index >= len(self.matches):
            wx.MessageBox("Select a preview row first.", "WayriCAD", wx.OK | wx.ICON_INFORMATION)
            return
        item = self.matches[index]
        select_items(self.board, [item.board_item])
        self.status.SetLabel(f"Selected {item.owner} on the PCB.")

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
            from .wayricad_runtime.fields import apply_fields
            from .wayricad_runtime.geometry import item_id
        except ImportError:
            from wayricad_runtime.fields import apply_fields
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
            apply_fields(operation, reverse=reverse)
        except Exception as exc:
            wx.MessageBox(str(exc), "Edit stopped", wx.OK | wx.ICON_ERROR)
            return False
        return True

    def _filtered_items(self) -> List[EditableItem]:
        enabled = []
        if self.edit_refs.GetValue():
            enabled.append("Reference")
        if self.edit_values.GetValue():
            enabled.append("Value")
        if self.edit_fields.GetValue():
            enabled.append("Field:")
        if self.edit_text.GetValue():
            enabled.extend(["PCB_TEXT", "PCB_FIELD", "PCB_SHAPE", "TEXTE_PCB"])
        return [item for item in self.items if any(item.kind.startswith(prefix) for prefix in enabled)]

    def _replace(self, text: str) -> str:
        pattern = self.match_text.GetValue()
        replacement = self.replacement_text.GetValue()
        flags = 0 if self.case_sensitive.GetValue() else re.IGNORECASE
        if self.use_regex.GetValue():
            return re.sub(pattern, replacement, text, flags=flags)
        return wildcard_replace(text, pattern, replacement, case_sensitive=self.case_sensitive.GetValue())


def wildcard_replace(text: str, pattern: str, replacement: str, case_sensitive: bool = False) -> str:
    """Replace wildcard matches while expanding '*' captures in replacement."""
    regex = "^" + "".join("(.*)" if ch == "*" else "(.{1})" if ch == "?" else re.escape(ch) for ch in pattern) + "$"
    flags = 0 if case_sensitive else re.IGNORECASE
    match = re.match(regex, text, flags=flags)
    if not match:
        return text
    star_values = []
    group_idx = 1
    for ch in pattern:
        if ch == "*":
            star_values.append(match.group(group_idx))
            group_idx += 1
        elif ch == "?":
            group_idx += 1
    result = replacement
    for value in star_values:
        result = result.replace("*", value, 1)
    return result
