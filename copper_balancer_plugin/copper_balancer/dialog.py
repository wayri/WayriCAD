"""Native, DPI-aware wxPython controls and an interactive PCB preview."""
import wx
import wx.lib.scrolledpanel
from .engine import Settings, SHAPES, MODES, LATTICES, Cancelled
from . import kicad_backend as backend

PRESETS = {
    "Fine thieving": dict(shape="Circle",size=.6,gap=.4,clearance=.4,edge_clearance=.8,mode=MODES[0]),
    "Standard thieving": dict(shape="Circle",size=1,gap=.5,clearance=.5,edge_clearance=1,mode=MODES[0]),
    "Square balancing": dict(shape="Square",size=1.2,gap=.4,clearance=.5,edge_clearance=1,mode=MODES[1],target=35),
    "Soft organic fill": dict(shape="Organic blob",size=1.8,gap=.5,clearance=.5,edge_clearance=1,mode=MODES[1],target=30),
    "Edge thieving": dict(shape="Hexagon",size=1.2,gap=.5,clearance=.5,edge_clearance=1,mode=MODES[2],band_width=5),
    "Angled bars": dict(shape="Bar",size=2,gap=.4,clearance=.5,edge_clearance=1,mode=MODES[0],rotation=45),
}


def label(parent,text,bold=False,size=None):
    control = wx.StaticText(parent,label=text)
    font = control.GetFont()
    if bold:
        font.SetWeight(wx.FONTWEIGHT_BOLD)
    if size:
        font.SetPointSize(size)
    control.SetFont(font)
    return control


