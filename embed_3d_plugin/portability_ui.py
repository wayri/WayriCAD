"""Simple saved-design workbench: extract first, relink only by a separate action."""
from __future__ import annotations
import json
from pathlib import Path
import threading
import wx
from .assets import set_window_icons
from .paths import Resolver
from .portability_io import read_text, read_bytes, load_extraction, saved_project_variables
from .codec import sha256
from .sexpr import parse
from .unbundle import extract_pcb, relink_pcb
from .symbols import extract_symbols, embed_symbols, relink_symbols
from .cli_validation import find_cli, validate_schematic


def describe(value):
    if hasattr(value,'preview'): value=value.preview()
    lines=[]
    labels={'kind':'Design type','source':'Source','assets':'Extracted assets','output':'New design folder',
            'files':'Files to extract','bytes':'Total bytes','operation':'Operation',
            'path_mode':'Reference style','sheets':'Schematic sheets','symbols':'Symbol definitions',
            'footprint_count':'PCB footprints','models_relinked':'Models to relink','link_footprints':'Relink footprint IDs','link_models':'Relink model paths',
            'local_library_links':'Link project-local symbol library','libraries_archived':'Symbol-library archives',
            'native_symbol_cache_retained':'Retain native symbol cache','remove_redundant_payloads':'Remove redundant embedded data',
            'remove_archive_attachments':'Remove managed archive attachments'}
    for key,label in labels.items():
        if key in value:
            content=value[key]
            if isinstance(content,bool):content='Yes' if content else 'No'
            lines.append(label+': '+str(content))
    for key,label in (('outputs','Files'),('library_view_files','Project-specific footprint-library files'),
                      ('removed_archive_entries','Archive entries to remove'),('warnings','Review before continuing')):
        if value.get(key):lines.extend(['',label+':']+['  '+str(v) for v in value[key]])
    return '\n'.join(lines)


class AsyncDialog(wx.Dialog):
    def init_async(self):
        self.busy=False; self.closing=False; self.stop=threading.Event(); self.controls=[]
        self.Bind(wx.EVT_CLOSE,self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK,self.on_key)
    def on_key(self,event):
        if event.GetKeyCode()==wx.WXK_ESCAPE: self.on_close()
        else: event.Skip()
    def on_close(self,event=None):
        if self.busy:
            self.closing=True; self.stop.set()
            if event and hasattr(event,'Veto'): event.Veto()
            self.status.SetLabel('Stopping safely after the current operation…')
        else: self.EndModal(wx.ID_CANCEL)
    def run_job(self,job,done):
        if self.busy: return
        self.busy=True; self.stop.clear()
        for ctrl in self.controls: ctrl.Enable(False)
        self.status.SetLabel('Working…  Original design files remain unchanged.')
        def work():
            result,error=None,None
            try: result=job()
            except Exception as exc: error=str(exc)
            wx.CallAfter(self.finish_job,result,error,done)
        threading.Thread(target=work,name='WayriCAD Embed3D-portability',daemon=True).start()
    def finish_job(self,result,error,done):
        self.busy=False
        for ctrl in self.controls: ctrl.Enable(True)
        if self.closing:
            self.EndModal(wx.ID_CANCEL); return
        if error:
            if hasattr(self, 'preview_valid'): self.invalidate()
            self.status.SetLabel('Stopped without overwriting the source design.')
            wx.MessageBox(error,'WayriCAD Embed3D',wx.OK|wx.ICON_WARNING,self)
        else:
            self.status.SetLabel('Complete. Originals are unchanged.')
            done(result)
    def call_gui(self,fn):
        """Marshal native pcbnew calls from an IO worker onto the UI thread."""
        ready=threading.Event(); result=[]; errors=[]
        def invoke():
            try:
                if self.stop.is_set(): raise InterruptedError('Cancelled before native validation')
                result.append(fn())
            except Exception as exc: errors.append(exc)
            finally: ready.set()
        wx.CallAfter(invoke)
        ready.wait()
        if errors: raise errors[0]
        return result[0] if result else None


