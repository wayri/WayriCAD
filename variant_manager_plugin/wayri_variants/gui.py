"""Responsive native review of saved KiCad variants; all writes use service plans."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import copy
import csv
import fnmatch
import html
import json
import wx
import wx.html
from . import service as S


FLAGS = ('dnp', 'excluded_from_bom', 'excluded_from_board', 'excluded_from_pos', 'exclude_from_sim')


def state_text(state, parents=()):
    if state is None:
        return 'Absent variant'
    fields = state['fields']
    flags = ', '.join(name for name in FLAGS if state.get(name)) or 'Included'
    ancestry = '; parent sheet: ' + ', '.join(p['label'] for p in parents if any(p['flags'].values())) if any(any(p['flags'].values()) for p in parents) else ''
    return f"{fields.get('Value', '')} | {fields.get('Footprint', '')} | {flags}{ancestry}"


def board_geometry(project):
    """Read saved geometry only; missing or ambiguous references stay unresolved."""
    try:
        import pcbnew
    except ImportError:
        return [], 'Board preview requires KiCad Python; state comparison remains available.'
    ctx = S.load(project)
    path = (ctx.project or ctx.root).with_suffix('.kicad_pcb')
    if not path.is_file():
        return [], 'No matching saved board; schematic-state preview only.'
    board = pcbnew.LoadBoard(str(path))
    geometry = []
    for footprint in board.GetFootprints():
        box = footprint.GetBoundingBox(False, False)
        geometry.append({'ref': footprint.GetReference(), 'x': pcbnew.ToMM(box.GetX()),
                         'y': pcbnew.ToMM(box.GetY()), 'w': max(.5, pcbnew.ToMM(box.GetWidth())),
                         'h': max(.5, pcbnew.ToMM(box.GetHeight())), 'bottom': footprint.IsFlipped()})
    return geometry, 'Saved footprint envelopes; field/assembly overlay only. Footprint changes require Update PCB from Schematic.'


class AssemblyCanvas(wx.Panel):
    """Compare assembly presence on the same saved physical footprint envelopes."""
    def __init__(self, parent, select):
        super().__init__(parent)
        self.geometry, self.objects, self.original, self.left, self.right, self.hits = [], [], [], S.DEFAULT, S.DEFAULT, []
        self.selected = set()
        self.side = 'Both'
        self.select = select
        self.SetMinSize((450, 150))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.click)

    def click(self, event):
        for box, keys in reversed(self.hits):
            if box.Contains(event.GetPosition()):
                self.select(keys)
                return

    def paint(self, _):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour('#182934')))
        dc.Clear()
        width, height = self.GetClientSize()
        self.hits = []
        geometry = [g for g in self.geometry if self.side == 'Both' or g['bottom'] == (self.side == 'Bottom')]
        if not geometry:
            dc.SetTextForeground(wx.Colour('#dde9ee'))
            dc.DrawText('No saved board geometry. Compare native component states below.', 18, 45)
            return
        x0, y0 = min(g['x'] for g in geometry), min(g['y'] for g in geometry)
        span_x = max(g['x'] + g['w'] for g in geometry) - x0
        span_y = max(g['y'] + g['h'] for g in geometry) - y0
        for pane, name in enumerate((self.left, self.right)):
            start, half = pane * width // 2, width // 2
            scale = max(.1, min((half - 48) / max(1, span_x), (height - 88) / max(1, span_y)))
            dc.SetTextForeground(wx.Colour('#dde9ee'))
            dc.DrawText(('Before: ' if pane == 0 else 'After: ') + name, start + 18, 12)
            by_reference = {}
            for obj in self.original if pane == 0 else self.objects:
                by_reference.setdefault(obj['label'], []).append(obj)
            for g in geometry:
                matches = by_reference.get(g['ref'], [])
                states = [o['states'].get(name) for o in matches]
                inherited = any(any(parent['flags'].values()) for o in matches for parent in o.get('parent_sheet_flags', {}).get(name, []))
                colour = '#647681' if len(states) != 1 or states[0] is None or inherited else (
                    '#bb6473' if states[0].get('excluded_from_board') else '#e4ad55' if states[0].get('dnp') else '#60b5aa')
                rect = wx.Rect(round(start + 24 + (g['x'] - x0) * scale), round(48 + (g['y'] - y0) * scale),
                               max(5, round(g['w'] * scale)), max(5, round(g['h'] * scale)))
                keys = [o['key'] for o in matches]
                dc.SetPen(wx.Pen(wx.Colour('#ffffff') if self.selected.intersection(keys) else wx.Colour(colour), 3 if self.selected.intersection(keys) else 1))
                dc.SetBrush(wx.Brush(wx.Colour(colour)))
                dc.DrawRectangle(rect)
                if rect.width > 20 and rect.height > 10:
                    dc.SetTextForeground(wx.Colour('#14212a'))
                    dc.DrawText(g['ref'], rect.x + 2, rect.y + 1)
                self.hits.append((rect, keys))
        dc.SetTextForeground(wx.Colour('#dde9ee'))
        dc.DrawText('Local flags: teal included · amber DNP · rose off-board · grey parent flag/unresolved', 18, max(30, height - 26))


class OperationDialog(wx.Dialog):
    """One bounded operation; all component edits use exact instance identities."""
    def __init__(self, parent, op, names, chosen, keys):
        super().__init__(parent, title=op.title() + ' variants', size=(540, 430))
        self.op, self.chosen, self.keys = op, chosen, keys
        panel = wx.Panel(self)
        self.panel = panel
        outer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, hgap=12, vgap=12)
        grid.AddGrowableCol(1)
        self.controls = {}
        def field(label, key, choices=None, value=''):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = wx.Choice(panel, choices=choices) if choices else wx.TextCtrl(panel, value=value)
            if choices:
                control.SetSelection(choices.index(value) if value in choices else 0)
            self.controls[key] = control
            grid.Add(control, 1, wx.EXPAND)
        named = [n for n in names if n != S.DEFAULT]
        selected = chosen[0] if chosen else (named[0] if named else S.DEFAULT)
        if op in ('create', 'duplicate', 'rename'):
            field('New name', 'name', value='New variant')
        if op in ('create', 'duplicate', 'rename', 'merge', 'promote'):
            field('Source variant', 'source', names if op in ('create', 'duplicate') else named, selected)
        if op == 'merge':
            field('Merge into', 'target', named, chosen[1] if len(chosen) > 1 else selected)
            field('Conflicts', 'policy', ['error', 'source', 'target'], 'error')
        if op == 'swap':
            field('First variant', 'left', named, selected)
            field('Second variant', 'right', named, chosen[1] if len(chosen) > 1 else selected)
        if op == 'promote':
            field('Keep old Default as (optional)', 'preserve_old')
        if op == 'edit':
            outer.Add(wx.StaticText(panel, label=f'Edit {len(keys)} selected instances in {len(chosen)} named variants.'), 0, wx.BOTTOM, 12)
            field('Property field (optional)', 'field')
            field('New field value', 'value')
            field('Assembly flag (optional)', 'flag', ['No flag change'] + list(FLAGS))
            field('Flag state', 'flag_value', ['True', 'False'])
        if op == 'delete':
            outer.Add(wx.StaticText(panel, label='Delete selected definitions and their overrides:\n' + '\n'.join(chosen)), 0, wx.BOTTOM, 12)
        outer.Add(grid, 0, wx.EXPAND)
        note = wx.StaticText(panel, label='This stages a preview. Source files remain unchanged until Apply.\nMerge combines overrides relative to Default; it does not merge circuits.')
        note.Wrap(490)
        outer.Add(note, 0, wx.TOP | wx.BOTTOM, 18)
        outer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALIGN_RIGHT)
        wrapper = wx.BoxSizer(wx.VERTICAL)
        wrapper.Add(outer, 1, wx.ALL | wx.EXPAND, 18)
        panel.SetSizer(wrapper)
        frame = wx.BoxSizer(wx.VERTICAL)
        frame.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame)

    def operations(self):
        values = {k: c.GetStringSelection() if isinstance(c, wx.Choice) else c.GetValue().strip() for k, c in self.controls.items()}
        if self.op == 'delete':
            return [{'op': 'delete', 'variants': self.chosen}]
        if self.op == 'edit':
            if not self.keys or not self.chosen:
                raise S.Error('Select component rows and named variants before bulk editing.')
            fields = {values['field']: values['value']} if values['field'] else {}
            flags = {values['flag']: values['flag_value'] == 'True'} if values['flag'] != 'No flag change' else {}
            if not fields and not flags:
                raise S.Error('Enter a field or select an assembly flag.')
            return [{'op': 'edit', 'variant': n, 'keys': self.keys, 'fields': fields, 'flags': flags} for n in self.chosen]
        if self.op == 'promote' and not values['preserve_old']:
            del values['preserve_old']
        return [{'op': self.op, **values}]


class VariantFrame(wx.Frame):
    def __init__(self, project='', note=''):
        super().__init__(None, title='WayriCAD Variant Manager', size=(1360, 900))
        self.SetMinSize((1000, 800))
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.closed = False
        self.inventory = None
        self.plan = None
        self.operations = []
        self.visible = []
        self.geometry = []
        self.sort_column, self.sort_reverse = 0, False
        icon = Path(__file__).parents[1] / 'icon.png'
        if icon.is_file():
            self.SetIcon(wx.Icon(str(icon), wx.BITMAP_TYPE_PNG))
        panel = wx.Panel(self)
        self.main_panel = panel
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label='Variant Manager')
        title.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        root.Add(title, 0, wx.ALL, 12)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.project = wx.TextCtrl(panel, value=project)
        bar.Add(self.project, 1, wx.RIGHT, 8)
        self.button(panel, bar, 'Open project…', self.browse)
        self.button(panel, bar, 'Reload', self.reload)
        self.button(panel, bar, 'Help', self.help)
        root.Add(bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        operations = wx.WrapSizer(wx.HORIZONTAL)
        for op in ('create', 'duplicate', 'rename', 'delete', 'edit', 'merge', 'swap', 'promote'):
            self.button(panel, operations, 'Bulk edit' if op == 'edit' else op.title(), lambda _, op=op: self.stage(op))
        self.button(panel, operations, 'Restore…', self.restore)
        self.button(panel, operations, 'Clear staged', self.clear)
        root.Add(operations, 0, wx.ALL | wx.EXPAND, 12)
        split = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(split)
        ls = wx.BoxSizer(wx.VERTICAL)
        ls.Add(wx.StaticText(left, label='Variants · select several for bulk operations'), 0, wx.ALL, 8)
        self.variants = wx.ListBox(left, style=wx.LB_EXTENDED)
        self.variants.Bind(wx.EVT_LISTBOX, self.variant_selected)
        ls.Add(self.variants, 1, wx.ALL | wx.EXPAND, 8)
        left.SetSizer(ls)
        right = wx.Panel(split)
        rs = wx.BoxSizer(wx.VERTICAL)
        comparison = wx.BoxSizer(wx.HORIZONTAL)
        self.before = wx.Choice(right)
        self.after = wx.Choice(right)
        self.side = wx.Choice(right, choices=['Both', 'Top', 'Bottom'])
        self.side.SetSelection(0)
        for label, control in (('Before', self.before), ('After', self.after), ('Board side', self.side)):
            comparison.Add(wx.StaticText(right, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            comparison.Add(control, 1, wx.RIGHT, 12)
            control.Bind(wx.EVT_CHOICE, self.refresh_rows)
        rs.Add(comparison, 0, wx.ALL | wx.EXPAND, 8)
        self.canvas = AssemblyCanvas(right, self.select_keys)
        rs.Add(self.canvas, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.geometry_note = wx.StaticText(right, label='Open a saved project to preview assembly states.')
        rs.Add(self.geometry_note, 0, wx.ALL, 8)
        self.filter = wx.SearchCtrl(right)
        self.filter.SetDescriptiveText('Filter references with wildcards, e.g. J* or U?')
        self.filter.Bind(wx.EVT_TEXT, self.refresh_rows)
        filters = wx.BoxSizer(wx.HORIZONTAL)
        filters.Add(self.filter, 1, wx.RIGHT, 8)
        self.mode = wx.Choice(right, choices=['Compare selected variants', 'All staged changes'])
        self.mode.SetSelection(0)
        self.mode.Bind(wx.EVT_CHOICE, self.refresh_rows)
        filters.Add(self.mode, 0, wx.RIGHT, 8)
        self.button(right, filters, 'Select visible', lambda _: self.select_keys([o['key'] for o in self.visible]))
        rs.Add(filters, 0, wx.EXPAND | wx.ALL, 8)
        self.table = wx.ListCtrl(right, style=wx.LC_REPORT)
        for name, size in [('Instance', 120), ('Before state', 350), ('After state', 350), ('Change', 130)]:
            self.table.InsertColumn(self.table.GetColumnCount(), name, width=size)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.table_selected)
        self.table.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.table_selected)
        self.table.Bind(wx.EVT_LIST_COL_CLICK, self.sort_rows)
        rs.Add(self.table, 1, wx.ALL | wx.EXPAND, 8)
        right.SetSizer(rs)
        split.SplitVertically(left, right, 245)
        split.SetMinimumPaneSize(180)
        split.SetSashGravity(0)
        root.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.review = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 90))
        root.Add(self.review, 0, wx.ALL | wx.EXPAND, 12)
        bottom = wx.BoxSizer(wx.HORIZONTAL)
        self.ack = wx.CheckBox(panel, label='I saved and closed this project’s KiCad editors and project manager')
        bottom.Add(self.ack, 1, wx.ALIGN_CENTER_VERTICAL)
        self.button(panel, bottom, 'Export review…', self.export)
        self.apply_button = self.button(panel, bottom, 'Apply reviewed changes', self.apply)
        self.apply_button.Disable()
        root.Add(bottom, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)
        self.CreateStatusBar()
        self.SetStatusText(note or 'Saved-file preview. PCB geometry stays unchanged; synchronize promoted footprints in KiCad.')
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.project.Bind(wx.EVT_TEXT, self.project_changed)
        if project:
            wx.CallAfter(self.reload)

    def button(self, parent, sizer, label, callback):
        button = wx.Button(parent, label=label)
        button.Bind(wx.EVT_BUTTON, callback)
        sizer.Add(button, 0, wx.RIGHT, 6)
        return button

    def on_close(self, event):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        event.Skip()

    def task(self, message, work, done):
        self.main_panel.Disable()
        self.apply_button.Disable()
        self.SetStatusText(message)
        self.review.SetValue(message)
        future = self.pool.submit(work)
        def completed(f):
            def display():
                if self.closed:
                    return
                self.main_panel.Enable()
                try:
                    done(f.result())
                except Exception as exc:
                    self.plan = None
                    self.review.SetValue(str(exc))
                    self.SetStatusText('Operation could not complete. Read the error and any rollback details before continuing.')
                    wx.MessageBox(str(exc), 'Variant Manager', wx.OK | wx.ICON_ERROR, self)
            wx.CallAfter(display)
        future.add_done_callback(completed)

    def project_changed(self, _):
        self.inventory, self.plan, self.operations = None, None, []
        self.table.DeleteAllItems()
        self.variants.Clear()
        self.canvas.geometry = []
        self.canvas.Refresh()
        self.apply_button.Disable()
        self.review.SetValue('Project changed. Reload the saved hierarchy before staging operations.')

    def browse(self, _):
        with wx.FileDialog(self, 'Open saved KiCad project', wildcard='KiCad project (*.kicad_pro;*.kicad_sch;*.kicad_pcb)|*.kicad_pro;*.kicad_sch;*.kicad_pcb', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.project.SetValue(dialog.GetPath())
                self.reload()

    def reload(self, _=None):
        project = self.project.GetValue()
        self.operations, self.plan = [], None
        def load():
            return S.inventory(project), board_geometry(project)
        def done(result):
            self.inventory, (self.geometry, note) = result
            self.geometry_note.SetLabel(note)
            self.populate_names()
            self.refresh_rows()
            self.review.SetValue('Select variants to compare. Select component rows before Bulk edit.\nChanges are staged; Apply creates a verified backup and checks saved-source hashes.')
            self.SetStatusText(f"{len(self.inventory['objects'])} hierarchy instances · {len(self.inventory['names'])} named variants")
        self.task('Loading saved hierarchy and variant states…', load, done)

    def populate_names(self):
        names = [S.DEFAULT] + (self.plan.names_after if self.plan else self.inventory['names'])
        self.variants.Set(names)
        for control, available in ((self.before, [S.DEFAULT] + self.inventory['names']), (self.after, names)):
            current = control.GetStringSelection()
            control.Set(available)
            control.SetSelection(available.index(current) if current in available else 0)
        if len(names) > 1:
            self.after.SetSelection(1)

    def objects(self):
        objects = copy.deepcopy(self.inventory['objects']) if self.inventory else []
        changed = {}
        for row in getattr(self.plan, 'rows', []) if self.plan else []:
            changed.setdefault(row['key'], []).append(row)
        for obj in objects:
            for row in changed.get(obj['key'], []):
                if row['after'] is None:
                    obj['states'].pop(row['variant'], None)
                else:
                    obj['states'][row['variant']] = row['after']
        if self.plan:
            final = S.review(self.plan).get('states_after', {})
            for obj in objects:
                if obj['key'] in final:
                    obj['states'] = final[obj['key']]
        lookup = {o['key']: o for o in objects}
        for obj in objects:
            template = obj.get('parent_sheet_flags', {}).get(S.DEFAULT, [])
            obj['parent_sheet_flags'] = {name: copy.deepcopy(template) for name in obj['states']}
            for name, parents in obj['parent_sheet_flags'].items():
                for parent in parents:
                    state = lookup[parent['key']]['states'].get(name)
                    if state is not None:
                        parent['flags'] = {flag: state[flag] for flag in parent['flags']}
        return objects

    def refresh_rows(self, _=None):
        if not self.inventory:
            return
        left, right = self.before.GetStringSelection(), self.after.GetStringSelection()
        mask = self.filter.GetValue().strip()
        objects = self.objects()
        original = {o['key']: o for o in self.inventory['objects']}
        self.table.DeleteAllItems()
        self.visible = []
        lookup = {o['key']: o for o in objects}
        if self.mode.GetSelection() == 1 and self.plan:
            entries = [(lookup[r['key']], r['before'], r['after'], r['variant']) for r in getattr(self.plan, 'rows', [])]
        else:
            entries = [(o, original[o['key']]['states'].get(left), o['states'].get(right), 'Changed' if original[o['key']]['states'].get(left) != o['states'].get(right) else 'Same') for o in objects]
        def order(entry):
            obj, before, after, change = entry
            return (obj['label'], state_text(before), state_text(after), change)[self.sort_column].casefold()
        entries.sort(key=order, reverse=self.sort_reverse)
        for obj, before, after, change in entries:
            if mask and not fnmatch.fnmatchcase(obj['label'].casefold(), mask.casefold()) and mask.casefold() not in obj['label'].casefold():
                continue
            index = self.table.InsertItem(self.table.GetItemCount(), obj['label'])
            before_name = change if self.mode.GetSelection() == 1 and self.plan else left
            after_name = change if self.mode.GetSelection() == 1 and self.plan else right
            for column, text in enumerate((state_text(before, original[obj['key']].get('parent_sheet_flags', {}).get(before_name, [])), state_text(after, obj.get('parent_sheet_flags', {}).get(after_name, [])), change), 1):
                self.table.SetItem(index, column, text)
            self.table.SetItemData(index, len(self.visible))
            self.visible.append(obj)
        self.canvas.geometry, self.canvas.objects, self.canvas.original = self.geometry, objects, self.inventory['objects']
        self.canvas.left, self.canvas.right, self.canvas.side = left, right, self.side.GetStringSelection()
        # Before pane needs original states; staged after states are shown on right.
        self.canvas.objects = objects
        self.canvas.Refresh()

    def sort_rows(self, event):
        column = event.GetColumn()
        self.sort_reverse = not self.sort_reverse if column == self.sort_column else False
        self.sort_column = column
        self.refresh_rows()

    def selected_keys(self):
        keys = []
        index = self.table.GetFirstSelected()
        while index != -1:
            keys.append(self.visible[index]['key'])
            index = self.table.GetNextSelected(index)
        return keys

    def select_keys(self, keys):
        for index, obj in enumerate(self.visible):
            self.table.SetItemState(index, wx.LIST_STATE_SELECTED if obj['key'] in keys else 0, wx.LIST_STATE_SELECTED)
        self.table_selected()

    def table_selected(self, _=None):
        self.canvas.selected = set(self.selected_keys())
        self.canvas.Refresh()

    def variant_selected(self, _):
        selected = list(self.variants.GetSelections())
        if selected:
            self.after.SetSelection(selected[-1])
            self.refresh_rows()

    def stage(self, op):
        if not self.inventory:
            return
        chosen = [self.variants.GetString(i) for i in self.variants.GetSelections() if self.variants.GetString(i) != S.DEFAULT]
        names = [S.DEFAULT] + (self.plan.names_after if self.plan else self.inventory['names'])
        if op not in ('create', 'duplicate') and len(names) < 2:
            wx.MessageBox('Create a named variant first.', 'Variant Manager', parent=self)
            return
        if op == 'delete' and not chosen:
            wx.MessageBox('Select named variants to delete.', 'Variant Manager', parent=self)
            return
        with OperationDialog(self, op, names, chosen, self.selected_keys()) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                additions = dialog.operations()
            except S.Error as exc:
                wx.MessageBox(str(exc), 'Variant Manager', parent=self)
                return
        candidate = self.operations + additions
        project = self.project.GetValue()
        def done(plan):
            self.operations, self.plan = candidate, plan
            self.populate_names()
            self.mode.SetSelection(1)
            self.refresh_rows()
            self.review.SetValue('\n'.join(plan.summary) + f'\n{len(getattr(plan, "rows", []))} changed instance/variant states · {plan.count} saved files\n' + plan.diff)
            self.apply_button.Enable(plan.count > 0)
            self.SetStatusText('Review the table and file diff. Apply requires closed project editors and a verified backup.')
        self.task('Building and validating the candidate variant states…', lambda: S.preview(project, candidate), done)

    def clear(self, _):
        self.operations, self.plan = [], None
        self.apply_button.Disable()
        if self.inventory:
            self.populate_names()
            self.refresh_rows()
        self.review.SetValue('Staged operations cleared. Saved files remain unchanged.')

    def apply(self, _):
        if not self.plan:
            return
        if not self.ack.GetValue():
            wx.MessageBox('Save and close this project in KiCad, including its project manager, then tick the acknowledgement. This independent window can remain open.', 'Variant Manager', parent=self)
            return
        plan = self.plan
        def done(backup):
            wx.MessageBox('Applied with verified backup:\n' + str(backup) + '\nReopen KiCad. Promoted footprint/assembly changes need Update PCB from Schematic.', 'Variant Manager', parent=self)
            self.ack.SetValue(False)
            self.reload()
        self.task('Checking source hashes, verifying backup and applying reviewed files…', lambda: S.apply(plan, editors_closed=True), done)

    def restore(self, _):
        if not self.inventory:
            return
        with wx.FileDialog(self, 'Select verified Variant Manager backup', wildcard='ZIP backup (*.zip)|*.zip', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            archive = dialog.GetPath()
        try:
            _, snapshot, _ = S.read_backup(archive)
            with wx.MultiChoiceDialog(self, 'Restore selected variant definitions (geometry stays unchanged)', 'Restore variants', snapshot['names']) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                names = [snapshot['names'][i] for i in dialog.GetSelections()]
            overwrite = bool(set(names).intersection(self.inventory['names']))
            if overwrite and wx.MessageBox('Replace the selected existing variant definitions from this backup?', 'Restore variants', wx.YES_NO | wx.NO_DEFAULT, self) != wx.YES:
                return
            plan = S.plan_restore_variants(self.project.GetValue(), archive, names, overwrite=overwrite)
            self.operations, self.plan = [], plan
            self.populate_names()
            self.refresh_rows()
            self.review.SetValue('\n'.join(plan.summary) + '\n' + plan.diff)
            self.apply_button.Enable(plan.count > 0)
        except Exception as exc:
            wx.MessageBox(str(exc), 'Restore variants', wx.OK | wx.ICON_ERROR, self)

    def export(self, _):
        if not self.plan:
            wx.MessageBox('Stage an operation to export its before/after review.', 'Variant Manager', parent=self)
            return
        with wx.FileDialog(self, 'Export review', wildcard='HTML report (*.html)|*.html|JSON review (*.json)|*.json|CSV changes (*.csv)|*.csv', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        if path.suffix.lower() not in ('.html', '.json', '.csv') or path.resolve() in {
                (self.plan.context.home / relative).resolve() for relative in self.plan.expected}:
            wx.MessageBox('Choose an HTML, JSON or CSV output that is separate from the source project.', 'Export review', parent=self)
            return
        data = S.review(self.plan)
        rows = data['rows']
        labels = {o['key']: o['label'] for o in self.inventory['objects']}
        if path.suffix.lower() == '.csv':
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['Instance', 'Variant', 'Before', 'After'])
                writer.writerows((labels.get(r['key'], r['key']), r['variant'], state_text(r['before']), state_text(r['after'])) for r in rows)
        elif path.suffix.lower() == '.html':
            body = ''.join('<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in (labels.get(r['key'], r['key']), r['variant'], state_text(r['before']), state_text(r['after']))) + '</tr>' for r in rows)
            path.write_text('<!doctype html><meta charset="utf-8"><title>WayriCAD Variant review</title><style>body{font:16px system-ui;margin:3em;background:#f5f8fa;color:#203746}table{border-collapse:collapse;width:100%}td,th{border:1px solid #cbd9df;padding:.6em;text-align:left}pre{white-space:pre-wrap}</style><h1>WayriCAD Variant review</h1><p>Saved-state preview. Geometry and connectivity are not modified; PCB synchronization is separate.</p><table><tr><th>Instance</th><th>Variant</th><th>Before</th><th>After</th></tr>' + body + '</table><h2>File diff</h2><pre>' + html.escape(data['diff']) + '</pre>', encoding='utf-8')
        else:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        self.SetStatusText('Review exported.')

    def help(self, _):
        dialog = wx.Dialog(self, title='Variant Manager help', size=(860, 680))
        window = wx.html.HtmlWindow(dialog)
        window.LoadPage(str(Path(__file__).parents[1] / 'help.html'))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(window, 1, wx.EXPAND)
        sizer.Add(dialog.CreateButtonSizer(wx.CLOSE), 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dialog.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()


def launch(project='', note=''):
    import os
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('WayriCAD.VariantManager')
    app = wx.App(False)
    frame = VariantFrame(project, note)
    frame.Show()
    app.MainLoop()
