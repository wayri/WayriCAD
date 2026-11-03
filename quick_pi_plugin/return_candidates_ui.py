"""Explicit review of geometry-ranked return candidates."""
import wx


def choose_candidate(parent, envelope):
    rows = envelope.get('candidates', [])
    dialog = wx.Dialog(parent, title='Review return candidates', size=(780, 530),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    intro = wx.StaticText(dialog, label=(
        f"Evaluated {envelope.get('evaluated_count', len(rows))} of "
        f"{envelope.get('candidate_count', len(rows))} zone nets. "
        'Choose a candidate after reviewing the saved copper evidence.'))
    intro.Wrap(730); layout.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
    table = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    for column, (label, width) in enumerate((('Net', 190), ('Covered samples', 130), ('Evidence', 390))):
        table.InsertColumn(column, label, width=width)
    for row in rows:
        index = table.InsertItem(table.GetItemCount(), row['net'])
        table.SetItem(index, 1, f"{row['covered_samples']} / {row['total_samples']}")
        table.SetItem(index, 2, row['status'])
    layout.Add(table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
    details = wx.TextCtrl(dialog, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 150))
    limitations = '\n'.join(envelope.get('limitations', []))
    if envelope.get('truncated'):
        limitations = 'Candidate list truncated; some nets were not evaluated.\n' + limitations
    details.SetValue(limitations); layout.Add(details, 0, wx.EXPAND | wx.ALL, 12)
    buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
    apply = dialog.FindWindowById(wx.ID_OK); apply.SetLabel('Use selected net'); apply.Enable(False)
    layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
    def selected(event):
        row = rows[event.GetIndex()]
        details.SetValue(row['reason'] + '\n\n' + limitations)
        apply.Enable(True)
    table.Bind(wx.EVT_LIST_ITEM_SELECTED, selected)
    dialog.SetSizer(layout)
    try:
        if dialog.ShowModal() == wx.ID_OK:
            index = table.GetFirstSelected()
            if index >= 0:
                return rows[index]['net']
        return None
    finally:
        dialog.Destroy()
