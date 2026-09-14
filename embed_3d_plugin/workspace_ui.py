"""Single-window KiCad 10 workspace: per-component/global asset checkboxes.

Native IO stays on the GUI thread; parsing, compression and plan creation run in
one cancellable worker. A preview is invalidated by any source/option/selection
change. Filtering never silently changes the selected scope.
"""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
import threading
import platform
import sys
import time
import traceback
import wx
import wx.dataview as dv
from . import __version__
from .assets import make_header_icon, set_window_icons
from .logging_utils import get_logger
from .paths import Resolver
from .portability_io import read_text, saved_project_variables
from .sexpr import parse
from . import workspace as ws
from .cli_validation import find_cli, validate_schematic

KIND_COLUMNS = {2:'symbols', 3:'footprints', 4:'models'}
ACTION_LABELS = {'embed':'Embed checked','embed-all':'Embed all', 'unbundle':'Unbundle',
                 'relink':'Relink', 'unbundle-relink':'Unbundle & relink'}


class ComponentModel(dv.DataViewIndexListModel):
    def __init__(self, changed):
        # wx may query virtual methods during initialization/reset.
        self.rows = []; self.changed = changed; self.locked = False
        super().__init__(0)

    def GetColumnCount(self): return 6
    def GetColumnType(self, col): return 'bool' if col in KIND_COLUMNS else 'string'
    def GetCount(self): return len(self.rows)

    def GetValueByRow(self, row, col):
        if not 0 <= row < len(self.rows):
            return False if col in KIND_COLUMNS else ''
        item = self.rows[row]
        if col in KIND_COLUMNS: return bool(item.checked[KIND_COLUMNS[col]] and item.available(KIND_COLUMNS[col]))
        return {0:item.reference, 1:item.value, 5:item.status}.get(col,'')

    def SetValueByRow(self, value, row, col):
        if self.locked or col not in KIND_COLUMNS or not 0 <= row < len(self.rows): return False
        item = self.rows[row]; kind = KIND_COLUMNS[col]
        if not item.available(kind): return False
        item.checked[kind] = bool(value)
        # Notify controller immediately, before another button can apply a stale preview.
        self.changed()
        return True

    def IsEnabledByRow(self, row, col):
        return (0 <= row < len(self.rows) and not self.locked and
                (col not in KIND_COLUMNS or self.rows[row].available(KIND_COLUMNS[col])))

    def IsEnabled(self, item, col):
        if not item.IsOk(): return False
        return self.IsEnabledByRow(self.GetRow(item), col)

    def HasValue(self, item, col):
        if not item.IsOk(): return False
        # No misleading unchecked box for an asset that does not exist.
        row = self.GetRow(item)
        return (0 <= row < len(self.rows) and
                (col not in KIND_COLUMNS or self.rows[row].available(KIND_COLUMNS[col])))

    def Compare(self, left, right, column, ascending):
        if not left.IsOk() or not right.IsOk(): return 0
        if not (0 <= self.GetRow(left) < len(self.rows) and 0 <= self.GetRow(right) < len(self.rows)): return 0
        a = self.rows[self.GetRow(left)]; b = self.rows[self.GetRow(right)]
        if column == 0: x,y=ws.natural(a.reference),ws.natural(b.reference)
        else: x,y=self.GetValueByRow(self.GetRow(left),column),self.GetValueByRow(self.GetRow(right),column)
        result=(x>y)-(x<y)
        if not result: result=(a.key>b.key)-(a.key<b.key)
        return result if ascending else -result

    def replace(self, rows):
        self.rows=list(rows); self.Reset(len(self.rows))


def attach_component_model(control, changed):
    """Use the wxPython Phoenix ownership contract, not the C++ sample idiom.

    Phoenix AssociateModel transfers ownership AND releases the initial Python
    native reference. An additional model.DecRef() deletes the model while the
    view still points at it. Keep a Python wrapper for selection/filter access;
    never manually release the view's reference here.
    Reference: wxWidgets/Phoenix wxPython-4.2.3, etg/dataview.py, AssociateModel.
    """
    model = ComponentModel(changed)
    control.AssociateModel(model)
    return model


