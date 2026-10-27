"""Reviewed per-case endpoint shunt banks for the native circuit exporter."""
import copy
import wx
import wx.grid

from .shunt_caps import editor_rows, editor_branches, MAX_TOTAL_CAPACITORS


def shunt_capacitor_dialog(parent, case_ids, initial=None):
    """Return detached capacitor banks after Apply, or None after Cancel."""
    dialog = wx.Dialog(parent, title='SI transient circuit · Shunt capacitors', size=(830, 540),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    dialog.SetMinSize(dialog.FromDIP((560, 390)))
    root = wx.BoxSizer(wx.VERTICAL)
    text = ('Add explicit source/receiver shunt branches to the exported KiCad/ngspice circuit. '
            'Each capacitor has its own series ESR and ESL to ideal common ground; zero omits that parasitic. '
            'The built-in illustrative eye does not use these parts. No PCB component or value is changed.')
    note = wx.StaticText(dialog, label=text); root.Add(note, 0, wx.EXPAND | wx.ALL, 10)
    grid = wx.grid.Grid(dialog)
    grid.SetMinSize((1,120))
    rows = editor_rows(initial or {})
    grid.CreateGrid(max(1, len(rows)), 6); grid.SetColLabelSize(38)
    for index, label in enumerate(('Case', 'Capacitor ID', 'At endpoint', 'C · nF', 'ESR · mΩ', 'ESL · nH')):
        grid.SetColLabelValue(index, label); grid.SetColSize(index, 125 if index < 3 else 95)
    def configure(row):
        grid.SetCellEditor(row, 0, wx.grid.GridCellChoiceEditor(list(case_ids), False))
        grid.SetCellEditor(row, 2, wx.grid.GridCellChoiceEditor(['source','receiver'], False))
        if case_ids:grid.SetCellValue(row, 0, case_ids[0])
        grid.SetCellValue(row, 2, 'receiver')
    for row in range(grid.GetNumberRows()):
        configure(row)
        if row < len(rows):
            for col, value in enumerate(rows[row]):grid.SetCellValue(row, col, str(value))
    root.Add(grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    error = wx.StaticText(dialog, label='Enter actual capacitance; C is never guessed. Unused blank rows are ignored.')
    error.SetForegroundColour(wx.Colour(130, 60, 30)); root.Add(error, 0, wx.EXPAND | wx.ALL, 10)
    actions = wx.WrapSizer(wx.HORIZONTAL)
    add = wx.Button(dialog, label='Add capacitor'); remove = wx.Button(dialog, label='Remove selected')
    for button in (add, remove):actions.Add(button, 0, wx.RIGHT | wx.BOTTOM, 8)
    root.Add(actions, 0, wx.LEFT | wx.RIGHT, 10)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    cancel = wx.Button(dialog, wx.ID_CANCEL); apply = wx.Button(dialog, label='Apply capacitor bank')
    for button in (cancel, apply):buttons.Add(button, 0, wx.ALL, 8)
    root.Add(buttons, 0, wx.ALIGN_RIGHT); dialog.SetSizer(root)
    result = {}
    def append(event):
        if grid.GetNumberRows() >= MAX_TOTAL_CAPACITORS:
            error.SetLabel(f'At most {MAX_TOTAL_CAPACITORS} capacitors per export.');return
        grid.AppendRows();configure(grid.GetNumberRows()-1)
    def delete(event):
        if grid.GetNumberRows()>1:grid.DeleteRows(max(0,grid.GetGridCursorRow()))
        else:
            for col in (1,3,4,5):grid.SetCellValue(0,col,'')
    def accept(event):
        grid.SaveEditControlValue();grid.DisableCellEditControl()
        values=[[grid.GetCellValue(row,col) for col in range(6)] for row in range(grid.GetNumberRows())]
        try:mapping=editor_branches(values,case_ids)
        except ValueError as caught:
            error.SetLabel(str(caught));error.Wrap(max(200,dialog.GetClientSize().width-24));dialog.Layout();return
        result.update(mapping);dialog.EndModal(wx.ID_OK)
    def wrap(event=None):
        note.SetMinSize((1,-1));note.SetLabel(text);note.Wrap(max(200,dialog.GetClientSize().width-24))
        dialog.Layout()
        if event:event.Skip()
    add.Bind(wx.EVT_BUTTON,append);remove.Bind(wx.EVT_BUTTON,delete);apply.Bind(wx.EVT_BUTTON,accept)
    dialog.Bind(wx.EVT_SIZE,wrap);wrap()
    dialog.shunt_controls=dict(grid=grid,apply=apply,error=error)
    try:return copy.deepcopy(result) if dialog.ShowModal()==wx.ID_OK else None
    finally:dialog.Destroy()
