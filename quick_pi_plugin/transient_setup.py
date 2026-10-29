"""Engineering-unit Quick PI setup above the retained advanced SI editor."""
from pathlib import Path
import json
import hashlib
import copy

import wx
import wx.grid
from wx.lib.wordwrap import wordwrap
from matplotlib.figure import Figure
from wayricad_runtime.transient_study_ui import TransientStudyDialog,FIELDS,COLUMNS
from .transient_inputs import PARAMETERS,LOAD_COLUMNS,engineering_from_study,engineering_to_study,recommend_step


class PITransientStudyDialog(TransientStudyDialog):
    """Keep the existing worker, time plots, convergence and export contracts."""
    def __init__(self,parent,kind,initial,runner,canvas_types,board_path=None,source_sha256=None,
                 terminals=(),signal_net='',return_nets=()):
        if kind!='pi':raise ValueError('Use the generic transient editor for thermal studies.')
        super().__init__(parent,kind,initial,runner,canvas_types,board_path,source_sha256)
        self._input_path=None;self._input_sha=None
        self._banks={};self._rise_times={};self._cap_terminals=tuple(terminals);self._signal_net=signal_net;self._cap_returns=tuple(return_nets)
        setup=self.rows.GetParent();form=setup.GetSizer();self._setup_form=form
        self._advanced_objects=[item.GetWindow() if item.IsWindow() else item.GetSizer() for item in form.GetChildren()]
        self.quick_panel=wx.Panel(setup);layout=wx.BoxSizer(wx.VERTICAL)
        self.advanced=wx.CheckBox(self.quick_panel,label='Advanced SI editor (Ω / H / F / s)')
        self.advanced.Bind(wx.EVT_CHECKBOX,self._toggle_advanced);layout.Add(self.advanced,0,wx.ALL,6)
        note=wx.StaticText(self.quick_panel,label='Enter explicit path inductance and effective decoupling C/ESR, or edit individual shunt capacitors for a load. Banks replace aggregate C/ESR. Zero L deliberately omits inductance. '
             'Source R may be seeded from one matching DC path; do not count that same copper resistance again as branch R. '
             'Use prescribed ideal current steps or bank-only linear current ramps; switching waveforms and regulator control dynamics are not simulated.')
        note.Wrap(980);layout.Add(note,0,wx.EXPAND|wx.ALL,6)
        self.quick_body=wx.Panel(self.quick_panel);body=wx.BoxSizer(wx.VERTICAL)
        grid=wx.FlexGridSizer(cols=4,hgap=8,vgap=8);grid.AddGrowableCol(1);grid.AddGrowableCol(3)
        self.quick_fields={}
        for key,label,_scale in PARAMETERS:
            grid.Add(wx.StaticText(self.quick_body,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(self.quick_body);control.Bind(wx.EVT_TEXT,self._changed)
            self.quick_fields[key]=control;grid.Add(control,1,wx.EXPAND);self._editable.append(control)
        body.Add(grid,0,wx.EXPAND|wx.ALL,6)
        self.quick_rows=wx.grid.Grid(self.quick_body);self.quick_rows.CreateGrid(1,len(LOAD_COLUMNS))
        for column,(_key,label,_scale) in enumerate(LOAD_COLUMNS):
            self.quick_rows.SetColLabelValue(column,label);self.quick_rows.SetColSize(column,130)
        self.quick_rows.SetColLabelSize(40);self.quick_rows.SetMinSize((-1,200))
        self.quick_rows.Bind(wx.grid.EVT_GRID_CELL_CHANGED,self._changed)
        self._editable.append(self.quick_rows);body.Add(self.quick_rows,1,wx.EXPAND|wx.ALL,6)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        for label,handler in [('Add load',self._quick_add),('Remove load',self._quick_remove),
                              ('Recommend time step',self._recommend),('Load inputs JSON…',self._load_inputs),
                              ('Save inputs JSON…',self._save_inputs),('Methods / help',self._help)]:
            button=wx.Button(self.quick_body,label=label);button.Bind(wx.EVT_BUTTON,handler)
            actions.Add(button,0,wx.RIGHT|wx.BOTTOM,6);self._editable.append(button)
        body.Add(actions,0,wx.ALL,6);self.quick_body.SetSizer(body);layout.Add(self.quick_body,1,wx.EXPAND)
        self.bank_button=wx.Button(self.quick_panel,label='Shunt capacitors for selected load…')
        self.bank_button.Bind(wx.EVT_BUTTON,self._edit_bank);self._editable.append(self.bank_button)
        layout.Add(self.bank_button,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        self.bank_status=wx.StaticText(self.quick_panel,label='No individual banks; aggregate C/ESR applies.')
        layout.Add(self.bank_status,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,6)
        self.quick_panel.SetSizer(layout);form.Insert(0,self.quick_panel,1,wx.EXPAND|wx.ALL,5)
        self._editable.append(self.advanced)
        self._populate_quick(initial)
        for item in self._advanced_objects:form.Show(item,False)
        setup.Layout();setup.FitInside();self.Layout()
        cap_page=wx.Panel(self.book);cap_layout=wx.BoxSizer(wx.VERTICAL)
        cap_text='Select a capacitor row for its internal C voltage and branch current. ESR heat is physical; numerical damping is separate. No spatial capacitor position is extracted.'
        self.cap_caption=wx.StaticText(cap_page,label=cap_text);self.cap_caption.SetMinSize((1,-1));self.cap_caption.SetToolTip(cap_text)
        cap_layout.Add(self.cap_caption,0,wx.EXPAND|wx.ALL,6)
        splitter=wx.SplitterWindow(cap_page,style=wx.SP_LIVE_UPDATE);splitter.SetMinimumPaneSize(110)
        self.cap_table=wx.ListCtrl(splitter,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(name,width) in enumerate([('Load / capacitor',260),('C · µF',100),('ESR · mΩ',100),('ESL · nH',100),('Peak |I| · A',120),('Peak ESR W',120)]):
            self.cap_table.InsertColumn(i,name,width=width)
        panel=wx.Panel(splitter);plot=wx.BoxSizer(wx.VERTICAL);self.cap_figure=Figure(figsize=(8,4))
        Canvas,Toolbar=canvas_types;self.cap_canvas=Canvas(panel,wx.ID_ANY,self.cap_figure);cap_toolbar=Toolbar(self.cap_canvas);cap_toolbar.Realize()
        plot.Add(self.cap_canvas,1,wx.EXPAND);plot.Add(cap_toolbar,0,wx.EXPAND);panel.SetSizer(plot)
        splitter.SplitHorizontally(self.cap_table,panel,160);cap_layout.Add(splitter,1,wx.EXPAND);cap_page.SetSizer(cap_layout)
        self.book.AddPage(cap_page,'Capacitor response');self._cap_results=[]
        self.cap_table.Bind(wx.EVT_LIST_ITEM_SELECTED,self._plot_capacitor)
        wrap_state={'busy':False,'width':None}
        def wrap_caption(event):
            if not wrap_state['busy'] and not self._closed:
                width=max(260,cap_page.GetClientSize().width-16)
                if width!=wrap_state['width']:
                    wrap_state.update(busy=True,width=width)
                    try:
                        self.cap_caption.SetLabel(wordwrap(cap_text,width,wx.ClientDC(self.cap_caption)));self.cap_caption.InvalidateBestSize();cap_page.Layout()
                    finally:wrap_state['busy']=False
            event.Skip()
        cap_page.Bind(wx.EVT_SIZE,wrap_caption)
        self.status.SetLabel('Fill the required source R and effective C values, review explicit L/ESR, then Recommend time step and Run transient.')

    def _changed(self,event=None):
        super()._changed(event)
        if hasattr(self,'cap_table'):
            self._cap_results=[];self.cap_table.DeleteAllItems();self.cap_figure.clear();self.cap_canvas.draw_idle()

    def _finished(self,result,error):
        super()._finished(result,error)
        if not self.result or self._closed:return
        from wayricad_runtime.transient_review import capacitor_rows
        self._cap_results=capacitor_rows(self.result['transient']);self.cap_table.DeleteAllItems()
        for row in self._cap_results:
            index=self.cap_table.InsertItem(self.cap_table.GetItemCount(),row['load_id']+' / '+row['id'].split('@',1)[0])
            for column,value in enumerate((row['capacitance_F']*1e6,row['esr_ohm']*1e3,row['esl_H']*1e9,row['peak_current_A'],row['peak_esr_loss_W']),1):
                self.cap_table.SetItem(index,column,f'{value:.7g}')
        if self._cap_results:self.cap_table.Select(0);self._plot_capacitor()

    def _plot_capacitor(self,event=None):
        selected=self.cap_table.GetFirstSelected()
        if not self.result or selected<0 or selected>=len(self._cap_results):return
        row=self._cap_results[selected];branch=row['branch'];times=self.result['transient']['times_s']
        self.cap_figure.clear();voltage=self.cap_figure.add_subplot(211);current=self.cap_figure.add_subplot(212,sharex=voltage)
        voltage.plot(times,branch['capacitor_voltage_V'],color='#147f94');voltage.set_ylabel('Internal C voltage · V')
        current.plot(times,branch['current_A'],color='#ad6a24');current.set_ylabel('Branch current · A');current.set_xlabel('Time · s')
        voltage.set_title(row['load_id']+' / '+row['id'].split('@',1)[0],fontsize=10)
        for axis in (voltage,current):axis.grid(True,alpha=.2)
        self.cap_figure.tight_layout();self.cap_canvas.draw_idle()

    def _help(self,event=None):
        from wayricad_runtime.help import open_help
        open_help(self,Path(__file__).with_name('transient_setup_help.html'))

    def _populate_quick(self,study):
        self._banks={i:copy.deepcopy(row['shunt_capacitors']) for i,row in enumerate(study.get('loads',[])) if row.get('shunt_capacitors')}
        self._rise_times={i:row.get('rise_time_s',0.) for i,row in enumerate(study.get('loads',[])) if row.get('shunt_capacitors')}
        parameters,rows=engineering_from_study(study)
        for key,value in parameters.items():self.quick_fields[key].ChangeValue(value)
        if self.quick_rows.GetNumberRows():self.quick_rows.DeleteRows(0,self.quick_rows.GetNumberRows())
        self.quick_rows.AppendRows(max(1,len(rows)))
        for index,row in enumerate(rows):
            for column,value in enumerate(row):self.quick_rows.SetCellValue(index,column,value)
        self._sync_bank_cells()

    def _quick_study(self,validate=True):
        if self.quick_rows.IsCellEditControlEnabled():self.quick_rows.SaveEditControlValue();self.quick_rows.DisableCellEditControl()
        rows=[[self.quick_rows.GetCellValue(i,j) for j in range(self.quick_rows.GetNumberCols())] for i in range(self.quick_rows.GetNumberRows())]
        return engineering_to_study({key:control.GetValue() for key,control in self.quick_fields.items()},rows,validate=validate,banks=self._banks,rise_times=self._rise_times)

    def _advanced_study(self,validate=True):
        if self.rows.IsCellEditControlEnabled():self.rows.SaveEditControlValue();self.rows.DisableCellEditControl()
        def number(text):return None if not str(text).strip() else float(text)
        study={key:number(control.GetValue()) for key,control in self.parameters.items() if str(control.GetValue()).strip()}
        study['loads']=[]
        for i in range(self.rows.GetNumberRows()):
            row={}
            for j,(key,_label) in enumerate(COLUMNS['pi']):
                if i in self._banks and key in ('capacitance_F','esr_ohm'):continue
                text=self.rows.GetCellValue(i,j)
                if key=='id':row[key]=text
                elif str(text).strip():row[key]=number(text)
            if i in self._banks:
                row['shunt_capacitors']=copy.deepcopy(self._banks[i]);row['rise_time_s']=self._rise_times.get(i,0.)
            study['loads'].append(row)
        if validate:
            from .transient import _request
            _request(study)
        return study

    def _sync_bank_cells(self):
        background=wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        for grid in (self.quick_rows,self.rows):
            for i in range(grid.GetNumberRows()):
                for column in (6,7):
                    if i in self._banks:grid.SetCellValue(i,column,'Bank')
                    elif grid.GetCellValue(i,column)=='Bank':grid.SetCellValue(i,column,'')
                    grid.SetReadOnly(i,column,i in self._banks)
                    grid.SetCellBackgroundColour(i,column,wx.Colour(224,236,240) if i in self._banks else background)
            grid.ForceRefresh()
        count=sum(map(len,self._banks.values()))
        self.bank_status.SetLabel(f'{count} individual shunt branches across {len(self._banks)} loads. Marked rows ignore aggregate C/ESR.' if count else 'No individual banks; aggregate C/ESR applies.')
        self.bank_status.Wrap(max(300,self.GetClientSize().width-45))

    def _edit_bank(self,event=None):
        grid=self.rows if self.advanced.GetValue() else self.quick_rows
        index=max(0,grid.GetGridCursorRow())
        if not grid.GetNumberRows():return
        from .shunt_caps_ui import ShuntCapacitorDialog
        assigned={row['id'] for i,bank in self._banks.items() if i!=index for row in bank}
        dialog=ShuntCapacitorDialog(self,grid.GetCellValue(index,0),self._banks.get(index,[]),
            self._cap_terminals,self._signal_net,self._cap_returns,assigned,self._rise_times.get(index,0.))
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            if dialog.result:
                self._banks[index]=dialog.result;self._rise_times[index]=dialog.rise_time_s
            else:
                self._banks.pop(index,None);self._rise_times.pop(index,None)
            self._sync_bank_cells();self._changed()
        finally:dialog.Destroy()

    def _write_advanced(self,study):
        for key,_name in FIELDS['pi']:self.parameters[key].ChangeValue('' if study.get(key) is None else str(study[key]))
        if self.rows.GetNumberRows():self.rows.DeleteRows(0,self.rows.GetNumberRows())
        self.rows.AppendRows(len(study['loads']))
        for index,row in enumerate(study['loads']):
            for column,(key,_name) in enumerate(COLUMNS['pi']):self.rows.SetCellValue(index,column,'' if row.get(key) is None else str(row[key]))
        self._sync_bank_cells()

    def _toggle_advanced(self,event=None):
        advanced=self.advanced.GetValue()
        try:
            if advanced:self._write_advanced(self._quick_study(validate=False))
            else:
                study=self._advanced_study(validate=False)
                self._populate_quick(study)
        except ValueError as exc:
            self.advanced.SetValue(not advanced);self.status.SetLabel(str(exc));return
        self.quick_body.Show(not advanced)
        for item in self._advanced_objects:self._setup_form.Show(item,advanced)
        self._setup_form.GetItem(self.quick_panel).SetProportion(0 if advanced else 1)
        self.quick_panel.Layout();self.rows.GetParent().Layout();self.rows.GetParent().FitInside();self.Layout()

    def _request(self):
        if self.advanced.GetValue():
            request={'action':'transient','study':self._advanced_study()}
            if self.board_path:request.update(board_path=str(self.board_path),source_sha256=self.source_sha256)
        else:
            request={'action':'transient','study':self._quick_study()}
            if self.board_path:request.update(board_path=str(self.board_path),source_sha256=self.source_sha256)
        if self._input_path:
            request['study_input_path']=self._input_path
            if self._input_sha:request['study_file_sha256']=self._input_sha
        return request

    def _quick_add(self,event=None):
        if self.quick_rows.GetNumberRows()>=64:self.status.SetLabel('At most 64 transient load units.');return
        self.quick_rows.AppendRows();index=self.quick_rows.GetNumberRows()-1
        defaults=[f'Load {index+1}','0','1','10','0','0','','0','','']
        for column,value in enumerate(defaults):self.quick_rows.SetCellValue(index,column,value)
        self._changed()

    def _quick_remove(self,event=None):
        if self.quick_rows.GetNumberRows()>1:
            row=max(0,self.quick_rows.GetGridCursorRow());self.quick_rows.DeleteRows(row)
            self._banks={i-(i>row):bank for i,bank in self._banks.items() if i!=row}
            self._rise_times={i-(i>row):value for i,value in self._rise_times.items() if i!=row};self._sync_bank_cells();self._changed()

    def _remove_row(self,event):
        if self.rows.GetNumberRows()>1:
            row=max(0,self.rows.GetGridCursorRow());self.rows.DeleteRows(row)
            self._banks={i-(i>row):bank for i,bank in self._banks.items() if i!=row}
            self._rise_times={i-(i>row):value for i,value in self._rise_times.items() if i!=row};self._sync_bank_cells();self._changed()

    def _recommend(self,event=None):
        try:
            value=recommend_step(self._request()['study'])
            if not value['within_budget']:
                raise ValueError(f"Suggested step {value['step_s']*1e6:.6g} µs needs {value['intervals']:,} intervals; shorten Duration before using it (limit {value['maximum_intervals']:,}).")
            if self.advanced.GetValue():self.parameters['step_s'].SetValue(f"{value['step_s']:.12g}")
            else:self.quick_fields['step_s'].SetValue(f"{value['step_s']*1e6:.12g}")
            self.status.SetLabel(value['note'])
        except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc))

    def _load_inputs(self,event=None):
        with wx.FileDialog(self,'Load explicit PI transient inputs',defaultDir=str(Path(self.board_path).resolve().parent) if self.board_path else '',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        try:
            if path.stat().st_size>1024*1024:raise ValueError('Transient input exceeds 1 MiB.')
            def pairs(items):
                result={}
                for key,value in items:
                    if key in result:raise ValueError('Repeated transient field: '+key)
                    result[key]=value
                return result
            content=path.read_bytes()
            study=json.loads(content.decode('utf-8-sig'),object_pairs_hook=pairs)
            from .transient import _request
            study=_request(study)
            if self.advanced.GetValue():self._write_advanced(study)
            self._populate_quick(study);self._input_path=str(path.resolve())
            self._input_sha=hashlib.sha256(content).hexdigest();self._changed()
            self.status.SetLabel('Loaded explicit R/L/C inputs. Review units and model assumptions before Run.')
        except (ValueError,OSError,TypeError,RecursionError) as exc:self.status.SetLabel(str(exc))

    def _save_inputs(self,event=None):
        try:study=self._request()['study']
        except ValueError as exc:self.status.SetLabel(str(exc));return
        with wx.FileDialog(self,'Save explicit PI transient inputs',defaultDir=str(Path(self.board_path).resolve().parent) if self.board_path else '',defaultFile='pi-transient-inputs.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        try:
            if path.suffix.lower()!='.json':raise ValueError('Choose a new .json file.')
            with path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(study,indent=2,allow_nan=False)+'\n')
            self.status.SetLabel('Saved explicit SI inputs; existing files were preserved.')
        except (OSError,ValueError) as exc:self.status.SetLabel(str(exc))
