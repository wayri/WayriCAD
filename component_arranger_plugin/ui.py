"""Guided grouping, anchor and side-by-side native placement review."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import webbrowser

import pcbnew as api
import wx
import wx.lib.scrolledpanel

from . import engine, grouping, native


class PlacementCanvas(wx.Panel):
    """Cached geometry only: no native board reads during painting."""
    def __init__(self, parent, on_pick):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((280, 180))
        self.models = (); self.before = (); self.area = None;self.net_edges=()
        self.side = 'both'; self.focus = ''; self.groups = {}; self.hits = []
        self.scale = 1.; self.offset = (0., 0.); self.drag = None
        self.on_pick = on_pick
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL, self.wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.down)
        self.Bind(wx.EVT_LEFT_UP, self.up)
        self.Bind(wx.EVT_MOTION, self.motion)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda e: self.fit())
        self.SetToolTip('Wheel: zoom. Drag: pan. Double-click: fit. Click a courtyard to choose the anchor. Dashed outlines: original. Solid: proposal. Shaded area: allowed placement region.')

    def fit(self):
        self.scale = 1.; self.offset = (0., 0.); self.Refresh()

    def set_models(self, models, external=()):
        self.models=tuple(models);nets={}
        for f in self.models:
            for pad in f.pads:
                if pad.net:nets.setdefault(pad.net,[]).append(engine.transform((pad.x,pad.y),f))
        for pad in external:
            if pad.net:nets.setdefault(pad.net,[]).append((pad.x,pad.y))
        self.net_edges=tuple(edge for points in nets.values() for edge in engine._mst(sorted(set(points))))
        self.Refresh()

    def wheel(self, event):
        self.scale = min(30., max(.2, self.scale * (1.2 if event.GetWheelRotation() > 0 else 1/1.2)))
        self.Refresh()

    def down(self, event):
        self.drag = (event.GetPosition(), self.offset)
        self.CaptureMouse()

    def motion(self, event):
        if self.drag and event.Dragging():
            p, start = self.drag
            self.offset = (start[0] + event.GetX()-p.x, start[1] + event.GetY()-p.y)
            self.Refresh()
        else:
            ref = next((ref for box, ref in self.hits if box.Contains(event.GetPosition())), '')
            if ref:
                self.SetToolTip(ref + ' — click to use as anchor; pads and courtyard are measured from the native footprint.')

    def up(self, event):
        if self.HasCapture(): self.ReleaseMouse()
        if self.drag and abs(event.GetX()-self.drag[0].x)+abs(event.GetY()-self.drag[0].y) < 4:
            ref = next((ref for box, ref in reversed(self.hits) if box.Contains(event.GetPosition())), '')
            if ref: self.on_pick(ref)
        self.drag = None

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self); dc.SetBackground(wx.Brush('#152a36')); dc.Clear()
        self.hits = []
        if not self.models:
            dc.SetTextForeground('#e1ebef'); dc.DrawText('Choose a group, confirm its anchor, then Preview.', 20, 20); return
        polys = [p for f in self.models for p in engine.world_courtyards(f)]
        points = [p for poly in polys for p in poly]
        if self.area:
            l,t,r,b = self.area; points += [(l,t),(r,b)]
        l,t = min(p[0] for p in points),min(p[1] for p in points)
        r,b = max(p[0] for p in points),max(p[1] for p in points)
        width,height = self.GetClientSize()
        scale = min(max(1,width-80)/max(1,r-l),max(1,height-80)/max(1,b-t))*self.scale
        def pt(p): return wx.Point(round(width/2+(p[0]-(l+r)/2)*scale+self.offset[0]),round(height/2+(p[1]-(t+b)/2)*scale+self.offset[1]))
        if self.area:
            al,at,ar,ab = self.area; a,z = pt((al,at)),pt((ar,ab))
            dc.SetPen(wx.Pen('#5d9fa2',2,wx.PENSTYLE_SHORT_DASH));dc.SetBrush(wx.Brush('#203e49'))
            dc.DrawRectangle(a.x,a.y,max(1,z.x-a.x),max(1,z.y-a.y))
        for f in self.before:
            if self.side != 'both' and f.side != self.side: continue
            dc.SetPen(wx.Pen('#ac9568',1,wx.PENSTYLE_SHORT_DASH));dc.SetBrush(wx.TRANSPARENT_BRUSH)
            for poly in engine.world_courtyards(f): dc.DrawPolygon([pt(p) for p in poly])
        dc.SetPen(wx.Pen('#617b88',1))
        for a,z,_ in self.net_edges:dc.DrawLine(pt(a),pt(z))
        palette = ('#47cfb4','#e5aa64','#a89be9','#70badb','#e48fbc')
        for f in self.models:
            if self.side != 'both' and f.side != self.side: continue
            colour = palette[sum(map(ord,self.groups.get(f.reference,'A')))%len(palette)]
            dc.SetPen(wx.Pen('#ffffff' if f.reference==self.focus else colour,3 if f.reference==self.focus else 1))
            dc.SetBrush(wx.Brush('#1e4d50' if f.side=='top' else '#3b3754'))
            for poly in engine.world_courtyards(f):
                screen=[pt(p) for p in poly]; dc.DrawPolygon(screen)
                xs,ys=[p.x for p in screen],[p.y for p in screen]
                self.hits.append((wx.Rect(min(xs),min(ys),max(3,max(xs)-min(xs)),max(3,max(ys)-min(ys))),f.reference))
            for pad in f.pads:
                dc.SetPen(wx.TRANSPARENT_PEN);dc.SetBrush(wx.Brush('#e8cc84'));dc.DrawCircle(pt(engine.transform((pad.x,pad.y),f)),2)
            dc.SetTextForeground(colour); dc.DrawText(self.groups.get(f.reference,'')+' '+f.reference+(' [B]' if f.side=='bottom' else ''),pt((f.x,f.y)))
        dc.SetTextForeground('#e1ebef');dc.DrawText('Solid: proposed  |  Dashed: original  |  Shaded: placement area  |  XY ratsnest proxy',12,12)


class ArrangerFrame(wx.Frame):
    def __init__(self,parent,board,board_guard=None):
        super().__init__(parent,title='WayriCAD Component Arranger',size=(1360,900))
        self.board=board;self.board_guard=board_guard or (lambda: True)
        self.plan=None;self.transaction=None;self.clusters=[];self.loading=False;self.busy=False
        self.models={};self.refs=sorted(fp.GetReference() for fp in board.GetFootprints())
        panel=wx.Panel(self);layout=wx.BoxSizer(wx.VERTICAL)
        self.settings_splitter=wx.SplitterWindow(panel,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        right_panel=wx.Panel(self.settings_splitter)
        left=wx.lib.scrolledpanel.ScrolledPanel(self.settings_splitter,size=(350,-1));self.settings_panel=left;left.SetMinSize((260,120));controls=wx.BoxSizer(wx.VERTICAL)
        def label(text): controls.Add(wx.StaticText(left,label=text),0,wx.TOP|wx.BOTTOM,5)
        def choice(title,items):
            label(title);c=wx.Choice(left,choices=items);c.SetSelection(0);controls.Add(c,0,wx.EXPAND|wx.BOTTOM,4);return c
        self.mode=choice('1. Choose components',['Selected PCB parts / group','Schematic sub-sheet','Native PCB group','Schematic wire clusters','Manual selection'])
        self.refresh_button=wx.Button(left,label='Find groups / refresh selection');controls.Add(self.refresh_button,0,wx.EXPAND)
        self.cluster=choice('Group (preview labels A/B/C)', ['Choose a group'])
        label('Drawn schematic wire threshold (mm)')
        self.threshold=wx.Slider(left,value=25,minValue=1,maxValue=200,style=wx.SL_HORIZONTAL|wx.SL_LABELS);controls.Add(self.threshold,0,wx.EXPAND)
        self.labels=wx.CheckBox(left,label='Include local-label linked clusters');self.globals=wx.CheckBox(left,label='Include global-label linked clusters')
        controls.Add(self.labels,0,wx.TOP,4);controls.Add(self.globals,0,wx.TOP,4)
        self.search=wx.SearchCtrl(left);self.search.SetDescriptiveText('Search references');controls.Add(self.search,0,wx.EXPAND|wx.TOP,8)
        self.parts=wx.CheckListBox(left,choices=self.refs,size=(-1,140),style=wx.LB_HSCROLL);controls.Add(self.parts,0,wx.EXPAND|wx.TOP,4);self.checked=set()
        self.anchor=choice('2. Confirm anchor (kept fixed)',self.refs or ['No footprints'])
        self.infer=wx.Button(left,label='Infer anchor and area');controls.Add(self.infer,0,wx.EXPAND)
        self.sides=choice('3. Allowed placement sides',['Top','Bottom','Top and bottom'])
        label('Allowed absolute rotations (degrees)');self.angles=wx.TextCtrl(left,value='0,90');controls.Add(self.angles,0,wx.EXPAND)
        self.angles.SetToolTip('Default 0,90. Example: 0,45,90,135,180,225,270,315. Locked parts and the anchor keep their original pose.')
        label('Requested envelope density (%)');self.density=wx.Slider(left,value=50,minValue=10,maxValue=90,style=wx.SL_HORIZONTAL|wx.SL_LABELS);controls.Add(self.density,0,wx.EXPAND)
        label('Area width × height (mm), centred on anchor')
        dims=wx.BoxSizer(wx.HORIZONTAL);self.area_w=wx.TextCtrl(left,value='20');self.area_h=wx.TextCtrl(left,value='20');dims.Add(self.area_w,1);dims.Add(self.area_h,1,wx.LEFT,5);controls.Add(dims,0,wx.EXPAND)
        label('4. Decoupling capacitor overrides')
        self.caps=wx.TextCtrl(left,value='',style=wx.TE_MULTILINE,size=(-1,55));controls.Add(self.caps,0,wx.EXPAND)
        self.caps.SetHint('C1=power_pin_number, C2=power_pin_number')
        self.caps.SetToolTip('Auto inference uses shared power-like net names. Explicitly map each capacitor to an anchor power pad to override. Known lower values must be nearer that pad. Unknown/ambiguous values remain reported, never guessed.')
        self.preview_button=wx.Button(left,label='Preview arrangement');controls.Add(self.preview_button,0,wx.EXPAND|wx.TOP,10)
        self.validate_button=wx.Button(left,label='Validate native candidate');controls.Add(self.validate_button,0,wx.EXPAND|wx.TOP,5)
        self.apply_button=wx.Button(left,label='Apply reviewed placement');controls.Add(self.apply_button,0,wx.EXPAND|wx.TOP,5)
        self.undo_button=wx.Button(left,label='Undo placement');controls.Add(self.undo_button,0,wx.EXPAND|wx.TOP,5)
        self.help_button=wx.Button(left,label='Help');controls.Add(self.help_button,0,wx.EXPAND|wx.TOP,5)
        left.SetSizer(controls);left.SetupScrolling(scroll_x=True)
        right=wx.BoxSizer(wx.VERTICAL)
        self.results_splitter=wx.SplitterWindow(right_panel,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        view_panel=wx.Panel(self.results_splitter);view=wx.BoxSizer(wx.VERTICAL)
        self.view_side=wx.Choice(view_panel,choices=['Both sides','Top','Bottom']);self.view_side.SetSelection(0);view.Add(self.view_side,0,wx.ALL,6)
        self.canvas=PlacementCanvas(view_panel,self.pick_anchor);view.Add(self.canvas,1,wx.EXPAND|wx.ALL,6);view_panel.SetSizer(view)
        self.summary=wx.TextCtrl(self.results_splitter,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,150))
        self.summary.SetMinSize((180,70))
        self.results_splitter.SetMinimumPaneSize(100);self.results_splitter.SplitHorizontally(view_panel,self.summary,-150);self.results_splitter.SetSashGravity(1)
        right.Add(self.results_splitter,1,wx.EXPAND)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        for button,text in [(self.preview_button,'Preview'),(self.validate_button,'Validate candidate'),(self.apply_button,'Apply placement'),(self.undo_button,'Undo placement'),(self.help_button,'Help')]:
            controls.Detach(button);button.Reparent(right_panel);button.SetLabel(text);actions.Add(button,1,wx.RIGHT,5)
        right.Add(actions,0,wx.EXPAND|wx.ALL,6)
        right_panel.SetSizer(right)
        self.settings_splitter.SetMinimumPaneSize(250);self.settings_splitter.SplitVertically(left,right_panel,350);self.settings_splitter.SetSashGravity(0)
        layout.Add(self.settings_splitter,1,wx.EXPAND|wx.ALL,8);panel.SetSizer(layout)
        self.SetMinSize((820,580))
        self.Bind(wx.EVT_HELP,lambda e:webbrowser.open(Path(__file__).with_name('help.html').as_uri()))
        self.refresh_button.Bind(wx.EVT_BUTTON,self.find_groups);self.mode.Bind(wx.EVT_CHOICE,self.find_groups)
        self.cluster.Bind(wx.EVT_CHOICE,self.choose_cluster);self.search.Bind(wx.EVT_TEXT,self.filter_parts)
        self.parts.Bind(wx.EVT_CHECKLISTBOX,self.check_parts);self.infer.Bind(wx.EVT_BUTTON,self.infer_area)
        self.preview_button.Bind(wx.EVT_BUTTON,self.preview);self.validate_button.Bind(wx.EVT_BUTTON,self.validate)
        self.apply_button.Bind(wx.EVT_BUTTON,self.apply);self.undo_button.Bind(wx.EVT_BUTTON,self.undo)
        self.help_button.Bind(wx.EVT_BUTTON,lambda e:webbrowser.open(Path(__file__).with_name('help.html').as_uri()))
        self.view_side.Bind(wx.EVT_CHOICE,self.change_view)
        for control,event in [(self.anchor,wx.EVT_CHOICE),(self.sides,wx.EVT_CHOICE),(self.angles,wx.EVT_TEXT),(self.density,wx.EVT_SLIDER),(self.area_w,wx.EVT_TEXT),(self.area_h,wx.EVT_TEXT),(self.caps,wx.EVT_TEXT)]:control.Bind(event,self.invalidate)
        self.threshold.Bind(wx.EVT_SLIDER,self.schedule_groups)
        self.labels.Bind(wx.EVT_CHECKBOX,self.confirm_links);self.globals.Bind(wx.EVT_CHECKBOX,self.confirm_links)
        self.Bind(wx.EVT_CLOSE,self.close)
        self.update_buttons();wx.CallAfter(self.find_groups,None)
        area=wx.Display(self).GetClientArea()
        self.SetSize((min(self.GetSize().width,area.width-24),min(self.GetSize().height,area.height-32)))
        self.CentreOnScreen()

    def close(self,event):
        if self.busy: event.Veto();return
        self.Destroy()

    def update_buttons(self):
        self.settings_panel.Enable(not self.busy)
        self.validate_button.Enable(bool(self.plan and self.plan.result.complete) and not self.busy)
        self.apply_button.Enable(bool(self.plan and self.plan.validated_digest) and not self.busy)
        self.undo_button.Enable(bool(self.transaction and self.transaction.applied) and not self.busy)
        self.preview_button.Enable(not self.busy)

    def invalidate(self,event=None):
        if not self.loading:
            self.plan=None;self.canvas.before=();self.update_buttons()
            try:
                self.canvas.area=self.options()['area'];self.canvas.focus=self.anchor.GetStringSelection();self.canvas.Refresh()
            except (ValueError, TypeError):pass
            self.summary.SetValue('Inputs changed. Preview and validate before applying.')
        if event:event.Skip()

    def error(self,error): wx.MessageBox(str(error),'Component Arranger',wx.OK|wx.ICON_ERROR)

    def guard(self):
        if not self.board_guard():raise ValueError('Originating PCB changed or closed. Reopen the plugin from that board.')

    def filter_parts(self,event=None):
        text=self.search.GetValue().casefold();shown=[r for r in self.refs if text in r.casefold()]
        self.parts.Set(shown)
        for i,r in enumerate(shown):self.parts.Check(i,r in self.checked)

    def check_parts(self,event):
        ref=self.parts.GetString(event.GetInt())
        if self.parts.IsChecked(event.GetInt()):self.checked.add(ref)
        else:self.checked.discard(ref)
        self.invalidate();self.show_selection()

    def show_selection(self):
        models=[]
        visible=set(self.checked)
        if self.mode.GetSelection()==3:
            visible.update(r for c in self.clusters for r in c['references'])
        for fp in self.board.GetFootprints():
            if fp.GetReference() in visible:
                try:models.append(native.model(fp,api))
                except ValueError as error:self.summary.SetValue(str(error))
        self.canvas.set_models(models);self.canvas.before=();self.canvas.Refresh()

    def find_groups(self,event):
        if self.busy:return
        try:
            self.guard();mode=self.mode.GetSelection()
            if mode==3:
                path=Path(self.board.GetFileName()).with_suffix('.kicad_sch')
                data=grouping.infer_schematic_groups(path,max_wire_mm=self.threshold.GetValue(),include_label_links=self.labels.GetValue(),include_global_links=self.globals.GetValue())
            elif mode==4:
                self.invalidate();return
            else:data=grouping.board_groups(self.board,scope=('selection','sheet','native_groups')[mode])
            self.clusters=data['clusters'];self.cluster.Set([c['id']+' · '+', '.join(c['references']) for c in self.clusters] or ['No group found'])
            self.canvas.groups={r:c['id'] for c in self.clusters for r in c['references']}
            if self.clusters:self.cluster.SetSelection(0);self.choose_cluster(None)
            self.summary.SetValue('\n'.join(data.get('warnings',[])) or 'Groups inferred from the chosen scope. Confirm the parts and anchor.')
            links=data.get('label_links',[])
            if links:self.summary.AppendText('\nLabel jumps for review: '+'; '.join(l['name']+' '+','.join(l['clusters']) for l in links))
        except Exception as error:self.error(error)

    def schedule_groups(self,event):
        self.invalidate()
        old=getattr(self,'_debounce',None)
        if old:old.Stop()
        if self.mode.GetSelection()==3:self._debounce=wx.CallLater(250,self.find_groups,None)

    def confirm_links(self,event):
        control=event.GetEventObject()
        if control.GetValue() and wx.MessageBox('Merge clusters connected by these schematic label jumps? Review their A/B/C group IDs before confirming.','Include label-linked clusters',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION)!=wx.YES:control.SetValue(False)
        self.find_groups(None)

    def choose_cluster(self,event):
        i=self.cluster.GetSelection()
        if 0<=i<len(self.clusters):
            self.checked=set(self.clusters[i]['references']) & set(self.refs);self.filter_parts();self.invalidate();self.infer_area(None)

    def pick_anchor(self,reference):
        if self.busy:return
        if reference in self.checked:
            self.anchor.SetStringSelection(reference);self.canvas.focus=reference;self.invalidate();self.canvas.Refresh()

    def infer_area(self,event):
        try:
            models=tuple(native.model(fp,api) for fp in self.board.GetFootprints() if fp.GetReference() in self.checked)
            key=engine.infer_anchor(models);anchor=next(f for f in models if f.key==key)
            self.loading=True;self.anchor.SetStringSelection(anchor.reference)
            sides=('top','bottom') if self.sides.GetSelection()==2 else (('bottom',) if self.sides.GetSelection()==1 else ('top',))
            area=engine.suggested_area(models,key,self.density.GetValue()/100,sides)
            self.area_w.SetValue(f'{area[2]-area[0]:.3f}');self.area_h.SetValue(f'{area[3]-area[1]:.3f}')
            self.loading=False;self.invalidate();self.canvas.area=area;self.canvas.focus=anchor.reference;self.show_selection()
        except Exception as error:self.loading=False;self.error(error)

    def change_view(self,event):
        self.canvas.side=('both','top','bottom')[self.view_side.GetSelection()];self.canvas.Refresh()

    def options(self):
        anchor=self.anchor.GetStringSelection()
        fp=next((f for f in self.board.GetFootprints() if f.GetReference()==anchor),None)
        if fp is None or anchor not in self.checked:raise ValueError('Choose an anchor from the checked components.')
        x,y,_,_=native.pose(fp,api);w,h=float(self.area_w.GetValue()),float(self.area_h.GetValue())
        if not 0<w<=1000 or not 0<h<=1000:raise ValueError('Area dimensions must be in (0,1000] mm.')
        targets={}
        for row in self.caps.GetValue().replace('\n',',').split(','):
            if row.strip():
                key,value=row.split('=',1);targets[key.strip()]=value.strip()
        return dict(anchor=anchor,area=(x-w/2,y-h/2,x+w/2,y+h/2),allowed_angles=tuple(float(a.strip()) for a in self.angles.GetValue().split(',')),
                    allowed_sides=('top','bottom') if self.sides.GetSelection()==2 else (('bottom',) if self.sides.GetSelection()==1 else ('top',)),
                    density=self.density.GetValue()/100,capacitor_targets=targets)

    def solve(self,*args,**kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(engine.arrange,*args,**kwargs)
            while not future.done():
                wx.YieldIfNeeded();time.sleep(.015)
            self.guard()
            return future.result()

    def preview(self,event):
        try:
            self.guard();options=self.options();self.busy=True;self.update_buttons()
            self.summary.SetValue('Searching bounded legal placements…');self.summary.Update()
            self.plan=native.propose(self.board,api,sorted(self.checked),solve=self.solve,**options)
            result=self.plan.result
            self.canvas.before=tuple(native.model(fp,api) for fp in self.board.GetFootprints() if fp.GetReference() in self.checked)
            self.canvas.set_models(result.footprints,self.plan.external_pads);self.canvas.area=options['area'];self.canvas.focus=self.anchor.GetStringSelection();self.canvas.fit()
            before,after=result.before,result.after
            reduction=100*(before.crossings-after.crossings)/before.crossings if before.crossings else 0
            self.summary.SetValue(f'{"LEGAL PROPOSAL" if result.complete else "INCOMPLETE — ORIGINAL RETAINED"}\nCrossings: {before.crossings} → {after.crossings} ({reduction:.1f}% reduction); MST length: {before.length_mm:.2f} → {after.length_mm:.2f} mm\nCourtyard packing density: {result.achieved_density:.1%}; requested {result.target_density:.1%}; {result.evaluations} candidate evaluations.\n'+'\n'.join(result.warnings))
            caps=[f.reference+' = '+(f'{engine.capacitance(f):.6g} F' if engine.capacitance(f) is not None else 'unknown')
                  for f in result.footprints if f.reference.upper().startswith('C')]
            if caps:self.summary.AppendText('\nCapacitance review: '+', '.join(caps))
        except Exception as error:self.plan=None;self.error(error)
        finally:self.busy=False;self.update_buttons()

    def validate(self,event):
        dialog=None
        try:
            self.guard();self.busy=True;self.update_buttons()
            dialog=wx.ProgressDialog('Native validation','Checking detached project and before/after DRC…',parent=self,style=wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME)
            native.validate(self.board,api,self.plan,lambda:dialog.Pulse()[0])
            self.summary.AppendText('\nNative validation passed: '+str(self.plan.evidence))
        except Exception as error:self.error(error)
        finally:
            if dialog:dialog.Destroy()
            self.busy=False;self.update_buttons()

    def apply(self,event):
        try:
            self.guard();self.transaction=native.Transaction(self.board,api,self.plan).exchange(True)
            self.plan=None;api.Refresh();self.summary.AppendText('\nApplied. Backup: '+self.transaction.backup.name+'\nRefill zones and run final DRC before saving.');self.update_buttons()
        except Exception as error:self.error(error)

    def undo(self,event):
        try:self.guard();self.transaction.exchange(False);self.plan=None;api.Refresh();self.summary.AppendText('\nOriginal placement restored.');self.update_buttons()
        except Exception as error:self.error(error)
