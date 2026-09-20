"""Focused native route, timing and termination-screen workflow."""
from pathlib import Path
from types import SimpleNamespace
import wx
from .measurement import TraceMeasurementEngine
from .quick_si import analyze,html_report
from .cli import write_report


class QuickSIPanel(wx.Panel):
    def __init__(self,parent,board,preview_class,saved_board=False):
        super().__init__(parent);self.board=board;self.saved_board=saved_board;self.report=None
        root=wx.BoxSizer(wx.HORIZONTAL)
        left=wx.ScrolledWindow(self,size=(340,-1));left.SetScrollRate(0,12);form=wx.BoxSizer(wx.VERTICAL)
        self.fields={}
        def row(name,label,value='',choices=None,parent=left,sizer=form):
            sizer.Add(wx.StaticText(parent,label=label),0,wx.TOP,7)
            control=wx.ComboBox(parent,choices=choices,value=value,style=wx.CB_READONLY) if choices is not None else wx.TextCtrl(parent,value=value)
            sizer.Add(control,0,wx.EXPAND|wx.TOP,3);self.fields[name]=control
            return control
        self.engine=TraceMeasurementEngine(board)
        nets=self.engine.net_names()
        row('net','Net',choices=nets);row('start','Source pad',choices=[]);row('end','Receiver pad',choices=[])
        row('rise_ns','Driver rise time (ns)','1');row('source_ohm','Driver resistance (ohm)','20')
        pane=wx.CollapsiblePane(left,label='Line and load assumptions');details=wx.BoxSizer(wx.VERTICAL);host=pane.GetPane()
        for name,label,value in [('frequency_mhz','Frequency (MHz)','100'),('load_ohm','Load resistance (ohm; blank = open)',''),('z0_ohm','Assumed uniform Z0 (ohm; blank = geometry)',''),('epsilon_eff','Assumed effective Er (blank = stackup)','')]:row(name,label,value,parent=host,sizer=details)
        row('reference','Reference layer','Auto',['Auto']+self.engine.available_layers(),host,details)
        host.SetSizer(details);form.Add(pane,0,wx.EXPAND|wx.TOP,10);pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        eye_pane=wx.CollapsiblePane(left,label='Illustrative eye (optional)');eye_form=wx.BoxSizer(wx.VERTICAL);eye_host=eye_pane.GetPane()
        self.eye_enabled=wx.CheckBox(eye_host,label='Generate ideal NRZ eye and step response')
        eye_form.Add(self.eye_enabled,0,wx.TOP,6)
        row('eye_bitrate_mbps','Bit rate (Mbps)','1000',parent=eye_host,sizer=eye_form)
        row('eye_swing_v','Source open-circuit swing (V)','1',parent=eye_host,sizer=eye_form)
        eye_host.SetSizer(eye_form);form.Add(eye_pane,0,wx.EXPAND|wx.TOP,10)
        eye_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        self.eye_enabled.Bind(wx.EVT_CHECKBOX,self.changed)
        note=wx.StaticText(left,label='Inputs are assumptions. The optional eye uses a uniform lossless line, ideal clock and resistive endpoints. No IBIS, coupling or protocol signoff.');note.Wrap(300);form.Add(note,0,wx.EXPAND|wx.TOP,10)
        run=wx.Button(left,label='Screen selected path');run.Bind(wx.EVT_BUTTON,self.run);form.Add(run,0,wx.EXPAND|wx.TOP,12)
        self.export=wx.Button(left,label='Export local HTML report');self.export.Disable();self.export.Bind(wx.EVT_BUTTON,self.export_report);form.Add(self.export,0,wx.EXPAND|wx.TOP,6)
        left.SetSizer(form);root.Add(left,0,wx.EXPAND|wx.ALL,10)
        right=wx.BoxSizer(wx.VERTICAL);self.views=wx.Notebook(self)
        route=wx.Panel(self.views);route_sizer=wx.BoxSizer(wx.VERTICAL);self.preview=preview_class(route);route_sizer.Add(self.preview,1,wx.EXPAND)
        from .preview_kit import add_zoom_toolbar
        add_zoom_toolbar(route,self.preview,route_sizer);route.SetSizer(route_sizer);self.views.AddPage(route,'Route')
        from .eye_ui import EyePanel
        self.eye_preview=EyePanel(self.views);self.views.AddPage(self.eye_preview,'Eye / step');right.Add(self.views,2,wx.EXPAND)
        self.status=wx.StaticText(self,label='Choose the source and receiver, review the inputs, then screen the path.');right.Add(self.status,0,wx.EXPAND|wx.ALL,7)
        self.results=wx.ListCtrl(self,style=wx.LC_REPORT);self.results.InsertColumn(0,'Measure',width=210);self.results.InsertColumn(1,'Result / evidence',width=620);right.Add(self.results,1,wx.EXPAND)
        root.Add(right,1,wx.EXPAND|wx.ALL,10);self.SetSizer(root)
        for name,control in self.fields.items():
            control.Bind(wx.EVT_COMBOBOX if isinstance(control,wx.ComboBox) else wx.EVT_TEXT,self.changed)
        self.fields['net'].Bind(wx.EVT_COMBOBOX,self.net_changed)
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

    def changed(self,event):
        self.report=None;self.export.Disable();self.results.DeleteAllItems();self.preview.show_result(SimpleNamespace(primary=None,mate=None))
        self.eye_preview.show_result(None)
        self.status.SetLabel('Inputs changed; run a fresh screen before exporting.')
        if event:event.Skip()

    def net_changed(self,event):
        pads=self.engine.pads_for_net(self.fields['net'].GetValue())
        for name in ('start','end'):self.fields[name].Clear();self.fields[name].AppendItems(pads)
        if pads:self.fields['start'].SetValue(pads[0]);self.fields['end'].SetValue(pads[-1])
        self.changed(None)

    def set_launch_selection(self,selection):
        net=selection.get('net','')
        if net not in self.engine.net_names():return
        self.fields['net'].SetValue(net);self.net_changed(None)
        pads=self.engine.pads_for_net(net);selected=[label for label in selection.get('pads',[]) if label in pads]
        if selected:self.fields['start'].SetValue(selected[0])
        if len(selected)>1:self.fields['end'].SetValue(selected[-1])
        elif selected and self.fields['end'].GetValue()==selected[0]:self.fields['end'].SetValue(next((p for p in pads if p!=selected[0]),selected[0]))

    def run(self,event):
        self.changed(None)
        try:
            values={key:(float(control.GetValue()) if control.GetValue().strip() else None) for key,control in self.fields.items() if key not in ('net','start','end','reference') and (self.eye_enabled.GetValue() or not key.startswith('eye_'))}
            if self.eye_enabled.GetValue() and values['eye_bitrate_mbps'] is None:raise ValueError('Enter a positive eye bit rate.')
            with wx.BusyCursor():
                report,path=analyze(self.board,self.fields['net'].GetValue(),self.fields['start'].GetValue(),self.fields['end'].GetValue(),self.fields['reference'].GetValue(),**values)
            self.report=report;self.preview.show_result(SimpleNamespace(primary=path,mate=None))
            pads={fp.GetReference()+'.'+pad.GetNumber():pad for fp in self.board.GetFootprints() for pad in fp.Pads() if pad.GetNetname()==path.net_name}
            self.preview.route_endpoints=[(pads[label].GetPosition().x/1e6,pads[label].GetPosition().y/1e6) for label in (path.start_pad,path.end_pad) if label in pads]
            for section in path.segments:
                if section.get('kind')=='zone' and 'start_mm' in section and 'end_mm' in section:
                    self.preview.tracks.append((*section['start_mm'],*section['end_mm'],section['layer'],0,None))
            self.preview.fit();self.preview.Refresh()
            rows=[('Line model','User assumptions' if values['z0_ohm'] is not None or values['epsilon_eff'] is not None else 'Board geometry / unresolved terms retained'),('Route',f'{path.net_name}: {path.start_pad} → {path.end_pad}'),('Length / geometry',f'{path.length_mm:.3f} mm; {path.track_count} tracks, {path.via_count} vias, {path.zone_count} zones')]
            for key,label,unit in [('delay_ns','One-way delay',' ns'),('electrical_length_deg','Electrical length',' deg'),('delay_to_rise_ratio','Delay / rise time',''),('z0_ohm','Uniform Z0',' ohm'),('source_reflection','Source reflection Γ',''),('load_reflection','Load reflection Γ',''),('first_load_step_per_source_step','First load step / source step',''),('series_match_candidate_ohm','Series-match candidate',' ohm')]:
                value=report[key];rows.append((label,'Unknown / not applicable' if value is None else f'{value:.5g}'+unit))
            rows += [('Delay basis',report['delay_source']),('Z0 basis',report['z0_source'])]+[('Review',note) for note in report['notes']]
            if 'eye' in report:
                eye=report['eye'];self.eye_preview.show_result(eye);self.views.SetSelection(1)
                if eye.get('status')=='UNAVAILABLE':rows.append(('Eye unavailable',eye['reason']))
                else:
                    rows += [('Eye center opening',f"{eye['center_opening_v']:.5g} V (sampled, ideal clock)"),('Eye sampled voltage range',f"{eye['min_v']:.5g} to {eye['max_v']:.5g} V")]
                    rows += [('Eye model',note) for note in eye['limitations']]
            for label,value in rows:index=self.results.InsertItem(self.results.GetItemCount(),label);self.results.SetItem(index,1,value)
            self.status.SetLabel(report['status']+' — '+report['edge_screen']);self.export.Enable()
        except Exception as exc:self.status.SetLabel(str(exc));wx.MessageBox(str(exc),'Quick SI',wx.OK|wx.ICON_ERROR,self)

    def export_report(self,event):
        if self.report is None:return
        source=Path(self.board.GetFileName())
        with wx.FileDialog(self,'Export Quick SI report',defaultDir=str(source.parent),defaultFile=source.stem+'-quick-si.html',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:write_report(dialog.GetPath(),html_report(self.report),source,'.html')
            except Exception as exc:wx.MessageBox(str(exc),'Report export failed',wx.OK|wx.ICON_ERROR,self)
