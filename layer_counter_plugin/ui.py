"""Native layer-counter setup and detached geometry preview."""
from pathlib import Path
import pcbnew
import wx
from . import core


class CounterPreview(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.preview=None;self.layer=None;self.glyphs=[]
        self.SetMinSize((440,380));self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))
        self.SetToolTip('All selected copper layers are overlaid in this diagram. The dashed rectangle is the zone-only keepout. Native copper text is mirrored on bottom when enabled.')

    def set_preview(self,preview):
        """Capture detached native glyph polygons once, retaining mirror and rotation."""
        glyphs=[]
        if preview is not None:
            for item in preview.items:
                if not isinstance(item,pcbnew.PCB_TEXT):continue
                shape=pcbnew.SHAPE_POLY_SET()
                item.TransformTextToPolySet(shape,0,pcbnew.FromMM(.001),pcbnew.ERROR_OUTSIDE)
                polygons=[]
                for index in range(shape.OutlineCount()):
                    rings=[]
                    for ring in [shape.COutline(index)]+[shape.CHole(index,hole) for hole in range(shape.HoleCount(index))]:
                        rings.append(tuple((pcbnew.ToMM(ring.CPoint(i).x),pcbnew.ToMM(ring.CPoint(i).y)) for i in range(ring.PointCount())))
                    polygons.append(tuple(rings))
                glyphs.append((item.GetLayer(),tuple(polygons)))
        self.glyphs=glyphs;self.preview=preview;self.Refresh()

    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('#f2f6f8'));dc.Clear()
        preview=self.preview
        if preview is None:
            dc.SetTextForeground('#455c69');dc.DrawText('Choose settings, then click Preview.',18,18);return
        left,top,right,bottom=preview.bounds
        width,height=self.GetClientSize()
        scale=min(max(1,width-70)/max(.01,right-left),max(1,height-70)/max(.01,bottom-top))
        def point(x,y):return round(width/2+(x-(left+right)/2)*scale),round(height/2+(y-(top+bottom)/2)*scale)
        palette=('#007e83','#b16b21','#6c50a0','#1e7c49','#b04358','#476b9d')
        layers=list(dict.fromkeys(entry['layer'] for entry in preview.labels))
        colours={layer:palette[index%len(palette)] for index,layer in enumerate(layers)}
        dc.SetPen(wx.Pen('#71828d',1,wx.PENSTYLE_SHORT_DASH));dc.SetBrush(wx.TRANSPARENT_BRUSH)
        a,b=point(left,top),point(right,bottom);dc.DrawRectangle(a[0],a[1],max(1,b[0]-a[0]),max(1,b[1]-a[1]))
        for keepout in getattr(preview,'keepouts',[]):
            if self.layer is not None and keepout['layer']!=self.layer:continue
            l,t,r,b=keepout['bounds'];a,z=point(l,t),point(r,b)
            dc.SetPen(wx.Pen(colours.get(keepout['layer'],'#71828d'),1,wx.PENSTYLE_SHORT_DASH))
            dc.DrawRectangle(a[0],a[1],max(1,z[0]-a[0]),max(1,z[1]-a[1]))
        for shape in preview.shapes:
            if self.layer is not None and shape['layer']!=self.layer:continue
            dc.SetPen(wx.Pen(colours[shape['layer']],max(1,round(shape['width']*scale))))
            if shape['kind']=='line':dc.DrawLine(*point(shape['x1'],shape['y1']),*point(shape['x2'],shape['y2']))
            elif shape['kind']=='circle':dc.DrawCircle(*point(shape['x'],shape['y']),max(1,round(shape['r']*scale)))
        gc=wx.GraphicsContext.Create(dc)
        if gc:
            gc.SetPen(wx.TRANSPARENT_PEN)
            for layer,polygons in self.glyphs:
                if self.layer is not None and layer!=self.layer:continue
                gc.SetBrush(wx.Brush(colours[layer]));path=gc.CreatePath()
                for rings in polygons:
                    for ring in rings:
                        if not ring:continue
                        path.MoveToPoint(*point(*ring[0]))
                        for vertex in ring[1:]:path.AddLineToPoint(*point(*vertex))
                        path.CloseSubpath()
                gc.DrawPath(path,wx.ODDEVEN_RULE)
            gc.Flush()
        dc.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT));dc.SetTextForeground('#455c69')
        dc.DrawText('Top board view - native copper glyphs and mirroring',12,height-24)



