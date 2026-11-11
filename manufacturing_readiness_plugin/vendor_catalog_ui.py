"""Show sourced preset coverage separately from the manufacturer directory."""
from __future__ import annotations
import wx
from .vendor_process_ui import choose_process


def choose_vendor(parent, catalog):
    dialog = wx.Dialog(parent, title='Manufacturer coverage and source documents', size=(1000, 650),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    note = wx.StaticText(dialog, label='A listed manufacturer is not a validated process profile. Select the exact service and confirm the quote. Missing limits are never populated from another manufacturer.')
    note.Wrap(940); layout.Add(note, 0, wx.EXPAND | wx.ALL, 10)
    search = wx.SearchCtrl(dialog); search.SetDescriptiveText('Find manufacturer or region'); layout.Add(search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    table = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    for index, (label, width) in enumerate([('Manufacturer', 220), ('Region', 150), ('Coverage', 245), ('Services', 230)]): table.InsertColumn(index, label, width=width)
    layout.Add(table, 1, wx.EXPAND | wx.ALL, 10)
    details = wx.TextCtrl(dialog, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 130)); layout.Add(details, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    use = wx.Button(dialog, wx.ID_OK, 'Choose this vendor’s preset'); use.Disable(); buttons.Add(use, 0, wx.ALL, 10)
    buttons.AddStretchSpacer(); buttons.Add(wx.Button(dialog, wx.ID_CANCEL, 'Close'), 0, wx.ALL, 10); layout.Add(buttons, 0, wx.EXPAND)
    rows = []
    def refresh(_event=None):
        rows[:] = [row for row in catalog['vendors'] if search.GetValue().casefold() in (row['name']+' '+row['region']).casefold()]
        table.DeleteAllItems(); use.Disable(); details.Clear()
        for row in rows:
            index = table.InsertItem(table.GetItemCount(), row['name']); table.SetItem(index, 1, row['region'])
            profiles = [profile for profile in catalog['profiles'] if profile['vendor'] == row['name']]
            native = any(rule['backend'] == 'native_drc' for profile in profiles for rule in profile['rules'])
            table.SetItem(index, 2, 'Partial native presets available' if native else 'Manual checklist; rules need confirmation' if profiles else 'Supplier confirmation needed')
            table.SetItem(index, 3, ', '.join(row['services']))
    def select(event):
        row = rows[event.GetIndex()]
        details.SetValue(row['notes']+'\n\nSource references:\n'+'\n'.join(row['source_urls']))
        use.Enable(any(profile['vendor'] == row['name'] for profile in catalog['profiles']))
    search.Bind(wx.EVT_TEXT, refresh); table.Bind(wx.EVT_LIST_ITEM_SELECTED, select)
    refresh(); dialog.SetSizer(layout)
    work = wx.Display(max(0, wx.Display.GetFromWindow(parent))).GetClientArea()
    dialog.SetSize((min(1000, work.width-30), min(650, work.height-40))); dialog.CentreOnParent()
    try:
        if dialog.ShowModal() == wx.ID_OK and table.GetFirstSelected() >= 0:
            return rows[table.GetFirstSelected()]['name']
        return None
    finally:
        dialog.Destroy()
