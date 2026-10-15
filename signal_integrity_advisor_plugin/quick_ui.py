"""Focused native route, timing and termination-screen workflow."""
from pathlib import Path
from types import SimpleNamespace
import threading
from wayricad_runtime.ipc import read_snapshot
import wx
from wayricad_runtime.readable_choice import ReadableComboBox
from .measurement import TraceMeasurementEngine
from .quick_si import analyze,html_report
from .cli import write_report


def reverse_selection_plan(current_net,net_pads,source,receiver):
    """Resolve a net and terminal roles without guessing signal direction."""
    names=set(net_pads)
    if not names:return None,'PCB selection has no connected net in this snapshot.'
    if current_net in names:net=current_net
    elif len(names)==1:net=next(iter(names))
    else:return None,'PCB selection contains multiple nets. Retain the current inputs or select one signal net explicitly.'
    pads=sorted(set(net_pads[net]));roles={}
    if net==current_net and len(pads)==2:
        if source in pads:roles={'start':source,'end':next(value for value in pads if value!=source)}
        elif receiver in pads:roles={'end':receiver,'start':next(value for value in pads if value!=receiver)}
    return {'net':net,'roles':roles,'pads':pads},('Pad direction is unresolved; choose Source and Receiver explicitly.' if pads and not roles else 'PCB selection mapped to the analysis view.')


