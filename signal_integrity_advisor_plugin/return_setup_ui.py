"""Small, explicit return-path setup for the common single-return workflow."""
from __future__ import annotations

import wx

from wayricad_runtime.readable_choice import ReadableComboBox, SearchableCheckListBox
from wayricad_runtime.searchable_selection import searchable_row


NO_REVIEW = 'No return-path check'
UNSPECIFIED = 'Not specified'


def reference_for_label(terminals, label):
    """Find the actual footprint reference without splitting dotted pad numbers."""
    references = {row['reference'] for row in terminals if row['label'] == label}
    return next(iter(references)) if len(references) == 1 else None


def ranked_pad_labels(terminals, nets, reference=None):
    """Put the chosen endpoint's return pads first, retaining explicit selection."""
    rows = [row for row in terminals if row['net'] in nets]
    rows.sort(key=lambda row: (row['reference'] != reference, row['reference'].casefold(), row['label'].casefold()))
    return list(dict.fromkeys(row['label'] for row in rows))


class ReturnSetupPanel(wx.Panel):
    """One visible return choice; multi-net and endpoint details stay optional."""
    def __init__(self, parent, nets, terminals, layers, on_change, on_layout):
        super().__init__(parent)
        self._names = list(nets); self._terminals = list(terminals)
        self._on_change = on_change; self._on_layout = on_layout
        self._setting = False; self._signal = ''; self._endpoints = ('', '')
        self._suggestion = None
        self._terminal_values = {}
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label='Return path (optional)')
        title.SetFont(title.GetFont().Bold()); root.Add(title, 0, wx.TOP, 9)
        self.primary = ReadableComboBox(self, choices=[NO_REVIEW]+self._names,
                                        value=NO_REVIEW, style=wx.CB_READONLY)
        self.primary.SetToolTip('Choose the actual return net to include its geometric review. Ctrl+F searches full names. No return current is inferred from a name.')
        self.primary.SetMinSize((1,-1))
        root.Add(self.primary, 0, wx.EXPAND|wx.TOP, 4)
        self.suggested = wx.StaticText(self, label='Choose the actual return net, or leave the review off.')
        self.suggested.Wrap(290); root.Add(self.suggested, 0, wx.EXPAND|wx.TOP, 4)
        self.use_suggestion = wx.Button(self, label='Use suggested return')
        self.use_suggestion.Disable(); root.Add(self.use_suggestion, 0, wx.EXPAND|wx.TOP, 4)
        self.summary = wx.StaticText(self, label='Return review is off. Source and receiver return pins are optional.')
        self.summary.Wrap(290); root.Add(self.summary, 0, wx.EXPAND|wx.TOP, 4)
        self.more = wx.CollapsiblePane(self, label='More return options',
            style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        host = self.more.GetPane(); details = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(host, label='Add other actual return nets only when needed. Optional pins record endpoint evidence; they do not create a solved return-current loop.')
        note.Wrap(285); details.Add(note, 0, wx.EXPAND|wx.BOTTOM, 4)
        self.nets = SearchableCheckListBox(host, choices=self._names, size=(-1, 105))
        self.nets.SetMinSize((1,105))
        details.Add(searchable_row(self.nets), 0, wx.EXPAND)
        self.source = ReadableComboBox(host, choices=[UNSPECIFIED], value=UNSPECIFIED, style=wx.CB_READONLY)
        self.sink = ReadableComboBox(host, choices=[UNSPECIFIED], value=UNSPECIFIED, style=wx.CB_READONLY)
        self.source.SetMinSize((1,-1)); self.sink.SetMinSize((1,-1))
        for label, control in [('Source return pin (optional; same part first)', self.source),
                               ('Receiver return pin (optional; same part first)', self.sink)]:
            details.Add(wx.StaticText(host, label=label), 0, wx.TOP, 6)
            details.Add(control, 0, wx.EXPAND)
            control.Bind(wx.EVT_COMBOBOX, self._pad_changed)
        details.Add(wx.StaticText(host, label='Impedance reference layer'), 0, wx.TOP, 6)
        self.reference = ReadableComboBox(host, choices=['Auto']+list(layers), value='Auto', style=wx.CB_READONLY)
        self.reference.SetMinSize((1,-1))
        self.reference.SetToolTip('Auto uses the existing geometry/stackup reference selection. This is separate from which net is checked for return-copper coverage.')
        details.Add(self.reference, 0, wx.EXPAND)
        host.SetSizer(details); root.Add(self.more, 0, wx.EXPAND|wx.TOP, 5)
        self.SetSizer(root); self.SetMinSize((1,-1)); self.more.SetMinSize((1,-1))
        self.primary.Bind(wx.EVT_COMBOBOX, self._primary_changed)
        self.nets.Bind(wx.EVT_CHECKLISTBOX, self._nets_changed)
        self.use_suggestion.Bind(wx.EVT_BUTTON, self._use_suggested)
        self.more.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda event: self._on_layout())

    def selected_nets(self):
        return [self.nets.GetString(i) for i in self.nets.GetCheckedItems()]

    def set_context(self, signal, source='', receiver=''):
        """Refresh suggestions and pad ordering without accepting a return guess."""
        from wayricad_runtime.return_setup import suggest_return_nets
        if signal == self._signal and (source, receiver) == self._endpoints:
            return
        if signal == self._signal:
            self._setting = True
            try:
                for control, previous, current in zip((self.source, self.sink), self._endpoints, (source, receiver)):
                    if previous != current: control.SetValue(UNSPECIFIED)
                self._endpoints = (source, receiver); self._refresh_pads()
            finally: self._setting = False
            return
        selected = set(self.selected_nets())-{signal}
        changed_signal = signal != self._signal
        self._signal = signal; self._endpoints = (source, receiver)
        self._setting = True
        try:
            names = [name for name in self._names if name != signal]
            primary = self.primary.GetValue()
            self.nets.Set(names)
            for index, name in enumerate(names): self.nets.Check(index, name in selected)
            self.primary.Set([NO_REVIEW]+names)
            self.primary.SetValue(primary if primary in selected else next(iter(sorted(selected)), NO_REVIEW))
            if changed_signal:
                self.source.SetValue(UNSPECIFIED); self.sink.SetValue(UNSPECIFIED)
            self._refresh_pads()
            suggestions = suggest_return_nets(self._names, signal)
            self._suggestion = suggestions[0]['name'] if suggestions else None
            self.use_suggestion.Enable(bool(self._suggestion))
            self.use_suggestion.SetLabel('Use '+self._suggestion if self._suggestion and len(self._suggestion)<24 else 'Use suggested return')
            self.use_suggestion.SetToolTip('Use '+self._suggestion if self._suggestion else 'Choose an actual return net explicitly.')
            self.suggested.SetLabel(('Suggested by name: '+self._suggestion+'. Confirm it is the actual return.')
                                    if self._suggestion else 'No name-based suggestion. Choose the actual return net.')
            self.suggested.Wrap(290); self._summary()
        finally: self._setting = False
        self.Layout(); self._on_layout()

    def _refresh_pads(self):
        selected = set(self.selected_nets())
        counts = {}
        for row in self._terminals:
            if row['net'] in selected: counts[row['label']] = counts.get(row['label'], 0)+1
        display = {}; self._terminal_values = {}
        for row in self._terminals:
            if row['net'] not in selected: continue
            label = row['label']
            text = label if counts[label] == 1 else label+' · '+row['id']
            display[row['id']] = text
            self._terminal_values[text] = label if counts[label] == 1 else row['id']
        for control, endpoint in zip((self.source, self.sink), self._endpoints):
            previous = control.GetValue()
            reference = reference_for_label(self._terminals, endpoint)
            rows = [row for row in self._terminals if row['net'] in selected]
            rows.sort(key=lambda row: (row['reference'] != reference, row['reference'].casefold(), row['label'].casefold(), row['id']))
            choices = [UNSPECIFIED]+[display[row['id']] for row in rows]
            control.Set(choices); control.SetValue(previous if previous in choices else UNSPECIFIED)

    def terminal_value(self, control):
        """Return a unique backend terminal ID; display labels remain readable."""
        value = control.GetValue()
        return None if value == UNSPECIFIED else self._terminal_values.get(value, value)

    def _summary(self):
        selected = self.selected_nets()
        label = selected[0] if len(selected) == 1 else str(len(selected))+' return nets' if selected else ''
        message = ('Checking '+label+'. Return pins are optional.') if selected else 'Return review is off. Choose a return to include the coverage check.'
        self.summary.SetLabel(message); self.summary.Wrap(290)
        self.use_suggestion.Enable(bool(self._suggestion) and selected != [self._suggestion])

    def _primary_changed(self, event=None):
        if self._setting: return
        selected = self.primary.GetValue()
        for index in range(self.nets.GetCount()): self.nets.Check(index, self.nets.GetString(index) == selected)
        self._refresh_pads(); self._summary(); self._on_change()

    def _use_suggested(self, event=None):
        if self._suggestion:
            self.primary.SetValue(self._suggestion); self._primary_changed()

    def _nets_changed(self, event=None):
        if self._setting: return
        selected = self.selected_nets(); current = self.primary.GetValue()
        self.primary.SetValue(current if current in selected else selected[0] if selected else NO_REVIEW)
        self._refresh_pads(); self._summary(); self._on_change()

    def _pad_changed(self, event=None):
        if not self._setting: self._on_change()
