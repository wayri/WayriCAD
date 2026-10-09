"""Reusable native component-input table, detached from saved PCB files."""
from __future__ import annotations

import wx
import wx.grid

from .component_inputs import ComponentInputsModel, QUANTITIES, parse_input


_HEADERS = ("Include", "Reference", "Side", "Value", "Power (W)",
            "RθJA (K/W)", "RθJB (K/W)", "RθJC (K/W)",
            "Min Tj (°C)", "Max Tj (°C)", "Input source", "Input status")


class _InputTable(wx.grid.GridTableBase):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.references = list(panel.model.references)

    def GetNumberRows(self):
        return len(self.references)

    def GetNumberCols(self):
        return len(_HEADERS)

    def GetColLabelValue(self, column):
        return _HEADERS[column]

    def GetTypeName(self, row, column):
        return wx.grid.GRID_VALUE_BOOL if column == 0 else wx.grid.GRID_VALUE_STRING

    def GetValue(self, row, column):
        ref = self.references[row]
        model = self.panel.model
        if column == 0:
            return "1" if model.is_included(ref) else ""
        if column == 1:
            return ref
        if column in (2, 3):
            return str(model.components[ref].get("side" if column == 2 else "value", ""))
        if 4 <= column < 10:
            return model.cell(ref, QUANTITIES[column - 4]).text
        return model.source_summary(ref) if column == 10 else model.row_status(ref)

    def SetValue(self, row, column, value):
        ref = self.references[row]
        if column == 0:
            self.panel.model.set_included(ref, str(value) == "1")
        elif 4 <= column < 10:
            self.panel.model.set_value(ref, QUANTITIES[column - 4], value)

    def IsEmptyCell(self, row, column):
        return self.GetValue(row, column) == ""

    def GetAttr(self, row, column, kind):
        attr = wx.grid.GridCellAttr()
        if column in (1, 2, 3, 10, 11):
            attr.SetReadOnly(True)
        return attr