class BoardCanvas(wx.Panel):
    def __init__(self,parent):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize(self.FromDIP((420,360)))
        self.preview = None
        self.heatmap = False
        self.stale = False
        self.scale = 1
        self.origin = [0,0]
        self.drag = None
        self.hover = None
        self.Bind(wx.EVT_PAINT,self.on_paint)
        self.Bind(wx.EVT_SIZE,lambda e: self.Refresh())
        self.Bind(wx.EVT_MOUSEWHEEL,self.on_zoom)
        self.Bind(wx.EVT_LEFT_DOWN,self.on_down)
        self.Bind(wx.EVT_LEFT_UP,self.on_up)
        self.Bind(wx.EVT_MOTION,self.on_motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e: setattr(self,"drag",None))
        self.Bind(wx.EVT_LEFT_DCLICK,lambda e: self.fit())
        self.SetToolTip("Scroll to zoom · drag to pan · double-click to fit. Density view: hover a tile for before / after coverage.")

    def set_preview(self,preview):
        self.preview = preview
        self.stale = False
        self.fit()

    def fit(self):
        if self.preview:
            points = [pt for outer in self.preview.outline for ring in outer for pt in ring]
            x0,y0 = min(p[0] for p in points),min(p[1] for p in points)
            x1,y1 = max(p[0] for p in points),max(p[1] for p in points)
            w,h = self.GetClientSize()
            self.scale = max(.01,min((w-64)/max(.01,x1-x0),(h-64)/max(.01,y1-y0)))
            self.origin = [(w-(x1-x0)*self.scale)/2-x0*self.scale,(h-(y1-y0)*self.scale)/2-y0*self.scale]
        self.Refresh()

    def screen(self,p):
        return p[0]*self.scale+self.origin[0],p[1]*self.scale+self.origin[1]

    def on_zoom(self,event):
        x,y = event.GetPosition()
        factor = 1.2 if event.GetWheelRotation()>0 else 1/1.2
        new = min(1500,max(.05,self.scale*factor))
        factor = new/self.scale
        self.origin = [x-(x-self.origin[0])*factor,y-(y-self.origin[1])*factor]
        self.scale = new
        self.Refresh()

    def on_down(self,event):
        self.drag = event.GetPosition()
        self.CaptureMouse()
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))

    def on_up(self,event):
        self.drag = None
        if self.HasCapture():
            self.ReleaseMouse()
        self.SetCursor(wx.NullCursor)

    def on_motion(self,event):
        p = event.GetPosition()
        if self.drag is not None and event.Dragging():
            self.origin[0] += p.x-self.drag.x
            self.origin[1] += p.y-self.drag.y
            self.drag = p
            self.Refresh()
        elif self.preview and self.heatmap:
            x,y = (p.x-self.origin[0])/self.scale,(p.y-self.origin[1])/self.scale
            self.hover = next((tile for tile in self.preview.plan.tiles.values() if tile.bounds[0]<=x<=tile.bounds[2] and tile.bounds[1]<=y<=tile.bounds[3]),None)
            self.Refresh()

    def draw_polygon(self,gc,rings,fill,stroke=None):
        path = gc.CreatePath()
        for ring in rings:
            if not ring:
                continue
            path.MoveToPoint(*self.screen(ring[0]))
            for point in ring[1:]:
                path.AddLineToPoint(*self.screen(point))
            path.CloseSubpath()
        gc.SetBrush(wx.Brush(fill))
        gc.SetPen(wx.Pen(stroke,1) if stroke else wx.TRANSPARENT_PEN)
        gc.DrawPath(path,wx.ODDEVEN_RULE)

    def on_paint(self,event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush("#ffffff"))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return
        font = self.GetFont()
        gc.SetFont(font,wx.Colour("#58636d"))
        w,h = self.GetClientSize()
        if self.preview is None:
            gc.SetFont(font.Bold().Larger(),wx.Colour("#273747"))
            gc.DrawText("A clear view before copper is added",32,h/2-48)
            gc.SetFont(font,wx.Colour("#58636d"))
            gc.DrawText("Choose a pattern and copper layers, then build a preview.",32,h/2-12)
            gc.DrawText("Board edges, existing copper and keepouts are checked automatically.",32,h/2+12)
            return
        for outer in self.preview.outline:
            self.draw_polygon(gc,outer,"#f4f6f8","#84909b")
        for outer in self.preview.allowed:
            self.draw_polygon(gc,outer,"#e5eee8")
        if self.heatmap:
            for tile in self.preview.plan.tiles.values():
                if tile.board_area <= 0:
                    continue
                t = min(1,tile.density/70)
                color = wx.Colour(int(35+200*t),int(155-75*t),int(170-105*t),95)
                x0,y0,x1,y1 = tile.bounds
                self.draw_polygon(gc,[[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]],color)
        for outer in self.preview.copper:
            self.draw_polygon(gc,outer,"#ba8748")
        for poly in self.preview.plan.shapes:
            self.draw_polygon(gc,[poly],"#259b7c" if not self.stale else "#607e79")
        gc.SetFont(font,wx.Colour("#273747"))
        gc.DrawText("Scroll to zoom  ·  Drag to pan  ·  Double-click to fit",16,h-28)
        if self.stale:
            gc.DrawText("SETTINGS CHANGED — rebuild preview to apply",16,14)
        elif self.heatmap and self.hover:
            cell = self.hover
            before = cell.existing_area/cell.board_area*100 if cell.board_area else 0
            gc.DrawText(f"Tile coverage  {before:.1f}% → {cell.density:.1f}%",16,14)
        else:
            gc.DrawText(self.preview.name + "  /  Top view",16,14)


