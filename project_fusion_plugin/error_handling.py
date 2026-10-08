"""Actionable recovery guidance; original backend evidence remains visible."""

def recovery(error):
    """Return a next step without treating failed checks as permission to apply."""
    message=str(error).lower()
    if 'rollback' in message or 'restore failed' in message:
        return 'Inspect the reported backup and transaction receipt before doing anything else. Verify the saved project in KiCad; do not retry Apply until recovery is complete.'
    if any(word in message for word in ('stale', 'source changed', 'target changed', 'hash mismatch', 'changed after')):
        return 'Save the latest design, then run Preview again. Review the new changes before Apply; the earlier review is no longer valid.'
    if any(word in message for word in ('lock', 'editors closed', 'editor is open')):
        return 'Save and close this project in KiCad, including its project manager. Then run a fresh Preview. Do not remove a lock belonging to a running editor.'
    if any(word in message for word in ('permission', 'access is denied', 'read-only', 'errno 13')):
        return 'Choose a writable candidate/output folder and check file permissions and available storage. Keep the original project and backup intact, then preview again.'
    if any(word in message for word in ('kicad-cli', 'executable', 'cannot locate a python')):
        return 'Check that KiCad is installed and select its matching kicad-cli executable in Merge settings. Retry Preview after correcting runtime discovery.'
    if any(word in message for word in ('no such file', 'not found', 'missing', 'cannot find')):
        return 'Check the saved source/target paths and required companion files or dependencies. Correct the source settings, then run Preview again.'
    return 'Read the details and source issues, correct the reported settings or design in a source copy, then run Preview again. Do not bypass a failed validation.'


def show_error(parent, error, title='Fusion operation stopped'):
    """Show selectable details and a recovery step in a native, copyable dialog."""
    import wx
    dialog=wx.Dialog(parent,title=title,size=(700,420),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
    from .variant_import_gui import apply_window_icon
    apply_window_icon(dialog)
    box=wx.BoxSizer(wx.VERTICAL)
    guidance=wx.StaticText(dialog,label=recovery(error));guidance.Wrap(650)
    box.Add(guidance,0,wx.ALL|wx.EXPAND,12)
    details=wx.TextCtrl(dialog,value=str(error),style=wx.TE_MULTILINE|wx.TE_READONLY)
    box.Add(details,1,wx.LEFT|wx.RIGHT|wx.BOTTOM|wx.EXPAND,12)
    buttons=wx.BoxSizer(wx.HORIZONTAL)
    copy=wx.Button(dialog,label='Copy details')
    def copy_details(event):
        if wx.TheClipboard.Open():
            try:wx.TheClipboard.SetData(wx.TextDataObject(str(error)+'\n\n'+recovery(error)))
            finally:wx.TheClipboard.Close()
    copy.Bind(wx.EVT_BUTTON,copy_details);buttons.Add(copy,0,wx.RIGHT,8)
    buttons.Add(dialog.CreateButtonSizer(wx.OK),0)
    box.Add(buttons,0,wx.ALL|wx.ALIGN_RIGHT,12);dialog.SetSizer(box)
    try:dialog.ShowModal()
    finally:dialog.Destroy()
