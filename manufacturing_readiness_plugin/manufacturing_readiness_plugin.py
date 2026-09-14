from __future__ import annotations
import json,os,subprocess,sys,webbrowser,threading,tempfile
from pathlib import Path
import pcbnew,wx
from .analysis import BoardMetrics,FabricatorProfile,audit_metrics,build_release,load_profile,save_profile
from .verification import capture_inputs,VerificationSnapshot,find_cli,drc_evidence
from .guided_ui import add_workflow, mark_primary

VERSION="3.1.0"
STATUS_COLOURS={"PASS":"#3fa56b","WARN":"#d4a62a","FAIL":"#e34a43","INFO":"#3399cc"}

class ReadinessMeter(wx.Panel):
    """Native text status keeps the audit table central."""
    def __init__(self,parent):
        super().__init__(parent);self.counts={"PASS":0,"WARN":0,"FAIL":0};self.total=0
        row=wx.BoxSizer(wx.HORIZONTAL);self.label=wx.StaticText(self,label='No audit yet')
        row.Add(self.label,0,wx.ALIGN_CENTER_VERTICAL|wx.ALL,6);self.SetSizer(row)
    def update(self,checks):
        self.counts={"PASS":0,"WARN":0,"FAIL":0};self.total=len(checks)
        for c in checks:
            key=c.status.upper()[:4]
            for name in self.counts:
                if key.startswith(name[:4].lower()) or key==name:self.counts[name]+=1;break
        self.label.SetLabel(f"{self.counts['PASS']} passed · {self.counts['FAIL']} failed · {self.counts['WARN']} warnings")
        self.Layout()


def make_sortable(table):
    state={"column":0,"reverse":False}
    def sort(event):
        column=event.GetColumn();state["reverse"]=not state["reverse"] if column==state["column"] else False;state["column"]=column;rows=[[table.GetItemText(r,c) for c in range(table.GetColumnCount())] for r in range(table.GetItemCount())];rows.sort(key=lambda row:row[column].casefold(),reverse=state["reverse"]);table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);[table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)]
    table.Bind(wx.EVT_LIST_COL_CLICK,sort)
class ManufacturingReadinessPlugin(pcbnew.ActionPlugin):
    def defaults(self):self.name="WayriCAD Manufacturing Readiness Manager";self.category="Fabrication";self.description="Audit fabricator capabilities and gate deterministic manufacturing releases.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"resources","icon-24.png");self.dark_icon_file_name=os.path.join(os.path.dirname(__file__),"resources","icon-dark-24.png");self.version=VERSION
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:return
        ManufacturingFrame(None,board).Show()
