"""Native review window for linked source updates to an existing project."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from types import ModuleType

import wx

if __package__ in (None, ''):
    __package__ = '_fusion_linked_standalone'
    package = ModuleType(__package__)
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[__package__] = package

from .model import MergeError


STATUS_COLOURS = {
    'up-to-date': '#2b8a3e', 'current': '#2b8a3e', 'changed': '#b26a00',
    'missing': '#b02a37', 'missing_source': '#b02a37', 'conflict': '#9c36b5',
    'unknown': '#68737d',
}


class LinkDiagram(wx.ScrolledWindow):
    """Selectable target → wrapper → subsheet → symbol relationship map."""
    def __init__(self, parent, on_select):
        super().__init__(parent, style=wx.BORDER_SUNKEN)
        self.on_select = on_select
        self.nodes = []
        self.hitboxes = []
        self.selected = None
        self.SetScrollRate(10, 10)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_click)

    def show_links(self, target_label, links, selected=None):
        self.selected = selected
        self.nodes = []
        y = 28
        for link in links:
            key = str(link.get('link_id', link.get('id', link.get('alias', ''))))
            alias = str(link.get('alias', link.get('source_alias', key)))
            status = str(link.get('status', 'unknown'))
            self.nodes.append((key, alias, status, y, link))
            y += 86
        self.target_label = target_label
        self.SetVirtualSize((900, max(190, y + 20)))
        self.Refresh()

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        self.PrepareDC(dc)
        background = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        foreground = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        dc.SetBackground(wx.Brush(background)); dc.Clear()
        dc.SetTextForeground(foreground)
        self.hitboxes = []
        target = (18, 28, 160, max(62, len(self.nodes) * 86 - 12))
        self.draw_box(dc, target, self.target_label or 'Target', foreground, selected=False)
        for key, alias, status, y, link in self.nodes:
            colour = wx.Colour(STATUS_COLOURS.get(status, STATUS_COLOURS['unknown']))
            wrapper = (245, y, 175, 58)
            subsheet = (490, y, 155, 58)
            symbol = (715, y, 155, 58)
            mid = y + 29
            dc.SetPen(wx.Pen(colour, 2))
            dc.DrawLine(178, mid, 245, mid)
            dc.DrawLine(420, mid, 490, mid)
            dc.DrawLine(645, mid, 715, mid)
            self.draw_box(dc, wrapper, alias+'  ['+status+']', colour, key == self.selected)
            hierarchy = link.get('hierarchy', [])
            first_sheet = hierarchy[0] if isinstance(hierarchy, list) and hierarchy else {}
            first_symbol = next((symbols[0] for sheet in hierarchy if isinstance(sheet, dict)
                                 for symbols in [sheet.get('symbols', [])] if isinstance(symbols, list) and symbols), None)
            sheet_label = (alias+' sheets' if first_sheet else f"Subsheets: {link.get('sheet_count', '?')}")
            if isinstance(first_symbol, dict):
                source_ref = str(first_symbol.get('reference', first_symbol.get('identity', 'Symbol')))
                target_ref = link.get('reference_map', {}).get(source_ref)
                symbol_label = source_ref+(' → '+str(target_ref) if target_ref and target_ref != source_ref else '')
            else:
                symbol_label = f"Symbols: {link.get('component_count', link.get('symbol_count', '?'))}"
            self.draw_box(dc, subsheet, sheet_label, colour, key == self.selected)
            self.draw_box(dc, symbol, symbol_label, colour, key == self.selected)
            self.hitboxes.extend((box, key) for box in (wrapper, subsheet, symbol))

    def draw_box(self, dc, box, label, colour, selected):
        x, y, w, h = box
        dc.SetPen(wx.Pen(colour, 3 if selected else 1))
        dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)))
        dc.DrawRoundedRectangle(x, y, w, h, 7)
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        dc.SetClippingRegion(x + 6, y + 5, w - 12, h - 10)
        dc.DrawText(label, x + 8, y + 12)
        dc.DestroyClippingRegion()

    def on_click(self, event):
        x, y = self.CalcUnscrolledPosition(event.GetPosition())
        for (bx, by, width, height), key in self.hitboxes:
            if bx <= x <= bx + width and by <= y <= by + height:
                self.on_select(key)
                break
        event.Skip()


class LinkedUpdatesDialog(wx.Dialog):
    def __init__(self, parent=None, target_path='', cli_path='', embedded=False):
        super().__init__(parent, title='Wayri Project Fusion — linked source updates',
                         size=(1120, 850), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cli_path = cli_path
        self.embedded = embedded
        self.scan_data = None
        self.links = []
        self.selected_link_id = None
        self.link_tree_items = {}
        self.source_overrides = {}
        self.identity_overrides = {}
        self.deferred_changes = set()
        self.change_rows = []
        self.pending_adoption_ids = []
        self.plan = self.plan_file = self.applied = None
        self.busy = False
        self._suspend = False
        self._watching = False
        self._watch_inflight = False
        self.build(target_path)
        self.CentreOnParent()

    def build(self, target_path):
        root = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label='Review links from new combined merges and existing-project imports. Earlier 0.6 merges are not automatically linked. Mixed-stack or preserved-outline links may require a full rebuild. Ctrl-select links in Overview. Scans and proposals never apply changes; Preview creates a separate candidate. Apply happens offline after closing KiCad editors.')
        intro.Wrap(1040)
        root.Add(intro, 0, wx.ALL | wx.EXPAND, 12)
        target_row = wx.BoxSizer(wx.HORIZONTAL)
        target_row.Add(wx.StaticText(self, label='Existing target'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.target = wx.FilePickerCtrl(self, path=target_path,
            message='Choose the linked target project',
            wildcard='KiCad projects (*.kicad_pro)|*.kicad_pro|Root schematics (*.kicad_sch)|*.kicad_sch|PCBs (*.kicad_pcb)|*.kicad_pcb',
            style=wx.FLP_OPEN | wx.FLP_USE_TEXTCTRL)
        self.target.Bind(wx.EVT_FILEPICKER_CHANGED, self.invalidate)
        target_row.Add(self.target, 1, wx.EXPAND)
        root.Add(target_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        candidate_row = wx.BoxSizer(wx.HORIZONTAL)
        candidate_row.Add(wx.StaticText(self, label='Review candidate parent'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        initial_parent = str(Path(target_path).resolve().parent.parent) if target_path else str(Path.home())
        self.candidate_parent = wx.DirPickerCtrl(self, path=initial_parent,
            message='Choose parent for a NEW linked-update candidate')
        self.candidate_parent.Bind(wx.EVT_DIRPICKER_CHANGED, self.invalidate_plan)
        candidate_row.Add(self.candidate_parent, 1, wx.EXPAND | wx.RIGHT, 8)
        candidate_row.Add(wx.StaticText(self, label='Folder'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.candidate_name = wx.TextCtrl(self, value=(Path(target_path).stem or 'Target')+'-LinkedReview', size=(180, -1))
        self.candidate_name.Bind(wx.EVT_TEXT, self.invalidate_plan)
        candidate_row.Add(self.candidate_name, 0)
        root.Add(candidate_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.scan_button = wx.Button(self, label='Scan all links')
        self.update_button = wx.Button(self, label='Preview selected updates…')
        self.relocate_button = wx.Button(self, label='Relocate source…')
        self.search_button = wx.Button(self, label='Search source folder…')
        self.autolink_button = wx.Button(self, label='Propose auto-links…')
        self.watch = wx.CheckBox(self, label='Watch saved sources')
        self.scan_button.Bind(wx.EVT_BUTTON, self.scan_all)
        self.update_button.Bind(wx.EVT_BUTTON, self.preview_selected)
        self.relocate_button.Bind(wx.EVT_BUTTON, self.relocate_source)
        self.search_button.Bind(wx.EVT_BUTTON, self.search_sources)
        self.autolink_button.Bind(wx.EVT_BUTTON, self.auto_link)
        self.watch.Bind(wx.EVT_CHECKBOX, self.toggle_watch)
        for button in (self.scan_button, self.update_button, self.relocate_button,
                       self.search_button, self.autolink_button, self.watch):
            controls.Add(button, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 8)
        root.Add(controls, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.retain_layout = wx.CheckBox(
            self, label='Keep current target footprint positions and routing during linked update')
        self.retain_layout.SetToolTip(
            'Inherit saved schematic and compatible footprint changes while keeping the placed '
            'target PCB geometry. Pad, connection and native DRC checks can stop an unsafe update.')
        self.retain_layout.Bind(wx.EVT_CHECKBOX, self.invalidate_plan)
        root.Add(self.retain_layout, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        link_actions = wx.BoxSizer(wx.HORIZONTAL)
        self.break_selected_button = wx.Button(self, label='Preview break selected links…')
        self.break_all_button = wx.Button(self, label='Preview break all links…')
        self.undo_button = wx.Button(self, label='Preview backed-up undo / redo…')
        self.break_selected_button.Bind(wx.EVT_BUTTON, self.preview_break_selected)
        self.break_all_button.Bind(wx.EVT_BUTTON, self.preview_break_all)
        self.undo_button.Bind(wx.EVT_BUTTON, self.preview_undo_last)
        for button in (self.break_selected_button, self.break_all_button, self.undo_button):
            link_actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(link_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.notebook = wx.Notebook(self)
        self.build_overview()
        self.build_changes()
        self.build_validation()
        root.Add(self.notebook, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.status = wx.StaticText(self, label='Scan the saved target to discover linked imports.')
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.major_ack = wx.CheckBox(self, label='I reviewed the major changes and want them included in this update.')
        self.major_ack.Bind(wx.EVT_CHECKBOX, self.on_acknowledge)
        self.closed_ack = wx.CheckBox(self, label='I saved and closed the target and any open source editors before offline Apply.')
        self.closed_ack.Bind(wx.EVT_CHECKBOX, self.on_acknowledge)
        if self.embedded:
            self.closed_ack.Disable()
        root.Add(self.major_ack, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        root.Add(self.closed_ack, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.load_button = wx.Button(self, label='Load reviewed update plan…')
        self.save_button = wx.Button(self, label='Save plan…')
        self.candidate_button = wx.Button(self, label='Show candidate')
        self.standalone_button = wx.Button(self, label='Open standalone Apply window')
        self.apply_button = wx.Button(self, label='Apply reviewed updates…')
        close = wx.Button(self, wx.ID_CANCEL, 'Close')
        self.load_button.Bind(wx.EVT_BUTTON, self.load_plan_dialog)
        self.save_button.Bind(wx.EVT_BUTTON, self.save_plan_dialog)
        self.candidate_button.Bind(wx.EVT_BUTTON, self.show_candidate)
        self.standalone_button.Bind(wx.EVT_BUTTON, self.open_standalone)
        self.apply_button.Bind(wx.EVT_BUTTON, self.apply_updates)
        close.Bind(wx.EVT_BUTTON, self.close)
        self.Bind(wx.EVT_CLOSE, self.close)
        for button in (self.load_button, self.save_button, self.candidate_button,
                       self.standalone_button, self.apply_button, close):
            actions.Add(button, 0, wx.RIGHT, 8)
        root.Add(actions, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(root)
        self.update_button.Disable(); self.relocate_button.Disable(); self.search_button.Disable(); self.autolink_button.Disable()
        self.break_selected_button.Disable(); self.break_all_button.Disable()
        if not target_path: self.undo_button.Disable()
        self.save_button.Disable(); self.candidate_button.Disable(); self.standalone_button.Disable(); self.apply_button.Disable()
        self.major_ack.Hide()
        if not self.embedded:
            self.standalone_button.Hide()
        self.watch_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_watch_tick, self.watch_timer)

    def build_overview(self):
        page = wx.Panel(self.notebook)
        box = wx.BoxSizer(wx.VERTICAL)
        summary = wx.BoxSizer(wx.HORIZONTAL)
        self.summary = wx.StaticText(page, label='No linked sources scanned.')
        summary.Add(self.summary, 1, wx.EXPAND)
        box.Add(summary, 0, wx.ALL | wx.EXPAND, 8)
        split = wx.SplitterWindow(page, style=wx.SP_LIVE_UPDATE)
        self.tree = wx.TreeCtrl(split, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_DEFAULT_STYLE | wx.TR_MULTIPLE)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_selection)
        self.diagram = LinkDiagram(split, self.select_link)
        split.SplitVertically(self.tree, self.diagram, 420)
        split.SetMinimumPaneSize(250)
        box.Add(split, 1, wx.ALL | wx.EXPAND, 8)
        page.SetSizer(box)
        self.notebook.AddPage(page, 'Overview')

    def build_changes(self):
        page = wx.Panel(self.notebook)
        box = wx.BoxSizer(wx.VERTICAL)
        self.changes = wx.ListCtrl(page, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        for index, (name, width) in enumerate((('Severity', 95), ('Category', 120), ('Component', 130),
                                               ('Pin', 85), ('Before', 270), ('After', 270), ('Review', 115))):
            self.changes.InsertColumn(index, name, width=width)
        box.Add(self.changes, 2, wx.ALL | wx.EXPAND, 8)
        self.changes.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_change_selected)
        self.change_advice = wx.TextCtrl(page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP,
                                         size=(-1, 74))
        self.defer_change_button = wx.Button(page, label='Ignore for now / restore')
        self.defer_change_button.Bind(wx.EVT_BUTTON, self.toggle_deferred_change)
        box.Add(self.change_advice, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)
        box.Add(self.defer_change_button, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.defer_change_button.Disable()
        compare = wx.BoxSizer(wx.HORIZONTAL)
        self.source_summary = wx.TextCtrl(page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        self.target_summary = wx.TextCtrl(page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        compare.Add(self.source_summary, 1, wx.RIGHT | wx.EXPAND, 8)
        compare.Add(self.target_summary, 1, wx.EXPAND)
        box.Add(compare, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        page.SetSizer(box)
        self.notebook.AddPage(page, 'Change Review')

    def build_validation(self):
        page = wx.Panel(self.notebook)
        box = wx.BoxSizer(wx.VERTICAL)
        self.validation = wx.TextCtrl(page, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        box.Add(self.validation, 1, wx.ALL | wx.EXPAND, 8)
        page.SetSizer(box)
        self.notebook.AddPage(page, 'Validation')

    @staticmethod
    def link_key(link):
        return str(link.get('id', link.get('link_id', link.get('alias', ''))))

    @staticmethod
    def major_count(value):
        if isinstance(value, (list, tuple)):
            return len(value)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def hierarchy_rows(link):
        rows = link.get('hierarchy', link.get('sheets', []))
        if not isinstance(rows, list): return []
        flattened = []
        def visit(row):
            if not isinstance(row, dict): return
            flattened.append(row)
            for child in row.get('children', []): visit(child)
        for row in rows: visit(row)
        return flattened

    def refresh_update_available(self):
        selected = set(self.selected_link_ids())
        unsupported = any(self.link_key(link) in selected and link.get('update_unsupported_reason')
                          for link in self.links)
        self.update_button.Enable(self.scan_data is not None and not self.busy and not unsupported)

    def invalidate_plan(self, event=None):
        if not self._suspend:
            self.plan = self.plan_file = None
            self.applied = None
            self.major_ack.SetValue(False); self.closed_ack.SetValue(False)
            self.save_button.Disable(); self.candidate_button.Disable()
            self.standalone_button.Disable(); self.apply_button.Disable()
            self.validation.SetValue('Inputs changed. Preview selected updates again.')
        if event is not None: event.Skip()

    def invalidate(self, event=None):
        if not self._suspend:
            self.invalidate_plan()
            self.scan_data = None; self.links = []; self.selected_link_id = None
            self.link_tree_items = {}
            self.source_overrides.clear()
            self.identity_overrides.clear()
            self.deferred_changes.clear()
            self.pending_adoption_ids = []
            self.tree.DeleteAllItems()
            self.diagram.show_links('', [])
            self.changes.DeleteAllItems()
            self.source_summary.Clear(); self.target_summary.Clear()
            self.summary.SetLabel('Scan the selected saved target.')
            self.update_button.Disable(); self.relocate_button.Disable(); self.search_button.Disable(); self.autolink_button.Disable()
            self.break_selected_button.Disable(); self.break_all_button.Disable()
            self.undo_button.Enable(bool(self.target.GetPath()))
            self.status.SetLabel('Target changed. Scan linked sources again.')
        if event is not None: event.Skip()

    def run(self, action, done, status, quiet=False):
        if self.busy:
            return
        self.busy = True
        self.status.SetLabel(status)
        for control in (self.target, self.candidate_parent, self.candidate_name,
                        self.scan_button, self.update_button, self.relocate_button,
                        self.search_button, self.autolink_button, self.break_selected_button,
                        self.break_all_button, self.undo_button, self.watch, self.major_ack, self.closed_ack,
                        self.load_button, self.save_button, self.candidate_button,
                        self.standalone_button, self.apply_button, self.tree, self.diagram):
            control.Disable()
        def worker():
            try:
                result = action()
                wx.CallAfter(self.finish, done, result, None, quiet)
            except Exception as exc:
                wx.CallAfter(self.finish, done, None, str(exc), quiet)
        threading.Thread(target=worker, name='FusionLinkedReview', daemon=True).start()

    def finish(self, done, result, error, quiet):
        self.busy = False
        for control in (self.target, self.candidate_parent, self.candidate_name,
                        self.scan_button, self.watch, self.load_button, self.tree, self.diagram):
            control.Enable()
        self.undo_button.Enable(bool(self.target.GetPath()))
        self.major_ack.Enable()
        if not self.embedded: self.closed_ack.Enable()
        if self.scan_data is not None:
            self.refresh_update_available(); self.relocate_button.Enable(); self.search_button.Enable(); self.autolink_button.Enable()
            self.break_selected_button.Enable(bool(self.links)); self.break_all_button.Enable(bool(self.links))
        if self.plan is not None:
            self.save_button.Enable(); self.candidate_button.Enable()
            if self.embedded: self.standalone_button.Enable()
            self.on_acknowledge()
        if error:
            self.status.SetLabel(error)
            if not quiet:
                wx.MessageBox(error, 'Linked update stopped', wx.OK | wx.ICON_ERROR, self)
            return
        done(result)

    def scan_all(self, event=None, search_roots=None, quiet=False):
        if self.busy:
            return
        target = self.target.GetPath()
        if not target:
            if not quiet: wx.MessageBox('Choose the existing saved target project.', 'Linked sources', wx.OK | wx.ICON_WARNING, self)
            return
        from .linked_updates import scan_links
        if not quiet: self.invalidate_plan()
        overrides = dict(self.source_overrides)
        self.run(lambda: scan_links(target, cli_path=self.cli_path, search_roots=search_roots,
                                    source_overrides=overrides),
                 self.show_watch_scan if quiet else self.show_scan,
                 'Checking saved source links…', quiet=quiet)

    def show_watch_scan(self, data):
        previous = [(self.link_key(link), link.get('status'), link.get('changes')) for link in self.links]
        current = [(self.link_key(link), link.get('status'), link.get('changes')) for link in data.get('links', [])]
        if current != previous:
            self.invalidate_plan()
            self.show_scan(data)
            self.status.SetLabel('Saved linked sources changed. Review the updated scan before previewing.')
        else:
            self.status.SetLabel('Watching saved sources. No changes detected.')

    def show_scan(self, data):
        self.scan_data = data
        self.links = list(data.get('links', []))
        self.identity_overrides.clear()
        self.deferred_changes.clear()
        self.pending_adoption_ids = []
        target = self.target.GetPath()
        self.tree.DeleteAllItems()
        self.link_tree_items = {}
        root = self.tree.AddRoot(Path(target).stem or 'Target')
        self.tree.SetItemData(root, None)
        symbol_budget = 5000
        for link in self.links:
            key = self.link_key(link)
            alias = str(link.get('alias', key))
            status = str(link.get('status', 'unknown'))
            changes = link.get('changes', [])
            if not isinstance(changes, list): changes = []
            major = self.major_count(link.get('major_changes', 0)) or sum(
                item.get('severity') == 'major' for item in changes if isinstance(item, dict))
            unsupported = bool(link.get('update_unsupported_reason'))
            wrapper = self.tree.AppendItem(root, f'{alias} — {status}' + (f'  ! {major} major' if major else '')
                                           + ('  ! full rebuild required' if unsupported else ''))
            self.tree.SetItemData(wrapper, key)
            self.link_tree_items[key] = wrapper
            hierarchy = self.hierarchy_rows(link)
            if hierarchy:
                branches = {}
                for sheet in sorted(hierarchy, key=lambda row: (str(row.get('sheet_path', row.get('path', ''))).count('/'),
                                                          str(row.get('sheet_path', row.get('path', ''))))):
                    path = str(sheet.get('sheet_path', sheet.get('path', '')))
                    parent_path = path.rsplit('/', 1)[0]
                    parent = branches.get(parent_path, wrapper)
                    display_path = str(sheet.get('display_path', sheet.get('name', path or 'Subsheet')))
                    label = alias if parent == wrapper else (display_path.strip('/').split('/')[-1] or 'Subsheet')
                    symbols = sheet.get('symbols', [])
                    count = len(symbols) if isinstance(symbols, list) else sheet.get('symbol_count', symbols)
                    branch = self.tree.AppendItem(parent, f'{label} — {count} symbols')
                    self.tree.SetItemData(branch, key)
                    if path: branches[path] = branch
                    if isinstance(symbols, list):
                        for index, symbol in enumerate(symbols):
                            if symbol_budget <= 0:
                                self.tree.AppendItem(branch, f'{len(symbols)-index} more symbols; inspect the source and change details.')
                                break
                            if not isinstance(symbol, dict): continue
                            reference = str(symbol.get('reference', symbol.get('identity', 'Symbol')))
                            target_ref = link.get('reference_map', {}).get(reference)
                            shown_reference = reference+(' → '+str(target_ref) if target_ref and target_ref != reference else '')
                            value = str(symbol.get('value', ''))
                            identity = str(symbol.get('identity', ''))
                            affected = [item for item in changes if isinstance(item, dict)
                                        and item.get('severity') == 'major'
                                        and (str(item.get('identity', '')) == identity or item.get('reference') == reference)]
                            pin_labels = sorted({str(item['pin']) for item in affected if item.get('pin')})
                            badge = ('  ! major'+(' pin '+','.join(pin_labels) if pin_labels else '')) if affected else ''
                            node = self.tree.AppendItem(branch, shown_reference + ('  '+value if value else '') + badge)
                            self.tree.SetItemData(node, key)
                            symbol_budget -= 1
            else:
                branch = self.tree.AppendItem(wrapper, f"Subsheets: {link.get('sheet_count', '?')}")
                self.tree.SetItemData(branch, key)
                node = self.tree.AppendItem(branch, f"Symbols: {link.get('component_count', link.get('symbol_count', '?'))}")
                self.tree.SetItemData(node, key)
        self.tree.Expand(root)
        self.diagram.show_links(Path(target).stem, self.links)
        counts = {}
        for link in self.links:
            status = str(link.get('status', 'unknown'))
            counts[status] = counts.get(status, 0) + 1
        count_text = ', '.join(f'{value} {status}' for status, value in sorted(counts.items())) or 'no linked sources'
        legacy = data.get('legacy_candidates', [])
        manual = sum(len([proposal for proposal in link.get('auto_link_proposals', [])
                          if not proposal.get('automatic')]) for link in self.links)
        self.summary.SetLabel(f'{len(self.links)} linked imports: {count_text}. '
                              f'{manual} identity proposal(s); {len(legacy)} legacy proposal(s).')
        unsupported_rows = [{'alias':link.get('alias', self.link_key(link)),
                             'update_unsupported_reason':link['update_unsupported_reason']}
                            for link in self.links if link.get('update_unsupported_reason')]
        validation = {'scan_report':data.get('report', {}), 'updates_requiring_full_rebuild':unsupported_rows}
        self.validation.SetValue(json.dumps(validation, indent=2, default=str))
        self.selected_link_id = None
        self.show_change_rows([])
        self.major_ack.Hide(); self.major_ack.SetValue(False); self.Layout()
        self.refresh_update_available(); self.relocate_button.Enable(); self.search_button.Enable(); self.autolink_button.Enable()
        self.break_selected_button.Enable(bool(self.links)); self.break_all_button.Enable(bool(self.links))
        self.undo_button.Enable(bool(self.target.GetPath()))
        self.status.SetLabel('Scan complete. Select a link to inspect changes and preview an update.')

    def on_tree_selection(self, event):
        item = event.GetItem()
        if item.IsOk():
            key = self.tree.GetItemData(item)
            if key is not None:
                self.select_link(str(key))
        event.Skip()

    def select_link(self, key):
        self.selected_link_id = key
        selected = [str(self.tree.GetItemData(item)) for item in self.tree.GetSelections()
                    if self.tree.GetItemData(item) is not None]
        if key not in selected and key in self.link_tree_items:
            self.tree.UnselectAll()
            self.tree.SelectItem(self.link_tree_items[key])
        link = next((item for item in self.links if self.link_key(item) == key), None)
        if link is None:
            return
        self.diagram.show_links(Path(self.target.GetPath()).stem, self.links, selected=key)
        changes = link.get('changes', [])
        self.show_change_rows(changes if isinstance(changes, list) else [], link.get('conflicts', []))
        candidates = link.get('source_candidates', [])
        source_lines = ['SOURCE', 'Alias: '+str(link.get('alias', '')),
                        'Saved project: '+str(link.get('source_project', '')),
                        'Variant: '+str(link.get('selected_variant', '')),
                        'Status: '+str(link.get('status', '')),
                        'Sheets: '+str(link.get('sheet_count', '?')),
                        'Components: '+str(link.get('component_count', '?'))]
        if link.get('error'): source_lines.append('Read error: '+str(link['error']))
        if candidates:
            source_lines.append('\nExact UUID source candidates:')
            source_lines.extend('  '+str(item.get('project', item)) for item in candidates)
        proposals = link.get('auto_link_proposals', [])
        if proposals:
            source_lines.append('\nLink proposals: '+str(len(proposals))+' (UUID matches are automatic; other matches need review)')
        if link.get('update_unsupported_reason'):
            source_lines.append('\nIncremental update unavailable; rebuild a complete combined candidate: '
                                +str(link['update_unsupported_reason']))
        reference_map = link.get('reference_map', {})
        if reference_map:
            source_lines.append('\nSource → target references:')
            source_lines.extend('  '+str(source)+' → '+str(target) for source,target in sorted(reference_map.items()))
        destination_lines = ['DESTINATION', 'Target project: '+self.target.GetPath(),
                             'Import wrapper UUID: '+str(link.get('wrapper_uuid', '')),
                             'Tracked sheets: '+str(link.get('sheet_count', '?')),
                             'Tracked components: '+str(link.get('component_count', '?')),
                             'Local conflicts: '+str(len(link.get('conflicts', [])))]
        self.source_summary.SetValue('\n'.join(source_lines))
        self.target_summary.SetValue('\n'.join(destination_lines))
        major = self.major_count(link.get('major_changes', 0)) or sum(change.get('severity') == 'major' for change in changes)
        self.major_ack.Show(major > 0)
        self.major_ack.SetValue(False)
        self.Layout()
        self.notebook.SetSelection(1)
        self.refresh_update_available()
        self.on_acknowledge()

    @staticmethod
    def change_key(link_id, change):
        return (str(link_id), str(change.get('category','')), str(change.get('identity','')),
                str(change.get('pin','')), json.dumps([change.get('before'),change.get('after')],
                                                   sort_keys=True, default=str))

    def show_change_rows(self, changes, conflicts=()):
        self.changes.DeleteAllItems()
        self.change_rows=[]
        self.change_advice.Clear()
        self.defer_change_button.Disable()
        for change in [*changes,*[dict(item,severity='blocked',identity=item.get('uuid',''),
                                      before='',after='',conflict=True) for item in conflicts]]:
            if not isinstance(change, dict): continue
            link_id = change.get('link_id', self.selected_link_id)
            link = next((item for item in self.links if self.link_key(item) == link_id), None)
            source_ref = change.get('reference', change.get('identity', ''))
            target_ref = (link or {}).get('reference_map', {}).get(source_ref)
            component = str(source_ref)+(' → '+str(target_ref) if target_ref and target_ref != source_ref else '')
            fields = [change.get('severity', ''), change.get('category', ''),
                      component,
                      change.get('pin', ''), change.get('before_display', change.get('before', '')),
                      change.get('after_display', change.get('after', '')),
                      'Deferred' if self.change_key(link_id,change) in self.deferred_changes else
                      ('Must resolve' if change.get('conflict') else 'Review')]
            fields = [json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                      for value in fields]
            row = self.changes.InsertItem(self.changes.GetItemCount(), fields[0])
            for column, value in enumerate(fields[1:], 1):
                self.changes.SetItem(row, column, value)
            self.change_rows.append((link_id,change))

    def on_change_selected(self, event):
        index=event.GetIndex()
        if index>=len(self.change_rows):return
        _,change=self.change_rows[index]
        advice=change.get('suggestion') or change.get('message') or 'Review this change.'
        if change.get('conflict'):
            advice+='\n\nThis destination conflict cannot be ignored during update.'
        else:
            advice+='\n\nIgnoring this row defers the entire linked design update until restored.'
        self.change_advice.SetValue(advice)
        self.defer_change_button.Enable(not change.get('conflict') and not self.busy)

    def toggle_deferred_change(self, event):
        index=self.changes.GetFirstSelected()
        if index<0 or index>=len(self.change_rows):return
        link_id,change=self.change_rows[index]
        if change.get('conflict'):return
        key=self.change_key(link_id,change)
        if key in self.deferred_changes:self.deferred_changes.remove(key)
        else:self.deferred_changes.add(key)
        self.changes.SetItem(index,6,'Deferred' if key in self.deferred_changes else 'Review')
        self.invalidate_plan()
        self.status.SetLabel('Ignored source changes defer their whole linked update; restore them before preview.')

    def selected_link_ids(self):
        keys = []
        selections = self.tree.GetSelections()
        for item in selections:
            key = self.tree.GetItemData(item)
            if key is not None and str(key) not in keys: keys.append(str(key))
        if not selections and self.selected_link_id is not None:
            keys.append(self.selected_link_id)
        return keys

    def on_acknowledge(self, event=None):
        needs_major = self.major_ack.IsShown()
        enabled = (self.plan is not None and not self.busy and not self.embedded
                   and self.closed_ack.GetValue() and (not needs_major or self.major_ack.GetValue())
                   and self.applied is None)
        self.apply_button.Enable(enabled)
        if event is not None: event.Skip()

    def toggle_watch(self, event):
        self._watching = self.watch.GetValue()
        if self._watching:
            self.watch_timer.Start(30000)
            self.status.SetLabel('Watching saved source files every 30 seconds; scans are read-only.')
        else:
            self.watch_timer.Stop()
            self.status.SetLabel('Source watch stopped.')
        event.Skip()

    def on_watch_tick(self, event):
        if self._watching and not self.busy and self.target.GetPath():
            self.scan_all(quiet=True)

    def relocate_source(self, event):
        keys = self.selected_link_ids()
        if len(keys) != 1:
            wx.MessageBox('Select exactly one linked import to relocate.', 'Source relocation', wx.OK | wx.ICON_INFORMATION, self)
            return
        link = next((item for item in self.links if self.link_key(item) == keys[0]), {})
        candidates = link.get('source_candidates', [])
        path = None
        if candidates:
            labels = [str(item['project'])+' — '+str(item.get('method', 'Exact UUID')) for item in candidates]
            labels.append('Browse another saved project…')
            with wx.SingleChoiceDialog(self, 'Choose an exact owning-UUID candidate or browse another path.',
                                       'Relocate linked source', labels) as choice:
                if choice.ShowModal() != wx.ID_OK: return
                index = choice.GetSelection()
            if index < len(candidates): path = candidates[index]['project']
        if path is None:
            with wx.FileDialog(self, 'Locate the original linked source project',
                               wildcard='KiCad projects (*.kicad_pro)|*.kicad_pro|Root schematics (*.kicad_sch)|*.kicad_sch',
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal() != wx.ID_OK: return
                path = dialog.GetPath()
        path = str(Path(path).with_suffix('.kicad_pro').resolve())
        self.source_overrides[keys[0]] = path
        self.invalidate_plan()
        self.scan_all(search_roots=[str(Path(path).parent)])
        self.status.SetLabel('Checking relocated source by exact owning UUID before preview…')

    def search_sources(self, event):
        if not self.target.GetPath(): return
        with wx.DirDialog(self, 'Search a folder for exact owning-UUID source matches') as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            folder = dialog.GetPath()
        self.scan_all(search_roots=[folder])

    def auto_link(self, event):
        if self.scan_data is None: return
        keys = self.selected_link_ids()
        if len(keys) == 1:
            link = next((item for item in self.links if self.link_key(item) == keys[0]), None)
            if link is not None and any(not item.get('automatic') for item in link.get('auto_link_proposals', [])):
                self.review_identity_proposals(link)
                return
        self.review_legacy_proposals(self.scan_data.get('legacy_candidates', []))

    def review_identity_proposals(self, link):
        key = self.link_key(link)
        choices = {}
        for proposal in link.get('auto_link_proposals', []):
            if proposal.get('automatic'): continue
            before = str(proposal.get('before', ''))
            candidates = ([proposal['after']] if proposal.get('after') else proposal.get('candidates', []))
            if not before or not candidates: continue
            labels = [str(candidate)+' — '+str(proposal.get('method', 'reviewed identity'))
                      for candidate in candidates]
            with wx.SingleChoiceDialog(self, 'Choose the exact new occurrence for\n'+before+
                                       '\n\nCancel skips this proposal; no change is applied during review.',
                                       'Review symbol link proposal', labels) as dialog:
                if dialog.ShowModal() != wx.ID_OK: continue
                selected = dialog.GetSelection()
            choices[before] = str(candidates[selected])
        if not choices:
            self.status.SetLabel('No manual identity bindings selected. Exact unchanged UUID paths remain automatic.')
            return
        self.identity_overrides[key] = choices
        self.pending_adoption_ids = []
        self.invalidate_plan()
        self.status.SetLabel(f'{len(choices)} explicit identity binding(s) selected for {link.get("alias", key)}. Preview selected updates to validate them.')

    def review_legacy_proposals(self, proposals):
        verified = [item for item in proposals if item.get('status') == 'verified_legacy' or item.get('verified') is True]
        if not verified:
            self.status.SetLabel('No proven legacy import can be adopted. Unverified suggestions remain in Validation.')
            self.validation.SetValue(json.dumps({'legacy_candidates': proposals}, indent=2, default=str))
            self.notebook.SetSelection(2)
            return
        labels = [f"{item.get('alias', item.get('id', 'Legacy import'))} — {item.get('method', 'exact provenance')} — {item.get('source_project', '')}"
                  for item in verified]
        with wx.MultiChoiceDialog(self, 'Select provenance-backed legacy imports for a reviewed adoption candidate.',
                                  'Legacy link proposals', labels) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            selected = dialog.GetSelections()
        self.pending_adoption_ids = [str(verified[index]['id']) for index in selected]
        self.invalidate_plan()
        if self.pending_adoption_ids:
            self.status.SetLabel(f'{len(self.pending_adoption_ids)} exact legacy proposal(s) selected. Preview selected updates to review adoption.')

    def candidate_directory(self):
        parent = Path(self.candidate_parent.GetPath())
        name = self.candidate_name.GetValue().strip()
        if not parent.is_dir():
            raise MergeError('Choose an existing review candidate parent folder.')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name):
            raise MergeError('Candidate folder name must start with a letter and use at most 64 letters, digits, underscores or hyphens.')
        root = parent / name
        candidate = root
        number = 2
        while candidate.exists() or candidate.with_name(candidate.name+'-linked-plan.json').exists():
            candidate = root.with_name(f'{name}-{number}')
            number += 1
        return candidate

    def preview_break_selected(self, event):
        ids = self.selected_link_ids()
        if not ids:
            wx.MessageBox('Select one or more import wrappers in Overview to break their update links.',
                          'Break selected links', wx.OK | wx.ICON_WARNING, self)
            return
        self.preview_break(ids)

    def preview_break_all(self, event):
        ids = [self.link_key(link) for link in self.links]
        if not ids:
            wx.MessageBox('Scan the saved target to find its linked imports first.',
                          'Break all links', wx.OK | wx.ICON_WARNING, self)
            return
        self.preview_break(ids)

    def preview_break(self, ids):
        if self.busy: return
        try:
            candidate = self.candidate_directory()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Check candidate location', wx.OK | wx.ICON_WARNING, self)
            return
        from .linked_updates import preview_break_links
        target = self.target.GetPath()
        self.invalidate_plan()
        self.run(lambda: preview_break_links(target, ids, candidate, cli_path=self.cli_path),
                 self.show_preview,
                 f'Creating a reviewed candidate to break {len(ids)} link(s) while retaining local design files…')

    def preview_undo_last(self, event):
        if self.busy: return
        target = self.target.GetPath()
        if not target:
            wx.MessageBox('Choose the saved target project whose last Apply should be undone.',
                          'Undo last Apply', wx.OK | wx.ICON_WARNING, self)
            return
        try:
            candidate = self.candidate_directory()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Check candidate location', wx.OK | wx.ICON_WARNING, self)
            return
        from .linked_updates import list_transactions
        self.invalidate_plan()
        def choose(transactions):
            self.validation.SetValue(json.dumps({'backup_history': transactions}, indent=2, default=str))
            if not transactions:
                self.status.SetLabel('No backed-up Fusion Apply transaction is available for this target.')
                self.notebook.SetSelection(2)
                return
            eligible = [entry for entry in transactions if entry.get('eligible')]
            if not eligible:
                self.status.SetLabel('No eligible backup matches the current saved target. See Validation for each reason.')
                self.notebook.SetSelection(2)
                return
            labels = [str(entry.get('operation', 'Apply'))+' — '+str(entry.get('created_at', ''))+
                      ' — '+Path(str(entry['backup_directory'])).name for entry in eligible]
            with wx.SingleChoiceDialog(self, 'Choose a backed-up transaction to reverse. Only receipts matching the current saved target are offered.',
                                       'Reviewed undo / redo', labels) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    self.status.SetLabel('Undo / redo selection cancelled; no target files changed.')
                    return
                selected = eligible[dialog.GetSelection()]
            from .linked_updates import preview_undo
            backup = selected['backup_directory']
            self.run(lambda: preview_undo(target, backup, candidate, cli_path=self.cli_path),
                     self.show_preview, 'Building an offline undo / redo candidate from the selected verified backup…')
        self.run(lambda: list_transactions(target), choose,
                 'Checking backed-up Apply receipts against the saved target…')

    def preview_selected(self, event):
        if self.busy:
            return
        adoption_ids = list(getattr(self, 'pending_adoption_ids', []))
        keys = self.selected_link_ids() if not adoption_ids else []
        if not keys and not adoption_ids:
            wx.MessageBox('Select one or more linked imports in the Overview tree.', 'Preview updates', wx.OK | wx.ICON_WARNING, self)
            return
        selected_links = [link for link in self.links if self.link_key(link) in keys]
        if any(key[0] in keys for key in self.deferred_changes):
            wx.MessageBox('An individual source change is ignored for now. Restore it in Change Review, or leave this link unchanged and update the other selected links separately.',
                          'Linked update deferred', wx.OK | wx.ICON_INFORMATION, self)
            return
        unsupported = [link for link in selected_links if link.get('update_unsupported_reason')]
        if unsupported:
            first = unsupported[0]
            wx.MessageBox(f"{first.get('alias', self.link_key(first))} needs a full combined rebuild: "
                          +str(first['update_unsupported_reason'])+'\n\nBreak-link and backed-up undo remain available.',
                          'Incremental update unavailable', wx.OK | wx.ICON_WARNING, self)
            return
        if len({bool(link.get('include_layout')) for link in selected_links}) > 1:
            wx.MessageBox('Preview routed and schematic-only links in separate reviewed updates.',
                          'Mixed link modes', wx.OK | wx.ICON_WARNING, self)
            return
        retained = bool(self.retain_layout.GetValue())
        conflicted = [link for link in selected_links
                      if any(conflict.get('category') != 'destination_pcb_items' or not retained
                             for conflict in link.get('conflicts', []))]
        if conflicted:
            first = conflicted[0]
            finding = next(conflict for conflict in first['conflicts']
                           if conflict.get('category') != 'destination_pcb_items' or not retained)
            detail = finding.get('message', 'Local destination edits overlap this linked import.')
            wx.MessageBox(f"{first.get('alias', self.link_key(first))}: {detail}\n\nResolve the local conflict in a reviewed copy before updating this link.",
                          'Destination conflict', wx.OK | wx.ICON_WARNING, self)
            return
        missing = [link for link in selected_links if link.get('status') == 'missing_source'
                   and self.link_key(link) not in self.source_overrides]
        if missing:
            wx.MessageBox('Relocate the missing saved source for '+str(missing[0].get('alias', self.link_key(missing[0])))+
                          ' and rescan before preview.', 'Missing linked source', wx.OK | wx.ICON_WARNING, self)
            return
        major = sum(self.major_count(link.get('major_changes', 0)) or
                    sum(change.get('severity') == 'major' for change in link.get('changes', []) if isinstance(change, dict))
                    for link in selected_links)
        if major and not self.major_ack.GetValue():
            self.major_ack.Show(); self.Layout()
            wx.MessageBox('Review the major changes and check the acknowledgement before preview.',
                          'Major linked changes', wx.OK | wx.ICON_WARNING, self)
            return
        try:
            candidate = self.candidate_directory()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Check candidate location', wx.OK | wx.ICON_WARNING, self)
            return
        target = self.target.GetPath()
        self.invalidate_plan()
        if adoption_ids:
            from .linked_updates import preview_adopt_links
            action = lambda: preview_adopt_links(target, adoption_ids, candidate, cli_path=self.cli_path)
            status = 'Building a reviewed legacy-link adoption candidate…'
        else:
            from .linked_updates import preview_update
            overrides = dict(self.source_overrides)
            identity_overrides = {key:dict(value) for key,value in self.identity_overrides.items()
                                  if key in keys}
            retain_layout = bool(self.retain_layout.GetValue())
            action = lambda: preview_update(target, keys, candidate, cli_path=self.cli_path,
                                            acknowledge_major=bool(major), source_overrides=overrides,
                                            identity_overrides=identity_overrides,
                                            retain_destination_layout=retain_layout)
            status = 'Building and validating linked update candidate…'
        self.run(action, self.show_preview, status)

    def show_preview(self, plan):
        try:
            path = self.write_plan(plan)
        except Exception as exc:
            self.status.SetLabel('Candidate created, but its offline plan could not be saved: '+str(exc))
            wx.MessageBox(str(exc), 'Cannot save linked update plan', wx.OK | wx.ICON_ERROR, self)
            return
        self.plan = plan; self.plan_file = path
        self.pending_adoption_ids = []
        report = plan.get('report', {})
        operation = ('undo' if report.get('linked_undo') else
                     'link break' if report.get('linked_break') else 'linked update')
        self.apply_button.SetLabel('Apply reviewed '+operation+'…')
        self.validation.SetValue('Offline plan: '+str(path)+'\nCandidate: '+str(plan['candidate_directory'])+'\n\n'
                                 +json.dumps(report, indent=2, default=str))
        changes = report.get('changes', [])
        if isinstance(changes, list): self.show_change_rows(changes)
        self.major_ack.Show(self.major_count(report.get('major_changes', 0)) > 0)
        self.major_ack.SetValue(False)
        self.Layout()
        self.save_button.Enable(); self.candidate_button.Enable()
        if self.embedded: self.standalone_button.Enable()
        self.on_acknowledge()
        self.notebook.SetSelection(2)
        self.status.SetLabel(operation.capitalize()+' candidate ready. Review Validation, then open standalone Apply and close KiCad editors.'
                             if self.embedded else operation.capitalize()+' candidate ready. Close target and source editors before offline Apply.')

    @staticmethod
    def plan_document(plan):
        return {'format': 'wayri-fusion-linked-plan-v1', 'plan': plan}

    def write_plan(self, plan):
        candidate = Path(plan['candidate_directory'])
        path = candidate.with_name(candidate.name+'-linked-plan.json')
        with path.open('x', encoding='utf-8') as stream:
            json.dump(self.plan_document(plan), stream, indent=2)
            stream.write('\n')
        return path

    def save_plan_dialog(self, event):
        if self.plan is None:
            return
        with wx.FileDialog(self, 'Save reviewed linked-update plan',
                           wildcard='JSON files (*.json)|*.json', defaultFile=Path(self.plan_file).name,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = Path(dialog.GetPath()).resolve()
        candidate = Path(self.plan['candidate_directory']).resolve()
        target = Path(self.plan['target_project']).resolve().parent
        source_roots = [Path(item['root']).resolve() for item in self.plan.get('source_hashes', [])]
        if any(path == root or root in path.parents for root in (candidate, target, *source_roots)):
            wx.MessageBox('Save the plan outside the target, source and candidate folders so their reviewed hashes stay unchanged.',
                          'Choose another plan location', wx.OK | wx.ICON_WARNING, self)
            return
        try:
            path.write_text(json.dumps(self.plan_document(self.plan), indent=2)+'\n', encoding='utf-8')
            self.plan_file = path
            self.status.SetLabel('Reviewed plan saved at '+str(path))
        except OSError as exc:
            wx.MessageBox(str(exc), 'Cannot save linked-update plan', wx.OK | wx.ICON_ERROR, self)

    def load_plan_dialog(self, event):
        with wx.FileDialog(self, 'Load reviewed linked-update plan',
                           wildcard='JSON files (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = dialog.GetPath()
        try:
            self.load_plan_path(path)
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot load linked-update plan', wx.OK | wx.ICON_ERROR, self)

    def load_plan_path(self, path):
        document = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(document, dict) or document.get('format') != 'wayri-fusion-linked-plan-v1':
            raise MergeError('Choose a Wayri Fusion linked-update review plan.')
        plan = document.get('plan')
        if not isinstance(plan, dict) or not all(key in plan for key in ('target_project', 'candidate_directory', 'candidate_hashes', 'report')):
            raise MergeError('The linked-update plan is incomplete.')
        self._suspend = True
        try:
            self.target.SetPath(str(plan['target_project']))
            self.candidate_parent.SetPath(str(Path(plan['candidate_directory']).parent))
            self.candidate_name.SetValue(Path(plan['candidate_directory']).name)
        finally:
            self._suspend = False
        self.plan = plan; self.plan_file = Path(path); self.applied = None
        self.scan_data = None; self.links = []; self.selected_link_id = None
        self.link_tree_items = {}
        self.tree.DeleteAllItems(); self.diagram.show_links(Path(plan['target_project']).stem, [])
        self.update_button.Disable(); self.relocate_button.Disable(); self.search_button.Disable(); self.autolink_button.Disable()
        self.break_selected_button.Disable(); self.break_all_button.Disable()
        self.undo_button.Enable(bool(self.target.GetPath()))
        self.changes.DeleteAllItems()
        report = plan['report']
        operation = ('undo' if report.get('linked_undo') else
                     'link break' if report.get('linked_break') else 'linked update')
        self.apply_button.SetLabel('Apply reviewed '+operation+'…')
        if isinstance(report.get('changes'), list): self.show_change_rows(report['changes'])
        self.validation.SetValue('Loaded offline plan: '+str(path)+'\nCandidate: '+str(plan['candidate_directory'])+'\n\n'
                                 +json.dumps(report, indent=2, default=str))
        self.major_ack.Show(self.major_count(report.get('major_changes', 0)) > 0)
        self.major_ack.SetValue(False); self.closed_ack.SetValue(False)
        self.Layout()
        self.save_button.Enable(); self.candidate_button.Enable()
        if self.embedded: self.standalone_button.Enable()
        self.on_acknowledge()
        self.notebook.SetSelection(2)
        self.status.SetLabel('Reviewed plan loaded. Close KiCad editors, then acknowledge and Apply.'
                             if not self.embedded else 'Reviewed plan loaded. Open standalone Apply, then close KiCad editors.')

    def show_candidate(self, event):
        if self.plan is not None:
            wx.LaunchDefaultApplication(str(self.plan['candidate_directory']))

    def open_standalone(self, event):
        if self.plan_file is None:
            return
        try:
            from .insertion_gui import InsertionDialog
            launcher = InsertionDialog.python_launcher()
            subprocess.Popen([str(launcher), str(Path(__file__).resolve()), '--plan', str(self.plan_file)],
                             close_fds=True)
            self.status.SetLabel('Standalone Apply window opened. Close KiCad editors before applying there.')
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot open standalone Apply window', wx.OK | wx.ICON_ERROR, self)

    def apply_updates(self, event):
        if self.embedded or self.busy or self.plan is None or not self.closed_ack.GetValue():
            return
        if self.major_ack.IsShown() and not self.major_ack.GetValue():
            return
        target = self.plan['target_project']
        report = self.plan.get('report', {})
        operation = ('undo the last Apply' if report.get('linked_undo') else
                     'break the selected update links' if report.get('linked_break') else
                     'apply linked source updates')
        if wx.MessageBox(f'Apply the reviewed candidate to {operation}?\n\n{target}\n\n'
                         'The backend checks all reviewed hashes again, creates a complete backup and applies offline.',
                         'Apply reviewed Fusion change', wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
            return
        from .insertion import apply_import
        plan = self.plan
        def done(result):
            self.applied = result
            self.plan = None
            self.apply_button.Disable(); self.candidate_button.Disable()
            self.validation.SetValue(json.dumps(result, indent=2, default=str))
            self.status.SetLabel('Applied with backup at '+str(result['backup_directory'])+'. Reopen target in KiCad and review ERC/DRC.')
            wx.MessageBox('Reviewed '+operation+' completed with a backup. Reopen the target and review schematic, PCB, ERC and DRC.',
                          'Fusion change complete', wx.OK | wx.ICON_INFORMATION, self)
        self.run(lambda: apply_import(plan), done, 'Checking hashes and applying reviewed updates offline…')

    def close(self, event):
        if self.busy:
            if isinstance(event, wx.CloseEvent) and event.CanVeto(): event.Veto()
            return
        self.watch_timer.Stop()
        if self.IsModal(): self.EndModal(wx.ID_CANCEL)
        else: self.Destroy()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Review and apply linked Wayri Fusion updates offline.')
    parser.add_argument('--plan', help='Reviewed linked-update plan JSON')
    args = parser.parse_args(argv)
    app = wx.App(False)
    dialog = LinkedUpdatesDialog()
    try:
        if args.plan:
            try: dialog.load_plan_path(args.plan)
            except Exception as exc:
                wx.MessageBox(str(exc), 'Cannot load linked-update plan', wx.OK | wx.ICON_ERROR, dialog)
                return 1
        dialog.ShowModal()
    finally:
        dialog.Destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
