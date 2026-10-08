"""Review-first, offline import of source instances into an existing saved project."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from types import ModuleType

import wx

if __package__ in (None, ''):
    # Direct execution needs package-relative imports, but the installed
    # package __init__ registers a PCB Editor action and must not run here.
    __package__ = '_fusion_insertion_standalone'
    package = ModuleType(__package__)
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[__package__] = package

from .model import MAX_INSTANCES, MergeError, SourceSpec, validate_source_aliases
from .variants import DEFAULT, detect_variants


def project_identity(path):
    """Treat the three KiCad companion paths as one project identity."""
    if not path:
        return ''
    return str(Path(path).with_suffix('.kicad_pro').resolve()).casefold()


def fresh_directory(parent, name):
    """Never silently reuse a previous candidate or extracted-source folder."""
    root = Path(parent) / name
    candidate = root
    number = 2
    while candidate.exists() or candidate.with_name(candidate.name+'-import-plan.json').exists():
        candidate = root.with_name(f'{name}-{number}')
        number += 1
    return candidate


class SectionBatchDialog(wx.Dialog):
    """Materialize selected schematic sheet occurrences as reviewed source copies."""
    def __init__(self, parent, source, cli_path='', max_sources=MAX_INSTANCES):
        super().__init__(parent, title='Choose subsheets — '+source.alias,
                         size=(850, 700), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.source, self.cli_path = source, cli_path
        self.max_sources = max_sources
        self.instances = []
        self.plan = self.result = None
        self._closed = False
        self.busy = False
        box = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='Select one or more exact sheet occurrences. Each selected hierarchy becomes a separate schematic-only source copy. Ancestor and descendant selections cannot overlap. Review the preview before creating copies.')
        note.Wrap(790)
        box.Add(note, 0, wx.ALL | wx.EXPAND, 12)
        self.sheets = wx.CheckListBox(self)
        self.sheets.Bind(wx.EVT_CHECKLISTBOX, self.invalidate)
        box.Add(self.sheets, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.report = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        box.Add(self.report, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.status = wx.StaticText(self, label='Reading saved sheet occurrences…')
        box.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button = wx.Button(self, label='Preview selected subsheets')
        self.create_button = wx.Button(self, label='Create reviewed source copies…')
        close = wx.Button(self, wx.ID_CANCEL, 'Close')
        self.preview_button.Bind(wx.EVT_BUTTON, self.preview_selection)
        self.create_button.Bind(wx.EVT_BUTTON, self.create_copies)
        close.Bind(wx.EVT_BUTTON, self.close)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        for button in (self.preview_button, self.create_button, close):
            bar.Add(button, 0, wx.RIGHT, 8)
        box.Add(bar, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(box)
        self.preview_button.Disable()
        self.create_button.Disable()
        self.defer(self.load_instances)

    def defer(self, callback, *args):
        def deliver():
            if not self._closed and bool(self):callback(*args)
        if not self._closed:wx.CallAfter(deliver)

    def on_destroy(self,event):
        if event.GetEventObject() is self:self._closed=True
        event.Skip()

    def run(self, action, done):
        if self.busy:
            return
        self.busy = True
        self.sheets.Disable(); self.preview_button.Disable(); self.create_button.Disable()
        def worker():
            try:
                result = action()
                self.defer(self.finish, done, result, None)
            except Exception as exc:
                self.defer(self.finish, done, None, str(exc))
        threading.Thread(target=worker, name='FusionSectionBatch', daemon=True).start()

    def finish(self, done, result, error):
        self.busy = False
        self.sheets.Enable(); self.preview_button.Enable()
        if error:
            self.plan=None;self.create_button.Disable()
            self.status.SetLabel(error)
            from .error_handling import show_error
            show_error(self,error,'Subsheet operation stopped')
            return
        done(result)

    def load_instances(self):
        from .sections import list_sections
        def done(instances):
            self.instances = instances
            self.sheets.Set([f"{item['display_path']} — {item['descendant_symbols']} symbols — {item['sheet_path']}"
                             for item in instances])
            self.status.SetLabel('Check the exact sheet occurrences to import.')
        self.run(lambda: list_sections(self.source), done)

    def selected_paths(self):
        paths = [item['sheet_path'] for index, item in enumerate(self.instances)
                 if self.sheets.IsChecked(index)]
        if not paths:
            raise MergeError('Select at least one subsheet occurrence.')
        if len(paths) > self.max_sources:
            raise MergeError(f'Only {self.max_sources} incoming instance slots remain.')
        return paths

    def invalidate(self, event=None):
        self.plan = None
        self.create_button.Disable()
        self.report.Clear()
        self.status.SetLabel('Selection changed. Preview the selected subsheets again.')
        if event is not None:
            event.Skip()

    def preview_selection(self, event):
        try:
            paths = self.selected_paths()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Choose subsheets', wx.OK | wx.ICON_WARNING, self)
            return
        from .sections import preview_schematic_sections
        self.invalidate()
        self.status.SetLabel('Checking selected schematic hierarchies…')
        def done(plan):
            self.plan = plan
            self.report.SetValue(json.dumps(plan.get('report', plan), indent=2, default=str))
            self.create_button.Enable()
            self.status.SetLabel('Preview ready. Review the extracted source report before creating copies.')
        self.run(lambda: preview_schematic_sections(self.source, paths, self.cli_path), done)

    def create_copies(self, event):
        if self.plan is None or self.busy:
            return
        with wx.DirDialog(self, 'Choose parent folder for NEW extracted source copies') as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = fresh_directory(dialog.GetPath(), Path(self.source.project).stem+'-FusionSheets')
        from .sections import apply_schematic_sections
        plan = self.plan
        self.status.SetLabel('Creating reviewed schematic source copies…')
        def done(specs):
            self.result = specs
            self.EndModal(wx.ID_OK)
        self.run(lambda: apply_schematic_sections(plan, destination), done)

    def close(self, event):
        if self.busy:
            if isinstance(event, wx.CloseEvent) and event.CanVeto():
                event.Veto()
            elif isinstance(event,wx.CloseEvent):
                self._closed=True;event.Skip()
            return
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


class InsertionDialog(wx.Dialog):
    """Preview a candidate, then explicitly apply it to a saved, closed target."""
    def __init__(self, parent=None, target_path='', sources=(), cli_path='', embedded=False):
        super().__init__(parent, title='Import into existing project — offline review',
                         size=(940, 780), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        from .variant_import_gui import apply_window_icon
        apply_window_icon(self)
        self.cli_path = cli_path
        self.embedded = embedded
        self.sources = []
        self.plan = self.applied = None
        self.plan_file = None
        self._closed = False
        self.busy = False
        self._suspend_invalidation = False
        root = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='Import one or more whole projects or reviewed subsheet copies into an existing saved project. Preview creates a separate candidate folder. Apply checks that saved inputs are unchanged, backs up the target and updates its files offline. Close target editors before Apply, then reopen the project in KiCad.')
        note.Wrap(880)
        root.Add(note, 0, wx.ALL | wx.EXPAND, 12)
        target_row = wx.BoxSizer(wx.HORIZONTAL)
        target_row.Add(wx.StaticText(self, label='Existing target project'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.target = wx.FilePickerCtrl(self, path=target_path,
            message='Choose the saved target project, root schematic or PCB',
            wildcard='KiCad projects (*.kicad_pro)|*.kicad_pro|Root schematics (*.kicad_sch)|*.kicad_sch|PCBs (*.kicad_pcb)|*.kicad_pcb',
            style=wx.FLP_OPEN | wx.FLP_USE_TEXTCTRL)
        self.target.Bind(wx.EVT_FILEPICKER_CHANGED, self.on_target_changed)
        target_row.Add(self.target, 1, wx.EXPAND)
        root.Add(target_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        root.Add(wx.StaticText(self, label='Incoming instances for a new preview (loaded plan sources are listed in its report; the target is always excluded)'),
                 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.source_list = wx.CheckListBox(self)
        self.source_list.Bind(wx.EVT_CHECKLISTBOX, self.invalidate)
        root.Add(self.source_list, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        source_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.source_buttons = []
        for label, handler in [('Add whole project(s)…', self.add_projects),
                               ('Add subsheet(s)…', self.add_subsheets),
                               ('Add routed section…', self.add_routed_section),
                               ('Variant destination…', self.edit_variant_import),
                               ('Remove highlighted', self.remove_source)]:
            button = wx.Button(self, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            self.source_buttons.append(button)
            source_bar.Add(button, 0, wx.RIGHT, 8)
        root.Add(source_bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout_row = wx.BoxSizer(wx.HORIZONTAL)
        self.include_layout = wx.CheckBox(self, label='Include routed PCB layout')
        self.include_layout.SetValue(True)
        self.include_layout.Bind(wx.EVT_CHECKBOX, self.invalidate)
        layout_row.Add(self.include_layout, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 20)
        layout_row.Add(wx.StaticText(self, label='Gap (mm)'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.gap = wx.SpinCtrlDouble(self, min=0, max=1000, initial=10, inc=1)
        self.gap.Bind(wx.EVT_SPINCTRLDOUBLE, self.invalidate)
        self.gap.Bind(wx.EVT_TEXT, self.invalidate)
        layout_row.Add(self.gap, 0)
        root.Add(layout_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        destination = wx.BoxSizer(wx.HORIZONTAL)
        destination.Add(wx.StaticText(self, label='Review candidate parent'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        default_parent = str(Path(target_path).resolve().parent.parent) if target_path else str(Path.home())
        self.candidate_parent = wx.DirPickerCtrl(self, path=default_parent,
            message='Choose a parent folder for a NEW review candidate')
        self.candidate_parent.Bind(wx.EVT_DIRPICKER_CHANGED, self.invalidate)
        destination.Add(self.candidate_parent, 1, wx.EXPAND | wx.RIGHT, 10)
        destination.Add(wx.StaticText(self, label='Folder name'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        name = Path(target_path).stem if target_path else 'Target'
        self.candidate_name = wx.TextCtrl(self, value=name+'-FusionReview', size=(190, -1))
        self.candidate_name.Bind(wx.EVT_TEXT, self.invalidate)
        destination.Add(self.candidate_name, 0)
        root.Add(destination, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.report = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        root.Add(self.report, 2, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.status = wx.StaticText(self, label='Choose incoming instances, then preview the candidate.')
        root.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.closed = wx.CheckBox(self, label='I saved and closed the target and incoming KiCad editors; the target will be backed up before offline Apply.')
        self.closed.Bind(wx.EVT_CHECKBOX, self.on_acknowledge)
        if embedded:
            self.closed.Disable()
        root.Add(self.closed, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        review_bar = wx.BoxSizer(wx.HORIZONTAL)
        action_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button = wx.Button(self, label='Preview candidate')
        self.open_button = wx.Button(self, label='Open candidate folder')
        self.load_button = wx.Button(self, label='Load reviewed plan…')
        self.handoff_button = wx.Button(self, label='Open standalone Apply window')
        self.apply_button = wx.Button(self, label='Apply to existing project…')
        close = wx.Button(self, wx.ID_CANCEL, 'Close')
        self.preview_button.Bind(wx.EVT_BUTTON, self.preview_import)
        self.open_button.Bind(wx.EVT_BUTTON, self.open_candidate)
        self.load_button.Bind(wx.EVT_BUTTON, self.load_reviewed_plan)
        self.handoff_button.Bind(wx.EVT_BUTTON, self.open_standalone)
        self.apply_button.Bind(wx.EVT_BUTTON, self.apply_import)
        close.Bind(wx.EVT_BUTTON, self.close)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        for button in (self.preview_button, self.open_button, self.load_button):
            review_bar.Add(button, 0, wx.RIGHT, 8)
        for button in (self.handoff_button, self.apply_button, close):
            action_bar.Add(button, 0, wx.RIGHT, 8)
        root.Add(review_bar, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.ALIGN_RIGHT, 12)
        root.Add(action_bar, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(root)
        self.open_button.Disable(); self.handoff_button.Disable(); self.apply_button.Disable()
        if not embedded:
            self.handoff_button.Hide()
        self.add_specs(sources, invalidate=False)
        self.CentreOnParent()

    def on_acknowledge(self, event=None):
        if self.plan is not None and self.closed.GetValue() and not self.busy and self.applied is None and not self.embedded:
            self.apply_button.Enable()
        else:
            self.apply_button.Disable()
        if event is not None:
            event.Skip()

    def on_target_changed(self, event=None):
        if not self._suspend_invalidation:
            target = self.target.GetPath()
            if target:
                self._suspend_invalidation = True
                try:
                    self.candidate_parent.SetPath(str(Path(target).resolve().parent.parent))
                    self.candidate_name.SetValue(Path(target).stem+'-FusionReview')
                finally:
                    self._suspend_invalidation = False
            self.invalidate()
        if event is not None:
            event.Skip()

    def invalidate(self, event=None):
        if self._suspend_invalidation:
            if event is not None:
                event.Skip()
            return
        self.plan = None
        self.plan_file = None
        self.closed.SetValue(False)
        self.apply_button.Disable(); self.open_button.Disable(); self.handoff_button.Disable()
        self.report.Clear()
        self.status.SetLabel('Inputs changed. Preview a new candidate before Apply.')
        if event is not None:
            event.Skip()

    def refresh_sources(self, checked=None):
        if checked is None:
            checked = [self.source_list.IsChecked(index) for index in range(self.source_list.GetCount())]
        from .variant_import_gui import disposition_label
        self.source_list.Set([f'{spec.alias} — {spec.kind.title()} — {spec.variant or "[Choose variant]"} → {disposition_label(spec)} — {spec.project}'
                              for spec in self.sources])
        for index in range(len(self.sources)):
            self.source_list.Check(index, checked[index] if index < len(checked) else True)

    def edit_variant_import(self,event=None):
        if self.busy:return
        index=self.source_list.GetSelection()
        if index<0:
            wx.MessageBox('Highlight an incoming source first.','Variant destination',wx.OK | wx.ICON_INFORMATION,self)
            return
        try:
            from .variant_import_gui import choose_variant_import,destination_names
            result=choose_variant_import(self,self.sources[index],destination_names(self.target.GetPath(),self.sources))
            if result is not None:
                self.sources[index]=result
                self.refresh_sources();self.source_list.SetSelection(index);self.invalidate()
        except Exception as exc:
            wx.MessageBox(str(exc),'Variant destination',wx.OK | wx.ICON_ERROR,self)

    def unique_alias(self, desired, used):
        base = re.sub(r'[^A-Za-z0-9_]', '_', desired)[:24]
        if not base or not base[0].isalpha():
            base = ('D_'+base)[:24]
        alias = base
        number = 2
        while alias.casefold() in used:
            suffix = f'_{number}'
            alias = base[:24-len(suffix)] + suffix
            number += 1
        used.add(alias.casefold())
        return alias

    def add_specs(self, specs, invalidate=True):
        incoming = [copy.deepcopy(spec) for spec in specs
                    if project_identity(spec.project) != project_identity(self.target.GetPath())]
        if len(self.sources)+len(incoming) > MAX_INSTANCES:
            raise MergeError(f'A maximum of {MAX_INSTANCES} incoming instances is allowed.')
        used = {spec.alias.casefold() for spec in self.sources}
        for spec in incoming:
            spec.alias = self.unique_alias(spec.alias, used)
        checked = [self.source_list.IsChecked(index) for index in range(self.source_list.GetCount())]
        self.sources.extend(incoming)
        self.refresh_sources(checked + [True] * len(incoming))
        if invalidate:
            self.invalidate()

    def add_projects(self, event):
        with wx.FileDialog(self, 'Select incoming KiCad project(s)',
                           wildcard='KiCad projects (*.kicad_pro)|*.kicad_pro|Root schematics (*.kicad_sch)|*.kicad_sch|PCBs (*.kicad_pcb)|*.kicad_pcb',
                           style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            paths = dialog.GetPaths()
        try:
            if len(self.sources)+len(paths) > MAX_INSTANCES:
                raise MergeError(f'A maximum of {MAX_INSTANCES} incoming instances is allowed.')
            pending = []
            for path in paths:
                from .source_detection import choose_source
                detected=choose_source(self,path)
                if detected is None:continue
                if detected.kind=='layout':
                    from .board_layout_gui import LayoutImportDialog
                    dialog=LayoutImportDialog(self,detected.project,self.target.GetPath(),self.cli_path)
                    try:dialog.ShowModal()
                    finally:dialog.Destroy()
                    continue
                path=detected.project
                if not detected.has_layout:self.include_layout.SetValue(False)
                if project_identity(path) == project_identity(self.target.GetPath()):
                    continue
                spec = SourceSpec(path, Path(path).stem)
                spec.selection=detected.selection
                names = detect_variants(spec)
                if names == [DEFAULT]:
                    spec.variant = DEFAULT
                else:
                    from .variant_import_gui import choose_variant_import,destination_names
                    chosen=choose_variant_import(self,spec,destination_names(self.target.GetPath(),self.sources+pending))
                    if chosen is None:continue
                    spec=chosen
                pending.append(spec)
            self.add_specs(pending)
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot add incoming projects', wx.OK | wx.ICON_ERROR, self)

    def choose_project_source(self):
        eligible = [spec for spec in self.sources if spec.kind == 'project'
                    and project_identity(spec.project) != project_identity(self.target.GetPath())]
        if not eligible:
            raise MergeError('Add an incoming whole project first, then select one of its subsheets.')
        labels = [f'{spec.alias} — {spec.project}' for spec in eligible]
        with wx.SingleChoiceDialog(self, 'Choose the source project for subsheet extraction',
                                   'Source project', labels) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            return eligible[dialog.GetSelection()]

    def add_subsheets(self, event):
        try:
            remaining = MAX_INSTANCES-len(self.sources)
            if remaining < 1:
                raise MergeError(f'A maximum of {MAX_INSTANCES} incoming instances is allowed.')
            source = self.choose_project_source()
            if source is None:
                return
            dialog = SectionBatchDialog(self, source, self.cli_path, max_sources=remaining)
            try:
                if dialog.ShowModal() == wx.ID_OK and dialog.result:
                    self.add_specs(dialog.result)
                    self.include_layout.SetValue(False)
                    self.status.SetLabel(f'Added {len(dialog.result)} reviewed schematic subsheet copies. PCB layout is off for this import; preview the candidate.')
            finally:
                dialog.Destroy()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot add subsheets', wx.OK | wx.ICON_ERROR, self)

    def add_routed_section(self, event):
        try:
            if len(self.sources) >= MAX_INSTANCES:
                raise MergeError(f'A maximum of {MAX_INSTANCES} incoming instances is allowed.')
            source = self.choose_project_source()
            if source is None:
                return
            from .section_gui import SectionDialog
            dialog = SectionDialog(self, source, self.cli_path)
            try:
                if dialog.ShowModal() == wx.ID_OK and dialog.result:
                    self.add_specs([dialog.result])
                    self.status.SetLabel('Added reviewed routed section copy. Preview the import candidate.')
            finally:
                dialog.Destroy()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot add routed section', wx.OK | wx.ICON_ERROR, self)

    def remove_source(self, event):
        index = self.source_list.GetSelection()
        if index == wx.NOT_FOUND:
            return
        checked = [self.source_list.IsChecked(row) for row in range(self.source_list.GetCount()) if row != index]
        self.sources.pop(index)
        self.refresh_sources(checked)
        self.invalidate()

    def selected_sources(self):
        target = self.target.GetPath()
        if not target:
            raise MergeError('Choose the existing target project.')
        selected = [copy.deepcopy(spec) for index, spec in enumerate(self.sources)
                    if self.source_list.IsChecked(index)
                    and project_identity(spec.project) != project_identity(target)]
        if not selected:
            raise MergeError('Check at least one incoming source other than the target.')
        if len(selected) > MAX_INSTANCES:
            raise MergeError(f'A maximum of {MAX_INSTANCES} incoming instances is allowed.')
        validate_source_aliases(selected)
        if any(spec.variant is None for spec in selected):
            raise MergeError('Choose a variant for every incoming instance before preview.')
        if self.include_layout.GetValue():
            missing = [spec.alias for spec in selected if not Path(spec.project).with_suffix('.kicad_pcb').is_file()]
            if missing:
                raise MergeError('These incoming instances have no saved PCB: '+', '.join(missing)+'. Uncheck Include routed PCB layout for a schematic-only import.')
        return selected

    def defer(self, callback, *args):
        def deliver():
            if not self._closed and bool(self):callback(*args)
        if not self._closed:wx.CallAfter(deliver)

    def on_destroy(self,event):
        if event.GetEventObject() is self:self._closed=True
        event.Skip()

    def run(self, action, done):
        if self.busy:
            return
        self.busy = True
        for control in (self.target, self.source_list, self.include_layout, self.gap,
                        self.candidate_parent, self.candidate_name, self.closed,
                        self.preview_button, self.apply_button, self.load_button,
                        self.handoff_button, self.open_button, *self.source_buttons):
            control.Disable()
        def worker():
            try:
                result = action()
                self.defer(self.finish, done, result, None)
            except Exception as exc:
                self.defer(self.finish, done, None, str(exc))
        threading.Thread(target=worker, name='FusionExistingImport', daemon=True).start()

    def finish(self, done, result, error):
        self.busy = False
        for control in (self.target, self.source_list, self.include_layout, self.gap,
                        self.candidate_parent, self.candidate_name, self.preview_button,
                        self.load_button, *self.source_buttons):
            control.Enable()
        if not self.embedded:
            self.closed.Enable()
        if self.plan is not None:
            self.open_button.Enable(); self.handoff_button.Enable()
            self.on_acknowledge()
        if error:
            self.invalidate()
            self.status.SetLabel(error)
            from .error_handling import show_error
            show_error(self,error,'Project import stopped')
            return
        done(result)

    def preview_import(self, event):
        if self.busy:
            return
        try:
            sources = self.selected_sources()
            name = self.candidate_name.GetValue().strip()
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name):
                raise MergeError('Candidate folder name must start with a letter and use at most 64 letters, digits, underscores or hyphens.')
            parent = self.candidate_parent.GetPath()
            if not parent or not Path(parent).is_dir():
                raise MergeError('Choose an existing parent folder for review candidates.')
            candidate = fresh_directory(parent, name)
            target = self.target.GetPath()
            include_layout = self.include_layout.GetValue()
            gap = self.gap.GetValue()
        except Exception as exc:
            wx.MessageBox(str(exc), 'Check import settings', wx.OK | wx.ICON_WARNING, self)
            return
        from .insertion import preview_import
        self.invalidate()
        self.status.SetLabel('Building and validating a separate review candidate…')
        def done(plan):
            try:
                path = self.save_plan(plan)
            except Exception as exc:
                self.status.SetLabel('Candidate created, but its offline plan could not be saved: '+str(exc))
                self.report.SetValue(json.dumps(plan.get('report', plan), indent=2, default=str))
                wx.MessageBox(str(exc), 'Cannot save reviewed import plan', wx.OK | wx.ICON_ERROR, self)
                return
            self.plan = plan
            self.plan_file = path
            self.report.SetValue(self.plan_summary(plan, path))
            self.status.SetLabel('Candidate ready. Review it, then open the standalone Apply window and close target editors.'
                                 if self.embedded else 'Candidate ready. Review it and close target editors before Apply.')
            self.open_button.Enable(); self.handoff_button.Enable()
            self.on_acknowledge()
        def build():
            if any((spec.selection and not spec.selection.get('whole_project',True)) or
                   (Path(spec.project).suffix.lower()=='.kicad_sch' and not Path(spec.project).with_suffix('.kicad_pro').is_file())
                   for spec in sources):
                from .workspace import materialize_sources
                prepared, originals=materialize_sources(sources,include_layout,Path(candidate).parent,self.cli_path)
                plan=preview_import(target,prepared,include_layout,candidate,cli_path=self.cli_path,gap_mm=gap)
                plan['selection_originals']=originals
                # apply_import checks source_hashes as well as materialized copies.
                plan['source_hashes'].extend(originals)
                return plan
            return preview_import(target,sources,include_layout,candidate,cli_path=self.cli_path,gap_mm=gap)
        self.run(build, done)

    def open_candidate(self, event):
        if self.plan is not None:
            wx.LaunchDefaultApplication(str(self.plan['candidate_directory']))

    @staticmethod
    def plan_summary(plan, path):
        roots = [entry['root'] for entry in plan.get('source_hashes', [])]
        source_lines = '\n'.join('  '+str(root) for root in roots) or '  See reviewed plan'
        return (f'Offline plan: {path}\nTarget: {plan["target_project"]}\n'
                f'Candidate: {plan["candidate_directory"]}\nIncoming source folders:\n{source_lines}\n\n'
                + json.dumps(plan.get('report', plan), indent=2, default=str))

    @staticmethod
    def save_plan(plan):
        candidate = Path(plan['candidate_directory'])
        path = candidate.with_name(candidate.name+'-import-plan.json')
        document = {'format': 'wayri-fusion-import-plan-v1', 'plan': plan}
        # Exclusive creation keeps previous reviewed plans intact.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2)
            stream.write('\n')
        return path

    def load_reviewed_plan(self, event):
        with wx.FileDialog(self, 'Load a reviewed offline import plan',
                           wildcard='Import plans (*.json)|*.json',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        try:
            self.load_plan_path(path)
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot load import plan', wx.OK | wx.ICON_ERROR, self)

    def load_plan_path(self, path):
        document = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(document, dict) or document.get('format') != 'wayri-fusion-import-plan-v1':
            raise MergeError('Choose a Wayri Fusion reviewed import plan.')
        plan = document.get('plan')
        if not isinstance(plan, dict) or not all(key in plan for key in ('target_project', 'candidate_directory', 'report')):
            raise MergeError('The reviewed import plan is incomplete.')
        self._suspend_invalidation = True
        try:
            self.target.SetPath(str(plan['target_project']))
            self.candidate_parent.SetPath(str(Path(plan['candidate_directory']).parent))
            self.candidate_name.SetValue(Path(plan['candidate_directory']).name)
            self.include_layout.SetValue(bool(plan['report'].get('include_layout', False)))
            if 'gap_mm' in plan:
                self.gap.SetValue(float(plan['gap_mm']))
            self.sources = []
            self.refresh_sources([])
        finally:
            self._suspend_invalidation = False
        self.plan = plan
        self.plan_file = Path(path)
        self.closed.SetValue(False)
        self.report.SetValue(self.plan_summary(plan, path))
        self.open_button.Enable(); self.handoff_button.Enable()
        self.on_acknowledge()
        self.status.SetLabel('Reviewed plan loaded. Close target editors, check the acknowledgement, then Apply.'
                             if not self.embedded else 'Reviewed plan loaded. Open the standalone Apply window and close target editors.')

    @staticmethod
    def python_launcher():
        executable = Path(sys.executable)
        if executable.stem.casefold().startswith('python'):
            if sys.platform == 'win32' and executable.with_name('pythonw.exe').is_file():
                return executable.with_name('pythonw.exe')
            return executable
        for name in ('pythonw.exe', 'python.exe', 'python3', 'python'):
            candidate = executable.with_name(name)
            if candidate.is_file():
                return candidate
        raise MergeError('Cannot locate a Python executable next to the KiCad editor. Open this plugin file with KiCad Python and pass --plan followed by the displayed plan path.')

    def open_standalone(self, event):
        if self.plan_file is None:
            return
        try:
            launcher = self.python_launcher()
            subprocess.Popen([str(launcher), str(Path(__file__).resolve()), '--plan', str(self.plan_file)],
                             close_fds=True)
            self.status.SetLabel('Standalone Apply window opened. Close this dialog and the target KiCad editors before applying there.')
        except Exception as exc:
            wx.MessageBox(str(exc), 'Cannot open standalone Apply window', wx.OK | wx.ICON_ERROR, self)

    def apply_import(self, event):
        if self.embedded or self.busy or self.plan is None or not self.closed.GetValue():
            return
        target = self.plan['target_project']
        message = (f'Apply the reviewed candidate to the saved target?\n\n{target}\n\n'
                   'The plugin will check saved-file hashes again and back up the target. '
                   'Keep its schematic and PCB editors closed until Apply finishes.')
        if wx.MessageBox(message, 'Apply reviewed import',
                         wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
            return
        from .insertion import apply_import
        plan = self.plan
        self.status.SetLabel('Checking saved inputs, backing up and applying offline…')
        def done(result):
            self.applied = result
            self.plan = None
            self.apply_button.Disable(); self.open_button.Disable()
            self.report.SetValue(json.dumps(result, indent=2, default=str))
            self.status.SetLabel(f"Applied with backup at {result['backup_directory']}. Reopen the target in KiCad and review ERC/DRC.")
            wx.MessageBox('Import applied with a backup. Reopen the target project in KiCad and review its schematic, PCB, ERC and DRC.',
                          'Import complete', wx.OK | wx.ICON_INFORMATION, self)
        self.run(lambda: apply_import(plan), done)

    def close(self, event):
        if self.busy:
            if isinstance(event, wx.CloseEvent) and event.CanVeto():
                event.Veto()
            elif isinstance(event,wx.CloseEvent):
                self._closed=True;event.Skip()
            return
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Apply a reviewed Wayri Fusion import after closing KiCad editors.')
    parser.add_argument('--plan', help='Reviewed import plan JSON created by Preview candidate')
    arguments = parser.parse_args(argv)
    app = wx.App(False)
    dialog = InsertionDialog()
    try:
        if arguments.plan:
            try:
                dialog.load_plan_path(arguments.plan)
            except Exception as exc:
                wx.MessageBox(str(exc), 'Cannot load reviewed import plan', wx.OK | wx.ICON_ERROR, dialog)
                return 1
        dialog.ShowModal()
    finally:
        dialog.Destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
