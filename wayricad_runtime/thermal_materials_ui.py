"""Native explicit-apply picker shared by independently installed analysis tools."""
from __future__ import annotations

from .thermal_materials import (PROPERTY_LABELS, PROPERTY_UNITS, get_material,
                                list_materials, review_material)


class ThermalMaterialDialog:
    """Show ``dialog.ShowModal()``; accepted reviewed record is ``selection``.

    Limit ``properties`` to inputs the calling model can actually consume.
    The caller explicitly binds numeric values to its controls and retains the
    selection as provenance; opening this dialog changes no model input.
    """
    def __init__(self, parent, *, properties=None, category=None, initial_id=None):
        import wx
        self.wx = wx; self.selection = None
        self.allowed = list(PROPERTY_UNITS) if properties is None else list(properties)
        if not self.allowed or set(self.allowed) - PROPERTY_UNITS.keys():
            raise ValueError('Choose supported thermal material properties.')
        self.records = list_materials(category)
        if not any(row['id'] == 'custom' for row in self.records): self.records.append(get_material('custom'))
        self.dialog = wx.Dialog(parent, title='Thermal material library · review and apply',
                                size=(820, 700), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        root = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self.dialog, label='Choose a reference, review its source and conditions, then check only the properties to apply. '
                             'Unknown values stay blank. Typical data and illustrative assumptions need design review.')
        note.Wrap(760); root.Add(note, 0, wx.EXPAND | wx.ALL, 12)
        self.choice = wx.Choice(self.dialog, choices=[row['name'] for row in self.records])
        selected = next((i for i, row in enumerate(self.records) if row['id'] == initial_id), 0)
        self.choice.SetSelection(selected); self.choice.Bind(wx.EVT_CHOICE, self._choose)
        root.Add(self.choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.evidence = wx.TextCtrl(self.dialog, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 190))
        root.Add(self.evidence, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.values = {}; self.checks = {}; form = wx.FlexGridSizer(0, 3, 9, 10); form.AddGrowableCol(1)
        for key in self.allowed:
            check = wx.CheckBox(self.dialog, label=PROPERTY_LABELS[key]); control = wx.TextCtrl(self.dialog)
            self.values[key] = control; self.checks[key] = check
            form.Add(check, 0, wx.ALIGN_CENTER_VERTICAL); form.Add(control, 1, wx.EXPAND)
            form.Add(wx.StaticText(self.dialog, label=PROPERTY_UNITS[key]), 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(form, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        root.Add(wx.StaticText(self.dialog, label='Review note · source, temperature, direction, grade or reason for an override'), 0, wx.LEFT | wx.RIGHT, 12)
        self.review_note = wx.TextCtrl(self.dialog, style=wx.TE_MULTILINE, size=(-1, 70))
        root.Add(self.review_note, 0, wx.EXPAND | wx.ALL, 12)
        self.reviewed = wx.CheckBox(self.dialog, label='I reviewed these selected values, units and their applicability to this model')
        root.Add(self.reviewed, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.status = wx.StaticText(self.dialog, label='No model input changes until Apply selected properties.')
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL); buttons.AddStretchSpacer()
        apply = wx.Button(self.dialog, label='Apply selected properties'); apply.Bind(wx.EVT_BUTTON, self._apply)
        buttons.Add(apply, 0, wx.RIGHT, 8); buttons.Add(wx.Button(self.dialog, wx.ID_CANCEL), 0)
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.dialog.SetSizer(root); self.dialog.SetMinSize((700, 620)); self._choose()

    def _choose(self, event=None):
        record = self.records[self.choice.GetSelection()]
        lines = [record['name'], record['note'], '', record['source']['title'],
                 record['source'].get('revision', ''), record['source'].get('url', '')]
        for key, prop in record['properties'].items():
            lines.extend(['', PROPERTY_LABELS[key] + ': ' + str(prop['value']) + ' ' + prop['unit'],
                          'Basis: ' + prop['basis'], prop['conditions'], prop['method']])
        self.evidence.SetValue('\n'.join(lines))
        for key in self.allowed:
            prop = record['properties'].get(key)
            self.values[key].SetValue(str(prop['value']) if prop else '')
            self.checks[key].SetValue(bool(prop) and key == 'thermal_conductivity_w_mk')
        self.reviewed.SetValue(False); self.review_note.SetValue('')
        self.status.SetLabel('Select properties and review their conditions before applying.')

    def selected_record(self):
        """Non-mutating validation entrypoint, also useful for native tests."""
        record = self.records[self.choice.GetSelection()]
        selected = [key for key in self.allowed if self.checks[key].GetValue()]
        values = {}
        for key in selected:
            try: values[key] = float(self.values[key].GetValue())
            except ValueError as exc: raise ValueError(PROPERTY_LABELS[key] + ': enter a known positive SI value.') from exc
        return review_material(record['id'], selected=selected, overrides=values,
                               reviewed=self.reviewed.GetValue(), review_note=self.review_note.GetValue())

    def _apply(self, event=None):
        try:
            self.selection = self.selected_record(); self.dialog.EndModal(self.wx.ID_OK)
        except ValueError as exc:
            self.status.SetLabel(str(exc)); self.status.Wrap(self.dialog.GetClientSize().width - 24); self.dialog.Layout()
