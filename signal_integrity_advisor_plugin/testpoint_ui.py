"""Compact live test-point editing, explicit preview then grouped apply."""
import wx
import wx.grid
from .testpoint_labels import LiveTestPoints,make_plan,native_records,table_layout


from .preview_kit import PanZoomCanvas,add_zoom_toolbar

class LabelPreview(PanZoomCanvas):
    def __init__(self,parent):
        super().__init__(parent,'Load and review test points to inspect names at their existing positions.');self.rows=[];self.cells=[]
        self.set_legend([('#bc9650','Pads'),('#397990','Proposed values'),('#4a8c45','Set table')])
    def show(self,rows,cells):self.rows=rows;self.cells=cells;self.fit();self.Refresh()
    def scene_bounds(self):
        points=[]
        for r in self.rows:
            points.extend([(r['x_mm']-1,-r['y_mm']-1),(r['x_mm']+1,-r['y_mm']+1),(r.get('label_x_mm',r['x_mm']),-r.get('label_y_mm',r['y_mm']))])
        for c in self.cells:points.extend([(c['x_mm'],-c['y_mm']),(c['x_mm']+len(c['text'])*c['size_mm'],-c['y_mm']-c['size_mm'])])
        if not points:return None
        x,y=zip(*points);return min(x)-2,min(y)-2,max(x)+2,max(y)+2
    def draw_scene(self,gc,project):
        for row in self.rows:
            gc.SetPen(wx.Pen('#8b7448',1));gc.SetBrush(wx.Brush('#d2b56c'))
            for px,py,pw,ph in row.get('pads',[(row['x_mm'],row['y_mm'],1,1)]):
                x,y=project((px,-py));gc.DrawEllipse(x-pw*self.scale/2,y-ph*self.scale/2,pw*self.scale,ph*self.scale)
            x,y=project((row.get('label_x_mm',row['x_mm']),-row.get('label_y_mm',row['y_mm'])))
            size=max(.5,row.get('label_size_mm',1))*self.scale;font=wx.Font(wx.FontInfo(10));font.SetPixelSize((0,max(6,round(size))))
            gc.SetFont(font,wx.Colour('#bd5b36' if row['reason'] else '#397990'));tw,th=gc.GetTextExtent(row['proposed']);gc.DrawText(row['proposed'],x-tw/2,y-th/2)
            px,py=project((row['x_mm'],-row['y_mm']));gc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT),wx.Colour('#536170'));gc.DrawText(row['reference'],px+5,py+8)
        for cell in self.cells:
            x,y=project((cell['x_mm'],-cell['y_mm']));font=wx.Font(wx.FontInfo(10));font.SetPixelSize((0,max(6,round(cell['size_mm']*self.scale))));gc.SetFont(font,wx.Colour('#4a8c45'));gc.DrawText(cell['text'],x,y)