class ManufacturingFrame(wx.Frame):
    def __init__(self,parent,board):
        super().__init__(parent,title="WayriCAD Manufacturing Readiness Manager",size=(1200,820))
        self.board=board;self.profile=FabricatorProfile();self.checks=[];self.snapshot=None
        self.busy=False;self.closing=False;self.process=None
        self._build();self.Centre();self.Bind(wx.EVT_CLOSE,self.on_close)
        for control in [*self.fields.values(),self.project,self.jobset]:control.Bind(wx.EVT_TEXT,self.invalidate)
        self.refresh_actions()
    def _build(self):
        p=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,root,"Manufacturing Readiness Manager","Save the board and project first. Audit and CLI checks use one private saved-design copy; changing inputs invalidates the release gates.",("Profile","Audit","Verify","Release"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()))
        self.tabs=wx.Notebook(p)
        profile=self.profile_page(self.tabs)
        review=wx.Panel(self.tabs);review_sizer=wx.BoxSizer(wx.VERTICAL)
        review_sizer.Add(self.audit_page(review),1,wx.EXPAND)
        self.verification_pane=wx.CollapsiblePane(review,label='Project, jobset & command log',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        pane=self.verification_pane.GetPane();pane_sizer=wx.BoxSizer(wx.VERTICAL)
        details=self.release_page(pane);details.SetMinSize(self.FromDIP((-1,230)))
        pane_sizer.Add(details,1,wx.EXPAND);pane.SetSizer(pane_sizer)
        self.verification_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(review.Layout(),self.Layout()))
        review_sizer.Add(self.verification_pane,0,wx.EXPAND|wx.ALL,10);review.SetSizer(review_sizer)
        self.tabs.AddPage(review,'Review & release');self.tabs.AddPage(profile,'Fabricator profile')
        root.Add(self.tabs,1,wx.EXPAND|wx.ALL,8);p.SetSizer(root)
    def profile_page(self,parent):
        p=wx.Panel(parent);r=wx.BoxSizer(wx.VERTICAL);g=wx.FlexGridSizer(0,2,7,10);g.AddGrowableCol(1,1);self.fields={}
        for label,key,value in (("Profile name","name",self.profile.name),("Minimum track (mm)","minimum_track_mm",str(self.profile.minimum_track_mm)),("Minimum clearance (mm)","minimum_clearance_mm",str(self.profile.minimum_clearance_mm)),("Minimum drill (mm)","minimum_drill_mm",str(self.profile.minimum_drill_mm)),("Minimum annular ring (mm)","minimum_annular_ring_mm",str(self.profile.minimum_annular_ring_mm)),("Maximum via aspect ratio","maximum_via_aspect_ratio",str(self.profile.maximum_via_aspect_ratio)),("Maximum copper layers","maximum_layers",str(self.profile.maximum_layers))):c=wx.TextCtrl(p,value=value);self.fields[key]=c;g.Add(wx.StaticText(p,label=label));g.Add(c,1,wx.EXPAND)
        r.Add(g,0,wx.EXPAND|wx.ALL,14);buttons=wx.BoxSizer(wx.HORIZONTAL);load=wx.Button(p,label="Load Profile JSON…");load.Bind(wx.EVT_BUTTON,self.load);save=wx.Button(p,label="Save Profile JSON…");save.Bind(wx.EVT_BUTTON,self.save);buttons.Add(load,0,wx.RIGHT,8);buttons.Add(save);r.Add(buttons,0,wx.ALL,14);p.SetSizer(r);return p
    def audit_page(self,parent):
        p=wx.Panel(parent);r=wx.BoxSizer(wx.VERTICAL)
        source=wx.StaticText(p,label=Path(self.board.GetFileName()).name or 'Save a PCB to begin')
        source.SetToolTip('Audit and verification use saved design copies. The editor must match the saved PCB.')
        r.Add(source,0,wx.LEFT|wx.RIGHT|wx.TOP,10)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.actions={}
        for label,handler,tip in [('Audit saved design',self.audit,'Capture saved files and check manufacturing limits'),('Run DRC',self.run_drc,'Verify the audited snapshot with KiCad'),('Run jobset',self.run_jobset,'Run the selected optional jobset after DRC'),('Export release…',self.package,'Package the exact verified snapshot and generated artifacts')]:
            button=wx.Button(p,label=label);button.SetToolTip(tip);button.Bind(wx.EVT_BUTTON,handler)
            if handler==self.audit:button.SetDefault()
            self.actions[handler.__name__]=button
            row.Add(button,0,wx.RIGHT,7)
        row.AddStretchSpacer();self.meter=ReadinessMeter(p);row.Add(self.meter,0,wx.ALIGN_CENTER_VERTICAL)
        r.Add(row,0,wx.EXPAND|wx.ALL,10);self.audit_table=wx.ListCtrl(p,style=wx.LC_REPORT)
        for i,(n,w) in enumerate((("Status",90),("Check",250),("Board",220),("Requirement",220))):self.audit_table.InsertColumn(i,n,width=w)
        make_sortable(self.audit_table)
        r.Add(self.audit_table,1,wx.EXPAND|wx.ALL,10);p.SetSizer(r);return p
    def release_page(self,parent):
        p=wx.Panel(parent);r=wx.BoxSizer(wx.VERTICAL);self.project=wx.TextCtrl(p,value=str(Path(self.board.GetFileName()).parent if self.board.GetFileName() else ""));self.jobset=wx.TextCtrl(p);g=wx.FlexGridSizer(2,3,7,8);g.AddGrowableCol(1,1);g.Add(wx.StaticText(p,label="Project directory"));g.Add(self.project,1,wx.EXPAND);g.Add(wx.StaticText(p,label=""));g.Add(wx.StaticText(p,label="Optional .kicad_jobset"));g.Add(self.jobset,1,wx.EXPAND);browse=wx.Button(p,label="Browse…");browse.Bind(wx.EVT_BUTTON,self.pick_jobset);g.Add(browse);r.Add(g,0,wx.EXPAND|wx.ALL,10)
        self.log=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY);r.Add(self.log,1,wx.EXPAND|wx.ALL,10);p.SetSizer(r);return p
    def current_profile(self):
        f=self.fields;return FabricatorProfile(f['name'].GetValue(),float(f['minimum_track_mm'].GetValue()),float(f['minimum_clearance_mm'].GetValue()),float(f['minimum_drill_mm'].GetValue()),float(f['minimum_annular_ring_mm'].GetValue()),float(f['maximum_via_aspect_ratio'].GetValue()),int(f['maximum_layers'].GetValue()))
    def load(self,_e):
        with wx.FileDialog(self,"Load profile",wildcard="JSON (*.json)|*.json",style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            self.profile=load_profile(d.GetPath());[self.fields[k].SetValue(str(v)) for k,v in vars(self.profile).items()]
    def save(self,_e):
        with wx.FileDialog(self,"Save profile",wildcard="JSON (*.json)|*.json",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:save_profile(d.GetPath(),self.current_profile())
    def invalidate(self,event=None):
        if self.snapshot:self.snapshot.drc=False;self.snapshot.jobset=False
        self.checks=[]
        self.refresh_actions()
        self.guide.set_step(0,'Inputs changed. Save the design, then repeat Audit Saved Design and verification.')
        if event:event.Skip()

    def refresh_actions(self):
        if not hasattr(self,'actions'):return
        passing=bool(self.snapshot and self.checks and not any(c.status=='FAIL' for c in self.checks))
        self.actions['audit'].Enable(not self.busy)
        self.actions['run_drc'].Enable(passing and not self.busy)
        self.actions['run_jobset'].Enable(bool(passing and self.snapshot.drc and self.snapshot.job_name) and not self.busy)
        self.actions['package'].Enable(bool(passing and self.snapshot.drc and (not self.snapshot.job_name or self.snapshot.jobset)) and not self.busy)

    def on_close(self,event):
        self.closing=True
        if self.process is not None:
            try:self.process.terminate()
            except OSError:pass
        event.Skip()

    def live_text(self):
        if getattr(pcbnew,'_wayricad_ipc',False):
            return self.board.raw.get_as_string()
        if not hasattr(pcbnew,'PCB_IO_KICAD_SEXPR'):
            raise ValueError('This KiCad build cannot serialize the live board for release verification.')
        filename=self.board.GetFileName()
        with tempfile.TemporaryDirectory(prefix='wayricad-live-check-') as directory:
            target=Path(directory)/'live.kicad_pcb'
            try:pcbnew.PCB_IO_KICAD_SEXPR().SaveBoard(str(target),self.board)
            finally:
                if self.board.GetFileName()!=filename:self.board.SetFileName(filename)
            return target.read_text(encoding='utf-8-sig')

    def context(self):
        return capture_inputs(self.board.GetFileName(),self.project.GetValue(),self.current_profile(),
                              self.jobset.GetValue().strip(),self.live_text())

    def checked_snapshot(self):
        if self.snapshot is None:raise ValueError('Run Audit Saved Design first.')
        self.snapshot.validate(self.context()[1])
        return self.snapshot

    def audit(self,_e):
        if self.busy:return
        try:
            self.snapshot=None;self.checks=[]
            files,key,job=self.context()
            self.snapshot=VerificationSnapshot(files,key,Path(self.board.GetFileName()).name,job)
            self.checks=audit_metrics(self.snapshot.metrics,self.current_profile());self.audit_table.DeleteAllItems()
            for c in self.checks:
                row=(c.status,c.item,c.actual,c.requirement);i=self.audit_table.InsertItem(self.audit_table.GetItemCount(),row[0])
                for col,value in enumerate(row[1:],1):self.audit_table.SetItem(i,col,value)
                self.audit_table.SetItemTextColour(i,wx.Colour(STATUS_COLOURS.get(c.status.upper(),"#3c4043")))
            self.meter.update(self.checks)
        except Exception as exc:wx.MessageBox(str(exc),"Audit failed",wx.OK|wx.ICON_ERROR)
        else:
            self.log.AppendText('Captured saved inputs. Via metrics use saved sizes; aspect ratio conservatively uses full board thickness. Clearance is the saved minimum rule; DRC verifies actual geometry.\n')
            self.guide.set_step(1,"Review the saved-design audit, then run DRC followed by the selected jobset.")
        finally:self.refresh_actions()
    def pick_jobset(self,_e):
        with wx.FileDialog(self,"Select jobset",wildcard="KiCad jobsets (*.kicad_jobset)|*.kicad_jobset",style=wx.FD_OPEN) as d:
            if d.ShowModal()==wx.ID_OK:self.jobset.SetValue(d.GetPath())
    def run(self,cmd,snapshot,kind,report=None):
        cli=find_cli()
        if cli is None:raise ValueError('KiCad CLI was not found. Add the KiCad 10 or 11 bin directory to PATH.')
        cmd=[str(cli),*cmd];self.busy=True;self.tabs.Disable()
        # Clear the previous successful result before starting the replacement check.
        setattr(snapshot,kind,False)
        if kind=='drc':snapshot.jobset=False
        self.log.AppendText('Running '+kind+' in the private saved-design copy…\n')
        def work():
            error=None;details={};passed=False
            try:
                flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
                self.process=subprocess.Popen(cmd,cwd=snapshot.root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**flags)
                try:stdout,stderr=self.process.communicate(timeout=300)
                except subprocess.TimeoutExpired:
                    self.process.kill();self.process.communicate();raise ValueError('KiCad CLI exceeded five minutes and was stopped.')
                details={'command':cmd,'returncode':self.process.returncode,'stdout':stdout,'stderr':stderr}
                passed=self.process.returncode==0
                if report is not None and self.process.returncode in (0,5):
                    evidence=drc_evidence(report,self.process.returncode)
                    passed=evidence['clean']
                    details.update(evidence)
                    details['report']=Path(report).relative_to(snapshot.root).as_posix()
                snapshot.record(kind,passed,details)
            except Exception as exc:error=str(exc)
            finally:self.process=None
            if not self.closing:wx.CallAfter(done,passed,details,error)
        def done(passed,details,error):
            if self.closing:return
            self.busy=False;self.tabs.Enable()
            self.refresh_actions()
            if error:
                setattr(snapshot,kind,False);self.log.AppendText(error+'\n');return
            try:snapshot.validate(self.context()[1])
            except Exception as exc:
                snapshot.drc=False;snapshot.jobset=False;self.log.AppendText(str(exc)+'\n');return
            self.log.AppendText(details.get('stdout','')+details.get('stderr','')+'\n'+kind+(': PASS\n' if passed else ': FAILED\n'))
            if 'findings' in details:
                self.log.AppendText('DRC findings: '+', '.join(f'{key.replace("_"," ")}: {count}' for key,count in details['findings'].items())+'.\n')
            self.guide.set_step(2,'Verification belongs to the captured design only. Rerunning DRC requires rerunning the selected jobset.')
        threading.Thread(target=work,name='WayriCAD manufacturing check',daemon=True).start()

    def run_drc(self,_e):
        if self.busy:return
        try:
            snapshot=self.checked_snapshot();out=snapshot.root/'wayricad-drc.json'
            self.run(['pcb','drc','--format','json','--output',str(out),'--exit-code-violations',str(snapshot.root/snapshot.board_name)],snapshot,'drc',out)
        except Exception as exc:wx.MessageBox(str(exc),'DRC could not start',wx.OK|wx.ICON_ERROR)

    def run_jobset(self,_e):
        if self.busy:return
        try:
            snapshot=self.checked_snapshot()
            if not snapshot.drc:raise ValueError('Run passing DRC before the jobset.')
            if not snapshot.job_name:raise ValueError('Choose a saved project jobset, then repeat the audit.')
            project=(snapshot.root/snapshot.board_name).with_suffix('.kicad_pro')
            self.run(['jobset','run','--stop-on-error','--file',str(snapshot.root/snapshot.job_name),str(project)],snapshot,'jobset')
        except Exception as exc:wx.MessageBox(str(exc),'Jobset could not start',wx.OK|wx.ICON_ERROR)

    def package(self,_e):
        if self.busy:return
        try:
            snapshot=self.checked_snapshot();hashes=snapshot.ready(self.context()[1])
            if not self.checks or any(c.status=='FAIL' for c in self.checks):raise ValueError('Resolve all failed saved-design audit checks before release.')
            with wx.FileDialog(self,'Release ZIP',wildcard='ZIP (*.zip)|*.zip',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                # Dialogs can remain open while the PCB or files change.
                snapshot.ready(self.context()[1])
                manifest=build_release(dialog.GetPath(),[snapshot.root/name for name in hashes],self.checks,VERSION,
                    expected_hashes=hashes,base_directory=snapshot.root,evidence={'input_key':snapshot.key,'checks':snapshot.evidence,
                    'scope':'Saved project and outputs created inside its private verification copy; external jobset outputs are not included.'})
                self.log.AppendText(f"Built {dialog.GetPath()} with {len(manifest['files'])} verified files.\n")
        except Exception as exc:wx.MessageBox(str(exc),'Release blocked',wx.OK|wx.ICON_WARNING)
