"""Preview-and-apply thermal starting assumptions shared by native tools."""
from .thermal_defaults import FIELD_INFO, NOTICE, populate_settings


def choose_defaults(parent, current, title='Populate material and environment defaults'):
    """Return proposed values/changed keys, or None. Opening changes nothing."""
    import wx
    dialog = wx.Dialog(parent, title=title, size=(860, 700),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    result = None
    root = wx.BoxSizer(wx.VERTICAL)
    note = wx.StaticText(dialog, label=NOTICE); note.SetMinSize((1,-1)); note.Wrap(790)
    root.Add(note, 0, wx.EXPAND | wx.ALL, 12)
    line = wx.BoxSizer(wx.HORIZONTAL)
    line.Add(wx.StaticText(dialog, label='Starting ambient °C'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    current_ambient=current.get('ambient_c')
    ambient = wx.TextCtrl(dialog, value=str(current_ambient if current_ambient is not None and str(current_ambient).strip() else 20))
    line.Add(ambient, 0)
    root.Add(line, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    replace = wx.CheckBox(dialog, label='Replace existing inputs too · otherwise fill blanks only')
    root.Add(replace, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    preview = wx.TextCtrl(dialog, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
    root.Add(preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
    status = wx.StaticText(dialog, label=''); status.SetMinSize((1,-1)); root.Add(status, 0, wx.EXPAND | wx.ALL, 12)
    buttons = wx.BoxSizer(wx.HORIZONTAL); buttons.AddStretchSpacer()
    apply = wx.Button(dialog, label='Populate missing fields')
    buttons.Add(apply, 0, wx.RIGHT, 8); buttons.Add(wx.Button(dialog, wx.ID_CANCEL), 0)
    root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

    def proposal():
        return populate_settings(current, ambient_c=ambient.GetValue(), replace_existing=replace.GetValue())

    def resize(event=None):
        note.SetLabel(NOTICE);note.Wrap(max(300,dialog.GetClientSize().width-30))
        dialog.Layout()
        if event:event.Skip()

    def refresh(event=None):
        try:
            updated, changed = proposal()
            lines = []
            for key in current:
                if key not in FIELD_INFO:
                    continue
                label, unit = FIELD_INFO[key]
                before = current[key]
                before = 'Unknown' if before is None or str(before).strip() == '' else str(before)
                lines.append(label+' ['+unit+']: '+before+' → '+str(updated[key])+
                             ('  (populate)' if key in changed else '  (retain)'))
            preview.ChangeValue('\n'.join(lines))
            status.SetLabel(str(len(changed))+' field(s) will change. Existing values are retained unless replacement is selected.')
            status.Wrap(max(300,dialog.GetClientSize().width-30))
            apply.Enable(True)
        except ValueError as exc:
            status.SetLabel(str(exc)); apply.Enable(False)
        apply.SetLabel('Apply starting values' if replace.GetValue() else 'Populate missing fields')
        if event:event.Skip()

    def accept(event):
        nonlocal result
        try:
            updated, changed = proposal()
            result = {'values': updated, 'changed': changed}
            dialog.EndModal(wx.ID_OK)
        except ValueError as exc:status.SetLabel(str(exc))

    ambient.Bind(wx.EVT_TEXT, refresh); replace.Bind(wx.EVT_CHECKBOX, refresh)
    apply.Bind(wx.EVT_BUTTON, accept)
    dialog.Bind(wx.EVT_SIZE,resize)
    dialog.SetSizer(root); dialog.SetMinSize((700, 560)); refresh();resize()
    try:
        return result if dialog.ShowModal() == wx.ID_OK else None
    finally:
        dialog.Destroy()