class ComponentInputPanel(wx.Panel):
    """Input scope and all numeric quantities in one independently editable table.

    ``on_change(state)`` receives detached explicit overrides and checked refs.
    ``on_select(reference)`` is cross-navigation only; it does not check a row.
    The owner controls worker requests, mapping choices and window cancellation.
    """

    def __init__(self, parent, model=None, on_change=None, on_select=None):
        super().__init__(parent)
        self.model = model or ComponentInputsModel()
        self.on_change = on_change
        self.on_select = on_select
        self._refreshing = False
        self._search_timer = wx.Timer(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.search = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search.SetDescriptiveText("Find reference, value or side")
        self.search.ShowCancelButton(True)
        toolbar.Add(self.search, 1, wx.RIGHT, 8)
        self.included_only = wx.CheckBox(self, label="Show included only")
        toolbar.Add(self.included_only, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.select_all_button = wx.Button(self, label="Select all")
        self.select_none_button = wx.Button(self, label="Select none")
        self.select_visible_button = wx.Button(self, label="Include visible")
        self.restore_button = wx.Button(self, label="Restore saved row")
        for button in (self.select_all_button, self.select_none_button,
                       self.select_visible_button, self.restore_button):
            toolbar.Add(button, 0, wx.RIGHT, 4)
        layout.Add(toolbar, 0, wx.EXPAND | wx.BOTTOM, 6)
        self.scope = wx.StaticText(self)
        layout.Add(self.scope, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.grid = wx.grid.Grid(self)
        self.table = _InputTable(self)
        self.grid.SetTable(self.table, True)
        self.grid.SetRowLabelSize(0)
        self.grid.SetColLabelSize(38)
        self.grid.SetSelectionMode(wx.grid.Grid.SelectRows)
        self.grid.SetColFormatBool(0)
        for column, width in enumerate((66, 85, 62, 115, 95, 108, 108, 108,
                                       100, 100, 250, 250)):
            self.grid.SetColSize(column, width)
        layout.Add(self.grid, 1, wx.EXPAND)
        self.note = wx.StaticText(self, label=(
            "Edit any numeric cell; RθJB is optional and always editable. "
            "Blank means unknown. Power may be zero; resistances must be positive. "
            "Values stay in QuickTherm; the PCB is unchanged."))
        layout.Add(self.note, 0, wx.EXPAND | wx.TOP, 6)
        self.error = wx.StaticText(self, label="")
        layout.Add(self.error, 0, wx.EXPAND | wx.TOP, 3)
        self.SetSizer(layout)
        self.search.Bind(wx.EVT_TEXT, self._search_changed)
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN,
                         lambda event: self.search.SetValue(""))
        self.Bind(wx.EVT_TIMER, self._filter, self._search_timer)
        self.included_only.Bind(wx.EVT_CHECKBOX, self._filter)
        self.select_all_button.Bind(wx.EVT_BUTTON,
                                    lambda event: self._select_all(True))
        self.select_none_button.Bind(wx.EVT_BUTTON,
                                     lambda event: self._select_all(False))
        self.select_visible_button.Bind(wx.EVT_BUTTON, self._select_visible)
        self.restore_button.Bind(wx.EVT_BUTTON, self._restore_saved)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGING, self._changing)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self._changed)
        self.grid.Bind(wx.grid.EVT_GRID_SELECT_CELL, self._selected)
        self.Bind(wx.EVT_SIZE, self._size)
        self._update_scope()

    def _size(self, event):
        self.note.Wrap(max(200, self.GetClientSize().width - 12))
        event.Skip()

    def load(self, inventory, field_map=None, manual_values=None,
             selected_references=None, limit_field_map=None):
        self.commit_pending_edits(validate=False)
        self.model = ComponentInputsModel(inventory, field_map, manual_values,
                                          selected_references, limit_field_map)
        self._refresh_rows()

    def set_mappings(self, field_map, limit_field_map=None):
        self.commit_pending_edits(validate=False)
        self.model.set_mappings(field_map, limit_field_map)
        self.grid.ForceRefresh()
        self._notify()

    def commit_pending_edits(self, validate=True):
        if self.grid.IsCellEditControlEnabled():
            row, column = self.grid.GetGridCursorRow(), self.grid.GetGridCursorCol()
            if 4 <= column < 10:
                editor = self.grid.GetCellEditor(row, column)
                try:
                    raw = editor.GetControl().GetValue()
                    parse_input(raw, QUANTITIES[column - 4])
                except ValueError as exc:
                    self.error.SetLabel(str(exc))
                    raise
                finally:
                    editor.DecRef()
            self.grid.SaveEditControlValue()
            self.grid.DisableCellEditControl()
        if validate:
            self.model.validate()

    def export_state(self):
        self.commit_pending_edits(validate=False)
        return self.model.export_state()

    def manual_values(self):
        self.commit_pending_edits(validate=False)
        return self.model.manual_values()

    def effective_values(self, selected_only=True, include_limits=True):
        self.commit_pending_edits(validate=False)
        return self.model.effective_values(selected_only, include_limits)

    def selected_references(self):
        return self.model.selected_references()

    def _search_changed(self, event):
        self._search_timer.StartOnce(180)
        event.Skip()

    def _filter(self, event=None):
        try:
            self.commit_pending_edits(validate=False)
        except ValueError:
            return
        self._refresh_rows()

    def _refresh_rows(self):
        refs = self.model.visible_references(self.search.GetValue(),
                                             self.included_only.GetValue())
        if refs != self.table.references:
            self._refreshing = True
            self.grid.BeginBatch()
            try:
                old_count = len(self.table.references)
                self.table.references = []
                if old_count:
                    self.grid.ProcessTableMessage(wx.grid.GridTableMessage(
                        self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED, 0, old_count))
                self.table.references = refs
                if refs:
                    self.grid.ProcessTableMessage(wx.grid.GridTableMessage(
                        self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_APPENDED, len(refs)))
            finally:
                self.grid.EndBatch()
                self._refreshing = False
        self.grid.ForceRefresh()
        self._update_scope()

    def _update_scope(self):
        selected = len(self.model.selected_references())
        self.scope.SetLabel(
            f"{selected} included of {len(self.model.references)} components · "
            f"{len(self.table.references)} visible. Run uses every checked row, "
            "including hidden rows. Select all/none affects the full board.")

    def _notify(self):
        self._update_scope()
        if self.on_change:
            self.on_change(self.model.export_state())

    def _select_all(self, included):
        try:
            self.commit_pending_edits(validate=False)
        except ValueError:
            return
        self.model.select_all(included=included)
        self._refresh_rows()
        self._notify()

    def _select_visible(self, event=None):
        try:
            self.commit_pending_edits(validate=False)
        except ValueError:
            return
        self.model.select_all(self.table.references)
        self._refresh_rows()
        self._notify()

    def _restore_saved(self, event=None):
        try:
            self.commit_pending_edits(validate=False)
        except ValueError:
            return
        indices = list(self.grid.GetSelectedRows())
        if not indices and self.grid.GetGridCursorRow() >= 0:
            indices = [self.grid.GetGridCursorRow()]
        self.model.restore_saved([self.table.references[index] for index in indices
                                  if index < len(self.table.references)])
        self.error.SetLabel("")
        self.grid.ForceRefresh()
        self._notify()

    def _changing(self, event):
        column = event.GetCol()
        if 4 <= column < 10:
            try:
                parse_input(event.GetString(), QUANTITIES[column - 4])
            except ValueError as exc:
                self.error.SetLabel(str(exc))
                self.error.SetForegroundColour(wx.Colour(175, 35, 35))
                self.Layout()
                event.Veto()
                return
        self.error.SetLabel("")
        event.Skip()

    def _changed(self, event):
        self.grid.ForceRefresh()
        self._notify()
        if self.included_only.GetValue() and event.GetCol() == 0:
            wx.CallAfter(self._refresh_rows)
        event.Skip()

    def _selected(self, event):
        if not self._refreshing and 0 <= event.GetRow() < len(self.table.references):
            if self.on_select:
                self.on_select(self.table.references[event.GetRow()])
        event.Skip()