class AssetPanel(wx.Panel):
    def __init__(self,parent,host,kind,source=''):
        super().__init__(parent)
        self.host,self.kind,self.plan=host,kind,None
        self.sizer=wx.BoxSizer(wx.VERTICAL)
        pcb=kind=='pcb'
        lead='Extract actual files. Relink only when you choose.' if pcb else 'Keep symbols self-contained. Export an editable library when needed.'
        title=wx.StaticText(self,label=lead)
        font=title.GetFont(); font.SetWeight(wx.FONTWEIGHT_BOLD);title.SetFont(font)
        self.sizer.Add(title,0,wx.BOTTOM,12)
        self.add_label('1  Saved PCB' if pcb else '1  Root schematic — saved files, not an open editor buffer')
        self.source=wx.FilePickerCtrl(self,path=source,wildcard='KiCad PCB|*.kicad_pcb' if pcb else 'KiCad schematic|*.kicad_sch',
                                      style=wx.FLP_OPEN|wx.FLP_FILE_MUST_EXIST|wx.FLP_USE_TEXTCTRL)
        self.sizer.Add(self.source,0,wx.EXPAND|wx.BOTTOM,10)
        self.add_label('2  Asset folder — Extract writes here; Relink reads this folder')
        default=str(Path(source).with_suffix(''))+'_assets' if source else ''
        self.assets=wx.DirPickerCtrl(self,path=default,style=wx.DIRP_USE_TEXTCTRL)
        self.sizer.Add(self.assets,0,wx.EXPAND|wx.BOTTOM,10)
        row=wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self,label='Library nickname'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.nickname=wx.TextCtrl(self,value='UnbundledFootprints' if pcb else 'UnbundledSymbols')
        row.Add(self.nickname,1); self.sizer.Add(row,0,wx.EXPAND|wx.BOTTOM,10)
        opts=wx.WrapSizer(wx.HORIZONTAL)
        if pcb:
            self.footprints=wx.CheckBox(self,label='Footprints');self.footprints.SetValue(True)
            self.models=wx.CheckBox(self,label='3D models');self.models.SetValue(True)
            self.external=wx.CheckBox(self,label='Also copy already-external models')
            for c in (self.footprints,self.models,self.external):opts.Add(c,0,wx.RIGHT|wx.BOTTOM,12)
            self.sizer.Add(opts,0,wx.EXPAND)
            self.origin=wx.Choice(self,choices=['As placed — native footprint normalization', 'Archived definitions — packaged PCB only'])
            self.origin.SetSelection(0);self.sizer.Add(self.origin,0,wx.EXPAND|wx.BOTTOM,10)
        else:
            self.follow=wx.CheckBox(self,label='Include hierarchical child sheets');self.follow.SetValue(True)
            self.unused=wx.CheckBox(self,label='Include unused cached definitions')
            for c in (self.follow,self.unused):opts.Add(c,0,wx.RIGHT|wx.BOTTOM,12)
            self.sizer.Add(opts,0,wx.EXPAND)
            note=wx.StaticText(self,label='Native lib_symbols caches stay in the schematic. Relinking changes library IDs, not pins or wiring.')
            note.Wrap(self.FromDIP(760));self.sizer.Add(note,0,wx.EXPAND|wx.BOTTOM,10)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        self.preview=wx.Button(self,label='Preview extraction')
        self.extract=wx.Button(self,label='Extract files');self.extract.Enable(False)
        self.relink=wx.Button(self,label='Relink extracted files…')
        self.relink.SetToolTip('Separate step. Choose the verified asset folder and write a NEW relinked design copy.')
        for c in (self.preview,self.extract,self.relink):actions.Add(c,0,wx.RIGHT|wx.BOTTOM,8)
        if not pcb:
            self.embed=wx.Button(self,label='Embed symbol archive…');actions.Add(self.embed,0,wx.BOTTOM,8)
            self.embed.Bind(wx.EVT_BUTTON,lambda e:self.open_operation('embed'))
        self.sizer.Add(actions,0,wx.EXPAND|wx.TOP,4)
        self.details=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,value=
            'Preview lists the files, size and warnings.\n\nExtract never changes the PCB or schematic.\nRelink writes a separate design copy and keeps original-file snapshots.\nNo existing library or model files are overwritten.')
        self.sizer.Add(self.details,1,wx.EXPAND|wx.TOP,10)
        self.SetSizer(self.sizer)
        self.source.Bind(wx.EVT_FILEPICKER_CHANGED,self.changed_source)
        self.assets.Bind(wx.EVT_DIRPICKER_CHANGED,self.invalidate)
        self.nickname.Bind(wx.EVT_TEXT,self.invalidate)
        if pcb:
            for c in (self.footprints,self.models,self.external):c.Bind(wx.EVT_CHECKBOX,self.invalidate)
            self.origin.Bind(wx.EVT_CHOICE,self.invalidate)
        else:
            self.follow.Bind(wx.EVT_CHECKBOX,self.invalidate);self.unused.Bind(wx.EVT_CHECKBOX,self.invalidate)
        self.preview.Bind(wx.EVT_BUTTON,self.on_preview);self.extract.Bind(wx.EVT_BUTTON,self.on_extract)
        self.relink.Bind(wx.EVT_BUTTON,lambda e:self.open_operation('relink'))
    def add_label(self,label):
        self.sizer.Add(wx.StaticText(self,label=label),0,wx.BOTTOM,4)
    def invalidate(self,event=None):
        self.plan=None;self.extract.Enable(False)
    def changed_source(self,event):
        self.invalidate()
        if self.source.GetPath():self.assets.SetPath(str(Path(self.source.GetPath()).with_suffix(''))+'_assets')
    def paths(self):
        path,folder=self.source.GetPath().strip(),self.assets.GetPath().strip()
        if not path or not Path(path).is_file():raise ValueError('Select an existing saved design file')
        if not folder:raise ValueError('Choose an asset folder')
        return Path(path).absolute(),Path(folder).absolute()
    def on_preview(self,event):
        self.invalidate()
        try:
            source,folder=self.paths();nickname=self.nickname.GetValue().strip()
            if self.kind=='pcb':
                fps,models,external=self.footprints.GetValue(),self.models.GetValue(),self.external.GetValue()
                resolver=Resolver(source.parent,saved_project_variables(source))
                text=read_text(source)
                references=[m.arg().value(text) for fp in parse(text).nodes(text,'footprint') for m in fp.nodes(text,'model')]
                resolver.capture_native(self.host.bridge.pcbnew, None, references)
                normalized=None;source_hash=None
                if fps and self.origin.GetSelection()==0:
                    self.host.status.SetLabel('Normalizing saved PCB footprints with KiCad…')
                    normalized,source_hash=self.host.bridge.extract_normalized_footprints(source)
                job=lambda:extract_pcb(source,folder,footprints=fps,models=models,include_external=external,nickname=nickname,
                      normalized=normalized,normalized_source_hash=source_hash,resolver=resolver,cancelled=self.host.stop.is_set)
            else:
                follow,unused=self.follow.GetValue(),self.unused.GetValue()
                job=lambda:extract_symbols(source,follow=follow,nickname=nickname,include_unused=unused,cancelled=self.host.stop.is_set)
        except Exception as exc:
            wx.MessageBox(str(exc),'WayriCAD Embed3D',wx.OK|wx.ICON_WARNING,self);return
        def done(plan):
            self.plan=plan;self.details.SetValue(describe(plan));self.extract.Enable(True)
        self.host.run_job(job,done)
    def on_extract(self,event):
        if not self.plan:return
        plan=self.plan;folder=Path(self.assets.GetPath()).absolute()
        def done(path):
            self.details.SetValue('Extracted to '+str(path.parent)+'\n\nOriginal design references are unchanged.\nUse Relink extracted files… as a separate step.\n\n'+describe(plan))
        self.host.run_job(lambda:plan.publish(folder,self.host.stop.is_set),done)
    def open_operation(self,operation):
        try:
            source,assets=self.paths()
        except Exception as exc:
            wx.MessageBox(str(exc),'WayriCAD Embed3D',wx.OK|wx.ICON_WARNING,self);return
        dlg=OperationDialog(self,self.host.bridge,self.kind,operation,source,assets,
                            self.nickname.GetValue().strip(),self.follow.GetValue() if self.kind!='pcb' else True)
        try:dlg.ShowModal()
        finally:dlg.Destroy()