class CopperBalancerDialog(wx.Dialog):
    def __init__(self,parent,board):
        super().__init__(parent,title="WayriCAD Copper Balancer",style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.board = board
        self.previews = []
        self.preview_settings = None
        self.preview_stamp = None
        self.layers = backend.copper_layers(board)
        self.controls = {}
        self.busy = False
        self.SetFont(wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT))
        self.build_ui()
        self.SetSize(self.FromDIP((1140,760)))
        self.SetMinSize(self.FromDIP((880,620)))
        display = wx.Display(self).GetClientArea()
        current = self.GetSize()
        self.SetSize((min(current.width,display.width-30),min(current.height,display.height-40)))
        self.CentreOnParent()
        self.Bind(wx.EVT_CLOSE,self.on_close)
        self.update_enabled()

    def build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        titles = wx.BoxSizer(wx.VERTICAL)
        titles.Add(label(self,"WayriCAD Copper Balancer",True,13),0,wx.BOTTOM,4)
        titles.Add(label(self,"Preview copper density, then apply."))
        header.Add(titles,1)
        badge = label(self,"",True,9)
        header.Add(badge,0,wx.ALIGN_CENTER_VERTICAL)
        root.Add(header,0,wx.EXPAND|wx.ALL,12)
        root.Add(wx.StaticLine(self),0,wx.EXPAND|wx.LEFT|wx.RIGHT,20)
        body = wx.BoxSizer(wx.HORIZONTAL)
        sidebar = wx.lib.scrolledpanel.ScrolledPanel(self,size=self.FromDIP((300,-1)),style=wx.TAB_TRAVERSAL)
        sidebar.SetMinSize(self.FromDIP((290,-1)))
        form = wx.BoxSizer(wx.VERTICAL)
        self.section(sidebar,form,"Pattern")
        preset = wx.Choice(sidebar,choices=list(PRESETS))
        preset.SetSelection(1)
        form.Add(preset,0,wx.EXPAND|wx.BOTTOM,12)
        preset.Bind(wx.EVT_CHOICE,self.on_preset)
        defaults = Settings()
        for key,title,choices in (("mode","Workflow",MODES),("shape","Shape",SHAPES),("lattice","Lattice",LATTICES)):
            form.Add(label(sidebar,title),0,wx.BOTTOM,4)
            c = wx.Choice(sidebar,choices=list(choices))
            c.SetStringSelection(getattr(defaults,key))
            self.controls[key] = c
            form.Add(c,0,wx.EXPAND|wx.BOTTOM,10)
            c.Bind(wx.EVT_CHOICE,self.on_change)
        self.section(sidebar,form,"Dimensions · mm")
        grid = wx.FlexGridSizer(cols=2,hgap=10,vgap=8)
        grid.AddGrowableCol(1)
        specs = (("size","Shape size",.2,20,.1),("gap","Minimum gap",.1,20,.1),
                 ("clearance","Copper clearance",.1,20,.1),("edge_clearance","Edge / cutout gap",.1,50,.1),
                 ("rotation","Rotation (°)",-180,180,5),("band_width","Edge band width",.2,100,.5),
                 ("target","Target density (%)",1,90,1),("tile_size","Density tile size",2,100,1))
        advanced = wx.CollapsiblePane(sidebar,label="Advanced geometry and density")
        advanced_panel = advanced.GetPane()
        advanced_grid = wx.FlexGridSizer(cols=2,hgap=10,vgap=8)
        advanced_grid.AddGrowableCol(1)
        for index,(key,title,lo,hi,step) in enumerate(specs):
            owner = sidebar if index < 4 else advanced_panel
            target_grid = grid if index < 4 else advanced_grid
            target_grid.Add(label(owner,title),0,wx.ALIGN_CENTER_VERTICAL)
            c = wx.SpinCtrlDouble(owner,min=lo,max=hi,initial=getattr(defaults,key),inc=step,size=self.FromDIP((104,-1)))
            c.SetDigits(2 if step < 1 else 0)
            self.controls[key] = c
            target_grid.Add(c,1,wx.EXPAND)
            c.Bind(wx.EVT_SPINCTRLDOUBLE,self.on_change)
            c.Bind(wx.EVT_TEXT,self.on_change)
        self.controls["size"].SetToolTip("Diameter for circles, hexagons, octagons and blobs; side for squares; length for bars (width = length / 3).")
        self.controls["gap"].SetToolTip("Guaranteed minimum separation, also constrained by board and default netclass clearance. Conservative circular envelopes set the actual lattice pitch.")
        self.controls["clearance"].SetToolTip("At least this gap to copper. Larger board, netclass and item clearances are also respected. Run KiCad DRC for custom rules.")
        form.Add(grid,0,wx.EXPAND|wx.BOTTOM,8)
        advanced_panel.SetSizer(advanced_grid)
        advanced.Collapse(True)
        advanced.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda e: (sidebar.Layout(), sidebar.SetupScrolling(scroll_x=False)))
        form.Add(advanced,0,wx.EXPAND|wx.BOTTOM,8)
        self.section(sidebar,form,"Layers and region")
        self.layer_check = wx.CheckListBox(sidebar,choices=[name for _,name in self.layers],size=self.FromDIP((-1,88)))
        self.layer_check.Check(0)
        self.layer_check.Bind(wx.EVT_CHECKLISTBOX,self.on_change)
        form.Add(self.layer_check,0,wx.EXPAND|wx.BOTTOM,10)
        self.region_choice = wx.Choice(sidebar,choices=["Entire board","Selected items bounds","Manual rectangle"])
        self.region_choice.SetSelection(0)
        self.region_choice.Bind(wx.EVT_CHOICE,self.on_change)
        form.Add(self.region_choice,0,wx.EXPAND|wx.BOTTOM,10)
        region_grid = wx.FlexGridSizer(cols=4,hgap=5,vgap=6)
        self.region_fields = []
        for title,value in (("X",0),("Y",0),("W",50),("H",50)):
            region_grid.Add(label(sidebar,title),0,wx.ALIGN_CENTER_VERTICAL)
            c = wx.TextCtrl(sidebar,value=str(value),size=self.FromDIP((68,-1)))
            c.Bind(wx.EVT_TEXT,self.on_change)
            self.region_fields.append(c)
            region_grid.Add(c)
        self.region_grid = region_grid
        self.region_form = form
        form.Add(region_grid,0,wx.BOTTOM,12)
        self.replace_check = wx.CheckBox(sidebar,label="Replace previous WayriCAD copper fill")
        self.replace_check.SetValue(True)
        self.replace_check.Bind(wx.EVT_CHECKBOX,self.on_change)
        form.Add(self.replace_check,0,wx.BOTTOM,12)
        limit_row = wx.BoxSizer(wx.HORIZONTAL)
        limit_row.Add(label(sidebar,"Limit per layer"),1,wx.ALIGN_CENTER_VERTICAL)
        self.limit = wx.SpinCtrl(sidebar,min=1,max=50000,initial=12000,size=self.FromDIP((104,-1)))
        self.limit.Bind(wx.EVT_SPINCTRL,self.on_change)
        self.limit.Bind(wx.EVT_TEXT,self.on_change)
        limit_row.Add(self.limit)
        form.Add(limit_row,0,wx.EXPAND|wx.BOTTOM,14)
        note = label(sidebar,"Each shape gets its own unique WayriCAD copper net, named by layer. Remove or replace checked layers anytime. No solder mask openings. Refill zones and run DRC after applying.")
        note.Wrap(self.FromDIP(266))
        form.Add(note,0,wx.EXPAND|wx.BOTTOM,14)
        sidebar.SetSizer(form)
        sidebar.SetupScrolling(scroll_x=False)
        body.Add(sidebar,0,wx.EXPAND|wx.RIGHT,18)
        right = wx.BoxSizer(wx.VERTICAL)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        toolbar.Add(label(self,"BOARD PREVIEW",True,10),1,wx.ALIGN_CENTER_VERTICAL)
        self.preview_layer = wx.Choice(self,choices=["No preview"])
        self.preview_layer.SetSelection(0)
        self.preview_layer.Bind(wx.EVT_CHOICE,self.on_preview_layer)
        toolbar.Add(self.preview_layer,0,wx.RIGHT,8)
        self.heat = wx.CheckBox(self,label="Density map")
        self.heat.Bind(wx.EVT_CHECKBOX,self.on_heat)
        toolbar.Add(self.heat,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        fit = wx.Button(self,label="Fit",size=self.FromDIP((45,-1)))
        fit.Bind(wx.EVT_BUTTON,lambda e: self.canvas.fit())
        toolbar.Add(fit)
        right.Add(toolbar,0,wx.EXPAND|wx.BOTTOM,10)
        self.canvas = BoardCanvas(self)
        right.Add(self.canvas,1,wx.EXPAND)
        legend = wx.BoxSizer(wx.HORIZONTAL)
        for color,text in (("#ba8748","Existing copper"),("#259b7c","Proposed fill"),("#607d81","Available space")):
            swatch = wx.Panel(self,size=self.FromDIP((10,10)))
            swatch.SetBackgroundColour(color)
            legend.Add(swatch,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5)
            legend.Add(label(self,text),0,wx.RIGHT,16)
        right.Add(legend,0,wx.TOP|wx.BOTTOM,10)
        metrics = wx.BoxSizer(wx.HORIZONTAL)
        self.stats = []
        for name in ("NEW SHAPES","ADDED COPPER","COVERAGE BEFORE → AFTER"):
            box = wx.BoxSizer(wx.VERTICAL)
            value = label(self,"—",True,18)
            self.stats.append(value)
            box.Add(value,0,wx.BOTTOM,4)
            box.Add(label(self,name,False,8))
            metrics.Add(box,1,wx.RIGHT,8)
        right.Add(metrics,0,wx.EXPAND|wx.TOP|wx.BOTTOM,8)
        self.status = wx.TextCtrl(self,value="Ready. Choose settings, then build a preview.",style=wx.TE_MULTILINE|wx.TE_READONLY|wx.BORDER_NONE,size=self.FromDIP((-1,60)))
        right.Add(self.status,0,wx.EXPAND|wx.TOP,8)
        body.Add(right,1,wx.EXPAND)
        root.Add(body,1,wx.EXPAND|wx.ALL,12)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        remove = wx.Button(self,label="Remove generated fill…")
        remove.Bind(wx.EVT_BUTTON,self.on_remove)
        footer.Add(remove)
        footer.AddStretchSpacer()
        cancel = wx.Button(self,wx.ID_CANCEL,"Close")
        footer.Add(cancel,0,wx.RIGHT,8)
        self.preview_button = wx.Button(self,label="Preview")
        self.preview_button.Bind(wx.EVT_BUTTON,self.on_preview)
        footer.Add(self.preview_button,0,wx.RIGHT,8)
        self.apply_button = wx.Button(self,label="Apply")
        self.apply_button.Enable(False)
        self.apply_button.Bind(wx.EVT_BUTTON,self.on_apply)
        self.preview_button.SetDefault()
        footer.Add(self.apply_button)
        root.Add(footer,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.SetSizer(root)

    def section(self,parent,sizer,text):
        sizer.Add(label(parent,text,True,9),0,wx.TOP|wx.BOTTOM,10)

    def update_enabled(self):
        mode = self.controls["mode"].GetStringSelection()
        for key in ("target","tile_size"):
            self.controls[key].Enable(mode == MODES[1] or key == "tile_size")
        self.controls["band_width"].Enable(mode == MODES[2])
        self.region_form.Show(self.region_grid, self.region_choice.GetSelection()==2, recursive=True)
        for field in self.region_fields:
            field.Enable(self.region_choice.GetSelection()==2)
        self.Layout()

    def on_change(self,event):
        self.apply_button.Enable(False)
        self.canvas.stale = bool(self.previews)
        self.canvas.Refresh()
        self.update_enabled()
        if self.previews:
            self.status.SetValue("Settings changed. Build a fresh preview to apply these settings.")
        event.Skip()

    def on_preset(self,event):
        values = PRESETS[event.GetString()]
        # Reset all pattern fields so switching presets never inherits an old angle.
        defaults = Settings()
        for key,control in self.controls.items():
            value = values.get(key,getattr(defaults,key))
            if isinstance(control,wx.Choice):
                control.SetStringSelection(value)
            else:
                control.SetValue(value)
        self.on_change(event)

    def read_settings(self):
        values = {key:(control.GetStringSelection() if isinstance(control,wx.Choice) else control.GetValue()) for key,control in self.controls.items()}
        region = None
        if self.region_choice.GetSelection()==1:
            region = backend.selected_bounds(self.board)
        elif self.region_choice.GetSelection()==2:
            try:
                x,y,w,h = [float(c.GetValue()) for c in self.region_fields]
            except ValueError:
                raise ValueError("Enter numeric X, Y, width, and height in millimetres.")
            region = (x,y,x+w,y+h)
        settings = Settings(**values,region=region,replace=self.replace_check.GetValue(),max_shapes=self.limit.GetValue())
        settings.validate()
        layers = [self.layers[i][0] for i in self.layer_check.GetCheckedItems()]
        if not layers:
            raise ValueError("Select at least one copper layer.")
        return settings,layers

    def on_preview(self,event):
        progress = None
        try:
            settings,layers = self.read_settings()
            self.apply_button.Enable(False)
            self.busy = True
            progress = wx.ProgressDialog("WayriCAD Copper Balancer","Reading board geometry…",maximum=1000,parent=self,
                                         style=wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_AUTO_HIDE|wx.PD_ELAPSED_TIME)
            def update(fraction,message):
                return progress.Update(min(999,int(fraction*1000)),message)[0]
            previews,warnings = backend.build_preview(self.board,layers,settings,update)
            self.previews,self.preview_settings = previews,settings
            self.preview_stamp = backend.review_stamp(self.board)
            self.preview_layer.SetItems([p.name for p in previews])
            self.preview_layer.SetSelection(0)
            self.on_preview_layer(None)
            count = sum(len(p.plan.shapes) for p in previews)
            messages = [f"{count:,} shapes / unique nets ready on {len(previews)} layer(s). Copper gaps ≥ {max(p.clearance for p in previews):g} mm; edge gaps ≥ {max(p.edge_clearance for p in previews):g} mm."]
            if any(p.plan.limited for p in previews):
                messages.append("Shape limit reached. Increase the limit or narrow the region for more coverage.")
            if settings.mode == MODES[1]:
                messages.append("The target is a per-tile ceiling. Obstacles, existing copper and shape spacing may keep coverage below it.")
            if count == 0:
                messages.append("No fill fits. Reduce shape size, adjust the region, or check zone coverage and clearances.")
            for preview in previews:
                d = preview.plan.diagnostics(settings.target)
                reasons = ', '.join(f"{k.replace('_',' ')}: {v}" for k,v in d['rejections'].items())
                messages.append(f"{preview.name}: {preview.plan.candidates} sites; {reasons}. Tile density {d['minimum_density']:.1f}–{d['maximum_density']:.1f}%; {d['tiles_below_target']}/{d['tiles']} below target; deficit {d['deficit_area_mm2']:.2f} mm².")
                if d['tiles_initially_above_target']:
                    messages.append(f"{d['tiles_initially_above_target']} tile(s) already exceed the target. Existing copper is preserved.")
            messages.extend(warnings)
            self.status.SetValue("\n".join(messages))
            self.apply_button.Enable(count>0)
        except Cancelled:
            self.canvas.stale = bool(self.previews)
            self.canvas.Refresh()
            self.status.SetValue("Preview cancelled. The PCB has not been changed.")
        except Exception as exc:
            self.canvas.stale = bool(self.previews)
            self.canvas.Refresh()
            self.error(exc)
        finally:
            self.busy = False
            if progress:
                progress.Destroy()

    def on_preview_layer(self,event):
        index = self.preview_layer.GetSelection()
        if 0 <= index < len(self.previews):
            preview = self.previews[index]
            was_stale = self.canvas.stale
            self.canvas.set_preview(preview)
            self.canvas.stale = was_stale if event else False
            plan = preview.plan
            self.stats[0].SetLabel(f"{len(plan.shapes):,}")
            self.stats[1].SetLabel(f"{plan.added_area:,.1f} mm²")
            before = plan.existing_area/plan.board_area*100 if plan.board_area else 0
            self.stats[2].SetLabel(f"{before:.1f}% → {plan.density:.1f}%")
            self.Layout()

    def on_heat(self,event):
        self.canvas.heatmap = self.heat.GetValue()
        self.canvas.Refresh()

    def on_apply(self,event):
        try:
            settings,layers = self.read_settings()
            if settings != self.preview_settings or layers != [p.layer for p in self.previews] or backend.review_stamp(self.board) != self.preview_stamp:
                self.apply_button.Enable(False)
                raise ValueError("Settings or board state changed. Build a new preview before applying.")
            self.finish_edits(lambda: backend.apply_preview(self.board,self.previews,settings))
        except Exception as exc:
            self.error(exc)

    def on_remove(self,event):
        try:
            layers = [self.layers[i][0] for i in self.layer_check.GetCheckedItems()]
            items = backend.managed_items(self.board,layers)
            count = len(items)
            if not count:
                self.status.SetValue("No WayriCAD copper fill exists on the checked layers.")
                return
            names = ", ".join(self.board.GetLayerName(l) for l in layers)
            if wx.MessageBox(f"Remove {count:,} generated shapes on {names}?\n\nTheir unused WayriCAD copper nets will also be removed. Other layers and circuit nets are preserved.", "Remove WayriCAD copper fill",wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION,self) == wx.YES:
                self.finish_edits(lambda: backend.remove_generated(self.board,layers))
        except Exception as exc:
            self.error(exc)

    def finish_edits(self, operation):
        """The desktop host saves only a new copy; native actions use host history."""
        if getattr(self,"save_result",None):
            if not self.save_result(operation):
                self.status.SetValue("Save cancelled. Preview is unchanged; choose Save balanced copy to continue.")
                return
        else:
            operation()
        self.EndModal(wx.ID_OK)

    def error(self,exc):
        self.apply_button.Enable(False)
        self.canvas.stale = bool(self.previews)
        self.canvas.Refresh()
        self.status.SetValue(str(exc))
        wx.MessageBox(str(exc),"WayriCAD Copper Balancer",wx.OK|wx.ICON_ERROR,self)

    def on_close(self,event):
        if self.busy:
            event.Veto()
        else:
            event.Skip()