class LayerCounterFrame(wx.Frame):
    def __init__(self,parent,board,board_guard=None):
        super().__init__(parent,title='WayriCAD Layer Counter',size=(1040,740))
        self.board=board;self.board_guard=board_guard or (lambda:True)
        self.preview=None;self.undo_stack=[];self.redo_stack=[]
        settings=core.defaults(board,pcbnew)
        panel=wx.Panel(self);outer=wx.BoxSizer(wx.VERTICAL);body=wx.BoxSizer(wx.HORIZONTAL)
        controls=wx.ScrolledWindow(panel);controls.SetScrollRate(0,12);controls.SetMinSize((320,420))
        form=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(controls,label='Identify the physical copper layers')
        title.SetFont(title.GetFont().Bold());form.Add(title,0,wx.ALL,8)
        self.styles=list(core.STYLES)
        form.Add(wx.StaticText(controls,label='Counter style'),0,wx.LEFT|wx.TOP,8)
        self.style=wx.Choice(controls,choices=[core.STYLES[key] for key in self.styles])
        self.style.SetSelection(self.styles.index(settings['style']));form.Add(self.style,0,wx.EXPAND|wx.ALL,8)
        self.style.SetToolTip('Choose the shape of the identification pattern. Core styles use the explicit physical layer pairs below.')
        self.layers=core.copper_layers(board,pcbnew)
        form.Add(wx.StaticText(controls,label='Copper layers to include'),0,wx.LEFT,8)
        self.layer_list=wx.CheckListBox(controls,choices=[f'L{number} · {name}' for layer,name,number in self.layers],size=(-1,140))
        for index,(layer,_,_) in enumerate(self.layers):self.layer_list.Check(index,layer in settings['layers'])
        form.Add(self.layer_list,0,wx.EXPAND|wx.ALL,8)
        grid=wx.FlexGridSizer(cols=2,hgap=8,vgap=7);grid.AddGrowableCol(1)
        self.fields={}
        for key,label in [('x','X (mm)'),('y','Y (mm)'),('size','Text size (mm)'),('stroke','Stroke (mm)'),('pitch','Pitch (mm)'),('margin','Zone margin (mm)')]:
            grid.Add(wx.StaticText(controls,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            field=wx.TextCtrl(controls,value=str(settings[key]));self.fields[key]=field;grid.Add(field,1,wx.EXPAND)
            field.SetToolTip(f'{label}. Changes require a fresh preview before Add.')
            field.Bind(wx.EVT_TEXT,self.invalidate)
        form.Add(grid,0,wx.EXPAND|wx.ALL,8)
        self.mirror=wx.CheckBox(controls,label='Mirror bottom copper text');self.mirror.SetValue(settings['mirror_bottom'])
        form.Add(self.mirror,0,wx.ALL,8)
        form.Add(wx.StaticText(controls,label='Core pairs (physical layers)'),0,wx.LEFT,8)
        self.pairs=wx.TextCtrl(controls,value=settings['core_pairs']);form.Add(self.pairs,0,wx.EXPAND|wx.ALL,8)
        self.pairs.SetToolTip('Example: L1/L2,L3/L4. These are explicit pairs, not inferred core/prepreg material boundaries.')
        note=wx.StaticText(controls,label='Preview first, then Add. Close this window and\nmove the resulting group with KiCad M.\nCheck copper text and keepout with native DRC.')
        form.Add(note,0,wx.ALL,8);controls.SetSizer(form)
        self.canvas=CounterPreview(panel)
        view=wx.BoxSizer(wx.VERTICAL)
        self.view_layer=wx.Choice(panel,choices=['All selected layers']+[f'L{number} - {name}' for layer,name,number in self.layers])
        self.view_layer.SetSelection(0);self.view_layer.SetToolTip('Inspect one physical layer or overlay all selected layers.')
        def change_view(event):
            index=self.view_layer.GetSelection();self.canvas.layer=None if index==0 else self.layers[index-1][0];self.canvas.Refresh()
        self.view_layer.Bind(wx.EVT_CHOICE,change_view)
        view.Add(self.view_layer,0,wx.EXPAND|wx.BOTTOM,8);view.Add(self.canvas,1,wx.EXPAND)
        body.Add(controls,0,wx.EXPAND|wx.ALL,8);body.Add(view,1,wx.EXPAND|wx.ALL,8)
        outer.Add(body,1,wx.EXPAND)
        self.status=wx.StaticText(panel,label='Ready. No board changes.');outer.Add(self.status,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        buttons=wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button=wx.Button(panel,label='Preview');self.add_button=wx.Button(panel,label='Add counter')
        self.undo_button=wx.Button(panel,label='Undo');self.redo_button=wx.Button(panel,label='Redo')
        help_button=wx.Button(panel,label='Help');close=wx.Button(panel,label='Close')
        for button in (self.preview_button,self.add_button,self.undo_button,self.redo_button,help_button,close):buttons.Add(button,0,wx.ALL,5)
        outer.Add(buttons,0,wx.ALIGN_RIGHT|wx.RIGHT|wx.BOTTOM,8);panel.SetSizer(outer)
        self.style.Bind(wx.EVT_CHOICE,self.invalidate);self.layer_list.Bind(wx.EVT_CHECKLISTBOX,self.invalidate)
        self.mirror.Bind(wx.EVT_CHECKBOX,self.invalidate);self.pairs.Bind(wx.EVT_TEXT,self.invalidate)
        self.preview_button.Bind(wx.EVT_BUTTON,self.make_preview);self.add_button.Bind(wx.EVT_BUTTON,self.add)
        self.undo_button.Bind(wx.EVT_BUTTON,lambda event:self.history(False));self.redo_button.Bind(wx.EVT_BUTTON,lambda event:self.history(True))
        help_button.Bind(wx.EVT_BUTTON,self.help);close.Bind(wx.EVT_BUTTON,lambda event:self.Close())
        self.SetMinSize((850,620));self.update_buttons()

    def update_buttons(self):
        self.add_button.Enable(self.preview is not None);self.undo_button.Enable(bool(self.undo_stack));self.redo_button.Enable(bool(self.redo_stack))

    def invalidate(self,event=None):
        self.preview=None;self.canvas.set_preview(None);self.status.SetLabel('Settings changed. Preview again before Add.');self.update_buttons()
        if event:event.Skip()

    def guard(self):
        if not self.board_guard():raise ValueError('The originating board was closed or replaced. Reopen Layer Counter from that board.')

    def settings(self):
        values={key:float(field.GetValue()) for key,field in self.fields.items()}
        values.update(style=self.styles[self.style.GetSelection()],layers=[layer for index,(layer,_,_) in enumerate(self.layers) if self.layer_list.IsChecked(index)],mirror_bottom=self.mirror.GetValue(),core_pairs=self.pairs.GetValue().strip())
        return values

    def error(self,exc):wx.MessageBox(str(exc),'Layer Counter',wx.OK|wx.ICON_ERROR,parent=self)

    def make_preview(self,event=None):
        try:
            self.guard();self.preview=core.plan(self.board,pcbnew,self.settings());self.canvas.set_preview(self.preview)
            self.status.SetLabel(f'{len(self.preview.labels)} copper labels ready. Board unchanged.');self.update_buttons()
        except Exception as exc:self.invalidate();self.error(exc)

    def add(self,event=None):
        try:
            self.guard()
            if self.preview is None:raise ValueError('Preview the current settings first.')
            tx=core.apply(self.board,pcbnew,self.preview);self.undo_stack.append(tx);self.redo_stack.clear()
            self.invalidate();pcbnew.Refresh();self.status.SetLabel('Counter added. Close this window, then move its group with M.');self.update_buttons()
        except Exception as exc:self.error(exc)

    def history(self,redo):
        try:
            self.guard();source=self.redo_stack if redo else self.undo_stack;target=self.undo_stack if redo else self.redo_stack
            if not source:return
            tx=source[-1];(tx.redo if redo else tx.undo)();source.pop();target.append(tx)
            self.invalidate();pcbnew.Refresh();self.status.SetLabel('Counter redone.' if redo else 'Counter undone.');self.update_buttons()
        except Exception as exc:self.error(exc)

    def help(self,event=None):
        dialog=wx.Dialog(self,title='Layer Counter help',size=(720,570))
        box=wx.BoxSizer(wx.VERTICAL);text=wx.TextCtrl(dialog,value=Path(__file__).with_name('HELP.md').read_text(encoding='utf-8'),style=wx.TE_MULTILINE|wx.TE_READONLY|wx.TE_WORDWRAP)
        box.Add(text,1,wx.EXPAND|wx.ALL,12);box.Add(dialog.CreateButtonSizer(wx.OK),0,wx.ALIGN_RIGHT|wx.ALL,8);dialog.SetSizer(box)
        dialog.ShowModal();dialog.Destroy()
