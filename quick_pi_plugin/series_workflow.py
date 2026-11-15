"""Guided series/bundle presentation, sharing the established path contracts."""
from copy import deepcopy


def checked_path(path, inventory, command=None):
    from .series_editor import parse_saved_path, path_from_command
    data = path_from_command(command, inventory, existing=path) if command is not None else deepcopy(path)
    parsed = parse_saved_path(data, inventory)
    if not parsed.get('series'):
        raise ValueError('Choose a series stage; same-net paths belong in the single-net setup.')
    return data


def stage_options(path, index, inventory):
    """Only replacements spanning the existing stage's exact net pair."""
    from .series_editor import parse_saved_path
    parsed = parse_saved_path(path, inventory)
    if not 0 <= index < len(parsed['series']):
        raise ValueError('Select a stage to correct.')
    rows = inventory.get('terminals', [])
    lookup = {row['id']: row for row in rows}
    stage = parsed['series'][index]
    start, end = lookup[stage['from_pad']]['net'], lookup[stage['to_pad']]['net']
    used = {part['id'] for i, item in enumerate(parsed['series']) for part in
            [item, *item.get('parallel', [])] if i != index}
    groups = {}
    for row in rows:
        ref = row.get('reference', row['label'].rsplit('.', 1)[0])
        if ref in used:
            continue
        key = (ref, row.get('footprint_uuid', ref))
        groups.setdefault(key, []).append(row)
    return [dict(reference=ref, from_pads=[p['id'] for p in pads if p['net'] == start],
                 to_pads=[p['id'] for p in pads if p['net'] == end])
            for (ref, owner), pads in sorted(groups.items())
            if any(p['net'] == start for p in pads) and any(p['net'] == end for p in pads)]


def corrected_stage(path, index, inventory, reference, incoming, outgoing, model,
                    *, replace_groups=False, all_in=False, all_out=False):
    from .series_editor import parse_saved_path, current_pad_group
    data = deepcopy(path)
    options = stage_options(path, index, inventory)
    found = next((p for p in options if p['reference'] == reference and
                  incoming in p['from_pads'] and outgoing in p['to_pads']), None)
    if found is None:
        raise ValueError('Choose reviewed current pins on the existing stage net pair.')
    parsed = parse_saved_path(path, inventory)['series'][index]
    previous = data['branches'][index]
    same = (reference, incoming, outgoing) == (parsed['id'], parsed['from_pad'], parsed['to_pad'])
    if same and not replace_groups:
        previous['model'] = model
    else:
        if not replace_groups and any(previous.get(k) for k in ('from_pads', 'to_pads', 'parallel')):
            raise ValueError('Confirm replacement of the previous pin groups and parallel bank.')
        data['branches'][index] = dict(reference=reference, from_pad=incoming, to_pad=outgoing, model=model,
            from_pads=current_pad_group(inventory['terminals'], incoming, all_in),
            to_pads=current_pad_group(inventory['terminals'], outgoing, all_out))
    return checked_path(data, inventory)


