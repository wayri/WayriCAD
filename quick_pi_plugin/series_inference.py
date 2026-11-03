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


def choose_inferred_path(parent, inventory, source, sink, *, include_unknown=False):
    import wx
    from wayricad_runtime.layout import fit_to_display
    from wayricad_runtime.series_topology import infer_series_paths
    from .console import terminal_aliases
    from .parallel_parts import suggested_resistance
    proposal = infer_series_paths(inventory, source, sink, include_unknown=include_unknown)
    if not proposal['routes']:
        raise ValueError('No candidate series route found. Review the endpoints and device classes, or add explicit pad pairs for other devices.')
    if not proposal['routes'][0]['stages']:
        raise ValueError('The endpoints share a saved net. Use the normal single-net setup; no series component is needed.')
    aliases = terminal_aliases(inventory)
    dialog = wx.Dialog(parent, title='Infer series paths · review components and models',
                       size=(1000, 740), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    layout = wx.BoxSizer(wx.VERTICAL)
    note = wx.StaticText(dialog, label=proposal['notice'] +
        (' Search limit reached; additional routes may exist.' if proposal['truncated'] else ''))
    note.Wrap(920); layout.Add(note, 0, wx.EXPAND | wx.ALL, 10)
    routes = wx.Choice(dialog, choices=[' → '.join(route['nets']) for route in proposal['routes']])
    routes.SetSelection(0); layout.Add(routes, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    area = wx.ScrolledWindow(dialog, style=wx.HSCROLL | wx.VSCROLL)
    area.SetScrollRate(12, 12); area.SetMinSize((0, 0))
    stack = wx.BoxSizer(wx.VERTICAL); area.SetSizer(stack)
    layout.Add(area, 1, wx.EXPAND | wx.ALL, 10)
    omitted = ', '.join(proposal['omitted_references'][:20])
    if omitted:
        omitted_note = wx.StaticText(dialog, label='Not traversed automatically: ' + omitted +
            '. Use explicit pad pairs for other device types.')
        omitted_note.Wrap(920); layout.Add(omitted_note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    actions = wx.BoxSizer(wx.HORIZONTAL)
    actions.AddStretchSpacer()
    accept = wx.Button(dialog, wx.ID_OK, label='Use reviewed path')
    actions.Add(accept, 0, wx.RIGHT, 8); actions.Add(wx.Button(dialog, wx.ID_CANCEL), 0)
    layout.Add(actions, 0, wx.EXPAND | wx.ALL, 10); dialog.SetSizer(layout)
    controls, drafts = [], {}
    def remember():
        for stage in controls:
            for part, check, text, incoming, outgoing in stage:
                drafts[(part['footprint_uuid'], tuple(part['from_pads']), tuple(part['to_pads']))] = (
                    check.GetValue(), text.GetValue(), [p for p,c in incoming if c.GetValue()], [p for p,c in outgoing if c.GetValue()])
    def populate(event=None):
        remember(); controls.clear(); stack.Clear(True)
        for number, stage in enumerate(proposal['routes'][routes.GetSelection()]['stages'], 1):
            stack.Add(wx.StaticText(area, label=f"Stage {number}: {stage['from_net']} → {stage['to_net']}"), 0, wx.TOP | wx.BOTTOM, 8)
            bank = []
            for part in stage['parts']:
                key = (part['footprint_uuid'], tuple(part['from_pads']), tuple(part['to_pads']))
                default = suggested_resistance(dict(id=part['reference'], component_value=part['component_value']))
                checked, model, selected_in, selected_out = drafts.get(key, (True, default, part['from_pads'], part['to_pads']))
                panel = wx.Panel(area); box = wx.BoxSizer(wx.VERTICAL)
                check = wx.CheckBox(panel, label=part['reference'] + ' · ' + part['component_value'] + ' (parallel bank)' if len(stage['parts']) > 1 else part['reference'] + ' · ' + part['component_value'])
                check.SetValue(checked); box.Add(check, 0, wx.BOTTOM, 4)
                pins = []
                for label, identifiers, selected in (('Incoming', part['from_pads'], selected_in), ('Outgoing', part['to_pads'], selected_out)):
                    line = wx.WrapSizer(wx.HORIZONTAL); line.Add(wx.StaticText(panel, label=label + ': '), 0, wx.ALIGN_CENTER_VERTICAL)
                    group = []
                    for identifier in identifiers:
                        control = wx.CheckBox(panel, label=aliases[identifier]); control.SetValue(identifier in selected)
                        line.Add(control, 0, wx.RIGHT, 8); group.append((identifier, control))
                    pins.append(group); box.Add(line, 0, wx.EXPAND | wx.BOTTOM, 4)
                excluded = ', '.join(aliases[p] for p in part['excluded_pads']) or 'None'
                box.Add(wx.StaticText(panel, label='Excluded pins: ' + excluded), 0, wx.BOTTOM, 4)
                model_row = wx.BoxSizer(wx.HORIZONTAL)
                model_row.Add(wx.StaticText(panel, label='Model: '), 0, wx.ALIGN_CENTER_VERTICAL)
                text = wx.TextCtrl(panel, value=model); text.SetHint('100mΩ, 5mΩ+10nH, 0.7V or diode(Vf=0.7V,Iref=1A,n=2,T=25C)')
                model_row.Add(text, 1, wx.EXPAND); box.Add(model_row, 0, wx.EXPAND)
                panel.SetSizer(box); stack.Add(panel, 0, wx.EXPAND | wx.LEFT | wx.BOTTOM, 12)
                bank.append((part, check, text, *pins))
            controls.append(bank)
        area.Layout(); area.FitInside(); area.Scroll(0, 0); dialog.Layout()
    result = None
    def apply(event):
        nonlocal result
        selections = [[dict(footprint_uuid=p['footprint_uuid'], model=text.GetValue(),
                           from_pads=[identifier for identifier,c in incoming if c.GetValue()],
                           to_pads=[identifier for identifier,c in outgoing if c.GetValue()])
                       for p,check,text,incoming,outgoing in stage if check.GetValue()] for stage in controls]
        try:
            result = reviewed_path(proposal, routes.GetSelection(), selections, inventory)
        except ValueError as exc:
            wx.MessageBox(str(exc), 'Complete the inferred path', wx.OK | wx.ICON_WARNING, parent=dialog)
            return
        dialog.EndModal(wx.ID_OK)
    routes.Bind(wx.EVT_CHOICE, populate); accept.Bind(wx.EVT_BUTTON, apply)
    populate(); fit_to_display(dialog)
    try:
        return result if dialog.ShowModal() == wx.ID_OK else None
    finally:
        dialog.Destroy()
