"""Reviewed IBIS endpoint controls for KiCad circuit export.

Selection is bound to a net and exact PCB Reference.Pad. Loading parses on a
worker; changing a model never claims to recompute Quick SI's ideal eye.
"""
from __future__ import annotations

import threading
import math
from pathlib import Path

import wx
from wayricad_runtime.readable_choice import ReadableComboBox

from .ibis_models import assignment_from_catalog, load_ibis


def model_choices(catalog, component, pin, role):
    """Return only exact pin models whose declared role is usable."""
    info = catalog.get('components', {}).get(component, {}).get('pins', {}).get(pin)
    if not info:
        return []
    name = info['model_name']
    names = catalog.get('selectors', {}).get(name, {}).get('models', [name])
    return [candidate for candidate in names
            if role in catalog.get('models', {}).get(candidate, {}).get('roles', [])]


def context_key(net, role, pad):
    if role not in ('source', 'sink') or not net or not pad or '.' not in pad:
        return None
    return net, role, pad


class IbisPane(wx.Panel):
    """Two independently reviewed endpoint assignments with a catalog cache."""

    def __init__(self, parent, changed):
        super().__init__(parent)
        self._changed = changed
        self._closed = False
        self._context = ('', '', '')
        self._assignments = {}
        self._blocked_keys = set()
        self._catalogs = {}
        self._current = {'source': None, 'sink': None}
        self._serial = {'source': 0, 'sink': 0}
        self._controls = {}
        layout = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='IBIS models are used only by KiCad circuit export. The existing eye plot remains an illustrative ideal-source screen.')
        note.Wrap(290)
        layout.Add(note, 0, wx.EXPAND | wx.ALL, 5)
        for role, title in (('source', 'Source / driver'), ('sink', 'Receiver / load')):
            box = wx.StaticBoxSizer(wx.VERTICAL, self, title)
            box_parent = box.GetStaticBox()
            bar = wx.BoxSizer(wx.HORIZONTAL)
            load = wx.Button(box_parent, label='Load IBIS…')
            load.Bind(wx.EVT_BUTTON, lambda event, r=role: self.load_file(r))
            bar.Add(load, 0, wx.RIGHT, 5)
            use_source = None
            if role == 'sink':
                use_source = wx.Button(box_parent, label='Use source file for receiver')
                use_source.Bind(wx.EVT_BUTTON, self.use_source_file)
                bar.Add(use_source, 0)
            box.Add(bar, 0, wx.EXPAND | wx.ALL, 4)
            filename = wx.StaticText(box_parent, label='No IBIS file selected')
            box.Add(filename, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
            endpoint = wx.StaticText(box_parent, label='No PCB pad selected')
            box.Add(endpoint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
            selectors = {}
            for key, caption in (('component', 'Component'), ('pin', 'Pin'),
                                 ('model', 'Model'), ('corner', 'Corner')):
                box.Add(wx.StaticText(box_parent, label=caption), 0, wx.LEFT | wx.TOP, 4)
                control = ReadableComboBox(box_parent, choices=['typ', 'min', 'max'] if key == 'corner' else [],style=wx.CB_READONLY)
                if key == 'pin':control.SetToolTip('Exact PCB pad-number matches are suggested; choose another IBIS pin explicitly when appropriate.')
                if key == 'model':control.SetToolTip('Only models declared for this endpoint role are listed. Choose when several remain.')
                if key == 'corner':control.SetToolTip('One typ/min/max corner is applied to VCC and pin R/L/C.')
                if key == 'corner':
                    control.SetSelection(0)
                control.Bind(wx.EVT_COMBOBOX, lambda event, r=role, k=key: self._selection_changed(r, k))
                box.Add(control, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
                selectors[key] = control
            layout.Add(box, 0, wx.EXPAND | wx.TOP, 6)
            self._controls[role] = {'load': load, 'use_source': use_source,
                                    'filename': filename, 'endpoint': endpoint,
                                    **selectors}
        self.SetSizer(layout)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._destroyed)

    def _destroyed(self, event):
        if event.GetEventObject() is self:
            self._closed = True
            for role in self._serial:
                self._serial[role] += 1
        event.Skip()

    def _key(self, role):
        net, source, sink = self._context
        return context_key(net, role, source if role == 'source' else sink)

    def set_context(self, net, source, sink):
        context = str(net or ''), str(source or ''), str(sink or '')
        if context != self._context:
            self._context = context
            for role in self._serial:
                self._serial[role] += 1  # A pending load must not apply to another pad.
                self._controls[role]['load'].Enable()
        for role in ('source', 'sink'):
            self._show_role(role)

    def _selected(self, role, field):
        control = self._controls[role][field]
        return control.GetStringSelection() if control.GetSelection() != wx.NOT_FOUND else ''

    def _choose(self, control, names, preferred=''):
        control.Set(list(names))
        choice = preferred if preferred in names else (names[0] if len(names) == 1 else '')
        control.SetStringSelection(choice) if choice else control.SetSelection(wx.NOT_FOUND)
        control.SetToolTip(choice or 'Choose an exact catalog entry')
        return choice

    def _show_role(self, role):
        controls = self._controls[role]
        key = self._key(role)
        controls['endpoint'].SetLabel((key[2]+' — reselect model: file changed') if key in self._blocked_keys else key[2] if key else 'Choose an exact PCB pad')
        controls['endpoint'].SetToolTip('The selected PCB endpoint and explicit IBIS component/pin mapping.')
        saved = self._assignments.get(key)
        catalog = self._catalogs.get(saved['path']) if saved else self._current[role]
        if catalog:
            self._current[role] = catalog
            path = catalog['path']
            controls['filename'].SetLabel(Path(path).name)
            controls['filename'].SetToolTip(path)
        else:
            controls['filename'].SetLabel('No IBIS file selected')
            controls['filename'].SetToolTip('Load a local .ibs file')
        controls['use_source'].Enable(self._current['source'] is not None) if controls['use_source'] else None
        component = self._choose(controls['component'], sorted(catalog['components']) if catalog else [],
                                 saved['component'] if saved else '')
        self._show_pin_model(role, component, saved)
        corner = saved['corners']['vcc'] if saved else 'typ'
        controls['corner'].SetStringSelection(corner)
        self._capture(role, notify=False)

    def _show_pin_model(self, role, component, saved=None):
        controls = self._controls[role]
        catalog = self._current[role]
        pins = sorted(catalog['components'][component]['pins']) if catalog and component else []
        key = self._key(role)
        exact = key[2].split('.', 1)[1] if key else ''
        # Prefer an exact number match; a different pin requires explicit choice.
        controls['pin'].Set(pins)
        pin = saved['pin'] if saved and saved['pin'] in pins else exact if exact in pins else ''
        controls['pin'].SetStringSelection(pin) if pin else controls['pin'].SetSelection(wx.NOT_FOUND)
        controls['pin'].SetToolTip(pin or 'Choose the IBIS pin for this PCB endpoint explicitly')
        models = model_choices(catalog, component, pin, role) if catalog and pin else []
        self._choose(controls['model'], models, saved['model'] if saved else '')

    def _selection_changed(self, role, field):
        self._blocked_keys.discard(self._key(role))
        if field in ('component','pin','model'):
            value=self._selected(role,field)
            self._controls[role][field].SetToolTip(value or 'Choose an exact catalog entry')
        if field == 'component':
            self._show_pin_model(role, self._selected(role, 'component'))
        elif field == 'pin':
            component = self._selected(role, 'component')
            pin = self._selected(role, 'pin')
            catalog = self._current[role]
            self._choose(self._controls[role]['model'], model_choices(catalog, component, pin, role) if catalog else [])
        self._capture(role)

    def _capture(self, role, notify=True):
        key = self._key(role)
        before = self._assignments.get(key)
        assignment = None
        catalog = self._current[role]
        if key and catalog:
            component = self._selected(role, 'component')
            pin = self._selected(role, 'pin')
            model = self._selected(role, 'model')
            corner = self._selected(role, 'corner')
            if key not in self._blocked_keys and component and pin and model and corner:
                try:
                    assignment = assignment_from_catalog(catalog, component, pin, model, role, corner)
                except ValueError:
                    pass
            if key not in self._blocked_keys:
                mapping=key[2]+' → '+component+'.'+pin if assignment else key[2]+' → choose IBIS component / pin / model'
                self._controls[role]['endpoint'].SetLabel(mapping)
                self._controls[role]['endpoint'].SetToolTip(mapping)
                self._controls[role]['endpoint'].Wrap(290)
        if key:
            if assignment:
                self._assignments[key] = assignment
            else:
                self._assignments.pop(key, None)
        if notify and before != assignment:
            self._changed()

    def assignment(self, net, role, pad):
        value = self._assignments.get(context_key(net, role, pad))
        return dict(value) if value else None

    def load_file(self, role):
        if self._closed:
            return
        with wx.FileDialog(self, f'Load {role} IBIS file', wildcard='IBIS models (*.ibs)|*.ibs',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        serial = self._serial[role] = self._serial[role] + 1
        context = self._context
        self._controls[role]['load'].Disable()

        def worker():
            try:
                catalog, error = load_ibis(path), None
            except Exception as caught:
                catalog, error = None, caught
            try:
                wx.CallAfter(self._loaded, role, serial, context, catalog, error)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True, name='Quick SI IBIS catalog').start()

    def _loaded(self, role, serial, context, catalog, error):
        if self._closed or serial != self._serial[role]:
            return
        self._controls[role]['load'].Enable()
        if context != self._context:
            return
        if error:
            wx.MessageBox(str(error), 'IBIS load failed', wx.OK | wx.ICON_ERROR, self)
            return
        old=self._catalogs.get(catalog['path'])
        if old and old['sha256']!=catalog['sha256']:
            for key,assignment in tuple(self._assignments.items()):
                if assignment['path']==catalog['path']:
                    self._assignments.pop(key)
                    self._blocked_keys.add(key)
        self._catalogs[catalog['path']] = catalog
        self._current[role] = catalog
        key = self._key(role)
        if key:
            self._assignments.pop(key, None)
        self._show_role(role)
        self._changed()

    def use_source_file(self, event=None):
        catalog = self._current['source']
        if not catalog:
            return
        self._serial['sink'] += 1
        self._current['sink'] = catalog
        key = self._key('sink')
        if key:
            self._assignments.pop(key, None)
        self._show_role('sink')
        self._changed()


def circuit_options_dialog(parent, reports=()):
    """Collect explicit simulation settings; None means the user cancelled."""
    dialog = wx.Dialog(parent, title='KiCad circuit export settings',
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    note = wx.StaticText(dialog, label='Export the reviewed IBIS endpoints and routed line sections. Enter copper thickness only when no saved value exists. Manual via L/C is an approximation and requires the explicit checkbox.')
    note.Wrap(460)
    layout.Add(note, 0, wx.EXPAND | wx.ALL, 10)
    grid = wx.FlexGridSizer(0, 2, 6, 8)
    grid.AddGrowableCol(1)
    entries = {}
    for key, label, default in (
        ('duration_ns', 'Duration (ns)', '100'),
        ('timestep_ns', 'Maximum timestep (ns)', '0.1'),
        ('frequency_mhz', 'Stimulus frequency (MHz)', '100'),
        ('duty_percent', 'Duty cycle (%)', '50'),
        ('copper_thickness_um', 'Assumed copper thickness µm (if not saved)', ''),
        ('via_capacitance_pf', 'Manual via capacitance (pF)', ''),
        ('via_inductance_nh', 'Manual via inductance (nH)', ''),
    ):
        grid.Add(wx.StaticText(dialog, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        control = wx.TextCtrl(dialog, value=default)
        grid.Add(control, 1, wx.EXPAND)
        entries[key] = control
    layout.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    from .setup_guide import circuit_timing_suggestion
    suggestion = wx.Button(dialog, label='Suggest timing from selected routes')
    timing_note = wx.StaticText(dialog, label='Timing remains editable. Check convergence in KiCad/ngspice; IBIS edge bandwidth is not inferred.')
    timing_note.Wrap(460)
    def suggest_timing(event):
        try:
            advice = circuit_timing_suggestion(reports)
            for key in ('duration_ns', 'timestep_ns', 'frequency_mhz'):
                entries[key].SetValue(f'{advice[key]:.9g}')
            timing_note.SetLabel(f"Duration / maximum-step ratio: {advice['estimated_points']:,}. Adaptive internal steps can be smaller. Review against the actual IBIS models.")
        except ValueError as error:timing_note.SetLabel(str(error))
        timing_note.Wrap(460); dialog.Layout()
    suggestion.Enable(bool(reports)); suggestion.Bind(wx.EVT_BUTTON, suggest_timing)
    layout.Add(suggestion, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
    layout.Add(timing_note, 0, wx.EXPAND | wx.ALL, 10)
    allow = wx.CheckBox(dialog, label='Allow explicit manual via approximation')
    layout.Add(allow, 0, wx.EXPAND | wx.ALL, 10)
    for key in ('via_capacitance_pf', 'via_inductance_nh'):
        entries[key].Enable(False)
    allow.Bind(wx.EVT_CHECKBOX, lambda event: [entries[key].Enable(allow.GetValue())
                                               for key in ('via_capacitance_pf', 'via_inductance_nh')])
    layout.Add(dialog.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
    dialog.SetSizerAndFit(layout)
    try:
        while dialog.ShowModal() == wx.ID_OK:
            try:
                options = {key: float(entries[key].GetValue()) for key in
                           ('duration_ns', 'timestep_ns', 'frequency_mhz', 'duty_percent')}
                options['allow_approximations'] = allow.GetValue()
                raw_copper=entries['copper_thickness_um'].GetValue().strip()
                options['copper_thickness_um']=float(raw_copper) if raw_copper else None
                for key in ('via_capacitance_pf', 'via_inductance_nh'):
                    raw = entries[key].GetValue().strip() if allow.GetValue() else ''
                    options[key] = float(raw) if raw else None
                if any(not math.isfinite(value) for value in options.values() if isinstance(value,(int,float))):
                    raise ValueError('Circuit settings must be finite numbers.')
                if options['duration_ns'] <= 0 or options['timestep_ns'] <= 0 or options['frequency_mhz'] <= 0 or not 0 < options['duty_percent'] < 100:
                    raise ValueError('Duration, timestep and frequency must be positive; duty cycle must be between 0 and 100%.')
                if any(options[key] is not None and options[key] < 0 for key in ('via_capacitance_pf', 'via_inductance_nh')):
                    raise ValueError('Manual via L/C values must be nonnegative.')
                if options['copper_thickness_um'] is not None and options['copper_thickness_um'] <= 0:
                    raise ValueError('Assumed copper thickness must be positive.')
                return options
            except ValueError as error:
                wx.MessageBox(str(error), 'Invalid circuit settings', wx.OK | wx.ICON_ERROR, dialog)
        return None
    finally:
        dialog.Destroy()
