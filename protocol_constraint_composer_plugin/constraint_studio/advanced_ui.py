"""Native engineering/team pages. No browser or implicit remote connections.
These widgets require host wx acceptance; headless tests cover their core actions.
"""
import json, pathlib, threading
from dataclasses import asdict
import wx
import wx.grid as gridlib
import wx.lib.scrolledpanel as scrolled
from . import team, topology, field_solver
from .courtyards import check_regions, sync_workspace
from .engineering import builtin_profiles
from .help_system import tooltip_for


def message(parent,text,error=False):
    wx.MessageBox(str(text),'Constraint Studio',wx.OK|(wx.ICON_ERROR if error else wx.ICON_INFORMATION),parent)

def file_path(parent,title,save=False,wildcard='All files|*.*'):
    with wx.FileDialog(parent,title,wildcard=wildcard,style=(wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT if save else wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)) as d:
        return pathlib.Path(d.GetPath()) if d.ShowModal()==wx.ID_OK else None

def ask(parent,title,password=False):
    cls=wx.PasswordEntryDialog if password else wx.TextEntryDialog
    with cls(parent,title,'Constraint Studio') as d:return d.GetValue() if d.ShowModal()==wx.ID_OK else None

class Page(scrolled.ScrolledPanel):
    def __init__(self,parent,title,description):
        super().__init__(parent);self.s=wx.BoxSizer(wx.VERTICAL);self.SetSizer(self.s)
        t=wx.StaticText(self,label=title);f=t.GetFont();f.SetPointSize(f.GetPointSize()+3);f.SetWeight(wx.FONTWEIGHT_BOLD);t.SetFont(f);self.s.Add(t,0,wx.ALL,12)
        t=wx.StaticText(self,label=description);t.Wrap(900);self.s.Add(t,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.SetupScrolling(scroll_x=False)
    def line(self,title,default='',options=None):
        s=wx.BoxSizer(wx.HORIZONTAL);lab=wx.StaticText(self,label=title,size=(205,-1));lab.Wrap(205);s.Add(lab,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        v=wx.ComboBox(self,value=default,choices=options or [],style=wx.CB_DROPDOWN) if options is not None else wx.TextCtrl(self,value=default)
        tip=tooltip_for(title)
        if tip:v.SetToolTip(tip)
        s.Add(v,1,wx.EXPAND);self.s.Add(s,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12);return v
    def actions(self,items):
        s=wx.WrapSizer();self.s.Add(s,0,wx.EXPAND|wx.ALL,10)
        for title,fn in items:
            b=wx.Button(self,label=title);b.Bind(wx.EVT_BUTTON,fn)
            tip=tooltip_for(title)
            if tip:b.SetToolTip(tip)
            s.Add(b,0,wx.ALL,4)
    def report(self):
        t=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,240));self.s.Add(t,1,wx.EXPAND|wx.ALL,12);return t

