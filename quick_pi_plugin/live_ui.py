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
        row=wx.WrapSizer(wx.HORIZONTAL)
        self.live_scroll=wx.CheckBox(page,label='Scroll load');self.live_scroll.SetValue(True)
        self.live_current=wx.SpinCtrlDouble(page,min=1e-9,max=1e9,initial=1,inc=.1,size=(130,-1),style=wx.SP_ARROW_KEYS|wx.TE_PROCESS_ENTER);self.live_current.SetDigits(9)
        self.live_step=wx.SpinCtrlDouble(page,min=1e-6,max=1e6,initial=.1,inc=.1,size=(90,-1));self.live_step.SetDigits(6)
        self.live_note=wx.StaticText(page,label='Run a 2.5D current solve to enable live tuning.',style=wx.ST_ELLIPSIZE_END)
        for item in (self.live_scroll,wx.StaticText(page,label='Total · A'),self.live_current,wx.StaticText(page,label='Step · A'),self.live_step):
            row.Add(item,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        layout.Add(row,0,wx.EXPAND|wx.ALL,6)
        self.live_note.SetMinSize((1,-1));layout.Add(self.live_note,0,wx.EXPAND|wx.LEFT|wx.RIGHT,6)
        self.live_current.SetToolTip('Exact fixed-temperature linear update; all sink loads scale proportionally. No remesh or new FEM solve.')
        self.live_step.SetToolTip('Amperes per wheel notch over solved copper. Shift uses one tenth of this step. Ctrl+wheel always zooms.')
        for event in (wx.EVT_SPINCTRLDOUBLE,wx.EVT_TEXT_ENTER):self.live_current.Bind(event,self._live_current_edited)
        canvas._wayricad_scroll_handler=self._live_wheel
        self._set_live_enabled(False,'Run a fixed-temperature 2.5D prescribed-current solve first.')

    def _set_live_enabled(self,enabled,reason):
        for control in (self.live_scroll,self.live_current,self.live_step):control.Enable(enabled)
        self.live_scroll.SetToolTip(reason);self.live_note.SetLabel(reason);self.live_note.SetToolTip(reason)

    def _reset_live(self):
        if not hasattr(self,'live_current'):return
        self._live_generation+=1;self._live_model=None;self._live_pending=None;self._live_stamp=None
        if self._live_timer:self._live_timer.Stop();self._live_timer=None
        self._set_live_enabled(False,'Run again after changing the simulation inputs.')

    def _source_stamp(self):
        stat=Path(self.board_path).stat()
        return stat.st_mtime_ns,stat.st_size,getattr(stat,'st_ino',0)

    def _prepare_live(self):
        from .live_current import LiveCurrentModel,live_current_eligibility
        self._reset_live();base=self.bundle;generation=self._live_generation
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
            self.live_current.SetValue(model.base_current_A)
            self._set_live_enabled(not self._busy,'Wheel on copper adjusts load · Ctrl+wheel zooms · all sinks scale together')
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
        if 'control' in key or 'ctrl' in key or gui is not None and gui.ControlDown():return False
        controller=self._probe_controllers.get(2)
        hit=None if not controller else controller['hit_test'](event.xdata,event.ydata)
        if hit is not None:
            value=controller['rows'][hit][2]
            if value is None or not math.isfinite(value):return False
        elif getattr(self,'_live_hit_index',None):
            if self._live_hit_index.pick(event.xdata,event.ydata,self._live_hit_count) is None:return False
        else:return False
        step=self.live_step.GetValue()
        if 'shift' in key or gui is not None and gui.ShiftDown():step/=10
        value=max(1e-9,min(1e9,self.live_current.GetValue()+event.step*step))
        self.live_current.SetValue(value);self._queue_live_current(value)
        return True

    def _queue_live_current(self,value):
        if self._closed or self._busy or not self._live_model:return
        if not math.isfinite(value) or value<=0:return
        try:current=self._source_stamp()==self._live_stamp
        except OSError:current=False
        if not current:
            self._reset_live();self.status.SetLabel('Saved PCB changed. Reload and rerun.');return
        self._live_pending=value;self.export.Disable();self.power_flow.Disable()
        if self._live_timer is None:self._live_timer=wx.CallLater(16,self._start_live_current)

    def _start_live_current(self):
        self._live_timer=None
        if self._closed or self._busy or not self._live_model or self._live_pending is None or self._live_running:return
        model=self._live_model;generation=self._live_generation;value=self._live_pending
        self._live_pending=None;self._live_running=True
        def worker():
            started=time.perf_counter()
            try:bundle=model.update(value);error=None
            except Exception as exc:bundle=None;error=str(exc)
            wx.CallAfter(self._finish_live_current,generation,bundle,error,(time.perf_counter()-started)*1000)
        threading.Thread(target=worker,name='Quick PI live current',daemon=True).start()

    def _finish_live_current(self,generation,bundle,error,elapsed_ms):
        self._live_running=False
        if self._closed:return
        if generation==self._live_generation and self._busy:
            if bundle is not None and self._live_pending is None:self._live_pending=bundle['result']['sink_current_A']
        elif generation==self._live_generation and self._live_pending is None:
            try:current=self._source_stamp()==self._live_stamp
            except OSError:current=False
            if not current:self._reset_live();self.status.SetLabel('Saved PCB changed. Reload and rerun.')
            elif error:
                self.live_note.SetLabel(error)
                if self._live_pending is None:self.live_current.SetValue(self.bundle['result']['sink_current_A'])
            else:self._show_live_current(bundle,elapsed_ms)
        if self._live_pending is not None and self._live_model and self._live_timer is None:
            self._live_timer=wx.CallLater(1,self._start_live_current)
        if self._live_pending is None:self._buttons()

    def _show_live_current(self,bundle,elapsed_ms):
        from .report import update_current_view,inspection_record,METRICS
        previous=self.bundle;bundle['view_settings']=dict(previous.get('view_settings',{}))
        bundle['board_scene']=self._board_scene;self.bundle=bundle
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
            factor=ratio**2 if metric in ('loss','risk') else 1. if metric=='resistance' else ratio
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
        self._live_hit_index=None
        if self.layer.GetSelection()>=0 and self._layers[self.layer.GetSelection()]['id']=='all' and self.bundle.get('mesh'):
            import numpy as np
            from wayricad_runtime.plot_probe import _CellIndex
            mesh=self.bundle['mesh'];points=np.asarray(mesh['points_mm']);triangles=np.asarray(mesh['triangles'],dtype=int)
            valid=np.asarray([value is not None for value in self.bundle.get('result',{}).get('cell_J_A_mm2',[])])
            if len(valid)==len(triangles):
                polygons=points[triangles[valid],:2];self._live_hit_index=_CellIndex(polygons);self._live_hit_count=len(polygons)
