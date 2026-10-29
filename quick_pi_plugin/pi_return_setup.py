"""Guided, explicit return-pad mapping for one rail or a shared DC return."""
from __future__ import annotations

import copy
import wx

from wayricad_runtime.layout import fit_to_display
from wayricad_runtime.readable_choice import ReadableChoice
from wayricad_runtime.searchable_selection import choose_items, searchable_row
from wayricad_runtime.return_setup import suggest_return_nets, return_pad_candidates


def choose_pad_unit(parent, inventory, net, selected=(), *, multiple=True):
    """Search full pad names while retaining checked pads across filters."""
    rows = return_pad_candidates(inventory.get('terminals', []), [net])
    if not rows:
        raise ValueError('No saved-board pads on '+net+'.')
    labels = [str(row.get('label', row['id']))+' · '+net+' · '+str(row['id']) for row in rows]
    indices = [i for i, row in enumerate(rows) if row['id'] in selected or row.get('label') in selected]
    result = choose_items(parent, labels, selection=indices[0] if indices else -1,
                          checked=indices if multiple else None,
                          group_keys=[(r.get('footprint_uuid') or r['id'], net) for r in rows],
                          group_label='Check component / same net')
    if result is None:
        return None
    if not result:
        raise ValueError('Choose at least one physical pad.')
    return [rows[i]['id'] for i in result]


def endpoint_references(inventory, names):
    """Resolve saved endpoint identities to their owning footprint references."""
    refs = set()
    for row in inventory.get('terminals', []):
        if row.get('id') in names or row.get('label') in names:
            refs.add(row.get('reference') or str(row.get('label', '')).rsplit('.', 1)[0])
    return refs