class QuickSIPanel(wx.Panel):
    def __init__(self,parent,board,preview_class,saved_board=False):
        super().__init__(parent);self.board=board;self.saved_board=saved_board;self.report=None;self.path=None
        self._closed=False;self._busy=False;self._generation=0;self._job_serial=0;self._cancel=threading.Event();self._result_fingerprints=None
        self._navigation_busy=False;self._navigation_serial=0
        self._source_fingerprints=None
        if saved_board:
            from .service import source_fingerprints
            self._source_fingerprints=source_fingerprints(board.GetFileName())
        self.Bind(wx.EVT_WINDOW_DESTROY,self._destroyed)
        root=wx.BoxSizer(wx.HORIZONTAL)
        left=wx.ScrolledWindow(self,size=(340,-1));left.SetScrollRate(0,12);form=wx.BoxSizer(wx.VERTICAL)
        self.fields={}
        def row(name,label,value='',choices=None,parent=left,sizer=form):
            sizer.Add(wx.StaticText(parent,label=label),0,wx.TOP,7)
            control=ReadableComboBox(parent,choices=choices,value=value,style=wx.CB_READONLY) if choices is not None else wx.TextCtrl(parent,value=value)
            sizer.Add(control,0,wx.EXPAND|wx.TOP,3);self.fields[name]=control
            return control
        with read_snapshot(board):
            self.engine=TraceMeasurementEngine(board)
            nets=self.engine.net_names()
        row('net','Net',choices=nets);self._net_names=nets
        self.net_search=wx.SearchCtrl(left);self.net_search.SetHint('Search net names');form.Add(self.net_search,0,wx.EXPAND|wx.TOP,5);self.net_search.Bind(wx.EVT_TEXT,self.filter_nets)
        pick=wx.Button(left,label='Select net on board');form.Add(pick,0,wx.EXPAND|wx.TOP,5);pick.Bind(wx.EVT_BUTTON,self.select_board_net)
        row('start','Source pad',choices=[]);row('end','Receiver pad',choices=[])
        row('rise_ns','Driver rise time (ns)','1');row('source_ohm','Driver resistance (ohm)','20')
        pane=wx.CollapsiblePane(left,label='Line and load assumptions');details=wx.BoxSizer(wx.VERTICAL);host=pane.GetPane()
        for name,label,value in [('frequency_mhz','Frequency (MHz)','100'),('load_ohm','Load resistance (ohm; blank = open)',''),('z0_ohm','Assumed uniform Z0 (ohm; blank = geometry)',''),('epsilon_eff','Assumed effective Er (blank = stackup)','')]:row(name,label,value,parent=host,sizer=details)
        with read_snapshot(board):layers=self.engine.available_layers()
        row('reference','Reference layer','Auto',['Auto']+layers,host,details)
        host.SetSizer(details);form.Add(pane,0,wx.EXPAND|wx.TOP,10);pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        returns_pane=wx.CollapsiblePane(left,label='Explicit return-path review (optional)');returns_layout=wx.BoxSizer(wx.VERTICAL);returns_host=returns_pane.GetPane()
        returns_note=wx.StaticText(returns_host,label='Choose actual return nets; no return net or current loop is inferred. Review covers the whole signal net.');returns_note.Wrap(285);returns_layout.Add(returns_note,0,wx.EXPAND|wx.BOTTOM,5)
        from wayricad_runtime.readable_choice import SearchableCheckListBox
        from wayricad_runtime.searchable_selection import searchable_row
        self.return_nets=SearchableCheckListBox(returns_host,choices=nets,size=(-1,105));returns_layout.Add(searchable_row(self.return_nets),0,wx.EXPAND)
        self.return_source=ReadableComboBox(returns_host,choices=['Not specified'],value='Not specified',style=wx.CB_READONLY)
        self.return_sink=ReadableComboBox(returns_host,choices=['Not specified'],value='Not specified',style=wx.CB_READONLY)
        for label,control in [('Source return pad (optional)',self.return_source),('Receiver return pad (optional)',self.return_sink)]:
            returns_layout.Add(wx.StaticText(returns_host,label=label),0,wx.TOP,5);returns_layout.Add(control,0,wx.EXPAND);control.Bind(wx.EVT_COMBOBOX,self.changed)
        returns_host.SetSizer(returns_layout);form.Add(returns_pane,0,wx.EXPAND|wx.TOP,10)
        returns_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        self.return_nets.Bind(wx.EVT_CHECKLISTBOX,self.return_nets_changed)
        eye_pane=wx.CollapsiblePane(left,label='Illustrative eye (optional)');eye_form=wx.BoxSizer(wx.VERTICAL);eye_host=eye_pane.GetPane()
        self.eye_enabled=wx.CheckBox(eye_host,label='Generate ideal NRZ eye and step response')
        eye_form.Add(self.eye_enabled,0,wx.TOP,6)
        row('eye_bitrate_mbps','Bit rate (Mbps)','1000',parent=eye_host,sizer=eye_form)
        row('eye_swing_v','Source open-circuit swing (V)','1',parent=eye_host,sizer=eye_form)
        eye_host.SetSizer(eye_form);form.Add(eye_pane,0,wx.EXPAND|wx.TOP,10)
        eye_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        self.eye_enabled.Bind(wx.EVT_CHECKBOX,self.changed)
        note=wx.StaticText(left,label='Inputs are assumptions. The optional eye uses a uniform lossless line, ideal clock and resistive endpoints. No IBIS, coupling or protocol signoff.');note.Wrap(300);form.Add(note,0,wx.EXPAND|wx.TOP,10)
        self.run_button=wx.Button(left,label='Screen selected path');self.run_button.Bind(wx.EVT_BUTTON,self.run);form.Add(self.run_button,0,wx.EXPAND|wx.TOP,12)
        self.cancel_button=wx.Button(left,label='Cancel analysis');self.cancel_button.Disable();self.cancel_button.Bind(wx.EVT_BUTTON,self.cancel_run);form.Add(self.cancel_button,0,wx.EXPAND|wx.TOP,5)
        self.export=wx.Button(left,label='Export local HTML report');self.export.Disable();self.export.Bind(wx.EVT_BUTTON,self.export_report);form.Add(self.export,0,wx.EXPAND|wx.TOP,6)
        self.select_route_button=wx.Button(left,label='Select route in PCB');self.select_route_button.Disable()
        self.select_returns_button=wx.Button(left,label='Select return nets in PCB');self.select_returns_button.Disable()
        self.read_selection_button=wx.Button(left,label='Use PCB selection')
        for control,handler in [(self.select_route_button,self.select_route_in_pcb),(self.select_returns_button,self.select_returns_in_pcb),(self.read_selection_button,self.use_pcb_selection)]:
            control.Bind(wx.EVT_BUTTON,handler);form.Add(control,0,wx.EXPAND|wx.TOP,5)
        left.SetSizer(form);root.Add(left,0,wx.EXPAND|wx.ALL,10)
        right=wx.BoxSizer(wx.VERTICAL);self.views=wx.Notebook(self)
        route=wx.Panel(self.views);route_sizer=wx.BoxSizer(wx.VERTICAL);self.preview=preview_class(route);self.preview.on_pick=self._pick_route_item;route_sizer.Add(self.preview,1,wx.EXPAND)
        from .preview_kit import add_zoom_toolbar
        add_zoom_toolbar(route,self.preview,route_sizer);route.SetSizer(route_sizer);self.views.AddPage(route,'Route')
        from .eye_ui import EyePanel
        self.eye_preview=EyePanel(self.views);self.views.AddPage(self.eye_preview,'Eye / step');right.Add(self.views,2,wx.EXPAND)
        self.status=wx.StaticText(self,label='Choose the source and receiver, review the inputs, then screen the path.');right.Add(self.status,0,wx.EXPAND|wx.ALL,7)
        self.results=wx.ListCtrl(self,style=wx.LC_REPORT);self.results.InsertColumn(0,'Measure',width=210);self.results.InsertColumn(1,'Result / evidence',width=620);right.Add(self.results,0,wx.EXPAND)
        self.results.SetMinSize((-1, 175))
        root.Add(right,1,wx.EXPAND|wx.ALL,10);self.SetSizer(root)
        for name,control in self.fields.items():
            control.Bind(wx.EVT_COMBOBOX if isinstance(control,wx.ComboBox) else wx.EVT_TEXT,self.changed)
        self.fields['net'].Bind(wx.EVT_COMBOBOX,self.net_changed)
        with read_snapshot(board):
            selected=[];counts={}
            for fp in board.GetFootprints():
                for pad in fp.Pads():
                    net=pad.GetNetname();counts[net]=counts.get(net,0)+1
                    if pad.IsSelected():selected.append((net,fp.GetReference()+'.'+pad.GetNumber()))
            selected_tracks=[track.GetNetname() for track in board.GetTracks() if track.IsSelected() and track.GetNetname()]
        candidate=next((name for name in nets if counts.get(name)==2),next((name for name in nets if counts.get(name,0)>=2),nets[0] if nets else ''))
        self.fields['net'].SetValue(selected[0][0] if selected else selected_tracks[0] if selected_tracks else candidate);self.net_changed(None)
        if selected:self.set_launch_selection({'net':selected[0][0],'pads':[label for net,label in selected if net==selected[0][0]]})
        left.FitInside()

    def return_nets_changed(self,event=None):
        selected={self.return_nets.GetString(i) for i in range(self.return_nets.GetCount()) if self.return_nets.IsChecked(i)}
        with read_snapshot(self.board):
            choices=['Not specified']+[str(fp.GetReference())+'.'+str(pad.GetNumber()) for fp in self.board.GetFootprints() for pad in fp.Pads() if str(pad.GetNetname()) in selected]
        for control in (self.return_source,self.return_sink):
            old=control.GetValue();control.Set(choices);control.SetValue(old if old in choices else 'Not specified')
        self.changed(event)

    def select_board_net(self,event=None):
        import pcbnew
        from wayricad_runtime.preview import GeometryPreview
        dialog=wx.Dialog(self,title='Select a net on the saved board',size=(850,620),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL);view=GeometryPreview(dialog);layout.Add(view,1,wx.EXPAND|wx.ALL,8)
        layout.Add(wx.StaticText(dialog,label='Click a pad, via or track to choose its net. Drag to pan; wheel to zoom.'),0,wx.ALL,8)
        layout.Add(dialog.CreateButtonSizer(wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,8);dialog.SetSizer(layout)
        view.set_board(self.board,pcbnew)
        def selected(net,xy):
            self.net_search.ChangeValue('');self.fields['net'].Set(self._net_names)
            self.fields['net'].SetValue(net);self.net_changed(None)
            dialog.EndModal(wx.ID_OK)
        view.on_net_select=selected
        dialog.ShowModal();dialog.Destroy()

    def filter_nets(self,event=None):
        from wayricad_runtime.net_filter import filter_combo
        current=self.fields['net'].GetValue()
        filter_combo(self.fields['net'],self._net_names,self.net_search.GetValue())
        if self.fields['net'].GetValue()!=current:self.net_changed(None)

    def changed(self,event):
        self._generation+=1;self._cancel.set();self._result_fingerprints=None
        self.report=None;self.path=None;self.export.Disable();self.results.DeleteAllItems();self.preview.show_result(SimpleNamespace(primary=None,mate=None))
        self.eye_preview.show_result(None)
        self.status.SetLabel('Inputs changed; run a fresh screen before exporting.')
        self._navigation_buttons()
        if event:event.Skip()

    def net_changed(self,event):
        with read_snapshot(self.board):pads=self.engine.pads_for_net(self.fields['net'].GetValue())
        for name in ('start','end'):self.fields[name].Clear();self.fields[name].AppendItems(pads)
        if pads:self.fields['start'].SetValue(pads[0]);self.fields['end'].SetValue(pads[-1])
        self.changed(None)

    def set_launch_selection(self,selection):
        net=selection.get('net','')
        with read_snapshot(self.board):names=self.engine.net_names()
        if net not in names:return
        self.fields['net'].SetValue(net);self.net_changed(None)
        with read_snapshot(self.board):pads=self.engine.pads_for_net(net)
        selected=[label for label in selection.get('pads',[]) if label in pads]
        if selected:self.fields['start'].SetValue(selected[0])
        if len(selected)>1:self.fields['end'].SetValue(selected[-1])
        elif selected and self.fields['end'].GetValue()==selected[0]:self.fields['end'].SetValue(next((p for p in pads if p!=selected[0]),selected[0]))

    def _navigation_buttons(self):
        ready=not self._closed and not self._navigation_busy
        self.select_route_button.Enable(ready and self.path is not None and self.report is not None)
        self.select_returns_button.Enable(ready and bool(self.return_nets.GetCheckedItems()))
        self.read_selection_button.Enable(ready)

    def _navigation_context(self):
        path=str(self.board.GetFileName())
        if not path:raise ValueError('Save the originating PCB before using cross-selection.')
        expected=None
        if self.saved_board:
            from .service import source_fingerprints
            current=source_fingerprints(path)
            if current!=self._source_fingerprints:
                self.changed(None);raise ValueError('Saved sources changed. Reopen Quick SI before cross-selection.')
            expected=current[str(Path(path).resolve())]
        return path,expected

    def _navigate(self,action,identifiers=(),nets=()):
        if self._closed or self._navigation_busy:return
        try:path,expected=self._navigation_context()
        except Exception as error:self.status.SetLabel(str(error));return
        # Everything captured here is plain data; only IPC runs in this thread.
        identifiers=tuple(str(value) for value in identifiers);nets=tuple(str(value) for value in nets)
        self._navigation_busy=True;self._navigation_serial+=1;serial=self._navigation_serial;generation=self._generation
        self._navigation_buttons();self.status.SetLabel('Reading PCB selection…' if action=='read' else 'Selecting reviewed items in the originating PCB Editor…')
        def work():
            payload=error=None
            try:
                from wayricad_runtime.analysis_selection import select_origin,selected_origin_ids
                if action=='read':payload=selected_origin_ids(path,expected_sha256=expected)
                else:payload=select_origin(path,identifiers,nets=nets,expected_sha256=expected,focus=True,return_details=True)
            except Exception as caught:error=caught
            if not self._closed:
                try:wx.CallAfter(self._navigation_finished,serial,generation,action,payload,error)
                except RuntimeError:pass
        self._navigation_thread=threading.Thread(target=work,daemon=True,name='Quick SI PCB navigation')
        try:self._navigation_thread.start()
        except RuntimeError as error:
            self._navigation_busy=False;self._navigation_buttons();self.status.SetLabel(str(error))

    def _navigation_finished(self,serial,generation,action,payload,error):
        if self._closed or serial!=self._navigation_serial:return
        self._navigation_busy=False;self._navigation_buttons()
        if generation!=self._generation:return
        if error is not None:
            from wayricad_runtime.context import redact_error
            self.status.SetLabel(redact_error(error));return
        try:
            self._navigation_context()
            if action=='read':self._apply_pcb_selection(payload)
            else:self.status.SetLabel(f"Selected {payload['count']} reviewed PCB items; focus {payload['focus']}.")
        except Exception as caught:self.status.SetLabel(str(caught))

    def select_route_in_pcb(self,event=None):
        if self.path is None or self.report is None:return
        ids=[str(item.m_Uuid.AsString()) for item in self.path.board_items]
        if not ids:self.status.SetLabel('No saved item UUIDs are available for this route.');return
        self._navigate('select',identifiers=ids)

    def select_returns_in_pcb(self,event=None):
        nets=[self.return_nets.GetString(i) for i in self.return_nets.GetCheckedItems()]
        if not nets:self.status.SetLabel('Choose explicit return nets first.');return
        self._navigate('select',nets=nets)

    def use_pcb_selection(self,event=None):self._navigate('read')

    def _pick_route_item(self,data):
        if not isinstance(data,tuple) or len(data)!=2 or data[1] is None:return
        self._navigate('select',identifiers=[str(data[1].m_Uuid.AsString())])

    def _apply_pcb_selection(self,identifiers):
        wanted={str(value).casefold() for value in identifiers}
        if not wanted:self.status.SetLabel('No PCB items are selected; inputs retained.');return
        index={};footprint_pads={};pad_labels={}
        def add(item):
            key=str(item.m_Uuid.AsString()).casefold();index.setdefault(key,[]).append(item);return key
        with read_snapshot(self.board):
            for footprint in self.board.GetFootprints():
                fp_key=add(footprint);children=[]
                for pad in footprint.Pads():
                    key=add(pad);children.append(key);pad_labels[key]=str(footprint.GetReference())+'.'+str(pad.GetNumber())
                footprint_pads[fp_key]=children
            for item in [*self.board.GetTracks(),*self.board.Zones()]:add(item)
            if any(len(index.get(key,[]))!=1 for key in wanted):
                raise ValueError('PCB selection no longer resolves uniquely in this saved snapshot. Save and reopen Quick SI; inputs retained.')
            expanded=wanted|{child for key in wanted for child in footprint_pads.get(key,[])}
            if any(len(index.get(key,[]))!=1 for key in expanded):raise ValueError('Selected footprint pads have ambiguous UUIDs in this snapshot; inputs retained.')
            net_pads={}
            for key in expanded:
                item=index[key][0];net=str(getattr(item,'GetNetname',lambda:'')())
                if net:net_pads.setdefault(net,[]).extend([pad_labels[key]] if key in pad_labels else [])
        previous=self.fields['net'].GetValue();source=self.fields['start'].GetValue();receiver=self.fields['end'].GetValue()
        plan,message=reverse_selection_plan(previous,net_pads,source,receiver)
        if plan is None:self.status.SetLabel(message);return
        if plan['net'] not in self._net_names:self.status.SetLabel('Selected net is absent from this snapshot; inputs retained.');return
        self.net_search.ChangeValue('');self.fields['net'].Set(self._net_names);self.fields['net'].SetValue(plan['net'])
        if plan['net']!=previous:
            self.net_changed(None)
            for name in ('start','end'):self.fields[name].SetSelection(wx.NOT_FOUND)
        else:self.changed(None)
        for name,value in plan['roles'].items():self.fields[name].SetValue(value)
        self.status.SetLabel(message+(' Selected pads: '+', '.join(plan['pads']) if plan['pads'] else ' No terminal direction was inferred from copper.'))

    def _destroyed(self,event):
        if event.GetEventObject() is self:
            self._closed=True;self._cancel.set()
        event.Skip()

    def cancel_run(self,event=None):
        self.changed(None);self.status.SetLabel('Cancelling saved-board analysis…')

    def _inputs(self):
        values={key:(float(control.GetValue()) if control.GetValue().strip() else None) for key,control in self.fields.items() if key not in ('net','start','end','reference') and (self.eye_enabled.GetValue() or not key.startswith('eye_'))}
        selected_returns=[self.return_nets.GetString(i) for i in range(self.return_nets.GetCount()) if self.return_nets.IsChecked(i)]
        if selected_returns:
            values['return_nets']=selected_returns
            values['return_terminal_ids']=[c.GetValue() for c in (self.return_source,self.return_sink) if c.GetValue()!='Not specified']
            values['return_terminal_roles']={role:c.GetValue() for role,c in [('source',self.return_source),('load',self.return_sink)] if c.GetValue()!='Not specified'}
        if self.eye_enabled.GetValue() and values['eye_bitrate_mbps'] is None:raise ValueError('Enter a positive eye bit rate.')
        return values

    def run(self,event=None):
        if self._busy or self._closed:return
        self.changed(None)
        try:
            values=self._inputs()
            if not self.saved_board:
                # Live SWIG/IPC board state is deliberately read only here on the
                # UI thread. Never substitute its saved file for unsaved edits.
                with wx.BusyCursor(),read_snapshot(self.board):
                    report,path=analyze(self.board,self.fields['net'].GetValue(),self.fields['start'].GetValue(),self.fields['end'].GetValue(),self.fields['reference'].GetValue(),**values)
                self._show_report(report,path,values)
                return
            from .service import source_fingerprints,run_job
            fingerprints=source_fingerprints(self.board.GetFileName())
            if fingerprints!=self._source_fingerprints:raise ValueError('The saved PCB or project rules changed. Reopen Quick SI before running.')
            request={'board_path':self.board.GetFileName(),'source_fingerprints':fingerprints,'net':self.fields['net'].GetValue(),
                     'start':self.fields['start'].GetValue(),'end':self.fields['end'].GetValue(),'reference':self.fields['reference'].GetValue(),'inputs':values}
            self._cancel=threading.Event();cancel=self._cancel;generation=self._generation;self._job_serial+=1;serial=self._job_serial
            self._busy=True;self.run_button.Disable();self.cancel_button.Enable();self.status.SetLabel('Screening saved PCB in a cancellable worker… You can change inputs or cancel.')
            def work():
                payload=error=None
                try:payload=run_job(request,cancelled=cancel.is_set)
                except Exception as caught:error=caught
                if not self._closed:
                    try:wx.CallAfter(self._finished,serial,generation,request,values,payload,error)
                    except RuntimeError:pass  # The wx application has already shut down.
            self._worker_thread=threading.Thread(target=work,daemon=True,name='Quick SI saved worker');self._worker_thread.start()
        except Exception as error:
            self._busy=False;self.run_button.Enable();self.cancel_button.Disable();self.status.SetLabel(str(error))

    def _finished(self,serial,generation,request,values,payload,error):
        if self._closed or serial!=self._job_serial:return
        self._busy=False;self.run_button.Enable();self.cancel_button.Disable()
        if generation!=self._generation:
            self.status.SetLabel('Analysis cancelled or inputs changed; run a fresh screen.');return
        if error is not None:self.status.SetLabel(str(error));return
        try:
            from .service import require_source,restore_path
            require_source(request)
            if payload.get('source_fingerprints')!=request['source_fingerprints']:raise ValueError('Worker result source does not match this request.')
            path=restore_path(payload,self.board)
            with read_snapshot(self.board):self._show_report(payload['report'],path,values)
            self._result_fingerprints=payload['source_fingerprints']
        except Exception as caught:
            self.changed(None);self.status.SetLabel(str(caught))

    def _show_report(self,report,path,values):
        self.report=report;self.path=path;self.preview.show_result(SimpleNamespace(primary=path,mate=None))
        pads={fp.GetReference()+'.'+pad.GetNumber():pad for fp in self.board.GetFootprints() for pad in fp.Pads() if pad.GetNetname()==path.net_name}
        self.preview.route_endpoints=[(pads[label].GetPosition().x/1e6,pads[label].GetPosition().y/1e6) for label in (path.start_pad,path.end_pad) if label in pads]
        for section in path.segments:
            if section.get('kind')=='zone' and 'start_mm' in section and 'end_mm' in section:
                self.preview.tracks.append((*section['start_mm'],*section['end_mm'],section['layer'],0,None))
        self.preview.fit();self.preview.Refresh()
        rows=[('Line model','User assumptions' if values['z0_ohm'] is not None or values['epsilon_eff'] is not None else 'Board geometry / unresolved terms retained'),('Route',f'{path.net_name}: {path.start_pad} → {path.end_pad}'),('Length / geometry',f'{path.length_mm:.3f} mm; {path.track_count} tracks, {path.via_count} vias, {path.zone_count} zones')]
        for key,label,unit in [('delay_ns','One-way delay',' ns'),('electrical_length_deg','Electrical length',' deg'),('delay_to_rise_ratio','Delay / rise time',''),('z0_ohm','Uniform Z0',' ohm'),('source_reflection','Source reflection Γ',''),('load_reflection','Load reflection Γ',''),('first_load_step_per_source_step','First load step / source step',''),('series_match_candidate_ohm','Series-match candidate',' ohm')]:
            value=report[key];rows.append((label,'Unknown / not applicable' if value is None else f'{value:.5g}'+unit))
        for endpoint,detail in report.get('endpoint_screen',{}).items():
            rows.append((endpoint.title()+' local line',f"{detail['z0_ohm']:.5g} ohm; local reflection {detail['reflection']:.5g} — {detail['basis']}"))
        summary=report.get('route_summary',{})
        for key,label,unit in [('resistance_dc_ohm','Path DC resistance',' ohm'),('resistance_ac_ohm','Path AC resistance',' ohm'),('modeled_impedance_length_mm','Length with section Z0 model',' mm'),('modeled_impedance_min_ohm','Modeled section Z0 minimum',' ohm'),('modeled_impedance_max_ohm','Modeled section Z0 maximum',' ohm')]:
            value=summary.get(key);rows.append((label,'Unresolved' if value is None else f'{value:.6g}'+unit))
        if report.get('return_path'):
            from wayricad_runtime.return_path import summary_text
            rows += [('Return-path review',line) for line in summary_text(report['return_path']).splitlines()]
        rows += [('Delay basis',report['delay_source']),('Z0 basis',report['z0_source'])]+[('Review',note) for note in report['notes']]
        if 'eye' in report:
            eye=report['eye'];self.eye_preview.show_result(eye);self.views.SetSelection(1)
            if eye.get('status')=='UNAVAILABLE':rows.append(('Eye unavailable',eye['reason']))
            else:
                rows += [('Eye center opening',f"{eye['center_opening_v']:.5g} V (sampled, ideal clock)"),('Eye sampled voltage range',f"{eye['min_v']:.5g} to {eye['max_v']:.5g} V")]
                rows += [('Eye model',note) for note in eye['limitations']]
        for label,value in rows:index=self.results.InsertItem(self.results.GetItemCount(),label);self.results.SetItem(index,1,value)
        self.status.SetLabel(report['status']+' — '+report['edge_screen']);self.export.Enable();self._navigation_buttons()

    def export_report(self,event):
        if self.report is None:return
        source=Path(self.board.GetFileName())
        if self.saved_board:
            from .service import source_fingerprints
            if self._result_fingerprints!=source_fingerprints(source):
                self.changed(None);self.status.SetLabel('Saved sources changed; reopen Quick SI and rerun before export.');return
        with wx.FileDialog(self,'Export Quick SI report',defaultDir=str(source.parent),defaultFile=source.stem+'-quick-si.html',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:write_report(dialog.GetPath(),html_report(self.report),source,'.html')
            except Exception as exc:wx.MessageBox(str(exc),'Report export failed',wx.OK|wx.ICON_ERROR,self)
