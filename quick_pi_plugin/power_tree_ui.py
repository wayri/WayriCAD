"""Small native review editor for power intent; no graph-framework dependency."""
from __future__ import annotations

from .power_tree import (KINDS, infer_power_tree, load_power_tree, new_edge,
                         new_node, save_power_tree, validate_power_tree)


def diagram_positions(tree):
    """Deterministic energy-flow columns, including disconnected candidates."""
    levels = {node['id']: 0 for node in tree['nodes']}
    for _ in tree['nodes']:
        changed = False
        for edge in tree['edges']:
            if levels[edge['target']] <= levels[edge['source']]:
                levels[edge['target']] = levels[edge['source']] + 1; changed = True
        if not changed:
            break
    counts = {}; positions = {}
    for node in sorted(tree['nodes'], key=lambda row: (levels[row['id']], row['id'])):
        column = levels[node['id']]; row = counts.get(column, 0); counts[column] = row + 1
        positions[node['id']] = (24 + column * 210, 24 + row * 105)
    return positions


class PowerTreeDialog:
    """Use ``dialog.ShowModal()``; ``tree`` is set only by reviewed acceptance.

    ``draft`` remains a private detached document until save/accept. No PCB,
    schematic, solver endpoint or previous result is changed by this editor.
    """
    def __init__(self, parent, inventory, board_path=None, existing=None):
        import wx
        self.wx = wx; self.inventory = inventory; self.tree = None; self.selected = None
        self.draft = validate_power_tree(existing) if existing is not None else infer_power_tree(
            inventory, {'board_path': str(board_path), 'source_sha256':inventory.get('source_sha256')} if board_path else None)
        self.dialog = wx.Dialog(parent, title='Quick PI · Reviewed power tree',
                                size=(1180, 820), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self.dialog, label='Review power intent from source → rail → converter → rail → load. '
                              'Arrows show energy flow. Voltages are signed relative to each rail’s explicit return; isolation remains separate.')
        intro.Wrap(1100); root.Add(intro, 0, wx.EXPAND | wx.ALL, 12)
        main = wx.BoxSizer(wx.HORIZONTAL)
        self.canvas = wx.ScrolledWindow(self.dialog, style=wx.HSCROLL | wx.VSCROLL | wx.BORDER_SIMPLE)
        self.canvas.SetScrollRate(12, 12); self.canvas.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.canvas.Bind(wx.EVT_PAINT, self._paint); self.canvas.Bind(wx.EVT_LEFT_DOWN, self._pick)
        main.Add(self.canvas, 2, wx.EXPAND | wx.RIGHT, 12)
        right = wx.BoxSizer(wx.VERTICAL)
        self.choose = wx.Choice(self.dialog); self.choose.Bind(wx.EVT_CHOICE, self._selected)
        right.Add(self.choose, 0, wx.EXPAND | wx.BOTTOM, 8)
        self.fields = {}; form = wx.FlexGridSizer(0, 2, 6, 7); form.AddGrowableCol(1)
        self.kind = wx.Choice(self.dialog, choices=list(KINDS))
        form.Add(wx.StaticText(self.dialog, label='Role'), 0, wx.ALIGN_CENTER_VERTICAL); form.Add(self.kind, 1, wx.EXPAND)
        for key, label in [('label', 'Label'), ('net', 'Rail net'), ('return_net', 'Return net'),
                           ('voltage_v', 'Signed voltage · V'), ('domain', 'Isolation domain'),
                           ('reference', 'Device reference'), ('footprint_uuid', 'Footprint UUID')]:
            control = wx.TextCtrl(self.dialog)
            self.fields[key] = control
            form.Add(wx.StaticText(self.dialog, label=label), 0, wx.ALIGN_CENTER_VERTICAL); form.Add(control, 1, wx.EXPAND)
        right.Add(form, 0, wx.EXPAND | wx.BOTTOM, 8)
        self.reviewed = wx.CheckBox(self.dialog, label='I reviewed this node and its assumptions')
        right.Add(self.reviewed, 0, wx.BOTTOM, 8)
        self.evidence = wx.TextCtrl(self.dialog, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 110))
        right.Add(self.evidence, 1, wx.EXPAND | wx.BOTTOM, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Apply node edits', self._apply), ('Delete node', self._delete)]:
            button = wx.Button(self.dialog, label=label); button.Bind(wx.EVT_BUTTON, handler); actions.Add(button, 0, wx.RIGHT, 5)
        right.Add(actions, 0, wx.BOTTOM, 8)
        add = wx.BoxSizer(wx.HORIZONTAL); self.add_kind = wx.Choice(self.dialog, choices=list(KINDS)); self.add_kind.SetSelection(0)
        add.Add(self.add_kind, 1, wx.RIGHT, 6)
        button = wx.Button(self.dialog, label='Add node'); button.Bind(wx.EVT_BUTTON, self._add); add.Add(button)
        right.Add(add, 0, wx.EXPAND)
        main.Add(right, 1, wx.EXPAND); root.Add(main, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        edges = wx.BoxSizer(wx.HORIZONTAL)
        self.edge_list = wx.ListBox(self.dialog, size=(-1, 110)); self.edge_list.Bind(wx.EVT_LISTBOX, self._edge_selected)
        edges.Add(self.edge_list, 1, wx.EXPAND | wx.RIGHT, 10)
        links = wx.BoxSizer(wx.VERTICAL)
        self.link_from = wx.Choice(self.dialog); self.link_to = wx.Choice(self.dialog)
        for label, control in [('Energy from', self.link_from), ('Energy to', self.link_to)]:
            row = wx.BoxSizer(wx.HORIZONTAL); row.Add(wx.StaticText(self.dialog, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            row.Add(control, 1); links.Add(row, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.edge_reviewed = wx.CheckBox(self.dialog, label='Connection reviewed')
        links.Add(self.edge_reviewed, 0, wx.BOTTOM, 5)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Add link', self._link), ('Update review', self._review_edge), ('Delete link', self._unlink)]:
            button = wx.Button(self.dialog, label=label); button.Bind(wx.EVT_BUTTON, handler); row.Add(button, 0, wx.RIGHT, 5)
        links.Add(row); edges.Add(links, 1, wx.EXPAND)
        root.Add(edges, 0, wx.EXPAND | wx.ALL, 12)
        self.status = wx.StaticText(self.dialog, label='Candidates remain unreviewed. Unknown voltage/reference/domain values remain blank.')
        root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Load tree…', self._load), ('Save draft…', self._save), ('Validate review', self._validate)]:
            button = wx.Button(self.dialog, label=label); button.Bind(wx.EVT_BUTTON, handler); footer.Add(button, 0, wx.RIGHT, 6)
        footer.AddStretchSpacer()
        button = wx.Button(self.dialog, label='Use reviewed tree'); button.Bind(wx.EVT_BUTTON, self._accept); footer.Add(button, 0, wx.RIGHT, 8)
        footer.Add(wx.Button(self.dialog, wx.ID_CANCEL, label='Close'), 0)
        root.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.dialog.SetSizer(root); self.dialog.SetMinSize((900, 700)); self._refresh()

    def _error(self, exc):
        self.status.SetLabel(str(exc)); self.status.Wrap(max(500, self.dialog.GetClientSize().width - 30)); self.dialog.Layout()

    def _refresh(self):
        self.ids = [node['id'] for node in self.draft['nodes']]
        labels = [node['label'] + ' · ' + node['kind'] + ('' if node.get('reviewed') else ' · review') for node in self.draft['nodes']]
        self.choose.SetItems(labels)
        for control in (self.link_from, self.link_to):
            control.SetItems([node['id'] + ' · ' + node['label'] for node in self.draft['nodes']])
            if self.ids: control.SetSelection(0)
        self.edge_list.SetItems([edge['source'] + ' → ' + edge['target'] + ('' if edge.get('reviewed') else ' · review') for edge in self.draft['edges']])
        if self.selected not in self.ids: self.selected = self.ids[0] if self.ids else None
        if self.selected:
            self.choose.SetSelection(self.ids.index(self.selected)); self._show_node()
        else:
            for field in self.fields.values(): field.SetValue('')
            self.evidence.SetValue('Add a node or load a saved tree.'); self.reviewed.SetValue(False)
        self.positions = diagram_positions(self.draft)
        self.canvas.SetVirtualSize((max([x + 200 for x, y in self.positions.values()] + [600]),
                                    max([y + 105 for x, y in self.positions.values()] + [300])))
        self.canvas.Refresh()

    def _selected(self, event=None):
        self.selected = self.ids[self.choose.GetSelection()]; self._show_node(); self.canvas.Refresh()

    def _show_node(self):
        node = next(node for node in self.draft['nodes'] if node['id'] == self.selected)
        self.kind.SetStringSelection(node['kind']); self.reviewed.SetValue(node.get('reviewed', False))
        for key, control in self.fields.items():
            value = node.get(key); control.SetValue('' if value is None else str(value))
        self.evidence.SetValue('ID: ' + node['id'] + '\nEvidence: ' + node.get('confidence', 'manual') + '\n' + '\n'.join(node.get('evidence', [])))

    def _apply(self, event=None):
        if not self.selected: return False
        candidate = validate_power_tree(self.draft)
        node = next(node for node in candidate['nodes'] if node['id'] == self.selected)
        node['kind'] = self.kind.GetStringSelection()
        values = {key: control.GetValue().strip() for key, control in self.fields.items()}
        try:
            node['label'] = values['label']; node['reviewed'] = self.reviewed.GetValue()
            if node['kind'] == 'rail':
                for key in ('net', 'return_net', 'domain'): node[key] = values[key]
                node['voltage_v'] = float(values['voltage_v']) if values['voltage_v'] else None
                for key in ('reference', 'footprint_uuid'): node.pop(key, None)
            else:
                for key in ('reference', 'footprint_uuid'): node[key] = values[key]
                for key in ('net', 'return_net', 'domain', 'voltage_v'): node.pop(key, None)
            evidence = node.setdefault('evidence', [])
            if 'Node fields edited in native review.' not in evidence: evidence.append('Node fields edited in native review.')
            self.draft = validate_power_tree(candidate, inventory=self.inventory); self._refresh()
            self.status.SetLabel('Node edits kept in this draft. Validate the complete tree before use.'); return True
        except (ValueError, TypeError) as exc:
            self._error(exc); return False

    def _add(self, event=None):
        number = 1
        while 'node-' + str(number) in self.ids: number += 1
        node = new_node('node-' + str(number), self.add_kind.GetStringSelection())
        candidate = validate_power_tree(self.draft); candidate['nodes'].append(node)
        try: self.draft = validate_power_tree(candidate)
        except ValueError as exc: self._error(exc); return
        self.selected = node['id']; self._refresh()

    def _delete(self, event=None):
        self.draft['nodes'] = [node for node in self.draft['nodes'] if node['id'] != self.selected]
        self.draft['edges'] = [edge for edge in self.draft['edges'] if self.selected not in (edge['source'], edge['target'])]
        self._refresh()

    def _link(self, event=None):
        if not self.ids: return
        candidate = validate_power_tree(self.draft)
        edge = new_edge(self.ids[self.link_from.GetSelection()], self.ids[self.link_to.GetSelection()])
        edge['reviewed'] = self.edge_reviewed.GetValue(); candidate['edges'].append(edge)
        try: self.draft = validate_power_tree(candidate); self._refresh()
        except ValueError as exc: self._error(exc)

    def _edge_selected(self, event=None):
        index = self.edge_list.GetSelection()
        if index >= 0: self.edge_reviewed.SetValue(self.draft['edges'][index].get('reviewed', False))

    def _review_edge(self, event=None):
        index = self.edge_list.GetSelection()
        if index >= 0:
            self.draft['edges'][index]['reviewed'] = self.edge_reviewed.GetValue(); self._refresh()

    def _unlink(self, event=None):
        index = self.edge_list.GetSelection()
        if index >= 0: self.draft['edges'].pop(index); self._refresh()

    def _validate(self, event=None):
        if self.selected and not self._apply(): return None
        try:
            result = validate_power_tree(self.draft, require_reviewed=True, inventory=self.inventory)
            if not result['nodes']: raise ValueError('Add at least one complete source/rail/load path.')
            self.status.SetLabel('Reviewed intent is internally consistent. No copper, converter dynamics or isolation rating has been solved.')
            return result
        except ValueError as exc: self._error(exc); return None

    def _accept(self, event=None):
        result = self._validate()
        if result is not None: self.tree = result; self.dialog.EndModal(self.wx.ID_OK)

    def _file(self, save):
        wx = self.wx
        style = wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT if save else wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        dialog = wx.FileDialog(self.dialog, 'Save power-tree draft' if save else 'Load power tree',
                               wildcard='Power-tree JSON (*.json)|*.json', style=style)
        try: return dialog.GetPath() if dialog.ShowModal() == wx.ID_OK else None
        finally: dialog.Destroy()

    def _save(self, event=None):
        if self.selected and not self._apply(): return
        path = self._file(True)
        if path:
            try: save_power_tree(path, self.draft); self.status.SetLabel('Saved draft; review status and evidence are retained.')
            except (ValueError, OSError) as exc: self._error(exc)

    def _load(self, event=None):
        path = self._file(False)
        if path:
            try: self.draft = load_power_tree(path, inventory=self.inventory); self._refresh()
            except (ValueError, OSError) as exc: self._error(exc)

    def _paint(self, event):
        wx = self.wx; dc = wx.AutoBufferedPaintDC(self.canvas); self.canvas.PrepareDC(dc)
        background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        foreground = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        dc.SetBackground(wx.Brush(background)); dc.Clear(); dc.SetTextForeground(foreground)
        dc.SetFont(self.canvas.GetFont())
        for edge in self.draft['edges']:
            x, y = self.positions[edge['source']]; tx, ty = self.positions[edge['target']]
            dc.SetPen(wx.Pen(foreground, 1, wx.PENSTYLE_SOLID if edge.get('reviewed') else wx.PENSTYLE_SHORT_DASH))
            dc.DrawLine(x + 170, y + 38, tx, ty + 38)
            dc.DrawLine(tx - 8, ty + 33, tx, ty + 38); dc.DrawLine(tx - 8, ty + 43, tx, ty + 38)
        for node in self.draft['nodes']:
            x, y = self.positions[node['id']]
            dc.SetPen(wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT) if node['id'] == self.selected else foreground, 3 if node['id'] == self.selected else 1))
            dc.SetBrush(wx.Brush(background)); dc.DrawRoundedRectangle(x, y, 170, 78, 6)
            label = node['label']; label = label if len(label) <= 22 else label[:19] + '…'
            dc.DrawText(label, x + 8, y + 7); dc.DrawText(node['kind'] + ('' if node.get('reviewed') else ' · review'), x + 8, y + 28)
            detail = ('? V' if node.get('voltage_v') is None else str(node['voltage_v']) + ' V') if node['kind'] == 'rail' else node.get('reference', '')
            dc.DrawText(detail[:24], x + 8, y + 49)

    def _pick(self, event):
        point = self.canvas.CalcUnscrolledPosition(event.GetPosition())
        for key, (x, y) in self.positions.items():
            if x <= point.x <= x + 170 and y <= point.y <= y + 78:
                self.selected = key; self.choose.SetSelection(self.ids.index(key)); self._show_node(); self.canvas.Refresh(); break
