from __future__ import annotations
import os, webbrowser
from pathlib import Path
import pcbnew, wx
from .analysis import auto_link, export_csv, harness_svg, load_pin_csv, validate_links
from .guided_ui import add_workflow, mark_primary, section

def make_sortable(table):
    state={"column":0,"reverse":False}
    def sort(event):
        column=event.GetColumn();state["reverse"]=not state["reverse"] if column==state["column"] else False;state["column"]=column;rows=[[table.GetItemText(r,c) for c in range(table.GetColumnCount())] for r in range(table.GetItemCount())];rows.sort(key=lambda row:row[column].casefold(),reverse=state["reverse"]);table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);[table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)]
    table.Bind(wx.EVT_LIST_COL_CLICK,sort)

class HarnessWorkbenchPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name="KiWay Harness and Cable Workbench";self.category="Documentation";self.description="Cross-link board connector documents into reviewed harness wire lists.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"icon.png");self.dark_icon_file_name=self.icon_file_name;self.version="0.1.0"
    def Run(self):HarnessFrame(None).Show()

class HarnessFrame(wx.Frame):
    def __init__(self,parent):super().__init__(parent,title="KiWay Harness and Cable Workbench",size=(1250,800));self.sources=[];self.destinations=[];self.links=[];self._build();self.Centre()
    def _build(self):
        p=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,root,"Harness and Cable Workbench","Cross-link reviewed connector pin documents into an auditable wire list and harness diagram.",("Import","Match","Review","Export"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()))
        input_box=section(p,"Endpoint Documents and Matching")
        input_parent=input_box.GetStaticBox()
        controls=wx.FlexGridSizer(2,6,7,8);controls.AddGrowableCol(1,1);controls.AddGrowableCol(3,1);self.source_label=wx.TextCtrl(input_parent,style=wx.TE_READONLY);self.dest_label=wx.TextCtrl(input_parent,style=wx.TE_READONLY);a=wx.Button(input_parent,label="Import Source…");a.Bind(wx.EVT_BUTTON,lambda e:self.load(True));b=wx.Button(input_parent,label="Import Destination…");b.Bind(wx.EVT_BUTTON,lambda e:self.load(False));controls.Add(a);controls.Add(self.source_label,1,wx.EXPAND);controls.Add(b);controls.Add(self.dest_label,1,wx.EXPAND)
        self.sp=wx.TextCtrl(input_parent,value="*");self.dp=wx.TextCtrl(input_parent,value="*");self.regex=wx.CheckBox(input_parent,label="Use regex capture groups");link=mark_primary(wx.Button(input_parent,label="Build Preview"),"Build a read-only harness preview from the imported endpoints");link.Bind(wx.EVT_BUTTON,self.preview);controls.Add(wx.StaticText(input_parent,label="Source net pattern"));controls.Add(self.sp,1,wx.EXPAND);controls.Add(wx.StaticText(input_parent,label="Destination net pattern"));controls.Add(self.dp,1,wx.EXPAND);controls.Add(self.regex);controls.Add(link);input_box.Add(controls,1,wx.EXPAND|wx.ALL,8);root.Add(input_box,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,10)
        properties_box=section(p,"Cable Properties");properties_parent=properties_box.GetStaticBox();cable=wx.BoxSizer(wx.HORIZONTAL);self.awg=wx.ComboBox(properties_parent,choices=["30","28","26","24","22","20","18","16"],value="24",style=wx.CB_READONLY);self.pair=wx.TextCtrl(properties_parent);self.shield=wx.ComboBox(properties_parent,choices=["","Overall shield","Pair shield","Drain wire"],style=wx.CB_READONLY);apply=wx.Button(properties_parent,label="Apply to Selected or All");apply.Bind(wx.EVT_BUTTON,self.apply_properties)
        for label,control in (("Wire gauge (AWG)",self.awg),("Pair or bundle",self.pair),("Shield",self.shield)):cable.Add(wx.StaticText(properties_parent,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5);cable.Add(control,0,wx.RIGHT,12)
        cable.Add(apply);properties_box.Add(cable,1,wx.EXPAND|wx.ALL,8);root.Add(properties_box,0,wx.EXPAND|wx.ALL,10)
        self.table=wx.ListCtrl(p,style=wx.LC_REPORT);cols=("Wire","Source project","Source pin","Source net","Destination project","Destination pin","Destination net","AWG","Pair","Shield","Status")
        for i,name in enumerate(cols):self.table.InsertColumn(i,name,width=120 if i not in (3,6) else 190)
        make_sortable(self.table)
        root.Add(self.table,1,wx.EXPAND|wx.ALL,8);foot=wx.BoxSizer(wx.HORIZONTAL);self.status=wx.StaticText(p,label="Import two KiWay pin CSV documents.");foot.Add(self.status,1,wx.ALIGN_CENTER_VERTICAL);diagram=wx.Button(p,label="Export Harness SVG…");diagram.Bind(wx.EVT_BUTTON,self.export_diagram);foot.Add(diagram,0,wx.RIGHT,8);export=wx.Button(p,label="Export Reviewed Wire List CSV…");export.Bind(wx.EVT_BUTTON,self.export);foot.Add(export);root.Add(foot,0,wx.EXPAND|wx.ALL,8);p.SetSizer(root)
    def load(self,source):
        with wx.FileDialog(self,"Import pin table",wildcard="CSV (*.csv)|*.csv",style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            records=load_pin_csv(d.GetPath());setattr(self,"sources" if source else "destinations",records);(self.source_label if source else self.dest_label).SetValue(f"{Path(d.GetPath()).name}: {len(records)} pins")
    def preview(self,_event):
        try:self.links=auto_link(self.sources,self.destinations,self.sp.GetValue(),self.dp.GetValue(),self.regex.GetValue())
        except Exception as exc:wx.MessageBox(str(exc),"Linking failed",wx.OK|wx.ICON_ERROR);return
        self.table.DeleteAllItems()
        for link in self.links:
            row=(link.wire_id,link.source.project,f"{link.source.connector}.{link.source.pin}",link.source.net,link.destination.project,f"{link.destination.connector}.{link.destination.pin}",link.destination.net,link.gauge_awg,link.pair,link.shield,link.status);i=self.table.InsertItem(self.table.GetItemCount(),row[0]);[self.table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)]
        issues=validate_links(self.links);self.status.SetLabel(f"{len(self.links)} wires | {len(issues)} validation findings");self.guide.set_step(2,"Review validation status and assign cable properties.")
    def apply_properties(self,_event):
        selected=[];index=self.table.GetFirstSelected()
        while index!=-1:selected.append(self.table.GetItemText(index,0));index=self.table.GetNextSelected(index)
        targets=set(selected) if selected else {link.wire_id for link in self.links}
        for link in self.links:
            if link.wire_id in targets:link.gauge_awg=self.awg.GetValue();link.pair=self.pair.GetValue();link.shield=self.shield.GetValue()
        for row in range(self.table.GetItemCount()):
            if self.table.GetItemText(row,0) in targets:self.table.SetItem(row,7,self.awg.GetValue());self.table.SetItem(row,8,self.pair.GetValue());self.table.SetItem(row,9,self.shield.GetValue())
    def export(self,_event):
        if not self.links:return
        with wx.FileDialog(self,"Export harness",wildcard="CSV (*.csv)|*.csv",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:export_csv(d.GetPath(),self.links)
    def export_diagram(self,_event):
        if not self.links:return
        with wx.FileDialog(self,"Export harness diagram",wildcard="SVG (*.svg)|*.svg",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:Path(d.GetPath()).write_text(harness_svg(self.links),encoding="utf-8")
