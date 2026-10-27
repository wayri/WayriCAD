"""Engineering-unit Quick PI setup above the retained advanced SI editor."""
from pathlib import Path
import json
import hashlib

import wx
import wx.grid
from wayricad_runtime.transient_study_ui import TransientStudyDialog,FIELDS,COLUMNS
from .transient_inputs import PARAMETERS,LOAD_COLUMNS,engineering_from_study,engineering_to_study,recommend_step


class PITransientStudyDialog(TransientStudyDialog):
    """Keep the existing worker, time plots, convergence and export contracts."""
    def __init__(self,parent,kind,initial,runner,canvas_types,board_path=None,source_sha256=None):
        if kind!='pi':raise ValueError('Use the generic transient editor for thermal studies.')
        super().__init__(parent,kind,initial,runner,canvas_types,board_path,source_sha256)
        self._input_path=None;self._input_sha=None
        setup=self.rows.GetParent();form=setup.GetSizer();self._setup_form=form
        self._advanced_objects=[item.GetWindow() if item.IsWindow() else item.GetSizer() for item in form.GetChildren()]
        self.quick_panel=wx.Panel(setup);layout=wx.BoxSizer(wx.VERTICAL)
        self.advanced=wx.CheckBox(self.quick_panel,label='Advanced SI editor (Ω / H / F / s)')
        self.advanced.Bind(wx.EVT_CHECKBOX,self._toggle_advanced);layout.Add(self.advanced,0,wx.ALL,6)
        note=wx.StaticText(self.quick_panel,label='Enter explicit path inductance and effective decoupling C/ESR. Zero L deliberately omits inductance. '
             'Source R may be seeded from one matching DC path; do not count that same copper resistance again as branch R. '
             'The model uses ideal current steps, not finite-rise switching edges or regulator control dynamics.')
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
        self.quick_panel.SetSizer(layout);form.Insert(0,self.quick_panel,1,wx.EXPAND|wx.ALL,5)
        self._editable.append(self.advanced)
        self._populate_quick(initial)
        for item in self._advanced_objects:form.Show(item,False)
        setup.Layout();setup.FitInside();self.Layout()
        self.status.SetLabel('Fill the required source R and effective C values, review explicit L/ESR, then Recommend time step and Run transient.')

    def _help(self,event=None):
        from wayricad_runtime.help import open_help
        open_help(self,Path(__file__).with_name('transient_setup_help.html'))

    def _populate_quick(self,study):
        parameters,rows=engineering_from_study(study)
        for key,value in parameters.items():self.quick_fields[key].ChangeValue(value)
        if self.quick_rows.GetNumberRows():self.quick_rows.DeleteRows(0,self.quick_rows.GetNumberRows())
        self.quick_rows.AppendRows(max(1,len(rows)))
        for index,row in enumerate(rows):
            for column,value in enumerate(row):self.quick_rows.SetCellValue(index,column,value)

    def _quick_study(self,validate=True):
        if self.quick_rows.IsCellEditControlEnabled():self.quick_rows.SaveEditControlValue();self.quick_rows.DisableCellEditControl()
        rows=[[self.quick_rows.GetCellValue(i,j) for j in range(self.quick_rows.GetNumberCols())] for i in range(self.quick_rows.GetNumberRows())]
        return engineering_to_study({key:control.GetValue() for key,control in self.quick_fields.items()},rows,validate=validate)

    def _write_advanced(self,study):
        for key,_name in FIELDS['pi']:self.parameters[key].ChangeValue('' if study.get(key) is None else str(study[key]))
        if self.rows.GetNumberRows():self.rows.DeleteRows(0,self.rows.GetNumberRows())
        self.rows.AppendRows(len(study['loads']))
        for index,row in enumerate(study['loads']):
            for column,(key,_name) in enumerate(COLUMNS['pi']):self.rows.SetCellValue(index,column,'' if row.get(key) is None else str(row[key]))

    def _toggle_advanced(self,event=None):
        advanced=self.advanced.GetValue()
        try:
            if advanced:self._write_advanced(self._quick_study(validate=False))
            else:
                if self.rows.IsCellEditControlEnabled():self.rows.SaveEditControlValue();self.rows.DisableCellEditControl()
                def number(text):return None if not str(text).strip() else float(text)
                study={key:number(control.GetValue()) for key,control in self.parameters.items()}
                study['loads']=[{key:self.rows.GetCellValue(i,j) if key=='id' else number(self.rows.GetCellValue(i,j))
                                 for j,(key,_label) in enumerate(COLUMNS['pi'])} for i in range(self.rows.GetNumberRows())]
                self._populate_quick(study)
        except ValueError as exc:
            self.advanced.SetValue(not advanced);self.status.SetLabel(str(exc));return
        self.quick_body.Show(not advanced)
        for item in self._advanced_objects:self._setup_form.Show(item,advanced)
        self._setup_form.GetItem(self.quick_panel).SetProportion(0 if advanced else 1)
        self.quick_panel.Layout();self.rows.GetParent().Layout();self.rows.GetParent().FitInside();self.Layout()

    def _request(self):
        if self.advanced.GetValue():request=super()._request()
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
        if self.quick_rows.GetNumberRows()>1:self.quick_rows.DeleteRows(max(0,self.quick_rows.GetGridCursorRow()));self._changed()

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
        with wx.FileDialog(self,'Load explicit PI transient inputs',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
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
        with wx.FileDialog(self,'Save explicit PI transient inputs',defaultFile='pi-transient-inputs.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        try:
            if path.suffix.lower()!='.json':raise ValueError('Choose a new .json file.')
            with path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(study,indent=2,allow_nan=False)+'\n')
            self.status.SetLabel('Saved explicit SI inputs; existing files were preserved.')
        except (OSError,ValueError) as exc:self.status.SetLabel(str(exc))
