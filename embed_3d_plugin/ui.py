"""Native, theme-aware wx UI. No webview, pip installer, or network connection."""
from __future__ import annotations
from pathlib import Path
import threading
import time
import wx
from .codec import Codec
from .core import Planner
from .paths import Resolver
from .sexpr import parse
from .storage import embed_files
from .logging_utils import get_logger
from .assets import make_header_icon, set_window_icons


def human_size(size):
    if size == 0:
        return '—'
    for suffix in ('B', 'KiB', 'MiB', 'GiB'):
        if size < 1024 or suffix == 'GiB':
            return ('%d %s' if suffix == 'B' else '%.1f %s') % (size, suffix)
        size /= 1024


def readable_settings(row):
    try:
        text = '(model ""'+row.settings
        root = parse(text)
        items = []
        for key, label in (('scale', 'Scale'), ('rotate', 'Rotation (°)'), ('offset', 'Offset (mm)')):
            block = root.one(text, key)
            xyz = block.one(text, 'xyz') if block else None
            if xyz:
                values = [v.value(text) for v in xyz.children[1:]]
                items.append(label+':  '+ '   '.join(a+' '+v for a, v in zip(('X', 'Y', 'Z'), values)))
        items.append('All 3D settings, including visibility and opacity, stay unchanged.')
        return '\n'.join(items)
    except (ValueError, AttributeError):
        return row.settings.strip()


