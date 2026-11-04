"""Review inferred topology, then use the established series-path contract."""
from __future__ import annotations

from copy import deepcopy


def reviewed_path(proposal, route_index, selections, inventory):
    """Convert reviewed stage selections and models into a normal saved path."""
    from .series_editor import parse_saved_path
    route = proposal['routes'][route_index]
    if len(selections) != len(route['stages']):
        raise ValueError('Review every stage in the route.')
    branches = []
    for stage, chosen in zip(route['stages'], selections):
        available = {part['footprint_uuid']: part for part in stage['parts']}
        if not chosen:
            raise ValueError('Select at least one component in every stage.')
        if len(chosen)>65:
            raise ValueError('A stage supports one primary and at most 64 parallel components.')
        parts = []
        used = set()
        for item in chosen:
            owner = item.get('footprint_uuid')
            if owner not in available or owner in used:
                raise ValueError('Choose each discovered component once.')
            used.add(owner)
            found = available[owner]
            groups = {}
            for key in ('from_pads', 'to_pads'):
                selected = item.get(key, found[key])
                if not selected or len(set(selected)) != len(selected) or set(selected) - set(found[key]):
                    raise ValueError('Review incoming and outgoing pins on the selected net pair.')
                groups[key] = list(selected)
            model = str(item.get('model', '')).strip()
            if not model:
                raise ValueError('Enter a resistance, R/L or forward-drop model for ' + found['reference'] + '.')
            parts.append(dict(footprint_uuid=owner, reference=found['reference'], model=model,
                              from_pad=groups['from_pads'][0], to_pad=groups['to_pads'][0], **groups))
        primary = parts[0]
        branch = {key: value for key, value in primary.items() if key != 'footprint_uuid'}
        if len(parts) > 1:
            branch['parallel'] = [{key: value for key, value in part.items() if key != 'reference'} for part in parts[1:]]
        branches.append(branch)
    path = dict(schema=1, source=proposal['source'], sink=proposal['sink'], branches=branches,
                source_terminals=deepcopy(proposal['source_terminals']),
                sink_terminals=deepcopy(proposal['sink_terminals']))
    parse_saved_path(path, inventory)
    return path


