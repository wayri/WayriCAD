"""Compact saved-project library workflow with isolated native validation."""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
import wx

from .assets import set_window_icons
from . import project_local
from .native_worker import normalize, validate_project
from .portability_io import saved_project_variables


class ProjectLibraryDialog(wx.Dialog):
    def __init__(self,parent,bridge=None,source=None):
        super().__init__(parent,title='WayriCAD Project Library',size=(850,660),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.bridge=bridge;self.result_message='';self.plan=None;self._busy=False
        self._closed=False;self._closing=False;self._cancel=threading.Event();self._preview_inputs=None
        self.SetMinSize((720,560));set_window_icons(self,wx)
        if not source and bridge is not None:
            board=getattr(bridge,'board',None)
            source=str(board.GetFileName()) if board is not None else ''
        outer=wx.BoxSizer(wx.VERTICAL)
        intro=wx.StaticText(self,label='Keep this project’s footprints, symbols and 3D models together.')
        font=intro.GetFont();font.SetWeight(wx.FONTWEIGHT_BOLD);intro.SetFont(font)
        outer.Add(intro,0,wx.EXPAND|wx.ALL,12)
        form=wx.FlexGridSizer(2,2,8,10);form.AddGrowableCol(1,1)
        self.source=wx.FilePickerCtrl(self,path=str(source or ''),message='Choose a saved KiCad design',
            wildcard='KiCad project or design (*.kicad_pro;*.kicad_pcb;*.kicad_sch)|*.kicad_pro;*.kicad_pcb;*.kicad_sch',
            style=wx.FLP_OPEN|wx.FLP_FILE_MUST_EXIST|wx.FLP_USE_TEXTCTRL)
        self.folder=wx.TextCtrl(self,value='local')
        self.folder.SetToolTip('Relative folder inside the project. Settings are remembered when localization succeeds.')
        for label,control in [('Project',self.source),('Library folder',self.folder)]:
            form.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
        outer.Add(form,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.options=wx.CollapsiblePane(self,label='Options',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        pane=self.options.GetPane();opts=wx.BoxSizer(wx.VERTICAL)
        grid=wx.FlexGridSizer(2,2,6,10);grid.AddGrowableCol(0,1);grid.AddGrowableCol(1,1)
        grid.Add(wx.StaticText(pane,label='Additional model folders — one per line'))
        grid.Add(wx.StaticText(pane,label='Path variables — NAME=FOLDER, one per line'))
        self.model_roots=wx.TextCtrl(pane,style=wx.TE_MULTILINE,size=(-1,62))
        self.variables=wx.TextCtrl(pane,style=wx.TE_MULTILINE,size=(-1,62))
        grid.Add(self.model_roots,1,wx.EXPAND);grid.Add(self.variables,1,wx.EXPAND);opts.Add(grid,1,wx.EXPAND)
        self.allow_missing=wx.CheckBox(pane,label='Keep unresolved 3D links and list them in the report')
        self.allow_missing.SetToolTip('The default stops when a linked model is unavailable. This option keeps its existing reference; it does not invent a replacement model.')
        opts.Add(self.allow_missing,0,wx.TOP,8);pane.SetSizer(opts)
        outer.Add(self.options,0,wx.EXPAND|wx.ALL,12)
        self.summary=wx.StaticText(self,label='Preview the saved design to see the exact files and links that will change.')
        outer.Add(self.summary,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.files=wx.ListCtrl(self,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        self.files.InsertColumn(0,'Change',width=110);self.files.InsertColumn(1,'Project file',width=590)
        outer.Add(self.files,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.issues=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY|wx.BORDER_NONE,size=(-1,62))
        self.issues.Hide();outer.Add(self.issues,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,12)
        self.ack=wx.CheckBox(self,label='I saved and closed this project’s PCB and Schematic editors.')
        self.ack.SetToolTip('Localization updates saved files with a backup. Reopen the project afterward so an old editor buffer cannot overwrite the new links.')
        outer.Add(self.ack,0,wx.EXPAND|wx.ALL,12)
        self.status=wx.StaticText(self,label='Ready')
        outer.Add(self.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.more=wx.Button(self,label='More…');self.preview=wx.Button(self,label='Preview')
        self.apply=wx.Button(self,label='Localize with backup');self.close=wx.Button(self,wx.ID_CANCEL,label='Close')
        self.apply.Enable(False);self.preview.SetDefault()
        footer.Add(self.more,0,wx.RIGHT,8);footer.AddStretchSpacer()
        for control in (self.preview,self.apply,self.close):footer.Add(control,0,wx.LEFT,8)
        outer.Add(footer,0,wx.EXPAND|wx.ALL,12);self.SetSizer(outer)
        self._edits=[self.source,self.folder,self.model_roots,self.variables,self.allow_missing,self.more]
        self.source.Bind(wx.EVT_FILEPICKER_CHANGED,self._source_changed)
        for control in (self.folder,self.model_roots,self.variables):control.Bind(wx.EVT_TEXT,self._invalidate)
        self.allow_missing.Bind(wx.EVT_CHECKBOX,self._invalidate)
        self.ack.Bind(wx.EVT_CHECKBOX,lambda event:self._buttons())
        self.options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:self.Layout())
        self.preview.Bind(wx.EVT_BUTTON,self.on_preview);self.apply.Bind(wx.EVT_BUTTON,self.on_apply)
        self.more.Bind(wx.EVT_BUTTON,self.on_more);self.close.Bind(wx.EVT_BUTTON,self.on_close)
        self.Bind(wx.EVT_CLOSE,self.on_close)
        self._load_settings();self.CentreOnParent()

    def _source_changed(self,event):
        self._load_settings();self.ack.SetValue(False);self._invalidate()

    def _load_settings(self):
        raw=self.source.GetPath()
        if not raw:return
        try:
            config=project_local.settings(Path(raw).resolve().parent)
            self.folder.ChangeValue(config.get('folder','local'))
            self.model_roots.ChangeValue('\n'.join(config.get('model_roots',[])))
            self.variables.ChangeValue('\n'.join(f'{name}={value}' for name,value in config.get('variables',{}).items()))
        except Exception as exc:self._show_issues(['Project settings: '+str(exc)])

    def _inputs(self):
        raw=self.source.GetPath().strip()
        if not raw:raise ValueError('Choose a saved KiCad project, PCB or schematic.')
        source=Path(raw).resolve()
        if not source.is_file():raise ValueError('The selected saved design does not exist.')
        if source.suffix not in ('.kicad_pro','.kicad_pcb','.kicad_sch'):raise ValueError('Choose a KiCad project, PCB or schematic file.')
        pcb=source.with_suffix('.kicad_pcb');sch=source.with_suffix('.kicad_sch')
        pcb=pcb if pcb.is_file() else None;sch=sch if sch.is_file() else None
        if not pcb and not sch:raise ValueError('No same-name saved PCB or schematic was found beside this project.')
        variables=saved_project_variables(source)
        for line in self.variables.GetValue().splitlines():
            if not line.strip():continue
            name,sep,value=line.partition('=');name=name.strip();value=value.strip()
            if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name) or not value:
                raise ValueError('Path variables must use NAME=FOLDER, one per line.')
            if name=='KIPRJMOD':raise ValueError('KIPRJMOD follows the selected project and cannot be overridden.')
            variables[name]=value
        roots=[str(Path(line.strip()).expanduser().resolve()) for line in self.model_roots.GetValue().splitlines() if line.strip()]
        missing=[path for path in roots if not Path(path).is_dir()]
        if missing:raise ValueError('Model folder not found: '+missing[0])
        return dict(pcb=pcb,schematic=sch,folder=project_local.folder_name(self.folder.GetValue().strip()),
                    variables=variables,model_roots=roots,allow_missing=self.allow_missing.GetValue())

    def _invalidate(self,event=None):
        if not self._busy:
            self.plan=None;self._preview_inputs=None;self.status.SetLabel('Preview required after changing the project or options.');self._buttons()
        if event:event.Skip()

    def _buttons(self):
        for control in self._edits:control.Enable(not self._busy)
        self.preview.Enable(not self._busy);self.ack.Enable(not self._busy)
        self.apply.Enable(not self._busy and self.plan is not None and self.ack.GetValue())
        self.close.SetLabel('Cancel' if self._busy else 'Close')

    def _show_issues(self,issues):
        self.issues.SetValue('\n'.join(str(issue) for issue in issues))
        self.issues.Show(bool(issues));self.Layout()

    def _run(self,operation,finished,message,discard_cancelled=True):
        if self._busy:return
        self._busy=True;self._cancel.clear();self.status.SetLabel(message);self._buttons()
        def worker():
            try:
                result=operation()
                if discard_cancelled and self._cancel.is_set():raise InterruptedError('Operation cancelled.')
                error=None
            except Exception as exc:result=None;error=exc
            wx.CallAfter(self._finish,finished,result,error)
        threading.Thread(target=worker,name='WayriCAD project library',daemon=True).start()

    def _finish(self,finished,result,error):
        if self._closed:return
        self._busy=False
        if error:
            self.plan=None;self.status.SetLabel('Cancelled' if isinstance(error,InterruptedError) else 'Review the issue below.')
            self._show_issues([str(error)])
        else:finished(result)
        self._buttons()
        if self._closing:self._end()

    def on_preview(self,event=None):
        try:inputs=self._inputs()
        except Exception as exc:self._show_issues([str(exc)]);return
        self.plan=None;self.files.DeleteAllItems();self._show_issues([])
        def prepare():
            normal,digest=normalize(inputs['pcb']) if inputs['pcb'] else (None,None)
            if self._cancel.is_set():raise InterruptedError('Preview cancelled.')
            project=(inputs['pcb'] or inputs['schematic']).parent
            resolver=project_local.ProjectResolver(project,inputs['variables'],inputs['model_roots'])
            return project_local.prepare(inputs['pcb'],inputs['schematic'],folder=inputs['folder'],
                normalized=normal,normalized_hash=digest,resolver=resolver,allow_missing=inputs['allow_missing'],cancelled=self._cancel.is_set)
        def finished(plan):
            self.plan=plan;self._preview_inputs=inputs;summary=plan.summary();counts=summary['counts']
            self.summary.SetLabel(f"{counts.get('footprints',0)} footprints · {counts.get('symbols',0)} symbols · {counts.get('models',0)} models → {plan.folder}/")
            for name in sorted(plan.files,key=lambda name:(name.startswith(plan.folder+'/'),name)):
                row=self.files.InsertItem(self.files.GetItemCount(),'Replace + backup' if plan.expected.get(name) is not None else 'Create')
                self.files.SetItem(row,1,name)
            self._show_issues(plan.warnings)
            self.status.SetLabel(f"{len(plan.files)} files reviewed. Save and close the editors, then localize.")
        self._run(prepare,finished,'Reading saved definitions and validating placed footprints…')

    def on_apply(self,event=None):
        if self.plan is None or not self.ack.GetValue():return
        plan=self.plan;inputs=self._preview_inputs
        def apply():
            return plan.apply(validate=lambda stage:validate_project(stage,
                inputs['pcb'].name if inputs['pcb'] else None,inputs['schematic'].name if inputs['schematic'] else None),cancelled=self._cancel.is_set)
        def finished(result):
            self.plan=None;self.ack.SetValue(False)
            self.result_message='Project libraries localized. Reopen the project to load the updated links.\n\nBackup: '+result['backup']
            self.status.SetLabel('Localized successfully. Reopen the project in KiCad.')
            self._show_issues(['Backup: '+result['backup']]+result.get('warnings',[]))
        self._run(apply,finished,'Validating the staged project, then publishing with a backup…',discard_cancelled=False)

    def on_more(self,event):
        menu=wx.Menu();advanced=menu.Append(wx.ID_ANY,'Advanced asset tools…')
        self.Bind(wx.EVT_MENU,self.on_advanced,advanced)
        upgrade=menu.Append(wx.ID_ANY,'Upgrade a project copy…')
        self.Bind(wx.EVT_MENU,self.on_upgrade,upgrade)
        live=menu.Append(wx.ID_ANY,'Live editor tools…')
        self.Bind(wx.EVT_MENU,lambda evt:wx.MessageBox('In PCB Editor, open Tools → External Plugins → WayriCAD Advanced Live Assets.\n\nThat native menu action uses the active board. This independent window works on saved project files.',
            'Live editor tools',wx.OK|wx.ICON_INFORMATION),live)
        self.PopupMenu(menu);menu.Destroy()

    def on_upgrade(self,event=None):
        try:
            source=Path(self.source.GetPath()).resolve()
            if source.suffix!='.kicad_sch':source=source.with_suffix('.kicad_sch')
            if not source.is_file():raise ValueError('Choose a project with a saved root schematic to upgrade.')
            with wx.DirDialog(self,'Choose a parent folder outside the source project',defaultPath=str(source.parent.parent),style=wx.DD_DIR_MUST_EXIST) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                parent=Path(dialog.GetPath())
            with wx.TextEntryDialog(self,'Name the new upgraded project folder','Upgrade a project copy',source.stem+'-KiCad10') as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                name=dialog.GetValue().strip()
            if not name or Path(name).name!=name or name in ('.','..'):raise ValueError('Enter a new folder name without path separators.')
            destination=parent/name
            if destination.exists():raise ValueError('Choose a new folder; existing projects are never overwritten.')
        except Exception as exc:self._show_issues([str(exc)]);return
        def upgrade():
            from wayricad_runtime.schematic_migration import upgrade_copy
            def progress(index,total,sheet):
                if self._cancel.is_set():raise InterruptedError('Project upgrade cancelled before publication.')
                wx.CallAfter(self.status.SetLabel,f'Upgrading sheet {index+1}/{total}: {sheet}')
            return upgrade_copy(source,destination,progress=progress)
        def finished(report):
            self.source.SetPath(report['destination']);self._load_settings();self.plan=None;self.ack.SetValue(False)
            self.files.DeleteAllItems();self.summary.SetLabel('Upgraded copy selected. Preview it to create project-local libraries.')
            self.status.SetLabel(f"Copied {report['schematics']} sheets; {report['native_components']} components and {report['native_nets']} nets preserved.")
            self._show_issues(['New project: '+str(destination),'Original project remains unchanged.'])
            self.result_message='Upgraded project copy: '+str(destination)
        self._run(upgrade,finished,'Copying the project and checking native connectivity before upgrade…',discard_cancelled=False)

    def on_advanced(self,event=None):
        if not getattr(self.bridge,'supports_file_tools',False) and not getattr(self.bridge,'supports_live_tools',True):
            from .project_launcher import launch
            launch(self.source.GetPath(),advanced=True)
            return
        from .workspace_ui import WorkspaceDialog
        dialog=WorkspaceDialog(self,self.bridge)
        try:
            dialog.ShowModal()
            if dialog.result_message:self.result_message=dialog.result_message
        finally:dialog.Destroy()
        self._invalidate()

    def on_close(self,event=None):
        if self._busy:
            self._cancel.set();self._closing=True;self.status.SetLabel('Cancelling safely; waiting for the current validation step…')
            if isinstance(event,wx.CloseEvent) and event.CanVeto():event.Veto()
            return
        self._end()

    def _end(self):
        self._closed=True
        if self.IsModal():self.EndModal(wx.ID_OK if self.result_message else wx.ID_CANCEL)
        else:self.Destroy()
