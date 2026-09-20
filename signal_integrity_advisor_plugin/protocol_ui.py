"""Collect reviewed paths, assign bus roles, and review protocol-screen evidence."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import wx
import wx.grid
from .protocol_profiles import list_profiles
from .protocol_suite import screen_suite
from .protocol_view import text,html_report
from .cli import write_report


class ProtocolPanel(wx.Panel):
    def __init__(self,parent,quick,preview_class):
        super().__init__(parent);self.quick=quick;self.snapshots=[];self.result=None
        self.source=Path(quick.board.GetFileName()) if quick.board.GetFileName() else None
        self.digest=self._digest();self.profiles=list_profiles()
        root=wx.BoxSizer(wx.VERTICAL)
        root.Add(wx.StaticText(self,label='1  Choose an interface   2  Add screened paths and assign roles   3  Review checks and missing evidence'),0,wx.ALL,10)
        top=wx.BoxSizer(wx.HORIZONTAL)
        self.profile=wx.Choice(self,choices=[p['title'] for p in self.profiles]);self.profile.SetSelection(0)
        top.Add(self.profile,1,wx.RIGHT,10)
        add=wx.Button(self,label='Add current Quick SI path');add.Bind(wx.EVT_BUTTON,self.add_current)
        add.Bind(wx.EVT_UPDATE_UI,lambda e:e.Enable(self.quick.report is not None))
        top.Add(add,0,wx.RIGHT,6)
        remove=wx.Button(self,label='Remove selected path');remove.Bind(wx.EVT_BUTTON,self.remove);top.Add(remove)
        root.Add(top,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.description=wx.StaticText(self);root.Add(self.description,0,wx.EXPAND|wx.ALL,10)
        options=wx.CollapsiblePane(self,label='Optional engineering budgets — supplied by you, not compliance limits',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        pane=options.GetPane();form=wx.FlexGridSizer(0,4,6,10);self.budgets={}
        for key,label in [('max_delay_ns','Maximum delay (ns)'),('max_skew_ps','Maximum group skew (ps)'),('max_impedance_error_percent','Z target deviation (%)'),('max_delay_to_rise_ratio','Maximum delay / rise')]:
            control=wx.TextCtrl(pane);form.Add(wx.StaticText(pane,label=label),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND);self.budgets[key]=control;control.Bind(wx.EVT_TEXT,self.invalidate)
        form.AddGrowableCol(1);form.AddGrowableCol(3);pane.SetSizer(form);root.Add(options,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:self.Layout())
        self.routes=wx.grid.Grid(self);self.routes.CreateGrid(0,5)
        for i,(label,width) in enumerate([('Reviewed route',390),('Role',90),('Group',110),('Length mm',110),('Delay ns',110)]):self.routes.SetColLabelValue(i,label);self.routes.SetColSize(i,self.FromDIP(width))
        self.routes.SetRowLabelSize(self.FromDIP(35))
        self.routes.SetMinSize(self.FromDIP((-1,100)));root.Add(self.routes,0,wx.EXPAND|wx.ALL,10)
        self.routes.Bind(wx.grid.EVT_GRID_CELL_CHANGED,self.invalidate)
        self.routes.Bind(wx.grid.EVT_GRID_SELECT_CELL,self.select_route)
        self.book=wx.Notebook(self)
        check_page=wx.Panel(self.book);check_box=wx.BoxSizer(wx.VERTICAL)
        self.checks=wx.ListCtrl(check_page,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(label,width) in enumerate([('Status',130),('Check',225),('Measured',100),('Limit',90),('Unit',100),('Evidence',450)]):self.checks.InsertColumn(i,label,width=self.FromDIP(width))
        check_box.Add(self.checks,1,wx.EXPAND)
        self.check_detail=wx.TextCtrl(check_page,style=wx.TE_MULTILINE|wx.TE_READONLY,size=self.FromDIP((-1,75)))
        check_box.Add(self.check_detail,0,wx.EXPAND|wx.TOP,6);check_page.SetSizer(check_box)
        self.checks.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select_check)
        self.book.AddPage(check_page,'Check results')
        preview_page=wx.Panel(self.book);box=wx.BoxSizer(wx.VERTICAL);self.preview=preview_class(preview_page);box.Add(self.preview,1,wx.EXPAND)
        from .preview_kit import add_zoom_toolbar
        add_zoom_toolbar(preview_page,self.preview,box);preview_page.SetSizer(box);self.book.AddPage(preview_page,'Selected route')
        from .eye_ui import EyePanel
        self.eye=EyePanel(self.book);self.book.AddPage(self.eye,'Selected eye / step')
        self.evidence=wx.TextCtrl(self.book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.book.AddPage(self.evidence,'Profile and evidence')
        root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.status=wx.StaticText(self,label='Screen a route in Quick SI, then add its snapshot here. Roles: P/N for pairs, clock/data for buses; each pair/bus needs a group.')
        root.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        buttons=wx.BoxSizer(wx.HORIZONTAL);self.run_button=wx.Button(self,label='Run protocol suite');self.run_button.Disable();self.run_button.Bind(wx.EVT_BUTTON,self.run);buttons.Add(self.run_button,0,wx.RIGHT,8)
        self.export=wx.Button(self,label='Export suite report');self.export.Disable();self.export.Bind(wx.EVT_BUTTON,self.save);buttons.Add(self.export)
        root.Add(buttons,0,wx.ALIGN_RIGHT|wx.ALL,10);self.SetSizer(root)
        self.profile.Bind(wx.EVT_CHOICE,self.profile_changed);self.profile_changed(None)

    def _digest(self):
        return hashlib.sha256(self.source.read_bytes()).hexdigest() if self.source and self.source.is_file() else None

    def fresh(self):
        if self.digest!=self._digest():raise ValueError('The saved board changed. Reopen Quick SI and screen fresh paths before running or exporting this suite.')

    def invalidate(self,event=None):
        self.result=None;self.export.Disable();self.checks.DeleteAllItems();self.check_detail.SetValue('Select a check to read its full evidence.')
        if hasattr(self,'status'):self.status.SetLabel('Selection or budgets changed. Run the suite again; stored routes remain reviewed snapshots.')
        if event:event.Skip()

    def profile_changed(self,event):
        self.invalidate();profile=self.profiles[self.profile.GetSelection()]
        rate=profile.get('rate_Gbps');nyquist=profile.get('nyquist_GHz')
        timing=f"{text(rate)} {profile['rate_kind']}" if rate is not None else 'Device-defined rate'
        if nyquist is not None:timing+=f" · nominal Nyquist {text(nyquist)} GHz"
        self.description.SetLabel(f"{profile['family']} · {timing}\n{profile['instructions']}")
        self.description.Wrap(max(600,self.GetClientSize().width-30));self.evidence.SetValue(json.dumps(profile,indent=2,ensure_ascii=False));self.Layout()

    def add_current(self,event=None):
        try:
            self.fresh()
            if self.quick.report is None or self.quick.path is None:raise ValueError('Screen a path in Quick SI first.')
            if len(self.snapshots)>=64:raise ValueError('Use at most 64 reviewed paths per suite.')
            report=copy.deepcopy(self.quick.report);report.update(board=str(self.source) if self.source else None,board_sha256=self.digest)
            path=report['path'];identity=(path['net_name'],path['start_pad'],path['end_pad'])
            if any(s['identity']==identity for s in self.snapshots):raise ValueError('This path is already in the suite. Remove it before adding a refreshed screen.')
            self.invalidate();row=len(self.snapshots);self.snapshots.append(dict(identity=identity,report=report,path=self.quick.path,endpoints=list(self.quick.preview.route_endpoints)))
            self.routes.AppendRows()
            for col,value in enumerate([f'{identity[0]}: {identity[1]} → {identity[2]}','','',text(path.get('length_mm')),text(report.get('delay_ns'))]):
                self.routes.SetCellValue(row,col,value);self.routes.SetReadOnly(row,col,col not in (1,2))
            self.routes.SetCellEditor(row,1,wx.grid.GridCellChoiceEditor(['','P','N','clock','data','control'],allowOthers=False))
            self.routes.SetGridCursor(row,0);self.routes.SelectRow(row);self.show_route(row);self.run_button.Enable()
            self.status.SetLabel('Path snapshot added. Assign its role and group, add other lanes if needed, then run the suite.')
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def show_route(self,row):
        if not 0<=row<len(self.snapshots):return
        item=self.snapshots[row];self.preview.show_result(SimpleNamespace(primary=item['path'],mate=None));self.preview.route_endpoints=list(item['endpoints'])
        for section in item['path'].segments:
            if section.get('kind')=='zone' and 'start_mm' in section and 'end_mm' in section:
                self.preview.tracks.append((*section['start_mm'],*section['end_mm'],section['layer'],0,None))
        self.preview.fit();self.preview.Refresh();self.eye.show_result(item['report'].get('eye'))

    def select_route(self,event):self.show_route(event.GetRow());event.Skip()

    def select_check(self,event):
        if self.result is None:return
        check=self.result['checks'][event.GetIndex()]
        self.check_detail.SetValue(check.get('evidence',''))
        key=check.get('id','').split('.')
        if len(key)>2 and key[0]=='route' and key[1].isdigit():
            row=int(key[1]);self.routes.SetGridCursor(row,0);self.routes.SelectRow(row);self.show_route(row)

    def remove(self,event):
        row=self.routes.GetGridCursorRow()
        if not 0<=row<len(self.snapshots):return
        self.snapshots.pop(row);self.routes.DeleteRows(row);self.invalidate();self.run_button.Enable(bool(self.snapshots))
        self.preview.show_result(SimpleNamespace(primary=None,mate=None));self.eye.show_result(None)
        if self.snapshots:self.show_route(min(row,len(self.snapshots)-1))

    def run(self,event=None):
        self.invalidate()
        try:
            self.fresh();self.routes.SaveEditControlValue()
            paths=[]
            for row,snapshot in enumerate(self.snapshots):
                report=copy.deepcopy(snapshot['report']);report.update(suite_role=self.routes.GetCellValue(row,1).strip(),suite_group=self.routes.GetCellValue(row,2).strip());paths.append(report)
            budgets={key:float(control.GetValue()) for key,control in self.budgets.items() if control.GetValue().strip()}
            result=screen_suite(self.profiles[self.profile.GetSelection()]['id'],paths,budgets=budgets)
            result.update(paths=paths,board=str(self.source) if self.source else None,board_sha256=self.digest)
            self.result=result
            for check in result['checks']:
                key=check.get('id','');parts=key.split('.')
                label=('Path '+str(int(parts[1])+1)+' · '+parts[2].replace('_',' ') if len(parts)==3 and parts[0]=='route' and parts[1].isdigit() else key.replace('_',' ').replace('.',' · '))
                values=[check.get('status','').replace('_',' ').capitalize(),label,check.get('measured'),check.get('limit'),check.get('unit',''),check.get('evidence','')]
                index=self.checks.InsertItem(self.checks.GetItemCount(),text(values[0]))
                for col,value in enumerate(values[1:],1):self.checks.SetItem(index,col,text(value))
            if result['checks']:self.checks.Select(0)
            from collections import Counter
            counts=Counter(c['status'] for c in result['checks'])
            self.status.SetLabel(result['status']+' · '+', '.join(f'{n} {status.lower().replace("_"," ")}' for status,n in counts.items())+' · Screening only, not certification.')
            self.evidence.SetValue(json.dumps({k:v for k,v in result.items() if k!='paths'},indent=2,ensure_ascii=False));self.export.Enable();self.book.SetSelection(0)
        except (ValueError,TypeError,KeyError,OSError) as exc:self.status.SetLabel(str(exc))

    def save(self,event):
        if self.result is None:return
        try:self.fresh()
        except (ValueError,OSError) as exc:self.invalidate();self.status.SetLabel(str(exc));return
        with wx.FileDialog(self,'Export protocol suite',defaultDir=str(self.source.parent) if self.source else '',defaultFile='protocol-suite.html',wildcard='HTML (*.html)|*.html|JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:
                target=Path(dialog.GetPath());extension=target.suffix.lower()
                if extension not in ('.json','.html'):raise ValueError('Choose .html or .json for the suite report.')
                payload=html_report(self.result) if extension=='.html' else json.dumps(self.result,indent=2,allow_nan=False)
                write_report(target,payload,self.source or __file__,extension)
            except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))
