from __future__ import annotations
import os,shutil,tempfile,time,webbrowser
from pathlib import Path
import pcbnew,wx
from .analysis import PRESETS,Assignment,ProtocolPreset,detect_protocols,generate_rules,merge_managed_rules
from .guided_ui import add_workflow, mark_primary

def make_sortable(table):
    state={"column":0,"reverse":False}
    def sort(event):
        column=event.GetColumn();state["reverse"]=not state["reverse"] if column==state["column"] else False;state["column"]=column;rows=[[table.GetItemText(r,c) for c in range(table.GetColumnCount())] for r in range(table.GetItemCount())];rows.sort(key=lambda row:row[column].casefold(),reverse=state["reverse"]);table.DeleteAllItems()
        for row in rows:i=table.InsertItem(table.GetItemCount(),row[0]);[table.SetItem(i,c,v) for c,v in enumerate(row[1:],1)]
    table.Bind(wx.EVT_LIST_COL_CLICK,sort)

PROTOCOL_COLOURS={"USB":"#3399cc","CAN":"#3fa56b","ETHERNET":"#d67142","PCIe/SerDes":"#a45ac7","DDR":"#d4a62a","RS-485":"#4fb3bf","RF":"#e34a43"}
def protocol_colour(name:str)->str:
    if name in PROTOCOL_COLOURS:return PROTOCOL_COLOURS[name]
    palette=tuple(PROTOCOL_COLOURS.values());return palette[sum(ord(c) for c in name)%len(palette)]

class ProtocolConstraintComposerPlugin(pcbnew.ActionPlugin):
    def defaults(self):self.name="KiWay Protocol Constraint Composer";self.category="Design Rules";self.description="Detect protocol nets and compose reviewed KiCad custom design rules.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"icon.png");self.dark_icon_file_name=self.icon_file_name;self.version="0.2.0"
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:return
        ConstraintFrame(None,board).Show()
