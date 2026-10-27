"""Latest-input-wins current tuning for the solved 2.5D board workspace."""
import hashlib
import math
import threading
import time
from pathlib import Path

import wx


class LiveCurrentControls:
    """Keep numerical work off wx and retain the existing board artists."""

    def _init_live_controls(self,page,layout,canvas):
        self._live_model=None;self._live_generation=0;self._live_pending=None
        self._live_timer=None;self._live_running=False;self._live_stamp=None
        self._live_wheel_time=None;self._live_wheel_direction=0
        self._live_targets=None;self._live_pending_vector=None;self._live_active_sink=None
        self._live_wheel_target=None
        self._live_preview=None;self._live_preview_context=None
        row=wx.WrapSizer(wx.HORIZONTAL)
        self.live_scroll=wx.CheckBox(page,label='Ctrl+scroll load');self.live_scroll.SetValue(True)
        self.live_current=wx.SpinCtrlDouble(page,min=1e-9,max=1e9,initial=1,inc=.1,size=(130,-1),style=wx.SP_ARROW_KEYS|wx.TE_PROCESS_ENTER);self.live_current.SetDigits(9)
        self.live_step=wx.SpinCtrlDouble(page,min=1e-6,max=1e6,initial=.1,inc=.1,size=(90,-1));self.live_step.SetDigits(6)
        self.live_note=wx.StaticText(page,label='Run a 2.5D current solve to enable live tuning.',style=wx.ST_ELLIPSIZE_END)
        self.live_preview_enabled=wx.CheckBox(page,label='Cursor preview');self.live_preview_enabled.SetValue(True)
        self.live_preview_mode=wx.Choice(page,choices=['Selected metric','All metrics']);self.live_preview_mode.SetSelection(0)
        for item in (self.live_scroll,wx.StaticText(page,label='Total · A'),self.live_current,wx.StaticText(page,label='Base step · A'),self.live_step):
            row.Add(item,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        for item in (self.live_preview_enabled,self.live_preview_mode):row.Add(item,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        self.live_preview_enabled.Bind(wx.EVT_CHECKBOX,lambda e:self._hide_current_preview() if not self.live_preview_enabled.GetValue() else None)
        layout.Add(row,0,wx.EXPAND|wx.ALL,6)
        self.live_note.SetMinSize((1,-1));layout.Add(self.live_note,0,wx.EXPAND|wx.LEFT|wx.RIGHT,6)
        self.live_current.SetToolTip('Total current scales all loads proportionally. Ctrl+scroll over a sink pad changes only that load, with a fixed-mesh electrical re-solve.')
        self.live_step.SetToolTip('Base amperes per Ctrl+wheel notch over solved copper. Slow: ×0.1; normal: ×1; fast: ×5. Plain wheel zooms.')
        for event in (wx.EVT_SPINCTRLDOUBLE,wx.EVT_TEXT_ENTER):self.live_current.Bind(event,self._live_current_edited)
        canvas._wayricad_scroll_handler=self._live_wheel
        self._set_live_enabled(False,'Run a fixed-temperature 2.5D prescribed-current solve first.')

    def _set_live_enabled(self,enabled,reason):
        for control in (self.live_scroll,self.live_current,self.live_step):control.Enable(enabled)
        self.live_scroll.SetToolTip(reason);self.live_note.SetLabel(reason);self.live_note.SetToolTip(reason)

    def _reset_live(self):
        if not hasattr(self,'live_current'):return
        self._hide_current_preview();self._live_preview_context=None
        if self._live_preview is not None:
            self._live_preview.Destroy();self._live_preview=None
        self._live_generation+=1;self._live_model=None;self._live_pending=None;self._live_stamp=None
        self._live_wheel_time=None;self._live_wheel_direction=0
        self._live_targets=None;self._live_pending_vector=None;self._live_active_sink=None
        self._live_wheel_target=None
        if self._live_timer:self._live_timer.Stop();self._live_timer=None
        self._set_live_enabled(False,'Run again after changing the simulation inputs.')

    def _source_stamp(self):
        stat=Path(self.board_path).stat()
        return stat.st_mtime_ns,stat.st_size,getattr(stat,'st_ino',0)

    def _prepare_live(self):
        from .live_current import LiveCurrentModel,live_current_eligibility
        self._reset_live();base=self.bundle;generation=self._live_generation
        solved=base.get('result',{}).get('total_sink_current_A',base.get('result',{}).get('sink_current_A'))
        if isinstance(solved,(int,float)) and math.isfinite(solved) and solved>0:
            self.live_current.SetRange(1e-9,max(1e9,solved));self.live_current.SetValue(solved)
        supported,reason=live_current_eligibility(base)
        if self.joule_feedback.GetValue():supported=False;reason='Temperature feedback requires a new electrothermal solve; live tuning is fixed-temperature only.'
        if not supported:self._set_live_enabled(False,reason);return
        self.live_note.SetLabel('Preparing instant current response…')
        def worker():
            try:
                before=self._source_stamp()
                geometry=base.get('geometry') or base['mesh'].get('geometry',{})
                expected=geometry.get('source_sha256')
                if expected and hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()!=expected:
                    raise ValueError('Saved PCB changed. Reload and rerun.')
                model=LiveCurrentModel(base)
                if before!=self._source_stamp():raise ValueError('Saved PCB changed. Reload and rerun.')
                error=None
            except Exception as exc:model=None;before=None;error=str(exc)
            wx.CallAfter(finish,model,before,error)
        def finish(model,stamp,error):
            if self._closed or generation!=self._live_generation or self.bundle is not base:return
            if error:self._set_live_enabled(False,error);return
            self._live_model=model;self._live_stamp=stamp
            self._live_targets=[float(row['current_A']) for row in self.bundle['result']['sinks']]
            self.live_current.SetValue(model.base_current_A)
            self._set_live_enabled(not self._busy,'Ctrl+wheel: sink pad changes that load; other copper scales total · Wheel zooms')
        threading.Thread(target=worker,name='Quick PI current basis',daemon=True).start()

    def _live_current_edited(self,event=None):
        self._queue_live_current(self.live_current.GetValue())

    def _live_wheel(self,event):
        if (not self._live_model or self._busy or not self.live_scroll.GetValue()
                or self.book.GetSelection()!=2 or event.inaxes is None or event.xdata is None):return False
        key=str(getattr(event,'key','') or '')
        _,canvas,navigation=self.views[2]
        if (getattr(navigation,'mode','') or getattr(navigation,'drag',None) is not None
                or getattr(canvas,'_drag',None) is not None
                or getattr(getattr(canvas,'toolbar',None),'mode','')):return False
        gui=getattr(event,'guiEvent',None)
        if not ('control' in key or 'ctrl' in key or gui is not None and gui.ControlDown()):
            self._live_wheel_time=None;self._live_wheel_direction=0
            return False
        if event.inaxes is not self.views[2][0].axes[0]:return False
        endpoint=self._live_endpoint_hit(event)
        if endpoint is not None and endpoint.ambiguous:
            self._live_wheel_time=None;self._live_wheel_direction=0;self._live_wheel_target=None
            self._hide_current_preview()
            self.status.SetLabel('Nearby endpoints are ambiguous ('+endpoint.label+'). Move closer to one pad or select its layer; currents unchanged.')
            return True
        sink=(endpoint.index,endpoint.label) if endpoint is not None and endpoint.role=='sink' else None
        controller=self._probe_controllers.get(2)
        hit=None if not controller else controller['hit_test'](event.xdata,event.ydata)
        if endpoint is not None:pass
        elif hit is not None:
            value=controller['rows'][hit][2]
            if value is None or not math.isfinite(value):return False
        elif getattr(self,'_live_hit_index',None):
            if self._live_hit_index.pick(event.xdata,event.ydata,self._live_hit_count) is None:return False
        else:return False
        notches=float(event.step)
        if not math.isfinite(notches) or notches==0:return False
        now=time.monotonic();direction=1 if notches>0 else -1
        target=('sink',sink[0]) if sink else ('total',)
        elapsed=None if self._live_wheel_time is None or target!=self._live_wheel_target else now-self._live_wheel_time
        # Restart finely after a pause or reversal; rapid same-direction
        # notches accelerate. Account for batched/high-resolution wheel events.
        rate=0. if elapsed is None or elapsed<=0 or elapsed>.4 or direction!=self._live_wheel_direction else abs(notches)/elapsed
        gain=.1 if rate<=5 else 1. if rate<=15 else 5.
        self._live_wheel_time=now;self._live_wheel_direction=direction
        self._live_wheel_target=target
        step=self.live_step.GetValue()*gain
        if sink is None:
            value=max(1e-9,min(1e9,self.live_current.GetValue()+notches*step))
            self.live_current.SetValue(value);self._queue_live_current(value)
            self._preview_current_change(event,None,value)
        else:
            index,label=sink
            targets=list(self._live_targets or [r['current_A'] for r in self.bundle['result']['sinks']])
            targets[index]=max(1e-9,min(1e9,targets[index]+notches*step))
            self._live_active_sink=index
            self._queue_live_current(math.fsum(targets),targets)
            self.live_current.SetValue(math.fsum(targets))
            self.live_note.SetLabel(f'{label}: {targets[index]:.6g} A · other sink currents retained')
            self._preview_current_change(event,index,targets[index])
        return True

    def _hide_current_preview(self):
        if getattr(self,'_live_preview',None):
            self._live_preview.timer.Stop();self._live_preview.Hide()

    def _preview_current_change(self,event,sink,pending):
        if not self._live_model or not self.live_preview_enabled.GetValue():return
        from .current_preview import comparison,popup
        from .report import METRICS
        identity=None;controller=self._probe_controllers.get(2)
        hit=controller['hit_test'](event.xdata,event.ydata) if controller else None
        if hit is not None:
            label=controller['rows'][hit][3]
            if label.startswith('Cell '):identity=('sheet',int(label[5:]))
        # Projected all-layer copper has no unique local layer sample. Sink
        # electrode values remain known; local J/loss stay explicitly unknown.
        metric=list(METRICS)[max(0,self.metric.GetSelection())]
        _,canvas,_=self.views[2];x,y=event.inaxes.transData.transform((event.xdata,event.ydata))
        ratio=getattr(canvas,'device_pixel_ratio',1.)
        position=canvas.ClientToScreen(wx.Point(round(x/ratio),round(canvas.GetClientSize().height-y/ratio)))
        self._live_preview_context=(self.bundle,metric,identity,sink,self.live_preview_mode.GetSelection()==1,position)
        if self._live_preview is None:self._live_preview=popup(self)
        self._live_preview.present(position,comparison(self.bundle,None,metric,identity,sink,
                                   self.live_preview_mode.GetSelection()==1,pending_current=pending),True)

    def _complete_current_preview(self,bundle):
        if not self._live_preview_context or not self.live_preview_enabled.GetValue():return
        from .current_preview import comparison
        before,metric,identity,sink,all_fields,position=self._live_preview_context
        if self._live_preview is not None:
            self._live_preview.present(position,comparison(before,bundle,metric,identity,sink,all_fields))

    def _live_sink_hit(self,event):
        """Compatibility accessor for one unambiguous displayed sink unit."""
        hit=self._live_endpoint_hit(event)
        return (hit.index,hit.label) if hit is not None and hit.role=='sink' and not hit.ambiguous else None

    def _live_endpoint_hit(self,event):
        if event.ydata is None:return None
        from .endpoint_targets import pick_endpoint,project_anchors
        ratio=max(1.,float(getattr(self.views[2][1],'device_pixel_ratio',1.)))
        transform=event.inaxes.transData;key=tuple(transform.get_matrix().ravel())
        if key!=getattr(self,'_live_endpoint_screen_key',None):
            self._live_endpoint_screen=project_anchors(getattr(self,'_live_endpoint_anchors',[]),transform.transform)
            self._live_endpoint_screen_key=key
        return pick_endpoint(transform.transform((event.xdata,event.ydata)),self._live_endpoint_screen,None,
                             proximity_px=14.*ratio,ambiguity_px=2.*ratio)

    def _queue_live_current(self,value,targets=None):
        if self._closed or self._busy or not self._live_model:return
        if not math.isfinite(value) or value<=0:return
        try:current=self._source_stamp()==self._live_stamp
        except OSError:current=False
        if not current:
            self._reset_live();self.status.SetLabel('Saved PCB changed. Reload and rerun.');return
        if self._live_targets is not None:
            if targets is None:
                factor=value/math.fsum(self._live_targets)
                targets=[v*factor for v in self._live_targets]
                self._live_active_sink=None
            self._live_targets=list(targets)
            baseline=[r['current_A'] for r in self._live_model._base['result']['sinks']]
            ratios=[a/b for a,b in zip(targets,baseline)]
            self._live_pending_vector=(list(targets) if any(not math.isclose(v,ratios[0],rel_tol=1e-12) for v in ratios) else None)
        self._live_pending=value;self.export.Disable();self.power_flow.Disable()
        if self._live_timer is None:self._live_timer=wx.CallLater(16,self._start_live_current)

    def _start_live_current(self):
        self._live_timer=None
        if self._closed or self._busy or not self._live_model or self._live_pending is None or self._live_running:return
        model=self._live_model;generation=self._live_generation;value=self._live_pending
        vector=self._live_pending_vector;base=self.bundle
        self._live_pending=None;self._live_pending_vector=None;self._live_running=True
        def worker():
            started=time.perf_counter()
            replacement=None
            try:
                if vector is None:bundle=model.update(value)
                else:
                    from .sink_current import SinkCurrentModel
                    from .live_current import LiveCurrentModel
                    bundle=SinkCurrentModel(base).update(vector)
                    replacement=LiveCurrentModel(bundle)
                error=None
            except Exception as exc:bundle=None;error=str(exc)
            wx.CallAfter(self._finish_live_current,generation,bundle,error,(time.perf_counter()-started)*1000,replacement)
        threading.Thread(target=worker,name='Quick PI live current',daemon=True).start()

    def _finish_live_current(self,generation,bundle,error,elapsed_ms,replacement=None):
        self._live_running=False
        if self._closed:return
        if generation==self._live_generation and self._busy:
            if bundle is not None and self._live_pending is None:self._live_pending=bundle['result']['sink_current_A']
        elif generation==self._live_generation and self._live_pending is None:
            try:current=self._source_stamp()==self._live_stamp
            except OSError:current=False
            if not current:self._reset_live();self.status.SetLabel('Saved PCB changed. Reload and rerun.')
            elif error:
                self._hide_current_preview()
                self.live_note.SetLabel(error)
                if self._live_pending is None:
                    self.live_current.SetValue(self.bundle['result']['sink_current_A'])
                    self._live_targets=[r['current_A'] for r in self.bundle['result']['sinks']]
            else:
                if replacement is not None:self._live_model=replacement
                self._show_live_current(bundle,elapsed_ms)
        if self._live_pending is not None and self._live_model and self._live_timer is None:
            self._live_timer=wx.CallLater(1,self._start_live_current)
        if self._live_pending is None:self._buttons()

    def _show_live_current(self,bundle,elapsed_ms):
        from .report import update_current_view,inspection_record,METRICS
        previous=self.bundle;bundle['view_settings']=dict(previous.get('view_settings',{}))
        bundle['board_scene']=self._board_scene;self.bundle=bundle
        self._complete_current_preview(bundle)
        request=bundle['request'];sinks=request.get('sinks') or []
        primary=request.get('sink_current',sinks[0].get('current_A') if sinks else None)
        if primary is not None:self.current.ChangeValue(f'{primary:.9g}')
        if sinks:self._extra_sinks=[dict(row) for row in sinks[1:]]
        if self._inspection:
            row=self._inspection
            if row['kind']!='object':
                refreshed=inspection_record(bundle,row['kind'],row['id'],row['metric'])
                if refreshed is not None:refreshed['source_ids']=list(row.get('source_ids',[]))
                self._inspection=refreshed
        for figure,_,_ in self.views:figure._wayricad_render_key=None
        independent=bundle['result'].get('live_current',{}).get('basis','').startswith('independent')
        if independent:
            old=self._probe_controllers.get(2)
            pins=[tuple(artist._wayricad_probe_row[:2]) for artist in old['probes']] if old else []
            self._draw(preserve=True)
            controller=self._probe_controllers.get(2)
            if controller:
                ax=self.views[2][0].axes[0]
                for point in pins:
                    hit=controller['hit_test'](*point)
                    if hit is None:continue
                    row=controller['rows'][hit]
                    artist=ax.annotate('',row[:2],xytext=(8,8),textcoords='offset points',fontsize=8,
                                       bbox={'facecolor':'white','alpha':.85})
                    artist._wayricad_probe_row=row;controller['probes'].append(artist)
                controller['refresh_values']()
            self.live_note.SetLabel(f'Independent sink update · {elapsed_ms:.1f} ms · fixed mesh; shared copper re-solved')
            self.status.SetLabel('Only the selected sink demand changed; shared copper and losses recomputed.')
            self.views[2][1].draw_idle()
            return
        figure,canvas,_=self.views[2]
        ax=figure.axes[0] if figure.axes else None
        same=None
        if ax:
            metric=list(METRICS)[max(0,self.metric.GetSelection())]
            manual=self._scale_limits(metric) if self.scale_mode.GetSelection()==2 else None
            same=update_current_view(ax,bundle,manual)
            if same is not None:self.color_legend.set_scale(ax._wayricad_color_scale)
        controller=self._probe_controllers.get(2)
        if controller:
            old=previous['result'];new=bundle['result'];ratio=new['sink_current_A']/old['sink_current_A']
            metric=list(METRICS)[max(0,self.metric.GetSelection())]
            factor=ratio**2 if metric in ('loss','risk','melt') else 1. if metric=='resistance' else ratio
            offset=new['source_voltage_V']*(1-ratio) if metric=='voltage' else 0.
            for row in controller['rows']:row[2]=row[2]*factor+offset
            if same and not controller['probes']:ax.stale=False;figure.stale=False
            controller['refresh_values'](keep_background=bool(same))
            if controller['probes']:same=False
        self._update_inspector(True,check_source=False)
        result=bundle['result'];state=result['feasibility']['status']
        self.summary.SetLabel(f"{state} · {result['sink_current_A']:.6g} A · ΔV {result['voltage_drop_V']*1000:.5g} mV · Loss {result['total_power_W']:.6g} W")
        self.live_note.SetLabel(f'Live · {elapsed_ms:.1f} ms calculation · no remesh')
        self.status.SetLabel('Live fixed-temperature DC · all sink currents scale proportionally · '+state)
        if same is None and self.book.GetSelection()==2:self._draw(preserve=True)
        elif same is False:canvas.draw_idle()
        elif ax is not None:ax.stale=False;figure.stale=False

    def _live_scene_ready(self,index,ax):
        if index!=2:return
        self._live_sink_anchors=[]
        self._live_endpoint_anchors=[]
        self._live_endpoint_screen_key=None
        bundle=self.bundle;geometry=bundle.get('geometry') or bundle.get('mesh',{}).get('geometry',{})
        terminals={key:row for row in geometry.get('terminals',[]) for key in (row['id'],row.get('label',row['id']))}
        layer=self._layers[self.layer.GetSelection()]['id'] if self.layer.GetSelection()>=0 else None
        units=bundle.get('terminal_units',{}).get('loads')
        if units is None:
            from .service import sink_requests
            try:units=sink_requests(bundle.get('request',{}))
            except ValueError:units=[]
        for number,unit in enumerate(units):
            if number>=len(bundle.get('result',{}).get('sinks',[])):break
            label=bundle['result']['sinks'][number]['label']
            for identifier in unit.get('terminals',[unit.get('terminal')]):
                terminal=terminals.get(identifier,{})
                for side,polygons in terminal.get('polygons',{}).items():
                    if layer not in (None,'all') and str(layer)!=str(side):continue
                    for polygon in polygons:
                        outline=polygon.get('outer',[])
                        if not outline:continue
                        from .endpoint_targets import pad_center
                        x,y=pad_center(outline)
                        self._live_sink_anchors.append((number,label,x,y,outline))
                        self._live_endpoint_anchors.append(dict(role='sink',index=number,label=label,center=(x,y),outline=outline))
                        if number==self._live_active_sink:
                            ax.scatter([x],[y],s=130,facecolors='none',edgecolors='#ff7f00',linewidths=2,zorder=30)
        request=bundle.get('request',{})
        sources=set(bundle.get('terminal_units',{}).get('source_terminals',[]))
        sources.update(request.get('source_terminals',[]))
        source=request.get('source_terminal',request.get('source'))
        if source is not None:sources.add(source)
        for identifier in sources:
            terminal=terminals.get(identifier,{})
            for side,polygons in terminal.get('polygons',{}).items():
                if layer not in (None,'all') and str(layer)!=str(side):continue
                for polygon in polygons:
                    outline=polygon.get('outer',[])
                    if not outline:continue
                    from .endpoint_targets import pad_center
                    self._live_endpoint_anchors.append(dict(role='source',index=None,label='Source · total load',center=pad_center(outline),outline=outline))
        self._live_hit_index=None
        if self.layer.GetSelection()>=0 and self._layers[self.layer.GetSelection()]['id']=='all' and self.bundle.get('mesh'):
            import numpy as np
            from wayricad_runtime.plot_probe import _CellIndex
            mesh=self.bundle['mesh'];points=np.asarray(mesh['points_mm']);triangles=np.asarray(mesh['triangles'],dtype=int)
            valid=np.asarray([value is not None for value in self.bundle.get('result',{}).get('cell_J_A_mm2',[])])
            if len(valid)==len(triangles):
                polygons=points[triangles[valid],:2];self._live_hit_index=_CellIndex(polygons);self._live_hit_count=len(polygons)
                self._live_hit_cells=np.flatnonzero(valid)
