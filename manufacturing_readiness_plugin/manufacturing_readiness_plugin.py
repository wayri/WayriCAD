from __future__ import annotations
import json,os,subprocess,sys,webbrowser
from pathlib import Path
import pcbnew,wx
from .analysis import BoardMetrics,FabricatorProfile,audit_metrics,build_release,load_profile,save_profile
from .guided_ui import add_workflow

VERSION="0.1.0"
def make_sortable(table):
    state={"column":0,"reverse":False}
    def sort(event):
        column=event.GetColumn();state["reverse"]=not state["reverse"] if column==state["column"] else False;state["column"]=column;rows=[[table.GetItemText(r,c) for c in range(table.GetColumnCount())] for r in range(table.GetItemCount())];rows.sort(key=lambda row:row[column].casefold(),reverse=state["reverse"]);table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);[table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)]
    table.Bind(wx.EVT_LIST_COL_CLICK,sort)
class ManufacturingReadinessPlugin(pcbnew.ActionPlugin):
    def defaults(self):self.name="KiWay Manufacturing Readiness Manager";self.category="Fabrication";self.description="Audit fabricator capabilities and gate deterministic manufacturing releases.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"icon.png");self.dark_icon_file_name=self.icon_file_name;self.version=VERSION
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:return
        ManufacturingFrame(None,board).Show()