class InlineInference:
    """Review inferred candidates in an existing editor, without opening dialogs.

    Drafts are scoped to the endpoint query, route and exact saved pad groups.
    Snapshots contain review inputs only; restore always discovers routes again.
    Importing this module does not require the native wx runtime.
    """

    def __init__(self, parent, inventory, on_use):
        import wx
        from .console import terminal_aliases
        self.wx, self.inventory, self.on_use = wx, inventory, on_use
        self.aliases = terminal_aliases(inventory)
        self.proposal, self.query = None, None
        self.controls, self.drafts = [], {}
        self._shown_route = None
        self.panel = wx.Panel(parent)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.note = wx.StaticText(self.panel, label='')
        layout.Add(self.note, 0, wx.EXPAND | wx.BOTTOM, 6)
        self.routes = wx.Choice(self.panel)
        layout.Add(self.routes, 0, wx.EXPAND | wx.BOTTOM, 6)
        # The containing editor owns scrolling so every bank remains in its flow.
        self.area = wx.Panel(self.panel)
        self.stack = wx.BoxSizer(wx.VERTICAL)
        self.area.SetSizer(self.stack)
        layout.Add(self.area, 0, wx.EXPAND)
        self.omitted = wx.StaticText(self.panel, label='')
        layout.Add(self.omitted, 0, wx.EXPAND | wx.BOTTOM, 6)
        self.status = wx.StaticText(self.panel, label='')
        layout.Add(self.status, 0, wx.EXPAND | wx.BOTTOM, 6)
        self.accept = wx.Button(self.panel, label='Use reviewed path')
        layout.Add(self.accept, 0, wx.BOTTOM, 6)
        self.panel.SetSizer(layout)
        self.routes.Bind(wx.EVT_CHOICE, self._populate)
        self.accept.Bind(wx.EVT_BUTTON, self._use)
        self.invalidate()

    @staticmethod
    def _part_key(part):
        return (part['footprint_uuid'], tuple(part['from_pads']), tuple(part['to_pads']))

    def _layout(self):
        self.note.Wrap(820)
        self.omitted.Wrap(820)
        self.status.Wrap(820)
        window = self.panel
        while window is not None:
            window.Layout()
            if isinstance(window, self.wx.ScrolledWindow):
                window.FitInside()
            window = window.GetParent()

    def _error(self, message):
        self.status.SetLabel(str(message))
        self._layout()

    def invalidate(self):
        """Discard all drafts when the endpoint query or device policy changes."""
        self.proposal, self.query, self._shown_route = None, None, None
        self.controls.clear()
        self.drafts.clear()
        self.routes.Clear()
        self.routes.Disable()
        self.accept.Disable()
        self.stack.Clear(True)
        self.note.SetLabel('Choose source and sink pads, then infer routes for review.')
        self.omitted.SetLabel('')
        self.status.SetLabel('')
        self._layout()

    def infer(self, source, sink, include_unknown=False, *, existing=None):
        """Populate current saved-board candidates; return success, errors inline."""
        from wayricad_runtime.series_topology import infer_series_paths
        query = dict(source=source, sink=sink, include_unknown=bool(include_unknown))
        previous = self.snapshot() if query == self.query else None
        self.invalidate()
        self.query = query
        try:
            proposal = infer_series_paths(self.inventory, source, sink,
                                          include_unknown=bool(include_unknown))
            if not proposal['routes']:
                raise ValueError('No candidate series route found. Review the endpoints and device classes, or add explicit pad pairs for other devices.')
            if not proposal['routes'][0]['stages']:
                raise ValueError('The endpoints share a saved net. Use the normal single-net setup; no series component is needed.')
        except ValueError as exc:
            self._error(exc)
            return False
        self.proposal = proposal
        self.note.SetLabel(proposal['notice'] +
            (' Search limit reached; additional routes may exist.' if proposal['truncated'] else ''))
        self.routes.SetItems([' → '.join(route['nets']) for route in proposal['routes']])
        self.routes.SetSelection(0)
        self.routes.Enable()
        self.accept.Enable()
        omitted = ', '.join(proposal['omitted_references'])
        self.omitted.SetLabel('Not traversed automatically: ' + omitted +
            '. Use explicit pad pairs for other device types.' if omitted else '')
        if previous:
            self._restore_drafts(previous)
        self._populate()
        if existing is not None:
            try:
                self.seed_path(existing)
            except ValueError as exc:
                self.invalidate()
                self._error(exc)
                return False
        return True

    def _remember(self):
        if self._shown_route is None:
            return
        self.drafts[self._shown_route] = [[dict(
            footprint_uuid=part['footprint_uuid'], available_from=list(part['from_pads']),
            available_to=list(part['to_pads']), included=check.GetValue(), model=text.GetValue(),
            from_pads=[p for p, c in incoming if c.GetValue()],
            to_pads=[p for p, c in outgoing if c.GetValue()])
            for part, check, text, incoming, outgoing in stage] for stage in self.controls]

    def _populate(self, event=None):
        from .parallel_parts import suggested_resistance
        wx = self.wx
        self._remember()
        self.controls.clear()
        self.stack.Clear(True)
        index = self.routes.GetSelection()
        if self.proposal is None or index < 0:
            return
        route = self.proposal['routes'][index]
        key = tuple(route['nets'])
        saved = self.drafts.get(key, [])
        for number, stage in enumerate(route['stages'], 1):
            self.stack.Add(wx.StaticText(self.area, label=
                f"Stage {number}: {stage['from_net']} → {stage['to_net']} · {len(stage['parts'])} component(s)"),
                0, wx.TOP | wx.BOTTOM, 8)
            previous = {self._part_key(dict(footprint_uuid=p['footprint_uuid'],
                from_pads=p['available_from'], to_pads=p['available_to'])): p
                for p in saved[number - 1]} if len(saved) >= number else {}
            bank = []
            for part in stage['parts']:
                default = suggested_resistance(dict(id=part['reference'], component_value=part['component_value']))
                draft = previous.get(self._part_key(part), {})
                model = draft.get('model', default)
                panel = wx.Panel(self.area)
                box = wx.BoxSizer(wx.VERTICAL)
                label = part['reference'] + ' · ' + part['component_value']
                if len(stage['parts']) > 1:
                    label += ' (parallel bank)'
                check = wx.CheckBox(panel, label=label)
                check.SetValue(draft.get('included', True))
                box.Add(check, 0, wx.BOTTOM, 4)
                pins = []
                for label, field in (('Incoming current pins', 'from_pads'), ('Outgoing current pins', 'to_pads')):
                    line = wx.WrapSizer(wx.HORIZONTAL)
                    line.Add(wx.StaticText(panel, label=label + ': '), 0, wx.ALIGN_CENTER_VERTICAL)
                    selected = draft.get(field, part[field])
                    group = []
                    for identifier in part[field]:
                        control = wx.CheckBox(panel, label=self.aliases.get(identifier, identifier))
                        control.SetValue(identifier in selected)
                        line.Add(control, 0, wx.RIGHT, 8)
                        group.append((identifier, control))
                    pins.append(group)
                    box.Add(line, 0, wx.EXPAND | wx.BOTTOM, 4)
                excluded = ', '.join(self.aliases.get(p, p) for p in part['excluded_pads']) or 'None'
                excluded_note = wx.StaticText(panel, label='Excluded pins: ' + excluded)
                excluded_note.Wrap(780)
                box.Add(excluded_note, 0, wx.EXPAND | wx.BOTTOM, 4)
                model_row = wx.BoxSizer(wx.HORIZONTAL)
                model_row.Add(wx.StaticText(panel, label='Model: '), 0, wx.ALIGN_CENTER_VERTICAL)
                text = wx.TextCtrl(panel, value=model)
                text.SetHint('100mΩ, 5mΩ+10nH, 0.7V or diode(Vf=0.7V,Iref=1A,n=2,T=25C)')
                model_row.Add(text, 1, wx.EXPAND)
                box.Add(model_row, 0, wx.EXPAND)
                if default:
                    box.Add(wx.StaticText(panel, label='Resistance suggested from component value; review before use.'),
                            0, wx.TOP, 4)
                panel.SetSizer(box)
                self.stack.Add(panel, 0, wx.EXPAND | wx.LEFT | wx.BOTTOM, 12)
                bank.append((part, check, text, *pins))
            self.controls.append(bank)
        self._shown_route = key
        self.status.SetLabel('')
        self._layout()

    def reviewed_path(self):
        """Validate the visible review against the established saved-path parser."""
        try:
            if self.proposal is None:
                raise ValueError('Infer routes for the current source and sink first.')
            selections = [[dict(footprint_uuid=p['footprint_uuid'], model=text.GetValue(),
                from_pads=[identifier for identifier, c in incoming if c.GetValue()],
                to_pads=[identifier for identifier, c in outgoing if c.GetValue()])
                for p, check, text, incoming, outgoing in stage if check.GetValue()]
                for stage in self.controls]
            result = reviewed_path(self.proposal, self.routes.GetSelection(), selections, self.inventory)
        except ValueError as exc:
            self._error(exc)
            raise
        self.status.SetLabel('')
        return result

    def _use(self, event=None):
        try:
            path = self.reviewed_path()
        except ValueError:
            return
        self.on_use(path)

    def snapshot(self):
        """Return JSON-compatible review drafts, including unselected candidates."""
        self._remember()
        return dict(schema=1, query=deepcopy(self.query),
                    selected_route=list(self._shown_route) if self._shown_route else None,
                    endpoint_groups={key: deepcopy(self.proposal[key]) for key in
                                     ('source_terminals', 'sink_terminals')} if self.proposal else {},
                    routes=[dict(nets=list(nets), stages=deepcopy(stages))
                            for nets, stages in self.drafts.items()])

    def _restore_drafts(self, snapshot):
        # Never trust saved route contents as topology. Match exact current pads.
        records = snapshot.get('routes', [])
        saved = {tuple(row['nets']): row for row in records
                 if isinstance(row, dict) and isinstance(row.get('nets'), list)
                 and all(isinstance(net, str) for net in row['nets'])} if isinstance(records, list) else {}
        for route in self.proposal['routes']:
            key = tuple(route['nets'])
            candidate = saved.get(key, {})
            stages = candidate.get('stages', [])
            if not isinstance(stages, list) or len(stages) != len(route['stages']):
                continue
            restored = []
            for stage, records in zip(route['stages'], stages):
                bank = []
                if not isinstance(records, list):
                    records = []
                for part in stage['parts']:
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        if (record.get('footprint_uuid') != part['footprint_uuid'] or
                            record.get('available_from') != part['from_pads'] or
                            record.get('available_to') != part['to_pads']):
                            continue
                        if (not isinstance(record.get('model'), str) or
                            not isinstance(record.get('included'), bool) or
                            any(not isinstance(record.get(field), list) or
                                any(p not in part[field] for p in record[field])
                                for field in ('from_pads', 'to_pads'))):
                            continue
                        bank.append(deepcopy(record))
                        break
                restored.append(bank)
            self.drafts[key] = restored
        selected = snapshot.get('selected_route')
        for index, route in enumerate(self.proposal['routes']):
            if route['nets'] == selected:
                self.routes.SetSelection(index)
                break
        groups = snapshot.get('endpoint_groups', {})
        if isinstance(groups, dict):
            for field, anchor in (('source_terminals', 'source'), ('sink_terminals', 'sink')):
                selected = groups.get(field)
                if (isinstance(selected, list) and self.proposal[anchor] in selected and
                    all(isinstance(p, str) and p in self.proposal[field] for p in selected) and
                    len(set(selected)) == len(selected)):
                    self.proposal[field] = list(selected)

    def seed_path(self, path):
        """Edit a validated existing path using matching discovered current pins.

        Unselected members of each discovered bank remain visible and unchecked.
        A path outside the discovered candidates raises instead of substituting a route.
        """
        from .series_editor import parse_saved_path
        if self.proposal is None:
            raise ValueError('Infer routes before restoring a reviewed path.')
        parsed = parse_saved_path(path, self.inventory)
        if (parsed['source_terminal'] != self.proposal['source'] or
            parsed['sink_terminal'] != self.proposal['sink']):
            raise ValueError('The reviewed path has different source or sink pads.')
        for index, route in enumerate(self.proposal['routes']):
            if len(route['stages']) != len(parsed['series']):
                continue
            restored = []
            for stage, solved, branch in zip(route['stages'], parsed['series'], path['branches']):
                models = [branch, *branch.get('parallel', [])]
                configured = [solved, *solved.get('parallel', [])]
                remaining = list(zip(configured, models))
                bank = []
                for part in stage['parts']:
                    match = next(((solved_part, model) for solved_part, model in remaining
                        if solved_part['id'] == part['reference'] and
                        solved_part['from_pad'] in part['from_pads'] and
                        solved_part['to_pad'] in part['to_pads'] and
                        all(p in part['from_pads'] for p in solved_part.get('from_pads', [])) and
                        all(p in part['to_pads'] for p in solved_part.get('to_pads', []))), None)
                    record = dict(footprint_uuid=part['footprint_uuid'],
                        available_from=list(part['from_pads']), available_to=list(part['to_pads']),
                        included=match is not None, model='', from_pads=list(part['from_pads']),
                        to_pads=list(part['to_pads']))
                    if match:
                        chosen, model = match
                        record.update(model=model['model'],
                            from_pads=list(chosen.get('from_pads', [chosen['from_pad']])),
                            to_pads=list(chosen.get('to_pads', [chosen['to_pad']])))
                        remaining.remove(match)
                    bank.append(record)
                if remaining:
                    break
                restored.append(bank)
            if len(restored) != len(route['stages']):
                continue
            self._shown_route = None
            self.drafts[tuple(route['nets'])] = restored
            self.routes.SetSelection(index)
            for field, anchor in (('source_terminals', 'source_terminal'), ('sink_terminals', 'sink_terminal')):
                self.proposal[field] = list(parsed.get(field, [parsed[anchor]]))
            self._populate()
            return True
        raise ValueError('The reviewed path does not match a discovered route. Continue with the explicit path editor.')

    def restore(self, snapshot):
        """Recompute a saved query against this inventory, then restore matching drafts."""
        self.invalidate()
        if not isinstance(snapshot, dict) or snapshot.get('schema') != 1:
            return False
        query = snapshot.get('query')
        if not isinstance(query, dict) or not all(isinstance(query.get(k), str) for k in ('source', 'sink')):
            return False
        if not self.infer(query['source'], query['sink'], bool(query.get('include_unknown', False))):
            return False
        # infer populated controls; discard those before applying stored drafts.
        self._shown_route = None
        self._restore_drafts(snapshot)
        self._populate()
        return True


def choose_inferred_path(parent, inventory, source, sink, *, include_unknown=False):
    """Compatibility dialog for callers which do not embed the inference panel."""
    import wx
    from wayricad_runtime.layout import fit_to_display
    dialog = wx.Dialog(parent, title='Infer series paths · review components and models',
                       size=(1000, 740), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    result = None
    def apply(path):
        nonlocal result
        result = path
        dialog.EndModal(wx.ID_OK)
    try:
        layout = wx.BoxSizer(wx.VERTICAL)
        area = wx.ScrolledWindow(dialog, style=wx.HSCROLL | wx.VSCROLL)
        area.SetScrollRate(12, 12)
        content = wx.BoxSizer(wx.VERTICAL)
        review = InlineInference(area, inventory, apply)
        content.Add(review.panel, 0, wx.EXPAND | wx.ALL, 10)
        area.SetSizer(content)
        layout.Add(area, 1, wx.EXPAND)
        layout.Add(wx.Button(dialog, wx.ID_CANCEL), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dialog.SetSizer(layout)
        if not review.infer(source, sink, include_unknown):
            raise ValueError(review.status.GetLabel())
        fit_to_display(dialog)
        return result if dialog.ShowModal() == wx.ID_OK else None
    finally:
        dialog.Destroy()
