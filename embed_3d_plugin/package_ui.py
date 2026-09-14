"""Separate, non-destructive PCB archive + relink workflow."""
from __future__ import annotations
from pathlib import Path
import threading
import wx
from .assets import set_window_icons
from .board_package import Definition, Instance, compose, write_package, slug, safe_name
from .core import Planner, verify_sources
from .sexpr import parse, semantic
from .logging_utils import get_logger


class PackageDialog(wx.Dialog):
    def __init__(self, parent, bridge, resolver, overrides):
        super().__init__(parent, title='Package PCB · Footprints + 3D models',
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.bridge, self.resolver = bridge, resolver
        self.overrides = {key: dict(value) for key, value in overrides.items()}
        self.imports, self.records, self.instances = [], [], []
        self.snapshot = ''
        self.valid = self.busy = self.closing = False
        self.stop = threading.Event()
        self.result_message = ''
        self.log = get_logger()
        self._build()
        set_window_icons(self, wx)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.CentreOnParent()

    def _build(self):
        outer = wx.BoxSizer(wx.VERTICAL)
        header = wx.StaticText(self, label='Archive inside the PCB. Relink to a local library.')
        font = header.GetFont(); font.SetPointSize(font.GetPointSize()+4); font.SetWeight(wx.FONTWEIGHT_BOLD)
        header.SetFont(font)
        outer.Add(header, 0, wx.EXPAND | wx.ALL, self.FromDIP(14))
        note = wx.StaticText(self, label='Creates a NEW packaged PCB copy; the open PCB and source libraries stay unchanged.\n'
                                        'All placed footprints, their reusable definitions and model bytes are included.\n'
                                        'The .pretty directory is reconstructed from PCB-embedded data, not an external model dependency.')
        outer.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(14))
        self.mode = wx.Choice(self, choices=['Use footprints as placed on the board (recommended)',
                                            'Prefer supplied definitions with matching Library:Name IDs'])
        self.mode.SetSelection(0)
        outer.Add(self.mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(14))
        outer.Add(wx.StaticText(self, label='Optional supplied footprints — local, custom or standard .pretty libraries'),
                  0, wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(6))
        self.import_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                      size=self.FromDIP((-1, 110)))
        self.import_list.InsertColumn(0, 'Source Library:Name', width=self.FromDIP(280))
        self.import_list.InsertColumn(1, 'Supplied file', width=self.FromDIP(560))
        outer.Add(self.import_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(14))
        controls = wx.BoxSizer(wx.HORIZONTAL)
        self.add_files = wx.Button(self, label='Add footprints…')
        self.add_library = wx.Button(self, label='Add .pretty…')
        self.source_id = wx.Button(self, label='Set source ID…')
        self.remove = wx.Button(self, label='Remove')
        for button in (self.add_files, self.add_library, self.source_id, self.remove):
            controls.Add(button, 0, wx.RIGHT, self.FromDIP(8))
        outer.Add(controls, 0, wx.EXPAND | wx.ALL, self.FromDIP(14))
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (label, width) in enumerate((('Footprint / source', 270), ('Models', 75),
                                          ('Link target', 280), ('State / issue', 310))):
            self.table.InsertColumn(i, label, width=self.FromDIP(width))
        outer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(14))
        self.details = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=self.FromDIP((-1, 82)))
        outer.Add(self.details, 0, wx.EXPAND | wx.ALL, self.FromDIP(14))
        self.status = wx.StaticText(self, label='Preview checks every model before enabling package creation.')
        outer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(14))
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.preview = wx.Button(self, label='Preview package')
        self.cancel = wx.Button(self, wx.ID_CANCEL, 'Cancel')
        self.create = wx.Button(self, label='Create new PCB package…')
        self.create.Enable(False)
        footer.Add(self.preview); footer.AddStretchSpacer(); footer.Add(self.cancel, 0, wx.RIGHT, self.FromDIP(8)); footer.Add(self.create)
        outer.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(14))
        self.SetSizer(outer)
        screen = wx.GetClientDisplayRect().GetSize()
        self.SetSize((min(self.FromDIP(1040), screen.width-50), min(self.FromDIP(780), screen.height-50)))
        self.SetMinSize(self.FromDIP((760, 620)))
        self.add_files.Bind(wx.EVT_BUTTON, self.on_add_files)
        self.add_library.Bind(wx.EVT_BUTTON, self.on_add_library)
        self.source_id.Bind(wx.EVT_BUTTON, self.on_source_id)
        self.remove.Bind(wx.EVT_BUTTON, self.on_remove)
        self.mode.Bind(wx.EVT_CHOICE, self.invalidate)
        self.preview.Bind(wx.EVT_BUTTON, self.on_preview)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.create.Bind(wx.EVT_BUTTON, self.on_create)
        self.cancel.Bind(wx.EVT_BUTTON, self.on_close)

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close()
        else:
            event.Skip()

    def on_close(self, event=None):
        if self.busy:
            self.closing = True; self.stop.set()
            self.status.SetLabel('Stopping after the current operation…')
            if hasattr(event, 'Veto'):
                event.Veto()
        else:
            self.EndModal(wx.ID_CANCEL)

    def invalidate(self, event=None):
        self.valid = False; self.create.Enable(False)
        self.status.SetLabel('Source selection changed. Preview again before packaging.')

    def set_busy(self, state):
        self.busy = state
        for widget in (self.mode, self.add_files, self.add_library, self.source_id,
                       self.remove, self.preview, self.import_list):
            widget.Enable(not state)
        self.create.Enable(not state and self.valid)

    def error(self, message):
        wx.MessageBox(str(message), 'WayriCAD Embed3D PCB package', wx.OK | wx.ICON_WARNING, self)

    def add_paths(self, paths):
        existing = {item['path'] for item in self.imports}
        for path in paths:
            path = Path(path).resolve()
            if path in existing:
                continue
            if path.suffix.lower() != '.kicad_mod' or not path.is_file():
                raise ValueError('Choose .kicad_mod files')
            nickname = path.parent.stem if path.parent.suffix.lower() == '.pretty' else 'User'
            self.imports.append({'path': path, 'source_id': nickname+':'+path.stem})
            existing.add(path)
        self.refresh_imports()

    def refresh_imports(self):
        self.import_list.DeleteAllItems()
        for i, item in enumerate(self.imports):
            self.import_list.InsertItem(i, item['source_id'])
            self.import_list.SetItem(i, 1, str(item['path']))
        self.invalidate()

    def on_add_files(self, event):
        with wx.FileDialog(self, 'Add definitions to archive and register', wildcard='KiCad footprints|*.kicad_mod',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.add_paths(dialog.GetPaths())
                except Exception as exc:
                    self.error(exc)

    def on_add_library(self, event):
        with wx.DirDialog(self, 'Add a .pretty library (every .kicad_mod in that folder)', style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                path = Path(dialog.GetPath())
                if path.suffix.lower() != '.pretty':
                    self.error('Select a .pretty library directory.'); return
                files = sorted(path.glob('*.kicad_mod'))
                if not files:
                    self.error('This library contains no .kicad_mod files.'); return
                try:
                    self.add_paths(files)
                except Exception as exc:
                    self.error(exc)

    def on_source_id(self, event):
        index = self.import_list.GetFirstSelected()
        if not 0 <= index < len(self.imports):
            return
        with wx.TextEntryDialog(self, 'Exact original ID to match on the board, e.g. Resistor_SMD:R_0402_1005Metric',
                                'Supplied definition source ID', self.imports[index]['source_id']) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                value = dialog.GetValue().strip()
                if value.count(':') != 1 or not all(value.split(':')) or any(ch in value for ch in '/\\\n\r'):
                    self.error('Use one nonempty Library:Name ID, not a file path.'); return
                self.imports[index]['source_id'] = value
                self.refresh_imports()

    def on_remove(self, event):
        index = self.import_list.GetFirstSelected()
        if 0 <= index < len(self.imports):
            del self.imports[index]
            self.refresh_imports()

    def on_preview(self, event):
        if self.busy:
            return
        self.valid = False; self.stop.clear(); self.set_busy(True)
        self.status.SetLabel('Capturing the PCB and checking ALL placed footprint models…')
        try:
            if self.bridge.footprints(False):
                sources, pool = self.bridge.sources(False, self.resolver)
            else:
                sources, pool = [], {}
            for source in sources:
                source['source_id'] = str(source['owner'].GetFPIDAsString())
            self.snapshot = self.bridge.board_text()
            # Supplied snapshots are captured before the worker; native expansion
            # stays on this thread even for variables only used by imported files.
            imports = []
            for item in self.imports:
                text = item['path'].read_text(encoding='utf-8')
                self.bridge.prepare_resolver(self.resolver, [n.arg().value(text) for n in parse(text).nodes(text, 'model')])
                imports.append({**item, 'text': text})
            prefer = self.mode.GetSelection() == 1
            ids = [item['source_id'] for item in imports]
            if prefer and len(set(ids)) != len(ids):
                raise ValueError('Multiple supplied files have the same Library:Name. Set distinct source IDs before matching.')
        except Exception as exc:
            self.set_busy(False); self.error(exc); return
        resolver, overrides, stop = self.resolver, self.overrides, self.stop
        def worker():
            records, instances, error = [], [], None
            try:
                planner = Planner(resolver)
                by_id = {}
                for index, item in enumerate(imports):
                    if stop.is_set():
                        raise InterruptedError('Package preview cancelled')
                    path = item['path']
                    plan = planner.scan(item['text'], item['source_id'], path.parent,
                                        overrides=overrides.get(str(path)), cancelled=stop.is_set)
                    plan.source_path = path
                    key = 'import-'+str(index+1)
                    record = {'key': key, 'name': 'I%04d_' % (index+1)+slug(path.stem),
                              'plan': plan, 'source_id': item['source_id'], 'origin': 'supplied definition'}
                    records.append(record); by_id[item['source_id']] = key
                for index, source in enumerate(sources):
                    if stop.is_set():
                        raise InterruptedError('Package preview cancelled')
                    plan = planner.scan(source['text'], source['name'], source['source_dir'], pool,
                                        overrides.get(source['key']), stop.is_set)
                    plan.owner = source['owner']
                    key = 'board-'+source['key']
                    record = {'key': key, 'name': 'B%04d_' % (index+1)+slug(source['name']),
                              'plan': plan, 'source_id': source['source_id'], 'origin': 'as-placed board snapshot'}
                    records.append(record)
                    target = by_id.get(source['source_id'], key) if prefer else key
                    instances.append(Instance(source['key'], plan, target, key))
            except Exception as exc:
                error = str(exc)
            wx.CallAfter(self.preview_done, records, instances, error)
        threading.Thread(target=worker, name='WayriCAD Embed3D-package-preview', daemon=True).start()

    def preview_done(self, records, instances, error):
        self.set_busy(False)
        if self.closing:
            self.EndModal(wx.ID_CANCEL); return
        self.records, self.instances = records, instances
        self.table.DeleteAllItems()
        names = {r['key']: r['name'] for r in records}
        targets = {i.snapshot_key: names.get(i.definition_key, '?') for i in instances}
        blocked = 0
        for index, record in enumerate(records):
            plan = record['plan']
            bad = [r for r in plan.rows if r.status != 'Embedded' and not (r.ready and r.checked)]
            blocked += len(bad)
            self.table.InsertItem(index, plan.name)
            self.table.SetItem(index, 1, str(len(plan.rows)))
            self.table.SetItem(index, 2, targets.get(record['key'], record['name']))
            self.table.SetItem(index, 3, '%d models unresolved' % len(bad) if bad else 'Ready · '+record['origin'])
        self.valid = not error and not blocked and bool(records)
        matched = sum(i.definition_key != i.snapshot_key for i in instances)
        self.status.SetLabel(error or ('%d board footprints · %d archived definitions · %d linked to supplied · %d unresolved models' %
                                      (len(instances), len(records), matched, blocked)))
        self.create.Enable(self.valid)
        if blocked:
            self.details.SetValue('Select a row for full missing-model details. Cancel this dialog and use All board footprints → '
                                  'Models folder / Find missing / Locate model in the main window. Those reviewed repairs are reused here. '
                                  'For a supplied footprint, repair/embed it using Footprint files mode first, then add it again. '
                                  'Incomplete packages are never produced.')
        if error:
            self.error(error)

    def on_select(self, event):
        index = self.table.GetFirstSelected()
        if not 0 <= index < len(self.records):
            return
        r = self.records[index]; plan = r['plan']
        lines = [r['origin']+': '+r['source_id'], 'Archived as: '+r['name'],
                 'Source file: '+str(plan.source_path or 'in-memory PCB; actual as-placed geometry')]
        for row in plan.rows:
            lines.append('[%s] %s\n%s' % (row.status, row.reference, row.detail))
        self.details.SetValue('\n'.join(lines))

    def on_create(self, event):
        if not self.valid or self.busy:
            return
        filename = str(self.bridge.board.GetFileName())
        if not filename:
            self.error('Give the PCB a filename with Save As before packaging. No board was changed.'); return
        source = Path(filename)
        with wx.DirDialog(self, 'Choose the parent directory for a NEW package folder',
                          defaultPath=str(source.parent), style=wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            parent = Path(dialog.GetPath())
        with wx.TextEntryDialog(self, 'New folder name (existing folders are never overwritten)',
                                'New PCB package', slug(source.stem)+'_embedded') as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                folder = safe_name(dialog.GetValue().strip())
            except ValueError as exc:
                self.error(exc); return
        destination = parent/folder
        if destination.exists():
            self.error('That folder already exists. Choose a new name.'); return
        matched = sum(i.definition_key != i.snapshot_key for i in self.instances)
        message = ('Create a new PCB package in:\n'+str(destination)+'\n\n'
                   'The PCB will contain footprint snapshots and model bytes in Board Setup → Embedded Files. '
                   'Placed footprint IDs will point to a project-local .pretty library reconstructed from those snapshots.\n\n'
                   'Your open PCB and original libraries are NOT modified. Open the new PCB after completion. '
                   'Saved .kicad_pro/.kicad_dru settings are copied when present; schematic files and schematic Footprint '
                   'fields are NOT copied or changed. Updating from the old schematic can revert the new links.')
        if matched:
            message += ('\n\n%d instances will link to supplied definitions. Their current pads, nets, placements and model '
                        'transforms remain as placed, even if the supplied definition differs. Later Update Footprints '
                        'from Library may replace geometry or models. Review that operation separately.' % matched)
        with wx.MessageDialog(self, message, 'Confirm PCB archive and relink', wx.OK | wx.CANCEL | wx.ICON_INFORMATION) as dialog:
            dialog.SetOKLabel('Create new package')
            if dialog.ShowModal() != wx.ID_OK:
                return
        self.set_busy(True); self.stop.clear()
        self.status.SetLabel('Normalizing library snapshots with KiCad. The active board is not being modified…')
        try:
            verify_sources([r['plan'] for r in self.records])
            current = self.bridge.board_text()
            if semantic(current) != semantic(self.snapshot):
                raise ValueError('The board changed since preview. Preview again before packaging.')
            with wx.BusyCursor():
                definitions = self.bridge.normalize_definitions(self.records)
            library_name = 'WayriCAD_Embed3D_'+slug(source.stem, 50)
            safe_name(library_name)
            sidecars = {source.with_suffix(s).name: source.with_suffix(s).read_bytes()
                        for s in ('.kicad_pro', '.kicad_dru') if source.with_suffix(s).is_file()}
            snapshot, instances = self.snapshot, list(self.instances)
        except Exception as exc:
            self.valid = False; self.set_busy(False); self.log.exception('Native package preparation failed'); self.error(exc); return
        self.status.SetLabel('Embedding footprint snapshots and deduplicating board-level 3D payloads…')
        stop = self.stop
        def worker():
            try:
                package = compose(snapshot, instances, definitions, library_name)
                if stop.is_set():
                    raise InterruptedError('Package creation cancelled before publishing')
                error = None
            except Exception as exc:
                package, error = None, str(exc)
            wx.CallAfter(self.composition_done, package, destination, source.name, sidecars, error)
        threading.Thread(target=worker, name='WayriCAD Embed3D-package-compose', daemon=True).start()

    def composition_done(self, package, destination, board_name, sidecars, error):
        if self.closing:
            self.set_busy(False); self.EndModal(wx.ID_CANCEL); return
        if error:
            self.valid = False; self.set_busy(False); self.error(error); return
        self.status.SetLabel('KiCad-native parse/save validation before publishing the new package…')
        try:
            with wx.BusyCursor():
                path = write_package(package, destination, board_name, sidecars, self.bridge.validate_package)
            self.result_message = ('Created:\n'+str(path)+'\n\nOpen this NEW PCB; the original PCB is unchanged.\n'
                                   'Footprint definitions and 3D bytes are inside its Board Setup → Embedded Files.\n'
                                   'Footprint library links target the included '+package.library_name+'.pretty library.\n\n'
                                   'Keep the package folder together for library editing. After moving only the PCB, use '
                                   'More → Rebuild embedded library from PCB to reconstruct the local library.\n'
                                   'The schematic was not edited; synchronize its Footprint fields deliberately before updating the PCB.')
            self.set_busy(False); self.EndModal(wx.ID_OK)
        except Exception as exc:
            self.log.exception('PCB package publication failed')
            self.valid = False; self.set_busy(False); self.error(exc)