class ManufacturingFrame(wx.Frame):
    def __init__(self,parent,board):super().__init__(parent,title="KiWay Manufacturing Readiness Manager",size=(1200,820));self.board=board;self.profile=FabricatorProfile();self.checks=[];self.drc_passed=False;self.jobset_passed=None;self._build();self.Centre()
    def _build(self):
        p=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,root,"Manufacturing Readiness Manager","Compare the PCB against a fabricator profile, run KiCad checks, and build a deterministic release only after every gate passes.",("Profile","Audit","Verify","Release"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()))
        self.tabs=wx.Notebook(p);self.tabs.AddPage(self.profile_page(self.tabs),"Fabricator Profile");self.tabs.AddPage(self.audit_page(self.tabs),"Board Audit");self.tabs.AddPage(self.release_page(self.tabs),"Release Gate");root.Add(self.tabs,1,wx.EXPAND|wx.ALL,8);p.SetSizer(root)
    def profile_page(self,parent):
        p=wx.Panel(parent);r=wx.BoxSizer(wx.VERTICAL);g=wx.FlexGridSizer(0,2,7,10);g.AddGrowableCol(1,1);self.fields={}
        for label,key,value in (("Profile name","name",self.profile.name),("Minimum track (mm)","minimum_track_mm",str(self.profile.minimum_track_mm)),("Minimum clearance (mm)","minimum_clearance_mm",str(self.profile.minimum_clearance_mm)),("Minimum drill (mm)","minimum_drill_mm",str(self.profile.minimum_drill_mm)),("Minimum annular ring (mm)","minimum_annular_ring_mm",str(self.profile.minimum_annular_ring_mm)),("Maximum via aspect ratio","maximum_via_aspect_ratio",str(self.profile.maximum_via_aspect_ratio)),("Maximum copper layers","maximum_layers",str(self.profile.maximum_layers))):c=wx.TextCtrl(p,value=value);self.fields[key]=c;g.Add(wx.StaticText(p,label=label));g.Add(c,1,wx.EXPAND)
        r.Add(g,0,wx.EXPAND|wx.ALL,14);buttons=wx.BoxSizer(wx.HORIZONTAL);load=wx.Button(p,label="Load Profile JSON…");load.Bind(wx.EVT_BUTTON,self.load);save=wx.Button(p,label="Save Profile JSON…");save.Bind(wx.EVT_BUTTON,self.save);buttons.Add(load,0,wx.RIGHT,8);buttons.Add(save);r.Add(buttons,0,wx.ALL,14);p.SetSizer(r);return p
    def audit_page(self,parent):
        p=wx.Panel(parent);r=wx.BoxSizer(wx.VERTICAL);a=wx.Button(p,label="Audit Current Board Against Profile");a.Bind(wx.EVT_BUTTON,self.audit);r.Add(a,0,wx.ALL,10);self.audit_table=wx.ListCtrl(p,style=wx.LC_REPORT)
        for i,(n,w) in enumerate((("Status",90),("Check",250),("Board",220),("Requirement",220))):self.audit_table.InsertColumn(i,n,width=w)
        make_sortable(self.audit_table)
        r.Add(self.audit_table,1,wx.EXPAND|wx.ALL,10);p.SetSizer(r);return p
    def release_page(self,parent):
        p=wx.Panel(parent);r=wx.BoxSizer(wx.VERTICAL);self.project=wx.TextCtrl(p,value=str(Path(self.board.GetFileName()).parent if self.board.GetFileName() else ""));self.jobset=wx.TextCtrl(p);g=wx.FlexGridSizer(2,3,7,8);g.AddGrowableCol(1,1);g.Add(wx.StaticText(p,label="Project directory"));g.Add(self.project,1,wx.EXPAND);g.Add(wx.StaticText(p,label=""));g.Add(wx.StaticText(p,label="Optional .kicad_jobset"));g.Add(self.jobset,1,wx.EXPAND);browse=wx.Button(p,label="Browse…");browse.Bind(wx.EVT_BUTTON,self.pick_jobset);g.Add(browse);r.Add(g,0,wx.EXPAND|wx.ALL,10)
        actions=wx.BoxSizer(wx.HORIZONTAL);drc=wx.Button(p,label="Run JSON DRC");drc.Bind(wx.EVT_BUTTON,self.run_drc);job=wx.Button(p,label="Run Jobset");job.Bind(wx.EVT_BUTTON,self.run_jobset);package=wx.Button(p,label="Build Release ZIP…");package.Bind(wx.EVT_BUTTON,self.package);actions.Add(drc,0,wx.RIGHT,8);actions.Add(job,0,wx.RIGHT,8);actions.Add(package);r.Add(actions,0,wx.ALL,10);self.log=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY);r.Add(self.log,1,wx.EXPAND|wx.ALL,10);p.SetSizer(r);return p
    def current_profile(self):
        f=self.fields;return FabricatorProfile(f['name'].GetValue(),float(f['minimum_track_mm'].GetValue()),float(f['minimum_clearance_mm'].GetValue()),float(f['minimum_drill_mm'].GetValue()),float(f['minimum_annular_ring_mm'].GetValue()),float(f['maximum_via_aspect_ratio'].GetValue()),int(f['maximum_layers'].GetValue()))
    def load(self,_e):
        with wx.FileDialog(self,"Load profile",wildcard="JSON (*.json)|*.json",style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            self.profile=load_profile(d.GetPath());[self.fields[k].SetValue(str(v)) for k,v in vars(self.profile).items()]
    def save(self,_e):
        with wx.FileDialog(self,"Save profile",wildcard="JSON (*.json)|*.json",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:save_profile(d.GetPath(),self.current_profile())
    def metrics(self):
        tracks=[float(pcbnew.ToMM(i.GetWidth())) for i in self.board.GetTracks() if "VIA" not in str(getattr(i,"GetClass",lambda:"")()).upper() and hasattr(i,"GetWidth")];vias=[i for i in self.board.GetTracks() if "VIA" in str(getattr(i,"GetClass",lambda:"")()).upper()];drills=[float(pcbnew.ToMM(i.GetDrillValue())) for i in vias if hasattr(i,"GetDrillValue")];rings=[(float(pcbnew.ToMM(i.GetWidth()))-float(pcbnew.ToMM(i.GetDrillValue())))/2 for i in vias if hasattr(i,"GetDrillValue")];settings=self.board.GetDesignSettings();clearance=float(pcbnew.ToMM(getattr(settings,"GetSmallestClearanceValue",lambda:0)())) or self.current_profile().minimum_clearance_mm;layers=int(getattr(self.board,"GetCopperLayerCount",lambda:2)());thickness=float(pcbnew.ToMM(getattr(settings,"GetBoardThickness",lambda:pcbnew.FromMM(1.6))()));aspect=max((thickness/d for d in drills if d>0),default=0);return BoardMetrics(min(tracks,default=99),clearance,min(drills,default=99),min(rings,default=99),aspect,layers)
    def audit(self,_e):
        try:self.checks=audit_metrics(self.metrics(),self.current_profile());self.audit_table.DeleteAllItems();[(lambda row:(lambda i:[self.audit_table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)])(self.audit_table.InsertItem(self.audit_table.GetItemCount(),row[0])))((c.status,c.item,c.actual,c.requirement)) for c in self.checks]
        except Exception as exc:wx.MessageBox(str(exc),"Audit failed",wx.OK|wx.ICON_ERROR)
        else:self.guide.set_step(1,"Review capability checks, then run DRC and the selected jobset.")
    def pick_jobset(self,_e):
        with wx.FileDialog(self,"Select jobset",wildcard="KiCad jobsets (*.kicad_jobset)|*.kicad_jobset",style=wx.FD_OPEN) as d:
            if d.ShowModal()==wx.ID_OK:self.jobset.SetValue(d.GetPath())
    def run(self,cmd):
        cli=Path(sys.executable).with_name("kicad-cli.exe")
        if cmd and cmd[0]=="kicad-cli" and cli.exists():cmd[0]=str(cli)
        cp=subprocess.run(cmd,capture_output=True,text=True,timeout=300);self.log.AppendText("$ "+subprocess.list2cmdline(cmd)+"\n"+cp.stdout+cp.stderr+f"\nExit: {cp.returncode}\n\n");return cp.returncode
    def run_drc(self,_e):
        board=self.board.GetFileName();out=str(Path(board).with_suffix('.kiway-drc.json'));self.drc_passed=self.run(["kicad-cli","pcb","drc","--format","json","--output",out,"--exit-code-violations",board])==0;self.guide.set_step(2,"Resolve failed gates or build the reviewed manufacturing release.")
    def run_jobset(self,_e):
        project=next(Path(self.project.GetValue()).glob('*.kicad_pro'),None);job=self.jobset.GetValue()
        if project and job:self.jobset_passed=self.run(["kicad-cli","jobset","run","--stop-on-error","--file",job,str(project)])==0
    def package(self,_e):
        if not self.checks or any(c.status=='FAIL' for c in self.checks) or not self.drc_passed or (self.jobset.GetValue() and self.jobset_passed is not True):wx.MessageBox("Release requires a passing board audit, passing JSON DRC, and a passing selected jobset.","Release blocked",wx.OK|wx.ICON_WARNING);return
        with wx.FileDialog(self,"Release ZIP",wildcard="ZIP (*.zip)|*.zip",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            root=Path(self.project.GetValue());files=[p for p in root.iterdir() if p.suffix in {'.kicad_pcb','.kicad_sch','.kicad_pro','.kicad_dru','.gbr','.drl','.csv','.pos','.json'}];manifest=build_release(d.GetPath(),files,self.checks,VERSION);self.log.AppendText(f"Built {d.GetPath()} with {len(manifest['files'])} hashed files.\n")
