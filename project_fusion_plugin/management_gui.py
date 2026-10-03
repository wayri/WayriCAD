"""Source-copy repair and selected-configuration BOM/field review dialogs."""
from pathlib import Path
import json
import threading
import traceback
import wx

from .model import MergeError
from .repair import preview_repair, apply_repair
from .bom_fields import inventory, grouped_bom, export_csv, preview_fields, apply_to_copies
from .dependencies import preview_dependencies,apply_dependencies


class RepairDialog(wx.Dialog):
    def __init__(self, parent, spec, cli_path=''):
        super().__init__(parent, title='Repair a new source copy — ' + spec.alias,
                         size=(940, 720), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.spec, self.cli_path = spec, cli_path
        self.plan = None
        self.result = None
        self.busy = False
        panel = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='Preview first. Compile the selected variant as Default in a NEW copy; retain placed geometry, repair unambiguous links, add missing parts from matching placed templates and stop for review when changed connections affect existing copper. Placement, routing, DRC and engineering review remain required.')
        note.Wrap(880)
        panel.Add(note, 0, wx.ALL | wx.EXPAND, 12)
        self.blank = wx.CheckBox(self, label='Retain placed footprints where the selected schematic footprint is blank')
        self.blank.Bind(wx.EVT_CHECKBOX, lambda event: self.invalidate())
        panel.Add(self.blank, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.report = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        panel.Add(self.report, 1, wx.ALL | wx.EXPAND, 12)
        self.status = wx.StaticText(self, label='Original project: ' + spec.project)
        panel.Add(self.status, 0, wx.ALL | wx.EXPAND, 12)
        self.preview = wx.Button(self, label='Preview repair')
        self.create = wx.Button(self, label='Create reviewed repair copy…')
        self.cancel = wx.Button(self, wx.ID_CANCEL, 'Close')
        self.create.Disable()
        self.preview.Bind(wx.EVT_BUTTON, self.on_preview)
        self.create.Bind(wx.EVT_BUTTON, self.on_create)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self.preview, self.create, self.cancel): row.Add(button, 0, wx.RIGHT, 8)
        panel.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(panel)
        self.CentreOnParent()

    def invalidate(self):
        self.plan = None
        self.create.Disable()
        self.report.Clear()
        self.status.SetLabel('Choices changed. Preview again.')

    def run(self, action, done):
        if self.busy: return
        self.busy = True
        for control in (self.preview, self.create, self.cancel, self.blank): control.Disable()
        self.status.SetLabel('Reading and validating source copy…')
        def worker():
            try: result, error = action(), None
            except Exception as exc: result, error = None, str(exc)
            wx.CallAfter(self.finish, done, result, error)
        threading.Thread(target=worker, name='FusionSourceRepair', daemon=True).start()

    def finish(self, done, result, error):
        self.busy = False
        for control in (self.preview, self.cancel, self.blank): control.Enable()
        if error:
            self.plan = None; self.create.Disable()
            self.status.SetLabel('Stopped; originals remain unchanged.')
            self.report.SetValue(error)
            return
        done(result)

    def on_preview(self, event):
        retain = self.blank.GetValue()
        def done(plan):
            self.plan = plan
            self.report.SetValue(json.dumps(plan.report, indent=2, ensure_ascii=False))
            self.create.Enable()
            self.status.SetLabel('Preview ready. Creating a copy applies these repairs; it does not complete routing.')
        self.run(lambda: preview_repair(self.spec, self.cli_path, retain), done)

    def on_create(self, event):
        if self.plan is None: return
        with wx.DirDialog(self, 'Choose a parent folder for a NEW repair-copy folder') as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            parent = Path(dialog.GetPath())
        destination = parent / (Path(self.spec.project).stem + '-FusionRepair')
        plan = self.plan
        def done(result):
            self.result = result[0]
            self.EndModal(wx.ID_OK)
        self.run(lambda: apply_repair(plan, destination, self.cli_path), done)

    def on_close(self, event):
        if self.busy:
            if event.CanVeto(): event.Veto()
            return
        if self.IsModal(): self.EndModal(wx.ID_CANCEL)
        else: self.Destroy()


