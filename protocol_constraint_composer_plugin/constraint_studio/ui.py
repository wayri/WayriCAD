"""Native wxPython GUI. Runs in KiCad 10's Python; no webview/server or implicit network connection.
Host acceptance is required: pure-core tests cannot certify wx/pcbnew execution.
"""
import copy, json, pathlib, threading
import wx
import wx.grid as gridlib
import wx.html
import wx.aui as aui
import wx.lib.scrolledpanel as scrolled
from .catalog import LAYERS
from .model import RuleDocument
from .profiles import bga_rules, matrix_rules, replace_generated
from .workspace import Workspace, atomic_write
from .board import stage_courtyard_area, refresh_copied_area
from .validation import native_drc
from .help_system import tooltip_for, topic_for_page
from .help_ui import HelpPanel, bind_dialog_help

TITLE='Constraint Studio 0.3.1 · KiCad 10'
BG='#F4F6FA'; PANEL='#FFFFFF'; INK='#17253C'; MUTED='#53647A'; ACCENT='#2155AD'

def error(parent,exc):
    wx.MessageBox(str(exc),'Constraint Studio',wx.OK|wx.ICON_ERROR,parent)

def info(parent,text):wx.MessageBox(text,'Constraint Studio',wx.OK|wx.ICON_INFORMATION,parent)

def label(parent,text,bold=False,size=None):
    w=wx.StaticText(parent,label=text)
    f=w.GetFont()
    if bold:f.SetWeight(wx.FONTWEIGHT_BOLD)
    if size:f.SetPointSize(size)
    w.SetFont(f);return w

def button(parent,text,handler):
    b=wx.Button(parent,label=text);b.Bind(wx.EVT_BUTTON,handler)
    tip=tooltip_for(text)
    if tip:b.SetToolTip(tip)
    return b

def row(parent,sizer,title,control):
    tip=tooltip_for(title)
    if tip:control.SetToolTip(tip)
    sizer.Add(label(parent,title),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
    sizer.Add(control,1,wx.EXPAND)
    return control

def mono(control):
    control.SetFont(wx.Font(10,wx.FONTFAMILY_TELETYPE,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_NORMAL))

def choices(parent,items,value='',editable=True):
    w=wx.ComboBox(parent,choices=list(items),style=wx.CB_DROPDOWN if editable else wx.CB_READONLY)
    if value:w.SetValue(value)
    elif items:w.SetSelection(0)
    return w

def text_value(v):return 'null' if v is None else str(v).lower() if isinstance(v,bool) else str(v)








class CourtyardCanvas(wx.Panel):
    """Exact staged polygon preview, explicitly not a DRC/match simulator."""
    def __init__(self,parent):
        super().__init__(parent,size=(-1,170));self.polygon=[];self.caption='Saved-geometry preview';self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint)
    def update(self,poly,caption):self.polygon=poly;self.caption=caption;self.Refresh()
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self) if hasattr(wx,'AutoBufferedPaintDC') else wx.BufferedPaintDC(self)
        dc.SetBackground(wx.Brush('#F0F4FA'));dc.Clear();dc.SetTextForeground(INK);dc.DrawText(self.caption,12,10)
        if not self.polygon:return
        loops=self.polygon if isinstance(self.polygon[0],list) else [self.polygon]
        allpts=[p for loop in loops for p in loop]
        if not allpts:return
        w,h=self.GetClientSize();xs=[p[0] for p in allpts];ys=[p[1] for p in allpts]
        dx=max(xs)-min(xs);dy=max(ys)-min(ys)
        scale=min(max(1,w-80)/max(dx,.1),max(1,h-65)/max(dy,.1))
        dc.SetPen(wx.Pen(ACCENT,2));dc.SetBrush(wx.TRANSPARENT_BRUSH)
        for loop in loops:
            points=[wx.Point(round((x-min(xs))*scale+(w-dx*scale)/2),round((y-min(ys))*scale+40)) for x,y in loop]
            if len(points)>2:dc.DrawPolygon(points)