class EmbedDialog(wx.Dialog):
    def __init__(self, parent, bridge):
        super().__init__(parent, title='WayriCAD Embed3D · Embed linked 3D models',
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.bridge, self.log = bridge, get_logger()
        self.plans, self.rows, self.overrides, self.files = [], [], {}, []
        self.source_keys = {}
        self.active_resolver = None
        self.busy = self.closing = self.updating = self.valid = False
        self.thread = None
        self.cancel_scan = threading.Event()
        self.result_message = ''
        self.codec_label = ''
        set_window_icons(self, wx)
        self._build()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda event: self.gauge.Pulse() if self.busy else None, self.timer)
        self.CentreOnParent()
        wx.CallAfter(self.start_scan)

    def _build(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self.brand_icon = make_header_icon(panel, wx)
        if self.brand_icon is not None:
            header.Add(self.brand_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(14))
        words = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label='Make your footprints portable.')
        font = title.GetFont(); font.SetPointSize(font.GetPointSize()+7); font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(font)
        words.Add(title, 0, wx.BOTTOM, self.FromDIP(5))
        subtitle = wx.StaticText(panel, label='Embed the actual model files. Keep every scale, rotation and offset.')
        words.Add(subtitle)
        header.Add(words, 1, wx.ALIGN_CENTER_VERTICAL)
        box.Add(header, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(17))
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label='Source'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(10))
        live = getattr(self.bridge, 'supports_live_tools', True)
        choices = ['Selected board footprints', 'All board footprints',
                   'Footprint files (.kicad_mod)…', 'Footprint library (.pretty)…']
        self.scope = wx.Choice(panel, choices=choices if live else choices[2:])
        selected = bool(self.bridge.footprints(True)) if live else False
        self.scope.SetSelection((0 if selected else 1) if live else 0)
        row.Add(self.scope, 1, wx.RIGHT, self.FromDIP(8))
        self.browse = wx.Button(panel, label='Browse…')
        self.browse.Enable(not live)
        row.Add(self.browse, 0, wx.RIGHT, self.FromDIP(8))
        self.scan = wx.Button(panel, label='Scan again')
        row.Add(self.scan)
        box.Add(row, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(6))
        portability = wx.BoxSizer(wx.HORIZONTAL)
        self.unbundle_button = wx.Button(panel, label='Unbundle PCB…')
        self.symbols_button = wx.Button(panel, label='Schematic symbols…')
        portability.Add(self.unbundle_button, 0, wx.RIGHT, self.FromDIP(8))
        portability.Add(self.symbols_button)
        box.Add(portability, 0, wx.BOTTOM, self.FromDIP(8))
        self.unbundle_button.Bind(wx.EVT_BUTTON, lambda event: self.on_portability(0))
        self.symbols_button.Bind(wx.EVT_BUTTON, lambda event: self.on_portability(1))
        self.scope_note = wx.StaticText(panel, label='Current PCB only. Source footprint libraries will not be changed.' if live else 'Saved footprint files only. Close them in Footprint Editor before applying.')
        box.Add(self.scope_note, 0, wx.BOTTOM | wx.EXPAND, self.FromDIP(15))
        self.summary = wx.StaticText(panel, label='Preparing preview…')
        bold = self.summary.GetFont(); bold.SetWeight(wx.FONTWEIGHT_BOLD); self.summary.SetFont(bold)
        box.Add(self.summary, 0, wx.BOTTOM, self.FromDIP(8))
        self.table = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SIMPLE)
        if not hasattr(self.table, 'EnableCheckBoxes'):
            raise RuntimeError('This KiCad Python build needs wxPython 4.1 or newer for native model checkboxes')
        self.table.EnableCheckBoxes(True)
        for index, (label, width) in enumerate((('Footprint', 175), ('Linked model', 270), ('Status', 130), ('File size', 85), ('Details / reason', 330))):
            self.table.InsertColumn(index, label, width=self.FromDIP(width))
        self.table.SetMinSize(self.FromDIP((650, 120)))
        box.Add(self.table, 1, wx.EXPAND)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.all_button = wx.Button(panel, label='Select ready', style=wx.BU_EXACTFIT)
        self.none_button = wx.Button(panel, label='Clear selection', style=wx.BU_EXACTFIT)
        self.find_missing = wx.Button(panel, label='Find missing…')
        self.model_folder = wx.Button(panel, label='Models folder…')
        self.locate = wx.Button(panel, label='Locate model…')
        self.locate.Enable(False)
        controls.Add(self.all_button, 0, wx.RIGHT, self.FromDIP(8))
        controls.Add(self.none_button)
        controls.AddStretchSpacer()
        controls.Add(self.model_folder, 0, wx.RIGHT, self.FromDIP(8))
        controls.Add(self.find_missing, 0, wx.RIGHT, self.FromDIP(8))
        controls.Add(self.locate)
        box.Add(controls, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, self.FromDIP(8))
        self.details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE,
                                   value='Select a model to inspect its path and existing 3D settings.')
        self.details.SetMinSize(self.FromDIP((-1, 95)))
        box.Add(self.details, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(9))
        self.advanced = wx.CollapsiblePane(panel, label='Path settings', style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        pane = self.advanced.GetPane()
        adv = wx.BoxSizer(wx.VERTICAL)
        adv.Add(wx.StaticText(pane, label='Project folder — used for ${KIPRJMOD} and relative paths'), 0, wx.BOTTOM, self.FromDIP(4))
        self.project = wx.DirPickerCtrl(pane, path=str(self.bridge.project_path()),
                                        style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        adv.Add(self.project, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(8))
        adv.Add(wx.StaticText(pane, label='Stock 3D-model root — leave empty to use the live KiCad setting'), 0, wx.BOTTOM, self.FromDIP(4))
        self.stock_root = wx.DirPickerCtrl(pane, path='', style=wx.DIRP_USE_TEXTCTRL | wx.DIRP_DIR_MUST_EXIST)
        adv.Add(self.stock_root, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(8))
        adv.Add(wx.StaticText(pane, label='Extra variables / legacy aliases — one NAME=folder per line'), 0, wx.BOTTOM, self.FromDIP(4))
        self.variables = wx.TextCtrl(pane, style=wx.TE_MULTILINE, size=self.FromDIP((-1, 55)))
        self.variables.SetHint('MY_MODELS=C:\\Models')
        adv.Add(self.variables, 0, wx.EXPAND)
        pane.SetSizer(adv)
        box.Add(self.advanced, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(8))
        self.status = wx.StaticText(panel, label='No changes have been made.')
        box.Add(self.status, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(5))
        self.gauge = wx.Gauge(panel, range=100, size=self.FromDIP((-1, 4)))
        box.Add(self.gauge, 0, wx.EXPAND | wx.BOTTOM, self.FromDIP(12))
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.export = wx.Button(panel, label='Export portable .pretty…')
        self.export.SetToolTip('Create new standalone library footprints with every linked model embedded. The current board is unchanged.')
        footer.Add(self.export, 0, wx.RIGHT, self.FromDIP(8))
        self.package = wx.Button(panel, label='Package PCB…')
        self.package.SetToolTip('Separate option: embed footprint definitions and 3D files in a NEW PCB copy; relink to a reconstructed project-local library.')
        footer.Add(self.package, 0, wx.RIGHT, self.FromDIP(8))
        self.more = wx.Button(panel, label='More…')
        footer.Add(self.more)
        footer.AddStretchSpacer()
        self.cancel = wx.Button(panel, wx.ID_CANCEL, 'Cancel')
        self.apply = wx.Button(panel, label='Embed models')
        self.apply.SetDefault()
        footer.Add(self.cancel, 0, wx.RIGHT, self.FromDIP(8)); footer.Add(self.apply)
        box.Add(footer, 0, wx.EXPAND)
        panel.SetSizer(box)
        outer.Add(panel, 1, wx.EXPAND | wx.ALL, self.FromDIP(20))
        self.SetSizer(outer)
        screen = wx.GetClientDisplayRect().GetSize()
        width, height = min(self.FromDIP(1000), screen.width-50), min(self.FromDIP(740), screen.height-50)
        self.SetSize((width, height))
        self.SetMinSize((min(self.FromDIP(780), width), min(self.FromDIP(590), height)))
        self.scope.Bind(wx.EVT_CHOICE, self.on_scope)
        self.browse.Bind(wx.EVT_BUTTON, lambda event: self.choose_sources())
        self.scan.Bind(wx.EVT_BUTTON, lambda event: self.start_scan())
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.table.Bind(wx.EVT_LIST_ITEM_CHECKED, self.on_check)
        self.table.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.on_check)
        self.all_button.Bind(wx.EVT_BUTTON, lambda event: self.select_rows(True))
        self.none_button.Bind(wx.EVT_BUTTON, lambda event: self.select_rows(False))
        self.locate.Bind(wx.EVT_BUTTON, self.on_locate)
        self.find_missing.Bind(wx.EVT_BUTTON, self.on_find_missing)
        self.model_folder.Bind(wx.EVT_BUTTON, self.on_model_folder)
        self.package.Bind(wx.EVT_BUTTON, self.on_package)
        self.more.Bind(wx.EVT_BUTTON, self.on_more)
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        self.export.Bind(wx.EVT_BUTTON, self.on_export)
        self.cancel.Bind(wx.EVT_BUTTON, self.on_close)
        self.project.Bind(wx.EVT_DIRPICKER_CHANGED, self.invalidate)
        self.stock_root.Bind(wx.EVT_DIRPICKER_CHANGED, self.invalidate)
        self.variables.Bind(wx.EVT_TEXT, self.invalidate)
        self.advanced.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.on_advanced)
        self.update_actions()

    def on_advanced(self, event):
        # Use the same vertical space for details and advanced path controls.
        self.details.Show(not self.advanced.IsExpanded())
        self.Layout()

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close(event)
        else:
            event.Skip()

    def on_close(self, event=None):
        if self.busy:
            self.closing = True
            self.cancel_scan.set()
            self.status.SetLabel('Stopping after the current model…')
            if hasattr(event, 'Veto'):
                event.Veto()
            return
        self.timer.Stop()
        self.EndModal(wx.ID_CANCEL)

    def invalidate(self, event=None):
        self.valid = False
        self.status.SetLabel('Path settings changed. Scan again to refresh the preview.')
        self.update_actions()

    def scope_mode(self):
        return self.scope.GetSelection() + (0 if getattr(self.bridge, 'supports_live_tools', True) else 2)

    def on_scope(self, event):
        self.overrides.clear()
        self.files = []
        self.valid = False
        file_mode = self.scope_mode() >= 2
        self.browse.Enable(file_mode)
        self.scope_note.SetLabel('Saved library files only. Close them in the Footprint Editor before applying.' if file_mode
                                 else 'Current PCB only. Source footprint libraries will not be changed.')
        self.update_actions()
        if file_mode:
            self.choose_sources()
        else:
            self.start_scan()

    def choose_sources(self):
        mode = self.scope_mode()
        if mode == 2:
            with wx.FileDialog(self, 'Choose saved footprints', wildcard='KiCad footprints (*.kicad_mod)|*.kicad_mod',
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                self.files = sorted(set(Path(p).resolve() for p in dialog.GetPaths()))
        elif mode == 3:
            with wx.DirDialog(self, 'Choose a .pretty footprint library', style=wx.DD_DIR_MUST_EXIST) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                root = Path(dialog.GetPath()).resolve()
                if root.suffix.lower() != '.pretty':
                    self.error('Choose a directory whose name ends in .pretty.')
                    return
                self.files = sorted(root.glob('*.kicad_mod'))
                if not self.files:
                    self.error('This library contains no .kicad_mod files.')
                    return
        else:
            return
        self.overrides.clear()
        if self.files and not (self.bridge.board and self.bridge.board.GetFileName()):
            self.project.SetPath(str(self.files[0].parent.parent if mode == 3 else self.files[0].parent))
        self.start_scan()

    def resolver(self):
        values = {}
        for line in self.variables.GetValue().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                raise ValueError('Use NAME=folder for each path variable')
            name, value = line.split('=', 1)
            if not name.strip() or not value.strip():
                raise ValueError('Path variable name and value must not be empty')
            values[name.strip()] = value.strip()
        project = Path(self.project.GetPath()) if self.project.GetPath() else None
        if project and not project.is_dir():
            raise ValueError('Project folder does not exist')
        # Project text variables may also be used in model references.
        if self.bridge.board and self.bridge.board.GetFileName():
            import json
            path = Path(str(self.bridge.board.GetFileName())).with_suffix('.kicad_pro')
            try:
                data = json.loads(path.read_text(encoding='utf-8')).get('text_variables', {})
                for key, value in data.items():
                    values.setdefault(key, value)
            except (OSError, ValueError):
                pass
        if self.stock_root.GetPath():
            root = Path(self.stock_root.GetPath())
            if not root.is_dir():
                raise ValueError('Stock 3D models folder does not exist')
            values['KICAD10_3DMODEL_DIR'] = str(root)
        return self.bridge.prepare_resolver(Resolver(project, values))

    def set_busy(self, value):
        self.busy = value
        for widget in (self.scope, self.scan, self.project, self.variables, self.stock_root, self.model_folder, self.more, self.all_button, self.none_button, self.table):
            widget.Enable(not value)
        self.browse.Enable(not value and self.scope_mode() >= 2)
        self.locate.Enable(False)
        if value:
            self.timer.Start(100)
        else:
            self.timer.Stop()
            self.gauge.SetValue(0)
        self.update_actions()

    def start_scan(self):
        if self.busy:
            return
        self.valid = False
        self.cancel_scan.clear()
        self.set_busy(True)
        self.summary.SetLabel('Scanning linked model files…')
        self.status.SetLabel('Nothing is changed during preview. Model compression is verified in memory.')
        self.details.SetValue('Select a model after the scan to inspect its existing 3D settings.')
        try:
            resolver = self.resolver()
            self.active_resolver = resolver
            mode = self.scope_mode()
            if mode < 2:
                sources, pool = self.bridge.sources(mode == 0, resolver)
            else:
                if not self.files:
                    raise ValueError('Choose footprint files or a .pretty library first')
                sources = [{'key': str(p.resolve()), 'source_path': p.resolve(), 'source_dir': p.resolve().parent,
                            'name': p.stem, 'owner': None, 'text': None} for p in self.files]
                pool = {}
        except Exception as exc:
            self.set_busy(False)
            self.summary.SetLabel('Choose footprints to begin.')
            self.status.SetLabel(str(exc))
            self.log.exception('Source snapshot failed')
            return
        overrides = {key: dict(value) for key, value in self.overrides.items()}
        def worker():
            plans, error, codec_label, keys = [], None, '', {}
            try:
                planner = Planner(resolver, Codec())
                codec_label = planner.codec.label
                last_progress = 0
                for index, source in enumerate(sources):
                    if self.cancel_scan.is_set():
                        raise InterruptedError('Scan cancelled')
                    text = source['text']
                    if text is None:
                        text = source['source_path'].read_bytes().decode('utf-8')
                    plan = planner.scan(text, source['name'], source['source_dir'], pool,
                                        overrides.get(source['key']), self.cancel_scan.is_set)
                    plan.source_path, plan.owner = source['source_path'], source['owner']
                    plans.append(plan)
                    keys[id(plan)] = source['key']
                    if time.monotonic()-last_progress > 0.15:
                        wx.CallAfter(self.progress, index+1, len(sources))
                        last_progress = time.monotonic()
            except Exception as exc:
                error = str(exc)
                if not isinstance(exc, InterruptedError):
                    self.log.exception('Scan failed')
            wx.CallAfter(self.scan_done, plans, keys, codec_label, error)
        self.thread = threading.Thread(target=worker, name='WayriCAD Embed3D-scan', daemon=True)
        self.thread.start()

    def progress(self, count, total):
        if self.busy and not self.closing:
            self.status.SetLabel('Scanned %d of %d footprints. No changes made.' % (count, total))

    def scan_done(self, plans, keys, codec_label, error):
        self.thread = None
        self.set_busy(False)
        if self.closing:
            self.EndModal(wx.ID_CANCEL)
            return
        self.plans, self.source_keys, self.codec_label = plans, keys, codec_label
        self.rows = [(p, r) for p in plans for r in p.rows]
        self.updating = True
        self.table.Freeze()
        try:
            self.table.DeleteAllItems()
            for index, (plan, row) in enumerate(self.rows):
                self.table.InsertItem(index, plan.name)
                self.table.SetItem(index, 1, row.reference.replace('\\', '/').split('/')[-1])
                self.table.SetItem(index, 2, row.status)
                self.table.SetItem(index, 3, human_size(row.size))
                self.table.SetItem(index, 4, row.detail.replace("\n", " "))
                self.table.CheckItem(index, row.checked)
        finally:
            self.table.Thaw()
            self.updating = False
        self.valid = error is None
        self.status.SetLabel(error or (codec_label+' · Preview only; backups are created on apply.'))
        self.update_actions()
        if self.rows:
            self.table.Select(0)
        if error:
            self.error(error)

    def selected_row(self):
        index = self.table.GetFirstSelected()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def on_select(self, event):
        selected = self.selected_row()
        if not selected:
            return
        plan, row = selected
        self.details.SetValue('%s\nLinked: %s\nResolved: %s\n%s\n%s' % (
            plan.name, row.reference, str(row.resolved or 'Stored inside the design / not resolved'),
            readable_settings(row), row.detail))
        self.locate.Enable(not self.busy and self.valid and row.status != 'Embedded')

    def on_check(self, event):
        if self.updating:
            return
        index = event.GetIndex()
        if not 0 <= index < len(self.rows):
            return
        _, row = self.rows[index]
        checked = self.table.IsItemChecked(index)
        row.checked = bool(checked and row.ready)
        if checked and not row.ready:
            self.updating = True
            self.table.CheckItem(index, False)
            self.updating = False
        self.update_actions()

    def select_rows(self, checked):
        self.updating = True
        for index, (_, row) in enumerate(self.rows):
            row.checked = checked and row.ready
            self.table.CheckItem(index, row.checked)
        self.updating = False
        self.update_actions()

    def update_actions(self):
        checked = sum(len(p.actionable) for p in self.plans)
        embedded = sum(r.status == 'Embedded' for _, r in self.rows)
        attention = sum(not r.ready and r.status != 'Embedded' for _, r in self.rows)
        if not self.busy and self.plans:
            self.summary.SetLabel('%d checked  ·  %d already embedded  ·  %d need attention  ·  %d footprints' %
                                  (checked, embedded, attention, len(self.plans)))
        self.apply.SetLabel('Embed %d model%s' % (checked, '' if checked == 1 else 's'))
        self.apply.Enable(self.valid and not self.busy and checked > 0)
        self.find_missing.Enable(self.valid and not self.busy and attention > 0)
        self.package.Enable(not self.busy and bool(self.bridge.board))
        portable = bool(self.rows) and all(r.status == 'Embedded' or (r.ready and r.checked) for _, r in self.rows)
        self.export.Enable(self.valid and not self.busy and self.scope_mode() < 2 and portable)
        self.table.Enable(not self.busy and self.valid)

    def on_locate(self, event):
        selected = self.selected_row()
        if not selected:
            return
        plan, row = selected
        with wx.FileDialog(self, 'Locate the exact model for '+plan.name,
                           wildcard='3D models|*.step;*.stp;*.stpz;*.wrl;*.wrz;*.igs;*.iges;*.x3d|All files|*.*',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                key = self.source_keys[id(plan)]
                path = dialog.GetPath()
                self.overrides.setdefault(key, {})[row.index] = path
                same = [(p, r) for p, r in self.rows if r is not row and r.reference == row.reference
                        and p.source_dir == plan.source_dir and r.status != 'Embedded']
                if same and wx.MessageBox('Use this same file for %d other entries with the identical link and library context?' % len(same),
                                          'Repair repeated references', wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES:
                    for p, r in same:
                        self.overrides.setdefault(self.source_keys[id(p)], {})[r.index] = path
                self.start_scan()

    def error(self, message):
        wx.MessageBox(str(message), 'WayriCAD Embed3D', wx.OK | wx.ICON_WARNING, self)

    def on_apply(self, event):
        if not self.valid or self.busy:
            return
        file_mode = self.scope_mode() >= 2
        chosen = [p for p in self.plans if p.actionable]
        checked = sum(len(p.actionable) for p in chosen)
        skipped = sum(r.status != 'Embedded' and not (r.ready and r.checked) for _, r in self.rows)
        target = '%d saved footprint file(s)' % len(chosen) if file_mode else '%d footprint(s) on the current PCB' % len(chosen)
        message = 'Embed %d model(s) into %s?\n\n' % (checked, target)
        message += 'Scale, rotation and offset are preserved. Backups are created first.\n'
        if file_mode:
            message += 'Close these files in the Footprint Editor first; unsaved editor buffers are not updated.\n'
        else:
            message += 'Source libraries are not changed. Save the PCB after the operation.\n'
        if skipped:
            message += '\n%d unchecked/unresolved model(s) will remain unchanged. This is a PARTIAL embed.' % skipped
        with wx.MessageDialog(self, message, 'Confirm embedding', wx.OK | wx.CANCEL | wx.ICON_INFORMATION) as dialog:
            dialog.SetOKLabel('Embed models')
            if dialog.ShowModal() != wx.ID_OK:
                return
        self.set_busy(True)
        self.status.SetLabel('Validating with KiCad and creating recovery files…')
        try:
            parent = Path(self.project.GetPath())
            if file_mode:
                backup = embed_files(self.plans, parent, self.bridge.validate_file)
                self.result_message = 'Embedded %d model(s) in %d footprint file(s).\n\nBackups and original paths:\n%s\n\nReopen the footprints in the Footprint Editor.' % (checked, len(chosen), backup)
            else:
                backup = self.bridge.apply_live(self.plans, parent)
                self.result_message = 'Embedded %d model(s) in %d board footprint(s).\n\nSave the PCB to keep the changes. Ctrl+Z uses KiCad’s action undo.\nSource footprint libraries were not modified.\n\nRecovery board and original paths:\n%s' % (checked, len(chosen), backup)
            if skipped:
                self.result_message += '\n\nPartial embed: %d other model(s) remain unchanged.' % skipped
            self.set_busy(False)
            self.EndModal(wx.ID_OK)
        except Exception as exc:
            self.log.exception('Apply failed')
            self.set_busy(False)
            self.valid = False
            self.status.SetLabel('Operation stopped. Scan again before retrying. Log: '+self.log.log_path)
            self.update_actions()
            self.error(str(exc)+'\n\nDiagnostic log: '+self.log.log_path)

    def on_export(self, event):
        with wx.DirDialog(self, 'Choose the parent directory for a NEW portable library',
                          defaultPath=self.project.GetPath(), style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            parent = Path(dialog.GetPath())
        with wx.TextEntryDialog(self, 'Name for the new library folder', 'Export portable footprints', 'Embedded3D.pretty') as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            name = dialog.GetValue().strip()
        if not name or Path(name).name != name or '/' in name or '\\' in name:
            self.error('Use a simple folder name, without a path.')
            return
        if not name.lower().endswith('.pretty'):
            name += '.pretty'
        self.set_busy(True)
        self.status.SetLabel('Creating and verifying standalone footprint files…')
        try:
            path = self.bridge.export_library(self.plans, parent/name)
            self.result_message = 'Created a portable footprint library:\n%s\n\nEvery model reference has an embedded payload. The board was not changed.\nAdd this folder through Preferences → Manage Footprint Libraries → Project Specific Libraries.' % path
            self.set_busy(False)
            self.EndModal(wx.ID_OK)
        except Exception as exc:
            self.log.exception('Export failed')
            self.set_busy(False)
            self.error(str(exc)+'\n\nDiagnostic log: '+self.log.log_path)


    def on_model_folder(self, event):
        roots = self.active_resolver.model_roots() if self.active_resolver else []
        with wx.DirDialog(self, 'Choose the root containing Resistor_SMD.3dshapes, Capacitor_SMD.3dshapes, etc.',
                          defaultPath=str(roots[0]) if roots else '', style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.stock_root.SetPath(dialog.GetPath())
                self.start_scan()

    def on_find_missing(self, event):
        from .repair_ui import FindMissingDialog
        groups = {}
        for plan, row in self.rows:
            if not row.ready and row.status not in ('Embedded', 'Missing payload'):
                identity = (row.reference, str(plan.source_dir or ''))
                groups.setdefault(identity, []).append((self.source_keys[id(plan)], row.index))
        if not groups:
            self.error('No unresolved external models to search for. A missing embedded payload needs its original model file.')
            return
        roots = self.active_resolver.model_roots() if self.active_resolver else []
        roots = [p for p in roots if p.is_dir()]
        with FindMissingDialog(self, groups, roots) as dialog:
            if dialog.ShowModal() == wx.ID_OK and dialog.accepted:
                for key, replacements in dialog.accepted.items():
                    self.overrides.setdefault(key, {}).update(replacements)
                self.start_scan()

    def on_package(self, event):
        from .package_ui import PackageDialog
        try:
            resolver = self.resolver()
            with PackageDialog(self, self.bridge, resolver, self.overrides) as dialog:
                if dialog.ShowModal() == wx.ID_OK:
                    wx.MessageBox(dialog.result_message, 'PCB package created', wx.OK | wx.ICON_INFORMATION, self)
        except Exception as exc:
            self.log.exception('Package dialog failed')
            self.error(str(exc))

    def on_more(self, event):
        menu = wx.Menu()
        diagnostics = menu.Append(wx.ID_ANY, 'Save scan diagnostics…')
        rebuild = menu.Append(wx.ID_ANY, 'Rebuild embedded library from PCB…')
        self.Bind(wx.EVT_MENU, self.on_diagnostics, id=diagnostics.GetId())
        self.Bind(wx.EVT_MENU, self.on_rebuild, id=rebuild.GetId())
        try:
            self.PopupMenu(menu)
        finally:
            self.Unbind(wx.EVT_MENU, id=diagnostics.GetId())
            self.Unbind(wx.EVT_MENU, id=rebuild.GetId())
            menu.Destroy()

    def on_diagnostics(self, event):
        import json
        if self.active_resolver is None:
            self.error('Run a scan first.'); return
        with wx.FileDialog(self, 'Save model-path diagnostics (includes local paths)',
                           defaultFile='WayriCAD Embed3D-diagnostics.json', wildcard='JSON files|*.json',
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    from .storage import write_json
                    write_json(Path(dialog.GetPath()), {'version': '0.4.1', 'kicad': self.bridge.version,
                                                       'resolution': self.active_resolver.diagnostics(),
                                                       'plans': [p.manifest() for p in self.plans]})
                except Exception as exc:
                    self.error(str(exc))

    def on_rebuild(self, event):
        from .board_package import rebuild_library
        with wx.FileDialog(self, 'Choose the saved PCB containing a WayriCAD Embed3D footprint archive',
                           defaultDir=self.project.GetPath(), wildcard='KiCad PCB|*.kicad_pcb',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        try:
            preview = rebuild_library(path)
            message = ('Rebuild %d footprint definitions beside this PCB?\n\n%s\n\n'
                       'Adds missing files and registers the project library. Existing files with later edits '
                       'are not overwritten. Close affected footprints in the Footprint Editor first. '
                       'The saved PCB is read, not changed; unsaved PCB changes are not included.') % (preview['files'], preview['library'])
            if wx.MessageBox(message, 'Rebuild embedded library', wx.OK | wx.CANCEL | wx.ICON_INFORMATION, self) != wx.OK:
                return
            self.set_busy(True)
            with wx.BusyCursor():
                result = rebuild_library(path, apply=True, validate=self.bridge.validate_package)
            self.set_busy(False)
            wx.MessageBox('Library reconstructed and project table registered.\n'+result['library']+
                          '\n\nClose and reopen the project so KiCad reloads fp-lib-table.',
                          'Rebuild complete', wx.OK | wx.ICON_INFORMATION, self)
        except Exception as exc:
            self.set_busy(False)
            self.log.exception('Library rebuild failed')
            self.error(str(exc))

    def on_portability(self, tab=0):
        if self.busy:
            self.error('Wait for the current scan to finish.'); return
        from .portability_ui import PortabilityDialog
        dialog = PortabilityDialog(self, self.bridge, tab)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