class ReturnSetupDialog(wx.Dialog):
    """One screen for the return domain, source ground and every load ground.

    Existing independent loops retain their model and single-pad endpoints.
    New/shared groups use explicit multi-pad units and preserve unrelated cases.
    """
    def __init__(self, parent, study, inventory, *, group_index=None, case_names=None,
                 independent_case=None):
        super().__init__(parent, title='Quick PI · Set up ground / return copper', size=(970, 730),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((720, 520)); self.inventory = inventory
        self.original = copy.deepcopy(study); self.group_index = group_index
        self.independent_case = independent_case; self.updated = None; self._loading = True
        self.source_pads = []; self.mappings = {}; self.rows = []
        self.old = (self.original['shared_returns'][group_index] if group_index is not None else {})
        cases = self.original['cases']; self.by_name = {c['name']: c for c in cases}
        occupied = {m['case'] for i, group in enumerate(self.original.get('shared_returns', []))
                    if i != group_index for m in group['loads']}
        self.available = [c for c in cases if (c['name'] == independent_case if independent_case else
            c['name'] not in occupied and not any(key in c for key in ('return_conduction', 'electrothermal')) and
            c['electrical'].get('model_dimension', '2.5d') == '2.5d' and
            not c['electrical'].get('package_conduction') and c['electrical'].get('load_resistance_ohm') is None)]
        root = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='1 Choose the rail(s).  2 Confirm the ground / return net.  '
            '3 Select where each load returns and where ground reaches the supply.\n'
            'Suggestions use footprint and net names only. Review every pad unit before Apply.')
        note.Wrap(900); root.Add(note, 0, wx.EXPAND | wx.ALL, 12)
        content = wx.ScrolledWindow(self); content.SetScrollRate(8, 12)
        layout = wx.BoxSizer(wx.VERTICAL)
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.cases = wx.CheckListBox(content, choices=[c['name']+' · '+c['electrical']['net'] for c in self.available],
                                     size=(240, 120), style=wx.LB_HSCROLL)
        top.Add(self.cases, 1, wx.EXPAND | wx.RIGHT, 12)
        fields = wx.FlexGridSizer(cols=2, vgap=8, hgap=8); fields.AddGrowableCol(1)
        self.name = wx.TextCtrl(content, value=self.old.get('name', 'Common ground'))
        self.net = ReadableChoice(content)
        supply_nets = {c['electrical']['net'] for c in cases}
        nets = [n for n in inventory.get('nets', []) if n not in supply_nets]
        suggestions = suggest_return_nets(nets)
        ordered = [r['name'] for r in suggestions]+sorted(set(nets)-{r['name'] for r in suggestions})
        self.net.SetItems(ordered)
        for label, control in [('Return group name', self.name), ('Ground / return net', self.net)]:
            fields.Add(wx.StaticText(content, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            fields.Add(searchable_row(control) if control is self.net else control, 1, wx.EXPAND)
        top.Add(fields, 2, wx.EXPAND); layout.Add(top, 0, wx.EXPAND | wx.BOTTOM, 12)
        self.source_summary = wx.TextCtrl(content, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 48))
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        source_row.Add(wx.StaticText(content, label='Supply ground\n(return reaches here)'), 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 12)
        source_row.Add(self.source_summary, 1, wx.EXPAND)
        self.source_button = wx.Button(content, label='Choose pads…')
        self.source_button.Bind(wx.EVT_BUTTON, self._source)
        source_row.Add(self.source_button, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 8)
        layout.Add(source_row, 0, wx.EXPAND | wx.BOTTOM, 10)
        self.table = wx.ListCtrl(content, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (label, width) in enumerate([('Rail / load', 230), ('Forward pads', 180), ('Load ground / return pads', 300), ('Demand (A)', 105)]):
            self.table.InsertColumn(i, label, width=width)
        self.table.SetMinSize((-1, 200)); self.table.SetToolTip('Select a load row, then Choose load ground pads. Double-click also opens the searchable pad picker.')
        self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._load)
        layout.Add(self.table, 1, wx.EXPAND | wx.BOTTOM, 8)
        buttons = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        self.load_button = wx.Button(content, label='Choose load ground pads…')
        self.load_button.Bind(wx.EVT_BUTTON, self._load)
        self.suggest = wx.Button(content, label='Suggest matching footprint pads')
        self.suggest.Bind(wx.EVT_BUTTON, self._suggest)
        for control in (self.load_button, self.suggest): buttons.Add(control, 0, wx.RIGHT | wx.BOTTOM, 8)
        layout.Add(buttons, 0, wx.EXPAND)
        mode = ('Existing independent loop: one pad per end; its original model and advanced settings are preserved.'
                if independent_case else 'Checked pads in each unit are ideal equipotential contacts. The solver distributes the total unit current; no equal split is assumed.')
        self.mode = wx.StaticText(content, label=mode); self.mode.Wrap(900)
        layout.Add(self.mode, 0, wx.EXPAND | wx.TOP, 8)
        content.SetSizer(layout); root.Add(content, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.status = wx.StaticText(self); self.status.Wrap(900)
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 12)
        actions = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        self.apply = self.FindWindow(wx.ID_OK); self.apply.SetLabel('Apply return setup')
        self.apply.Bind(wx.EVT_BUTTON, self._apply)
        root.Add(actions, 0, wx.EXPAND | wx.ALL, 12); self.SetSizer(root)
        selected = set(case_names or ()) or {m['case'] for m in self.old.get('loads', [])}
        if independent_case: selected = {independent_case}
        if not selected and len(self.available) == 1: selected = {self.available[0]['name']}
        for i, case in enumerate(self.available): self.cases.Check(i, case['name'] in selected)
        if independent_case:
            definition = self.by_name[independent_case]['return_conduction']
            self.net.SetStringSelection(definition['net']); self.source_pads = [definition['sink_terminal']]
            from .service import sink_requests
            for i, sink in enumerate(sink_requests(self.by_name[independent_case]['electrical'])):
                self.mappings[(independent_case, sink.get('id') or 'load-'+str(i+1))] = [definition['source_terminal']]
            self.name.ChangeValue(independent_case+' ground'); self.name.Disable(); self.cases.Disable()
        elif self.old:
            self.net.SetStringSelection(self.old['net']); self.source_pads = list(self.old['source_terminals'])
            self.mappings = {(m['case'], m['sink']): list(m['terminals']) for m in self.old['loads']}
        elif ordered:
            self.net.SetSelection(0)
        self._loading = False
        self.cases.Bind(wx.EVT_CHECKLISTBOX, self._cases_changed)
        self.net.Bind(wx.EVT_CHOICE, self._net_changed)
        self._rebuild(); fit_to_display(self)

    def set_status(self, message):
        self.status.SetLabel(message)
        self.status.Wrap(max(300, self.GetClientSize().width-40))
        self.Layout()

    def _selected(self):
        return [case for i, case in enumerate(self.available) if self.cases.IsChecked(i)]

    def _labels(self, names):
        labels = {t['id']: t.get('label', t['id']) for t in self.inventory.get('terminals', [])}
        return ', '.join(labels.get(n, n) for n in names) or 'Not selected'

    def _rebuild(self):
        from .service import sink_requests
        from .terminals import pad_names
        selected = self._selected(); self.rows = []; self.table.DeleteAllItems()
        for case in selected:
            for i, sink in enumerate(sink_requests(case['electrical'])):
                identity = sink.get('id') or 'load-'+str(i+1); key = (case['name'], identity)
                self.rows.append((key, sink))
                row = self.table.InsertItem(self.table.GetItemCount(), case['name']+' / '+identity)
                self.table.SetItem(row, 1, self._labels(pad_names(sink)))
                self.table.SetItem(row, 2, self._labels(self.mappings.get(key, [])))
                self.table.SetItem(row, 3, format(sink['current_A'], '.7g'))
        self.source_summary.ChangeValue(self._labels(self.source_pads))
        if self.rows: self.table.Select(0)
        missing = sum(not self.mappings.get(key) for key, _ in self.rows)+(not self.source_pads)
        self.set_status((str(missing)+' return pad unit(s) still need selection. ' if missing else 'All return pad units selected. ')+
            'Confirm the actual ground domain and review the mappings, then Apply. Shared return contacts combine load currents; contacts at supply ground have zero return drop.')
        self.apply.Enable(bool(selected) and bool(self.net.GetStringSelection()))
        self.source_button.Enable(bool(self.net.GetStringSelection())); self.load_button.Enable(bool(self.rows))

    def _cases_changed(self, event=None):
        self._rebuild()

    def _net_changed(self, event=None):
        self.source_pads = []; self.mappings.clear(); self._rebuild()
        self.set_status('Return net changed. Old pad mappings were cleared; choose or suggest pads on this net.')

    def _source(self, event=None):
        try:
            values = choose_pad_unit(self, self.inventory, self.net.GetStringSelection(), self.source_pads,
                                     multiple=not bool(self.independent_case))
            if values is not None: self.source_pads = values; self._rebuild()
        except ValueError as exc: self.set_status(str(exc))

    def _load(self, event=None):
        index = self.table.GetFirstSelected()
        if not 0 <= index < len(self.rows): return
        key, _ = self.rows[index]
        try:
            values = choose_pad_unit(self, self.inventory, self.net.GetStringSelection(), self.mappings.get(key, []),
                                     multiple=not bool(self.independent_case))
            if values is not None:
                self.mappings[key] = values; self._rebuild(); self.table.Select(index)
        except ValueError as exc: self.set_status(str(exc))

    def _suggest(self, event=None):
        from .terminals import source_names, pad_names
        net = self.net.GetStringSelection()
        if not net: return
        def candidates(names):
            refs = endpoint_references(self.inventory, names)
            return [r['id'] for ref in sorted(refs) for r in return_pad_candidates(
                self.inventory.get('terminals', []), [net], ref)]
        chosen = list(dict.fromkeys(p for c in self._selected() for p in candidates(source_names(c['electrical']))))
        if chosen and (not self.independent_case or len(chosen) == 1): self.source_pads = chosen
        for key, sink in self.rows:
            chosen = candidates(pad_names(sink))
            if chosen and (not self.independent_case or len(chosen) == 1): self.mappings[key] = chosen
        self._rebuild(); self.set_status('Suggested by the owning footprints only. Review all rows; missing or ambiguous units still need manual selection. Apply explicitly confirms the mappings.')

    def build_study(self):
        """Return a validated copy; cancel and validation errors leave input untouched."""
        from .batch import validate_study
        from .service import sink_requests
        selected = self._selected(); net = self.net.GetStringSelection()
        if not selected or not net or not self.source_pads:
            raise ValueError('Choose rail(s), the return net and the supply-ground pad unit.')
        result = copy.deepcopy(self.original); by_name = {c['name']: c for c in result['cases']}
        choices = return_pad_candidates(self.inventory.get('terminals', []), [net])
        def canonical(names):
            selected = []
            for name in names:
                matches = [r for r in choices if r['id'] == name or r.get('label') == name]
                if len(matches) != 1:
                    raise ValueError('Select an unambiguous physical pad on the current return net: '+name)
                selected.append(matches[0]['id'])
            if len(selected) != len(set(selected)):
                raise ValueError('The same physical pad is repeated in one return unit.')
            return selected
        source_pads = canonical(self.source_pads)
        mappings = []
        for selected_case in selected:
            case = by_name[selected_case['name']]; sinks = sink_requests(case['electrical'])
            for i, sink in enumerate(sinks):
                identity = sink.get('id') or 'load-'+str(i+1); key = (case['name'], identity)
                pads = canonical(self.mappings.get(key, []))
                if not pads: raise ValueError('Choose load-ground pads for '+case['name']+' / '+identity+'.')
                if self.independent_case:
                    if len(pads) != 1 or len(source_pads) != 1:
                        raise ValueError('An existing independent loop requires one pad at each end.')
                    definition = {**case['return_conduction'], 'net': net,
                                  'source_terminal': pads[0], 'sink_terminal': source_pads[0]}
                    from .power_loop import return_request
                    return_request(case['electrical'], definition); case['return_conduction'] = definition
                else:
                    sink['id'] = identity
                    mappings.append({'case': case['name'], 'sink': identity, 'terminals': list(pads)})
            if not self.independent_case:
                for key in ('sink_terminal', 'sink_current', 'sink_min_voltage', 'sink_max_voltage'):
                    case['electrical'].pop(key, None)
                case['electrical']['sinks'] = sinks
        if not self.independent_case:
            group = {**self.old, 'name': self.name.GetValue().strip(), 'net': net,
                     'source_terminals': source_pads, 'loads': mappings}
            groups = result.setdefault('shared_returns', [])
            if self.group_index is None: groups.append(group)
            else: groups[self.group_index] = group
        return validate_study(result)

    def _apply(self, event=None):
        try: self.updated = self.build_study()
        except (ValueError, TypeError) as exc: self.set_status(str(exc)); return
        self.EndModal(wx.ID_OK)