class WorkspaceDialog(wx.Dialog):
    def __init__(self, parent, bridge, *, auto_scan=True):
        super().__init__(parent, title='WayriCAD Embed3D '+__version__+' · Design assets',
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.bridge=bridge; self.result_message=''; self.inventory=None; self.resolver=None
        self.plan=None; self.valid=False; self.busy=False; self.closing=False; self.destroying=False
        self.cancel_event=threading.Event(); self.worker=None; self.source_signature=None
        self.cli=find_cli(); self._updating=False
        self.task=''; self.last_error=''; self.last_traceback=''; self.scan_report={}
        self.scan_started=None
        self._build(); set_window_icons(self,wx)
        self.Bind(wx.EVT_CLOSE,self.on_close); self.Bind(wx.EVT_CHAR_HOOK,self.on_key)
        self.timer=wx.Timer(self); self.Bind(wx.EVT_TIMER,self.on_timer,self.timer)
        self.CentreOnParent(); self.refresh_controls()
        if auto_scan and (self.pcb_text.GetValue() or self.sch_text.GetValue()): wx.CallAfter(self.scan)

    def _label(self,parent,label,bold=False):
        control=wx.StaticText(parent,label=label)
        if bold:
            font=control.GetFont();font.SetWeight(wx.FONTWEIGHT_BOLD);control.SetFont(font)
        return control

    def _button(self,parent,label,handler,tooltip=''):
        b=wx.Button(parent,label=label)
        b.Bind(wx.EVT_BUTTON,handler)
        if tooltip:b.SetToolTip(tooltip)
        return b

    def _build(self):
        # Keep the footer outside the scrolled content: primary actions cannot be
        # clipped by an expanded options panel or a small/high-DPI monitor.
        outer=wx.BoxSizer(wx.VERTICAL)
        self.panel=wx.ScrolledWindow(self,style=wx.VSCROLL)
        self.panel.SetScrollRate(0,self.FromDIP(12)); p=self.panel
        box=wx.BoxSizer(wx.VERTICAL)
        header=wx.BoxSizer(wx.HORIZONTAL)
        words=wx.BoxSizer(wx.VERTICAL)
        title=self._label(p,'Design assets',True)
        font=title.GetFont();font.SetPointSize(font.GetPointSize()+2);title.SetFont(font)
        words.Add(title,0,wx.BOTTOM,self.FromDIP(3))
        title.SetToolTip('Select component assets, choose an operation, preview it, then apply to a new saved copy.')
        header.Add(words,1,wx.ALIGN_CENTER_VERTICAL)
        box.Add(header,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(10))
        boardname=str(self.bridge.board.GetFileName()) if getattr(self.bridge,'board',None) else ''
        self.source_pane=wx.CollapsiblePane(p,label='Sources · '+(Path(boardname).name if boardname else 'choose saved files'),style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        self.source_panel=wx.Panel(self.source_pane.GetPane()); sp=self.source_panel
        grid=wx.FlexGridSizer(2,3,self.FromDIP(5),self.FromDIP(8));grid.AddGrowableCol(1,1)
        self.pcb_text=wx.TextCtrl(sp);self.sch_text=wx.TextCtrl(sp)
        if boardname and Path(boardname).is_file():
            self.pcb_text.ChangeValue(boardname)
            sibling=Path(boardname).with_suffix('.kicad_sch')
            if sibling.is_file():self.sch_text.ChangeValue(str(sibling))
        for label,ctrl,kind in [('Saved PCB',self.pcb_text,'pcb'),('Root schematic',self.sch_text,'schematic')]:
            grid.Add(self._label(sp,label),0,wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl,1,wx.EXPAND)
            b=self._button(sp,'Choose…',lambda e,k=kind:self.browse_source(k))
            grid.Add(b)
        sp.SetSizer(grid)
        source_sizer=wx.BoxSizer(wx.VERTICAL);source_sizer.Add(sp,1,wx.EXPAND|wx.TOP,self.FromDIP(6))
        self.source_pane.GetPane().SetSizer(source_sizer)
        if not boardname:self.source_pane.Expand()
        box.Add(self.source_pane,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(5))
        saved=self._label(p,'Save in KiCad first. Changes create new design copies.')
        saved.Wrap(self.FromDIP(820));box.Add(saved,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(8))
        if getattr(self.bridge,'capability_note',''):
            note=self._label(p,'IPC mode · saved designs · archived footprints')
            note.SetToolTip(self.bridge.capability_note)
            note.Wrap(self.FromDIP(820));box.Add(note,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(8))
        self.selection_panel=wx.Panel(p);ss=wx.BoxSizer(wx.HORIZONTAL)
        ss.Add(self._label(self.selection_panel,'Select:',True),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.FromDIP(10))
        self.globals={}
        for label,kind in [('Symbols','symbols'),('Footprints','footprints'),('3D models','models'),('All types',None)]:
            cb=wx.CheckBox(self.selection_panel,label=label,style=wx.CHK_3STATE)
            cb.SetToolTip('Select or clear this type across ALL components, including rows hidden by the search filter.')
            cb.Bind(wx.EVT_CHECKBOX,lambda e,k=kind:self.global_check(k))
            self.globals[kind]=cb;ss.Add(cb,0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,self.FromDIP(14))
        ss.AddStretchSpacer()
        self.scan_button=self._button(self.selection_panel,'Scan',lambda e:self.scan(),'Read saved design files and refresh all components. No writes.')
        ss.Add(self.scan_button);self.selection_panel.SetSizer(ss)
        box.Add(self.selection_panel,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(7))
        searchrow=wx.BoxSizer(wx.HORIZONTAL)
        self.search=wx.SearchCtrl(p,style=wx.TE_PROCESS_ENTER);self.search.SetDescriptiveText('Find reference, value, library or status…')
        self.search.ShowCancelButton(True);self.search.SetMinSize(self.FromDIP((210,-1)))
        self.summary=self._label(p,'No saved design scanned yet.',True)
        searchrow.Add(self.search,1,wx.RIGHT,self.FromDIP(10));searchrow.Add(self.summary,0,wx.ALIGN_CENTER_VERTICAL)
        box.Add(searchrow,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(5))
        self.table=dv.DataViewCtrl(p,style=dv.DV_ROW_LINES|dv.DV_VERT_RULES|dv.DV_SINGLE)
        self.model=attach_component_model(self.table,self.selection_changed)
        self.table.AppendTextColumn('Component',0,width=self.FromDIP(92),flags=dv.DATAVIEW_COL_RESIZABLE|dv.DATAVIEW_COL_SORTABLE)
        self.table.AppendTextColumn('Value',1,width=self.FromDIP(205),flags=dv.DATAVIEW_COL_RESIZABLE|dv.DATAVIEW_COL_SORTABLE)
        for col,label,width in [(2,'Symbol',82),(3,'Footprint',90),(4,'3D models',94)]:
            self.table.AppendToggleColumn(label,col,width=self.FromDIP(width),mode=dv.DATAVIEW_CELL_ACTIVATABLE,
                                          align=wx.ALIGN_CENTER,flags=dv.DATAVIEW_COL_RESIZABLE)
        self.table.AppendTextColumn('Status',5,width=self.FromDIP(260),flags=dv.DATAVIEW_COL_RESIZABLE|dv.DATAVIEW_COL_SORTABLE)
        self.table.SetMinSize(self.FromDIP((360,155)))
        box.Add(self.table,1,wx.EXPAND)
        self.list_notice=self._label(p,'Choose a saved PCB or schematic, then Scan to list components.')
        self.list_notice.Wrap(self.FromDIP(840))
        box.Add(self.list_notice,0,wx.EXPAND|wx.TOP,self.FromDIP(5))
        self.table.SetToolTip('Blank cells mean the asset is unavailable. Each row checkbox controls that component; a 3D checkbox includes all its model entries.')
        # Destinations are shared by all asset types and all actions.
        self.destination_pane=wx.CollapsiblePane(p,label='Output folders',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        self.destination_panel=wx.Panel(self.destination_pane.GetPane());dp=self.destination_panel
        dest=wx.FlexGridSizer(2,3,self.FromDIP(5),self.FromDIP(8));dest.AddGrowableCol(1,1)
        base=Path(boardname).parent if boardname else Path(self.bridge.project_path())
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
        self.assets_text=wx.TextCtrl(dp,value=str(base/('WayriCAD Embed3D-assets-'+stamp)))
        self.output_text=wx.TextCtrl(dp,value=str(base/('WayriCAD Embed3D-output-'+stamp)))
        for label,ctrl,handler in [('Asset folder',self.assets_text,self.browse_assets),('New design folder',self.output_text,self.browse_output)]:
            dest.Add(self._label(dp,label),0,wx.ALIGN_CENTER_VERTICAL);dest.Add(ctrl,1,wx.EXPAND)
            dest.Add(self._button(dp,'Choose…',handler))
        self.assets_text.SetToolTip('Unbundle writes here. Relink reads this exact extraction folder, including its manifest.')
        self.output_text.SetToolTip('Embed and relink create this NEW folder, including both selected source designs. It must not already exist.')
        dp.SetSizer(dest)
        destination_sizer=wx.BoxSizer(wx.VERTICAL);destination_sizer.Add(dp,1,wx.EXPAND|wx.TOP,self.FromDIP(6))
        self.destination_pane.GetPane().SetSizer(destination_sizer)
        box.Add(self.destination_pane,0,wx.EXPAND|wx.TOP|wx.BOTTOM,self.FromDIP(7))
        self.options_pane=wx.CollapsiblePane(p,label='Options & library tools',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        op=self.options_pane.GetPane();opt=wx.BoxSizer(wx.VERTICAL)
        line=wx.BoxSizer(wx.HORIZONTAL)
        self.follow=wx.CheckBox(op,label='Include child sheets');self.follow.SetValue(True)
        self.local_links=wx.CheckBox(op,label='Relink local libraries on embed');self.local_links.SetValue(True)
        self.copy_external=wx.CheckBox(op,label='Also unbundle external models')
        for c in (self.follow,self.local_links,self.copy_external):line.Add(c,0,wx.RIGHT,self.FromDIP(14))
        opt.Add(line,0,wx.BOTTOM,self.FromDIP(7))
        line=wx.BoxSizer(wx.HORIZONTAL)
        self.prune=wx.CheckBox(op,label='Remove redundant attachments after relink');self.prune.SetValue(False)
        self.native_validate=wx.CheckBox(op,label='Validate with KiCad before publishing');self.native_validate.SetValue(True)
        line.Add(self.prune,0,wx.RIGHT,self.FromDIP(16));line.Add(self.native_validate)
        opt.Add(line,0,wx.BOTTOM,self.FromDIP(7))
        line=wx.BoxSizer(wx.HORIZONTAL)
        line.Add(self._label(op,'Paths'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.FromDIP(6))
        self.path_mode=wx.Choice(op,choices=['Project-relative','Absolute']);self.path_mode.SetSelection(0)
        line.Add(self.path_mode,0,wx.RIGHT,self.FromDIP(14))
        line.Add(self._label(op,'Footprint source'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.FromDIP(6))
        self.fp_source=wx.Choice(op,choices=['As placed (KiCad normalization)','Previously embedded archive']);self.fp_source.SetSelection(0)
        if not getattr(self.bridge,'supports_normalization',True):
            self.fp_source.SetSelection(1);self.fp_source.Disable()
            self.fp_source.SetToolTip('The IPC API does not expose native footprint normalization. Existing embedded archives can still be extracted and relinked.')
        line.Add(self.fp_source,1)
        opt.Add(line,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(7))
        grid=wx.FlexGridSizer(2,2,self.FromDIP(5),self.FromDIP(8));grid.AddGrowableCol(1,1)
        self.stock_root=wx.DirPickerCtrl(op,path='',style=wx.DIRP_USE_TEXTCTRL|wx.DIRP_DIR_MUST_EXIST)
        grid.Add(self._label(op,'Stock models folder'),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(self.stock_root,1,wx.EXPAND)
        nickline=wx.BoxSizer(wx.HORIZONTAL)
        self.fp_nickname=wx.TextCtrl(op,value='WayriCAD_Embed3D_Footprints');self.sym_nickname=wx.TextCtrl(op,value='WayriCAD_Embed3D_Symbols')
        nickline.Add(self.fp_nickname,1,wx.RIGHT,self.FromDIP(8));nickline.Add(self.sym_nickname,1)
        grid.Add(self._label(op,'Footprint / symbol library names'),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(nickline,1,wx.EXPAND)
        opt.Add(grid,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(6))
        self.variables=wx.TextCtrl(op,style=wx.TE_MULTILINE,size=self.FromDIP((-1,46)))
        self.variables.SetHint('Optional path variables, one NAME=folder per line')
        opt.Add(self.variables,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(6))
        advbuttons=wx.BoxSizer(wx.HORIZONTAL)
        self.legacy_button=self._button(op,'Standalone library / live-board tools…',self.open_legacy,
            'Existing footprint-file, supplied-library, repair and live-model workflows. The main embed/unbundle/relink actions stay in this window.')
        if not (getattr(self.bridge,'supports_live_tools',True) or getattr(self.bridge,'supports_file_tools',False)):
            self.legacy_button.Disable()
            self.legacy_button.SetToolTip('These native live-board tools require the KiCad 10 source plugin.')
        self.report_button=self._button(op,'Save preview report…',self.save_report)
        self.diagnostics_button=self._button(op,'Save scan diagnostics…',self.save_diagnostics,
            'Works even when Scan fails. Saves versions, source paths, counts and the error traceback locally; no model payloads or environment dump.')
        advbuttons.Add(self.legacy_button,0,wx.RIGHT,self.FromDIP(8));advbuttons.Add(self.report_button,0,wx.RIGHT,self.FromDIP(8))
        advbuttons.Add(self.diagnostics_button)
        opt.Add(advbuttons);op.SetSizer(opt)
        box.Add(self.options_pane,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(6))
        self.details=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY|wx.TE_DONTWRAP)
        self.details.SetMinSize(self.FromDIP((-1,92)))
        self.details.SetValue('Select a component to inspect its symbol, footprint and model paths.\nChoose an action below to review the operation here before applying it.')
        box.Add(self.details,0,wx.EXPAND)
        p.SetSizer(box);outer.Add(p,1,wx.EXPAND|wx.ALL,self.FromDIP(14))
        # A two-line fixed footer remains visible at small window sizes.
        bottom=wx.Panel(self);foot=wx.BoxSizer(wx.VERTICAL)
        self.status=self._label(bottom,'No changes made. Scan, choose assets, then select an action.')
        self.status.Wrap(self.FromDIP(860));foot.Add(self.status,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(5))
        self.gauge=wx.Gauge(bottom,range=100,size=self.FromDIP((-1,4)));foot.Add(self.gauge,0,wx.EXPAND|wx.BOTTOM,self.FromDIP(7))
        runline=wx.BoxSizer(wx.HORIZONTAL)
        self.operation_keys=list(ACTION_LABELS)
        self.operation=wx.Choice(bottom,choices=list(ACTION_LABELS.values()));self.operation.SetSelection(0)
        self.operation.SetToolTip('Embed all includes every available asset, regardless of the row checkboxes.')
        self.operation.Bind(wx.EVT_CHOICE,self.invalidate_plan)
        runline.Add(self.operation,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.FromDIP(8))
        self.preview_button=self._button(bottom,'Preview',lambda event:self.preview(self.operation_keys[self.operation.GetSelection()]))
        runline.Add(self.preview_button,0,wx.RIGHT,self.FromDIP(8))
        self.footer_hint=self._label(bottom,'Filtered-out checks stay selected.')
        runline.Add(self.footer_hint,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.FromDIP(8))
        self.close_button=self._button(bottom,'Close',self.on_close)
        self.apply_button=self._button(bottom,'Apply preview',self.apply_preview)
        self.apply_button.SetDefault();runline.Add(self.close_button,0,wx.RIGHT,self.FromDIP(8));runline.Add(self.apply_button)
        foot.Add(runline,0,wx.EXPAND);bottom.SetSizer(foot)
        outer.Add(bottom,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,self.FromDIP(14));self.SetSizer(outer)
        screen=wx.GetClientDisplayRect().GetSize()
        width=min(self.FromDIP(1030),max(720,screen.width-40));height=min(self.FromDIP(850),max(500,screen.height-55))
        self.SetSize((width,height));self.SetMinSize((min(self.FromDIP(780),width),min(self.FromDIP(560),height)))
        self.search.Bind(wx.EVT_TEXT,lambda e:self.filter_rows())
        self.search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN,lambda e:self.search.SetValue(''))
        self.table.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED,self.show_component)
        for ctrl in (self.pcb_text,self.sch_text,self.variables):ctrl.Bind(wx.EVT_TEXT,self.sources_changed)
        self.stock_root.Bind(wx.EVT_DIRPICKER_CHANGED,self.sources_changed)
        self.follow.Bind(wx.EVT_CHECKBOX,self.sources_changed)
        for ctrl in (self.assets_text,self.output_text,self.fp_nickname,self.sym_nickname):ctrl.Bind(wx.EVT_TEXT,self.invalidate_plan)
        for ctrl in (self.local_links,self.copy_external,self.prune,self.native_validate):ctrl.Bind(wx.EVT_CHECKBOX,self.invalidate_plan)
        for ctrl in (self.fp_source,self.path_mode):ctrl.Bind(wx.EVT_CHOICE,self.invalidate_plan)
        self.options_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,self.options_changed)
        for pane in (self.source_pane,self.destination_pane):
            pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(self.panel.Layout(),self.panel.FitInside(),self.Layout()))

    def options_changed(self,event):
        self.details.Show(not self.options_pane.IsExpanded())
        self.panel.Layout();self.panel.FitInside();self.Layout()

    def _fingerprint(self):
        return (self.pcb_text.GetValue().strip(),self.sch_text.GetValue().strip(),self.follow.GetValue(),
                self.stock_root.GetPath(),self.variables.GetValue())

    def sources_changed(self,event=None):
        self.valid=False;self.invalidate_plan();self.status.SetLabel('Sources or path settings changed. Scan again before choosing an action.')

    def invalidate_plan(self,event=None):
        had_plan = self.plan is not None
        self.plan=None;self.refresh_controls()
        if had_plan:
            self.status.SetLabel('Selection or options changed. Choose an action to refresh the preview.')

    def selection_changed(self):
        self.invalidate_plan();self.refresh_globals();self.refresh_summary()

    def refresh_controls(self):
        if not hasattr(self,'apply_button'):return
        self.model.locked=self.busy or not self.valid
        self.apply_button.Enable(self.plan is not None and not self.busy)
        has=self.inventory is not None and self.valid and bool(self.inventory.rows)
        checked=has and self.inventory.selection().any()
        key=self.operation_keys[self.operation.GetSelection()]
        self.preview_button.Enable(bool(has if key=='embed-all' else checked) and not self.busy)
        self.operation.Enable(not self.busy)
        self.scan_button.Enable(not self.busy)
        for ctrl in (self.source_pane,self.destination_pane,self.options_pane,self.search,self.selection_panel):ctrl.Enable(not self.busy)
        self.close_button.SetLabel('Stop' if self.busy else 'Close')
        self.report_button.Enable(self.plan is not None and not self.busy)
        self.diagnostics_button.Enable(not self.busy)
        self.table.Enable(not self.busy and self.valid)
        self.refresh_globals()

    def refresh_globals(self):
        if not self.inventory or not self.valid:
            for ctrl in self.globals.values():
                ctrl.Set3StateValue(wx.CHK_UNCHECKED);ctrl.Enable(False)
            return
        values={'none':wx.CHK_UNCHECKED,'mixed':wx.CHK_UNDETERMINED,'all':wx.CHK_CHECKED}
        self._updating=True
        try:
            for kind,ctrl in self.globals.items():
                ctrl.Set3StateValue(values[self.inventory.state(kind)])
                kinds=ws.TYPES if kind is None else (kind,)
                ctrl.Enable(not self.busy and any(r.available(k) for r in self.inventory.rows for k in kinds))
        finally:self._updating=False

    def global_check(self,kind):
        if self._updating or self.busy or not self.valid or not self.inventory:return
        self.inventory.select_all(kind,self.globals[kind].Get3StateValue()!=wx.CHK_UNCHECKED)
        self.model.Reset(len(self.model.rows));self.selection_changed()

    def refresh_summary(self):
        if not self.inventory:return
        counts=self.inventory.selection().counts()
        n=len(self.inventory.rows);shown=len(self.model.rows)
        self.summary.SetLabel(f'{shown}/{n} rows  ·  {counts["symbols"]} symbols  ·  {counts["footprints"]} footprints  ·  {counts["models"]} model sets')
        self.panel.Layout()

    def filter_rows(self):
        if not self.inventory:return
        query=self.search.GetValue().casefold().strip()
        rows=self.inventory.rows
        if query:rows=[r for r in rows if query in (' '.join((r.reference,r.value,r.footprint_id,r.status,*r.symbol_ids))).casefold()]
        self.model.replace(rows)
        if not self.inventory.rows:
            notice=('No components were found in the selected SAVED files. Save the populated PCB/schematic in KiCad, '
                    'then choose that file and Scan again. Asset checkboxes select operations; they do not filter the list.')
        elif not rows:
            notice=f'No search matches. {len(self.inventory.rows)} components were scanned; clear the search box to show them.'
        else:
            notice=''
        self.list_notice.SetLabel(notice);self.list_notice.Show(bool(notice))
        self.list_notice.Wrap(self.FromDIP(840))
        self.refresh_summary()
        self.panel.FitInside()

    def show_component(self,event):
        item=event.GetItem()
        if item.IsOk() and self.plan is None:
            row=self.model.GetRow(item)
            if 0 <= row < len(self.model.rows):self.details.SetValue(self.model.rows[row].detail())

    def browse_source(self,kind):
        wildcard='KiCad PCB (*.kicad_pcb)|*.kicad_pcb' if kind=='pcb' else 'KiCad schematic (*.kicad_sch)|*.kicad_sch'
        with wx.FileDialog(self,'Choose saved '+kind,wildcard=wildcard,style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal()!=wx.ID_OK:return
            path=Path(dlg.GetPath());control=self.pcb_text if kind=='pcb' else self.sch_text;control.SetValue(str(path))
            other=self.sch_text if kind=='pcb' else self.pcb_text
            sibling=path.with_suffix('.kicad_sch' if kind=='pcb' else '.kicad_pcb')
            if not other.GetValue() and sibling.is_file():other.SetValue(str(sibling))
            stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
            self.assets_text.SetValue(str(path.parent/('WayriCAD Embed3D-assets-'+stamp)))
            self.output_text.SetValue(str(path.parent/('WayriCAD Embed3D-output-'+stamp)))
        self.scan()

    def browse_assets(self,event=None):
        with wx.DirDialog(self,'Choose asset folder (existing extraction for Relink)',defaultPath=str(Path(self.assets_text.GetValue()).parent)) as dlg:
            if dlg.ShowModal()==wx.ID_OK:self.assets_text.SetValue(dlg.GetPath())

    def browse_output(self,event=None):
        with wx.DirDialog(self,'Choose parent for a NEW design folder',defaultPath=str(Path(self.output_text.GetValue()).parent)) as dlg:
            if dlg.ShowModal()==wx.ID_OK:
                self.output_text.SetValue(str(Path(dlg.GetPath())/('WayriCAD Embed3D-output-'+datetime.now().strftime('%Y%m%d-%H%M%S'))))

    def _resolver(self,pcb,sch):
        source=Path(pcb or sch);variables=saved_project_variables(source)
        for line in self.variables.GetValue().splitlines():
            if not line.strip():continue
            if '=' not in line:raise ValueError('Path variable must use NAME=folder: '+line)
            key,value=line.split('=',1)
            if not key.strip() or not value.strip():raise ValueError('Empty variable name or folder.')
            variables[key.strip()]=value.strip()
        if self.stock_root.GetPath():variables['KICAD10_3DMODEL_DIR']=self.stock_root.GetPath()
        resolver=Resolver(source.parent,variables);refs=[]
        if pcb:
            text=read_text(pcb)
            refs=[m.arg().value(text) for fp in parse(text).nodes(text,'footprint') for m in fp.nodes(text,'model')]
        # This is the only native path discovery step; never call pcbnew from a worker.
        if hasattr(self.bridge,'prepare_resolver'):self.bridge.prepare_resolver(resolver,refs)
        return resolver

    def scan(self):
        if self.busy:return
        self.task='scan';self.last_error='';self.last_traceback=''
        self.scan_started=time.monotonic()
        self.scan_report={'outcome':'reading', 'plugin_version':__version__,
                          'pcb':self.pcb_text.GetValue().strip(),
                          'schematic':self.sch_text.GetValue().strip()}
        try:
            pcb=self.pcb_text.GetValue().strip();sch=self.sch_text.GetValue().strip()
            if not pcb and not sch:raise ValueError('Choose a saved PCB, root schematic, or both.')
            # File/model resolution is independent of the global selection checkboxes.
            resolver=self._resolver(pcb,sch);signature=self._fingerprint();follow=self.follow.GetValue()
            previous={r.key:dict(r.checked) for r in self.inventory.rows} if self.inventory and self.source_signature==signature else {}
            get_logger().info('Scan start: plugin=%s PCB=%s schematic=%s',__version__,pcb or '(none)',sch or '(none)')
            def work():return ws.scan_design(pcb or None,sch or None,follow=follow,resolver=resolver,cancelled=self.cancel_event.is_set)
            def done(inventory):
                self.inventory=inventory;self.resolver=resolver;self.source_signature=signature
                for row in inventory.rows:
                    if row.key in previous:
                        for kind in ws.TYPES:row.checked[kind]=previous[row.key][kind] and row.available(kind)
                # Only enable actions after the real view/model refresh succeeds.
                self.filter_rows()
                self.valid=True;self.refresh_controls()
                count=len(inventory.rows)
                self.scan_report.update(outcome='ok' if count else 'empty', components=count,
                    visible_rows=len(self.model.rows), available=inventory.selection(True).counts(),
                    elapsed_seconds=round(time.monotonic()-self.scan_started,3),warnings=list(inventory.warnings))
                get_logger().info('Scan complete: %s',json.dumps(self.scan_report,ensure_ascii=False))
                if not count:
                    self.details.SetValue(self.list_notice.GetLabel()+'\n\nPCB: '+(pcb or '(not selected)')+
                                          '\nSchematic: '+(sch or '(not selected)'))
                    self.status.SetLabel('Scan finished: 0 components in the saved files. Check the source paths and save the design in KiCad.')
                else:
                    self.details.SetValue(f'Scan complete: {count} components. Select assets, then choose Embed, Unbundle or Relink.\n'
                        'The global checkboxes select assets; they do not hide components.\n\n'+'\n'.join(inventory.warnings))
                    message=f'Scan complete: {count} components. Original designs are unchanged.'
                    if not self.model.rows:message+=' Clear the search box to show the scanned rows.'
                    self.status.SetLabel(message)
            self.valid=False;self._start(work,done,'Scanning saved design assets…',task='scan')
        except Exception as exc:self.error(exc)

    def _options(self):
        if not self.assets_text.GetValue().strip():raise ValueError('Choose an asset folder.')
        if not self.output_text.GetValue().strip():raise ValueError('Choose a new design folder.')
        return ws.Options(Path(self.assets_text.GetValue()),Path(self.output_text.GetValue()),
            path_mode='relative' if self.path_mode.GetSelection()==0 else 'absolute',follow=self.follow.GetValue(),
            include_external=self.copy_external.GetValue(),local_links=self.local_links.GetValue(),prune=self.prune.GetValue(),
            footprint_nickname=self.fp_nickname.GetValue().strip(),symbol_nickname=self.sym_nickname.GetValue().strip())

    def preview(self,action):
        if self.busy or not self.valid or not self.inventory:return
        self.task='operation'
        try:
            self.inventory.assert_fresh();selection=self.inventory.selection(action=='embed-all')
            options=self._options();operation='embed' if action=='embed-all' else action
            normalized=normal_hash=None
            # Relink uses verified extracted definitions; no normalization needed.
            if selection.footprints and operation in ('embed','unbundle','unbundle-relink'):
                self.status.SetLabel('Preparing checked footprint definitions with KiCad…');self.status.Update()
                with wx.BusyCursor():
                    if self.fp_source.GetSelection()==1:
                        normalized,normal_hash=ws.archived_normalized(self.inventory.pcb,selection.footprints)
                    else:
                        normalized,normal_hash=self.bridge.extract_normalized_footprints(self.inventory.pcb,selected_uuids=selection.footprints)
            inventory=self.inventory;resolver=self.resolver
            def work():return ws.prepare_operation(inventory,selection,operation,options,normalized=normalized,
                normalized_hash=normal_hash,resolver=resolver,cancelled=self.cancel_event.is_set)
            def done(plan):
                self.plan=plan;summary=plan.summary();counts=summary['counts']
                lines=[ACTION_LABELS[action]+' — preview',
                    f'{counts["symbols"]} symbol instances · {counts["footprints"]} footprints · {counts["models"]} component model sets',
                    'Source designs remain unchanged.']
                if action=='embed-all':lines.append('Embed all overrides the current checkbox choices and includes every available asset.')
                if plan.extractions:lines.append('Asset folder: '+str(options.assets))
                if plan.change:lines.append('New design: '+str(options.output))
                if summary['files_to_extract']:lines.append('Files to extract: '+str(summary['files_to_extract']))
                if summary['design_files']:lines+=['Design output files:']+['  '+n for n in summary['design_files'][:50]]
                lines+=['','Notes:']+['• '+n for n in summary['warnings']]
                self.details.SetValue('\n'.join(lines));self.options_pane.Collapse();self.details.Show()
                self.panel.Layout();self.panel.FitInside();self.refresh_controls()
                wx.CallAfter(self._show_details)
                self.status.SetLabel('Preview ready: '+ACTION_LABELS[action]+'. Review below, then click Apply preview.')
            self._start(work,done,'Preparing '+ACTION_LABELS[action].lower()+' preview…')
        except Exception as exc:self.error(exc)

    def _show_details(self):
        if not self.destroying:
            self.panel.Scroll(0,max(0,self.panel.GetVirtualSize().height//max(1,self.FromDIP(12))))

    def _start(self,work,done,message,*,task='operation'):
        self.task=task
        self.plan=None;self.busy=True;self.cancel_event.clear();self.refresh_controls();self.status.SetLabel(message)
        self.timer.Start(100)
        def execute():
            try:result,error=work(),None
            except Exception as exc:result,error=None,exc
            wx.CallAfter(self._finished,result,error,done)
        self.worker=threading.Thread(target=execute,name='WayriCAD Embed3D-workspace',daemon=True)
        try:self.worker.start()
        except Exception:
            self.timer.Stop();self.busy=False;self.refresh_controls()
            raise

    def _finished(self,result,error,done):
        if self.destroying:return
        self.timer.Stop();self.gauge.SetValue(0);self.busy=False
        if self.closing:
            self.destroying=True
            if self.IsModal():self.EndModal(wx.ID_CANCEL)
            else:self.Hide()
            return
        if error:self.error(error)
        else:
            try:done(result)
            except Exception as exc:self.error(exc)
        self.refresh_controls()

    def apply_preview(self,event=None):
        if self.busy or self.plan is None:return
        plan=self.plan
        self.task='operation'
        try:
            if self.native_validate.GetValue() and plan.change and self.inventory.schematic and not self.cli:
                raise ValueError('KiCad CLI was not found for schematic validation. Add the KiCad bin folder to PATH, or explicitly turn off native validation in Options. No output was published.')
            self.busy=True;self.refresh_controls();self.status.SetLabel('Writing and validating the previewed output. Original designs are unchanged.');self.status.Update()
            # Native parser/footprint APIs must remain on the GUI thread.
            # Plans already contain compressed payloads; only staged IO and native
            # validation happen here. No wx.Yield reentrancy during publication.
            def validate(staging):
                if not self.native_validate.GetValue():return
                if self.inventory.pcb:
                    self.bridge.validate_portable_board(staging/self.inventory.pcb.name)
                    # Verify native library footprints too, not only board model refs.
                    for file in staging.rglob('*.kicad_mod'):
                        if not getattr(self.bridge,'supports_native_roundtrip',True):
                            self.bridge.validate_footprint_file(file)
                            continue
                        text=read_text(file);fp=self.bridge.deserialize(text);actual=self.bridge.serialize(fp)
                        if self.bridge.model_structure(text)!=self.bridge.model_structure(actual):
                            raise ValueError('Native parser changed a footprint model setting: '+file.name)
                        self.bridge.check_payloads(text,actual)
                if self.inventory.schematic:validate_schematic(staging/self.inventory.schematic.name,self.cli)
            with wx.BusyCursor():result=plan.apply(validate=validate)
            message='Completed '+('Embed' if plan.operation=='embed' else ACTION_LABELS[plan.operation])+'.'
            if plan.extractions:message+='\nAssets: '+str(plan.options.assets)
            if plan.change:message+='\nOpen the NEW design from: '+str(plan.options.output)
            message+='\nOriginal saved files and open editor buffers were not modified.'
            self.details.SetValue(message+'\n\n'+json.dumps(result,indent=2,ensure_ascii=False))
            self.status.SetLabel('Complete. Original designs are unchanged. The source fields still point to the originals.')
            self.plan=None
        except Exception as exc:self.error(exc)
        finally:self.busy=False;self.refresh_controls();self.refresh_globals()

    def error(self,exc):
        self.plan=None;self.last_error=str(exc)
        self.last_traceback=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__))
        if self.task=='scan':
            self.valid=False
            self.scan_report.update(outcome='failed',error=str(exc))
            if self.scan_started is not None:
                self.scan_report['elapsed_seconds']=round(time.monotonic()-self.scan_started,3)
            self.summary.SetLabel('Scan failed — no new results')
            self.list_notice.SetLabel('Scan failed. See the error below, or use Options → Save scan diagnostics….')
            self.list_notice.Show()
        get_logger().error('Workspace: %s',exc,exc_info=(type(exc),exc,exc.__traceback__))
        self.details.SetValue(str(exc)+'\n\nNo original design has been overwritten.\nIf a combined operation failed after extraction, its verified asset files may remain.\nLog: '+get_logger().log_path)
        self.details.Show();self.options_pane.Collapse();self.panel.Layout();self.panel.FitInside()
        prefix='Scan failed' if self.task=='scan' else 'Action stopped'
        self.status.SetLabel(prefix+': '+str(exc).replace('\n',' ')[:180])
        self.status.Wrap(self.FromDIP(860));self.refresh_controls();wx.CallAfter(self._show_details)

    def open_legacy(self,event=None):
        if self.busy:return
        if not (getattr(self.bridge,'supports_live_tools',True) or getattr(self.bridge,'supports_file_tools',False)):
            self.error(ValueError('Live-board tools require the KiCad 10 source plugin. Use the saved-design workflow in this window.'))
            return
        from .ui import EmbedDialog
        self.invalidate_plan()
        dialog=EmbedDialog(self,self.bridge)
        try:dialog.ShowModal()
        finally:dialog.Destroy()
        self.valid=False;self.status.SetLabel('Library tools closed. Save any live PCB changes, then Scan again.');self.refresh_controls()

    def save_report(self,event=None):
        if self.plan is None:return
        with wx.FileDialog(self,'Save preview report',defaultFile='WayriCAD Embed3D-preview.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal()==wx.ID_OK:
                try:Path(dlg.GetPath()).write_text(json.dumps(self.plan.summary(),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                except Exception as exc:self.error(exc)

    def diagnostics(self):
        try:
            wx_version=wx.version()
        except Exception:
            wx_version='(unavailable)'
        return {'plugin_version':__version__, 'module':str(Path(__file__).absolute()),
                'python_version':sys.version, 'platform':platform.platform(),
                'wx_version':wx_version, 'kicad_version':str(getattr(self.bridge,'version','unknown')),
                'pcb':self.pcb_text.GetValue().strip(),'schematic':self.sch_text.GetValue().strip(),
                'scan':dict(self.scan_report),'inventory_components':len(self.inventory.rows) if self.inventory else 0,
                'visible_rows':len(self.model.rows),'filter':self.search.GetValue(),
                'valid':bool(self.valid),'busy':bool(self.busy),
                'last_error':self.last_error,'traceback':self.last_traceback,
                'log_path':get_logger().log_path,
                'privacy':'Contains local paths and version/count/error information. No model payloads, full designs or environment dump. Review before sharing.'}

    def save_diagnostics(self,event=None):
        with wx.FileDialog(self,'Save scan diagnostics',defaultFile='WayriCAD Embed3D-scan-diagnostics.json',
                           wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dlg:
            if dlg.ShowModal()==wx.ID_OK:
                try:
                    Path(dlg.GetPath()).write_text(json.dumps(self.diagnostics(),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                    self.status.SetLabel('Diagnostics saved locally. Review paths before sharing. Original designs are unchanged.')
                except Exception as exc:self.error(exc)

    def on_timer(self,event):
        if self.busy:self.gauge.Pulse()

    def on_key(self,event):
        if event.GetKeyCode()==wx.WXK_ESCAPE:self.on_close()
        else:event.Skip()

    def on_close(self,event=None):
        if self.busy:
            self.cancel_event.set();self.closing=True;self.status.SetLabel('Stopping safely…')
            if event and hasattr(event,'Veto'):event.Veto()
            return
        self.timer.Stop();self.destroying=True
        if self.IsModal():self.EndModal(wx.ID_CANCEL)
        else:self.Hide()