class TestPointLabelsPanel(wx.Panel):
    def __init__(self,parent,board,saved_board=False):
        super().__init__(parent);self.board=board;self.live=None;self.stamp=None;self.rows=[];self.cells=[]
        root=wx.BoxSizer(wx.VERTICAL);form=wx.BoxSizer(wx.HORIZONTAL)
        self.pattern=wx.TextCtrl(self,value='TP*',size=(90,-1));self.template=wx.TextCtrl(self,value='{net}',size=(190,-1))
        self.silk=wx.CheckBox(self,label='Show values on silkscreen');self.add_table=wx.CheckBox(self,label='Add set table');self.side=wx.Choice(self,choices=['Front','Back']);self.side.SetSelection(0)
        for label,control in [('References',self.pattern),('Value template',self.template)]:form.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5);form.Add(control,0,wx.RIGHT,12)
        root.Add(form,0,wx.ALL|wx.EXPAND,10)
        advanced=wx.CollapsiblePane(self,label='Silkscreen and table options');host=advanced.GetPane();details=wx.BoxSizer(wx.VERTICAL);options=wx.BoxSizer(wx.HORIZONTAL)
        for control in (self.silk,self.add_table,self.side):control.Reparent(host);options.Add(control,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
        details.Add(options,0,wx.ALL,8)
        coords=wx.BoxSizer(wx.HORIZONTAL);self.x=wx.TextCtrl(host,value='0',size=(75,-1));self.y=wx.TextCtrl(host,value='0',size=(75,-1));self.size=wx.TextCtrl(host,value='1',size=(65,-1))
        for label,control in [('Table X (mm)',self.x),('Y (mm)',self.y),('Text size (mm)',self.size)]:coords.Add(wx.StaticText(host,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5);coords.Add(control,0,wx.RIGHT,12)
        note=wx.StaticText(host,label='Review grid cells to override labels. Table and labels need silkscreen clearance review in KiCad.');coords.Add(note,1,wx.ALIGN_CENTER_VERTICAL);details.Add(coords,0,wx.EXPAND|wx.ALL,8);host.SetSizer(details);root.Add(advanced,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10);advanced.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:self.Layout())
        split=wx.SplitterWindow(self);self.grid=wx.grid.Grid(split);self.grid.CreateGrid(0,5)
        for i,label in enumerate(('Reference','Net','Current value','Proposed value','Excluded / reason')):self.grid.SetColLabelValue(i,label);self.grid.SetColSize(i,135 if i<4 else 220)
        preview_host=wx.Panel(split);preview_box=wx.BoxSizer(wx.VERTICAL);self.preview=LabelPreview(preview_host);preview_box.Add(self.preview,1,wx.EXPAND);add_zoom_toolbar(preview_host,self.preview,preview_box);preview_host.SetSizer(preview_box);split.SplitVertically(self.grid,preview_host,620);root.Add(split,1,wx.EXPAND|wx.ALL,10)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.refresh=wx.Button(self,label='1 · Load test points');self.review=wx.Button(self,label='2 · Review changes');self.apply=wx.Button(self,label='3 · Apply to editor');self.undo_button=wx.Button(self,label='Undo last apply')
        for button,handler in ((self.refresh,self.load),(self.review,self.review_changes),(self.apply,self.apply_changes),(self.undo_button,self.undo)):
            footer.Add(button,0,wx.RIGHT,8);button.Bind(wx.EVT_BUTTON,handler)
        self.apply.Disable();self.undo_button.Disable();root.Add(footer,0,wx.ALL,10)
        self.status=wx.StaticText(self,label='Load uses the originating editor when available. Standalone saved-board previews cannot apply.');root.Add(self.status,0,wx.EXPAND|wx.ALL,10);self.SetSizer(root)
        for c in (self.pattern,self.template,self.x,self.y,self.size):c.Bind(wx.EVT_TEXT,self.invalidate)
        for c in (self.silk,self.add_table):c.Bind(wx.EVT_CHECKBOX,self.invalidate)
        self.side.Bind(wx.EVT_CHOICE,self.invalidate);self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED,self.invalidate)

    def invalidate(self,event=None):
        self.apply.Disable();self.stamp=None
        if event:event.Skip()

    def load(self,event=None):
        self.invalidate();self.live=None
        try:
            self.live=LiveTestPoints(self.board.GetFileName());stamp,self.records,_=self.live.snapshot();message='Live originating editor connected.'
        except Exception as exc:
            self.records=native_records(self.board);message='Saved-board preview only: '+str(exc)
        try:
            self.rows=make_plan(self.records,self.pattern.GetValue(),self.template.GetValue());self.loaded_template=self.template.GetValue();self.populate();self.preview.show(self.rows,[]);self.status.SetLabel(message)
        except Exception as exc:self.error(exc)

    def populate(self):
        if self.grid.GetNumberRows():self.grid.DeleteRows(0,self.grid.GetNumberRows())
        if self.rows:self.grid.AppendRows(len(self.rows))
        for i,r in enumerate(self.rows):
            for j,key in enumerate(('reference','net','value','proposed','reason')):self.grid.SetCellValue(i,j,str(r[key]));self.grid.SetReadOnly(i,j,j!=3)

    def review_changes(self,event=None):
        self.grid.SaveEditControlValue();self.grid.HideCellEditControl()
        self.invalidate()
        try:
            if not hasattr(self,'records'):raise ValueError('Load test points first.')
            overrides={r['id']:self.grid.GetCellValue(i,3) for i,r in enumerate(self.rows)} if self.template.GetValue()==self.loaded_template else {}
            if self.live:
                stamp,records,_=self.live.snapshot()
                if records!=self.records:raise ValueError('Board changed since loading. Load test points and review again.')
            else:stamp=None
            self.rows=make_plan(self.records,self.pattern.GetValue(),self.template.GetValue(),overrides)
            self.cells=table_layout(self.rows,float(self.x.GetValue()),float(self.y.GetValue()),float(self.size.GetValue())) if self.add_table.GetValue() else []
            self.loaded_template=self.template.GetValue();self.populate();self.preview.show(self.rows,self.cells);self.stamp=stamp
            valid=sum(not r['reason'] for r in self.rows);self.apply.Enable(bool(self.live and valid))
            self.status.SetLabel(f'Reviewed {valid} test points; {len(self.rows)-valid} excluded; {len(self.cells)//2} table rows. Existing value positions are retained.')
        except Exception as exc:self.error(exc)

    def apply_changes(self,event=None):
        try:
            if self.stamp is None or self.live is None:raise ValueError('Review a live editor snapshot first.')
            count,items=self.live.apply(self.stamp,self.rows,silk=self.silk.GetValue(),table=self.cells,back=self.side.GetSelection()==1)
            self.undo_button.Enable();self.invalidate();self.status.SetLabel(f'Updated {count} values and added {items} table text cells. KiCad Undo or Undo last apply reverses the operation. Save only after visual/DRC review.')
        except Exception as exc:self.error(exc)

    def undo(self,event=None):
        try:self.live.undo();self.undo_button.Disable();self.invalidate();self.status.SetLabel('Last test point operation reversed. Reload to continue.')
        except Exception as exc:self.error(exc)

    def error(self,exc):
        from wayricad_runtime.context import redact_error
        message=redact_error(exc);self.status.SetLabel(message);wx.MessageBox(message,'Test point labels',wx.OK|wx.ICON_ERROR,self)