class GuidedSeriesWorkflow:
    """Small view/controller boundary; no solver or persistence policy lives here."""
    def __init__(self, parent, editor):
        import wx
        self.wx, self.editor = wx, editor
        self.current_path = None
        self.last_mode = 0
        self.book = wx.Notebook(parent)
        self.book.SetMinSize((0,250))
        self.auto, self.console, self.bundle = (wx.ScrolledWindow(self.book) for _ in range(3))
        for page, label in ((self.auto, 'Auto'), (self.console, 'Console'), (self.bundle, 'Bundle')):
            page.SetScrollRate(12,12)
            self.book.AddPage(page, label)
        self.auto_sizer, self.console_sizer, self.bundle_sizer = (wx.BoxSizer(wx.VERTICAL) for _ in range(3))
        for page, sizer in ((self.auto, self.auto_sizer), (self.console, self.console_sizer),
                            (self.bundle, self.bundle_sizer)):
            page.SetSizer(sizer)
        self.corrections = wx.CollapsiblePane(parent, label='Correct stages / explicit path')
        from .series_power_tree_ui import diagram_canvas
        self.preview_book = wx.Notebook(parent)
        self.preview_book.SetMinSize((0,160))
        self.diagram = diagram_canvas(self.preview_book, {'nodes': []})
        self.tree = wx.TreeCtrl(self.preview_book, style=wx.TR_DEFAULT_STYLE | wx.TR_HAS_BUTTONS, size=(-1, 160))
        self.tree.SetMinSize((0, 120))
        self.preview_book.AddPage(self.diagram,'Diagram')
        self.preview_book.AddPage(self.tree,'Details')
        self.preview_controls=wx.BoxSizer(wx.HORIZONTAL)
        self.preview_controls.Add(wx.StaticText(parent,label='Topology only - no solved voltages, currents or power.'),
                                  1,wx.ALIGN_CENTER_VERTICAL)
        for art,tip,handler in ((wx.ART_PLUS,'Zoom in',lambda e:self.diagram.zoom(1.2)),
                               (wx.ART_MINUS,'Zoom out',lambda e:self.diagram.zoom(1/1.2)),
                               (wx.ART_GO_HOME,'Fit diagram width',lambda e:(self.diagram.fit_width(),self.diagram.Refresh(False)))):
            button=wx.BitmapButton(parent,bitmap=wx.ArtProvider.GetBitmap(art,wx.ART_BUTTON,(16,16)))
            button.SetToolTip(tip);button.Bind(wx.EVT_BUTTON,handler)
            self.preview_controls.Add(button,0,wx.LEFT,4)
        self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._mode_changed)
        self.corrections.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._layout)

    @property
    def mode(self):
        return self.book.GetSelection() if self.book.GetSelection() < 2 else self.last_mode

    def _layout(self, event=None):
        for page in (self.auto,self.console,self.bundle):
            page.Layout()
            page.FitInside()
        self.editor.body.Layout()
        self.editor.body.FitInside()
        if event:
            event.Skip()

    def _mode_changed(self, event):
        if self.book.GetSelection() < 2:
            self.last_mode = self.book.GetSelection()
        if self.mode == 1 and not self.editor.manual.GetValue().strip():
            from .series_editor import display_path_command
            try:
                data = self.resolve_auto()
                self.editor.manual.ChangeValue(display_path_command(data, self.editor.inventory))
                self.editor._manual_pending = True
            except ValueError:
                pass
        self.refresh()
        self._layout(event)

    def resolve_auto(self):
        editor = self.editor
        if editor.inference.proposal is not None:
            data = editor.inference.reviewed_path()
            for role, check in (('source', editor.source_all), ('sink', editor.sink_all)):
                if not check.GetValue():
                    data.pop(role + '_terminals', None)
        else:
            data = editor._path_data()
        return checked_path(data, editor.inventory)

    def resolve(self):
        editor = self.editor
        if self.mode == 1:
            return checked_path(editor._path_data(), editor.inventory, editor.manual.GetValue())
        return self.resolve_auto()

    def refresh(self):
        if not hasattr(self.editor, 'run_button'):
            return
        self.current_path = None
        self.tree.DeleteAllItems()
        try:
            if self.book.GetSelection() == 2:
                batch = self.editor.batch_setup
                if not 0 <= batch.selected < len(batch.cases):
                    raise ValueError('Select a bundle case to preview, or edit a path in Auto / Console.')
                from .series_editor import draft_from_request
                data = draft_from_request(batch.cases[batch.selected]['electrical'], self.editor.inventory)['path']
            else:
                data = self.resolve()
            from .series_power_tree import series_path_tree
            tree = series_path_tree(data, self.editor.inventory)
            self.diagram.set_tree(tree)
            root = self.tree.AddRoot('Reviewed saved-net path (topology only)')
            for node in tree['nodes']:
                item = self.tree.AppendItem(root, node['kind'] + ': ' + node['label'])
                for part in node.get('parts', []):
                    child = self.tree.AppendItem(item, part['reference'] + ': ' + str(part['model'].get('model', '')))
                    for title, key in (('In', 'incoming_pins'), ('Out', 'outgoing_pins')):
                        self.tree.AppendItem(child, title + ': ' + ', '.join(p['label'] for p in part[key]))
                if node.get('pins'):
                    self.tree.AppendItem(item, ', '.join(p['label'] for p in node['pins']))
            self.tree.ExpandAll()
            self.current_path = data
            self.editor.preview.ChangeValue('Valid reviewed path; ' + str(len(data['branches'])) + ' stage(s).')
        except (ValueError, KeyError) as exc:
            self.diagram.set_tree({'nodes': []})
            self.tree.DeleteAllItems()
            self.tree.AddRoot('Incomplete path - preview cleared')
            self.editor.preview.ChangeValue(str(exc))
        ready = self.current_path is not None and self.book.GetSelection() != 2
        self.editor.run_button.Enable(ready)
        self.editor.save_button.Enable(ready)
        self._layout()

    def edit_stage(self, event=None):
        import wx
        from wayricad_runtime.readable_choice import ReadableChoice
        editor = self.editor
        index = (editor.inference.stage_choice.GetSelection() if editor.inference.proposal is not None
                 else editor.list.GetSelection())
        try:
            path = self.resolve()
            if index < 0 and path['branches']:
                index = 0
            choices = stage_options(path, index, editor.inventory)
        except ValueError as exc:
            editor.preview.ChangeValue(str(exc))
            return
        dialog = wx.Dialog(editor.dialog, title='Correct series stage', size=(650, 460),
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        box = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(cols=2, hgap=8, vgap=8)
        form.AddGrowableCol(1)
        component = ReadableChoice(dialog, choices=[p['reference'] for p in choices])
        incoming, outgoing = ReadableChoice(dialog), ReadableChoice(dialog)
        model = wx.TextCtrl(dialog, value=path['branches'][index]['model'])
        kind = ReadableChoice(dialog, choices=['Resistance / RL', 'Fixed forward drop', 'Diode at DC current'])
        kind.SetSelection(0)
        for title, control in (('Component', component), ('Incoming current pin', incoming),
                               ('Outgoing current pin', outgoing), ('Model type', kind), ('Model', model)):
            form.Add(wx.StaticText(dialog, label=title), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        box.Add(form, 0, wx.EXPAND | wx.ALL, 12)
        all_in = wx.CheckBox(dialog, label='All same-component / net incoming pins')
        all_out = wx.CheckBox(dialog, label='All same-component / net outgoing pins')
        replace = wx.CheckBox(dialog, label='Replace previous pin groups and parallel bank')
        for control in (all_in, all_out, replace):
            box.Add(control, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        status = wx.StaticText(dialog, label='')
        box.Add(status, 1, wx.EXPAND | wx.ALL, 12)
        buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        dialog.SetSizer(box)

        def populate(event=None):
            p = choices[component.GetSelection()]
            for control, field in ((incoming, 'from_pads'), (outgoing, 'to_pads')):
                control.Set([editor._pad_aliases.get(i, i) for i in p[field]])
                control.SetSelection(wx.NOT_FOUND)
            if event:
                model.ChangeValue('')
                all_in.SetValue(False)
                all_out.SetValue(False)
            dialog.FindWindow(wx.ID_OK).Enable(False)

        selected = next(i for i, p in enumerate(choices) if p['reference'] == path['branches'][index]['reference'])
        component.SetSelection(selected)
        populate()
        from .series_editor import parse_saved_path
        parsed = parse_saved_path(path, editor.inventory)
        for control, field in ((incoming, 'from_pad'), (outgoing, 'to_pad')):
            control.SetStringSelection(editor._pad_aliases.get(parsed['series'][index][field], parsed['series'][index][field]))
        candidate = [None]

        def validate(event=None):
            candidate[0] = None
            all_in.Enable(replace.GetValue())
            all_out.Enable(replace.GetValue())
            try:
                p = choices[component.GetSelection()]
                if min(incoming.GetSelection(), outgoing.GetSelection()) < 0:
                    raise ValueError('Choose both current pins explicitly; unrelated pins stay excluded.')
                from .console import _model
                values = _model(model.GetValue())
                actual = 2 if 'diode' in values else 1 if 'fixed_drop_v' in values else 0
                if actual != kind.GetSelection():
                    raise ValueError('Model expression must match the selected model type.')
                candidate[0] = corrected_stage(path, index, editor.inventory, p['reference'],
                    p['from_pads'][incoming.GetSelection()], p['to_pads'][outgoing.GetSelection()], model.GetValue(),
                    replace_groups=replace.GetValue(), all_in=all_in.GetValue(), all_out=all_out.GetValue())
                status.SetLabel('Ready')
            except ValueError as exc:
                status.SetLabel(str(exc))
                status.Wrap(590)
            dialog.FindWindow(wx.ID_OK).Enable(candidate[0] is not None)
            if event:
                event.Skip()

        from .console import _model
        values = _model(model.GetValue())
        kind.SetSelection(2 if 'diode' in values else 1 if 'fixed_drop_v' in values else 0)
        component.Bind(wx.EVT_CHOICE, lambda event: (populate(event), validate()))
        for control in (incoming, outgoing, kind):
            control.Bind(wx.EVT_CHOICE, validate)
        model.Bind(wx.EVT_TEXT, validate)
        for control in (replace, all_in, all_out):
            control.Bind(wx.EVT_CHECKBOX, validate)
        validate()
        try:
            if dialog.ShowModal() == wx.ID_OK and candidate[0] is not None:
                editor._restore_path(candidate[0])
                editor.manual.ChangeValue('')
                editor._manual_pending = False
                self.book.SetSelection(0)
                self.refresh()
        finally:
            dialog.Destroy()
