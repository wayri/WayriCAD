"""Small explicit capacitor-bank screen, separate from board placement checks."""
from pathlib import Path
import csv
import json
import math

import wx
import wx.grid
from matplotlib.figure import Figure
from ..plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
from .impedance import analyze,initial_model,validate
from ..study_setup_file import project_directory


class PdnImpedanceDialog(wx.Dialog):
    def __init__(self,parent):
        super().__init__(parent,title='Quick PI · PDN target and capacitor bank',size=(1060,780),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetMinSize((850,620));self.result=None;self._loading=False;self._input_path=None;self._probes=[]
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Explicit lumped source R/L feeding a local capacitor bank. Enter effective, derated C and part + mounting ESL. '
                           'The illustrative values below are not extracted from this board; placement proximity is a separate check.')
        note.Wrap(1000);root.Add(note,0,wx.EXPAND|wx.ALL,8)
        self.book=wx.Notebook(self);setup=wx.ScrolledWindow(self.book);setup.SetScrollRate(8,8);form=wx.BoxSizer(wx.VERTICAL)
        fields=wx.FlexGridSizer(cols=4,hgap=8,vgap=7);fields.AddGrowableCol(1);fields.AddGrowableCol(3);self.fields={}
        for key,label in [('source_resistance_ohm','Source / upstream R mΩ'),('source_inductance_H','Source / loop L nH'),
                          ('allowed_ripple_V','Allowed ripple mV'),('current_step_A','Load step ΔI A'),
                          ('start_Hz','Start frequency Hz'),('stop_Hz','Stop frequency Hz'),('points','Coarse log samples')]:
            fields.Add(wx.StaticText(setup,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(setup);control.Bind(wx.EVT_TEXT,self._changed);self.fields[key]=control;fields.Add(control,1,wx.EXPAND)
        form.Add(fields,0,wx.EXPAND|wx.ALL,8)
        self.caps=wx.grid.Grid(setup);self.caps.CreateGrid(1,5)
        for index,label in enumerate(('Capacitor / model','Effective C µF','ESR mΩ','Total ESL nH','Quantity')):
            self.caps.SetColLabelValue(index,label);self.caps.SetColSize(index,200 if index==0 else 150)
        self.caps.SetMinSize((-1,180));self.caps.Bind(wx.grid.EVT_GRID_CELL_CHANGED,self._changed);form.Add(self.caps,1,wx.EXPAND|wx.ALL,8)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        for title,handler in [('Add capacitor type',self._add),('Remove selected',self._remove),('Load model JSON…',self._load),('Save model JSON…',self._save)]:
            button=wx.Button(setup,label=title);button.Bind(wx.EVT_BUTTON,handler);actions.Add(button,0,wx.RIGHT,6)
        form.Add(actions,0,wx.ALL,8);setup.SetSizer(form);self.book.AddPage(setup,'1 · Target and bank')
        page=wx.Panel(self.book);plots=wx.BoxSizer(wx.VERTICAL);self.figure=Figure(figsize=(10,4));self.canvas=FigureCanvasWxAgg(page,wx.ID_ANY,self.figure)
        plots.Add(self.canvas,1,wx.EXPAND);toolbar=NavigationToolbar2WxAgg(self.canvas);toolbar.Realize();plots.Add(toolbar,0,wx.EXPAND)
        self.summary=wx.TextCtrl(page,style=wx.TE_MULTILINE|wx.TE_READONLY);self.summary.SetMinSize((-1,120));plots.Add(self.summary,0,wx.EXPAND|wx.ALL,6);page.SetSizer(plots)
        self.book.AddPage(page,'2 · Impedance and checks');root.Add(self.book,1,wx.EXPAND|wx.ALL,8)
        self.status=wx.StaticText(self,label='Illustrative model. Review every physical value before Calculate.');self.status.Wrap(1000);root.Add(self.status,0,wx.EXPAND|wx.ALL,8)
        buttons=wx.BoxSizer(wx.HORIZONTAL);run=wx.Button(self,label='Calculate impedance');run.Bind(wx.EVT_BUTTON,self._run)
        self.export=wx.Button(self,label='Export samples CSV…');self.export.Bind(wx.EVT_BUTTON,self._export);self.export.Disable()
        help_button=wx.Button(self,label='Methods / help');help_button.Bind(wx.EVT_BUTTON,self._help)
        close=wx.Button(self,wx.ID_CLOSE,'Close');close.Bind(wx.EVT_BUTTON,self._close)
        for control in (run,self.export,help_button,close):buttons.Add(control,0,wx.RIGHT,7)
        root.Add(buttons,0,wx.ALIGN_RIGHT|wx.ALL,8);self.SetSizer(root);self._populate(initial_model());self.Bind(wx.EVT_CLOSE,self._close)

    def _close(self,event=None):
        for controller in self._probes:controller['disconnect']()
        self._probes=[]
        if self.IsModal():self.EndModal(wx.ID_CLOSE)
        else:self.Destroy()

    def _help(self,event=None):
        from wayricad_runtime.help import open_help
        open_help(self,Path(__file__).with_name('help.html'))

    def _populate(self,model):
        model=validate(model);self._loading=True
        try:
            for key,control in self.fields.items():
                factor=1000 if key in ('source_resistance_ohm','allowed_ripple_V') else 1e9 if key=='source_inductance_H' else 1
                control.ChangeValue(str(model[key]*factor))
            if self.caps.GetNumberRows():self.caps.DeleteRows(0,self.caps.GetNumberRows())
            self.caps.AppendRows(len(model['capacitors']))
            for index,row in enumerate(model['capacitors']):
                for column,value in enumerate((row['name'],row['capacitance_F']*1e6,row['esr_ohm']*1000,row['esl_H']*1e9,row['quantity'])):self.caps.SetCellValue(index,column,str(value))
        finally:self._loading=False

    def _model(self):
        if self.caps.IsCellEditControlEnabled():self.caps.SaveEditControlValue();self.caps.DisableCellEditControl()
        model={key:float(control.GetValue()) for key,control in self.fields.items()}
        if any(not math.isfinite(value) for value in model.values()):raise ValueError('PDN inputs must be finite numbers.')
        if model['points']!=int(model['points']):raise ValueError('Log sample count must be an integer.')
        model['points']=int(model['points']);model['source_resistance_ohm']/=1000;model['source_inductance_H']/=1e9;model['allowed_ripple_V']/=1000
        model['capacitors']=[]
        for index in range(self.caps.GetNumberRows()):
            quantity=float(self.caps.GetCellValue(index,4))
            if not math.isfinite(quantity):raise ValueError('Capacitor quantity must be finite.')
            if quantity!=int(quantity):raise ValueError('Capacitor quantity must be a whole number.')
            model['capacitors'].append(dict(name=self.caps.GetCellValue(index,0),capacitance_F=float(self.caps.GetCellValue(index,1))*1e-6,
                esr_ohm=float(self.caps.GetCellValue(index,2))*1e-3,esl_H=float(self.caps.GetCellValue(index,3))*1e-9,quantity=int(quantity)))
        return validate(model)

    def _changed(self,event=None):
        if not self._loading:
            for controller in self._probes:controller['disconnect']()
            self._probes=[]
            self.result=None;self.export.Disable();self.figure.clear();self.canvas.draw_idle();self.summary.ChangeValue('')
            self.status.SetLabel('Model changed. Recalculate before using or exporting the curves.')
        if event:event.Skip()

    def _add(self,event=None):
        if self.caps.GetNumberRows()>=32:self.status.SetLabel('At most 32 capacitor types.');return
        self.caps.AppendRows();index=self.caps.GetNumberRows()-1
        for column,value in enumerate((f'Capacitor {index+1}','','','','1')):self.caps.SetCellValue(index,column,value)
        self._changed()

    def _remove(self,event=None):
        if self.caps.GetNumberRows()>1:self.caps.DeleteRows(max(0,self.caps.GetGridCursorRow()));self._changed()

    def _run(self,event=None):
        self._changed()
        try:result=analyze(self._model())
        except (ValueError,ArithmeticError,TypeError) as exc:self.status.SetLabel(str(exc));return
        self.result=result;self.figure.clear();left=self.figure.add_subplot(121);right=self.figure.add_subplot(122)
        rows=result['rows'];frequencies=[row['frequency_Hz'] for row in rows]
        left.loglog(frequencies,[float('nan') if row['impedance_ohm'] is None else row['impedance_ohm'] for row in rows],label='Explicit lumped bank')
        left.axhline(result['target_ohm'],color='#b94535',linestyle='--',label='ΔV / ΔI target');left.set_xlabel('Frequency Hz');left.set_ylabel('|Z| Ω');left.grid(True,which='both',alpha=.25);left.legend(fontsize=8)
        right.semilogx(frequencies,[float('nan') if row['phase_deg'] is None else row['phase_deg'] for row in rows]);right.set_xlabel('Frequency Hz');right.set_ylabel('Phase degrees');right.grid(True,alpha=.25)
        self.figure.tight_layout()
        from wayricad_runtime.plot_probe import attach_probes
        for axes,key,unit in ((left,'impedance_ohm','Ω'),(right,'phase_deg','degrees')):
            samples=[(row['frequency_Hz'],row[key],row[key],f"{row['frequency_Hz']:.7g} Hz") for row in rows if row[key] is not None]
            self._probes.append(attach_probes(self.canvas,axes,samples,unit=unit))
        self.canvas.draw_idle();self.export.Enable();self.book.SetSelection(1)
        peak=result['peak'];self.summary.ChangeValue(f"{result['status']}\nTarget {result['target_ohm']:.6g} Ω; sampled peak {peak['impedance_ohm']:.6g} Ω at {peak['frequency_Hz']:.6g} Hz.\n"
            f"{result['sample_count']} refined samples; peak change {100*result['refinement_relative_change']:.4g}%; effective bank C {result['effective_capacitance_F']*1e6:.6g} µF.\n"+'\n'.join(result['limitations']))
        self.status.SetLabel('Lumped screening complete. Sampled target checks do not establish real-board transient regulation.')

    def _load(self,event=None):
        with wx.FileDialog(self,'Load explicit PDN model',defaultDir=project_directory(self),wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        try:
            if path.stat().st_size>1024*1024:raise ValueError('PDN model exceeds 1 MiB.')
            def pairs(items):
                result={}
                for key,value in items:
                    if key in result:raise ValueError('Repeated PDN field: '+key)
                    result[key]=value
                return result
            self._populate(json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=pairs));self._input_path=path.resolve();self._changed()
        except (OSError,ValueError,TypeError,RecursionError) as exc:self.status.SetLabel(str(exc))

    def _save(self,event=None):
        try:model=self._model()
        except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc));return
        with wx.FileDialog(self,'Save explicit PDN model',defaultDir=project_directory(self),defaultFile='pdn-capacitor-bank.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        try:
            if path.suffix.lower()!='.json':raise ValueError('Choose a NEW .json file.')
            with path.open('x',encoding='utf-8') as stream:stream.write(json.dumps(model,indent=2,allow_nan=False)+'\n')
            self.status.SetLabel('Saved explicit model; existing files preserved.')
        except (OSError,ValueError) as exc:self.status.SetLabel(str(exc))

    def _export(self,event=None):
        if not self.result:return
        with wx.FileDialog(self,'Export sampled impedance',defaultFile='pdn-impedance.csv',wildcard='CSV (*.csv)|*.csv',style=wx.FD_SAVE) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath())
        try:
            if path.suffix.lower()!='.csv':raise ValueError('Choose a NEW .csv file.')
            with path.open('x',encoding='utf-8',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['frequency_Hz','impedance_ohm','phase_deg','target_ohm','model_status'])
                for row in self.result['rows']:writer.writerow([row['frequency_Hz'],row['impedance_ohm'],row['phase_deg'],self.result['target_ohm'],self.result['status']])
            self.status.SetLabel('Exported sampled lumped impedance; existing files preserved.')
        except (OSError,ValueError) as exc:self.status.SetLabel(str(exc))