class PortabilityDialog(AsyncDialog):
    def __init__(self,parent,bridge,tab=0):
        super().__init__(parent,title='WayriCAD Embed3D · Design portability',style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.bridge=bridge;self.init_async();set_window_icons(self,wx)
        sizer=wx.BoxSizer(wx.VERTICAL);self.book=wx.Notebook(self)
        board=str(bridge.board.GetFileName()) if bridge.board else ''
        schematic=str(Path(board).with_suffix('.kicad_sch')) if board else ''
        if schematic and not Path(schematic).is_file():schematic=''
        self.pcb=AssetPanel(self.book,self,'pcb',board)
        self.symbols=AssetPanel(self.book,self,'schematic',schematic)
        self.book.AddPage(self.pcb,'PCB · footprints & 3D');self.book.AddPage(self.symbols,'Schematic · symbols')
        self.book.SetSelection(tab);sizer.Add(self.book,1,wx.EXPAND|wx.ALL,16)
        self.status=wx.StaticText(self,label='Save your design before scanning. These workflows read saved files.')
        sizer.Add(self.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        close=wx.Button(self,wx.ID_CANCEL,'Close');close.Bind(wx.EVT_BUTTON,self.on_close)
        sizer.Add(close,0,wx.ALIGN_RIGHT|wx.ALL,16);self.SetSizer(sizer)
        self.controls=[self.book]
        screen=wx.GetClientDisplayRect().GetSize()
        self.SetSize((min(self.FromDIP(920),screen.width-40),min(self.FromDIP(740),screen.height-40)))
        self.SetMinSize((min(self.FromDIP(690),screen.width-40),min(self.FromDIP(600),screen.height-40)))
        self.CentreOnParent()


class OperationDialog(AsyncDialog):
    def __init__(self,parent,bridge,kind,operation,source,assets,nickname,follow):
        title='Embed schematic symbol archive' if operation=='embed' else 'Relink to extracted files'
        super().__init__(parent,title='WayriCAD Embed3D · '+title,style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.bridge,self.kind,self.operation=bridge,kind,operation
        self.source,self.assets,self.nickname,self.follow=source,assets,nickname,follow
        self.supplied=[];self.preview_inputs={};self.preview_valid=False;self.init_async();set_window_icons(self,wx)
        sizer=wx.BoxSizer(wx.VERTICAL)
        self.form=wx.Panel(self);form=wx.BoxSizer(wx.VERTICAL)
        description=wx.StaticText(self.form,label=str(source)+'\n\nWrites a NEW design folder. The original files and editor buffers are not changed.')
        description.Wrap(self.FromDIP(760));form.Add(description,0,wx.EXPAND|wx.BOTTOM,12)
        form.Add(wx.StaticText(self.form,label='New design folder — choose a parent, then enter a new folder name'),0,wx.BOTTOM,4)
        suffix='_embedded' if operation=='embed' else '_external'
        self.output=wx.DirPickerCtrl(self.form,path=str(source.with_suffix(''))+suffix,style=wx.DIRP_USE_TEXTCTRL)
        form.Add(self.output,0,wx.EXPAND|wx.BOTTOM,12)
        self.output.Bind(wx.EVT_DIRPICKER_CHANGED,self.invalidate)
        self.path_mode=wx.Choice(self.form,choices=['Project-relative paths (${KIPRJMOD})','Absolute paths'])
        self.path_mode.SetSelection(0)
        self.path_mode.Bind(wx.EVT_CHOICE,self.invalidate)
        if operation=='relink':
            form.Add(self.path_mode,0,wx.EXPAND|wx.BOTTOM,10)
            if kind=='pcb':
                row=wx.BoxSizer(wx.HORIZONTAL)
                self.link_fp=wx.CheckBox(self.form,label='Relink footprint library IDs');self.link_fp.SetValue(True)
                self.link_models=wx.CheckBox(self.form,label='Relink 3D models');self.link_models.SetValue(True)
                try:
                    meta,_=load_extraction(assets, source)
                    self.link_fp.SetValue(bool(meta.get('footprints')));self.link_fp.Enable(bool(meta.get('footprints')))
                    self.link_models.SetValue(bool(meta.get('models')));self.link_models.Enable(bool(meta.get('models')))
                except Exception:
                    pass  # Preview supplies the actionable manifest error; no writes occur here.
                for c in (self.link_fp,self.link_models):
                    row.Add(c,0,wx.RIGHT,14);c.Bind(wx.EVT_CHECKBOX,self.invalidate)
                form.Add(row,0,wx.BOTTOM,10)
            self.prune=wx.CheckBox(self.form,label='Remove redundant archive/model attachments after relinking')
            self.prune.SetValue(False);self.prune.Bind(wx.EVT_CHECKBOX,self.invalidate)
            self.prune.SetToolTip('Default is keep. Remove only extracted managed data with no remaining native references. Native schematic lib_symbols are never removed.')
            form.Add(self.prune,0,wx.BOTTOM,10)
        else:
            self.path_mode.Hide()
            self.local=wx.CheckBox(self.form,label='Also create a project-local symbol library and relink its IDs')
            self.local.SetValue(False);self.local.Bind(wx.EVT_CHECKBOX,self.invalidate)
            form.Add(self.local,0,wx.BOTTOM,8)
            self.imports=wx.Button(self.form,label='Add supplied .kicad_sym archives…');self.imports.Bind(wx.EVT_BUTTON,self.on_imports)
            form.Add(self.imports,0,wx.BOTTOM,5)
            self.import_label=wx.StaticText(self.form,label='No supplied libraries. Existing as-drawn symbols are always included.')
            self.import_label.Wrap(self.FromDIP(720));form.Add(self.import_label,0,wx.EXPAND|wx.BOTTOM,10)
        cli=find_cli()
        self.native=wx.CheckBox(self.form,label='Validate the generated schematic with local KiCad CLI' if kind!='pcb' else 'Validate the generated PCB with KiCad native parser')
        self.native.SetValue(kind=='pcb' or cli is not None);self.native.Bind(wx.EVT_CHECKBOX,self.invalidate)
        if kind!='pcb' and cli is None:
            self.native.SetToolTip('No KiCad CLI detected. This optional check will fail until the CLI is installed on PATH. It is not ERC or visual testing.')
        form.Add(self.native,0,wx.BOTTOM,10)
        self.form.SetSizer(form);sizer.Add(self.form,0,wx.EXPAND|wx.ALL,16)
        self.details=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,value='Preview first. Review the output folder, path mode and attachment-removal setting before creating the copy.')
        sizer.Add(self.details,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.status=wx.StaticText(self,label='Original design files remain unchanged.')
        sizer.Add(self.status,0,wx.EXPAND|wx.ALL,16)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.preview=wx.Button(self,label='Preview changes');self.apply=wx.Button(self,label='Create new design copy');self.apply.Enable(False)
        self.close=wx.Button(self,wx.ID_CANCEL,'Close')
        row.Add(self.preview);row.AddStretchSpacer();row.Add(self.close,0,wx.RIGHT,8);row.Add(self.apply)
        sizer.Add(row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16);self.SetSizer(sizer)
        self.controls=[self.form,self.preview,self.apply]
        self.preview.Bind(wx.EVT_BUTTON,lambda e:self.execute(False));self.apply.Bind(wx.EVT_BUTTON,lambda e:self.execute(True));self.close.Bind(wx.EVT_BUTTON,self.on_close)
        screen=wx.GetClientDisplayRect().GetSize()
        self.SetSize((min(self.FromDIP(870),screen.width-40),min(self.FromDIP(710),screen.height-40)))
        self.CentreOnParent()
    def invalidate(self,event=None):
        self.preview_valid=False;self.apply.Enable(False)
    def on_imports(self,event):
        with wx.FileDialog(self,'Add symbol libraries to archive (does not replace existing symbols)',wildcard='KiCad symbol library|*.kicad_sym',
                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST|wx.FD_MULTIPLE) as dlg:
            if dlg.ShowModal()==wx.ID_OK:
                self.supplied=list(dict.fromkeys([*self.supplied,*map(Path,dlg.GetPaths())]))
                self.import_label.SetLabel(str(len(self.supplied))+' supplied libraries: '+', '.join(p.name for p in self.supplied))
                self.import_label.Wrap(self.FromDIP(720));self.invalidate();self.Layout()
    def execute(self,apply):
        if apply and not self.preview_valid:return
        try:
            value=self.output.GetPath().strip()
            if not value:raise ValueError('Choose a NEW output folder')
            output=Path(value).absolute()
            if output.exists() or not output.parent.is_dir():raise ValueError('The output must be a NEW folder under an existing parent')
            options={'apply':apply,'cancelled':self.stop.is_set}
            if self.native.GetValue():
                if self.kind=='pcb':options['validate']=lambda stage:self.call_gui(lambda:self.bridge.validate_portable_board(stage/self.source.name))
                else:options['validate']=lambda stage:validate_schematic(stage/self.source.name)
            if self.operation=='embed':
                kwargs=dict(options,follow=self.follow,nickname=self.nickname,supplied=tuple(self.supplied),local_links=self.local.GetValue())
                fn=lambda:embed_symbols(self.source,output,**kwargs)
            else:
                kwargs=dict(options,path_mode='relative' if self.path_mode.GetSelection()==0 else 'absolute',prune=self.prune.GetValue())
                if self.kind=='pcb':
                    kwargs.update(link_footprints=self.link_fp.GetValue(),link_models=self.link_models.GetValue())
                    fn=lambda:relink_pcb(self.source,self.assets,output,**kwargs)
                else:fn=lambda:relink_symbols(self.source,self.assets,output,**kwargs)
        except Exception as exc:
            wx.MessageBox(str(exc),'WayriCAD Embed3D',wx.OK|wx.ICON_WARNING,self);return
        def done(report):
            self.details.SetValue(('Created: '+str(output)+'\nOpen the new design in KiCad.\n\n' if apply else 'Native validation, when enabled, runs before publication—not during this preview.\n\n')+describe(report))
            self.preview_inputs=report.get('input_sha256',{})
            self.preview_valid=not apply;self.apply.Enable(not apply)
        expected=dict(self.preview_inputs) if apply else {}
        def guarded():
            for path,digest in expected.items():
                if sha256(read_bytes(Path(path))) != digest:
                    raise ValueError('An input changed since Preview. Preview again: '+path)
            return fn()
        self.run_job(guarded,done)
