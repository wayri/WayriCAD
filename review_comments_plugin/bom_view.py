"""Read-only native field-value table; selecting a cell never publishes a note."""
from pathlib import Path

import wx
import wx.grid

from .bom_review import load_bom, bom_anchor
from .model import unchanged
from .theme import palette, apply_theme
from .widgets import ActionButton


class FieldTable(wx.grid.GridTableBase):
    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot
    def GetNumberRows(self): return len(self.snapshot['rows'])
    def GetNumberCols(self): return len(self.snapshot['columns'])
    def GetValue(self, row, col): return self.snapshot['rows'][row]['fields'].get(self.snapshot['columns'][col], '')
    def GetColLabelValue(self, col): return self.snapshot['columns'][col]
    def GetRowLabelValue(self, row):
        flags = self.snapshot['rows'][row]['flags']
        return str(row+1) + (' *' if flags.get('dnp') or not flags.get('in_bom', True) else '')
    def IsEmptyCell(self, row, col): return not bool(self.GetValue(row, col))


class BomView(wx.Panel):
    def __init__(self, parent, canvas):
        super().__init__(parent)
        self.canvas = canvas
        self.snapshot = None
        self.path = None
        layout = wx.BoxSizer(wx.VERTICAL)
        self.status = wx.StaticText(self, label='Saved KiCad fields · read only · edit the design in KiCad')
        layout.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        self.grid = wx.grid.Grid(self)
        self.grid.CreateGrid(0, 0)
        self.grid.EnableEditing(False)
        self.grid.SetSelectionMode(wx.grid.Grid.SelectCells)
        self.grid.SetRowLabelSize(45)
        self.grid.SetDefaultColSize(150)
        layout.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Comment on cell', self.comment_cell), ('Comment on row', self.comment_row),
                               ('Reload fields', self.reload), ('Back to drawing', self.back)]:
            controls.Add(ActionButton(self, label, handler, compact=True), 0, wx.RIGHT, 5)
        layout.Add(controls, 0, wx.ALL, 8)
        self.SetSizer(layout)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self.comment_cell)

    def load(self, path):
        owner = self.canvas.owner
        root = Path(owner.values['root']).resolve() if owner.values.get('root') else Path(path).parent.resolve()
        snapshot = load_bom(path, root=root)
        self.apply_snapshot(path, root, snapshot)

    def apply_snapshot(self, path, root, snapshot):
        self.path, self.root, self.snapshot = Path(path).resolve(), root, snapshot
        rows, columns = snapshot['rows'], snapshot['columns']
        self.table = FieldTable(snapshot)
        self.grid.SetTable(self.table, takeOwnership=True)
        if rows and columns: self.grid.SetGridCursor(0, 0)
        self.status.SetLabel(f"{snapshot['origin_file']} · {len(rows)} saved field rows · * DNP/excluded · variants are explicit saved metadata")
        self.canvas.set_variants(snapshot['variants'])
        self.apply_palette()

    def apply_palette(self):
        colors = palette(self.canvas.owner)
        apply_theme(self, self.canvas.owner.review_theme)
        self.grid.SetDefaultCellBackgroundColour(colors['surface'])
        self.grid.SetDefaultCellTextColour(colors['text'])
        self.grid.SetLabelBackgroundColour(colors['background'])
        self.grid.SetLabelTextColour(colors['text'])
        self.grid.SetGridLineColour(colors['border'])
        self.grid.SetSelectionBackground(colors['primary'])
        self.grid.SetSelectionForeground(colors['primary_text'])
        self.grid.ForceRefresh()

    def _comment(self, field):
        owner, snapshot = self.canvas.owner, self.snapshot
        try:
            if not snapshot or not owner.session or owner.session.status != 'synced':
                raise ValueError('Connect and refresh the matching saved design before commenting on fields.')
            owner.session.require_authorization()
            if owner.session.path != self.path:
                raise ValueError('Use Review this file for the table’s saved design before commenting.')
            for name, digest in snapshot['source_hashes'].items():
                unchanged(self.root / name, digest)
            index = self.grid.GetGridCursorRow()
            if not 0 <= index < len(snapshot['rows']):
                raise ValueError('Select a saved field row first.')
            column = self.grid.GetGridCursorCol()
            name = snapshot['columns'][column] if field and 0 <= column < len(snapshot['columns']) else None
            target = bom_anchor(owner.session.scope, snapshot['rows'][index], snapshot['source_hashes'],
                                field=name, variant=owner.review_variant)
            owner.set_target(target)
            owner.compose.SetFocus()
        except (ValueError, RuntimeError, OSError) as error:
            self.status.SetLabel(str(error))

    def comment_cell(self, event=None): self._comment(True)
    def comment_row(self, event=None): self._comment(False)
    def reload(self, event=None):
        if self.path: self.canvas.show_bom(path=self.path)
    def back(self, event=None): self.canvas.view_book.SetSelection(0)

    def focus_anchor(self, target):
        context = target.get('context', {})
        if context.get('type') != 'bom' or not self.snapshot:
            return False
        for index, row in enumerate(self.snapshot['rows']):
            if row['id'] == context['rowId']:
                field = context.get('field')
                if field and (field not in row['fields'] or field not in self.snapshot['columns']):
                    self.status.SetLabel('This BOM field no longer exists. The original comment context is retained.')
                    return False
                column = self.snapshot['columns'].index(field) if field in self.snapshot['columns'] else 0
                self.grid.SetGridCursor(index, column)
                self.grid.MakeCellVisible(index, column)
                self.canvas.view_book.SetSelection(1)
                if context['sourceFiles'] != self.snapshot['source_hashes']:
                    self.status.SetLabel('Changed since this comment · showing the current saved row · original context retained')
                return True
        self.status.SetLabel('This BOM row or field no longer exists. Its original comment context is retained.')
        return False
