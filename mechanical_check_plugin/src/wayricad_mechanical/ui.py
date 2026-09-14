"""Native, keyboard-accessible wxWidgets workflow shared with KiCad."""
import json
import tempfile
import threading
from copy import deepcopy
from pathlib import Path

import wx
import wx.grid as grid
import wx.html

from .config import load, mount_defaults, save, validate
from .findings import finish
from .report import export
from .runner import run
from .runtime import Cancelled, discover
from .viewer import Scene
from .extract import is_mounting

INK, MUTED, BG, TEAL = '#242424', '#656565', '#f7f7f7', '#267269'


def label(parent, text, size=11, bold=False, color=INK):
    widget = wx.StaticText(parent, label=text)
    font = widget.GetFont()
    font.SetPointSize(size)
    if bold:
        font.SetWeight(wx.FONTWEIGHT_BOLD)
    widget.SetFont(font)
    widget.SetForegroundColour(color)
    return widget


def button(parent, text, action):
    widget = wx.Button(parent, label=text)
    widget.Bind(wx.EVT_BUTTON, action)
    return widget


class Window(wx.Frame):
    def __init__(self, board_path=None, rules_path=None, live_board=None, snapshot_of=None):
        super().__init__(None, title='WayriCAD Mechanical Check — Board validation', size=(1160, 820))
        self.SetMinSize((980, 700))
        self.SetBackgroundColour(BG)
        icon=Path(__file__).resolve().parents[2]/'resources/icon-24.png'
        if icon.exists():self.SetIcon(wx.Icon(str(icon),wx.BITMAP_TYPE_PNG))
        self.config = load(rules_path)
        self.rules_path = rules_path
        self.live_board = live_board
        self.snapshot_of = snapshot_of
        self.board_path = str(board_path or (live_board.GetFileName() if live_board else ''))
        self.result = None
        self.running = False
        self.cancel = threading.Event()
        self.mount_rows = []
        self.filtered = []
        self.step = 0
        root = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        navigation = wx.BoxSizer(wx.HORIZONTAL)
        navigation.Add(label(root, 'Mechanical Check', 12, True), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 18)
        self.nav_buttons=[]
        for i, title in enumerate(['Board', 'Rules', 'Run', 'Review', 'Report']):
            control=button(root,title,lambda e,n=i:self.show_step(n))
            navigation.Add(control,0,wx.RIGHT,5)
            self.nav_buttons.append(control)
        navigation.AddStretchSpacer()
        navigation.Add(button(root,'Help',self.help))
        layout.Add(navigation,0,wx.EXPAND|wx.ALL,12)
        content=wx.Panel(root)
        vertical=wx.BoxSizer(wx.VERTICAL)
        header=wx.BoxSizer(wx.HORIZONTAL)
        self.heading=label(content,'Board',14,True)
        header.Add(self.heading,1,wx.ALIGN_CENTER_VERTICAL)
        header.Add(label(content,'Saved board · millimetres',10,False,MUTED),0,wx.ALIGN_CENTER_VERTICAL)
        vertical.Add(header,0,wx.EXPAND|wx.ALL,12)
        self.book=wx.Simplebook(content)
        self.pages=[]
        for _ in range(5):
            page=wx.Panel(self.book)
            self.book.AddPage(page,'')
            self.pages.append(page)
        self.board_page()
        self.rules_page()
        self.run_page()
        self.review_page()
        self.report_page()
        vertical.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.status=label(content,'Checks the saved file. Save PCB edits before running.',10,False,MUTED)
        footer.Add(self.status,1,wx.ALIGN_CENTER_VERTICAL)
        self.back=button(content,'Back',lambda e:self.show_step(max(0,self.step-1)))
        self.next=button(content,'Continue',lambda e:self.show_step(min(4,self.step+1)))
        footer.Add(self.back,0,wx.RIGHT,10)
        footer.Add(self.next)
        vertical.Add(footer,0,wx.EXPAND|wx.ALL,12)
        content.SetSizer(vertical)
        layout.Add(content,1,wx.EXPAND)
        root.SetSizer(layout)
        self.Bind(wx.EVT_CLOSE,self.close)
        self.load_board()
        if snapshot_of:
            self.file.Disable()
            self.status.SetLabel('IPC snapshot captured at launch — reopen WayriCAD Mechanical Check after editing the PCB')
        self.show_step(0)
        self.Centre()

    def board_page(self):
        p=self.pages[0]; s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'Choose the saved board to check.',12,True),0,wx.BOTTOM,12)
        s.Add(label(p,'Inspect solid interference, fasteners, height allowances and assembly access.\nThe report records exactly what was checked and what needs more information.',11,False,MUTED),0,wx.BOTTOM,28)
        s.Add(label(p,'BOARD FILE',9,True,MUTED),0,wx.BOTTOM,8)
        self.file=wx.FilePickerCtrl(p,path=self.board_path,message='Choose a KiCad board',wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb',style=wx.FLP_OPEN|wx.FLP_FILE_MUST_EXIST|wx.FLP_USE_TEXTCTRL)
        self.file.Enable(self.live_board is None)
        self.file.Bind(wx.EVT_FILEPICKER_CHANGED,lambda e:self.load_board())
        s.Add(self.file,0,wx.EXPAND|wx.BOTTOM,22)
        form=wx.FlexGridSizer(cols=2,hgap=18,vgap=14);form.AddGrowableCol(1)
        self.project=wx.TextCtrl(p,value=self.config['project_name'])
        self.revision=wx.TextCtrl(p,value=self.config['project_revision'])
        self.reviewer=wx.TextCtrl(p,value=self.config['reviewer'])
        for title,control in [('Project name',self.project),('Revision / build',self.revision),('Reviewer',self.reviewer)]:
            form.Add(label(p,title),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
        s.Add(form,0,wx.EXPAND|wx.BOTTOM,25)
        self.board_stats=label(p,'Choose a board to inspect its model inventory.',12,True)
        s.Add(self.board_stats,0,wx.BOTTOM,18)
        runtime=discover()
        s.Add(label(p,'GEOMETRY ENGINE',9,True,MUTED),0,wx.BOTTOM,8)
        s.Add(label(p,'KiCad STEP exporter + FreeCAD / Open CASCADE\n'+('Executables found — Run checks runtime compatibility' if all(runtime.values()) else 'Setup needed — open Help'),11,False,MUTED),0,wx.BOTTOM,15)
        s.AddStretchSpacer()
        s.Add(label(p,'Missing STEP models are reported as coverage gaps. They never count as a pass.',10,False,TEAL),0,wx.BOTTOM,20)
        p.SetSizer(s)

    def rules_page(self):
        p=self.pages[1]; s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'Set the physical limits for this assembly.',14,True),0,wx.BOTTOM,14)
        fields=wx.FlexGridSizer(cols=4,vgap=10,hgap=14);fields.AddGrowableCol(1);fields.AddGrowableCol(3)
        self.numbers={}
        for title,key in [('3D clearance','clearance_mm'),('Top height','top_height_mm'),('Horizontal allowance','xy_clearance_mm'),('Bottom height','bottom_height_mm'),('Vertical allowance','z_clearance_mm'),('Nozzle radius','nozzle_radius_mm'),('Hardware clearance','screw_clearance_mm'),('Nozzle travel','nozzle_travel_mm')]:
            control=wx.SpinCtrlDouble(p,min=0,max=10000,inc=.1,initial=self.config[key]);control.SetDigits(3)
            fields.Add(label(p,title+' (mm)'),0,wx.ALIGN_CENTER_VERTICAL);fields.Add(control,1,wx.EXPAND)
            self.numbers[key]=control
        s.Add(fields,0,wx.EXPAND|wx.BOTTOM,14)
        self.dnp=wx.CheckBox(p,label='Include components marked Do Not Populate')
        self.dnp.SetValue(self.config['include_dnp']);s.Add(self.dnp,0,wx.BOTTOM,16)
        s.Add(label(p,'Mounting intent',13,True),0,wx.BOTTOM,5)
        s.Add(label(p,'Confirm each hole. Dimensions below describe your actual hardware, not a certified screw standard.',10,False,MUTED),0,wx.BOTTOM,10)
        self.mount_grid=grid.Grid(p)
        self.mount_grid.CreateGrid(0,9)
        for i,title in enumerate(['Ref','Actual','Required','Side','Head Ø','Washer Ø','Height','Shaft Ø','Tool R']):
            self.mount_grid.SetColLabelValue(i,title)
            self.mount_grid.SetColSize(i,90 if i!=2 else 112)
        self.mount_grid.SetRowLabelSize(0)
        s.Add(self.mount_grid,1,wx.EXPAND|wx.BOTTOM,12)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        for title,fn in [('Load rules…',self.import_rules),('Save rules…',self.save_rules),('Zones / enclosure / advanced…',self.advanced)]:
            actions.Add(button(p,title,fn),0,wx.RIGHT,8)
        s.Add(actions,0,wx.BOTTOM,10)
        p.SetSizer(s)

    def run_page(self):
        p=self.pages[2];s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'A complete mechanical review, with traceable evidence.',15,True),0,wx.TOP|wx.BOTTOM,18)
        for title,desc in [('01   Model coverage','Resolve STEP files and preserve KiCad placement, rotations and board side.'),('02   Physical fit','Measure solid interference, clearances, height limits and PCB penetration.'),('03   Hardware & assembly','Review plating intent, screw envelopes, nearby pads and nozzle access.')]:
            s.Add(label(p,title,13,True),0,wx.TOP,22);s.Add(label(p,desc,11,False,MUTED),0,wx.TOP,7)
        self.progress=wx.Gauge(p,range=100)
        s.Add(self.progress,0,wx.EXPAND|wx.TOP,30)
        self.progress_text=label(p,'Ready when you are.',11,False,TEAL);s.Add(self.progress_text,0,wx.TOP,12)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.run_button=button(p,'Run 3D validation',self.start)
        self.run_button.SetMinSize((200,44))
        self.cancel_button=button(p,'Cancel',lambda e:self.cancel.set());self.cancel_button.Disable()
        row.Add(self.run_button,0,wx.RIGHT,12);row.Add(self.cancel_button,0,wx.ALIGN_CENTER_VERTICAL)
        s.Add(row,0,wx.TOP,24);s.AddStretchSpacer()
        p.SetSizer(s)

    def review_page(self):
        p=self.pages[3];s=wx.BoxSizer(wx.VERTICAL)
        self.summary=label(p,'Run validation to see findings.',12,True);s.Add(self.summary,0,wx.BOTTOM,10)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.search=wx.SearchCtrl(p,style=wx.TE_PROCESS_ENTER);self.search.SetDescriptiveText('Search part, rule or finding')
        self.search.Bind(wx.EVT_TEXT,self.filter_findings)
        self.severity=wx.Choice(p,choices=['All findings','Errors','Warnings','Waived']);self.severity.SetSelection(0);self.severity.Bind(wx.EVT_CHOICE,self.filter_findings)
        row.Add(self.search,1,wx.RIGHT,10);row.Add(self.severity)
        s.Add(row,0,wx.EXPAND|wx.BOTTOM,10)
        split=wx.SplitterWindow(p,style=wx.SP_LIVE_UPDATE)
        left=wx.Panel(split);ls=wx.BoxSizer(wx.VERTICAL)
        self.scene=Scene(left);ls.Add(self.scene,1,wx.EXPAND)
        controls=wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(button(left,'Fit board',lambda e:self.scene.fit()),0,wx.RIGHT,8)
        controls.Add(button(left,'Focus contact',lambda e:self.scene.focus_contact()),0,wx.RIGHT,8)
        controls.Add(button(left,'Top',lambda e:self.set_view(0,0)),0,wx.RIGHT,8)
        controls.Add(button(left,'Isometric',lambda e:self.set_view(-.6,.8)))
        ls.Add(controls,0,wx.TOP|wx.BOTTOM,8)
        toggles=wx.BoxSizer(wx.HORIZONTAL)
        for title,key,initial in [('Isolate parts','isolate',True),('Transparent PCB','ghost',True),('Cutaway PCB','section',False)]:
            control=wx.CheckBox(left,label=title);control.SetValue(initial)
            control.Bind(wx.EVT_CHECKBOX,lambda e,k=key:(setattr(self.scene,k,e.IsChecked()),self.scene.Refresh()))
            toggles.Add(control,0,wx.RIGHT,10)
        ls.Add(toggles,0,wx.BOTTOM,8)
        ls.Add(label(left,'Red: exact contact volume (X-ray) · Gold: hardware allowance\nDrag: orbit · Right-drag: pan · Wheel: zoom',9,False,MUTED),0,wx.BOTTOM,8)
        left.SetSizer(ls)
        right=wx.Panel(split);rs=wx.BoxSizer(wx.VERTICAL)
        self.list=wx.ListCtrl(right,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(title,width) in enumerate([('Level',75),('Parts',100),('Finding',340)]):self.list.InsertColumn(i,title,width=width)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select_finding)
        rs.Add(self.list,1,wx.EXPAND)
        right.SetSizer(rs);split.SplitVertically(left,right,510);split.SetMinimumPaneSize(270)
        s.Add(split,1,wx.EXPAND)
        self.detail=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY|wx.BORDER_SIMPLE,size=(-1,115))
        s.Add(self.detail,0,wx.EXPAND|wx.TOP,10)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(button(p,'Locate in PCB editor',self.locate),0,wx.RIGHT,10)
        actions.Add(button(p,'Record / remove waiver…',self.waive),0,wx.RIGHT,10)
        actions.Add(button(p,'Model coverage…',self.coverage))
        s.Add(actions,0,wx.TOP|wx.BOTTOM,10);p.SetSizer(s)

    def report_page(self):
        p=self.pages[4];s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(p,'Share the review with your mechanical and assembly teams.',15,True),0,wx.BOTTOM,18)
        s.Add(label(p,'Each export creates a new project + UTC timestamp folder.\nThe interactive HTML report works offline; JSON preserves the complete run and CSV lists findings.',11,False,MUTED),0,wx.BOTTOM,20)
        self.report_info=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,260))
        s.Add(self.report_info,1,wx.EXPAND|wx.BOTTOM,18)
        self.export_button=button(p,'Export HTML + JSON + CSV…',self.export_report)
        self.export_button.SetMinSize((270,45));s.Add(self.export_button,0,wx.BOTTOM,20)
        p.SetSizer(s)

    def load_board(self):
        path=self.file.GetPath()
        self.board_path=path
        self.result=None
        self.export_button.Disable()
        self.list.DeleteAllItems()
        self.detail.Clear()
        self.report_info.Clear()
        self.summary.SetLabel('Run validation to see findings for this board.')
        self.scene.set_report({'bodies': []})
        if not path and not self.live_board:return
        try:
            import pcbnew as pcb
            board=self.live_board or pcb.LoadBoard(path)
            footprints=list(board.GetFootprints())
            count=sum(bool(list(f.Models())) for f in footprints)
            self.board_stats.SetLabel(f'{len(footprints):,} footprints    ·    {count:,} with model assignments    ·    {pcb.ToMM(board.GetDesignSettings().GetBoardThickness()):.2f} mm board')
            if not self.project.GetValue():self.project.SetValue(Path(path).stem)
            rows=[]
            for fp in footprints:
                if is_mounting(fp,self.config['mounts']):
                    for pad in fp.Pads():
                        if max(pad.GetDrillSize().x,pad.GetDrillSize().y):
                            rows.append((fp.GetReference(),'NPTH' if pad.GetAttribute()==pcb.PAD_ATTRIB_NPTH else 'PTH'))
                            break
            self.fill_mounts(sorted(rows))
            self.result=None
        except Exception as exc:
            self.board_stats.SetLabel('Could not read board: '+str(exc))

    def fill_mounts(self,rows):
        self.mount_rows=rows
        g=self.mount_grid
        if g.GetNumberRows():g.DeleteRows(0,g.GetNumberRows())
        if not rows:return
        g.AppendRows(len(rows))
        for row,(ref,actual) in enumerate(rows):
            m=self.config['mounts'].get(ref,mount_defaults())
            vals=[ref,actual,m['expected_plating'] if ref in self.config['mounts'] else 'Unconfirmed',m.get('side','top'),m.get('head_diameter_mm',0),m.get('washer_diameter_mm',0),m.get('head_height_mm',0),m.get('shaft_diameter_mm',0),m.get('tool_radius_mm',0)]
            for col,val in enumerate(vals):g.SetCellValue(row,col,str(val))
            g.SetReadOnly(row,0);g.SetReadOnly(row,1)
            g.SetCellEditor(row,2,grid.GridCellChoiceEditor(['Unconfirmed','NPTH','PTH','either']))
            g.SetCellEditor(row,3,grid.GridCellChoiceEditor(['top','bottom','both']))
            for col in range(4,9):g.SetCellEditor(row,col,grid.GridCellFloatEditor(precision=3))

    def get_config(self):
        if self.mount_grid.IsCellEditControlEnabled():
            self.mount_grid.SaveEditControlValue();self.mount_grid.DisableCellEditControl()
        c=deepcopy(self.config)
        c.update(project_name=self.project.GetValue().strip(),project_revision=self.revision.GetValue().strip(),reviewer=self.reviewer.GetValue().strip(),include_dnp=self.dnp.GetValue())
        c.update({key:control.GetValue() for key,control in self.numbers.items()})
        c['mounts']={}
        for row,(ref,actual) in enumerate(self.mount_rows):
            expected=self.mount_grid.GetCellValue(row,2)
            if expected=='Unconfirmed':continue
            m=dict(expected_plating=expected,side=self.mount_grid.GetCellValue(row,3))
            for col,key in enumerate(['head_diameter_mm','washer_diameter_mm','head_height_mm','shaft_diameter_mm','tool_radius_mm'],4):m[key]=float(self.mount_grid.GetCellValue(row,col))
            c['mounts'][ref]=m
        return validate(c)

    def show_step(self,n):
        if self.running and n!=2:return
        self.step=n;self.book.SetSelection(n)
        for index, control in enumerate(self.nav_buttons): control.Enable(index != n and not self.running)
        self.heading.SetLabel(['Board and project','Clearance and hardware rules','Run mechanical checks','Review findings','Export local report'][n])
        self.back.Enable(n>0 and not self.running);self.next.Enable(n<4 and not self.running)
        self.export_button.Enable(self.result is not None)
        self.Layout()

    def start(self,event):
        try:
            config=self.get_config()
            if not self.board_path and not self.live_board:raise ValueError('Choose a board first.')
            self.config=config
            path=self.board_path
            self.live_temp=None
            if self.live_board:
                import pcbnew
                self.live_temp=tempfile.TemporaryDirectory(prefix='wayricad-mechanical-live-')
                path=str(Path(self.live_temp.name)/'live.kicad_pcb')
                original=self.live_board.GetFileName()
                try:
                    if not pcbnew.SaveBoard(path,self.live_board):raise RuntimeError('Could not capture live board')
                finally:self.live_board.SetFileName(original)
            self.running=True;self.cancel.clear();self.result=None
            self.show_step(2);self.run_button.Disable();self.cancel_button.Enable()
            self.status.SetLabel('Validation running — your board remains editable')
            def worker():
                try:
                    result=run(path,config,lambda value,message:wx.CallAfter(self.update_progress,value,message),self.cancel,Path(self.snapshot_of or self.board_path).resolve().parent if self.board_path else None)
                    if self.live_board:
                        result.update(board_name=Path(self.board_path).name or 'Unsaved board',board_path=self.board_path,source_kind='live editor snapshot')
                    elif self.snapshot_of:
                        result.update(board_name=Path(self.snapshot_of).name,board_path=self.snapshot_of,source_kind='IPC snapshot captured at launch')
                    wx.CallAfter(self.completed,result,None)
                except Exception as exc:wx.CallAfter(self.completed,None,exc)
            threading.Thread(target=worker,daemon=True).start()
        except Exception as exc:wx.MessageBox(str(exc),'Check setup',wx.OK|wx.ICON_WARNING,self)

    def update_progress(self,value,message):
        self.progress.SetValue(value);self.progress_text.SetLabel(message)

    def completed(self,result,error):
        self.running=False;self.run_button.Enable();self.cancel_button.Disable()
        if self.live_temp:self.live_temp.cleanup();self.live_temp=None
        if error:
            self.progress_text.SetLabel('Cancelled.' if isinstance(error,Cancelled) else 'Validation could not finish.')
            self.status.SetLabel('No completed report is available')
            if not isinstance(error,Cancelled):wx.MessageBox(str(error),'Validation error',wx.OK|wx.ICON_ERROR,self)
            self.show_step(2);return
        self.result=result;self.scene.set_report(result);self.refresh_result();self.show_step(3)

    def refresh_result(self):
        r=self.result
        self.summary.SetLabel(f"{r['status'].replace('_',' ').upper()}   ·   {len(r['findings'])} findings   ·   {len(r['coverage']['gaps'])} coverage gaps")
        self.status.SetLabel('Completed '+r['local_timestamp'][:19].replace('T',' '))
        self.report_info.SetValue(f"Project: {r['project_name']}\nRevision: {r['project_revision'] or 'Unspecified'}\nBoard: {r['board_name']}\nReviewer: {r['reviewer'] or 'Unspecified'}\n\nStarted (UTC): {r['started_at']}\nCompleted (UTC): {r['completed_at']}\nLocal time: {r['local_timestamp']}\nDuration: {r['duration_seconds']} s\n\nResult: {r['status']}\nBoard SHA-256: {r['board_sha256']}\n\nEvery finding includes rule, affected references, evidence, measurement, corrective action and waiver reason.")
        self.filter_findings();self.export_button.Enable()

    def filter_findings(self,event=None):
        if not self.result:return
        self.list.DeleteAllItems();self.filtered=[]
        query=self.search.GetValue().lower();severity=self.severity.GetSelection()
        for f in self.result['findings']:
            if query and query not in json.dumps(f).lower():continue
            if severity==1 and f['severity']!='error' or severity==2 and f['severity']!='warning' or severity==3 and not f['waiver']:continue
            self.filtered.append(f)
            i=self.list.InsertItem(self.list.GetItemCount(),'Waived' if f['waiver'] else f['severity'].title())
            self.list.SetItem(i,1,', '.join(f['refs']));self.list.SetItem(i,2,f['summary'])
        if self.filtered:self.list.Select(0)
        else:self.detail.SetValue('No findings match this filter. Review model coverage before accepting the run.')

    def selected(self):
        index=self.list.GetFirstSelected()
        return self.filtered[index] if 0<=index<len(self.filtered) else None

    def select_finding(self,event):
        f=self.filtered[event.GetIndex()];self.scene.select(f)
        measurement='' if f['measured'] is None else f"\nMeasured: {f['measured']:.4f} {f.get('unit','')}" + (f"   Required: {f['limit']} {f.get('unit','')}" if f['limit'] is not None else '')
        self.detail.SetValue(f"{f['summary']}\n{f['rule']}  ·  Evidence: {f['evidence']}  ·  {', '.join(f['refs'])}{measurement}\n{f['action']}\n"+('Waiver: '+f['waiver'] if f['waiver'] else ''))

    def set_view(self,yaw,pitch):
        self.scene.yaw=-1.5708 if pitch==0 else -1.0
        self.scene.pitch=1.5707 if pitch==0 else .75
        self.scene.Refresh()

    def locate(self,event):
        f=self.selected()
        if not f:return
        try:
            import pcbnew
            board=pcbnew.GetBoard()
            if not board or (self.board_path and Path(board.GetFileName()).resolve()!=Path(self.board_path).resolve()):
                raise ValueError('Open this board in PCB Editor and launch WayriCAD Mechanical Check from its toolbar to locate parts.')
            for fp in board.GetFootprints():
                if fp.GetReference() in f['refs']:fp.SetSelected()
                else:fp.ClearSelected()
            pcbnew.Refresh()
        except Exception as exc:wx.MessageBox(str(exc),'Locate parts',wx.OK,self)

    def waive(self,event):
        f=self.selected()
        if not f:return
        with wx.TextEntryDialog(self,'Enter a review reason. Clear the text to remove an existing waiver.','Finding waiver',f['waiver']) as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            reason=dlg.GetValue().strip()
            if reason:self.config['waivers'][f['id']]=reason
            else:self.config['waivers'].pop(f['id'],None)
            self.result['rules']['waivers']=deepcopy(self.config['waivers'])
            finish(self.result,self.config);self.refresh_result()

    def coverage(self,event):
        if self.result:
            dlg=wx.Dialog(self,title='Model coverage and limits',size=(760,550))
            s=wx.BoxSizer(wx.VERTICAL);s.Add(wx.TextCtrl(dlg,value=json.dumps(self.result['coverage'],indent=2),style=wx.TE_MULTILINE|wx.TE_READONLY),1,wx.EXPAND|wx.ALL,15)
            s.Add(dlg.CreateButtonSizer(wx.OK),0,wx.ALL|wx.ALIGN_RIGHT,15);dlg.SetSizer(s);dlg.ShowModal();dlg.Destroy()

    def import_rules(self,event):
        with wx.FileDialog(self,'Load project rules',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            try:
                self.config=load(dlg.GetPath());self.rules_path=dlg.GetPath()
                for key,control in self.numbers.items():control.SetValue(self.config[key])
                self.project.SetValue(self.config['project_name']);self.revision.SetValue(self.config['project_revision']);self.reviewer.SetValue(self.config['reviewer']);self.dnp.SetValue(self.config['include_dnp'])
                self.load_board()
            except Exception as exc:wx.MessageBox(str(exc),'Invalid rules',wx.OK|wx.ICON_ERROR,self)

    def save_rules(self,event):
        try:
            config=self.get_config()
            with wx.FileDialog(self,'Save project rules',defaultFile=Path(self.board_path).stem+'.wayricad-mechanical.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dlg:
                if dlg.ShowModal()==wx.ID_OK:save(dlg.GetPath(),config);self.config=config;self.rules_path=dlg.GetPath()
        except Exception as exc:wx.MessageBox(str(exc),'Invalid rules',wx.OK|wx.ICON_WARNING,self)

    def advanced(self,event):
        keys=['height_zones','keepouts','enclosures','model_variables','volume_tolerance_mm3']
        dlg=wx.Dialog(self,title='Advanced physical rules',size=(760,600),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        s=wx.BoxSizer(wx.VERTICAL)
        s.Add(label(dlg,'Height zones use KiCad XY. Keepouts and enclosure STEP use CAD XYZ.\nSee Help for coordinates and examples.',11,False,MUTED),0,wx.ALL,15)
        editor=wx.TextCtrl(dlg,value=json.dumps({k:self.config[k] for k in keys},indent=2),style=wx.TE_MULTILINE)
        s.Add(editor,1,wx.EXPAND|wx.ALL,15);s.Add(dlg.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALL|wx.ALIGN_RIGHT,15);dlg.SetSizer(s)
        if dlg.ShowModal()==wx.ID_OK:
            try:
                changes=json.loads(editor.GetValue())
                if set(changes)-set(keys):raise ValueError('This editor only accepts the displayed advanced fields.')
                c=deepcopy(self.config);c.update(changes);self.config=validate(c)
            except Exception as exc:wx.MessageBox(str(exc),'Invalid advanced rules',wx.OK|wx.ICON_WARNING,self)
        dlg.Destroy()

    def export_report(self,event):
        if not self.result:return
        with wx.DirDialog(self,'Choose a reports folder') as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            try:
                paths=export(self.result,dlg.GetPath());self.status.SetLabel('Report saved: '+str(Path(paths['html']).parent))
                wx.LaunchDefaultBrowser(Path(paths['html']).as_uri())
            except Exception as exc:wx.MessageBox(str(exc),'Export error',wx.OK|wx.ICON_ERROR,self)

    def help(self,event):
        dlg=wx.Dialog(self,title='WayriCAD Mechanical Check — Help',size=(1050,820),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        dlg.SetMinSize((540,480))
        path=Path(__file__).resolve().parents[2]/'resources/help.html'
        if path.exists():
            from .help_viewer import HelpViewer
            viewer=HelpViewer(dlg,path)
        else:
            viewer=wx.html.HtmlWindow(dlg)
            viewer.SetPage('<h1>WayriCAD Mechanical Check help</h1><p>Reinstall the plugin ZIP to restore resources/help.html.</p>')
        s=wx.BoxSizer(wx.VERTICAL);s.Add(viewer,1,wx.EXPAND);s.Add(dlg.CreateButtonSizer(wx.OK),0,wx.ALL|wx.ALIGN_RIGHT,12);dlg.SetSizer(s);dlg.ShowModal();dlg.Destroy()

    def close(self,event):
        if self.running:
            self.cancel.set();self.status.SetLabel('Cancelling geometry worker — close again after it stops');event.Veto();return
        self.Destroy()


def launch(board_path=None,rules_path=None,snapshot_of=None,review_path=None):
    app=wx.App.Get() or wx.App(False)
    result=None
    if review_path:
        result=json.loads(Path(review_path).read_text(encoding='utf-8'))
        board_path=result['board_path']
    window=Window(board_path,rules_path,snapshot_of=snapshot_of)
    if result:
        window.result=result;window.config=result['rules'];window.scene.set_report(result)
        window.refresh_result();window.show_step(3)
        window.SetTitle('WayriCAD Mechanical Check — Shaded conflict review')
    window.Show()
    app.MainLoop()
