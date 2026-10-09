"""Native setup and time plots for explicit PI and thermal transient studies."""
from __future__ import annotations
import copy
import math
from pathlib import Path
import threading

import wx
import wx.grid
from matplotlib.figure import Figure

from .transient_study import draw_study,study_summary,write_study_report,limits_violated

FIELDS={
    'pi': [('source_voltage_V','Source setpoint V'),('source_resistance_ohm','Shared source R Ω'),
           ('source_inductance_H','Shared source L H'),('source_current_limit_A','Source budget A (optional)'),
           ('duration_s','Duration s'),('step_s','Integration step s')],
    'thermal': [('ambient_c','Ambient °C'),('initial_temperature_c','Initial temperature °C'),
                ('duration_s','Duration s'),('step_s','Output interval s')],
}
COLUMNS={
    'pi': [('id','Load / pad'),('initial_current_A','Before A'),('step_current_A','After A'),
           ('step_time_s','Step time s'),('path_resistance_ohm','Path R Ω'),('path_inductance_H','Path L H'),
           ('capacitance_F','C F (required)'),('esr_ohm','Cap ESR Ω'),
           ('min_voltage_V','Min V (optional)'),('max_voltage_V','Max V (optional)')],
    'thermal': [('reference','Component'),('initial_power_W','Before W'),('step_power_W','After W'),
                ('step_time_s','Step time s'),('resistance_K_W','Rθ to ambient K/W'),
                ('capacitance_J_K','Cθ J/K (required)'),('limit_c','Limit °C (optional)')],
}
OPTIONAL={'source_current_limit_A','min_voltage_V','max_voltage_V','limit_c'}


def read_study(kind,parameters,rows):
    """Convert visible controls; missing physical capacities remain errors."""
    def number(key,label,text):
        if not str(text).strip():
            if key in OPTIONAL:return None
            raise ValueError('Enter '+label+'.')
        try:value=float(text)
        except (ValueError,TypeError) as exc:raise ValueError(label+' must be a number.') from exc
        if not math.isfinite(value):raise ValueError(label+' must be finite.')
        return value
    result={}
    for key,label in FIELDS[kind]:
        value=number(key,label,parameters[key])
        if value is not None:result[key]=value
    parsed=[]
    for index,values in enumerate(rows,1):
        row={}
        for (key,label),text in zip(COLUMNS[kind],values):
            if key in ('id','reference'):
                if not str(text).strip():raise ValueError(f'Row {index}: enter {label}.')
                row[key]=str(text).strip()
            else:
                value=number(key,f'row {index} {label}',text)
                if value is not None:row[key]=value
        parsed.append(row)
    result['loads' if kind=='pi' else 'components']=parsed
    return result


