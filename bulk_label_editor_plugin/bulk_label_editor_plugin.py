"""Bulk label/component editor for KiCad pcbnew."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, List

import pcbnew
import wx


@dataclass
class EditableItem:
    kind: str
    owner: str
    current: str
    setter: Callable[[str], None]


class BulkLabelEditorPlugin(pcbnew.ActionPlugin):
    """ActionPlugin entry point for wildcard/regex board text edits."""

    def defaults(self) -> None:
        self.name = "KiWay Bulk Label Editor"
        self.category = "Utilities"
        self.description = "Bulk rename labels, PCB text, footprint references, values, and fields using wildcard or regex rules."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.version = "0.2.0"

    def Run(self) -> None:
        frame = BulkLabelEditorFrame(None, pcbnew.GetBoard())
        frame.Show()


class BulkLabelEditorFrame(wx.Frame):
    """Preview-and-apply editor for common pcbnew text-bearing objects."""

    def __init__(self, parent: Any, board: Any) -> None:
        super().__init__(parent, title="KiWay Bulk Label Editor", size=(900, 620))
        self.board = board
        self.items: List[EditableItem] = []
        self.matches: List[EditableItem] = []
        self.undo_stack: List[List[tuple[EditableItem, str, str]]] = []
        self.redo_stack: List[List[tuple[EditableItem, str, str]]] = []
        self._build_ui()
        self.refresh_items()
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        options = wx.StaticBoxSizer(wx.StaticBox(panel, label="Rename Rule"), wx.VERTICAL)
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

        row2 = wx.BoxSizer(wx.HORIZONTAL)
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

        row3 = wx.BoxSizer(wx.HORIZONTAL)
        preview_btn = wx.Button(panel, label="Preview")
        preview_btn.Bind(wx.EVT_BUTTON, self.on_preview)
        apply_btn = wx.Button(panel, label="Apply")
        apply_btn.Bind(wx.EVT_BUTTON, self.on_apply)
        undo_btn = wx.Button(panel, label="Undo")
        undo_btn.Bind(wx.EVT_BUTTON, self.on_undo)
        redo_btn = wx.Button(panel, label="Redo")
        redo_btn.Bind(wx.EVT_BUTTON, self.on_redo)
        refresh_btn = wx.Button(panel, label="Refresh")
        refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        for btn in (preview_btn, apply_btn, undo_btn, redo_btn, refresh_btn):
            row3.Add(btn, 0, wx.ALL, 4)
        options.Add(row3, 0, wx.EXPAND)
        root.Add(options, 0, wx.EXPAND | wx.ALL, 6)

        self.preview = wx.ListCtrl(panel, style=wx.LC_REPORT)
        for idx, (label, width) in enumerate([("Kind", 120), ("Owner", 120), ("Current", 260), ("New", 260)]):
            self.preview.InsertColumn(idx, label, width=width)
        root.Add(self.preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        self.status = wx.StaticText(panel, label="Ready.")
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        panel.SetSizer(root)

    def refresh_items(self) -> None:
        self.items = []
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            self.items.append(EditableItem("Reference", ref, ref, fp.SetReference))
            self.items.append(EditableItem("Value", ref, fp.GetValue(), fp.SetValue))
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
                    field.SetText,
                )
            )

    def _add_board_text(self) -> None:
        drawings = getattr(self.board, "GetDrawings", lambda: [])()
        for drawing in drawings:
            get_text = getattr(drawing, "GetText", None)
            set_text = getattr(drawing, "SetText", None)
            if callable(get_text) and callable(set_text):
                self.items.append(EditableItem(type(drawing).__name__, "Board", get_text(), set_text))

    def on_refresh(self, _event: Any) -> None:
        self.refresh_items()

    def on_preview(self, _event: Any) -> None:
        self.preview.DeleteAllItems()
        self.matches = []
        try:
            for item in self._filtered_items():
                new_value = self._replace(item.current)
                if new_value == item.current:
                    continue
                self.matches.append(item)
                idx = self.preview.InsertItem(self.preview.GetItemCount(), item.kind)
                self.preview.SetItem(idx, 1, item.owner)
                self.preview.SetItem(idx, 2, item.current)
                self.preview.SetItem(idx, 3, new_value)
        except re.error as exc:
            self.status.SetLabel(f"Regex error: {exc}")
            return
        self.status.SetLabel(f"{len(self.matches)} matching editable items.")

    def on_apply(self, _event: Any) -> None:
        if not self.matches:
            wx.MessageBox("No matching items to apply.", "KiWay", wx.OK | wx.ICON_INFORMATION)
            return
        count = 0
        operation: List[tuple[EditableItem, str, str]] = []
        for item in self.matches:
            new_value = self._replace(item.current)
            item.setter(new_value)
            operation.append((item, item.current, new_value))
            count += 1
        if operation:
            self.undo_stack.append(operation)
            self.redo_stack.clear()
        if hasattr(pcbnew, "Refresh"):
            pcbnew.Refresh()
        self.refresh_items()
        self.status.SetLabel(f"Applied {count} edits.")

    def on_undo(self, _event: Any) -> None:
        if not self.undo_stack:
            self.status.SetLabel("Nothing to undo.")
            return
        operation = self.undo_stack.pop()
        for item, old_value, _new_value in reversed(operation):
            item.setter(old_value)
        self.redo_stack.append(operation)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.refresh_items()
        self.status.SetLabel(f"Undid {len(operation)} edits.")

    def on_redo(self, _event: Any) -> None:
        if not self.redo_stack:
            self.status.SetLabel("Nothing to redo.")
            return
        operation = self.redo_stack.pop()
        for item, _old_value, new_value in operation:
            item.setter(new_value)
        self.undo_stack.append(operation)
        if hasattr(pcbnew, "Refresh"): pcbnew.Refresh()
        self.refresh_items()
        self.status.SetLabel(f"Redid {len(operation)} edits.")

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
