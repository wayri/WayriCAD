"""Worksheet-first native workspace. No browser, webview, cloud, or generated mock UI.
All drawings are read-only saved-board previews and are labeled accordingly.
"""
import copy, csv, io, json, math, pathlib
import wx
from .help_system import tooltip_for
from .help_ui import bind_dialog_help
import wx.grid as gridlib
import wx.aui as aui
from .catalog import CATALOG, CATEGORIES, LAYERS, SEVERITIES
from .model import Rule, Constraint, RuleDocument, lint, numeric
from .inspection import items_from_board, rule_match, priority_trace, read_drc_report
from .engineering import (builtin_profiles, compile_profile, install_profile, capture_profile,
    validate_profile, matrix_from_csv, matrix_to_csv, timing_budget, length_from_delay,
    stackup_layers, record_review, review_state)
from .linked_areas import all_areas, area_polygon
from .workspace import atomic_write

INK='#17253C'; MUTED='#53647A'; LINE='#D8E0EA'; SURFACE='#F4F6FA'; ACCENT='#225ABC'

def text(parent,value,bold=False,size=10):
    w=wx.StaticText(parent,label=value);f=w.GetFont();f.SetPointSize(size)
    if bold:f.SetWeight(wx.FONTWEIGHT_BOLD)
    w.SetFont(f);return w

def btn(parent,value,fn):
    b=wx.Button(parent,label=value);b.Bind(wx.EVT_BUTTON,fn)
    tip=tooltip_for(value)
    if tip:b.SetToolTip(tip)
    return b

def fail(parent,e):wx.MessageBox(str(e),'Constraint Studio',wx.OK|wx.ICON_ERROR,parent)
def info(parent,s):wx.MessageBox(s,'Constraint Studio',wx.OK|wx.ICON_INFORMATION,parent)

def new_grid(parent,columns):
    grid=gridlib.Grid(parent);grid.CreateGrid(0,len(columns));grid.SetRowLabelSize(0)
    grid.SetDefaultRowSize(30);grid.SetColLabelSize(32);grid.SetGridLineColour(wx.Colour(LINE))
    grid.SetLabelBackgroundColour(wx.Colour(SURFACE));grid.SetSelectionMode(gridlib.Grid.SelectRows)
    for i,(name,width) in enumerate(columns):grid.SetColLabelValue(i,name);grid.SetColSize(i,width)
    return grid

def resize_rows(grid,count):
    old=grid.GetNumberRows()
    if old>count:grid.DeleteRows(count,old-count)
    elif count>old:grid.AppendRows(count-old)


def clipboard_read():
    if not wx.TheClipboard.Open():raise ValueError('Clipboard is in use')
    try:
        data=wx.TextDataObject()
        if not wx.TheClipboard.GetData(data):raise ValueError('Clipboard has no text')
        return data.GetText()
    finally:wx.TheClipboard.Close()

def clipboard_write(value):
    if not wx.TheClipboard.Open():raise ValueError('Clipboard is in use')
    try:wx.TheClipboard.SetData(wx.TextDataObject(value));wx.TheClipboard.Flush()
    finally:wx.TheClipboard.Close()


class BoardPreview(wx.Panel):
    """Lightweight saved-board overview, not a copper geometry/DCR renderer."""
    def __init__(self,parent,on_pick=None):
        super().__init__(parent);self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.items=[];self.areas=[];self.selected=set();self.zoom=1.;self.offset=(0.,0.);self.pick=on_pick;self.mapping=None
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_LEFT_DOWN,self.click);self.Bind(wx.EVT_LEFT_DCLICK,lambda e:self.fit())
        self.SetMinSize((250,180));self.SetToolTip('Wheel: zoom. Double click: fit board. Click an item: use as inspector A. Saved geometry preview, not native DRC.')
    def load(self,items,context):
        self.items=items;self.areas=[]
        for a in all_areas(context):
            try:self.areas.append((a['name'],area_polygon(a)))
            except ValueError:pass
        self.fit()
    def fit(self):self.zoom=1.;self.offset=(0.,0.);self.Refresh()
    def wheel(self,event):
        self.zoom=max(.2,min(40.,self.zoom*(1.15 if event.GetWheelRotation()>0 else 1/1.15)));self.Refresh()
    def click(self,event):
        if not self.mapping:return
        transform=self.mapping;pt=event.GetPosition();best=None;distance=20
        for item in self.items:
            for p in item.points:
                q=transform(p);d=math.hypot(q[0]-pt.x,q[1]-pt.y)
                if d<distance:distance=d;best=item
        if best and self.pick:self.pick(best)
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('#101D30'));dc.Clear()
        width,height=self.GetClientSize();dc.SetTextForeground('#DCE7F7')
        dc.DrawText('SAVED BOARD  ·  overview only  ·  wheel zoom / double-click fit',12,10)
        pts=[p for item in self.items for p in item.points]+[p for _,poly in self.areas for p in poly]
        if not pts:dc.DrawText('Open a board to preview its objects and rule areas.',12,44);return
        xmin,xmax=min(p[0] for p in pts),max(p[0] for p in pts);ymin,ymax=min(p[1] for p in pts),max(p[1] for p in pts)
        scale=min(max(width-50,10)/max(xmax-xmin,1),max(height-80,10)/max(ymax-ymin,1))*self.zoom
        cx,cy=(xmin+xmax)/2,(ymin+ymax)/2
        def xy(p):return (int(width/2+(p[0]-cx)*scale),int((height+30)/2+(p[1]-cy)*scale))
        self.mapping=xy
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        for name,poly in self.areas:
            dc.SetPen(wx.Pen('#C6A4F0',2,wx.PENSTYLE_SHORT_DASH));q=[xy(p) for p in poly]
            if len(q)>2:dc.DrawPolygon(q);dc.DrawText(name,q[0][0]+3,q[0][1]+3)
        for item in self.items[:50000]:
            color='#FFD369' if item.uid in self.selected else '#73B9EE' if any(l=='F.Cu' for l in item.layers) else '#96A2B7'
            dc.SetPen(wx.Pen(color,2 if item.uid in self.selected else 1));dc.SetBrush(wx.TRANSPARENT_BRUSH)
            q=[xy(p) for p in item.points]
            if not q:continue
            if item.geometry in ('polygon','envelope') and len(q)>2:dc.DrawPolygon(q)
            elif item.geometry=='capsule' and len(q)==2:
                dc.SetPen(wx.Pen(color,max(1,min(40,int(item.radius*2*scale)))));dc.DrawLine(*q[0],*q[1])
            elif item.geometry=='circle':dc.DrawCircle(*q[0],max(2,min(300,int(item.radius*scale))))
            elif item.kind=='Footprint':
                x,y=q[0];dc.DrawLine(x-4,y,x+4,y);dc.DrawLine(x,y-4,x,y+4);dc.DrawText(item.reference,x+6,y+3)
        dc.SetTextForeground('#ADBFD5');dc.DrawText('Not to scale for sign-off. Arcs/custom shapes may be omitted. Yellow = selected preview matches.',12,max(height-24,40))