class BGADialog(wx.Dialog):
    def __init__(self,parent,workspace,selected_ref=''):
        super().__init__(parent,title='Component escape / courtyard rules',size=(900,790),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.w=workspace;self.result=None
        bind_dialog_help(self,"bga")
        outer=wx.BoxSizer(wx.VERTICAL);self.SetSizer(outer)
        body=scrolled.ScrolledPanel(self);s=wx.BoxSizer(wx.VERTICAL);body.SetSizer(s);outer.Add(body,1,wx.EXPAND)
        s.Add(label(body,'Local manufacturing exception — without relaxing the whole board',True,13),0,wx.ALL,16)
        g=wx.FlexGridSizer(cols=2,vgap=10,hgap=12);g.AddGrowableCol(1,1);s.Add(g,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        refs=[f.reference for f in workspace.context.footprints]
        self.ref=row(body,g,'Component',choices(body,refs,selected_ref or (refs[0] if refs else 'U1')))
        self.mode=row(body,g,'Boundary policy',choices(body,['Strict: existing named rule area','Strict: copy saved front courtyard','Dynamic courtyard intersection (NOT strict)','Component children only (NOT an area)','Strict: attach courtyard area to footprint'],editable=False))
        from .linked_areas import all_areas
        self.mode.SetSelection(4)
        self.area=row(body,g,'Rule area / new area name',choices(body,[a['name'] for a in all_areas(workspace.context) if a['rule_area']]))
        self.area.SetValue('')
        self.layer=row(body,g,'Copper layer',choices(body,[l for l in workspace.context.layers if l.endswith('.Cu')] or ['F.Cu'],workspace.context.footprint(self.ref.GetValue()).layer if refs else 'F.Cu',False))
        self.clearance=row(body,g,'Local copper clearance',wx.TextCtrl(body))
        self.width=row(body,g,'Local track width (optional)',wx.TextCtrl(body))
        self.via=row(body,g,'Local via diameter (optional)',wx.TextCtrl(body))
        self.hole=row(body,g,'Local drill size (optional)',wx.TextCtrl(body))
        self.explain=label(body,'');s.Add(self.explain,0,wx.EXPAND|wx.ALL,16)
        self.canvas=CourtyardCanvas(body);s.Add(self.canvas,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.auto_sync=wx.CheckBox(body,label='Regenerate this managed scope on review/export after saved courtyard edits (refuse independent rule/area edits).');s.Add(self.auto_sync,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.ack=wx.CheckBox(body,label='I reviewed the scope, board-wide manufacturing floors, and saved-geometry limitations.');s.Add(self.ack,0,wx.ALL,16)
        outer.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL|wx.HELP),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.mode.Bind(wx.EVT_COMBOBOX,self.refresh);self.ref.Bind(wx.EVT_COMBOBOX,self.refresh);self.Bind(wx.EVT_BUTTON,self.ok,id=wx.ID_OK)
        self.refresh(None);body.SetupScrolling(scroll_x=False);self.SetMinSize((720,480))
        area=wx.GetClientDisplayRect();self.SetSize((min(900,area.width-24),min(790,area.height-48)));self.CenterOnParent()
    def refresh(self,event):
        i=self.mode.GetSelection();self.area.Enable(i<2 or i==4)
        if event and event.GetEventObject() is self.ref and i==4:
            self.layer.SetValue(self.w.context.footprint(self.ref.GetValue()).layer)
        if i==1 and not self.area.GetValue():self.area.SetValue('CS_'+self.ref.GetValue()+'_COURTYARD')
        if i==4:
            msg='STRICT whole-item containment in a native footprint-owned area. The area uses the component local coordinates rather than a frozen board snapshot. Supports lines, arcs, circles and disjoint/nested contours on either side. Hole intersections are excluded. Exact arc serialization requires native acceptance. Generated rules have no fixed layer clause so the area layer controls scope. Native move/flip validation is required.'
        elif i<2:
            msg='Both A AND B must be entirely enclosed for clearance; routing dimensions use A only. Boundary-crossing segments keep stricter outside rules. No automatic trace splitting.'
            if i==1:msg+=' A simple FRONT courtyard is copied to a board-level area in the REVIEW COPY. It does NOT follow later footprint movement. Arcs, back-side parts, holes and multiple contours are rejected.'
        elif i==2:msg='WARNING: this tracks the native courtyard dynamically, but any intersecting object is matched in its entirety. A track crossing the courtyard may be relaxed outside it. This is NOT strict containment.'
        else:msg='Only children of this footprint are matched. Nearby escape tracks are not footprint children. This is not a spatial escape-area scope.'
        if self.w.floors:msg+=' Board floor: clearance '+str(self.w.floors.get('min_clearance','unknown'))+' mm; track '+str(self.w.floors.get('min_track_width','unknown'))+' mm.'
        self.explain.SetLabel(msg);self.explain.Wrap(max(400,self.GetClientSize().width-64))
        try:
            from .linked_areas import world_polygon
            from .courtyards import courtyard_contours,contour_points
            loops,_=courtyard_contours(self.w.context,self.ref.GetValue())
            poly=[world_polygon(self.w.context.footprint(self.ref.GetValue()),contour_points(loop)) for loop in loops];caption='Saved courtyard contours (curves sampled for preview only) — not DRC'
        except Exception as e:poly=[];caption=str(e)
        self.canvas.update(poly,caption);self.Layout()
    def ok(self,event):
        try:
            if not self.ack.GetValue():raise ValueError('Review and acknowledge the scope limitations first')
            ref=self.ref.GetValue();self.w.context.footprint(ref)
            i=self.mode.GetSelection();area=self.area.GetValue().strip();board_text=None;guard=None
            if i==0:
                from .linked_areas import all_areas
                found=[x for x in all_areas(self.w.context) if x['name']==area and x['rule_area']]
                if len(found)!=1:raise ValueError('Choose a unique native named rule area. This strict workflow does not use copper zones.')
            elif i==1:board_text,guard=stage_courtyard_area(self.w.context,ref,area,(self.layer.GetValue(),))
            elif i==4:
                from .courtyards import stage_regions
                board_text,guard=stage_regions(self.w.context,ref,area,(self.layer.GetValue(),),self.auto_sync.GetValue());area=guard['name']
            rules=bga_rules(ref,self.clearance.GetValue(),self.width.GetValue(),self.via.GetValue(),self.hole.GetValue(),
                mode='area' if i<2 or i==4 else 'intersection' if i==2 else 'pads',area=area,layer='' if i==4 else self.layer.GetValue())
            if i==4:
                from .courtyards import scope_for_regions,pair_scope
                aa,bb=scope_for_regions(guard['regions'],'A'),scope_for_regions(guard['regions'],'B')
                for r in rules:r.condition=pair_scope(guard['regions']) if any(c.kind=='clearance' for c in r.constraints) else aa
            from .model import lint
            errors=[x.message for x in lint(RuleDocument(rules=rules),self.w.floors) if x.severity=='error']
            if errors:raise ValueError('\n'.join(errors))
            if guard:
                guard['rule_names']=[r.name for r in rules]
                if i==4:guard['rule_states']=[r.state() for r in rules]
            self.result=(rules,board_text,guard);self.EndModal(wx.ID_OK)
        except Exception as e:error(self,e)


class StudioFrame(wx.Frame):
    def __init__(self,parent=None,board_path='',selected_ref='',native_select=None,native_probe=None,native_selection=None):
        super().__init__(parent,title=TITLE+' — development build',size=(1560,960),style=wx.DEFAULT_FRAME_STYLE)
        self.SetMinSize((900,580));self.SetBackgroundColour(BG)
        self.w=Workspace();self.w.saved_state=self.w.state();self.selected_ref=selected_ref;self.native_select=native_select
        self.native_probe=native_probe;self.native_selection=native_selection
        self.index=None;self.editing=None;self.rule_rows=[];self.setting_rows=[];self.loading=False;self.last_export=None
        self.undo_stack=[];self.redo_stack=[];self.worker=None
        self.CreateStatusBar(2);self.SetStatusWidths([-1,280])
        self.SetStatusText('Offline native GUI • staged edits • no live project writes')
        self.SetStatusText('Local lint ≠ native DRC',1)
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        header=wx.Panel(self);header.SetBackgroundColour(INK);hs=wx.WrapSizer(wx.HORIZONTAL,flags=wx.REMOVE_LEADING_SPACES);header.SetSizer(hs)
        title=label(header,'CONSTRAINT STUDIO',True,18);title.SetForegroundColour('white');hs.Add(title,0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,18)
        self.project_label=label(header,'Open a saved board');self.project_label.SetForegroundColour('#D5DFF0');hs.Add(self.project_label,0,wx.LEFT|wx.ALIGN_CENTER_VERTICAL,12)
        for text,fn in [('Open board…',self.open_board),('BGA / IC wizard…',self.bga),('Review & export…',self.show_review)]:hs.Add(button(header,text,fn),0,wx.ALL|wx.ALIGN_CENTER_VERTICAL,8)
        root.Add(header,0,wx.EXPAND)
        note=label(self,'DEVELOPMENT BUILD  ·  Save your board and Board Setup first. Changes stay in this workspace until you export and review them.')
        root.Add(note,0,wx.EXPAND|wx.ALL,12)
        self.book=aui.AuiNotebook(self,style=aui.AUI_NB_TOP|aui.AUI_NB_SCROLL_BUTTONS|aui.AUI_NB_TAB_MOVE);root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.rule_page=wx.Panel(self.book);self.matrix_page=wx.Panel(self.book);self.review_page=wx.Panel(self.book);self.help_page=wx.Panel(self.book)
        for p,t in [(self.rule_page,'Rule inspection'),(self.matrix_page,'Matrices'),(self.review_page,'Review & export'),(self.help_page,'Help')]:self.book.AddPage(p,t)
        self.build_rules();self.build_matrix();self.build_review();self.build_help();self.build_menu()
        from .workbench_ui import WorkspacePanel, ProfilesPanel, ReportsPanel
        self.workbench=WorkspacePanel(self.book,self);self.book.InsertPage(0,self.workbench,'Workspace',True)
        self.profile_panel=ProfilesPanel(self.book,self);self.book.InsertPage(3,self.profile_panel,'Sets & timing')
        self.reports_panel=ReportsPanel(self.book,self);self.book.InsertPage(4,self.reports_panel,'DRC evidence')
        from .advanced_ui import AdvancedPanel
        self.advanced_panel=AdvancedPanel(self.book,self);self.book.AddPage(self.advanced_panel,'Engineering & team')
        self.book.Bind(aui.EVT_AUINOTEBOOK_PAGE_CHANGED,self.page_changed);self.Bind(wx.EVT_CLOSE,self.on_close)
        self.refresh_rules()
        if board_path:
            try:self.load(board_path)
            except Exception as e:error(self,e)
        self.Center()
    def select_page(self,page):
        for i in range(self.book.GetPageCount()):
            if self.book.GetPage(i) is page:self.book.SetSelection(i);return
    def build_menu(self):
        menu=wx.MenuBar();file=wx.Menu();edit=wx.Menu()
        for title,fn in [('Open board…\tCtrl+O',self.open_board),('Import native rule profile…',self.import_rules),('Export native rules only…',self.export_rules),('Export review bundle…\tCtrl+S',self.export),('Reload saved source',self.reload),('Rebuild managed courtyard areas…',self.rebuild_courtyards),('Close',lambda e:self.Close())]:
            item=file.Append(wx.ID_ANY,title);self.Bind(wx.EVT_MENU,fn,item)
        for title,fn in [('Undo workspace action\tCtrl+Z',self.undo),('Redo workspace action\tCtrl+Y',self.redo),('Copy generated native rules',self.copy_rules),('Edit rules in KiCad…',self.native_rule_help)]:
            item=edit.Append(wx.ID_ANY,title);self.Bind(wx.EVT_MENU,fn,item)
        menu.Append(file,'File');menu.Append(edit,'Edit')
        help_menu=wx.Menu()
        for title,topic in [('Help on this page\tF1',None),('Help centre','help-centre'),('Getting started','start'),('Constraint reference','constraint-reference'),('Function and property reference','function-reference'),('UI gallery','ui-gallery'),('Troubleshooting','troubleshooting'),('Release status / limitations','limitations')]:
            item=help_menu.Append(wx.ID_ANY,title)
            self.Bind(wx.EVT_MENU,lambda event,t=topic:self.open_help(t),item)
        menu.Append(help_menu,'Help');self.SetMenuBar(menu)
        self.Bind(wx.EVT_CHAR_HOOK,self.help_key)
    def build_rules(self):
        """Inspect existing/generated rules; native KiCad owns general rule editing."""
        root=wx.BoxSizer(wx.VERTICAL);self.rule_page.SetSizer(root)
        root.Add(label(self.rule_page,'Saved and generated rules — read only',True,14),0,wx.ALL,12)
        root.Add(button(self.rule_page,'Edit rules in KiCad…',self.native_rule_help),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.search=wx.SearchCtrl(self.rule_page);self.search.ShowCancelButton(True)
        root.Add(self.search,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.rules=wx.ListCtrl(self.rule_page,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(title,width) in enumerate((('On',44),('Rule name',340),('Severity',100))):self.rules.InsertColumn(i,title,width=width)
        root.Add(self.rules,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.rule_summary=wx.TextCtrl(self.rule_page,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,200));mono(self.rule_summary)
        root.Add(self.rule_summary,1,wx.EXPAND|wx.ALL,12)
        self.search.Bind(wx.EVT_TEXT,lambda e:self.refresh_rules())
        self.rules.Bind(wx.EVT_LIST_ITEM_SELECTED,self.select_rule)
    def checkpoint(self):
        self.undo_stack.append(self.w.clone());self.undo_stack=self.undo_stack[-30:];self.redo_stack.clear()
    def collect(self):
        """The rule overview is read-only; generators stage changes explicitly."""
        return

    def native_rule_help(self,event=None):
        info(self,'In KiCad PCB Editor, use Tools → Design Rule Editor for ordinary rules and conditions. '
                  'Use Board Setup for netclasses and board-wide constraints. Save there, then reload '
                  'the saved source in Studio. Export or undo staged Studio changes before reloading.')
    def refresh_rules(self,select_index=None):
        self.loading=True
        self.rules.DeleteAllItems();self.rule_rows=[];q=self.search.GetValue().lower()
        for i in reversed(range(len(self.w.document.rules))):
            r=self.w.document.rules[i]
            if q and q not in (r.name+' '+r.condition+' '+' '.join(c.kind for c in r.constraints)).lower():continue
            n=self.rules.InsertItem(self.rules.GetItemCount(),'✓' if r.enabled else '—');self.rules.SetItem(n,1,r.name);self.rules.SetItem(n,2,r.severity or 'inherit');self.rule_rows.append(i)
            if not r.enabled:self.rules.SetItemTextColour(n,MUTED)
        self.loading=False
        idx=self.index if select_index is None else select_index
        if idx in self.rule_rows:
            n=self.rule_rows.index(idx);self.rules.Select(n);self.rules.EnsureVisible(n)
        elif self.rule_rows:
            self.index=None;self.editing=None;self.rules.Select(0);self.load_rule(self.rule_rows[0])
        else:self.index=None;self.editing=None;self.clear_form()
        self.SetStatusText(f'{len(self.w.document.rules)} rules • highest priority shown first • source files untouched')
    def clear_form(self):
        self.rule_summary.ChangeValue('Select a rule to inspect its generated native syntax.')
    def select_rule(self,event):
        if self.loading:return
        n=event.GetIndex()
        if not (0<=n<len(self.rule_rows)):return
        idx=self.rule_rows[n]
        if idx==self.index:return
        self.collect();self.load_rule(idx)
    def load_rule(self,index):
        self.index=index;self.editing=None
        self.rule_summary.ChangeValue(self.w.document.rules[index].emit())














    def bga(self,event):
        self.collect()
        if not self.w.board_path:info(self,'Open a saved board first.');return
        with BGADialog(self,self.w,self.selected_ref) as d:
            if d.ShowModal()!=wx.ID_OK:return
            rules,board_text,guard=d.result;self.checkpoint()
            for r in rules:self.w.document.append(r)
            if board_text:self.w.board_text=board_text;self.w.refresh_board_context()
            if guard:self.w.guards.append(guard)
            self.load_rule(len(self.w.document.rules)-1);self.refresh_rules();self.select_page(self.rule_page)
            self.SetStatusText('Component rules staged. '+('A copied area is staged ONLY in the review board.' if guard else 'No geometry changed.'))

    def rebuild_courtyards(self,event):
        self.collect()
        if not self.w.guards:info(self,'This project has no Constraint Studio-managed courtyard areas.');return
        text='Rebuild these managed areas from the CURRENT SAVED footprint courtyard?\n\n'+'\n'.join(g['reference']+' → '+g['name'] for g in self.w.guards)+'\n\nNew managed scopes refuse independent area/rule edits; legacy scopes retain their rebuild behavior. Snapshot references and attached-area owner UUIDs must still match.'
        if wx.MessageBox(text,'Rebuild managed courtyard areas',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)!=wx.YES:return
        try:
            trial=self.w.clone()
            from .courtyards import sync_workspace
            sync_workspace(trial,explicit=True)
            for i,g in enumerate(trial.guards):
                if g.get('mode')=='footprint-owned-contours-v1':continue
                if g.get('mode')=='footprint-owned-linear-courtyard':
                    from .linked_areas import rebuild_attached_area
                    trial.board_text,new=rebuild_attached_area(trial.context,g)
                else:trial.board_text,new=refresh_copied_area(trial.context,g)
                trial.guards[i]=new;trial.refresh_board_context()
            self.checkpoint();self.w=trial;self.show_review(None)
        except Exception as e:error(self,e)

    def build_matrix(self):
        p=self.matrix_page;s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(label(p,'Pairwise spacing, like a constraint-manager spreadsheet',True,14),0,wx.ALL,16)
        s.Add(label(p,'Blank = inherit. Diagonal = same class/type, not necessarily same net. Clearance checks different nets; physical clearance also checks same-net objects.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        bar=wx.WrapSizer();s.Add(bar,0,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        self.mx_scope=choices(p,['netclass','component_class','type','net'],'netclass',False)
        self.mx_kind=choices(p,['clearance','physical_clearance','creepage','courtyard_clearance','hole_clearance','physical_hole_clearance','hole_to_hole','silk_clearance'],'clearance',False)
        self.mx_layer=choices(p,LAYERS,'Any');self.mx_group=wx.TextCtrl(p,value='Main');self.mx_region=choices(p,[])
        for title,c in [('Scope',self.mx_scope),('Constraint',self.mx_kind),('Layer',self.mx_layer),('Set name',self.mx_group),('Inside area (optional)',self.mx_region)]:bar.Add(label(p,title),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,8);bar.Add(c,0,wx.RIGHT|wx.BOTTOM,15)
        controls=wx.BoxSizer(wx.HORIZONTAL);s.Add(controls,0,wx.EXPAND|wx.ALL,16)
        self.mx_labels=wx.TextCtrl(p,value='Default, Power, HighSpeed');controls.Add(self.mx_labels,1,wx.RIGHT,12)
        controls.Add(button(p,'Build / reset grid',self.reset_matrix),0,wx.RIGHT,8);controls.Add(button(p,'Use project netclasses',self.project_matrix),0)
        self.matrix=gridlib.Grid(p);self.matrix.CreateGrid(3,3);self.matrix.SetDefaultColSize(160);self.matrix.SetRowLabelSize(180)
        self.matrix.Bind(gridlib.EVT_GRID_CELL_CHANGED,self.matrix_changed);s.Add(self.matrix,1,wx.EXPAND|wx.LEFT|wx.RIGHT,16)
        bottom=wx.BoxSizer(wx.HORIZONTAL);s.Add(bottom,0,wx.ALL,16)
        bottom.Add(button(p,'Stage / replace this rule set',self.stage_matrix),0,wx.RIGHT,12)
        bottom.Add(label(p,'Existing unrelated rules are kept. Review precedence after generating a matrix.'),0,wx.ALIGN_CENTER_VERTICAL)
        actions=wx.WrapSizer();s.Add(actions,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        for title,fn in [('Import CSV',self.matrix_import_csv),('Export CSV',self.matrix_export_csv),('Load saved matrix',self.matrix_load_saved),('Fill all cells',self.matrix_fill)]:actions.Add(button(p,title,fn),0,wx.RIGHT|wx.BOTTOM,6)
        self.mx_names=['Default','Power','HighSpeed'];self._matrix_busy=False;self.reset_matrix(None)
    def reset_matrix(self,event):
        try:
            names=[x.strip() for x in self.mx_labels.GetValue().split(',') if x.strip()]
            if not names or len(names)>80 or len(set(names))!=len(names):raise ValueError('Use 1–80 unique comma-separated labels')
            n=len(names);g=self.matrix
            if g.GetNumberRows():g.DeleteRows(0,g.GetNumberRows())
            if g.GetNumberCols():g.DeleteCols(0,g.GetNumberCols())
            g.AppendRows(n);g.AppendCols(n);self.mx_names=names
            for i,name in enumerate(names):
                g.SetRowLabelValue(i,name);g.SetColLabelValue(i,name)
                for j in range(n):g.SetReadOnly(i,j,j<i)
            self.mx_scope.SetToolTip('Type names use native capitalization such as Pad, Track, Via. Class labels must exist in the project.')
        except Exception as e:error(self,e)
    def project_matrix(self,event):
        self.mx_scope.SetValue('netclass');self.mx_labels.ChangeValue(', '.join(self.w.netclasses or ['Default']));self.reset_matrix(event)
    def matrix_changed(self,event):
        if self._matrix_busy:return
        i,j=event.GetRow(),event.GetCol();self._matrix_busy=True
        if i!=j:self.matrix.SetCellValue(j,i,self.matrix.GetCellValue(i,j))
        self._matrix_busy=False;event.Skip()
    def stage_matrix(self,event):
        try:
            self.collect();self.matrix.SaveEditControlValue();self.matrix.HideCellEditControl()
            cells={(i,j):self.matrix.GetCellValue(i,j) for i in range(len(self.mx_names)) for j in range(len(self.mx_names))}
            group=self.mx_group.GetValue().strip()
            if not group or '\n' in group:raise ValueError('Enter a nonempty matrix set name')
            layer=self.mx_layer.GetValue();layer='' if layer=='Any' else layer
            region=self.mx_region.GetValue().strip()
            from .linked_areas import all_areas
            if region and not any(a['name']==region and a['rule_area'] for a in all_areas(self.w.context)):raise ValueError('The optional region must be an existing named rule area; reload after creating it in KiCad')
            rules=matrix_rules(self.mx_names,cells,self.mx_kind.GetValue(),self.mx_scope.GetValue(),layer,group,region)
            if not rules and wx.MessageBox('All cells inherit. Remove this managed matrix rule set?', 'Clear matrix constraints',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
            from .engineering import rules_fingerprint
            old=self.w.metadata.get('matrices',{}).get(group)
            existing=[r for r in self.w.document.rules if 'CS-MATRIX '+group in r.notes.splitlines()]
            if old and old.get('rules_hash') and rules_fingerprint(existing)!=old['rules_hash']:
                raise ValueError('Matrix rules were edited manually. Use a new matrix set name or restore the managed rules before replacing them.')
            self.checkpoint();replace_generated(self.w.document,rules,'CS-MATRIX '+group)
            self.w.metadata.setdefault('matrices',{})[group]={'labels':self.mx_names[:],'cells':[[cells[i,j] for j in range(len(self.mx_names))] for i in range(len(self.mx_names))],'scope':self.mx_scope.GetValue(),'kind':self.mx_kind.GetValue(),'layer':layer,'region':region,'rules_hash':rules_fingerprint(rules)}
            self.index=None;self.editing=None;self.refresh_rules()
            info(self,f'{len(rules)} pair rules staged. Matrix set {group!r} was replaced in place where present; inspect other overlapping rule priorities.')
        except Exception as e:error(self,e)

    def matrix_import_csv(self,event):
        from .engineering import matrix_from_csv
        with wx.FileDialog(self,'Import a symmetric matrix',wildcard='CSV (*.csv)|*.csv',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                names,cells=matrix_from_csv(pathlib.Path(d.GetPath()).read_text('utf-8-sig'))
                if any(',' in n for n in names):raise ValueError('This GUI uses comma-separated labels; rename labels containing commas before importing')
                self.mx_labels.SetValue(', '.join(names));self.reset_matrix(None)
                for (i,j),v in cells.items():self.matrix.SetCellValue(i,j,v)
            except Exception as e:error(self,e)
    def matrix_export_csv(self,event):
        from .engineering import matrix_to_csv
        self.matrix.SaveEditControlValue();self.matrix.HideCellEditControl()
        with wx.FileDialog(self,'Export spacing matrix',wildcard='CSV (*.csv)|*.csv',defaultFile='clearance-matrix.csv',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:atomic_write(d.GetPath(),matrix_to_csv(self.mx_names,{(i,j):self.matrix.GetCellValue(i,j) for i in range(len(self.mx_names)) for j in range(len(self.mx_names))}).encode('utf-8-sig'))
            except Exception as e:error(self,e)
    def matrix_load_saved(self,event):
        saved=self.w.metadata.get('matrices',{});names=list(saved)
        if not names:info(self,'No managed matrix definitions are saved in this project. Existing native rule blocks remain editable in the rule worksheet.');return
        with wx.SingleChoiceDialog(self,'Choose a matrix','Load matrix',names) as d:
            if d.ShowModal()!=wx.ID_OK:return
            name=names[d.GetSelection()];m=saved[name];self.mx_group.SetValue(name);self.mx_labels.SetValue(', '.join(m['labels']));self.reset_matrix(None)
            self.mx_scope.SetValue(m['scope']);self.mx_kind.SetValue(m['kind']);self.mx_layer.SetValue(m['layer'] or 'Any');self.mx_region.SetValue(m['region'])
            for i,row in enumerate(m['cells']):
                for j,v in enumerate(row):self.matrix.SetCellValue(i,j,v)
    def matrix_fill(self,event):
        with wx.TextEntryDialog(self,'Fill all pair cells. Blank means inherit.','Fill matrix') as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                v=d.GetValue().strip()
                if v:
                    from .model import numeric
                    numeric(v)
                for i in range(len(self.mx_names)):
                    for j in range(len(self.mx_names)):self.matrix.SetCellValue(i,j,v)
            except Exception as e:error(self,e)
















    def build_review(self):
        p=self.review_page;s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(label(p,'Review staged changes, then ask KiCad to validate them',True,14),0,wx.ALL,16)
        s.Add(label(p,'KiCad 10 does not expose a supported IPC rule setter. This build exports review files; it does not hot-write an open project.\nUse the supplied offline apply tool only after closing every source-project editor. Clipboard transfer is available for rules-only changes.'),0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        actions=wx.WrapSizer();s.Add(actions,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        for title,fn in [('Refresh lint & diff',self.show_review),('Copy native rules',self.copy_rules),('Export review bundle…',self.export),('Run native DRC on export',self.run_native)]:actions.Add(button(p,title,fn),0,wx.RIGHT|wx.BOTTOM,8)
        clirow=wx.BoxSizer(wx.HORIZONTAL);s.Add(clirow,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        clirow.Add(label(p,'kicad-cli path (optional)'),0,wx.RIGHT|wx.ALIGN_CENTER_VERTICAL,12);self.cli_path=wx.TextCtrl(p);clirow.Add(self.cli_path,1,wx.RIGHT,8);clirow.Add(button(p,'Browse…',self.browse_cli),0)
        self.review_book=wx.Notebook(p);s.Add(self.review_book,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,16)
        self.issues=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.diff=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.native_text=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.rules_text=wx.TextCtrl(self.review_book,style=wx.TE_MULTILINE|wx.TE_READONLY)
        for ctrl,title in [(self.issues,'Local lint'),(self.diff,'File diff'),(self.rules_text,'Generated native rules'),(self.native_text,'Native DRC report')]:mono(ctrl);self.review_book.AddPage(ctrl,title)
        self.native_text.ChangeValue('Native DRC has NOT been run. A successful local lint result is not a geometry or syntax sign-off.')
    def show_review(self,event):
        self.collect()
        try:
            issues=self.w.issues();self.issues.ChangeValue('\n\n'.join(f'{i.severity.upper()}  |  {i.rule}\n{i.message}' for i in issues) or 'No local issues detected. Native KiCad syntax and geometry checking are still required.')
            self.diff.ChangeValue(self.w.review());self.rules_text.ChangeValue(self.w.document.emit());self.select_page(self.review_page)
        except Exception as e:error(self,e)
    def browse_cli(self,event):
        with wx.FileDialog(self,'Locate kicad-cli executable',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()==wx.ID_OK:self.cli_path.ChangeValue(d.GetPath())
    def copy_rules(self,event):
        self.collect()
        if any(x.severity=='error' for x in self.w.issues()):error(self,'Fix local lint errors before copying generated rules. See Review.');return
        if self.w.board_text and self.w.board_text!=((self.w.originals.get('.kicad_pcb') or b'').decode('utf-8-sig')):
            error(self,'This workspace contains staged geometry changes. Rules-only clipboard transfer would omit the required area. Export the full review bundle.');return
        if wx.TheClipboard.Open():
            try:wx.TheClipboard.SetData(wx.TextDataObject(self.w.document.emit()));wx.TheClipboard.Flush()
            finally:wx.TheClipboard.Close()
            info(self,'Generated rules copied. In KiCad Board Setup → Custom Rules, paste into the native editor, run its syntax check, inspect the changes, and accept. This does not apply staged .kicad_pro settings.')
        else:error(self,'Clipboard is in use')
    def export(self,event):
        self.collect()
        if not self.w.board_path:info(self,'Open a saved board before exporting a project review bundle.');return
        try:
            self.w.verify_originals()
            from .courtyards import sync_workspace
            trial=self.w.clone();names=sync_workspace(trial)
            if names:self.checkpoint();self.w=trial;self.index=None;self.editing=None;self.refresh_rules()
        except Exception as e:error(self,e);return
        if any(x.severity=='error' for x in self.w.issues()):
            if wx.MessageBox('Local lint contains errors. Export a REVIEW-ONLY bundle? The offline apply tool will refuse it.','Export with errors',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)!=wx.YES:return
        with wx.DirDialog(self,'Choose an EMPTY review folder outside the source project',style=wx.DD_DEFAULT_STYLE) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:self.last_export=self.w.export_bundle(d.GetPath());self.SetStatusText('Review bundle exported: '+str(self.last_export));info(self,'Review bundle exported; source files were NOT changed.\n\nOpen its board in KiCad, verify scope and settings, and run native DRC. The source release includes the offline apply tool with fingerprint checks and backups.')
            except Exception as e:error(self,e)
    def run_native(self,event):
        self.collect()
        if self.worker and self.worker.is_alive():info(self,'A native validation process is already running.');return
        if not self.last_export:info(self,'Export a review bundle first. Native DRC runs only on that exported copy.');return
        manifest=json.loads((self.last_export/'constraint-studio-manifest.json').read_text('utf-8'))
        # A changed workspace must not be attributed to an older exported validation.
        if self.w.dirty:error(self,'Workspace changed since export. Export a new bundle before validation.');return
        export_dir=self.last_export
        validation_snapshot=self.w.state()
        board=export_dir/self.w.board_path.name;cli=self.cli_path.GetValue().strip()
        self.native_text.ChangeValue('Running native KiCad DRC on the exported board. Zones are refilled in memory; source and export geometry are not saved by this command.\n')
        self.review_book.SetSelection(3)
        def work():
            try:
                result=native_drc(board,cli)
                text=json.dumps(result,indent=2,ensure_ascii=False)
                atomic_write(export_dir/'constraint-studio-validation-log.json',text.encode())
            except Exception as e:result=None;text='NATIVE VALIDATION FAILED / UNAVAILABLE\n'+str(e)
            wx.CallAfter(finish,text,result)
        def finish(text,result):
            if self and not self.IsBeingDeleted():
                from .report_view import report_excerpt
                self.native_text.ChangeValue(('STALE FOR CURRENT WORKSPACE — this report belongs to the earlier exported snapshot.\n\n' if self.w.state()!=validation_snapshot else '')+report_excerpt(text));self.SetStatusText('Native validation finished. Read the report; an exit code alone is not certification.')
                if result and isinstance(result.get('data'),dict):
                    try:self.reports_panel.load_data(result['data'],'Native DRC on exported review: '+str(export_dir))
                    except Exception as e:self.SetStatusText('Report available in Review; evidence-table import: '+str(e))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
    def import_rules(self,event):
        self.collect()
        with wx.FileDialog(self,'Import native rule profile',wildcard='KiCad rules (*.kicad_dru)|*.kicad_dru|All files|*.*',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                incoming=RuleDocument.load(pathlib.Path(d.GetPath()).read_text('utf-8-sig'))
                self.checkpoint()
                # Append the imported rules at higher priority; this is not whole-file replacement.
                for r in incoming.rules:self.w.document.append(copy.deepcopy(r))
                self.index=None;self.editing=None;self.refresh_rules();info(self,f'{len(incoming.rules)} rules appended at higher priority. Review overlap and project-specific names.')
            except Exception as e:error(self,e)
    def export_rules(self,event):
        self.collect()
        with wx.FileDialog(self,'Export native rules (not a project apply)',wildcard='KiCad rules (*.kicad_dru)|*.kicad_dru',defaultFile='constraint-profile.kicad_dru',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            p=pathlib.Path(d.GetPath()).resolve()
            if self.w.board_path and p==self.w.board_path.with_suffix('.kicad_dru'):error(self,'Do not hot-write the source rules. Export to a separate file or use native clipboard transfer.');return
            try:atomic_write(p,self.w.document.emit().encode());info(self,'Rule profile exported. Board settings and staged geometry are not included in this rules-only file.')
            except Exception as e:error(self,e)
    def build_help(self):
        s=wx.BoxSizer(wx.VERTICAL);self.help_page.SetSizer(s)
        try:
            self.help_panel=HelpPanel(self.help_page);s.Add(self.help_panel,1,wx.EXPAND)
            self.help_html=self.help_panel.content
        except Exception as exc:
            self.help_panel=None
            text=wx.StaticText(self.help_page,label='Offline help is unavailable. Reinstall the complete matching PCM package.\n'+str(exc))
            text.Wrap(760);s.Add(text,0,wx.ALL,20)
    def open_help(self,topic=None):
        if topic is None:
            page=self.book.GetCurrentPage();title=self.book.GetPageText(self.book.GetSelection());sub=''
            nested=getattr(page,'book',None)
            if nested is not None and nested.GetSelection()>=0:sub=nested.GetPageText(nested.GetSelection())
            if page is getattr(self,'workbench',None):
                nested=page.midbook;sub=nested.GetPageText(nested.GetSelection())
            topic=topic_for_page(title,sub)
        self.select_page(self.help_page)
        if self.help_panel:self.help_panel.navigate(topic)
    def help_key(self,event):
        if event.GetKeyCode()==wx.WXK_F1:self.open_help()
        else:event.Skip()
    def load(self,path):
        self.w=Workspace.load(path);self.index=None;self.editing=None;self.undo_stack=[];self.redo_stack=[];self.last_export=None
        self.project_label.SetLabel(self.w.board_path.name);self.SetTitle(TITLE+' — '+self.w.board_path.name)
        self.refresh_rules();self.project_matrix(None)
        from .linked_areas import all_areas
        self.mx_region.SetItems([a['name'] for a in all_areas(self.w.context) if a['rule_area']]);self.mx_region.SetValue('')
        if hasattr(self,'workbench'):self.workbench.refresh();self.profile_panel.refresh()
    def confirm_discard(self):
        self.collect()
        if not self.w.dirty:return True
        return wx.MessageBox('Discard unexported staged changes? Source files have not been modified.','Unexported changes',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)==wx.YES
    def open_board(self,event):
        if not self.confirm_discard():return
        with wx.FileDialog(self,'Open saved KiCad PCB',wildcard='KiCad board (*.kicad_pcb)|*.kicad_pcb',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()==wx.ID_OK:
                try:self.load(d.GetPath())
                except Exception as e:error(self,e)
    def reload(self,event):
        if self.w.board_path and self.confirm_discard():
            try:self.load(self.w.board_path)
            except Exception as e:error(self,e)
    def undo(self,event):
        self.collect()
        if not self.undo_stack:return
        self.redo_stack.append(self.w.clone());self.w=self.undo_stack.pop();self.index=None;self.editing=None;self.refresh_rules()
        if hasattr(self,'workbench'):self.workbench.refresh();self.profile_panel.refresh_review()
    def redo(self,event):
        if not self.redo_stack:return
        self.undo_stack.append(self.w.clone());self.w=self.redo_stack.pop();self.index=None;self.editing=None;self.refresh_rules()
        if hasattr(self,'workbench'):self.workbench.refresh();self.profile_panel.refresh_review()
    def page_changed(self,event):
        if event.GetEventObject() is not self.book:event.Skip();return
        if hasattr(self,'name'):self.collect()
        if hasattr(self,'workbench') and self.book.GetCurrentPage() is self.workbench:self.workbench.refresh()
        if hasattr(self,'profile_panel') and self.book.GetCurrentPage() is self.profile_panel:self.profile_panel.refresh_review()
        event.Skip()
    def on_close(self,event):
        if self.worker and self.worker.is_alive():
            info(self,'Native validation is still running. Close this window after it finishes.');event.Veto();return
        if not self.confirm_discard():event.Veto();return
        self.Destroy()


def launch(board_path='',selected_ref='',parent=None,native_select=None,native_probe=None,native_selection=None):
    frame=StudioFrame(parent,board_path,selected_ref,native_select,native_probe,native_selection)
    area=wx.GetClientDisplayRect();frame.SetSize((min(1560,area.width-32),min(960,area.height-48)))
    frame.Center();frame.Show();return frame