class AdvancedPanel(wx.Panel):
    def __init__(self,parent,frame):
        super().__init__(parent);self.frame=frame;self.cancel=threading.Event();self.thread=None;self.catalog_rows=[]
        s=wx.BoxSizer(wx.VERTICAL);self.SetSizer(s);self.book=wx.Notebook(self);s.Add(self.book,1,wx.EXPAND)
        self.regions();self.catalogs();self.reviews();self.paths();self.fields();self.host()
        for i in range(self.book.GetPageCount()):self.book.GetPage(i).SetupScrolling(scroll_x=False)
        self.Bind(wx.EVT_WINDOW_DESTROY,lambda e:(self.cancel.set(),e.Skip()))
    def page(self,title,description):
        p=Page(self.book,title,description);self.book.AddPage(p,title);return p
    def guarded(self,fn):
        try:return fn()
        except Exception as e:message(self,e,True)
    def changed(self):
        self.frame.index=None;self.frame.editing=None;self.frame.refresh_rules();self.frame.workbench.refresh();self.frame.profile_panel.refresh()
    def regions(self):
        p=self.page('Managed regions','Lines, arcs, circles and nested contours are preserved in staged footprint-owned areas. Automatic synchronization is opt-in and only acts on the saved/staged snapshot; it never edits the open PCB.')
        p.actions([('Inspect managed scopes',lambda e:self.guarded(self.inspect_regions)),('Regenerate eligible scopes',lambda e:self.guarded(self.regenerate)),('BGA / IC wizard',self.frame.bga)])
        self.region_report=p.report()
    def inspect_regions(self):
        self.frame.collect();rows=[]
        for g in self.frame.w.guards:
            if g.get('mode')=='footprint-owned-contours-v1':state,detail=check_regions(self.frame.w.context,g)
            else:state,detail='legacy','Use File → Rebuild managed courtyard areas'
            rows.append({'name':g['name'],'component':g['reference'],'state':state,'detail':detail,'auto_sync':g.get('auto_sync',False)})
        self.region_report.ChangeValue(json.dumps(rows,indent=2))
    def regenerate(self):
        self.frame.collect();trial=self.frame.w.clone();names=sync_workspace(trial,explicit=True)
        if names:self.frame.checkpoint();self.frame.w=trial;self.changed()
        self.inspect_regions();message(self,'Staged regenerated areas: '+(', '.join(names) or 'none'))
    def catalogs(self):
        p=self.page('Shared catalog','Connect explicitly to a shared folder or an HTTPS static catalog. Versions are immutable and pinned by SHA-256. Importing a new definition does not silently migrate existing rule instances.')
        self.location=p.line('Folder or HTTPS root');p.actions([('Choose shared folder',lambda e:self.choose_catalog()),('Check versions',lambda e:self.guarded(self.check_catalog)),('Import selected version',lambda e:self.guarded(self.import_catalog)),('Publish local definition',lambda e:self.guarded(self.publish_catalog))])
        self.catalog_list=wx.ListBox(p);p.s.Add(self.catalog_list,0,wx.EXPAND|wx.ALL,12);self.catalog_list.SetMinSize((-1,150));self.catalog_report=p.report()
    def choose_catalog(self):
        with wx.DirDialog(self,'Choose a shared catalog directory') as d:
            if d.ShowModal()==wx.ID_OK:self.location.SetValue(d.GetPath())
    def catalog(self):
        loc=self.location.GetValue().strip()
        if not loc:raise ValueError('Choose an explicit catalog location first')
        if '://' in loc:return team.HTTPSCatalog(loc)
        return team.SharedCatalog(loc)
    def check_catalog(self):
        # A bounded synchronous metadata fetch is explicitly initiated by the user.
        self.catalog_rows=team.synchronization_plan(self.frame.w,self.catalog())
        self.catalog_list.Set([x['key']+' — '+x['status'] for x in self.catalog_rows]);self.catalog_report.ChangeValue(json.dumps(self.catalog_rows,indent=2))
    def import_catalog(self):
        i=self.catalog_list.GetSelection()
        if i<0:raise ValueError('Check versions and select one')
        row=self.catalog_rows[i];trial=self.frame.w.clone();team.pin_profile(trial,self.catalog(),row['key'],row['sha256'])
        self.frame.checkpoint();self.frame.w=trial;self.changed();self.check_catalog()
    def publish_catalog(self):
        cat=self.catalog()
        if not isinstance(cat,team.SharedCatalog):raise ValueError('HTTPS mirrors are read-only. Publish through your managed shared directory.')
        ps=list({p['id']+'@'+p['version']:p for p in builtin_profiles()+list(self.frame.w.metadata.get('profiles',{}).values())}.values())
        with wx.SingleChoiceDialog(self,'Select a profile definition. No board data is published.','Publish immutable profile',[p['id']+'@'+p['version'] for p in ps]) as d:
            if d.ShowModal()!=wx.ID_OK:return
            p=ps[d.GetSelection()]
        if wx.MessageBox('Publish '+p['id']+'@'+p['version']+' to\n'+str(cat.root)+'?','Confirm catalog write',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        key,digest=cat.publish(p);self.check_catalog();message(self,key+'\nSHA-256: '+digest)
    def reviews(self):
        p=self.page('Signed reviews','Ed25519 signatures bind board, rules, settings and profile bindings. Trust comes from a separately managed public-key registry—not an embedded key. This is not native DRC or fabrication accreditation.')
        self.principal=p.line('Reviewer identity');self.rationale=p.line('Review rationale');self.trust_path=p.line('External trust registry')
        self.required=p.line('Required independent approvals','1')
        p.actions([('Create encrypted signing key',lambda e:self.guarded(self.create_key)),('Create / add trusted public key',lambda e:self.guarded(self.trust_key)),('Sign current content',lambda e:self.guarded(self.sign)),('Verify signed reviews',lambda e:self.guarded(self.verify))])
        self.review_report=p.report()
        if not team.crypto_available():self.review_report.ChangeValue('Optional dependency missing: cryptography. Signed-review actions explain how to enable it; ordinary editing remains available. No key is generated or sent automatically.')
    def create_key(self):
        phrase=ask(self,'Signing-key passphrase (at least 12 characters)',True)
        if phrase is None:return
        private,public=team.generate_identity(phrase);p=file_path(self,'Save ENCRYPTED private key outside the project',True,'PEM key|*.pem')
        if not p:return
        pub=p.with_name(p.stem+'.public.pem')
        if pub.exists():raise ValueError('Public-key companion exists; select a different new filename')
        from .workspace import atomic_write
        atomic_write(p,private);p.chmod(0o600);atomic_write(pub,public)
        message(self,'Encrypted private key and public companion saved. Protect the private file and passphrase; only share the public companion.\nKey ID: '+team.key_id(public))
    def trust_key(self):
        p=file_path(self,'Select an Ed25519 PUBLIC key',wildcard='PEM key|*.pem')
        if not p:return
        public=p.read_bytes();kid=team.key_id(public);principal=ask(self,'Identity verified by your team administrator')
        if not principal:return
        target=file_path(self,'Save external trust registry (not in the project)',True,'JSON|*.json')
        if not target:return
        registry=json.loads(target.read_text('utf-8')) if target.exists() else {}
        if kid in registry and registry[kid].get('principal')!=principal:raise ValueError('Key already assigned to another identity')
        if wx.MessageBox('Trust this key as an APPROVER for '+principal+'?\n'+kid+'\nVerify its fingerprint through an independent channel.','Trust administrator action',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        registry[kid]={'public_key':public.decode(),'principal':principal,'roles':['approver']}
        from .workspace import atomic_write
        atomic_write(target,json.dumps(registry,indent=2).encode());self.trust_path.SetValue(str(target))
    def sign(self):
        self.frame.collect();p=file_path(self,'Select ENCRYPTED private signing key',wildcard='PEM key|*.pem')
        if not p:return
        phrase=ask(self,'Private-key passphrase',True)
        if phrase is None:return
        with wx.SingleChoiceDialog(self,'Sign your decision about the currently staged content','Signed decision',['reviewed','approved','rejected']) as d:
            if d.ShowModal()!=wx.ID_OK:return
            status=d.GetStringSelection()
        trial=self.frame.w.clone();record=team.sign_review(trial,p.read_bytes(),phrase,self.principal.GetValue(),self.rationale.GetValue(),status)
        self.frame.checkpoint();self.frame.w=trial;self.review_report.ChangeValue(json.dumps(record['body'],indent=2));self.changed()
    def verify(self):
        self.frame.collect();p=pathlib.Path(self.trust_path.GetValue())
        report=team.verify_reviews(self.frame.w,json.loads(p.read_text('utf-8')),int(self.required.GetValue()));self.review_report.ChangeValue(json.dumps(report,indent=2))
    def paths(self):
        p=self.page('Signal paths','Build a declared series path across resistor/connector pads. Native rules remain separate fromTo constraints on real KiCad nets. Extra branches are reported; no copper continuity, impedance or delay is inferred.')
        self.path_name=p.line('Constraint-set name','Interface path');self.source=p.line('Source endpoint (Ref-Pad)');self.sink=p.line('Sink endpoint (Ref-Pad)')
        self.total=p.line('Total budget (ps)');self.margin=p.line('Reserved margin (ps)','0')
        p.s.Add(wx.StaticText(p,label='Explicit component pass-throughs (one distinct pad pair per row):'),0,wx.LEFT,12)
        self.bridges=gridlib.Grid(p);self.bridges.CreateGrid(0,3)
        for i,n in enumerate(['From pad','To pad','Component delay (ps)']):self.bridges.SetColLabelValue(i,n);self.bridges.SetColSize(i,220)
        self.bridges.SetMinSize((-1,130));p.s.Add(self.bridges,0,wx.EXPAND|wx.ALL,12)
        p.actions([('Add pass-through',lambda e:self.bridges.AppendRows()),('Remove last',lambda e:self.bridges.DeleteRows(self.bridges.GetNumberRows()-1) if self.bridges.GetNumberRows() else None),('Preview logical path',lambda e:self.guarded(self.preview_path)),('Stage per-net rules',lambda e:self.guarded(self.install_path))])
        self.budgets=p.line('PCB segment budgets (ps, comma separated)');self.path_report=p.report()
    def path_values(self):
        if self.bridges.IsCellEditControlEnabled():self.bridges.SaveEditControlValue();self.bridges.DisableCellEditControl()
        return [{'from':self.bridges.GetCellValue(i,0).strip(),'to':self.bridges.GetCellValue(i,1).strip(),'delay_ps':self.bridges.GetCellValue(i,2).strip()} for i in range(self.bridges.GetNumberRows()) if any(self.bridges.GetCellValue(i,j).strip() for j in range(3))]
    def preview_path(self):
        self.frame.collect();plan=topology.series_path(self.frame.w.context,self.source.GetValue(),self.sink.GetValue(),self.path_values());self.path_report.ChangeValue(json.dumps(plan,indent=2))
    def install_path(self):
        self.frame.collect();trial=self.frame.w.clone()
        plan=topology.stage_path(trial,self.source.GetValue(),self.sink.GetValue(),self.path_values(),self.total.GetValue(),self.margin.GetValue(),self.budgets.GetValue().split(','),self.path_name.GetValue())
        self.frame.checkpoint();self.frame.w=trial;self.changed();self.path_report.ChangeValue(json.dumps(plan,indent=2))
    def fields(self):
        p=self.page('2-D line solver','Quasi-static electrostatic field solution, not a full-wave SI/PI solver. All dielectric dimensions are user inputs. Finite box, grid and zero-thickness assumptions must be checked before using a result.')
        self.kind=p.line('Cross-section','microstrip',['microstrip','stripline']);self.width=p.line('Trace width (mm)');self.height=p.line('Height to lower ground (mm)');self.er=p.line('Relative permittivity');self.gap=p.line('Differential edge gap (blank = single)')
        p.actions([('Solve coarse + refined grids',lambda e:self.solve()),('Cancel calculation',lambda e:self.cancel.set()),('Save numeric report',lambda e:self.guarded(self.save_field))]);self.field_report=p.report();self.field_result=None
    def solve(self):
        if self.thread and self.thread.is_alive():message(self,'A field calculation is already running.');return
        try:values=(float(self.width.GetValue()),float(self.height.GetValue()),float(self.er.GetValue()),float(self.gap.GetValue()) if self.gap.GetValue().strip() else None,self.kind.GetValue())
        except ValueError as e:message(self,e,True);return
        self.cancel.clear();self.field_report.ChangeValue('Solving two meshes. Cancellation is available. No constraints are changed by this calculation.')
        def done(result,error):
            if not self or self.IsBeingDeleted():return
            self.field_result=result;self.field_report.ChangeValue(str(error) if error else json.dumps(result,indent=2))
        def run():
            try:r=field_solver.convergence(*values,cancel=self.cancel.is_set);wx.CallAfter(done,r,None)
            except Exception as e:wx.CallAfter(done,None,e)
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
    def save_field(self):
        if not self.field_result:raise ValueError('Complete a field calculation first')
        p=file_path(self,'Save field calculation report',True,'JSON|*.json')
        if p:p.write_text(json.dumps(self.field_result,indent=2),encoding='utf-8')
    def host(self):
        p=self.page('Native inspection','Use KiCad’s own resolution dialog for the CURRENT OPEN BOARD. This does not inspect un-applied staged rules. The plugin never presents an offline candidate as a proven native winner.')
        p.actions([('Open native clearance resolution',lambda e:self.guarded(lambda:self.native_resolution(True))),('Open native constraint resolution',lambda e:self.guarded(lambda:self.native_resolution(False))),('Acceptance instructions',lambda e:message(self,'Use tools/acceptance.py from the source package or constraint_studio/acceptance.py from PCM. It writes machine-readable evidence; missing runtimes are SKIP, never PASS. See docs/ACCEPTANCE.md.'))])
        t=p.report();t.ChangeValue('Select two items directly in PCB Editor for clearance, or one for constraint resolution. If this KiCad build exposes a matching native menu action it is dispatched; otherwise instructions are shown. Cross-probe flags alone are not treated as the tool selection.')
    def native_resolution(self,pair):
        from .native_bridge import open_resolution
        self.frame.collect()
        if self.frame.w.dirty and wx.MessageBox('The workspace contains staged changes. Native inspection uses ONLY the open board’s current rules. Continue?','Different constraint snapshots',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        open_resolution(pair)