class WorkspacePanel(wx.Panel):
    def __init__(self,parent,frame):
        super().__init__(parent);self.frame=frame;self.filter=('all','');self.rows=[];self.busy=False;self.items=[];self.current_items=[];self.last_stamp=None
        self.a=None;self.b=None
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        bar=wx.WrapSizer();root.Add(bar,0,wx.EXPAND|wx.ALL,10)
        for title,fn in [('New scoped rule',self.new_scoped),('BGA / component exception',frame.bga),('Edit selected rule',self.edit_selected),('Refresh',lambda e:self.refresh()),('Focus worksheet / restore',self.toggle_focus),('Undo',frame.undo),('Redo',frame.redo)]:bar.Add(btn(self,title,fn),0,wx.RIGHT|wx.BOTTOM,6)
        self.summary=text(self,'Open a board to start a constraint worksheet.',True,11);root.Add(self.summary,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        outer=wx.SplitterWindow(self,style=wx.SP_LIVE_UPDATE);root.Add(outer,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        nav=wx.Panel(outer);nav.SetBackgroundColour(SURFACE);ns=wx.BoxSizer(wx.VERTICAL);nav.SetSizer(ns)
        ns.Add(text(nav,'DESIGN SCOPE',True,11),0,wx.ALL,12)
        self.nav=wx.TreeCtrl(nav,style=wx.TR_DEFAULT_STYLE|wx.TR_HIDE_ROOT);ns.Add(self.nav,1,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.nav.Bind(wx.EVT_TREE_SEL_CHANGED,self.on_scope)
        body=wx.SplitterWindow(outer,style=wx.SP_LIVE_UPDATE);outer.SetMinimumPaneSize(175);outer.SplitVertically(nav,body,215)
        mid=wx.Panel(body);right=wx.ScrolledWindow(body);right.SetScrollRate(0,12)
        ms=wx.BoxSizer(wx.VERTICAL);mid.SetSizer(ms)
        searchrow=wx.BoxSizer(wx.HORIZONTAL);ms.Add(searchrow,0,wx.EXPAND|wx.ALL,8)
        self.search=wx.SearchCtrl(mid);self.search.ShowCancelButton(True);searchrow.Add(self.search,1,wx.RIGHT,8)
        self.disabled=wx.CheckBox(mid,label='Include disabled');self.disabled.SetValue(True);searchrow.Add(self.disabled,0,wx.ALIGN_CENTER_VERTICAL)
        self.search.Bind(wx.EVT_TEXT,lambda e:self.refresh_table());self.disabled.Bind(wx.EVT_CHECKBOX,lambda e:self.refresh_table())
        self.midbook=aui.AuiNotebook(mid,style=aui.AUI_NB_TOP|aui.AUI_NB_SCROLL_BUTTONS);ms.Add(self.midbook,1,wx.EXPAND)
        tablepanel=wx.Panel(self.midbook);ts=wx.BoxSizer(wx.VERTICAL);tablepanel.SetSizer(ts)
        self.grid=new_grid(tablepanel,[('On',45),('Priority',63),('Rule / set',220),('Constraint',195),('Minimum',94),('Preferred',94),('Maximum',94),('Layer',95),('Severity',84)])
        ts.Add(self.grid,1,wx.EXPAND)
        ts.Add(text(tablepanel,'Blank = unspecified / inherited. Scope tree filters declared references, not effective inheritance. Preferred values are targets.',False,9),0,wx.ALL,8)
        tools=wx.WrapSizer();ts.Add(tools,0,wx.EXPAND|wx.ALL,8)
        for title,fn in [('Fill selected rows',self.fill),('Copy rows',self.copy_rows),('Paste min / opt / max',self.paste_values),('Export CSV',self.export_csv),('Higher priority',lambda e:self.move(1)),('Lower priority',lambda e:self.move(-1))]:tools.Add(btn(tablepanel,title,fn),0,wx.RIGHT|wx.BOTTOM,5)
        self.midbook.AddPage(tablepanel,'Constraint worksheet')
        self.canvas=BoardPreview(self.midbook,self.pick_a);self.midbook.AddPage(self.canvas,'Layout scope preview')
        self.grid.Bind(gridlib.EVT_GRID_CELL_CHANGED,self.cell_changed);self.grid.Bind(gridlib.EVT_GRID_SELECT_CELL,self.select_cell)
        self.grid.Bind(gridlib.EVT_GRID_CELL_LEFT_DCLICK,lambda e:self.edit_selected(e) if e.GetCol() in (2,3) else e.Skip())
        rs=wx.BoxSizer(wx.VERTICAL);right.SetSizer(rs)
        rs.Add(text(right,'CONTEXT & EXPLANATION',True,11),0,wx.ALL,12)
        self.detail=text(right,'Select a worksheet row.');rs.Add(self.detail,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.scope_text=wx.TextCtrl(right,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,92));rs.Add(self.scope_text,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        scopebuttons=wx.WrapSizer();rs.Add(scopebuttons,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        for title,fn in [('Edit scope',self.edit_scope),('Find matches',self.preview_matches),('Cross-probe matches',self.probe_matches)]:scopebuttons.Add(btn(right,title,fn),0,wx.RIGHT|wx.BOTTOM,5)
        self.match_summary=text(right,'Scope preview has not been evaluated.');rs.Add(self.match_summary,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        rs.Add(text(right,'RULE RESOLUTION — OFFLINE SUBSET',True,10),0,wx.ALL,12)
        self.a_choice=wx.ComboBox(right,style=wx.CB_READONLY);self.b_choice=wx.ComboBox(right,style=wx.CB_READONLY)
        for title,ctrl in [('Object A',self.a_choice),('Object B (for pair rules)',self.b_choice)]:rs.Add(text(right,title),0,wx.LEFT|wx.BOTTOM,12);rs.Add(ctrl,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.a_choice.Bind(wx.EVT_COMBOBOX,self.choose_a);self.b_choice.Bind(wx.EVT_COMBOBOX,self.choose_b)
        pickbar=wx.WrapSizer();rs.Add(pickbar,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        for title,fn in [('Use KiCad selection',self.native_selection),('Explain priority',self.explain)]:pickbar.Add(btn(right,title,fn),0,wx.RIGHT|wx.BOTTOM,6)
        self.trace=wx.TextCtrl(right,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,220));rs.Add(self.trace,1,wx.EXPAND|wx.ALL,12)
        self.trace.ChangeValue('Native DRC and KiCad’s own constraint resolution remain authoritative. Unsupported expressions stay unknown; they are not treated as non-matches.')
        body.SetMinimumPaneSize(300);body.SplitVertically(mid,right,850);body.SetSashGravity(.75)
        self.outer=outer;self.body=body;self.nav_panel=nav;self.mid_panel=mid;self.right_panel=right;self.focused=False;self.refresh()
    def toggle_focus(self,event):
        if not self.focused:
            self.body.Unsplit(self.right_panel);self.outer.Unsplit(self.nav_panel);self.focused=True
        else:
            self.nav_panel.Show();self.right_panel.Show()
            self.outer.SplitVertically(self.nav_panel,self.body,215)
            self.body.SplitVertically(self.mid_panel,self.right_panel,max(350,int(self.body.GetClientSize().width*.7)));self.focused=False
        self.Layout()
    def refresh(self):
        f=self.frame
        if hasattr(f,'collect'):f.collect()
        self.busy=True
        try:
            w=f.w;old_filter=self.filter;aid=self.a.uid if self.a else '';bid=self.b.uid if self.b else '';self.items=items_from_board(w.context,w.project)
            selectnode=None
            self.nav.DeleteAllItems();root=self.nav.AddRoot('Workspace')
            allnode=self.nav.AppendItem(root,'All constraints');self.nav.SetItemData(allnode,('all',''))
            groups=self.nav.AppendItem(root,'Constraint domains')
            for cat in CATEGORIES:
                node=self.nav.AppendItem(groups,cat);self.nav.SetItemData(node,('category',cat))
                if old_filter==('category',cat):selectnode=node
            for title,kind,names in [('Components','component',[fp.reference for fp in w.context.footprints]),('Netclasses','netclass',w.netclasses),('Nets','net',w.context.nets),('Rule areas','area',[a['name'] for a in all_areas(w.context)])]:
                parent=self.nav.AppendItem(root,title+f' ({len(names)})')
                for name in names[:1500]:
                    node=self.nav.AppendItem(parent,name);self.nav.SetItemData(node,(kind,name))
                    if old_filter==(kind,name):selectnode=node;self.nav.Expand(parent)
            self.nav.Expand(groups);self.nav.SelectItem(selectnode or allnode);self.filter=old_filter if selectnode else ('all','')
            self.a_choice.SetItems([item.label for item in self.items]);self.b_choice.SetItems(['No second object']+[item.label for item in self.items]);self.b_choice.SetSelection(0)
            self.a=next((i for i in self.items if i.uid==aid and aid),None);self.b=next((i for i in self.items if i.uid==bid and bid),None)
            if self.a:self.a_choice.SetSelection(self.items.index(self.a))
            if self.b:self.b_choice.SetSelection(self.items.index(self.b)+1)
            self.current_items=[];self.canvas.selected=set();self.match_summary.SetLabel('Scope preview has not been evaluated for this workspace state.')
            self.canvas.load(self.items,w.context)
        finally:self.busy=False
        self.refresh_table()
    def on_scope(self,event):
        if self.busy or not self.nav or self.nav.IsBeingDeleted():return
        data=self.nav.GetItemData(event.GetItem())
        if data:self.filter=data
        if data and data[0]=='component':self.frame.selected_ref=data[1]
        self.refresh_table()
    def refresh_table(self):
        if self.busy:return
        self.busy=True
        try:
            q=self.search.GetValue().lower().strip();kind,target=self.filter;self.rows=[];w=self.frame.w
            area_names=[a['name'] for a in all_areas(w.context) if a.get('owner')==target]
            for index in range(len(w.document.rules)-1,-1,-1):
                r=w.document.rules[index]
                if not r.enabled and not self.disabled.GetValue():continue
                if kind in ('component','netclass','net','area') and target not in r.condition and target not in r.name and not any(n in r.condition for n in area_names):continue
                for ci,c in enumerate(r.constraints):
                    spec=CATALOG.get(c.kind)
                    if kind=='category' and (not spec or spec.category!=target):continue
                    if q and q not in (r.name+' '+r.condition+' '+c.kind+' '+(spec.label if spec else '')).lower():continue
                    self.rows.append((index,ci))
            resize_rows(self.grid,len(self.rows))
            for row,(ri,ci) in enumerate(self.rows):
                r=w.document.rules[ri];c=r.constraints[ci];spec=CATALOG.get(c.kind)
                vals=['yes' if r.enabled else 'no',str(len(w.document.rules)-ri),r.name,spec.label if spec else c.kind,c.values.get('min',''),c.values.get('opt',''),c.values.get('max',''),r.layer or 'Any',r.severity or 'inherit']
                for col,v in enumerate(vals):
                    self.grid.SetCellValue(row,col,str(v));self.grid.SetReadOnly(row,col,col in (1,3) or (col in (4,5,6) and (not spec or ('min','opt','max')[col-4] not in spec.fields)))
                    self.grid.SetCellBackgroundColour(row,col,wx.Colour('white' if row%2==0 else '#F6F8FC'))
                    self.grid.SetCellTextColour(row,col,wx.Colour(INK if r.enabled else MUTED))
                self.grid.SetCellEditor(row,0,gridlib.GridCellChoiceEditor(['yes','no']))
                self.grid.SetCellEditor(row,7,gridlib.GridCellChoiceEditor(LAYERS,True))
                self.grid.SetCellEditor(row,8,gridlib.GridCellChoiceEditor(['inherit']+SEVERITIES))
            self.summary.SetLabel(f'{len(self.rows)} constraint rows  ·  {len(w.document.rules)} rules  ·  {len(self.items)} saved objects  ·  Review: {review_state(w)}')
        finally:self.busy=False
    def selected_row(self):
        row=self.grid.GetGridCursorRow()
        return self.rows[row] if 0<=row<len(self.rows) else None
    def selected_rows(self):
        rows=list(self.grid.GetSelectedRows())
        if not rows and self.grid.GetGridCursorRow()>=0:rows=[self.grid.GetGridCursorRow()]
        return [r for r in rows if r<len(self.rows)]
    def after_change(self):
        # Discard stale form copies so visiting the detail tab cannot overwrite
        # a worksheet edit with the previous rule model.
        f=self.frame;f.index=None;f.editing=None;f.refresh_rules();self.refresh_table();self.current_items=[];self.canvas.selected=set();self.canvas.Refresh();self.match_summary.SetLabel('Rules changed — evaluate matches again.')
    def cell_changed(self,event):
        if self.busy:return
        row,col=event.GetRow(),event.GetCol()
        if row>=len(self.rows):return
        ri,ci=self.rows[row];trial=self.frame.w.clone();r=trial.document.rules[ri];c=r.constraints[ci];value=self.grid.GetCellValue(row,col).strip()
        try:
            if col==0:r.enabled=value=='yes'
            elif col==2:
                if not value:raise ValueError('Rule name cannot be blank')
                r.name=value
            elif col in (4,5,6):
                key=('min','opt','max')[col-4]
                if value:numeric(value,CATALOG[c.kind].unit);c.values[key]=value
                else:c.values.pop(key,None)
            elif col==7:r.layer='' if value=='Any' else value
            elif col==8:r.severity='' if value=='inherit' else value
            errors=[i.message for i in lint(RuleDocument(rules=[r])) if i.severity=='error']
            if errors:raise ValueError('\n'.join(errors))
            self.frame.checkpoint();self.frame.w=trial;self.after_change()
        except Exception as e:fail(self,e);self.refresh_table()
    def select_cell(self,event):
        row=event.GetRow()
        if row<len(self.rows):
            ri,ci=self.rows[row];r=self.frame.w.document.rules[ri];c=r.constraints[ci]
            self.detail.SetLabel(r.name+'\n'+(CATALOG[c.kind].help if c.kind in CATALOG else 'Preserved native extension'));self.detail.Wrap(305)
            self.scope_text.ChangeValue(r.condition or 'All objects (no condition)')
            self.trace.ChangeValue('Choose A (and B for pair constraints), then Explain priority. This is an offline subset trace, not a native winner query.')
        event.Skip()
    def edit_selected(self,event):
        row=self.selected_row()
        if not row:return
        self.frame.load_rule(row[0]);self.frame.refresh_rules(row[0]);self.frame.select_page(self.frame.rule_page)
    def edit_scope(self,event):
        row=self.selected_row()
        if not row:return
        self.frame.load_rule(row[0]);self.frame.build_scope(event);self.frame.collect();self.after_change()
    def new_scoped(self,event):
        from .expressions import property_test,function_test
        kind,target=self.filter;r=Rule('New '+(target or 'board')+' rule',constraints=[Constraint('clearance',{'min':'0.2mm'})])
        # A new rule starts disabled: 0.2 mm is an editable placeholder, not a
        # proposed manufacturing value or an automatically active exception.
        r.enabled=False;r.notes='Draft placeholder. Enter approved values before enabling.'
        if kind=='component':r.condition=function_test('A','memberOfFootprint',[target]).emit()
        elif kind=='netclass':r.condition=function_test('A','hasNetclass',[target]).emit()
        elif kind=='net':r.condition=property_test('A','NetName','==',target).emit()
        elif kind=='area':
            from .expressions import both
            r.condition=both('enclosedByArea',target).emit()
        self.frame.collect();self.frame.checkpoint();self.frame.w.document.append(r);self.after_change()
        self.frame.load_rule(len(self.frame.w.document.rules)-1);self.frame.select_page(self.frame.rule_page)
    def move(self,delta):
        row=self.selected_row()
        if not row:return
        self.frame.collect();self.frame.checkpoint();self.frame.w.document.move(row[0],delta);self.after_change()
    def fill(self,event):
        selected=self.selected_rows()
        if not selected:return
        with wx.SingleChoiceDialog(self,'Choose a column to fill for selected rows','Bulk fill',['Minimum','Preferred','Maximum']) as choose:
            if choose.ShowModal()!=wx.ID_OK:return
            key=('min','opt','max')[choose.GetSelection()]
        with wx.TextEntryDialog(self,'Value with units. Blank removes this field.','Fill '+key) as d:
            if d.ShowModal()!=wx.ID_OK:return
            value=d.GetValue().strip()
        try:
            trial=self.frame.w.clone()
            for row in selected:
                ri,ci=self.rows[row];c=trial.document.rules[ri].constraints[ci];spec=CATALOG.get(c.kind)
                if not spec or key not in spec.fields:raise ValueError(c.kind+' does not support '+key+'; no rows were changed')
                if value:numeric(value,spec.unit);c.values[key]=value
                else:c.values.pop(key,None)
            errs=[i.message for i in lint(RuleDocument(rules=[trial.document.rules[i] for i in sorted(set(self.rows[r][0] for r in selected))])) if i.severity=='error']
            if errs:raise ValueError('\n'.join(errs))
            self.frame.checkpoint();self.frame.w=trial;self.after_change()
        except Exception as e:fail(self,e)
    def copy_rows(self,event):
        try:clipboard_write('\n'.join('\t'.join(self.grid.GetCellValue(row,c) for c in range(self.grid.GetNumberCols())) for row in self.selected_rows()))
        except Exception as e:fail(self,e)
    def paste_values(self,event):
        try:
            rows=list(csv.reader(io.StringIO(clipboard_read()),delimiter='\t'));start=self.grid.GetGridCursorRow()
            if start<0 or start+len(rows)>len(self.rows):raise ValueError('Select a starting row with enough remaining worksheet rows')
            trial=self.frame.w.clone();affected=set()
            for i,values in enumerate(rows):
                if len(values)!=3:raise ValueError('Paste exactly three columns: minimum, preferred, maximum')
                ri,ci=self.rows[start+i];c=trial.document.rules[ri].constraints[ci];spec=CATALOG.get(c.kind);affected.add(ri)
                for key,value in zip(('min','opt','max'),values):
                    if value.strip():
                        if not spec or key not in spec.fields:raise ValueError(c.kind+' has no '+key)
                        numeric(value,spec.unit);c.values[key]=value.strip()
                    else:c.values.pop(key,None)
            errors=[x.message for x in lint(RuleDocument(rules=[trial.document.rules[i] for i in affected])) if x.severity=='error']
            if errors:raise ValueError('\n'.join(errors))
            self.frame.checkpoint();self.frame.w=trial;self.after_change()
        except Exception as e:fail(self,e)
    def export_csv(self,event):
        with wx.FileDialog(self,'Export visible worksheet',wildcard='CSV (*.csv)|*.csv',defaultFile='constraints.csv',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()!=wx.ID_OK:return
            out=io.StringIO(newline='');writer=csv.writer(out);writer.writerow([self.grid.GetColLabelValue(c) for c in range(self.grid.GetNumberCols())])
            for r in range(self.grid.GetNumberRows()):writer.writerow([self.grid.GetCellValue(r,c) for c in range(self.grid.GetNumberCols())])
            try:atomic_write(d.GetPath(),out.getvalue().encode('utf-8-sig'))
            except Exception as e:fail(self,e)
    def preview_matches(self,event):
        row=self.selected_row()
        if not row:return
        r=self.frame.w.document.rules[row[0]];c=r.constraints[row[1]];pair=CATALOG.get(c.kind).pair if c.kind in CATALOG else False
        yes=[];unknown=0
        if len(self.items)>50000:fail(self,'Scope preview is limited to 50,000 objects. Use native DRC for this board.');return
        for item in self.items:
            m=rule_match(r,item,self.b,self.frame.w.context,pair=pair)
            if m.value is True:yes.append(item)
            elif m.value is None:unknown+=1
        self.current_items=yes;self.canvas.selected={i.uid for i in yes};self.canvas.Refresh()
        msg=f'{len(yes)} offline matches; {unknown} unknown; {len(self.items)-len(yes)-unknown} non-matches.'
        if pair and not self.b:msg+=' Select B to evaluate pair scopes.'
        self.match_summary.SetLabel(msg);self.match_summary.Wrap(305)
        self.midbook.SetSelection(1)
    def probe_matches(self,event):
        callback=getattr(self.frame,'native_probe',None)
        if not callback:info(self,'Cross-probing requires launching from KiCad. Offline preview remains available.');return
        if not self.current_items:info(self,'Find matches first. Unknown matches are never selected.');return
        if len(self.current_items)>2000:fail(self,'Refine the scope to 2,000 or fewer matched items before cross-probing.');return
        try:
            self.frame.w.verify_originals();callback([i.uid for i in self.current_items if i.uid])
        except Exception as e:fail(self,e)
    def pick_a(self,item):
        self.a=item
        for i,x in enumerate(self.items):
            if x.uid==item.uid:self.a_choice.SetSelection(i);break
        self.canvas.selected={item.uid};self.canvas.Refresh()
    def choose_a(self,event):
        n=self.a_choice.GetSelection();self.a=self.items[n] if n>=0 else None
    def choose_b(self,event):
        n=self.b_choice.GetSelection()-1;self.b=self.items[n] if n>=0 else None
    def native_selection(self,event):
        callback=getattr(self.frame,'native_selection',None)
        if not callback:info(self,'Selection capture is available only when launched from KiCad.');return
        try:
            ids=callback();selected=[i for i in self.items if i.uid in ids]
            if not selected:raise ValueError('No selected saved objects found. Save/reload after creating or changing objects.')
            self.pick_a(selected[0]);self.b=selected[1] if len(selected)>1 else None
            self.b_choice.SetSelection(self.items.index(self.b)+1 if self.b else 0)
        except Exception as e:fail(self,e)
    def explain(self,event):
        row=self.selected_row()
        if not row or not self.a:info(self,'Select a constraint row and Object A. Pair rules also need Object B.');return
        c=self.frame.w.document.rules[row[0]].constraints[row[1]]
        t=priority_trace(self.frame.w.document,c.kind,self.a,self.b,self.frame.w.context,self.frame.w.floors)
        lines=['OFFLINE SCOPE / PRIORITY TRACE — NOT NATIVE SIGN-OFF',f'Manufacturing floor: {t["manufacturing_floor_mm"]} mm' if t['manufacturing_floor_mm'] is not None else 'No mapped manufacturing floor in the saved project.','']
        for r in t['rows']:
            lines.extend([f'#{r["priority"]}  {r["rule"]}',r['status']+' | '+r['severity'],'; '.join(r['constraints']),'; '.join(r['reasons']),''])
        lines.append(t['warning']);self.trace.ChangeValue('\n'.join(lines))


class CaptureSetDialog(wx.Dialog):
    """Capture multiple worksheet rules and bind literal fields without JSON edits."""
    def __init__(self,parent,rules):
        super().__init__(parent,title='Create a reusable constraint set',size=(1040,700),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        bind_dialog_help(self,"capture-set")
        from .engineering import profile_slots
        self.result=None;self.base=capture_profile(rules,'user.my-set','My constraint set');self.slots=profile_slots(self.base)
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        root.Add(text(self,'Capture selected rules → choose fields to parameterize',True,13),0,wx.ALL,14)
        g=wx.FlexGridSizer(cols=2,vgap=8,hgap=12);g.AddGrowableCol(1,1);root.Add(g,0,wx.EXPAND|wx.LEFT|wx.RIGHT,14)
        self.pid=wx.TextCtrl(self,value='user.my-set');self.name=wx.TextCtrl(self,value='My constraint set');self.version=wx.TextCtrl(self,value='1.0.0')
        for label,control in [('Stable identifier',self.pid),('Display name',self.name),('Version',self.version)]:g.Add(text(self,label),0,wx.ALIGN_CENTER_VERTICAL);g.Add(control,1,wx.EXPAND)
        root.Add(text(self,'Leave Parameter blank to retain the literal. Reuse a parameter name to bind multiple compatible fields together.'),0,wx.ALL,14)
        self.grid=new_grid(self,[('Captured rule / field',370),('Saved value',250),('Parameter (optional)',220),('Type',100)])
        resize_rows(self.grid,len(self.slots));root.Add(self.grid,1,wx.EXPAND|wx.LEFT|wx.RIGHT,14)
        for i,slot in enumerate(self.slots):
            for j,value in enumerate((slot['label'],slot['value'],'',slot['type'])):self.grid.SetCellValue(i,j,value)
            self.grid.SetReadOnly(i,0);self.grid.SetReadOnly(i,1);self.grid.SetCellEditor(i,3,gridlib.GridCellChoiceEditor(['text','mm','ps','count','number','layer','deg']))
        self.defaults=wx.CheckBox(self,label='Use captured parameter values as defaults (otherwise require explicit values on every binding)');root.Add(self.defaults,0,wx.ALL,14)
        root.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL|wx.HELP),0,wx.EXPAND|wx.ALL,14)
        self.Bind(wx.EVT_BUTTON,self.ok,id=wx.ID_OK);self.SetMinSize((850,550));self.CenterOnParent()
    def ok(self,event):
        from .engineering import parameterize_profile
        try:
            self.grid.SaveEditControlValue();self.grid.HideCellEditControl()
            p=copy.deepcopy(self.base);p['id']=self.pid.GetValue().strip();p['name']=self.name.GetValue().strip();p['version']=self.version.GetValue().strip()
            choices={i:{'name':self.grid.GetCellValue(i,2).strip(),'type':self.grid.GetCellValue(i,3)} for i in range(len(self.slots)) if self.grid.GetCellValue(i,2).strip()}
            self.result=parameterize_profile(p,choices,self.defaults.GetValue());self.EndModal(wx.ID_OK)
        except Exception as e:fail(self,e)



class ProfilesPanel(wx.Panel):
    def __init__(self,parent,frame):
        super().__init__(parent);self.frame=frame;self.profiles=[];self.current=None;self.pending=None
        root=wx.BoxSizer(wx.VERTICAL);self.SetSizer(root)
        root.Add(text(self,'Reusable constraints & engineering budgets',True,14),0,wx.ALL,14)
        top=wx.WrapSizer();root.Add(top,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        for label,fn in [('Import profile JSON',self.import_profile),('Export current profile',self.export_profile),('Create set from selected rules',self.capture),('Refresh sets',lambda e:self.refresh())]:top.Add(btn(self,label,fn),0,wx.RIGHT|wx.BOTTOM,6)
        book=aui.AuiNotebook(self,style=aui.AUI_NB_TOP|aui.AUI_NB_SCROLL_BUTTONS);self.book=book;root.Add(book,1,wx.EXPAND|wx.ALL,10)
        p=wx.Panel(book);book.AddPage(p,'Constraint sets');ps=wx.BoxSizer(wx.HORIZONTAL);p.SetSizer(ps)
        left=wx.Panel(p);ls=wx.BoxSizer(wx.VERTICAL);left.SetSizer(ls);ps.Add(left,0,wx.EXPAND|wx.RIGHT,12)
        self.list=wx.ListBox(left,size=(270,-1));ls.Add(self.list,1,wx.EXPAND);self.list.Bind(wx.EVT_LISTBOX,self.select_profile)
        right=wx.Panel(p);rs=wx.BoxSizer(wx.VERTICAL);right.SetSizer(rs);ps.Add(right,1,wx.EXPAND)
        self.description=text(right,'Select a profile. Parameters are intentionally blank until you enter approved values.');rs.Add(self.description,0,wx.EXPAND|wx.ALL,8)
        line=wx.BoxSizer(wx.HORIZONTAL);rs.Add(line,0,wx.EXPAND|wx.ALL,8);line.Add(text(right,'Instance name'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
        self.instance=wx.TextCtrl(right,value='My interface');line.Add(self.instance,1)
        self.params=new_grid(right,[('Parameter',290),('Type',110),('Value / project binding',330)]);rs.Add(self.params,1,wx.EXPAND|wx.ALL,8)
        self.apply_floors=wx.CheckBox(right,label='Explicitly apply the profile’s board-wide manufacturing floors');rs.Add(self.apply_floors,0,wx.ALL,8)
        self.migration=wx.CheckBox(right,label='I reviewed and approve replacement by a changed profile version / definition');rs.Add(self.migration,0,wx.ALL,8)
        bar=wx.WrapSizer();rs.Add(bar,0,wx.ALL,8)
        for label,fn in [('Preview generated rules / diff',self.preview),('Stage set',self.stage),('Load an existing instance',self.load_instance),('Ungroup instance',self.ungroup)]:bar.Add(btn(right,label,fn),0,wx.RIGHT|wx.BOTTOM,6)
        self.preview_text=wx.TextCtrl(right,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,200));rs.Add(self.preview_text,1,wx.EXPAND|wx.ALL,8)
        self._timing(book);self._review(book);self.refresh()
    def refresh(self):
        self.profiles=builtin_profiles()+list(self.frame.w.metadata.get('profiles',{}).values())
        unique={p['id']+'@'+p['version']:p for p in self.profiles};self.profiles=list(unique.values())
        self.list.Set([p['name']+'  ·  '+p['version'] for p in self.profiles])
        if self.profiles:self.list.SetSelection(0);self.select_profile(None)
        self.refresh_review()
    def select_profile(self,event):
        idx=self.list.GetSelection()
        if idx<0:return
        self.current=self.profiles[idx];self.description.SetLabel(self.current.get('description',''));self.description.Wrap(840)
        self.param_keys=list(self.current.get('parameters',{}));resize_rows(self.params,len(self.param_keys))
        for i,key in enumerate(self.param_keys):
            spec=self.current['parameters'][key]
            for col,v in enumerate((spec.get('label',key),spec['type'],spec.get('default',''))):self.params.SetCellValue(i,col,str(v));self.params.SetReadOnly(i,col,col<2)
            if spec['type']=='layer':self.params.SetCellEditor(i,2,gridlib.GridCellChoiceEditor(self.frame.w.context.layers,True))
            if key=='netclass':self.params.SetCellEditor(i,2,gridlib.GridCellChoiceEditor(self.frame.w.netclasses,True))
        self.apply_floors.SetValue(False);self.apply_floors.Enable(bool(self.current.get('floors')));self.migration.SetValue(False);self.preview_text.ChangeValue('Enter values, then Preview. No constraints are changed until Stage set.')
    def bindings(self):
        self.params.SaveEditControlValue();self.params.HideCellEditControl()
        return {key:self.params.GetCellValue(i,2).strip() for i,key in enumerate(self.param_keys)}
    def preview(self,event):
        try:
            if not self.current:raise ValueError('Select a profile')
            self.frame.collect();trial=self.frame.w.clone();install_profile(trial,self.current,self.bindings(),self.instance.GetValue().strip(),self.apply_floors.GetValue(),self.migration.GetValue())
            self.preview_text.ChangeValue(trial.review());self.pending=trial
        except Exception as e:fail(self,e)
    def stage(self,event):
        try:
            self.frame.collect();trial=self.frame.w.clone();install_profile(trial,self.current,self.bindings(),self.instance.GetValue().strip(),self.apply_floors.GetValue(),self.migration.GetValue())
            if self.apply_floors.GetValue() and wx.MessageBox('Apply these staged board-wide manufacturing floor changes? Review fabrication approval independently.','Board floor change',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)!=wx.YES:return
            self.frame.checkpoint();self.frame.w=trial;self.frame.index=None;self.frame.editing=None;self.frame.refresh_rules();self.frame.refresh_settings();self.frame.workbench.refresh();self.refresh_review()
            self.preview_text.ChangeValue('Set staged. Source files are unchanged. Export and validate the review bundle.')
        except Exception as e:fail(self,e)
    def load_instance(self,event):
        instances=self.frame.w.metadata.get('profile_instances',{});names=list(instances)
        if not names:info(self,'No saved profile instances in this workspace.');return
        with wx.SingleChoiceDialog(self,'Select a managed set','Load bindings',names) as d:
            if d.ShowModal()!=wx.ID_OK:return
            name=names[d.GetSelection()];entry=instances[name];key=entry['profile_id']+'@'+entry['version']
            for i,p in enumerate(self.profiles):
                if p['id']+'@'+p['version']==key:self.list.SetSelection(i);self.select_profile(None);break
            else:fail(self,'Profile definition is missing; import it before editing this instance.');return
            self.instance.SetValue(name)
            for i,k in enumerate(self.param_keys):self.params.SetCellValue(i,2,str(entry.get('bindings',{}).get(k,'')))
    def ungroup(self,event):
        name=self.instance.GetValue().strip();instances=self.frame.w.metadata.get('profile_instances',{})
        if name not in instances:info(self,'Load a managed instance first.');return
        if wx.MessageBox('Keep the generated rules but remove profile ownership? Future profile migrations will not update this block.','Ungroup set',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        self.frame.checkpoint();marker='CS-SET '+name
        for r in self.frame.w.document.rules:
            if marker in r.notes.splitlines():r.notes='\n'.join(x for x in r.notes.splitlines() if x!=marker)
        instances.pop(name);self.frame.index=None;self.frame.editing=None;self.frame.refresh_rules();self.frame.workbench.refresh()
    def import_profile(self,event):
        with wx.FileDialog(self,'Import constraint set',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                p=validate_profile(json.loads(pathlib.Path(d.GetPath()).read_text('utf-8-sig')));self.frame.checkpoint();self.frame.w.metadata.setdefault('profiles',{})[p['id']+'@'+p['version']]=p;self.refresh()
            except Exception as e:fail(self,e)
    def export_profile(self,event):
        if not self.current:return
        with wx.FileDialog(self,'Export reusable constraint set',wildcard='JSON (*.json)|*.json',defaultFile=self.current['id']+'.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as d:
            if d.ShowModal()==wx.ID_OK:
                try:atomic_write(d.GetPath(),(json.dumps(self.current,indent=2)+'\n').encode())
                except Exception as e:fail(self,e)
    def capture(self,event):
        self.frame.collect();view=self.frame.workbench
        indices=sorted(set(view.rows[row][0] for row in view.selected_rows()))
        if not indices:info(self,'Select one or more rules in the Workspace first.');return
        try:
            with CaptureSetDialog(self,[self.frame.w.document.rules[i] for i in indices]) as d:
                if d.ShowModal()!=wx.ID_OK:return
                p=d.result;key=p['id']+'@'+p['version']
                if key in self.frame.w.metadata.get('profiles',{}) and wx.MessageBox('Replace this local profile definition? Existing instances will require explicit migration approval when updated.','Profile definition exists',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
                self.frame.checkpoint();self.frame.w.metadata.setdefault('profiles',{})[key]=p;self.refresh()
        except Exception as e:fail(self,e)
    def _timing(self,book):
        p=wx.ScrolledWindow(book);p.SetScrollRate(0,12);book.AddPage(p,'Timing budget & stackup');s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(text(p,'Allocate a real timing budget — without inventing an impedance result',True,12),0,wx.ALL,14)
        grid=wx.FlexGridSizer(cols=2,vgap=12,hgap=14);grid.AddGrowableCol(1,1);s.Add(grid,0,wx.EXPAND|wx.ALL,14)
        self.budget_inputs={}
        for key,name,default in [('total','Total available delay (ps)',''),('package','Known package contributions (ps)','0'),('connector','Known connector / other contributions (ps)','0'),('margin','Reserved margin (ps)','0'),('er','Optional EFFECTIVE permittivity for a uniform-line estimate','')]:
            grid.Add(text(p,name),0,wx.ALIGN_CENTER_VERTICAL);ctrl=wx.TextCtrl(p,value=default);grid.Add(ctrl,1,wx.EXPAND);self.budget_inputs[key]=ctrl
        s.Add(btn(p,'Calculate PCB allocation',self.calculate),0,wx.ALL,14)
        self.budget_result=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,160));s.Add(self.budget_result,0,wx.EXPAND|wx.ALL,14)
        s.Add(btn(p,'Read saved stackup',self.read_stackup),0,wx.ALL,14)
        self.stack_grid=new_grid(p,[('Layer',180),('Type',140),('Material',210),('Thickness (mm)',150),('Dielectric εr',130),('Loss tangent',125)]);s.Add(self.stack_grid,1,wx.EXPAND|wx.ALL,14)
        s.Add(text(p,'Dielectric εr is NOT automatically microstrip effective permittivity. This budget page is not a field solver. The separate 2-D line solver uses ideal assumptions; no via model or impedance sign-off is supplied.',False,9),0,wx.ALL,14)
    def calculate(self,event):
        try:
            d={k:c.GetValue().strip() for k,c in self.budget_inputs.items()};b=timing_budget(d['total'],d['package'],d['connector'],d['margin'])
            msg=f'PCB propagation budget: {b["pcb_ps"]:.6g} ps\nTotal minus supplied package, connector and reserved-margin terms.\n'
            if d['er']:msg+=f'Uniform-line estimate only: {length_from_delay(b["pcb_ps"],d["er"]):.6g} mm\n'
            msg+='Use the From–to path profile with the PCB delay in ps. Enter source/sink and bounds explicitly.\n'+b['warning'];self.budget_result.ChangeValue(msg)
        except Exception as e:fail(self,e)
    def read_stackup(self,event):
        rows=stackup_layers(self.frame.w.context);resize_rows(self.stack_grid,len(rows))
        for i,r in enumerate(rows):
            for j,key in enumerate(('name','type','material','thickness','epsilon_r','loss_tangent')):self.stack_grid.SetCellValue(i,j,r.get(key,''));self.stack_grid.SetReadOnly(i,j)
        if not rows:info(self,'No explicit stackup is stored in the saved board.')
    def _review(self,book):
        p=wx.Panel(book);book.AddPage(p,'Local review history');s=wx.BoxSizer(wx.VERTICAL);p.SetSizer(s)
        s.Add(text(p,'Content-bound review records',True,12),0,wx.ALL,14)
        s.Add(text(p,'These are local, self-attested records — not authenticated approval, native DRC certification, or a shared-team database.'),0,wx.ALL,14)
        grid=wx.FlexGridSizer(cols=2,vgap=10,hgap=12);grid.AddGrowableCol(1,1);s.Add(grid,0,wx.EXPAND|wx.ALL,14)
        self.reviewer=wx.TextCtrl(p);self.rationale=wx.TextCtrl(p);self.review_status=wx.ComboBox(p,choices=['draft','reviewed','approved','rejected'],style=wx.CB_READONLY);self.review_status.SetSelection(1)
        for label,ctrl in [('Reviewer',self.reviewer),('Rationale / change request',self.rationale),('Local status',self.review_status)]:grid.Add(text(p,label),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(ctrl,1,wx.EXPAND)
        s.Add(btn(p,'Record local review',self.record),0,wx.ALL,14)
        self.review_log=wx.TextCtrl(p,style=wx.TE_MULTILINE|wx.TE_READONLY);s.Add(self.review_log,1,wx.EXPAND|wx.ALL,14)
    def refresh_review(self):
        if not hasattr(self,'review_log'):return
        self.review_log.ChangeValue('Current status: '+review_state(self.frame.w)+'\n\n'+json.dumps(self.frame.w.metadata.get('reviews',[]),indent=2))
    def record(self,event):
        try:
            self.frame.collect();trial=self.frame.w.clone();record_review(trial,self.reviewer.GetValue(),self.rationale.GetValue(),self.review_status.GetValue());self.frame.checkpoint();self.frame.w=trial;self.refresh_review();self.frame.workbench.refresh_table()
        except Exception as e:fail(self,e)


class ReportsPanel(wx.Panel):
    def __init__(self,parent,frame):
        super().__init__(parent);self.frame=frame;self.records=[];self.visible=[];self.report_info={}
        s=wx.BoxSizer(wx.VERTICAL);self.SetSizer(s)
        s.Add(text(self,'Native DRC evidence & cross-probing',True,14),0,wx.ALL,14)
        row=wx.BoxSizer(wx.HORIZONTAL);s.Add(row,0,wx.EXPAND|wx.ALL,12)
        row.Add(btn(self,'Import KiCad JSON report',self.import_report),0,wx.RIGHT,8);row.Add(btn(self,'Cross-probe selected violation',self.crossprobe),0,wx.RIGHT,8)
        self.search=wx.SearchCtrl(self);row.Add(self.search,1);self.search.Bind(wx.EVT_TEXT,lambda e:self.refresh())
        self.caption=text(self,'No native report loaded. Offline scope preview is not a native DRC result.');s.Add(self.caption,0,wx.ALL,12)
        self.grid=new_grid(self,[('Severity',95),('Section',145),('Check type',210),('Native description',750)]);self.grid.EnableEditing(False);s.Add(self.grid,1,wx.EXPAND|wx.ALL,12)
        self.detail=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,180));s.Add(self.detail,0,wx.EXPAND|wx.ALL,12)
        self.grid.Bind(gridlib.EVT_GRID_SELECT_CELL,self.select)
    def import_report(self,event):
        with wx.FileDialog(self,'Open native DRC report',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as d:
            if d.ShowModal()!=wx.ID_OK:return
            try:
                data=json.loads(pathlib.Path(d.GetPath()).read_text('utf-8-sig'))
                # Accept the plugin validation wrapper or native CLI JSON itself.
                if isinstance(data.get('data'),dict):data=data['data']
                elif isinstance(data.get('report'),dict):data=data['report']
                self.records=read_drc_report(data);self.report_info=data;self.caption.SetLabel('Imported: '+pathlib.Path(d.GetPath()).name+' — report may be stale; this does not validate the current staged edits.');self.refresh()
            except Exception as e:fail(self,e)
    def load_data(self,data,caption):
        self.records=read_drc_report(data);self.report_info=data;self.caption.SetLabel(caption+' — report is evidence for that snapshot only.');self.refresh()
    def refresh(self):
        query=self.search.GetValue().lower();self.visible=[r for r in self.records if query in json.dumps(r).lower()];resize_rows(self.grid,len(self.visible))
        for i,r in enumerate(self.visible):
            for j,key in enumerate(('severity','section','type','description')):self.grid.SetCellValue(i,j,str(r.get(key,'')))
    def select(self,event):
        row=event.GetRow()
        if row<len(self.visible):self.detail.ChangeValue(json.dumps(self.visible[row]['native_record'],indent=2))
        event.Skip()
    def crossprobe(self,event):
        row=self.grid.GetGridCursorRow()
        if not 0<=row<len(self.visible):return
        callback=getattr(self.frame,'native_probe',None)
        if not callback:info(self,'Launch the plugin from KiCad to cross-probe report UUIDs.');return
        ids=self.visible[row]['uuids']
        if not ids:info(self,'This native report entry has no item UUIDs.');return
        try:callback(ids)
        except Exception as e:fail(self,e)
