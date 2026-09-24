from __future__ import annotations
from wayricad_runtime.help import open_help as open_native_help
import os,webbrowser
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
    def defaults(self):self.name="WayriCAD Constraint Studio";self.category="Design Rules";self.description="Detect protocol nets and compose reviewed KiCad custom design rules.";self.show_toolbar_button=True;self.icon_file_name=os.path.join(os.path.dirname(__file__),"resources","icon-24.png");self.dark_icon_file_name=self.icon_file_name.replace("icon-24.png", "icon-dark-24.png");self.version="3.4.0"
    def Run(self):
        board=pcbnew.GetBoard()
        if board is None:return
        from .studio_ui import ConstraintStudioFrame
        ConstraintStudioFrame(None, str(board.GetFileName()), board).Show()
class ConstraintFrame(wx.Frame):
    def __init__(self,parent,board):super().__init__(parent,title="WayriCAD Protocol Constraint Composer",size=(1200,820));self.board=board;self.assignments=[];self.generated="";self.presets=dict(PRESETS);self._build();self.Centre()
    def _build(self):
        p=wx.Panel(self);r=wx.BoxSizer(wx.VERTICAL)
        self.guide=add_workflow(p,r,"Protocol Constraint Composer","Detect protocol nets and review their custom design rules.",("Detect","Assign","Preview","Stage"),lambda e:open_native_help(self,Path(__file__).with_name("help.html")))
        split=wx.SplitterWindow(p);left=wx.Panel(split);right=wx.Panel(split)
        ls=wx.BoxSizer(wx.VERTICAL);rs=wx.BoxSizer(wx.VERTICAL)
        detect=mark_primary(wx.Button(left,label="Detect Nets"),"Detect likely protocol nets without modifying design rules")
        detect.Bind(wx.EVT_BUTTON,self.detect);ls.Add(detect,0,wx.EXPAND|wx.ALL,6)
        assignment=wx.BoxSizer(wx.HORIZONTAL)
        self.protocol=wx.ComboBox(left,choices=list(self.presets),style=wx.CB_READONLY);self.protocol.SetSelection(0)
        assignment.Add(self.protocol,1,wx.RIGHT,6)
        assign=wx.Button(left,label="Assign to Selection");assign.Bind(wx.EVT_BUTTON,self.assign_protocol)
        assignment.Add(assign,0);ls.Add(assignment,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        geometry=wx.CollapsiblePane(left,label="Protocol geometry",style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        pane=geometry.GetPane();options=wx.BoxSizer(wx.VERTICAL)
        edit=wx.FlexGridSizer(0,2,5,8);edit.AddGrowableCol(1,1)
        self.width=wx.TextCtrl(pane);self.clearance=wx.TextCtrl(pane);self.gap=wx.TextCtrl(pane);self.skew=wx.TextCtrl(pane)
        for label,control in (("Width (mm)",self.width),("Clearance (mm)",self.clearance),("Differential gap (mm)",self.gap),("Maximum skew (mm)",self.skew)):
            edit.Add(wx.StaticText(pane,label=label),0,wx.ALIGN_CENTER_VERTICAL);edit.Add(control,1,wx.EXPAND)
        options.Add(edit,0,wx.EXPAND|wx.ALL,6)
        update=wx.Button(pane,label="Update Geometry");update.Bind(wx.EVT_BUTTON,self.update_preset)
        options.Add(update,0,wx.ALIGN_RIGHT|wx.ALL,6);pane.SetSizer(options)
        geometry.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:left.Layout())
        ls.Add(geometry,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        self.protocol.Bind(wx.EVT_COMBOBOX,self.load_preset);self.load_preset(None)
        self.table=wx.ListCtrl(left,style=wx.LC_REPORT)
        for i,(label,width) in enumerate((("Protocol",130),("Net",230),("Detection",100))):self.table.InsertColumn(i,label,width=width)
        make_sortable(self.table);ls.Add(self.table,1,wx.EXPAND|wx.ALL,6)
        generate=wx.Button(left,label="Preview Rules");generate.Bind(wx.EVT_BUTTON,self.generate)
        ls.Add(generate,0,wx.EXPAND|wx.ALL,6)
        self.chips_host=wx.Panel(left);self.chips_sizer=wx.WrapSizer(wx.HORIZONTAL);self.chips_host.SetSizer(self.chips_sizer)
        ls.Add(self.chips_host,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6);left.SetSizer(ls)
        self.preview=wx.TextCtrl(right,style=wx.TE_MULTILINE|wx.TE_RICH2)
        self.preview.SetHint("Preview rules to review their exact text here.")
        self.preview.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
        rs.Add(self.preview,1,wx.EXPAND|wx.ALL,6)
        buttons=wx.BoxSizer(wx.HORIZONTAL)
        more=wx.Button(right,label="More");more.SetToolTip("Copy rules or export a .kicad_dru file")
        more.Bind(wx.EVT_BUTTON,self.more_actions);buttons.Add(more,0,wx.RIGHT,8)
        apply=wx.Button(right,label="Stage in Constraint Studio");apply.Bind(wx.EVT_BUTTON,self.apply);buttons.Add(apply)
        rs.Add(buttons,0,wx.ALIGN_RIGHT|wx.ALL,6);right.SetSizer(rs)
        split.SplitVertically(left,right,480);split.SetMinimumPaneSize(340)
        r.Add(split,1,wx.EXPAND|wx.ALL,8);p.SetSizer(r)

    def more_actions(self,event):
        menu=wx.Menu()
        for label,handler in (("Copy Rules",self.copy_rules),("Export .kicad_dru…",self.export)):
            item=menu.Append(wx.ID_ANY,label);menu.Bind(wx.EVT_MENU,handler,id=item.GetId())
        try:event.GetEventObject().PopupMenu(menu)
        finally:menu.Destroy()
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
        text=self.preview.GetValue()
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text));wx.TheClipboard.Close()
    def nets(self):
        if self.board is None:
            from .constraint_studio.inspection import items_from_board
            workspace=self.GetParent().w
            return sorted(set(workspace.context.nets) | {item.net for item in items_from_board(workspace.context,workspace.project) if item.net})
        return sorted({str(pad.GetNetname()) for fp in self.board.GetFootprints() for pad in fp.Pads() if str(pad.GetNetname())})
    def detect(self,_e):
        self.generated="";self.preview.Clear()
        self.assignments=detect_protocols(self.nets(),self.presets);self.table.DeleteAllItems()
        for a in self.assignments:i=self.table.InsertItem(self.table.GetItemCount(),a.protocol);self.table.SetItem(i,1,a.net);self.table.SetItem(i,2,a.confidence)
        self.refresh_chips();self.guide.set_step(1,"Review detected assignments and adjust protocol geometry.")
    def generate(self,_e):
        rows=[]
        for i in range(self.table.GetItemCount()):
            protocol=self.table.GetItemText(i,0);net=self.table.GetItemText(i,1)
            if protocol in PRESETS and net:rows.append(Assignment(protocol,net,self.table.GetItemText(i,2)))
        try:self.generated=generate_rules(rows,self.presets)
        except ValueError as exc:wx.MessageBox(str(exc),"Invalid rules",wx.OK|wx.ICON_ERROR);return
        self.preview.SetValue(self.generated);self.guide.set_step(2,"Review the exact rule text, then stage it in Constraint Studio.")
    def load_preset(self,_event):
        preset=self.presets[self.protocol.GetValue()];self.width.SetValue(str(preset.width_mm));self.clearance.SetValue(str(preset.clearance_mm));self.gap.SetValue(str(preset.diff_gap_mm));self.skew.SetValue(str(preset.max_skew_mm))
    def update_preset(self,_event):
        current=self.presets[self.protocol.GetValue()]
        try:
            preset=ProtocolPreset(current.name,current.patterns,float(self.width.GetValue()),float(self.clearance.GetValue()),float(self.gap.GetValue()),float(self.skew.GetValue()),current.target_ohm)
            generate_rules([Assignment(current.name,'validation','user')],{current.name:preset})
            self.presets[current.name]=preset;self.generated="";self.preview.Clear()
        except ValueError as exc:wx.MessageBox(str(exc),"Invalid geometry",wx.OK|wx.ICON_ERROR)
    def assign_protocol(self,_event):
        self.generated="";self.preview.Clear()
        index=self.table.GetFirstSelected()
        while index!=-1:self.table.SetItem(index,0,self.protocol.GetValue());self.table.SetItem(index,2,"user");index=self.table.GetNextSelected(index)
    def export(self,_e):
        if not self.preview.GetValue():return
        with wx.FileDialog(self,"Export rules",wildcard="KiCad rules (*.kicad_dru)|*.kicad_dru",style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:Path(d.GetPath()).write_text("(version 1)\n\n"+self.preview.GetValue(),encoding='utf-8')
    def apply(self,_e):
        if not self.preview.GetValue():return
        try:
            studio=self.GetParent()
            if not hasattr(studio,'stage_protocols'):
                from .studio_ui import ConstraintStudioFrame
                studio=ConstraintStudioFrame(board_path=str(self.board.GetFileName()) if self.board else '')
                studio.Show()
            studio.stage_protocols(self.preview.GetValue());studio.Raise()
            self.guide.set_step(3,"Staged in Constraint Studio. Review and export from that window.")
        except Exception as exc:wx.MessageBox(str(exc),"Rules not staged",wx.OK|wx.ICON_ERROR)
