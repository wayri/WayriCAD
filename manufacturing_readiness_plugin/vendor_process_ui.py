"""Exact-process library browser; custom data never overwrites bundled rules."""
from pathlib import Path
import wx

from . import checklists
from .vendor_catalog import import_custom_profile, search_profiles, search_vendors


def choose_process(parent, catalog, *, layers=None):
    dialog = wx.Dialog(parent, title='Vendor process library', size=(1050, 690),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    search = wx.SearchCtrl(dialog)
    search.SetDescriptiveText('Search supplier, service, material or region')
    layout.Add(search, 0, wx.EXPAND | wx.ALL, 10)
    compatible = wx.CheckBox(dialog, label=f'Only presets supporting this board ({layers} copper layers)')
    compatible.SetValue(layers is not None); compatible.Enable(layers is not None)
    layout.Add(compatible, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
    tabs = wx.Notebook(dialog)
    presets = wx.ListCtrl(tabs, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    directory = wx.ListCtrl(tabs, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    for i, (name, width) in enumerate([('Supplier / process', 360), ('Layers', 100), ('Outer oz', 100), ('Copper basis', 160), ('Native checks', 110)]):
        presets.InsertColumn(i, name, width=width)
    for i, (name, width) in enumerate([('Supplier', 240), ('Region', 180), ('Services', 310), ('Preset count', 120)]):
        directory.InsertColumn(i, name, width=width)
    tabs.AddPage(presets, 'Process presets'); tabs.AddPage(directory, 'Supplier directory')
    layout.Add(tabs, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    details = wx.TextCtrl(dialog, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 145))
    layout.Add(details, 0, wx.EXPAND | wx.ALL, 10)
    buttons = wx.BoxSizer(wx.HORIZONTAL)
    use = wx.Button(dialog, wx.ID_OK, 'Use selected process'); use.Disable()
    importer = wx.Button(dialog, label='Import custom profile')
    exporter = wx.Button(dialog, label='Export selected profile'); exporter.Disable()
    for control in (importer, exporter, use): buttons.Add(control, 0, wx.RIGHT, 8)
    buttons.AddStretchSpacer(); buttons.Add(wx.Button(dialog, wx.ID_CANCEL, 'Close'))
    layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
    rows, vendors = [], []
    selected = [None]

    def refresh(_event=None):
        rows[:] = search_profiles(catalog, search.GetValue(), layers=layers if compatible.GetValue() else None)
        vendors[:] = search_vendors(catalog, search.GetValue())
        presets.DeleteAllItems(); directory.DeleteAllItems()
        selected[0] = None; use.Disable(); exporter.Disable()
        details.SetValue(f'{len(rows)} matching process presets; {len(vendors)} suppliers. '
                         'Public limits are conditional screening inputs, not supplier approval. Select the exact service and confirm your quote.')
        for profile in rows:
            process = profile['process']; i = presets.InsertItem(presets.GetItemCount(), profile['name'])
            values = [str(process.get('layers')), str(process.get('copper_oz')), str(process.get('copper_basis', 'Unspecified')),
                      str(sum(rule['backend'] == 'native_drc' for rule in profile['rules']))]
            for j, value in enumerate(values, 1): presets.SetItem(i, j, value)
        for vendor in vendors:
            i = directory.InsertItem(directory.GetItemCount(), vendor['name'])
            for j, value in enumerate([vendor['region'], ', '.join(vendor['services']),
                                      str(sum(row['vendor'] == vendor['name'] for row in catalog['profiles']))], 1):
                directory.SetItem(i, j, value)

    def select(event):
        profile = rows[event.GetIndex()]; selected[0] = profile
        lines = [profile['name'], profile['vendor'] + ' / ' + profile['service'], profile['revision'],
                 str(profile['process']), profile.get('notes', ''), '', 'Limits:']
        lines.extend(f"{rule['title']}: {rule.get('minimum')} .. {rule.get('maximum')} {rule.get('unit') or ''} ({rule['backend']})" for rule in profile['rules'])
        lines.extend('\n' + source['title'] + '\n' + source['url'] + '\nVerified: ' + str(source['verified']) for source in profile['sources'])
        details.SetValue('\n'.join(lines)); use.Enable(); exporter.Enable()

    def supplier(event):
        vendor = vendors[event.GetIndex()]
        selected[0] = None; use.Disable(); exporter.Disable()
        details.SetValue(vendor['notes'] + '\n\n' + '\n'.join(vendor['source_urls']))

    def import_profile(_event):
        nonlocal catalog
        with wx.FileDialog(dialog, 'Import a custom process profile', wildcard='JSON (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as file:
            if file.ShowModal() != wx.ID_OK: return
            try:
                path = Path(file.GetPath())
                if path.stat().st_size > checklists.MAX_DOCUMENT_BYTES: raise ValueError('Profile exceeds 2 MiB.')
                catalog = import_custom_profile(catalog, path.read_text(encoding='utf-8-sig'))
                search.ChangeValue(''); compatible.SetValue(False); refresh()
            except (OSError, ValueError) as exc: wx.MessageBox(str(exc), 'Profile import failed', wx.OK | wx.ICON_ERROR, dialog)

    def export_profile(_event):
        if selected[0] is None: return
        with wx.FileDialog(dialog, 'Export process profile', defaultFile=selected[0]['id']+'.json', wildcard='JSON (*.json)|*.json', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as file:
            if file.ShowModal() != wx.ID_OK: return
            try:
                destination = Path(file.GetPath()).resolve()
                if destination == Path(__file__).with_name('vendor_catalog.json').resolve(): raise ValueError('Do not overwrite the bundled catalogue.')
                checklists.save_profile(destination, selected[0])
            except (OSError, ValueError) as exc: wx.MessageBox(str(exc), 'Profile export failed', wx.OK | wx.ICON_ERROR, dialog)

    search.Bind(wx.EVT_TEXT, refresh); compatible.Bind(wx.EVT_CHECKBOX, refresh)
    presets.Bind(wx.EVT_LIST_ITEM_SELECTED, select); directory.Bind(wx.EVT_LIST_ITEM_SELECTED, supplier)
    tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, lambda event: (selected.__setitem__(0, None), use.Disable(), exporter.Disable(), event.Skip()))
    importer.Bind(wx.EVT_BUTTON, import_profile); exporter.Bind(wx.EVT_BUTTON, export_profile)
    refresh(); dialog.SetSizer(layout); dialog.SetMinSize((760, 500)); dialog.CentreOnParent()
    try:
        accepted = dialog.ShowModal() == wx.ID_OK
        return (selected[0]['id'] if accepted and selected[0] else None), catalog
    finally: dialog.Destroy()