class ConstraintFrame(wx.Frame):
    def __init__(self,parent,board):super().__init__(parent,title="KiWay Protocol Constraint Composer",size=(1200,820));self.board=board;self.assignments=[];self.generated="";self.presets=dict(PRESETS);self._build();self.Centre()
    def _build(self):
        p=wx.Panel(self);r=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,r,"Protocol Constraint Composer","Detect likely protocol nets and compose a reviewable KiCad managed-rule block with explicit geometry and backups.",("Detect","Assign","Preview","Apply"),lambda e:webbrowser.open(Path(__file__).with_name("help.html").as_uri()))
        split=wx.SplitterWindow(p);left=wx.Panel(split);right=wx.Panel(split);ls=wx.BoxSizer(wx.VERTICAL);rs=wx.BoxSizer(wx.VERTICAL);detect=mark_primary(wx.Button(left,label="Detect From Current Board"),"Detect likely protocol nets without modifying design rules");detect.Bind(wx.EVT_BUTTON,self.detect);ls.Add(detect,0,wx.EXPAND|wx.ALL,6)
        edit=wx.FlexGridSizer(0,4,5,6);edit.AddGrowableCol(1,1);self.protocol=wx.ComboBox(left,choices=list(self.presets),style=wx.CB_READONLY);self.protocol.SetSelection(0);self.width=wx.TextCtrl(left);self.clearance=wx.TextCtrl(left);self.gap=wx.TextCtrl(left);self.skew=wx.TextCtrl(left)
        for label,control in (("Protocol",self.protocol),("Width (mm)",self.width),("Clearance (mm)",self.clearance),("Differential gap (mm)",self.gap),("Maximum skew (mm)",self.skew)):edit.Add(wx.StaticText(left,label=label));edit.Add(control,1,wx.EXPAND)
        ls.Add(edit,0,wx.EXPAND|wx.ALL,6);self.protocol.Bind(wx.EVT_COMBOBOX,self.load_preset);self.load_preset(None)
        edit_actions=wx.BoxSizer(wx.HORIZONTAL);assign=wx.Button(left,label="Assign Protocol to Selected Rows");assign.SetToolTip("Assign the selected preset to each selected net row");assign.Bind(wx.EVT_BUTTON,self.assign_protocol);update=wx.Button(left,label="Update Protocol Geometry");update.SetToolTip("Update this session's preset from the entered geometry");update.Bind(wx.EVT_BUTTON,self.update_preset);edit_actions.Add(assign,1,wx.RIGHT,6);edit_actions.Add(update,1);ls.Add(edit_actions,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        self.table=wx.ListCtrl(left,style=wx.LC_REPORT);self.table.InsertColumn(0,"Protocol",width=150);self.table.InsertColumn(1,"Net",width=260);self.table.InsertColumn(2,"Detection",width=110);ls.Add(self.table,1,wx.EXPAND|wx.ALL,6);generate=wx.Button(left,label="Generate Rule Preview");generate.SetToolTip("Generate the exact managed rules for review");generate.Bind(wx.EVT_BUTTON,self.generate);ls.Add(generate,0,wx.EXPAND|wx.ALL,6);left.SetSizer(ls)
        make_sortable(self.table)
        chips_row=wx.BoxSizer(wx.HORIZONTAL);chips_label=wx.StaticText(left,label="Detected mix:");chips_label.SetFont(chips_label.GetFont().Bold());chips_row.Add(chips_label,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8);self.chips_host=wx.Panel(left);self.chips_sizer=wx.WrapSizer(wx.HORIZONTAL);self.chips_host.SetSizer(self.chips_sizer);chips_row.Add(self.chips_host,1,wx.EXPAND);ls.Add(chips_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        self.preview=wx.TextCtrl(right,style=wx.TE_MULTILINE|wx.TE_RICH2);self.preview.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)));rs.Add(self.preview,1,wx.EXPAND|wx.ALL,6);buttons=wx.BoxSizer(wx.HORIZONTAL);copy_rules=wx.Button(right,label="Copy Rules");copy_rules.SetToolTip("Copy the reviewed rule block to the clipboard");copy_rules.Bind(wx.EVT_BUTTON,self.copy_rules);export=wx.Button(right,label="Export .kicad_dru…");export.Bind(wx.EVT_BUTTON,self.export);apply=wx.Button(right,label="Apply Managed Block…");apply.Bind(wx.EVT_BUTTON,self.apply);buttons.Add(copy_rules,0,wx.RIGHT,8);buttons.Add(export,0,wx.RIGHT,8);buttons.Add(apply);rs.Add(buttons,0,wx.ALIGN_RIGHT|wx.ALL,6);right.SetSizer(rs);split.SplitVertically(left,right,500);r.Add(split,1,wx.EXPAND|wx.ALL,8);p.SetSizer(r)
    def refresh_chips(self):
        self.chips_sizer.Clear(delete_windows=True)
        counts={}
        for a in self.assignments:counts[a.protocol]=counts.get(a.protocol,0)+1
        for name,count in sorted(counts.items(),key=lambda item:(-item[1],item[0])):
            chip=wx.Panel(self.chips_host,size=(-1,24));chip.SetBackgroundColour(wx.Colour(protocol_colour(name)));text=wx.StaticText(chip,label=f" {name} × {count} ",style=wx.ALIGN_CENTER);row=wx.BoxSizer(wx.HORIZONTAL);row.Add(text,1,wx.ALIGN_CENTER_VERTICAL);chip.SetSizer(row);self.chips_sizer.Add(chip,0,wx.ALL,3)
        if not counts:
            empty=wx.StaticText(self.chips_host,label="run Detect to populate");empty.SetForegroundColour(wx.Colour("#78848f"));self.chips_sizer.Add(empty,0,wx.ALIGN_CENTER_VERTICAL)
        self.chips_host.Layout()
    def copy_rules(self,_event):
        if not self.generated and not self.preview.GetValue():return
        text=self.generated or self.preview.GetValue()
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text));wx.TheClipboard.Close()
    def nets(self):return sorted({str(pad.GetNetname()) for fp in self.board.GetFootprints() for pad in fp.Pads() if str(pad.GetNetname())})
    def detect(self,_e):
        self.assignments=detect_protocols(self.nets(),self.presets);self.table.DeleteAllItems()
        for a in self.assignments:i=self.table.InsertItem(self.table.GetItemCount(),a.protocol);self.table.SetItem(i,1,a.net);self.table.SetItem(i,2,a.confidence)
        self.guide.set_step(1,"Review detected assignments and adjust protocol geometry.")
    def generate(self,_e):
        rows=[]
        for i in range(self.table.GetItemCount()):
            protocol=self.table.GetItemText(i,0);net=self.table.GetItemText(i,1)
            if protocol in PRESETS and net:rows.append(Assignment(protocol,net,self.table.GetItemText(i,2)))
        self.generated=generate_rules(rows,self.presets);self.preview.SetValue(self.generated);self.guide.set_step(2,"Review the exact rule text, then export or apply it with a backup.")
    def load_preset(self,_event):
        preset=self.presets[self.protocol.GetValue()];self.width.SetValue(str(preset.width_mm));self.clearance.SetValue(str(preset.clearance_mm));self.gap.SetValue(str(preset.diff_gap_mm));self.skew.SetValue(str(preset.max_skew_mm))
    def update_preset(self,_event):
        current=self.presets[self.protocol.GetValue()]
        try:self.presets[current.name]=ProtocolPreset(current.name,current.patterns,float(self.width.GetValue()),float(self.clearance.GetValue()),float(self.gap.GetValue()),float(self.skew.GetValue()),current.target_ohm)
        except ValueError as exc:wx.MessageBox(str(exc),"Invalid geometry",wx.OK|wx.ICON_ERROR)
    def assign_protocol(self,_event):
        index=self.table.GetFirstSelected()
        while index!=-1:self.table.SetItem(index,0,self.protocol.GetValue());self.table.SetItem(index,2,"user");index=self.table.GetNextSelected(index)
    def export(self,_e):
        if not self.preview.GetValue():return
        with wx.FileDialog(self,"Export rules",wildcard="KiCad rules (*.kicad_dru)|*.kicad_dru",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:Path(d.GetPath()).write_text("(version 1)\n\n"+self.preview.GetValue(),encoding='utf-8')
    def apply(self,_e):
        board_file=Path(self.board.GetFileName())
        if not board_file or not self.preview.GetValue():return
        if wx.MessageBox("Apply the reviewed KiWay managed rule block? A timestamped backup will be created. Close Board Setup first.","Confirm rule update",wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING)!=wx.YES:return
        target=board_file.with_suffix('.kicad_dru');existing=target.read_text(encoding='utf-8') if target.exists() else '(version 1)\n';backup=target.with_name(target.name+f'.{time.strftime("%Y%m%d-%H%M%S")}.bak')
        if target.exists():shutil.copy2(target,backup)
        merged=merge_managed_rules(existing,self.preview.GetValue());fd,temp=tempfile.mkstemp(prefix=target.name,suffix='.tmp',dir=target.parent);os.close(fd);Path(temp).write_text(merged,encoding='utf-8');os.replace(temp,target);wx.MessageBox(f"Rules written to {target.name}.\nBackup: {backup.name if backup.exists() else 'new file'}\nOpen Board Setup and run Check rule syntax before DRC.","Rules applied",wx.OK|wx.ICON_INFORMATION)
