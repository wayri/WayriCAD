"""Focused native route, timing and termination-screen workflow."""
from pathlib import Path
from types import SimpleNamespace
import threading
import copy
from datetime import datetime
from uuid import uuid4
from wayricad_runtime.ipc import read_snapshot
import wx
from wayricad_runtime.readable_choice import ReadableComboBox
from .measurement import TraceMeasurementEngine
from .quick_si import analyze


def _model_source_stamps(paths):
    """Cheap callback freshness check; the exporter validates full file hashes."""
    stamps={}
    for raw in set(paths):
        path=Path(raw).resolve(strict=True)
        info=path.stat()
        stamps[str(path)]=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    return stamps


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
        self._source_fingerprints=None;self.study_cases=[];self.study_report=None;self.crosstalk_pairs=[]
        self._circuit_generation=0;self._circuit_busy=False
        if saved_board:
            from .service import source_fingerprints
            self._source_fingerprints=source_fingerprints(board.GetFileName())
        self.Bind(wx.EVT_WINDOW_DESTROY,self._destroyed)
        root=wx.BoxSizer(wx.HORIZONTAL)
        self.workspace_splitter=wx.SplitterWindow(self,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        self.workspace_splitter.SetMinimumPaneSize(self.FromDIP(250))
        self.workspace_splitter.SetSashGravity(0.)
        left=wx.ScrolledWindow(self.workspace_splitter,size=(340,-1));self.inputs=left;left.SetScrollRate(0,12);form=wx.BoxSizer(wx.VERTICAL)
        self.fields={}
        def row(name,label,value='',choices=None,parent=left,sizer=form):
            sizer.Add(wx.StaticText(parent,label=label),0,wx.TOP,7)
            control=ReadableComboBox(parent,choices=choices,value=value,style=wx.CB_READONLY) if choices is not None else wx.TextCtrl(parent,value=value)
            control.SetMinSize((1,-1))
            sizer.Add(control,0,wx.EXPAND|wx.TOP,3);self.fields[name]=control
            return control
        with read_snapshot(board):
            self.engine=TraceMeasurementEngine(board)
            return_terminals=[];selected=[]
            for footprint in board.GetFootprints():
                reference=str(footprint.GetReference());owner=str(footprint.m_Uuid.AsString())
                for pad in footprint.Pads():
                    net=str(pad.GetNetname())
                    if not net:continue
                    label=reference+'.'+str(pad.GetNumber())
                    return_terminals.append({'label':label,'net':net,'reference':reference,
                        'id':str(pad.m_Uuid.AsString()),'footprint_uuid':owner})
                    if pad.IsSelected():selected.append((net,label))
            nets=sorted({terminal['net'] for terminal in return_terminals},key=self.engine._natural_key)
        self.setup_button=wx.Button(left,label='Set up path and response…')
        self.setup_button.SetToolTip('Review source/receiver, same-part pads, line assumptions and illustrative eye together. No board changes.')
        self.setup_button.Bind(wx.EVT_BUTTON,self.setup_path);form.Add(self.setup_button,0,wx.EXPAND|wx.TOP,5)
        row('net','Net',choices=nets);self._net_names=nets
        self.net_search=wx.SearchCtrl(left);self.net_search.SetHint('Find net · * wildcard, ~ fuzzy');form.Add(self.net_search,0,wx.EXPAND|wx.TOP,5);self.net_search.Bind(wx.EVT_TEXT,self.filter_nets)
        pick=wx.Button(left,label='Select net on board');form.Add(pick,0,wx.EXPAND|wx.TOP,5);pick.Bind(wx.EVT_BUTTON,self.select_board_net)
        row('start','Source pad',choices=[]);row('end','Receiver pad',choices=[])
        with read_snapshot(board):
            layers=self.engine.available_layers()
        self._setup_terminals=return_terminals
        self._setup_pads={}
        for terminal in return_terminals:self._setup_pads.setdefault(terminal['net'],[]).append(terminal['label'])
        for pads in self._setup_pads.values():pads.sort(key=self.engine._natural_key)
        from .return_setup_ui import ReturnSetupPanel
        self.return_setup=ReturnSetupPanel(left,nets,return_terminals,layers,
            lambda:self.changed(None),lambda:(left.FitInside(),self.Layout()))
        self.return_nets=self.return_setup.nets;self.return_source=self.return_setup.source;self.return_sink=self.return_setup.sink
        self.fields['reference']=self.return_setup.reference
        form.Add(self.return_setup,0,wx.EXPAND|wx.TOP,5)

        ibis_pane=wx.CollapsiblePane(left,label='IBIS models for KiCad circuit export',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        from .ibis_ui import IbisPane
        self.ibis=IbisPane(ibis_pane.GetPane(),self._circuit_inputs_changed)
        ibis_layout=wx.BoxSizer(wx.VERTICAL);ibis_layout.Add(self.ibis,1,wx.EXPAND)
        ibis_pane.GetPane().SetSizer(ibis_layout);form.Add(ibis_pane,0,wx.EXPAND|wx.TOP,10)
        ibis_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        row('rise_ns','Driver rise time (ns)','1');row('source_ohm','Driver resistance (ohm)','20')
        pane=wx.CollapsiblePane(left,style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE,label='Line and load assumptions');details=wx.BoxSizer(wx.VERTICAL);host=pane.GetPane()
        for name,label,value in [('frequency_mhz','Frequency (MHz)','100'),('load_ohm','Load resistance (ohm; blank = open)',''),('z0_ohm','Assumed uniform Z0 (ohm; blank = geometry)',''),('epsilon_eff','Assumed effective Er (blank = stackup)','')]:row(name,label,value,parent=host,sizer=details)
        host.SetSizer(details);form.Add(pane,0,wx.EXPAND|wx.TOP,10);pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        from wayricad_runtime.readable_choice import SearchableCheckListBox
        from wayricad_runtime.searchable_selection import searchable_row
        study_pane=wx.CollapsiblePane(left,label='Multi-net study',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        study_host=study_pane.GetPane();study_form=wx.BoxSizer(wx.VERTICAL)
        study_note=wx.StaticText(study_host,label='Choose nets, edit source/receiver assignments, then optionally configure directed local crosstalk pairs.');study_note.Wrap(295)
        study_form.Add(study_note,0,wx.EXPAND|wx.BOTTOM,5)
        self.study_nets=SearchableCheckListBox(study_host,choices=nets,size=(-1,130));study_form.Add(searchable_row(self.study_nets),0,wx.EXPAND)
        self.study_add=wx.Button(study_host,label='Add checked nets to study')
        self.study_edit=wx.Button(study_host,label='Edit study cases…')
        self.study_returns=wx.Button(study_host,label='Use this return setup for study cases')
        self.study_returns.SetToolTip('Apply selected return nets to every case. Optional per-case return pins are cleared so unrelated endpoint assumptions are not copied.')
        self.crosstalk_edit=wx.Button(study_host,label='Configure crosstalk pairs (optional)…')
        self.crosstalk_results=wx.Button(study_host,label='Review crosstalk results…');self.crosstalk_results.Disable()
        self.study_run=wx.Button(study_host,label='Run multi-net study')
        for control,handler in [(self.study_add,self._add_study_cases),(self.study_returns,self._apply_study_returns),(self.study_edit,self._edit_study_cases),(self.crosstalk_edit,self._edit_crosstalk),(self.study_run,self.run_study),(self.crosstalk_results,self._show_crosstalk)]:
            control.Bind(wx.EVT_BUTTON,handler);study_form.Add(control,0,wx.EXPAND|wx.TOP,5)
        study_host.SetSizer(study_form);form.Add(study_pane,0,wx.EXPAND|wx.TOP,10)
        study_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.Layout(),left.FitInside(),self.Layout()))

        eye_pane=wx.CollapsiblePane(left,style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE,label='Illustrative eye (optional)');eye_form=wx.BoxSizer(wx.VERTICAL);eye_host=eye_pane.GetPane()
        self.eye_enabled=wx.CheckBox(eye_host,label='Generate ideal NRZ eye and step response')
        eye_form.Add(self.eye_enabled,0,wx.TOP,6)
        row('eye_bitrate_mbps','Bit rate (Mbps)','1000',parent=eye_host,sizer=eye_form)
        row('eye_swing_v','Source open-circuit swing (V)','1',parent=eye_host,sizer=eye_form)
        eye_host.SetSizer(eye_form);form.Add(eye_pane,0,wx.EXPAND|wx.TOP,10)
        eye_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(left.FitInside(),self.Layout()))
        self.eye_enabled.Bind(wx.EVT_CHECKBOX,self.changed)
        note=wx.StaticText(left,label='Inputs are assumptions. The optional eye uses a uniform lossless line, ideal clock and resistive endpoints. It does not use IBIS export models or establish coupling or protocol signoff.');note.Wrap(300);form.Add(note,0,wx.EXPAND|wx.TOP,10)
        self.run_button=wx.Button(left,label='Screen selected path');self.run_button.Bind(wx.EVT_BUTTON,self.run);form.Add(self.run_button,0,wx.EXPAND|wx.TOP,12)
        self.cancel_button=wx.Button(left,label='Cancel analysis');self.cancel_button.Disable();self.cancel_button.Bind(wx.EVT_BUTTON,self.cancel_run);form.Add(self.cancel_button,0,wx.EXPAND|wx.TOP,5)
        self.export=wx.Button(left,label='Save results / Pocket KiVi…');self.export.SetToolTip('Save the report, complete numerical JSON and a portable Pocket KiVi copy for verified saved-board results.');self.export.Disable();self.export.Bind(wx.EVT_BUTTON,self.export_report);form.Add(self.export,0,wx.EXPAND|wx.TOP,6)
        from wayricad_runtime.project_results_ui import add_project_results
        self.project_results=add_project_results(self,left,form,'quick-si',board.GetFileName(),
            lambda:[('SI route / eye',self.report),('Multi-net SI study',self.study_report)],
            certify=bool(saved_board),status=lambda text:self.status.SetLabel(text),module_file=__file__)
        self.blender=wx.Button(left,label='Blender…');self.blender.Disable();self.blender.Bind(wx.EVT_BUTTON,self.export_blender)
        self.blender.SetToolTip('Export current route evidence for Blender; no traveling-wave simulation is inferred.')
        form.Add(self.blender,0,wx.EXPAND|wx.TOP,6)
        self.export_circuit_button=wx.Button(left,label='Export KiCad circuit…');self.export_circuit_button.Disable()
        self.export_circuit_button.Bind(wx.EVT_BUTTON,lambda event:self._start_circuit_export(False));form.Add(self.export_circuit_button,0,wx.EXPAND|wx.TOP,6)
        self.copy_circuit_button=wx.Button(left,label='Copy circuit…');self.copy_circuit_button.Disable()
        self.copy_circuit_button.SetToolTip('Create a model bundle, then copy KiCad schematic clipboard text.')
        self.copy_circuit_button.Bind(wx.EVT_BUTTON,lambda event:self._start_circuit_export(True));form.Add(self.copy_circuit_button,0,wx.EXPAND|wx.TOP,6)
        self.select_route_button=wx.Button(left,label='Select route in PCB');self.select_route_button.Disable()
        self.select_returns_button=wx.Button(left,label='Select return nets in PCB');self.select_returns_button.Disable()
        self.read_selection_button=wx.Button(left,label='Use PCB selection')
        for control,handler in [(self.select_route_button,self.select_route_in_pcb),(self.select_returns_button,self.select_returns_in_pcb),(self.read_selection_button,self.use_pcb_selection)]:
            control.Bind(wx.EVT_BUTTON,handler);form.Add(control,0,wx.EXPAND|wx.TOP,5)
        from .help_utils import open_help
        help_button=wx.Button(left,wx.ID_HELP,label='Help: Quick SI workflow')
        help_button.Bind(wx.EVT_BUTTON,lambda event:open_help(self));form.Add(help_button,0,wx.EXPAND|wx.TOP,8)
        left.SetSizer(form)
        self.results_splitter=wx.SplitterWindow(self.workspace_splitter,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        self.results_splitter.SetMinimumPaneSize(self.FromDIP(120));self.results_splitter.SetSashGravity(.7)
        view_host=wx.Panel(self.results_splitter);right=wx.BoxSizer(wx.VERTICAL);self.views=wx.Notebook(view_host)
        route=wx.Panel(self.views);route_sizer=wx.BoxSizer(wx.VERTICAL);self.preview=preview_class(route);self.preview.on_pick=self._pick_route_item;route_sizer.Add(self.preview,1,wx.EXPAND)
        from .preview_kit import add_zoom_toolbar
        add_zoom_toolbar(route,self.preview,route_sizer);route.SetSizer(route_sizer);self.views.AddPage(route,'Route')
        from .eye_ui import EyePanel
        self.eye_preview=EyePanel(self.views);self.views.AddPage(self.eye_preview,'Eye / step');right.Add(self.views,2,wx.EXPAND)
        self.study_choice=ReadableComboBox(view_host,choices=[],style=wx.CB_READONLY)
        self.study_choice.SetToolTip('Select one completed study case to inspect its own route, return audit and results.')
        self.study_choice.Hide();self.study_choice.Bind(wx.EVT_COMBOBOX,self._select_study_case)
        right.Add(self.study_choice,0,wx.EXPAND|wx.TOP,5)
        self.status=wx.StaticText(view_host,label='Choose the source and receiver, review the inputs, then screen the path.');right.Add(self.status,0,wx.EXPAND|wx.ALL,7)
        self.results=wx.ListCtrl(self.results_splitter,style=wx.LC_REPORT);self.results.InsertColumn(0,'Measure',width=210);self.results.InsertColumn(1,'Result / evidence',width=620)
        self.results.SetMinSize((-1, 175))
        view_host.SetSizer(right)
        self.results_splitter.SplitHorizontally(view_host,self.results,-self.FromDIP(200))
        self.workspace_splitter.SplitVertically(left,self.results_splitter,self.FromDIP(350))
        root.Add(self.workspace_splitter,1,wx.EXPAND|wx.ALL,8);self.SetSizer(root)
        from wayricad_runtime.layout import install_accessibility
        install_accessibility(self,Path(__file__).with_name('help.html'))
        for name,control in self.fields.items():
            control.Bind(wx.EVT_COMBOBOX if isinstance(control,wx.ComboBox) else wx.EVT_TEXT,self.changed)
        self.fields['net'].Bind(wx.EVT_COMBOBOX,self.net_changed)
        counts={}
        for terminal in return_terminals:counts[terminal['net']]=counts.get(terminal['net'],0)+1
        with read_snapshot(board):
            selected_tracks=[track.GetNetname() for track in board.GetTracks() if track.IsSelected() and track.GetNetname()]
        candidate=next((name for name in nets if counts.get(name)==2),next((name for name in nets if counts.get(name,0)>=2),nets[0] if nets else ''))
        self.fields['net'].SetValue(selected[0][0] if selected else selected_tracks[0] if selected_tracks else candidate);self.net_changed(None)
        if selected:self.set_launch_selection({'net':selected[0][0],'pads':[label for net,label in selected if net==selected[0][0]]})
        left.FitInside()

    def setup_path(self,event=None):
        if self._closed:return
        from .setup_guide import setup_dialog
        selection=setup_dialog(self,self._setup_pads,self._setup_terminals,
            {key:self.fields[key].GetValue() for key in ('net','start','end')},
            {key:control.GetValue() for key,control in self.fields.items() if key not in ('net','start','end','reference')},
            self.eye_enabled.GetValue(),self.return_setup.selected_nets())
        if selection is None:return
        self.net_search.ChangeValue('');self.fields['net'].Set(self._net_names)
        self.fields['net'].SetValue(selection['net']);self.net_changed(None)
        for key in ('start','end'):self.fields[key].SetValue(selection[key])
        for key,value in selection['values'].items():self.fields[key].ChangeValue(value)
        self.eye_enabled.SetValue(selection['eye_enabled']);self.changed(None)
        self.status.SetLabel('Setup applied. Review return/IBIS inputs as needed, then screen the path.')
        if selection['run']:self.run()

    def _review_return_nets(self):
        if self.study_report and self.study_choice.GetSelection()!=wx.NOT_FOUND:
            return self.study_report['cases'][self.study_choice.GetSelection()].get('inputs',{}).get('return_nets',[])
        return [self.return_nets.GetString(i) for i in self.return_nets.GetCheckedItems()]

    def _add_study_cases(self,event=None):
        try:
            values=self._inputs()
            selected=[self.study_nets.GetString(i) for i in self.study_nets.GetCheckedItems()]
            if not selected:raise ValueError('Check at least one study net first.')
            existing={case['net'] for case in self.study_cases}
            selected=[net for net in selected if net not in existing]
            if len(self.study_cases)+len(selected)>64:raise ValueError('Use at most 64 cases per study.')
            for net in selected:
                current=net==self.fields['net'].GetValue()
                self.study_cases.append({'id':'case-'+str(len(self.study_cases)+1),'net':net,
                    'start':self.fields['start'].GetValue() if current else '',
                    'end':self.fields['end'].GetValue() if current else '',
                    'reference':self.fields['reference'].GetValue() or 'Auto','inputs':dict(values)})
            self.changed(None);self.study_edit.SetLabel('Edit study cases ('+str(len(self.study_cases))+')…')
            self.status.SetLabel('Study prepared. Edit all source/receiver pads; no direction is inferred for newly added nets.')
        except Exception as error:self.status.SetLabel(str(error))

    def _apply_study_returns(self,event=None):
        if not self.study_cases:
            self.status.SetLabel('Add the selected study nets first, then apply their return setup.');return
        try:
            from .return_case_setup import apply_return_nets
            self.study_cases=apply_return_nets(self.study_cases,self.return_setup.selected_nets())
            self.changed(None)
            self.status.SetLabel('Return settings applied to '+str(len(self.study_cases))+
                ' cases. Optional return pins cleared; edit only cases that need a different return.')
        except ValueError as error:self.status.SetLabel(str(error))

    def _edit_study_cases(self,event=None):
        if not self.study_cases:self._add_study_cases()
        if not self.study_cases:return
        import copy
        import wx.grid as gridlib
        from wayricad_runtime.layout import install_accessibility
        dialog=wx.Dialog(self,title='Quick SI · Explicit independent route cases',size=(1080,670),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='Each row is independent. Start/end use Reference.Pad (inspect the net in the single-route form). Return nets are comma-separated; return pads belong to those nets. Blank source/receiver remains an explicit case error. Delete checked rows to remove cases.')
        note.Wrap(980);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        grid=gridlib.Grid(dialog);columns=['Remove','Case','Net','Source pad','Receiver pad','Reference','Rise ns','Frequency MHz','Driver Ω','Load Ω','Assumed Z0 Ω','Assumed Er','Return nets','Source return','Receiver return']
        grid.CreateGrid(len(self.study_cases),len(columns))
        for col,name in enumerate(columns):grid.SetColLabelValue(col,name);grid.SetColSize(col,140 if col not in (0,6,8,9,11) else 95)
        for row,case in enumerate(self.study_cases):
            inputs=case.get('inputs',{});roles=inputs.get('return_terminal_roles',{})
            values=['',case['id'],case['net'],case.get('start',''),case.get('end',''),case.get('reference','Auto'),
                    inputs.get('rise_ns',1),inputs.get('frequency_mhz',100),inputs.get('source_ohm',20),inputs.get('load_ohm'),inputs.get('z0_ohm'),inputs.get('epsilon_eff'),
                    ', '.join(inputs.get('return_nets',[])),roles.get('source',''),roles.get('load','')]
            for col,value in enumerate(values):grid.SetCellValue(row,col,'' if value is None else str(value))
            grid.SetCellEditor(row,0,gridlib.GridCellBoolEditor());grid.SetCellRenderer(row,0,gridlib.GridCellBoolRenderer())
        layout.Add(grid,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
        install_accessibility(dialog)
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            grid.SaveEditControlValue();cases=[]
            for row,original in enumerate(self.study_cases):
                cell=lambda col:grid.GetCellValue(row,col).strip()
                if cell(0)=='1':continue
                case=copy.deepcopy(original);case.update(id=cell(1),net=cell(2),start=cell(3),end=cell(4),reference=cell(5) or 'Auto')
                inputs=case['inputs']
                for col,key in [(6,'rise_ns'),(7,'frequency_mhz'),(8,'source_ohm'),(9,'load_ohm'),(10,'z0_ohm'),(11,'epsilon_eff')]:inputs[key]=float(cell(col)) if cell(col) else None
                returns=[value.strip() for value in cell(12).split(',') if value.strip()]
                for key in ('return_nets','return_terminal_roles','return_terminal_ids'):inputs.pop(key,None)
                if returns or cell(13) or cell(14):
                    roles={key:value for key,value in [('source',cell(13)),('load',cell(14))] if value}
                    inputs.update(return_nets=returns,return_terminal_roles=roles,return_terminal_ids=list(roles.values()))
                cases.append(case)
            if cases:
                from .study import cases_from_config
                cases_from_config({'cases':cases})
            self.study_cases=cases;self.changed(None);self.study_edit.SetLabel('Edit study cases ('+str(len(cases))+')…')
        except Exception as error:self.status.SetLabel('Study edit not applied: '+str(error))
        finally:dialog.Destroy()

    def _edit_crosstalk(self,event=None):
        import copy
        import wx.grid as gridlib
        from .crosstalk import checked_pairs
        if len(self.study_cases)<2:
            self.status.SetLabel('Add and assign at least two route cases before choosing a directed crosstalk pair.');return
        dialog=wx.Dialog(self,title='Local crosstalk · Explicit aggressor and victim',size=(1090,560),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='Local equal-width parallel sections only. saved-stripline checks the actual stackup and two filled bounding planes (Height/Er unused). homogeneous-plane is a what-if model requiring one plane, center-to-plane Height and Er. Four section ports match sqrt(Zeven × Zodd); route driver/load settings do not apply. Swing is open-circuit; rise is 10–90%.')
        note.Wrap(1020);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        columns=['Remove','Pair ID','Aggressor case','Victim case','Rise ns','Swing V','Model','Plane 1','Plane 2','Height mm','Er']
        grid=gridlib.Grid(dialog);grid.CreateGrid(max(1,len(self.crosstalk_pairs)),len(columns))
        for i,name in enumerate(columns):grid.SetColLabelValue(i,name);grid.SetColSize(i,125 if i in (1,2,3,6) else 95)
        ids=[case['id'] for case in self.study_cases]
        layers=[str(self.board.GetLayerName(layer)) for layer in self.board.GetEnabledLayers().CuStack()]
        def fill(row,pair):
            ref=pair.get('reference',{})
            values=['',pair.get('id','coupling-'+str(row+1)),pair.get('aggressor',''),pair.get('victim',''),pair.get('rise_ns',1),pair.get('swing_v',1),ref.get('model','saved-stripline'),ref.get('layer',''),ref.get('upper_layer',''),ref.get('height_mm',''),ref.get('epsilon_r','')]
            for col,value in enumerate(values):grid.SetCellValue(row,col,str(value))
            grid.SetCellEditor(row,0,gridlib.GridCellBoolEditor());grid.SetCellRenderer(row,0,gridlib.GridCellBoolRenderer())
            for col in (2,3):grid.SetCellEditor(row,col,gridlib.GridCellChoiceEditor(ids))
            grid.SetCellEditor(row,6,gridlib.GridCellChoiceEditor(['saved-stripline','homogeneous-plane']))
            for col in (7,8):grid.SetCellEditor(row,col,gridlib.GridCellChoiceEditor(layers))
        for row,pair in enumerate(self.crosstalk_pairs or [{}]):fill(row,pair)
        layout.Add(grid,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        add=wx.Button(dialog,label='Add directed pair')
        def add_row(event):
            if grid.GetNumberRows()<64:grid.AppendRows(1);fill(grid.GetNumberRows()-1,{})
        add.Bind(wx.EVT_BUTTON,add_row);layout.Add(add,0,wx.ALL,10)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            grid.SaveEditControlValue();pairs=[]
            for row in range(grid.GetNumberRows()):
                cell=lambda col:grid.GetCellValue(row,col).strip()
                if cell(0)=='1':continue
                ref={'model':cell(6),'layer':cell(7)}
                if cell(6)=='saved-stripline':ref['upper_layer']=cell(8)
                else:ref.update(height_mm=float(cell(9)),epsilon_r=float(cell(10)))
                pairs.append({'id':cell(1),'aggressor':cell(2),'victim':cell(3),'rise_ns':float(cell(4)),'swing_v':float(cell(5)),'reference':ref})
            self.crosstalk_pairs=checked_pairs({'crosstalk':pairs},self.study_cases)
            self.changed(None);self.crosstalk_edit.SetLabel('Configure crosstalk pairs ('+str(len(pairs))+')…')
            self.status.SetLabel('Directed local coupling inputs saved. Run the multi-net study to refresh all evidence.')
        except Exception as error:self.status.SetLabel('Crosstalk inputs not applied: '+str(error))
        finally:dialog.Destroy()

    def _show_crosstalk(self,event=None):
        if not self.study_report:return
        lines=['LOCAL COUPLED-SECTION SCREENING','Section peaks are not summed or cascaded into whole-route terminal waveforms.','']
        for pair in self.study_report.get('crosstalk',[]):
            lines.extend([pair['id']+' · '+pair['aggressor']+' → '+pair['victim']+' · '+pair['status'],
                          'Reference: '+str(pair['reference']),*pair['limitations']])
            for section in pair['sections']:
                peak=(f"< {section['next_numerical_resolution_v']*1000:.3g} mV numerical floor" if section['coupling_numerical_status']=='BELOW_NUMERICAL_FLOOR' else f"{section['next_peak_v']*1000:.4g} mV")
                lines.append(f"{section['layer']} · overlap {section['length_mm']:.6g} mm · gap {section['gap_mm']:.6g} mm · {section['direction']} direction · NEXT {peak} at victim {section['near_victim_role']} · FEXT 0 (ideal homogeneous model only) · delay {section['delay_ns']:.6g} ns · coupling refinement Δk={section['coupling_refinement_absolute']:.3g}")
            for role,coverage in pair.get('coverage',{}).items():
                lines.append(f"{role}: {coverage['supported_overlap_mm']:.6g} mm supported overlap / {coverage['route_length_mm']:.6g} mm route; {coverage['unmodeled_length_mm']:.6g} mm unmodeled.")
            lines.extend('Unresolved: '+entry['reason'] for entry in pair['unresolved'])
            lines.append('')
        dialog=wx.Dialog(self,title='Crosstalk results · Local assumptions and coverage',size=(1000,650),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL);text=wx.TextCtrl(dialog,value='\n'.join(lines),style=wx.TE_MULTILINE|wx.TE_READONLY|wx.HSCROLL)
        layout.Add(text,1,wx.EXPAND|wx.ALL,10);layout.Add(dialog.CreateButtonSizer(wx.OK),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
        dialog.ShowModal();dialog.Destroy()

    def run_study(self,event=None):
        if self._busy or self._closed or self._circuit_busy:return
        self.changed(None)
        try:
            import copy
            from .study import cases_from_config,run_study
            config={'cases':copy.deepcopy(self.study_cases),'crosstalk':copy.deepcopy(self.crosstalk_pairs)};cases_from_config(config)
            if not self.saved_board:
                with wx.BusyCursor(),read_snapshot(self.board):report=run_study(self.board,config)
                self._show_study(report);return
            from .service import source_fingerprints,run_job
            fingerprints=source_fingerprints(self.board.GetFileName())
            if fingerprints!=self._source_fingerprints:raise ValueError('Saved PCB or rules changed. Reopen Quick SI before running.')
            request={'mode':'study','board_path':self.board.GetFileName(),'source_fingerprints':fingerprints,'study':config}
            self._cancel=threading.Event();cancel=self._cancel;generation=self._generation;self._job_serial+=1;serial=self._job_serial
            self._busy=True;self.run_button.Disable();self.cancel_button.Enable();self._update_circuit_buttons();self.status.SetLabel('Screening routes, explicit returns and requested local coupling in one saved snapshot…')
            def work():
                payload=error=None
                try:payload=run_job(request,cancelled=cancel.is_set)
                except Exception as caught:error=caught
                if not self._closed:
                    try:wx.CallAfter(self._study_finished,serial,generation,request,payload,error)
                    except RuntimeError:pass
            self._worker_thread=threading.Thread(target=work,daemon=True,name='Quick SI study worker');self._worker_thread.start()
        except Exception as error:
            self._busy=False;self.run_button.Enable();self.cancel_button.Disable();self.status.SetLabel(str(error))

    def _study_finished(self,serial,generation,request,payload,error):
        if self._closed or serial!=self._job_serial:return
        self._busy=False;self.run_button.Enable();self.cancel_button.Disable()
        if generation!=self._generation:self.status.SetLabel('Study cancelled or inputs changed; rerun the study.');return
        if error is not None:self.status.SetLabel(str(error));return
        try:
            from .service import require_source
            require_source(request)
            if payload.get('source_fingerprints')!=request['source_fingerprints']:raise ValueError('Study result source does not match this request.')
            self._show_study(payload['study']);self._result_fingerprints=payload['source_fingerprints']
        except Exception as caught:self.changed(None);self.status.SetLabel(str(caught))

    def _show_study(self,report):
        self.study_report=report
        self.crosstalk_results.Enable(bool(report.get('crosstalk')))
        self.study_choice.Set([case['id']+' · '+case.get('net','')+' · '+case['status'] for case in report['cases']])
        self.study_choice.SetSelection(0);self.study_choice.Show();self.GetSizer().Layout()
        self._select_study_case();self.export.Enable()

    def _select_study_case(self,event=None):
        if not self.study_report or self.study_choice.GetSelection()==wx.NOT_FOUND:return
        self._circuit_generation+=1
        case=self.study_report['cases'][self.study_choice.GetSelection()]
        self.ibis.set_context(case.get('net',''),case.get('start',''),case.get('end',''))
        self.results.DeleteAllItems();self.report=None;self.path=None;self.eye_preview.show_result(None)
        self.preview.show_result(SimpleNamespace(primary=None,mate=None))
        if 'report' in case:
            from .service import restore_path
            with read_snapshot(self.board):self._show_report(case['report'],restore_path(case,self.board),case.get('inputs',{}))
        else:
            row=self.results.InsertItem(0,case['id']+' · ERROR');self.results.SetItem(row,1,case.get('error','Unresolved case'))
            self.status.SetLabel('Case failed; other case results are retained. '+case.get('error',''));self._navigation_buttons()
        self.export.Enable()
        self._update_circuit_buttons()

    def return_nets_changed(self,event=None):
        self.return_setup._nets_changed(event)

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
        self._circuit_generation+=1
        self.study_report=None
        if hasattr(self,'crosstalk_results'):self.crosstalk_results.Disable()
        if hasattr(self,'study_choice'):self.study_choice.Clear();self.study_choice.Hide()
        self.report=None;self.path=None;self.export.Disable();self.results.DeleteAllItems();self.preview.show_result(SimpleNamespace(primary=None,mate=None))
        self.eye_preview.show_result(None)
        self._update_circuit_buttons()
        if hasattr(self,'ibis'):
            self.ibis.set_context(self.fields['net'].GetValue(),self.fields['start'].GetValue(),self.fields['end'].GetValue())
        if hasattr(self,'return_setup'):
            self.return_setup.set_context(self.fields['net'].GetValue(),self.fields['start'].GetValue(),self.fields['end'].GetValue())
        self.status.SetLabel('Inputs changed; run a fresh screen before exporting.')
        self._navigation_buttons()
        if event:event.Skip()

    def net_changed(self,event):
        if self.saved_board:pads=self._setup_pads.get(self.fields['net'].GetValue(),[])
        else:
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
        self.select_returns_button.Enable(ready and bool(self._review_return_nets()))
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
        nets=self._review_return_nets()
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
            self._closed=True;self._cancel.set();self._circuit_generation+=1
        event.Skip()

    def cancel_run(self,event=None):
        self.changed(None);self.status.SetLabel('Cancelling saved-board analysis…')

    def _inputs(self):
        values={key:(float(control.GetValue()) if control.GetValue().strip() else None) for key,control in self.fields.items() if key not in ('net','start','end','reference') and (self.eye_enabled.GetValue() or not key.startswith('eye_'))}
        selected_returns=[self.return_nets.GetString(i) for i in range(self.return_nets.GetCount()) if self.return_nets.IsChecked(i)]
        if selected_returns:
            values['return_nets']=selected_returns
            roles={role:(self.return_setup.terminal_value(c) if hasattr(self,'return_setup') else c.GetValue())
                   for role,c in [('source',self.return_source),('load',self.return_sink)] if c.GetValue()!='Not specified'}
            values['return_terminal_ids']=list(roles.values())
            values['return_terminal_roles']=roles
        if self.eye_enabled.GetValue() and values['eye_bitrate_mbps'] is None:raise ValueError('Enter a positive eye bit rate.')
        return values

    def run(self,event=None):
        if self._busy or self._closed or self._circuit_busy:return
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
            self._busy=True;self.run_button.Disable();self.cancel_button.Enable();self._update_circuit_buttons();self.status.SetLabel('Screening saved PCB in a cancellable worker… You can change inputs or cancel.')
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
        rows=[('Line model','User assumptions' if values.get('z0_ohm') is not None or values.get('epsilon_eff') is not None else 'Board geometry / unresolved terms retained'),('Route',f'{path.net_name}: {path.start_pad} → {path.end_pad}'),('Length / geometry',f'{path.length_mm:.3f} mm; {path.track_count} tracks, {path.via_count} vias, {path.zone_count} zones')]
        from .setup_guide import readiness_rows
        rows += readiness_rows(report)
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
        self.status.SetLabel(report['status']+' — '+report['edge_screen']);self.export.Enable();self._navigation_buttons();self._update_circuit_buttons()

    def export_report(self,event):
        if self._closed or self._busy or self._circuit_busy:return
        if self.report is None and self.study_report is None:return
        source=Path(self.board.GetFileName())
        if self.saved_board:
            from .service import source_fingerprints
            if self._result_fingerprints!=source_fingerprints(source):
                self.changed(None);self.status.SetLabel('Saved sources changed; reopen Quick SI and rerun before export.');return
        with wx.FileDialog(self,'Save Quick SI results and Pocket KiVi data',defaultDir=str(source.parent),defaultFile=source.stem+'-quick-si.html',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            destination=dialog.GetPath()
        from .saved_results import write_results
        report=self.study_report or self.report
        study=self.study_report is not None
        fingerprints=dict(self._result_fingerprints) if self._result_fingerprints else None
        saved=bool(self.saved_board)
        def finished(result):
            self.status.SetLabel('Saved HTML, full numerical JSON'+(' and Pocket KiVi JSON' if result.get('pocket_kivi_json') else ' (live source remains unverified)')+': '+result['html'])
        self._blender_task(lambda:write_results(destination,report,board_path=source,
            fingerprints=fingerprints,saved=saved,study=study),finished,
            'Saving complete SI numerical results and report…',label='Save results')

    def _circuit_inputs_changed(self):
        # IBIS changes invalidate pending circuit output, but not PCB geometry.
        self._circuit_generation+=1
        if self.report is not None or self.study_report is not None:
            self.status.SetLabel('IBIS selection changed. Quick SI route results are retained; circuit export will use the reviewed models.')

    def _update_circuit_buttons(self):
        if not hasattr(self,'export_circuit_button'):return
        ready=not (self._closed or self._busy or self._circuit_busy) and (
            self.report is not None or bool(self.study_report and any('report' in case for case in self.study_report['cases'])))
        self.export_circuit_button.Enable(ready);self.copy_circuit_button.Enable(ready)
        if hasattr(self,'blender'):self.blender.Enable(ready)

    def export_blender(self,event=None):
        if self._closed or self._busy or self._circuit_busy:return
        bundle=self.study_report or self.report
        if not bundle:return
        if self.saved_board:
            from .service import source_fingerprints
            try:current=source_fingerprints(self.board.GetFileName())
            except (OSError,ValueError,RuntimeError) as exc:
                self.status.SetLabel('Cannot verify saved sources for Blender export: '+str(exc));return
            if self._result_fingerprints!=current:
                self.changed(None);self.status.SetLabel('Saved sources changed; reopen Quick SI and rerun before Blender export.');return
            bundle=dict(bundle)
            bundle['source_fingerprints']=dict(self._result_fingerprints)
        from wayricad_runtime.blender_ui import choose_export
        choose_export(self,bundle,'si',self._blender_task,self.status.SetLabel)

    def _blender_task(self,operation,finished,message,*,label='Blender export'):
        """Use the circuit-export worker gate without blocking native rendering."""
        if self._closed or self._busy or self._circuit_busy:return
        generation=self._generation
        self._circuit_busy=True;self.run_button.Disable();self._update_circuit_buttons();self.status.SetLabel(message)
        def deliver(answer,error):
            if self._closed:return
            self._circuit_busy=False;self.run_button.Enable(not self._busy);self._update_circuit_buttons()
            if error is not None:self.status.SetLabel(label+': '+str(error));return
            if generation!=self._generation:
                self.status.SetLabel(label+' represents the previous completed result; inputs changed during export.');return
            try:finished(answer)
            except Exception as exc:self.status.SetLabel(label+': '+str(exc))
        def work():
            answer=error=None
            try:answer=operation()
            except Exception as exc:error=exc
            if not self._closed:
                try:wx.CallAfter(deliver,answer,error)
                except RuntimeError:pass
        threading.Thread(target=work,daemon=True,name='Quick SI Blender export').start()

    def _circuit_cases(self):
        if not self.study_report:
            if self.report is None:return []
            path=self.report['path']
            return [{'id':path['net_name'],'net':path['net_name'],'start':path['start_pad'],
                     'end':path['end_pad'],'report':self.report}]
        completed=[case for case in self.study_report['cases'] if 'report' in case]
        if not completed:return []
        choices=[f"{case['id']} · {case['net']} · {case['start']} → {case['end']} · {case['status']}" for case in completed]
        failed=len(self.study_report['cases'])-len(completed)
        message='Check completed cases to include. Assign source and receiver IBIS models by selecting each case in the result dropdown first.'
        if failed:message+=f' {failed} failed case(s) have no completed report and cannot be exported.'
        dialog=wx.MultiChoiceDialog(self,message,'Choose KiCad circuit cases',choices)
        current=self.study_choice.GetSelection()
        if current!=wx.NOT_FOUND:
            chosen=self.study_report['cases'][current]
            if chosen in completed:dialog.SetSelections([completed.index(chosen)])
        try:
            if dialog.ShowModal()!=wx.ID_OK:return []
            return [completed[index] for index in dialog.GetSelections()]
        finally:dialog.Destroy()

    def _start_circuit_export(self,copy_to_clipboard):
        if self._closed or self._busy or self._circuit_busy:return
        try:
            if not self.saved_board:
                raise ValueError('Save the PCB and reopen Quick SI before circuit export; unsaved live geometry cannot be proven current.')
            from .service import source_fingerprints
            board_path=self.board.GetFileName()
            fingerprints=source_fingerprints(board_path)
            if self._result_fingerprints is None or fingerprints!=self._result_fingerprints or fingerprints!=self._source_fingerprints:
                raise ValueError('Saved PCB or rules changed since the route result. Reopen Quick SI and rerun before circuit export.')
            cases=self._circuit_cases()
            if not cases:return
            records=[];missing=[]
            for case in cases:
                source=self.ibis.assignment(case['net'],'source',case['start'])
                sink=self.ibis.assignment(case['net'],'sink',case['end'])
                if not source or not sink:
                    missing.append(case['id']+': '+', '.join(name for name,assignment in
                                   (('source',source),('receiver',sink)) if not assignment))
                else:records.append({'id':case['id'],'report':copy.deepcopy(case['report']),
                                     'source':source,'sink':sink})
            if missing:
                raise ValueError('Assign exact source and receiver IBIS pins for every checked case. Select each case in the result dropdown: '+ '; '.join(missing))
            from .ibis_ui import circuit_options_dialog
            options=circuit_options_dialog(self,[record['report'] for record in records],
                                           [record['id'] for record in records])
            if options is None:return
            shunts=options.pop('shunt_capacitors_by_case',{})
            for record in records:record['shunt_capacitors']=shunts.get(record['id'],[])
            with wx.DirDialog(self,'Choose parent folder for a new SI circuit bundle',
                              defaultPath=str(Path(board_path).parent),style=wx.DD_DEFAULT_STYLE|wx.DD_DIR_MUST_EXIST) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                parent=Path(dialog.GetPath())
            destination=parent/('SI-circuit-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
            if source_fingerprints(board_path)!=fingerprints:
                raise ValueError('Saved PCB or rules changed while configuring export. Reopen Quick SI and rerun.')
            model_stamps=_model_source_stamps(record[role]['path'] for record in records for role in ('source','sink'))
            generation=self._circuit_generation
            self._circuit_busy=True;self._update_circuit_buttons()
            self.status.SetLabel('Building KiCad circuit and copying reviewed IBIS files in a worker…')

            def work():
                result=error=None
                try:
                    from .si_circuit import export_circuit
                    def guard():
                        if self._closed or generation!=self._circuit_generation:
                            raise ValueError('Circuit inputs changed during export.')
                        if source_fingerprints(board_path)!=fingerprints:
                            raise ValueError('Saved PCB or rules changed during circuit export.')
                    guard()
                    result=export_circuit(records,destination,options,guard=guard)
                    guard()
                except Exception as caught:error=caught
                if not self._closed:
                    try:wx.CallAfter(self._circuit_finished,generation,fingerprints,model_stamps,destination,copy_to_clipboard,result,error)
                    except RuntimeError:pass

            threading.Thread(target=work,daemon=True,name='Quick SI circuit export').start()
        except Exception as error:
            self.status.SetLabel(str(error))

    def _circuit_finished(self,generation,fingerprints,model_stamps,destination,copy_to_clipboard,result,error):
        if self._closed:return
        self._circuit_busy=False;self._update_circuit_buttons()
        if generation!=self._circuit_generation:
            self.status.SetLabel('Inputs changed during circuit export. Any generated bundle needs review; clipboard was not changed.')
            return
        if error:
            self.status.SetLabel('Circuit export failed: '+str(error));return
        try:
            from .service import source_fingerprints
            if source_fingerprints(self.board.GetFileName())!=fingerprints or self._result_fingerprints!=fingerprints:
                raise ValueError('Saved PCB or rules changed after circuit export; clipboard was not changed.')
            if _model_source_stamps(model_stamps)!=model_stamps:
                raise ValueError('IBIS model file changed after circuit export; clipboard was not changed. Reload the model and export again.')
            if copy_to_clipboard:
                if not wx.TheClipboard.Open():raise ValueError('Clipboard is busy; the circuit bundle was created but could not be copied.')
                try:
                    if not wx.TheClipboard.SetData(wx.TextDataObject(result['clipboard_text'])):
                        raise ValueError('Clipboard rejected the circuit text.')
                    wx.TheClipboard.Flush()
                finally:wx.TheClipboard.Close()
                message='KiCad circuit copied. Model bundle: '+str(destination)
            else:message='KiCad circuit bundle exported: '+str(result['schematic'])
            if result.get('shunt_capacitor_count'):
                message+=' · '+str(result['shunt_capacitor_count'])+' shunt capacitors; run the transient in KiCad.'
            self.status.SetLabel(message)
        except Exception as caught:self.status.SetLabel(str(caught))
