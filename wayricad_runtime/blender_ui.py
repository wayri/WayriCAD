"""Explicit, background export of completed analysis evidence for Blender."""
from __future__ import annotations

from pathlib import Path
import re


def destination(parent, name):
    """Return a new child directory, rejecting aliases and Windows device names."""
    name = str(name)
    if re.search(r'[\x00-\x1f]', name):
        raise ValueError('Choose a normal new folder name without control characters.')
    name = name.strip()
    if (not name or name in ('.', '..') or re.search(r'[<>:"/\\|?*]', name)
            or name.endswith(('.', ' ')) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I)):
        raise ValueError('Choose a normal new folder name without path separators.')
    parent = Path(parent).expanduser().resolve(strict=True)
    if not parent.is_dir():
        raise ValueError('Choose an existing parent folder.')
    target = parent / name
    if target.exists() or target.is_symlink():
        raise ValueError('The export folder already exists. Choose a new name; existing files are retained.')
    return target


def choose_export(parent, bundle, tool, submit, status):
    """Choose a bundle folder and submit work through the host's worker.

    ``submit(operation, finished, message)`` runs operation away from the UI and
    invokes finished on its UI thread. ``status(text)`` reports host feedback.
    Blender is optional and is launched only after explicit user selection.
    """
    import wx

    dialog = wx.Dialog(parent, title='Export to Blender', style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    intro = wx.StaticText(dialog, label='Export completed geometry and result fields. This creates a new folder; it does not change the PCB.')
    intro.Wrap(570)
    layout.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
    layout.Add(wx.StaticText(dialog, label='Parent folder'), 0, wx.LEFT | wx.RIGHT, 12)
    folder = wx.DirPickerCtrl(dialog, path=str(Path.home()), style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
    layout.Add(folder, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    layout.Add(wx.StaticText(dialog, label='New export folder'), 0, wx.LEFT | wx.RIGHT, 12)
    name = wx.TextCtrl(dialog, value='wayricad-' + tool + '-blender')
    layout.Add(name, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    fields = {'pi': [('voltage', 'Potential · V'), ('drop', 'Voltage drop · mV'),
                     ('density', 'Current density · A/mm²'), ('loss', 'Cell dissipated power · W')],
              'si': [('delay', 'Section screening delay · ns'), ('impedance', 'Section impedance · Ω'),
                     ('resistance', 'Section resistance · Ω')],
              'therm': [('temperature', 'Temperature · °C')]}[tool]
    layout.Add(wx.StaticText(dialog, label='Result field'), 0, wx.LEFT | wx.RIGHT, 12)
    metric = wx.Choice(dialog, choices=[label for key, label in fields])
    metric.SetSelection(0)
    metric.SetToolTip('Choose a supported saved scalar field. Unknown values stay unavailable.')
    layout.Add(metric, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    launch = wx.CheckBox(dialog, label='Open Blender after export')
    launch.SetToolTip('Optional. Blender must already be installed; no software is downloaded.')
    layout.Add(launch, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    layout.Add(wx.StaticText(dialog, label='Blender executable (optional; blank uses automatic discovery)'), 0, wx.LEFT | wx.RIGHT, 12)
    executable = wx.FilePickerCtrl(dialog, message='Choose Blender executable', style=wx.FLP_USE_TEXTCTRL | wx.FLP_FILE_MUST_EXIST)
    executable.Disable()
    launch.Bind(wx.EVT_CHECKBOX, lambda event: executable.Enable(launch.GetValue()))
    layout.Add(executable, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    note = wx.StaticText(dialog, label='Animation uses stored computed samples where available. Static fields do not become a transient simulation. Component envelopes are not STEP models.')
    note.Wrap(570)
    layout.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
    dialog.FindWindow(wx.ID_OK).SetLabel('Export')
    layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
    dialog.SetSizerAndFit(layout)
    dialog.SetMinSize(dialog.GetSize())
    target = None
    try:
        while dialog.ShowModal() == wx.ID_OK:
            try:
                target = destination(folder.GetPath(), name.GetValue())
                break
            except (ValueError, OSError) as exc:
                wx.MessageBox(str(exc), 'Choose a new export folder', wx.OK | wx.ICON_WARNING, dialog)
        if target is None:
            return
        open_after = launch.GetValue()
        selected_metric = fields[metric.GetSelection()][0]
        blender = executable.GetPath().strip() or None
    finally:
        dialog.Destroy()

    def operation():
        from .blender_export import export_bundle
        result = {'export': export_bundle(bundle, target, tool=tool, metric=selected_metric), 'launched': False}
        if open_after:
            try:
                from .blender_export import run_blender
                run_blender(target, executable=blender, background=False)
                result['launched'] = True
            except (ValueError, OSError, RuntimeError) as exc:
                result['launch_error'] = str(exc)
        return result

    def finished(result):
        if result.get('launch_error'):
            status('Bundle exported. Blender did not open: ' + result['launch_error'])
        elif result.get('launched'):
            status('Exported bundle and opened Blender: ' + str(target))
        else:
            status('Exported Blender bundle: ' + str(target))

    submit(operation, finished, 'Preparing Blender geometry, fields and computed frames…')