class TransientStudyDialog(wx.Dialog):
    def __init__(self,parent,kind,initial,runner,canvas_types,board_path=None,source_sha256=None):
        title='Quick PI · Transient load steps' if kind=='pi' else 'QuickTherm · Transient power steps'
        super().__init__(parent,title=title,size=(1100,760),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetMinSize((820,580));self.kind=kind;self.runner=runner;self.board_path=board_path
        self.source_sha256=source_sha256;self.result=None;self._busy=False;self._closed=False;self._closing=False
        self._cancel=threading.Event();self.parameters={};self._editable=[]
        root=wx.BoxSizer(wx.VERTICAL)
        note=('Explicit shared source and load-path R/L with local C/ESR. Source current budget is diagnostic; no regulator CV/CC or PCB-field solve.' if kind=='pi' else
              'Independent component Rθ/Cθ paths to a prescribed ambient. Enter physical heat capacities; this does not simulate board heat spreading.')
        snapshot=' Saved PCB snapshot '+source_sha256[:12]+'.' if source_sha256 else ''
        label=wx.StaticText(self,label=note+' Values are explicit model inputs; missing capacities must be entered.'+snapshot);label.Wrap(1020)
        root.Add(label,0,wx.EXPAND|wx.ALL,10)
        self.book=wx.Notebook(self);setup=wx.ScrolledWindow(self.book);setup.SetScrollRate(8,8);form=wx.BoxSizer(wx.VERTICAL)
        grid=wx.FlexGridSizer(0,4,8,10);grid.AddGrowableCol(1);grid.AddGrowableCol(3)
        for key,name in FIELDS[kind]:
            grid.Add(wx.StaticText(setup,label=name),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(setup,value='' if initial.get(key) is None else str(initial[key]))
            self.parameters[key]=control;self._editable.append(control);grid.Add(control,1,wx.EXPAND)
            control.Bind(wx.EVT_TEXT,self._changed)
        form.Add(grid,0,wx.EXPAND|wx.ALL,10)
        self.rows=wx.grid.Grid(setup)
        cases=initial.get('loads' if kind=='pi' else 'components',[])
        self.rows.CreateGrid(max(1,len(cases)),len(COLUMNS[kind]))
        for column,(key,name) in enumerate(COLUMNS[kind]):self.rows.SetColLabelValue(column,name);self.rows.SetColSize(column,135)
        self.rows.SetColLabelSize(45)
        for index,row in enumerate(cases):
            for column,(key,_) in enumerate(COLUMNS[kind]):
                self.rows.SetCellValue(index,column,'' if row.get(key) is None else str(row[key]))
        self.rows.Bind(wx.grid.EVT_GRID_CELL_CHANGED,self._changed)
        form.Add(self.rows,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        buttons=wx.BoxSizer(wx.HORIZONTAL)
        self.add=wx.Button(setup,label='Add load' if kind=='pi' else 'Add component')
        self.remove=wx.Button(setup,label='Remove selected row')
        self.add.Bind(wx.EVT_BUTTON,self._add_row);self.remove.Bind(wx.EVT_BUTTON,self._remove_row)
        for control in (self.add,self.remove):buttons.Add(control,0,wx.RIGHT,8);self._editable.append(control)
        form.Add(buttons,0,wx.ALL,10);setup.SetSizer(form);self.book.AddPage(setup,'Setup')
        panel=wx.Panel(self.book);plot_layout=wx.BoxSizer(wx.VERTICAL);self.figure=Figure(figsize=(9,5))
        Canvas,Toolbar=canvas_types;self.canvas=Canvas(panel,wx.ID_ANY,self.figure);toolbar=Toolbar(self.canvas);toolbar.Realize()
        plot_layout.Add(self.canvas,1,wx.EXPAND);plot_layout.Add(toolbar,0,wx.EXPAND);panel.SetSizer(plot_layout)
        self.book.AddPage(panel,'Time plots')
        self.details=wx.TextCtrl(self.book,style=wx.TE_MULTILINE|wx.TE_READONLY);self.book.AddPage(self.details,'Checks / limits')
        root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        example='100e-6 F' if kind=='pi' else '1 J/K'
        self.status=wx.StaticText(self,label='Set capacities and step conditions, then Run transient. Units are SI; e.g. '+example+'.');self.status.Wrap(1020)
        root.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        self.run=wx.Button(self,label='Run transient');self.stop=wx.Button(self,label='Cancel run');self.export=wx.Button(self,label='Export HTML / JSON…')
        close=wx.Button(self,wx.ID_CLOSE,label='Close')
        for control in (self.run,self.stop,self.export,close):actions.Add(control,0,wx.RIGHT,8)
        root.Add(actions,0,wx.ALIGN_RIGHT|wx.ALL,10);self.SetSizer(root)
        self.run.Bind(wx.EVT_BUTTON,self._run);self.stop.Bind(wx.EVT_BUTTON,lambda event:self._cancel.set())
        self.export.Bind(wx.EVT_BUTTON,self._export);close.Bind(wx.EVT_BUTTON,self._close);self.Bind(wx.EVT_CLOSE,self._close)
        self.stop.Disable();self.export.Disable()

    def _changed(self,event=None):
        self.result=None;self.export.Disable();self.figure.clear();self.canvas.draw_idle();self.details.ChangeValue('')
        self.status.SetLabel('Inputs changed. Run transient again.')
        if event:event.Skip()

    def _add_row(self,event):
        if self.rows.GetNumberRows()>=64:self.status.SetLabel('The setup editor supports at most 64 rows.');return
        self.rows.AppendRows();self._changed()

    def _remove_row(self,event):
        if self.rows.GetNumberRows()>1:self.rows.DeleteRows(max(0,self.rows.GetGridCursorRow()));self._changed()

    def _request(self):
        self.rows.SaveEditControlValue();self.rows.DisableCellEditControl()
        rows=[[self.rows.GetCellValue(i,j) for j in range(self.rows.GetNumberCols())] for i in range(self.rows.GetNumberRows())]
        study=read_study(self.kind,{key:control.GetValue() for key,control in self.parameters.items()},rows)
        request={'action':'transient','study':study}
        if self.board_path:request.update(board_path=str(self.board_path),source_sha256=self.source_sha256)
        return request

    def _run(self,event=None):
        if self._busy:return
        try:request=self._request()
        except ValueError as exc:self.status.SetLabel(str(exc));return
        self._changed();self._busy=True;self._cancel.clear();self.run.Disable();self.stop.Enable()
        for control in self._editable:control.Disable()
        self.rows.EnableEditing(False);self.status.SetLabel('Running the bounded transient worker…')
        def work():
            result=None;error=None
            try:result=self.runner(copy.deepcopy(request),self._cancel.is_set)
            except Exception as exc:error=str(exc)
            if not self._closed:wx.CallAfter(self._finished,result,error)
        threading.Thread(target=work,daemon=True).start()

    def _finished(self,result,error):
        if self._closed:return
        self._busy=False;self.run.Enable();self.stop.Disable()
        for control in self._editable:control.Enable()
        self.rows.EnableEditing(True)
        if self._closing:self._finish_close();return
        if self._cancel.is_set():error='Transient study cancelled. No results accepted.'
        if not error and (not isinstance(result,dict) or 'transient' not in result):error='Worker returned no transient result.'
        if error:self.status.SetLabel(error);return
        self.result=result;draw_study(self.figure,result);self.canvas.draw_idle()
        self.details.ChangeValue(study_summary(result));self.book.SetSelection(1);self.export.Enable()
        violated=limits_violated(result['transient'])
        self.status.SetLabel(('LIMIT VIOLATION. ' if violated else 'Study complete. ')+str(len(result['transient']['times_s']))+' samples · review Checks / limits before using the result.')
        self.status.SetForegroundColour('#a93426' if violated else '#253945')
        self.status.Wrap(max(400,self.GetClientSize().width-30));self.Layout()

    def _export(self,event=None):
        if not self.result:return
        with wx.FileDialog(self,'Export transient report',defaultFile='transient-study.html',wildcard='HTML report (*.html)|*.html',
                           style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
        companion=Path(path).with_suffix('.json')
        if companion.exists() and wx.MessageBox('Replace the existing paired JSON report?','Paired report exists',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        try:
            paths=write_study_report(path,self.result);self.status.SetLabel('Exported '+paths['html'])
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def _close(self,event=None):
        if self._busy:
            self._closing=True;self._cancel.set();self.status.SetLabel('Cancelling the worker before closing…')
            if event and hasattr(event,'CanVeto') and event.CanVeto():event.Veto()
            return
        self._finish_close()

    def _finish_close(self):
        self._closed=True
        if self.IsModal():self.EndModal(wx.ID_CLOSE)
        else:self.Destroy()