class BomFieldsDialog(wx.Dialog):
    def __init__(self, parent, sources):
        super().__init__(parent, title='Fusion BOM and field manager', size=(1050, 820),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.sources = sources
        self.rows = inventory(sources)
        self.plan = None
        self.result = None
        self.busy = False
        self.book = wx.Notebook(self)
        bom = wx.Panel(self.book); fields = wx.Panel(self.book)
        self.book.AddPage(bom, 'Combined BOM')
        self.book.AddPage(fields, 'Fields and bulk edits')
        box = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(bom, label='Combine the selected source variants. Exact field and assembly-state matches group together; DNP and BOM-excluded parts remain distinguishable. Quantities count each physical multi-unit component once. Source references stay in the export.')
        note.Wrap(970); box.Add(note, 0, wx.ALL | wx.EXPAND, 12)
        self.excluded = wx.CheckBox(bom, label='Include BOM-excluded parts in separate groups')
        self.excluded.Bind(wx.EVT_CHECKBOX, lambda event: self.show_bom())
        box.Add(self.excluded, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.bom = wx.ListCtrl(bom, style=wx.LC_REPORT)
        for i, (label, width) in enumerate([('Qty',50),('DNP',50),('In BOM',65),('Value',150),('Footprint',210),('MPN / part number',180),('Source references',260)]):
            self.bom.InsertColumn(i, label, width=width)
        box.Add(self.bom, 1, wx.ALL | wx.EXPAND, 12)
        export = wx.Button(bom, label='Export combined BOM CSV…')
        export.Bind(wx.EVT_BUTTON, lambda event: self.export(True))
        box.Add(export, 0, wx.ALL | wx.ALIGN_RIGHT, 12); bom.SetSizer(box)
        box = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(fields, label='Select rows for bulk edits or field-name merging. A rename conflict stops the plan. Reference, Footprint, sheet structure and assembly flags require the source repair/variant workflows. Preview edits before creating NEW source copies; originals and open editors stay unchanged.')
        note.Wrap(970); box.Add(note, 0, wx.ALL | wx.EXPAND, 12)
        self.field_list = wx.ListCtrl(fields, style=wx.LC_REPORT)
        for i, (label, width) in enumerate([('Source',150),('Reference',90),('Unit',45),('Value',150),('Fields',530)]):
            self.field_list.InsertColumn(i, label, width=width)
        for row in self.rows:
            idx = self.field_list.InsertItem(self.field_list.GetItemCount(), row['source'])
            for col, value in enumerate([row['reference'],str(row['unit']),row['fields'].get('Value',''),json.dumps(row['fields'],ensure_ascii=False)], 1):
                self.field_list.SetItem(idx,col,value)
        self.field_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.invalidate())
        self.field_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda event: self.invalidate())
        box.Add(self.field_list, 1, wx.ALL | wx.EXPAND, 12)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.field_name = wx.TextCtrl(fields, value='MPN')
        self.field_value = wx.TextCtrl(fields)
        self.rename_target = wx.TextCtrl(fields, value='Manufacturer Part Number')
        for label, control in [('Field',self.field_name),('Set value',self.field_value),('Rename / merge into',self.rename_target)]:
            row.Add(wx.StaticText(fields,label=label),0,wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,6)
            row.Add(control,1,wx.RIGHT,10)
            control.Bind(wx.EVT_TEXT,lambda event:self.invalidate())
        box.Add(row, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 12)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Preview value edit',lambda event:self.preview(False)),('Preview field rename',lambda event:self.preview(True)),('Export field inventory CSV…',lambda event:self.export(False))]:
            button=wx.Button(fields,label=label); button.Bind(wx.EVT_BUTTON,handler); row.Add(button,0,wx.RIGHT,8)
        self.apply_button = wx.Button(fields,label='Create reviewed field copies…')
        self.apply_button.Bind(wx.EVT_BUTTON,self.apply)
        self.apply_button.Disable(); row.Add(self.apply_button,0)
        box.Add(row,0,wx.ALL,12)
        self.preview_text = wx.TextCtrl(fields,style=wx.TE_MULTILINE | wx.TE_READONLY)
        box.Add(self.preview_text,1,wx.ALL | wx.EXPAND,12); fields.SetSizer(box)
        self.status=wx.StaticText(self,label='Selected configurations only; pending field edits are not included in CSV exports.')
        self.close_button=wx.Button(self,wx.ID_CANCEL,'Close')
        self.Bind(wx.EVT_CLOSE,self.close)
        box=wx.BoxSizer(wx.VERTICAL); box.Add(self.book,1,wx.ALL | wx.EXPAND,10)
        box.Add(self.status,0,wx.LEFT | wx.RIGHT | wx.BOTTOM,12)
        box.Add(self.close_button,0,wx.ALL | wx.ALIGN_RIGHT,12); self.SetSizer(box)
        self.show_bom(); self.CentreOnParent()

    def show_bom(self):
        try:
            groups=grouped_bom(self.rows,self.excluded.GetValue())
            self.groups=groups; self.bom.DeleteAllItems()
            for row in groups:
                fields=row['fields']; flags=row['flags']
                refs=', '.join(r['source']+':'+r['reference'] for r in row['references'])
                mpn=next((v for k,v in fields.items() if k.casefold() in {'mpn','manufacturer part number','manf#'}),'')
                idx=self.bom.InsertItem(self.bom.GetItemCount(),str(row['quantity']))
                for col,value in enumerate([flags['dnp'],flags['in_bom'],fields.get('Value',''),fields.get('Footprint',''),mpn,refs],1): self.bom.SetItem(idx,col,value)
        except Exception as exc:
            self.groups=[]; self.status.SetLabel(str(exc))

    def invalidate(self):
        self.plan=None; self.apply_button.Disable(); self.preview_text.Clear()

    def selected(self):
        ids=[]; idx=self.field_list.GetFirstSelected()
        while idx != -1:
            ids.append(self.rows[idx]['identity']); idx=self.field_list.GetNextSelected(idx)
        if not ids: raise MergeError('Select field rows first.')
        return ids

    def preview(self, rename):
        try:
            ids=self.selected(); name=self.field_name.GetValue().strip()
            self.plan=preview_fields(self.rows,ids,renames={name:self.rename_target.GetValue().strip()} if rename else None,
                                     edits=None if rename else {name:self.field_value.GetValue()})
            self.preview_text.SetValue(json.dumps(self.plan,indent=2,ensure_ascii=False))
            self.apply_button.Enable()
        except Exception as exc:
            self.invalidate(); self.preview_text.SetValue(str(exc))

    def export(self,bom):
        with wx.FileDialog(self,'Export selected-configuration BOM' if bom else 'Export field inventory',
                           defaultFile='fusion-bom.csv' if bom else 'fusion-fields.csv',wildcard='CSV files|*.csv',style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try: export_csv(dialog.GetPath(),self.groups if bom else self.rows,bom=bom)
            except Exception as exc: wx.MessageBox(str(exc),'Export failed',wx.OK | wx.ICON_ERROR,self)

    def apply(self,event):
        if self.plan is None or self.busy:return
        with wx.DirDialog(self,'Choose parent folder for NEW field-edited source copies') as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            destination=Path(dialog.GetPath())/'FusionFieldCopies'
        plan=self.plan
        self.busy=True; self.book.Disable(); self.close_button.Disable()
        self.status.SetLabel('Creating candidate copies and checking source hashes…')
        def worker():
            try: result,error=apply_to_copies(self.sources,plan,destination),None
            except Exception as exc: result,error=None,str(exc)
            wx.CallAfter(self.finish,result,error)
        threading.Thread(target=worker,name='FusionFieldCopies',daemon=True).start()

    def finish(self,result,error):
        self.busy=False; self.book.Enable(); self.close_button.Enable()
        if error: self.status.SetLabel(error);return
        self.result=result; self.EndModal(wx.ID_OK)

    def close(self,event):
        if self.busy:
            if event.CanVeto():event.Veto()
            return
        if self.IsModal(): self.EndModal(wx.ID_CANCEL)
        else:self.Destroy()


class DependencyDialog(wx.Dialog):
    def __init__(self,parent,specs):
        super().__init__(parent,title='Dependency audit and path review',size=(920,720),style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.specs=specs;self.plan=None;self.result=None;self.busy=False
        box=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Audit all local references together. Unique files and footprint folders inside each source produce explicit path suggestions. Review them, then create new copies with those mappings. Ambiguous or missing dependencies remain unresolved; strict merge checks still run.')
        note.Wrap(860);box.Add(note,0,wx.ALL | wx.EXPAND,12)
        self.report=wx.TextCtrl(self,style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        box.Add(self.report,1,wx.ALL | wx.EXPAND,12)
        self.status=wx.StaticText(self,label='No files are changed by an audit.')
        box.Add(self.status,0,wx.ALL,12)
        self.audit=wx.Button(self,label='Audit dependencies')
        self.create=wx.Button(self,label='Create copies with reviewed mappings…');self.create.Disable()
        self.cancel=wx.Button(self,wx.ID_CANCEL,'Close')
        self.audit.Bind(wx.EVT_BUTTON,self.on_audit);self.create.Bind(wx.EVT_BUTTON,self.on_create)
        self.Bind(wx.EVT_CLOSE,self.close)
        row=wx.BoxSizer(wx.HORIZONTAL)
        for button in (self.audit,self.create,self.cancel):row.Add(button,0,wx.RIGHT,8)
        box.Add(row,0,wx.ALL | wx.ALIGN_RIGHT,12);self.SetSizer(box);self.CentreOnParent()

    def run(self,action,done):
        if self.busy:return
        self.busy=True
        for control in (self.audit,self.create,self.cancel):control.Disable()
        self.status.SetLabel('Reading dependency files and checking hashes…')
        def worker():
            try:result,error=action(),None
            except Exception as exc:result,error=None,str(exc)
            wx.CallAfter(self.finish,done,result,error)
        threading.Thread(target=worker,name='FusionDependencyAudit',daemon=True).start()

    def finish(self,done,result,error):
        self.busy=False;self.audit.Enable();self.cancel.Enable()
        if error:
            self.plan=None;self.create.Disable();self.report.SetValue(error);self.status.SetLabel('Stopped. Originals remain unchanged.');return
        done(result)

    def on_audit(self,event):
        def done(plan):
            self.plan=plan;self.report.SetValue(json.dumps(plan['report'],indent=2,ensure_ascii=False))
            self.create.Enable(bool(plan['report']['suggestions']))
            self.status.SetLabel('Review the suggestions. Entries without a suggestion still need manual resolution.')
        self.run(lambda:preview_dependencies(self.specs),done)

    def on_create(self,event):
        if not self.plan:return
        with wx.DirDialog(self,'Choose a parent for NEW dependency-resolved source copies') as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            destination=Path(dialog.GetPath())/'FusionDependencyCopies'
        plan=self.plan
        def done(result):self.result=result;self.EndModal(wx.ID_OK)
        self.run(lambda:apply_dependencies(plan,destination),done)

    def close(self,event):
        if self.busy:
            if event.CanVeto():event.Veto()
            return
        if self.IsModal():self.EndModal(wx.ID_CANCEL)
        else:self.Destroy()
